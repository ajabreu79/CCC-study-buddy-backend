from pydantic import BaseModel, validator, Field, EmailStr, field_validator  # type: ignore

from typing import Optional
from datetime import datetime
from enum import Enum
import re
from src.utils import is_valid_email


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


class AllowedUserModel(BaseModel):
    emails: str  # "user1@example.com, user2@example.com"
    access_level: int  # 9,5,1,0

    @validator("emails")
    def validate_emails(cls, v: str):
        email_list = [email.strip() for email in v.split(",") if email.strip()]
        if not email_list:
            raise ValueError("At least one email must be provided")
        for email in email_list:
            if not is_valid_email(email):
                raise ValueError(f"Invalid email format: {email}")
        return v

    @validator("access_level")
    def validate_access_level(cls, v: int):
        allowed_levels = [9, 5, 1, 0]
        if v not in allowed_levels:
            raise ValueError(
                f"Invalid access level: {v}. Allowed values are {allowed_levels}"
            )
        return v


class SetAccessLevelModel(BaseModel):
    new_access_level: int = Field(..., ge=0, le=9)
    email: EmailStr


class UserSignUpModel(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=64)
    first_name: str = Field(..., min_length=1, max_length=50, pattern=r"^[A-Za-z-]+$")
    last_name: str = Field(..., min_length=1, max_length=50, pattern=r"^[A-Za-z-]+$")

    @field_validator("password")
    def validate_password(cls, v):
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"[0-9]", v):
            raise ValueError("Password must contain at least one digit")
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', v):
            raise ValueError("Password must contain at least one special character")
        return v


class UserSignInModel(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=64)
