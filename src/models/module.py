from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator
from fastapi import Form


class CreateTrainingModuleRequest(BaseModel):
    title: str = Field(..., min_length=1, description="Title of the training module")
    system_prompt: str = Field(
        ..., min_length=1, description="System prompt for the training module"
    )
    criteria: Optional[List[str]] = Field(
        default=None, description="Criteria for the training module"
    )

    @field_validator("title", "system_prompt")
    @classmethod
    def validate_non_empty(cls, value, field):
        if not value.strip():
            raise ValueError(f"{field.name} cannot be empty")
        return value

    @field_validator("criteria")
    @classmethod
    def validate_non_empty_list(cls, value):
        if value and not all(item.strip() for item in value):
            raise ValueError("All items in criteria must be non-empty strings")
        return value

    @classmethod
    def as_form(
        cls,
        title: str = Form(...),
        system_prompt: str = Form(...),
        criteria: Optional[List[str]] = Form(None),
    ):
        return cls(title=title, system_prompt=system_prompt, criteria=criteria)


class EditTrainingModuleRequest(BaseModel):
    title: Optional[str] = Field(
        None, min_length=1, description="Optional updated title"
    )
    system_prompt: Optional[str] = Field(
        None, min_length=1, description="Optional updated system prompt"
    )
    criteria: Optional[List[str]] = Field(
        None, min_length=1, description="Optional updated criteria"
    )
    keep_existing_pdf: bool = Field(
        False, description="Whether to keep existing PDF files"
    )

    @field_validator("title", "system_prompt")
    @classmethod
    def validate_non_empty(cls, value, field):
        if value is not None and not value.strip():
            raise ValueError(f"{field.name} cannot be empty if provided")
        return value

    @field_validator("criteria")
    @classmethod
    def validate_non_empty_list(cls, value):
        if value is not None and not all(item.strip() for item in value):
            raise ValueError("All items in criteria must be non-empty strings")
        return value

    @classmethod
    def as_form(
        cls,
        title: Optional[str] = Form(None),
        system_prompt: Optional[str] = Form(None),
        criteria: Optional[List[str]] = Form(None),
        keep_existing_pdf: bool = Form(False),
    ):
        return cls(
            title=title,
            system_prompt=system_prompt,
            criteria=criteria,
            keep_existing_pdf=keep_existing_pdf,
        )


class ModuleListResponse(BaseModel):
    modules: List[Dict[str, Any]]
    page: int
    page_size: int
    total_count: int


class ResourceListResponse(BaseModel):
    resources: List[Dict[str, Any]]
    module_id: str
    count: int


class ResourceUploadResponse(BaseModel):
    message: str
    resource_id: str
    file_url: str
    filename: str
    status: str
