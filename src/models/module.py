from typing import Optional
from pydantic import BaseModel, Field, field_validator


class CreateTrainingModuleRequest(BaseModel):
    title: str = Field(..., min_length=1, description="Title of the training module")
    system_prompt: str = Field(
        ..., min_length=1, description="System prompt for the training module"
    )


class EditTrainingModuleRequest(BaseModel):
    title: Optional[str] = Field(
        None, min_length=1, description="Optional updated title"
    )
    system_prompt: Optional[str] = Field(
        None, min_length=1, description="Optional updated system prompt"
    )

    @field_validator("title", "system_prompt")
    def validate_non_empty(cls, value, field):
        if value is not None and not value.strip():
            raise ValueError(f"{field.name} cannot be empty if provided")
        return value
