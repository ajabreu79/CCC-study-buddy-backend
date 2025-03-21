from typing import Optional
from pydantic import BaseModel, Field, field_validator


class CreateTrainingModuleRequest(BaseModel):
    title: str = Field(..., min_length=1, description="Title of the training module")
    system_prompt: str = Field(
        ..., min_length=1, description="System prompt for the training module"
    )
    passing_score: int = Field(
        ..., ge=0, le=100, description="Passing score for the training module"
    )


class EditTrainingModuleRequest(BaseModel):
    title: Optional[str] = Field(
        None, min_length=1, description="Optional updated title"
    )
    system_prompt: Optional[str] = Field(
        None, min_length=1, description="Optional updated system prompt"
    )
    passing_score: Optional[int] = Field(
        None, ge=0, le=100, description="Optional updated passing score"
    )

    @field_validator("title", "system_prompt")
    def validate_non_empty(cls, value, field):
        if value is not None and not value.strip():
            raise ValueError(f"{field.name} cannot be empty if provided")
        return value

    @field_validator("passing_score")
    def validate_passing_score(cls, value):
        if value is not None and not 0 <= value <= 100:
            raise ValueError("Passing score must be between 0 and 100")
        return value
