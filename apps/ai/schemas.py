"""Pydantic schemas bound to Gemini structured output.

Services bind these via with_structured_output(Schema, method="json_schema")
— Gemini's native responseSchema (the 4.x default; pinned explicitly).
The LLM returns skill *names*, never UUIDs — the service maps names to real
SkillSet rows and drops inventions.
"""
from typing import Literal

from pydantic import BaseModel, Field

SkillLevel = Literal['Beginner', 'Intermediate', 'Advanced', 'Expert']


class SuggestedSkillDraft(BaseModel):
    skill_name: str = Field(description="A skill name chosen from the provided taxonomy list.")
    skill_level: SkillLevel = Field(description="Required proficiency for this job.")
    is_required: bool = Field(description="True if must-have, False if nice-to-have.")


class JobPostDraft(BaseModel):
    job_title: str = Field(description="Concise job title, max ~120 characters.")
    job_description: str = Field(
        description="Full description including responsibilities and requirements prose.")
    suggested_skills: list[SuggestedSkillDraft] = Field(
        description="3-8 skills strictly from the provided taxonomy list.")


DegreeType = Literal[
    'High School', 'Associate', 'Bachelor', 'Master', 'PhD',
    'Certificate', 'Diploma',
]

# Date fields are plain str, NOT datetime.date: langchain-google-genai strips
# `format` from schemas before they reach Gemini, so the ISO rule must live in
# the description. Field names mirror the Django models so confirmed drafts
# POST straight to the existing seekers CRUD endpoints.


class EducationEntry(BaseModel):
    institute_university_name: str = Field(description="Institution name as written in the resume.")
    degree_type: DegreeType | None = Field(
        description="Closest matching degree type, or null if unclear.")
    field_of_study: str = Field(description="Major/field, empty string if absent.")
    academic_details: str = Field(description="Honors, thesis, or notes; empty string if absent.")
    percentage: float | None = Field(
        description="Grade as a 0-100 number ONLY if explicitly stated, else null.")
    start_date: str | None = Field(
        description="ISO date YYYY-MM-DD; year-only becomes YYYY-01-01; null if absent.")
    end_date: str | None = Field(
        description="ISO date YYYY-MM-DD; year-only becomes YYYY-01-01; null if absent or ongoing.")


class ExperienceEntry(BaseModel):
    company_name: str = Field(description="Employer name as written.")
    position: str = Field(description="Job title as written.")
    description: str = Field(description="Responsibilities/achievements; empty string if absent.")
    job_location_city: str = Field(description="City, empty string if absent.")
    job_location_country: str = Field(description="Country, empty string if absent.")
    start_date: str | None = Field(
        description="ISO date YYYY-MM-DD; year-only becomes YYYY-01-01; null if absent.")
    end_date: str | None = Field(
        description="ISO date YYYY-MM-DD; null if absent or current role.")


class ResumeSkill(BaseModel):
    skill_name: str = Field(description="One skill as named in the resume.")
    skill_level: SkillLevel = Field(
        description="Proficiency estimated from context; Intermediate when unclear.")


class ResumeExtract(BaseModel):
    education: list[EducationEntry] = Field(description="All education records found.")
    experience: list[ExperienceEntry] = Field(description="All work experience found.")
    skills: list[ResumeSkill] = Field(description="All identifiable skills.")


# Screening: the model never sees a UUID. Dossiers are labelled candidate_1..N
# and the model echoes the label back; the service maps labels to real rows and
# drops any label it did not issue.


class CandidateAssessment(BaseModel):
    candidate_ref: str = Field(
        description="The candidate label exactly as given in the prompt, e.g. candidate_3.")
    score: int = Field(
        description="Fit score for THIS job, 0-100. 80+ strong, 50-79 partial, below 50 weak.")
    strengths: list[str] = Field(
        description="2-4 short concrete strengths, each grounded in the dossier text.")
    gaps: list[str] = Field(
        description="1-4 short concrete gaps against the job's requirements.")
    summary: str = Field(description="Two-sentence hiring summary for this candidate.")


class ScreeningResult(BaseModel):
    candidates: list[CandidateAssessment] = Field(
        description="Exactly one entry per candidate label supplied in the prompt.")
