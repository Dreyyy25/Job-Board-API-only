"""Prompt templates for AI features — every prompt lives here."""

JOB_POST_WRITER_SYSTEM = (
    "You are a hiring copywriter for a job board. Given a company's rough notes, "
    "write a polished, honest job post draft. Fold any requirements into the "
    "job_description as a clearly formatted section — do not invent perks, salary "
    "figures, or qualifications the notes don't support. Suggest 3-8 relevant "
    "skills, choosing skill_name values ONLY from the provided taxonomy list, "
    "verbatim. If the taxonomy has no relevant skill, suggest fewer skills rather "
    "than inventing names."
)


def build_job_post_writer_prompt(
    *,
    notes: str,
    company_name: str,
    business_stream: str,
    job_type_name: str,
    location_hint: str,
    skill_names: list[str],
) -> list[tuple[str, str]]:
    """Return (role, content) message tuples for model.invoke()."""
    context_lines = [
        f"Company: {company_name} (industry: {business_stream})",
    ]
    if job_type_name:
        context_lines.append(f"Job type: {job_type_name}")
    if location_hint:
        context_lines.append(f"Location: {location_hint}")
    human = (
        "\n".join(context_lines)
        + "\n\nSkill taxonomy (choose skill_name values only from this list):\n"
        + ", ".join(skill_names)
        + "\n\nCompany's rough notes:\n"
        + notes
    )
    return [("system", JOB_POST_WRITER_SYSTEM), ("human", human)]
