"""Prompt templates for AI features — every prompt lives here."""

from langchain_core.messages import HumanMessage

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
        + (", ".join(skill_names) or "(none available — suggest no skills)")
        + "\n\nCompany's rough notes:\n"
        + notes
    )
    return [("system", JOB_POST_WRITER_SYSTEM), ("human", human)]


RESUME_IMPORT_SYSTEM = (
    "You are a resume parser for a job board. Extract the candidate's education, "
    "work experience, and skills EXACTLY as stated — never invent institutions, "
    "employers, dates, or numbers that are not in the resume. Dates are ISO "
    "YYYY-MM-DD; when only a year or month is given use the first day; use null "
    "when absent. Map degree names to the closest degree_type choice or null. "
    "Estimate skill_level from context, defaulting to Intermediate. percentage "
    "is a 0-100 grade figure — null unless explicitly stated."
)

_RESUME_INSTRUCTION = "Extract structured data from this resume."


def build_resume_import_messages(*, resume_text=None, pdf_b64=None):
    """Messages for resume extraction. Exactly one kwarg is non-None
    (enforced by the service; not re-validated here).

    PDF bytes travel as an inline base64 data content block (langchain-core's
    legacy source_type form, handled by is_data_content_block and converted
    to a Gemini inline_data Part; the v1 form uses a flat 'base64' key).
    """
    if pdf_b64 is not None:
        content = [
            {
                "type": "file",
                "source_type": "base64",
                "mime_type": "application/pdf",
                "data": pdf_b64,
            },
            {"type": "text", "text": _RESUME_INSTRUCTION},
        ]
    else:
        content = [
            {"type": "text", "text": f"{_RESUME_INSTRUCTION}\n\nResume:\n{resume_text}"},
        ]
    return [("system", RESUME_IMPORT_SYSTEM), HumanMessage(content=content)]
