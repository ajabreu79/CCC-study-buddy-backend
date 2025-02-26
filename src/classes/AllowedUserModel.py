from pydantic import BaseModel, validator

from src.Utils import is_valid_email


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
