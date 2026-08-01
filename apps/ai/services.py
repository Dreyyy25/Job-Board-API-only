"""Service layer for AI features. Views translate domain exceptions to HTTP."""
import base64
import logging
import time

from django.core.exceptions import ValidationError  # malformed UUID -> 404, not 500
from django.utils import timezone

from apps.companies.models import Company
from apps.jobs.models import JobPost, JobPostActivity
from apps.seekers.models import SkillSet

from .exceptions import (
    AIProviderError,
    AIQuotaExceededError,
    AIResponseInvalidError,
    CompanyProfileMissingError,
    InvalidResumeFileError,
    JobPostNotFoundError,
    NoApplicantsError,
    ScreeningPermissionError,
)
from .llm import get_model
from .models import AIUsageLog, ScreeningReport
from .prompts import (
    build_job_post_writer_prompt,
    build_resume_import_messages,
    build_screening_prompt,
)
from .schemas import JobPostDraft, ResumeExtract, ScreeningResult

logger = logging.getLogger('apps.ai')


def _classify_provider_error(exc):
    """Quota signals → AIQuotaExceededError; everything else → AIProviderError."""
    code = getattr(exc, 'code', None) or getattr(exc, 'status_code', None)
    text = str(exc)
    if code == 429 or 'RESOURCE_EXHAUSTED' in text or 'quota' in text.lower():
        return AIQuotaExceededError(text)
    return AIProviderError(text)


def _invoke_structured(model, schema, prompt, usage_sink):
    """One structured-output call with exactly one retry.

    Retries transient provider errors and parse failures; quota errors
    raise immediately (retrying spends more quota for nothing).

    Every attempt that returns a result object (including parse
    failures — the raw AIMessage still carries usage_metadata) appends
    {'usage': <usage_metadata dict>, 'latency_ms': <per-attempt int>} to
    usage_sink, so billable spend is recorded even when the call never
    yields a usable draft. Provider exceptions (no result object) append
    nothing — no tokens were confirmed spent.

    Returns the parsed instance.
    """
    structured = model.with_structured_output(
        schema, method='json_schema', include_raw=True)
    last_error = None
    for attempt in range(2):
        started = time.monotonic()
        try:
            result = structured.invoke(prompt)
        except Exception as exc:
            last_error = _classify_provider_error(exc)
            logger.warning('ai provider error attempt=%s cls=%s', attempt,
                           type(exc).__name__)
            if isinstance(last_error, AIQuotaExceededError):
                raise last_error
            continue
        latency_ms = int((time.monotonic() - started) * 1000)
        usage = getattr(result.get('raw'), 'usage_metadata', None) or {}
        usage_sink.append({'usage': usage, 'latency_ms': latency_ms})
        if result.get('parsed') is None:
            last_error = AIResponseInvalidError(str(result.get('parsing_error')))
            logger.warning('ai parse failure attempt=%s', attempt)
            continue
        return result['parsed']
    raise last_error


MAX_RESUME_BYTES = 5 * 1024 * 1024
MAX_SCREENED_APPLICANTS = 50
_COVER_LETTER_CHARS = 500
_EXPERIENCE_DESC_CHARS = 300
# Row caps per dossier section. Seekers create these rows through unrestricted
# viewsets, so without a cap one applicant could pad a dossier to megabytes of
# prompt text — billed to the company and able to blow the run's timeout.
MAX_DOSSIER_EDUCATION = 10
MAX_DOSSIER_EXPERIENCE = 15
MAX_DOSSIER_SKILLS = 30


def _fetch_applications(job_post):
    """Newest-first applications, capped, with every dossier relation preloaded.

    with_related() covers user_account/job_post/company only — the seeker
    relations must be prefetched explicitly or dossier assembly becomes an N+1.
    """
    return list(
        JobPostActivity.objects
        .filter(job_post=job_post)
        .with_related()
        .prefetch_related(
            'user_account__seeker_profile',
            'user_account__education',
            'user_account__experiences',
            'user_account__skills__skill_set',
        )
        .order_by('-application_date')[:MAX_SCREENED_APPLICANTS]
    )


def _seeker_name(user_account):
    """Full name, or '' when the seeker profile is missing.

    Django's reverse-one-to-one DoesNotExist subclasses AttributeError, so
    getattr's default fires instead of raising.
    """
    profile = getattr(user_account, 'seeker_profile', None)
    if profile is None:
        return ''
    return f"{profile.first_name} {profile.last_name}".strip()


def _date_span(start, end):
    if not start and not end:
        return ''
    return f"{start.isoformat() if start else '?'} to {end.isoformat() if end else 'present'}"


def _build_dossier(label, activity):
    """Compact plain-text dossier for one applicant.

    Never includes the applicant's email — name only, per the privacy rule.
    All related sets are read with .all() so the prefetch cache is used, and
    the per-section caps slice the materialized list — slicing the queryset
    instead would issue a fresh LIMIT query and reintroduce the N+1.
    """
    user = activity.user_account
    lines = [f"{label}:", f"Name: {_seeker_name(user) or 'Not provided'}"]

    skills = [f"{s.skill_set.skill_name} ({s.skill_level})"
              for s in list(user.skills.all())[:MAX_DOSSIER_SKILLS]]
    lines.append("Skills: " + (", ".join(skills) or "none listed"))

    for edu in list(user.education.all())[:MAX_DOSSIER_EDUCATION]:
        span = _date_span(edu.start_date, edu.end_date)
        lines.append(
            f"Education: {edu.degree_type or 'Unspecified'} in "
            f"{edu.field_of_study or 'unspecified field'} at "
            f"{edu.institute_university_name or 'unnamed institution'}"
            + (f" ({span})" if span else "")
        )

    for exp in list(user.experiences.all())[:MAX_DOSSIER_EXPERIENCE]:
        span = _date_span(exp.start_date, exp.end_date)
        description = exp.description[:_EXPERIENCE_DESC_CHARS]
        lines.append(
            f"Experience: {exp.position} at {exp.company_name}"
            + (f" ({span})" if span else "")
            + (f" - {description}" if description else "")
        )

    if activity.cover_letter:
        lines.append("Cover letter: " + activity.cover_letter[:_COVER_LETTER_CHARS])

    return "\n".join(lines)


def _record_usage(feature, user, model, usage_sink):
    """One AIUsageLog row per token-consuming attempt (see _invoke_structured)."""
    for entry in usage_sink:
        usage = entry['usage']
        AIUsageLog.objects.create(
            feature=feature,
            user=user,
            model=str(getattr(model, 'model', '')),
            input_tokens=usage.get('input_tokens', 0),
            output_tokens=usage.get('output_tokens', 0),
            latency_ms=entry['latency_ms'],
        )


def generate_job_post_draft(user, *, notes, job_type=None, location_hint='',
                            model=None):
    """Draft a job post from rough notes. Creates nothing but the usage log.

    Returns {'job_title', 'job_description', 'suggested_skills': [
        {'skill_set_id', 'skill_name', 'skill_level', 'is_required'}]}
    with skills mapped to real SkillSet rows; inventions dropped.
    """
    model = model or get_model('flash')
    try:
        company = user.company_profile
    except Company.DoesNotExist:
        raise CompanyProfileMissingError()
    skills = list(SkillSet.objects.order_by('skill_name'))
    prompt = build_job_post_writer_prompt(
        notes=notes,
        company_name=company.company_name,
        business_stream=company.business_stream.business_stream_name,
        job_type_name=job_type.job_type_name if job_type else '',
        location_hint=location_hint,
        skill_names=[s.skill_name for s in skills],
    )

    usage_sink = []
    try:
        draft = _invoke_structured(model, JobPostDraft, prompt, usage_sink)
    finally:
        # One row per attempt that returned a result object — including
        # parse failures — so billable spend is never silently dropped.
        _record_usage(AIUsageLog.Feature.JOB_POST_WRITER, user, model, usage_sink)

    by_name = {s.skill_name.lower(): s for s in skills}
    suggested = []
    for item in draft.suggested_skills:
        skill = by_name.get(item.skill_name.strip().lower())
        if skill is None:
            continue  # invented by the model
        suggested.append({
            'skill_set_id': str(skill.id),
            'skill_name': skill.skill_name,
            'skill_level': item.skill_level,
            'is_required': item.is_required,
        })

    return {
        'job_title': draft.job_title,
        'job_description': draft.job_description,
        'suggested_skills': suggested,
    }


def extract_resume(user, *, text='', file=None, model=None):
    """Extract structured education/experience/skills from a resume.

    Draft-only: persists nothing but usage logs. Returns
    {'education': [...], 'experience': [...],
     'skills': [{'skill_set_id', 'skill_name', 'skill_level'}],
     'new_skill_suggestions': [str]} — entry keys mirror the
    EducationData/ExperienceData models; known skills map to real SkillSet
    rows, unknown ones surface as suggestions instead of being dropped.
    """
    text = (text or '').strip()
    if bool(text) == bool(file):
        raise InvalidResumeFileError('Provide exactly one of text or file.')

    pdf_b64 = None
    if file is not None:
        if file.size > MAX_RESUME_BYTES:
            raise InvalidResumeFileError('PDF must be 5 MB or smaller.')
        header = file.read(5)
        file.seek(0)
        if header != b'%PDF-':
            raise InvalidResumeFileError('File is not a readable PDF.')
        pdf_b64 = base64.b64encode(file.read()).decode('ascii')

    model = model or get_model('flash')
    prompt = build_resume_import_messages(
        resume_text=text or None, pdf_b64=pdf_b64)

    usage_sink = []
    try:
        extract = _invoke_structured(model, ResumeExtract, prompt, usage_sink)
    finally:
        _record_usage(AIUsageLog.Feature.RESUME_IMPORT, user, model, usage_sink)

    by_name = {s.skill_name.lower(): s for s in SkillSet.objects.all()}
    skills, suggestions, seen, seen_suggestions = [], [], set(), set()
    for item in extract.skills:
        name = item.skill_name.strip()
        if not name:
            continue
        skill = by_name.get(name.lower())
        if skill is not None:
            if str(skill.id) in seen:
                continue
            seen.add(str(skill.id))
            skills.append({
                'skill_set_id': str(skill.id),
                'skill_name': skill.skill_name,
                'skill_level': item.skill_level,
            })
        elif name.lower() not in seen_suggestions:
            seen_suggestions.add(name.lower())
            suggestions.append(name)

    education = []
    for entry in extract.education:
        dumped = entry.model_dump()
        # The model's EducationData serializer declares degree_type with
        # blank=True (not null=True) — None fails validation, so coerce the
        # LLM's "null if unclear" to the model's own absent representation
        # before the confirmed draft is POSTed straight to that endpoint.
        if dumped.get('degree_type') is None:
            dumped['degree_type'] = ''
        education.append(dumped)

    return {
        'education': education,
        'experience': [e.model_dump() for e in extract.experience],
        'skills': skills,
        'new_skill_suggestions': suggestions,
    }


def _has_newer_application(job_post, since):
    """Staleness rule: any application newer than the report.

    Deliberately a timestamp comparison, not a count — withdraw-plus-reapply
    leaves the count unchanged and would keep serving a stale report.
    """
    return JobPostActivity.objects.filter(
        job_post=job_post, application_date__gt=since).exists()


def _screening_response(job_post, report, *, cached):
    payload = report.report or {}
    return {
        'job_post_id': str(job_post.id),
        'applicant_count': report.applicant_count,
        'truncated': payload.get('truncated', False),
        'excluded_count': payload.get('excluded_count', 0),
        'generated_at': report.created_at.isoformat(),
        'cached': cached,
        'candidates': payload.get('candidates', []),
    }


def screen_applicants(user, *, job_post_id, refresh=False, model=None):
    """Score and rank a job post's applicants, caching the run.

    Returns the shape documented on the endpoint. Creates nothing but a
    ScreeningReport and its usage log — applications are never mutated.
    """
    try:
        job_post = (JobPost.objects
                    .select_related('company')
                    .prefetch_related('required_skills__skill_set')
                    .get(id=job_post_id))
    except (JobPost.DoesNotExist, ValidationError, ValueError):
        raise JobPostNotFoundError()

    if not (user.is_staff or user.is_superuser):
        if job_post.company.user_account_id != user.id:
            raise ScreeningPermissionError()

    # The report is stamped with the run's start, not its write time: the LLM
    # call can take the better part of a minute, and an application arriving in
    # that window is absent from the report. Stamping it later would judge that
    # application "not newer" forever. Conservative (one extra run at the
    # boundary) beats leaky (the applicant is never screened).
    run_started = timezone.now()

    # Count first, cache second: an emptied pool must 409 rather than replay a
    # report about applications that no longer exist — the one extra COUNT on
    # the cache-hit path is the price.
    total_applicants = JobPostActivity.objects.filter(job_post=job_post).count()
    if total_applicants == 0:
        raise NoApplicantsError()

    latest = (ScreeningReport.objects
              .filter(job_post=job_post).order_by('-created_at').first())
    if latest is not None and not refresh and not _has_newer_application(
            job_post, latest.created_at):
        return _screening_response(job_post, latest, cached=True)

    applications = _fetch_applications(job_post)
    labels = {f"candidate_{i}": activity
              for i, activity in enumerate(applications, start=1)}

    prompt = build_screening_prompt(
        job_title=job_post.job_title,
        job_description=job_post.job_description,
        required_skills=[
            f"{s.skill_set.skill_name} ({s.skill_level}, "
            f"{'required' if s.is_required else 'nice-to-have'})"
            for s in job_post.required_skills.all()
        ],
        dossiers=[_build_dossier(label, activity)
                  for label, activity in labels.items()],
    )

    model = model or get_model('pro')
    usage_sink = []
    try:
        result = _invoke_structured(model, ScreeningResult, prompt, usage_sink)
    finally:
        _record_usage(AIUsageLog.Feature.SCREENING, user, model, usage_sink)

    candidates, seen = [], set()
    for item in result.candidates:
        activity = labels.get(item.candidate_ref.strip())
        if activity is None or activity.id in seen:
            continue  # label the service never issued, or a duplicate
        seen.add(activity.id)
        candidates.append({
            'application_id': str(activity.id),
            'applicant_id': str(activity.user_account_id),
            'applicant_name': _seeker_name(activity.user_account),
            'score': max(0, min(100, item.score)),
            'strengths': list(item.strengths),
            'gaps': list(item.gaps),
            'summary': item.summary,
        })

    # Deterministic ranking — no second LLM call. Name then id break ties so
    # the same inputs always produce the same order.
    candidates.sort(key=lambda c: (-c['score'], c['applicant_name'], c['application_id']))
    for rank, candidate in enumerate(candidates, start=1):
        candidate['rank'] = rank

    logger.info('ai screening job_post=%s screened=%s returned=%s',
                job_post.id, len(applications), len(candidates))

    report = ScreeningReport.objects.create(
        job_post=job_post,
        report={
            'candidates': candidates,
            'truncated': total_applicants > MAX_SCREENED_APPLICANTS,
            # max(0, ...): an application landing between the COUNT and the
            # fetch makes len(applications) the larger of the two.
            'excluded_count': max(0, total_applicants - len(applications)),
        },
        applicant_count=len(applications),
        created_at=run_started,
    )
    return _screening_response(job_post, report, cached=False)
