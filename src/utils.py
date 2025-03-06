import re
import uuid
import bcrypt  # type: ignore
import jwt  # type: ignore
import os
import datetime
from src.constants import USER_ID, ACCESS_LEVEL, EXP, USER
from fastapi import HTTPException, status, Request, Depends
from Cryptodome.Cipher import AES
import base64


def is_valid_email(email: str) -> bool:
    email_regex = r"(^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$)"
    return re.match(email_regex, email) is not None


def generate_uuid() -> str:
    return str(uuid.uuid4())


def encrypt_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def create_token(user_id: str, access_level: int) -> str:

    return jwt.encode(
        {
            USER_ID: user_id,
            ACCESS_LEVEL: access_level,
            EXP: datetime.datetime.utcnow() + datetime.timedelta(days=3),
        },
        os.getenv("JWT_SECRET_KEY"),
        algorithm="HS256",
    )


def verify_pwd(pwd: str, hashed_pwd) -> bool:
    if isinstance(hashed_pwd, str):
        hashed_pwd = hashed_pwd.encode("utf-8")
    return bcrypt.checkpw(pwd.encode("utf-8"), hashed_pwd)


def get_current_user(request: Request):
    """
    Retrieves the current authenticated user from the request state.
    Raises an HTTP 401 error if the user is not authenticated.
    """
    user = getattr(request.state, USER, None)
    if user is None:
        raise HTTPException(status_code=401, detail="User not authenticated")
    return user


def require_access_level(min_level: int):
    """
    Dependency that checks if the current user's ACCESS_LEVEL >= min_level.
    Raises a 403 error if not.
    """

    def dependency(user: dict = Depends(get_current_user)):
        user_level = user.get(ACCESS_LEVEL, 0)
        if user_level < min_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions.",
            )
        return user

    return dependency
