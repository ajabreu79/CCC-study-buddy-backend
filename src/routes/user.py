from fastapi import APIRouter, HTTPException, Body, Depends, Request
import datetime

from src.models.user import (
    AllowedUserModel,
    SetAccessLevelModel,
    UserSignUpModel,
    UserSignInModel,
)
from src.utils import (
    generate_user_id,
    encrypt_password,
    create_token,
    verify_pwd,
)
from src.constants import (
    USERS,
    ALLOWED_USERS,
    EMAIL,
    ACCESS_LEVEL,
    FIRST_NAME,
    LAST_NAME,
    USER_ID,
    HASHED_PW,
    WORKSPACE_ID,
    IS_DELETED,
    ALL,
    DELETED,
    ACTIVE,
    USER,
    ADDED_AT,
    ADDED_BY,
)

from firebase_config import db

router = APIRouter()


def get_current_user(request: Request):
    """
    Retrieves the current authenticated user from the request state.
    Raises an HTTP 401 error if the user is not authenticated.
    """
    user = getattr(request.state, USER, None)
    if user is None:
        raise HTTPException(status_code=401, detail="User not authenticated")
    return user


# -----------------------------------
# User Signup and Signin Endpoints
# -----------------------------------


@router.post("/signup")
def sign_up(payload: UserSignUpModel = Body(...)):
    """
    Sign up a new user.
    - If no allowed user document exists and the user database is empty, assign Super Admin (access level 9).
    - Otherwise, verify the user is allowed to sign up.
    """
    allowed_user_doc = db.collection(ALLOWED_USERS).document(payload.email).get()
    existing_users = list(db.collection(USERS).limit(1).get())

    if not allowed_user_doc.exists and not existing_users:
        access_level = 9
        message = "Sign-up successful as Super Admin"
    else:
        if not allowed_user_doc.exists:
            raise HTTPException(status_code=403, detail="User not allowed to sign up")
        access_level = allowed_user_doc.to_dict().get(ACCESS_LEVEL)
        message = "Sign-up successful"

    hashed_pw = encrypt_password(payload.password)
    user_id = generate_user_id()

    user_data = {
        USER_ID: user_id,
        FIRST_NAME: payload.first_name,
        LAST_NAME: payload.last_name,
        EMAIL: payload.email,
        HASHED_PW: hashed_pw.encode("utf-8"),
        ACCESS_LEVEL: access_level,
        WORKSPACE_ID: 0,
        IS_DELETED: None,
    }

    db.collection(USERS).document(payload.email).set(user_data)

    token = create_token(user_data[USER_ID], user_data[ACCESS_LEVEL])

    return {"message": message, "token": token}


@router.post("/signin")
def sign_in(payload: UserSignInModel = Body(...)):
    """
    Sign in an existing user by verifying email and password.
    Returns a token if the credentials are valid.
    """
    user_ref = db.collection(USERS).where(EMAIL, "==", payload.email).limit(1).get()
    if not user_ref:
        raise HTTPException(status_code=401, detail="Invalid email")

    user = user_ref[0].to_dict()
    if not verify_pwd(payload.password, user[HASHED_PW]):
        raise HTTPException(status_code=401, detail="Invalid password")

    token = create_token(user[USER_ID], user[ACCESS_LEVEL])
    return {"message": "Sign-in successful", "token": token}


# -----------------------------------
# Allowed Users and Access Control
# -----------------------------------


@router.post("/allowed-users")
async def allowed_users(
    payload: AllowedUserModel = Body(...), current_user=Depends(get_current_user)
):
    """
    Add a list of allowed users to the Firestore collection 'allowed_users'.
    The payload should contain a comma-separated list of emails and an access level.
    Only users with access level 9 are permitted to add allowed users.
    """
    if current_user[ACCESS_LEVEL] != 9:
        raise HTTPException(
            status_code=403, detail="Insufficient privileges to add users"
        )

    email_list = [email.strip() for email in payload.emails.split(",") if email.strip()]
    batch = db.batch()

    for email in email_list:
        allowed_user_data = {
            EMAIL: email,
            ACCESS_LEVEL: payload.access_level,
            ADDED_BY: current_user[USER_ID],
            ADDED_AT: datetime.datetime.utcnow(),
        }
        doc_ref = db.collection(ALLOWED_USERS).document(email)
        batch.set(doc_ref, allowed_user_data)

    batch.commit()
    return {"message": f"Invitations sent to {len(email_list)} user(s)"}


@router.post("/set-access-level")
def set_access_level(
    payload: SetAccessLevelModel,
    current_user: dict = Depends(get_current_user),
):
    """
    Modify a user's access level.
    - The requesting user must have a higher or equal access level.
    - Users can only be upgraded to a level that does not exceed the requester's level.
    """
    requester_access_level = current_user.get(ACCESS_LEVEL, 0)
    user_ref = db.collection(USERS).where(EMAIL, "==", payload.email).get()

    if not user_ref:
        raise HTTPException(status_code=404, detail="User not found")

    user_document = user_ref[0]
    user_data = user_document.to_dict()
    user_current_access_level = user_data.get(ACCESS_LEVEL)

    if int(requester_access_level) < int(user_current_access_level):
        raise HTTPException(
            status_code=403,
            detail="You cannot modify the access level of a user with a higher access level than yours.",
        )

    if int(requester_access_level) < int(payload.new_access_level):
        raise HTTPException(
            status_code=403, detail="Cannot assign access level higher than your own"
        )

    # Update access level in both the users and allowed users collections.
    db.collection(USERS).document(payload.email).update(
        {ACCESS_LEVEL: payload.new_access_level}
    )
    db.collection(ALLOWED_USERS).document(payload.email).update(
        {ACCESS_LEVEL: payload.new_access_level}
    )

    return {
        "message": f"Updated access level for {payload.email} to {payload.new_access_level}"
    }


# -----------------------------------
# User Listing and Deletion
# -----------------------------------


@router.get("/")
def list_users(filter_type: str = ALL):
    """
    List users with an optional filter:
    - 'deleted': Only deleted users.
    - 'active': Only active (non-deleted) users.
    - 'all' (default): Both deleted and active users.
    """
    if filter_type == DELETED:
        users_ref = db.collection(USERS).where(IS_DELETED, "!=", None).stream()
        users = [
            {
                FIRST_NAME: user.to_dict()[FIRST_NAME],
                LAST_NAME: user.to_dict()[LAST_NAME],
                EMAIL: user.to_dict()[EMAIL],
                ACCESS_LEVEL: user.to_dict()[ACCESS_LEVEL],
            }
            for user in users_ref
        ]
        return users

    elif filter_type == ACTIVE:
        users_ref = db.collection(USERS).where(IS_DELETED, "==", None).stream()
        users = [
            {
                FIRST_NAME: user.to_dict()[FIRST_NAME],
                LAST_NAME: user.to_dict()[LAST_NAME],
                EMAIL: user.to_dict()[EMAIL],
                ACCESS_LEVEL: user.to_dict()[ACCESS_LEVEL],
            }
            for user in users_ref
        ]
        return users

    else:  # ALL users
        deleted_users_ref = db.collection(USERS).where(IS_DELETED, "!=", None).stream()
        deleted_users = [
            {
                FIRST_NAME: user.to_dict()[FIRST_NAME],
                LAST_NAME: user.to_dict()[LAST_NAME],
                EMAIL: user.to_dict()[EMAIL],
                ACCESS_LEVEL: user.to_dict()[ACCESS_LEVEL],
            }
            for user in deleted_users_ref
        ]

        non_deleted_users_ref = (
            db.collection(USERS).where(IS_DELETED, "==", None).stream()
        )
        non_deleted_users = [
            {
                FIRST_NAME: user.to_dict()[FIRST_NAME],
                LAST_NAME: user.to_dict()[LAST_NAME],
                EMAIL: user.to_dict()[EMAIL],
                ACCESS_LEVEL: user.to_dict()[ACCESS_LEVEL],
            }
            for user in non_deleted_users_ref
        ]

        return deleted_users + non_deleted_users


@router.delete("/{user_id}")
def delete_user(user_id: str, request: Request):
    """
    Soft delete a user by setting the 'isDeleted' field to the current timestamp.
    The user_id is provided as a path parameter.
    """
    user_query = db.collection(USERS).where(USER_ID, "==", user_id).limit(1)
    user_docs = user_query.get()

    if not user_docs:
        raise HTTPException(status_code=404, detail="User not found")

    doc_snapshot = user_docs[0]
    doc_ref = doc_snapshot.reference
    doc_ref.update({IS_DELETED: datetime.datetime.utcnow()})

    return {"message": f"User {user_id} has been soft deleted."}
