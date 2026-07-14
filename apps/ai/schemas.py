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
