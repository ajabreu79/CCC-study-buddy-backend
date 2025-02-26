# src/models/UserModel.py

from pydantic import BaseModel, validator, Field
from typing import Optional
from datetime import datetime

from src.Utils import is_valid_email


class UserModel(BaseModel):
    user_id: str = Field(..., description="Unique identifier for the user")
    first_name: str = Field(..., description="User's first name")
    last_name: str = Field(..., description="User's last name")
    email: str = Field(..., description="User's email address")
    access_level: int = Field(
        ...,
        description="Access level (9 = admin, 5 = manager, 1 = trainee, 0 = deleted)",
    )
    isDeleted: Optional[datetime] = Field(
        None, description="Timestamp for soft deletion; None means active"
    )
    workspace_id: int = Field(0, description="Workspace ID (default is 0)")

    @validator("user_id")
    def validate_user_id(cls, v: str):
        if not v.strip():
            raise ValueError("user_id must be provided and non-empty")
        return v.strip()

    @validator("first_name", "last_name", pre=True, always=True)
    def trim_names(cls, v: str):
        if isinstance(v, str):
            return v.strip()
        return v

    @validator("email")
    def validate_email(cls, v: str):
        v = v.strip()
        if not is_valid_email(v):
            raise ValueError(f"Invalid email format: {v}")
        return v

    @validator("access_level")
    def validate_access_level(cls, v: int):
        allowed_levels = [9, 5, 1, 0]
        if v not in allowed_levels:
            raise ValueError(
                f"Invalid access level: {v}. Allowed values are {allowed_levels}"
            )
        return v
