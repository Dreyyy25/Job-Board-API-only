"""Read-only agent tools, bound to one user by closure.

SECURITY: no tool takes a user identifier. The requesting user is captured in
the closure, so an instruction injected into any text the model reads — a
company-authored job description, for instance — cannot redirect a tool at
another person's data. Every tool is read-only; the agent has no write path.

Tool output is model input, and model input is billed, so every string
returned here is length-capped.
"""

from django.core.exceptions import ValidationError

from apps.jobs.models import JobPost
from apps.seekers.models import SeekerSkillSet

MAX_SEARCH_RESULTS = 5
MAX_TOOL_DESCRIPTION_CHARS = 800
MAX_PROFILE_ROWS = 15
# A company can attach one JobPostSkillSet row per catalog SkillSet to a single
# post — JobPostSkillSetViewSet is a plain ModelViewSet with only a
# unique_together constraint, no per-job count cap — so an uncapped skills read
# is a company-controlled cost amplifier on billed tool output, same risk class
# as the Phase 3 screening dossier's per-applicant skill cap.
MAX_JOB_SKILLS = 30
NOT_FOUND = "Job not found, or it is not currently published."


def _published():
    return JobPost.objects.published().with_related()


def _get_published_job(job_post_id):
    """None instead of an exception: the model invents ids, and a ValueError
    escaping a tool would surface as a 500 on a perfectly ordinary turn."""
    try:
        return _published().get(id=job_post_id)
    except (JobPost.DoesNotExist, ValidationError, ValueError, TypeError):
        return None


def _job_line(job):
    location = job.job_location
    where = ", ".join(p for p in [location.city, location.country] if p) if location else ""
    return (
        f"- id={job.id} | {job.job_title} at {job.company.company_name}"
        + (f" | {where}" if where else "")
        + (f" | {job.job_type.job_type_name}" if job.job_type_id else "")
    )


def build_tools(user):
    """Four read-only tools bound to `user`. Order is part of the contract."""
    from langchain_core.tools import tool

    @tool
    def search_jobs(keywords: str = "", city: str = "", country: str = "") -> str:
        """Search currently published job posts. Use empty strings to skip a filter.

        Returns up to five matches, each with an id usable by get_job_details.
        """
        qs = _published()
        if keywords:
            qs = qs.filter(job_title__icontains=keywords)
        if city:
            qs = qs.filter(job_location__city__icontains=city)
        if country:
            qs = qs.filter(job_location__country__icontains=country)
        jobs = list(qs.order_by('-created_at')[:MAX_SEARCH_RESULTS])
        if not jobs:
            return "No matching published jobs found."
        return "\n".join(_job_line(j) for j in jobs)

    @tool
    def get_job_details(job_post_id: str) -> str:
        """Full details for one published job post, given its id."""
        job = _get_published_job(job_post_id)
        if job is None:
            return NOT_FOUND
        skills = (
            ", ".join(
                f"{s.skill_set.skill_name} ({s.skill_level}, {'required' if s.is_required else 'nice-to-have'})"
                for s in job.required_skills.all()[:MAX_JOB_SKILLS]
            )
            or "none listed"
        )
        salary = ""
        if job.salary_min or job.salary_max:
            salary = f"\nSalary: {job.salary_min or '?'} - {job.salary_max or '?'}"
        # job_description_hidden is the company's private notes — never exposed.
        return (
            f"Title: {job.job_title}\n"
            f"Company: {job.company.company_name}\n"
            f"Required skills: {skills}"
            f"{salary}\n"
            f"Description: {job.job_description[:MAX_TOOL_DESCRIPTION_CHARS]}"
        )

    @tool
    def get_my_profile() -> str:
        """The requesting job seeker's own profile, skills, education and experience."""
        profile = getattr(user, 'seeker_profile', None)
        name = f"{profile.first_name} {profile.last_name}".strip() if profile is not None else ""
        lines = [f"Name: {name or 'Not provided'}"]
        if profile is not None and profile.goals:
            lines.append(f"Goals: {profile.goals[:MAX_TOOL_DESCRIPTION_CHARS]}")
        # for_user(...).with_related() select_relates skill_set — reading
        # s.skill_set off a bare reverse FK would be one query per skill.
        skills = [
            f"{s.skill_set.skill_name} ({s.skill_level})"
            for s in SeekerSkillSet.objects.for_user(user).with_related()[:MAX_PROFILE_ROWS]
        ]
        lines.append("Skills: " + (", ".join(skills) or "none listed"))
        for edu in user.education.all()[:MAX_PROFILE_ROWS]:
            lines.append(
                f"Education: {edu.degree_type or 'Unspecified'} in "
                f"{edu.field_of_study or 'unspecified field'} at "
                f"{edu.institute_university_name or 'unnamed institution'}"
            )
        for exp in user.experiences.all()[:MAX_PROFILE_ROWS]:
            lines.append(f"Experience: {exp.position} at {exp.company_name}")
        # The user's email is deliberately absent — same privacy rule as dossiers.
        return "\n".join(lines)

    @tool
    def compare_fit(job_post_id: str) -> str:
        """Compare the requesting seeker's skills against one job's requirements.

        The overlap is computed exactly; narrate this result rather than
        estimating fit yourself.
        """
        job = _get_published_job(job_post_id)
        if job is None:
            return NOT_FOUND
        # Same MAX_JOB_SKILLS cap as get_job_details — a company-controlled
        # skill count must not translate into unbounded billed tool output.
        required = {s.skill_set.skill_name for s in job.required_skills.all()[:MAX_JOB_SKILLS]}
        mine = {s.skill_set.skill_name for s in SeekerSkillSet.objects.for_user(user).with_related()}
        matched = sorted(required & mine)
        missing = sorted(required - mine)
        return (
            f"Job: {job.job_title}\n"
            f"Matched {len(matched)} of {len(required)} listed skills.\n"
            f"Matched: {', '.join(matched) or 'none'}\n"
            f"Missing: {', '.join(missing) or 'none'}"
        )

    return [search_jobs, get_job_details, get_my_profile, compare_fit]
