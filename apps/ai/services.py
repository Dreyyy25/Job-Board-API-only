"""Service layer for AI features. Views translate domain exceptions to HTTP."""
import base64
import logging
import time

from apps.companies.models import Company
from apps.seekers.models import SkillSet

from .exceptions import (
    AIProviderError,
    AIQuotaExceededError,
    AIResponseInvalidError,
    CompanyProfileMissingError,
    InvalidResumeFileError,
)
from .llm import get_model
from .models import AIUsageLog
from .prompts import build_job_post_writer_prompt, build_resume_import_messages
from .schemas import JobPostDraft, ResumeExtract

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
    skills, suggestions, seen = [], [], set()
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
        elif name.lower() not in {s.lower() for s in suggestions}:
            suggestions.append(name)

    return {
        'education': [e.model_dump() for e in extract.education],
        'experience': [e.model_dump() for e in extract.experience],
        'skills': skills,
        'new_skill_suggestions': suggestions,
    }
