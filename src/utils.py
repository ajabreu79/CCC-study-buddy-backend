import re
import uuid
import bcrypt  # type: ignore
import jwt  # type: ignore
import os
import datetime
from src.constants import USER_ID, ACCESS_LEVEL, EXP, USER, TOKEN, SESSIONS, CREATED_AT
from fastapi import HTTPException, status, Request, Depends

from firebase_config import db


def is_valid_email(email: str) -> bool:
    email_regex = r"(^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$)"
    return re.match(email_regex, email) is not None


def generate_uuid() -> str:
    return str(uuid.uuid4())


def encrypt_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def create_token(user_id: str, name: str, access_level: int) -> str:

    return jwt.encode(
        {
            USER_ID: user_id,
            ACCESS_LEVEL: access_level,
            USER: name,
            EXP: datetime.datetime.utcnow() + datetime.timedelta(days=7),
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


def is_token_valid(session_data, token):
    """
    Check if the provided session_data has a valid token.

    Returns True if:
    - The stored token matches the provided token, and
    - The current time is before the token's expiration (EXP).
    """
    current_time = datetime.datetime.now(datetime.timezone.utc)

    return session_data.get(EXP) > current_time


def get_session(user_id, token):
    """
    Retrieve the session for the given user_id and check if the token is valid.

    Returns:
    - The session data if the token is valid.
    - None if no session exists or if the token has expired/doesn't match.
    """
    session_doc = db.collection(SESSIONS).document(user_id).get()

    if not session_doc.exists:
        return None

    session_data = session_doc.to_dict()
    if is_token_valid(session_data, token):
        return session_data

    db.collection(SESSIONS).document(user_id).delete()

    return None


def create_session(user_id, token):
    """
    Create a new session or return the existing session if a valid token is found.

    The session data includes:
    - user_id, creation timestamp (CREATED_AT)
    - expiration timestamp (EXP), set to 7 days from creation
    - the token (TOKEN)

    If a session already exists and the token is still valid (i.e. within 7 days),
    the stored session data is returned.
    """
    session_data = get_session(user_id, token)

    if session_data:
        return session_data

    current_time = datetime.datetime.utcnow()

    # Either no session exists or the token is expired/invalid, so create a new session.
    new_session_data = {
        CREATED_AT: current_time,
        EXP: current_time + datetime.timedelta(days=7),
        TOKEN: token,
    }

    db.collection(SESSIONS).document(user_id).set(new_session_data)
    return new_session_data
