import re
import uuid
import bcrypt  # type: ignore
import jwt  # type: ignore
import os
import datetime
from src.constants import USER_ID, ACCESS_LEVEL, EXP


def is_valid_email(email: str) -> bool:
    email_regex = r"(^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$)"
    return re.match(email_regex, email) is not None


def generate_user_id() -> str:
    return str(uuid.uuid4())


def encrypt_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def create_token(user_id: str, access_level: int) -> str:

    return jwt.encode(
        {
            USER_ID: user_id,
            ACCESS_LEVEL: access_level,
            EXP: datetime.datetime.utcnow() + datetime.timedelta(days=1),
        },
        os.getenv("JWT_SECRET_KEY"),
        algorithm="HS256",
    )


def verify_pwd(pwd: str, hashed_pwd: str) -> bool:
    return bcrypt.checkpw(pwd.encode("utf-8"), hashed_pwd.encode("utf-8"))
