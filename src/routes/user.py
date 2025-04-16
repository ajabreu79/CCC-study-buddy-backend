from fastapi import APIRouter, HTTPException, Body, Depends, Request, status
import datetime
from google.cloud.firestore_v1.base_query import FieldFilter

from src.models.user import (
    AllowedUserModel,
    SetAccessLevelModel,
    UserSignUpModel,
    UserSignInModel,
)
from src.utils import (
    generate_uuid,
    encrypt_password,
    create_token,
    verify_pwd,
    get_current_user,
    require_access_level,
    create_session,
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
    CREATED_AT,
    CREATED_BY,
    MODIFIED_AT,
    MODIFIED_BY,
    DELETED_LEVEL,
    USER_LEVEL,
    ACCESS_LEVEL,
    ALLOWED_USERS,
    MANAGER_LEVEL,
    ADMIN_LEVEL,
    TOKEN,
    SESSIONS,
)

from firebase_config import db

router = APIRouter()


# -----------------------------------
# Sign up
# -----------------------------------


@router.post("/signup")
def sign_up(payload: UserSignUpModel = Body(...)):
    """
    Sign up a new user.
    - If the user database is empty, sign up the user as Super Admin (access level 9).
    - Otherwise, verify that the user is allowed to sign up by checking the allowed users collection.
    """
    user_snapshot = db.collection(USERS).document(payload.email).get()
    if user_snapshot.exists:
        message = "Email is already registered"
        raise HTTPException(status_code=400, detail="Email is already registered")

    users_snapshot = list(db.collection(USERS).limit(1).get())
    if not users_snapshot:
        access_level = 9
        message = "Sign-up successful as Super Admin"
    else:
        allowed_user_doc = db.collection(ALLOWED_USERS).document(payload.email).get()
        if not allowed_user_doc.exists:
            raise HTTPException(status_code=403, detail="User not allowed to sign up")
        access_level = allowed_user_doc.to_dict().get(ACCESS_LEVEL)
        message = "Sign-up successful"

    hashed_pw = encrypt_password(payload.password)
    user_id = generate_uuid()

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
    token = create_token(
        user_data[USER_ID],
        user_data[FIRST_NAME] + " " + user_data[LAST_NAME],
        user_data[ACCESS_LEVEL],
    )

    session_data = create_session(user_id, token)

    if not session_data:
        raise HTTPException(
            status_code=500, detail="Failed to create a session for the user"
        )

    return {"message": message, "token": session_data[TOKEN]}


# -----------------------------------
# Sign in
# -----------------------------------


@router.post("/signin")
def sign_in(payload: UserSignInModel = Body(...)):
    """
    Sign in an existing user by verifying email and password.
    Returns a token if the credentials are valid.
    """
    user_ref = (
        db.collection(USERS)
        .where(filter=FieldFilter(EMAIL, "==", payload.email))
        .where(filter=FieldFilter(ACCESS_LEVEL, ">", DELETED_LEVEL))
        .limit(1)
        .get()
    )
    if not user_ref:
        raise HTTPException(status_code=401, detail="Invalid email")

    user = user_ref[0].to_dict()
    if not verify_pwd(payload.password, user[HASHED_PW]):
        raise HTTPException(status_code=401, detail="Invalid password")

    token = create_token(
        user[USER_ID],
        user[FIRST_NAME] + " " + user[LAST_NAME],
        user[ACCESS_LEVEL],
    )

    session_data = create_session(user[USER_ID], token)

    if not session_data:
        raise HTTPException(
            status_code=500, detail="Failed to create a session for the user"
        )

    return {"message": "Sign-in successful", "token": session_data[TOKEN]}


@router.post("/logout", dependencies=[Depends(require_access_level(USER_LEVEL))])
def logout(
    current_user=Depends(get_current_user),
):
    """
    Logs out a user by deleting their session from the database.
    Expects an Authorization header with the JWT token.
    """
    user_id = current_user.get(USER_ID, 0)
    try:
        db.collection(SESSIONS).document(user_id).delete()
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to delete session")

    return {"message": "Logout successful"}


# -----------------------------------
# Add to Allowed Users
# -----------------------------------


@router.post(
    "/allowed-users", dependencies=[Depends(require_access_level(ADMIN_LEVEL))]
)
async def allowed_users(
    payload: AllowedUserModel = Body(...), current_user=Depends(get_current_user)
):
    """
    Add a list of allowed users to the Firestore collection 'allowed_users'.
    The payload should contain a comma-separated list of emails and an access level.
    Only users with access level 9 are permitted to add allowed users.
    """

    email_list = [email.strip() for email in payload.emails.split(",") if email.strip()]
    batch = db.batch()

    for email in email_list:
        allowed_user_data = {
            EMAIL: email,
            ACCESS_LEVEL: payload.access_level,
            CREATED_BY: current_user[USER_ID],
            CREATED_AT: datetime.datetime.utcnow(),
            MODIFIED_AT: None,
            MODIFIED_BY: None,
        }
        doc_ref = db.collection(ALLOWED_USERS).document(email)
        batch.set(doc_ref, allowed_user_data)

    batch.commit()
    return {"message": f"Users successfully added to allowed users list"}


# -----------------------------------
# List Allowed Users
# -----------------------------------


@router.get(
    "/allowed-users", dependencies=[Depends(require_access_level(MANAGER_LEVEL))]
)
def get_allowed_users(
    search: str = "",
    page: int = 1,
    page_size: int = 10,
    current_user=Depends(get_current_user),
):
    """
    List all allowed users with pagination and optional search.

    Managers and administrators can access this endpoint.

    Optional search:
    - search: A search term to filter allowed users by their email (prefix match).

    Pagination parameters:
    - page (default=1): The page number.
    - page_size (default=10): The number of allowed users per page.
    """
    if page < 1:
        raise HTTPException(
            status_code=400, detail="Page number must be greater than 0"
        )
    if page_size < 1:
        raise HTTPException(status_code=400, detail="Page size must be greater than 0")

    base_query = db.collection(ALLOWED_USERS)

    if search:
        base_query = base_query.order_by(EMAIL)
        base_query = base_query.start_at({EMAIL: search})
        base_query = base_query.end_at({EMAIL: search + "\uf8ff"})

    offset_val = (page - 1) * page_size
    query = base_query.offset(offset_val).limit(page_size)

    allowed_users = [
        {
            EMAIL: user.to_dict().get(EMAIL),
            ACCESS_LEVEL: user.to_dict().get(ACCESS_LEVEL),
            CREATED_AT: user.to_dict().get(CREATED_AT),
            CREATED_BY: user.to_dict().get(CREATED_BY),
            MODIFIED_AT: user.to_dict().get(MODIFIED_AT),
            MODIFIED_BY: user.to_dict().get(MODIFIED_BY),
        }
        for user in query.stream()
    ]

    return {
        "allowed_users": allowed_users,
        "page": page,
        "page_size": page_size,
        "total_count": len(allowed_users),
    }


# -----------------------------------
# Modify User Access Level
# -----------------------------------


@router.post(
    "/set-access-level", dependencies=[Depends(require_access_level(MANAGER_LEVEL))]
)
def set_access_level(
    payload: SetAccessLevelModel,
    current_user: dict = Depends(get_current_user),
):
    """
    Modify a user's access level.
    - The requesting user must have a higher or equal access level.
    - Users can only be upgraded to a level that does not exceed the requester's level.
    """
    requester_level = int(current_user.get(ACCESS_LEVEL, 0))
    user_query = (
        db.collection(USERS).where(filter=FieldFilter(EMAIL, "==", payload.email)).get()
    )

    if not user_query:
        raise HTTPException(status_code=404, detail="User not found")

    user_data = user_query[0].to_dict()
    user_level = int(user_data.get(ACCESS_LEVEL, 0))
    new_level = int(payload.new_access_level)

    if requester_level < user_level:
        raise HTTPException(
            status_code=403,
            detail="You cannot modify the access level of a user with a higher access level than yours.",
        )

    if requester_level < new_level:
        raise HTTPException(
            status_code=403, detail="Cannot assign access level higher than your own"
        )

    now = datetime.datetime.utcnow()
    update_data = {
        ACCESS_LEVEL: new_level,
        MODIFIED_AT: now,
        MODIFIED_BY: current_user[USER_ID],
    }

    # Using a batch update for both collections if available.
    batch = db.batch()
    user_doc_ref = db.collection(USERS).document(payload.email)
    allowed_doc_ref = db.collection(ALLOWED_USERS).document(payload.email)

    batch.update(user_doc_ref, update_data)
    batch.update(allowed_doc_ref, update_data)
    batch.commit()

    return {"message": f"Updated access level for {payload.email} to {new_level}"}


# -----------------------------------
# List Users
# -----------------------------------


@router.get("/list", dependencies=[Depends(require_access_level(USER_LEVEL))])
def list_users(
    filter_type: str = ALL, search: str = "", page: int = 1, page_size: int = 10
):
    """
    List users with optional filtering, multi‑field search, and pagination:
    - 'deleted': Only deleted users.
    - 'active': Only active (non‑deleted) users.
    - 'all' (default): Both deleted and active users.

    Optional search:
    - search: A search term to filter users by their email (prefix match).

    Pagination parameters:
    - page (default=1): The page number.
    - page_size (default=10): The number of users per page.
    """

    base_query = db.collection(USERS)

    if filter_type == DELETED:
        base_query = base_query.where(
            filter=FieldFilter(ACCESS_LEVEL, "==", DELETED_LEVEL)
        )
    elif filter_type == ACTIVE:
        base_query = base_query.where(
            filter=FieldFilter(ACCESS_LEVEL, ">", DELETED_LEVEL)
        )

    if search:
        base_query = base_query.order_by(EMAIL)
        base_query = base_query.start_at({EMAIL: search})
        base_query = base_query.end_at({EMAIL: search + "\uf8ff"})

    offset_val = (page - 1) * page_size
    query = base_query.offset(offset_val).limit(page_size)

    users = [
        {
            WORKSPACE_ID: user.to_dict()[WORKSPACE_ID],
            IS_DELETED: user.to_dict()[IS_DELETED],
            USER_ID: user.to_dict()[USER_ID],
            FIRST_NAME: user.to_dict()[FIRST_NAME],
            LAST_NAME: user.to_dict()[LAST_NAME],
            EMAIL: user.to_dict()[EMAIL],
            ACCESS_LEVEL: user.to_dict()[ACCESS_LEVEL],
        }
        for user in query.stream()
    ]

    return users


# -----------------------------------
# Delete User
# -----------------------------------


@router.delete("/{user_id}")
def delete_user(user_id: str, request: Request):
    """
    Soft delete a user by setting the 'isDeleted' field to the current timestamp.
    The user_id is provided as a path parameter.
    """
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID is required")

    user_query = (
        db.collection(USERS).where(filter=FieldFilter(USER_ID, "==", user_id)).limit(1)
    )
    user_docs = user_query.get()

    if not user_docs:
        raise HTTPException(status_code=404, detail="User not found")

    doc_snapshot = user_docs[0]
    doc_ref = doc_snapshot.reference
    doc_ref.update(
        {
            IS_DELETED: datetime.datetime.utcnow(),
            MODIFIED_AT: datetime.datetime.utcnow(),
            MODIFIED_BY: request.state.user[USER_ID],
            ACCESS_LEVEL: DELETED_LEVEL,
        }
    )

    db.collection(SESSIONS).document(user_id).delete()

    return {"message": f"User {user_id} has been soft deleted."}


# -----------------------------------
# Remove from Allowed Users List
# -----------------------------------


@router.delete(
    "/allowed-users/{email}", dependencies=[Depends(require_access_level(ADMIN_LEVEL))]
)
async def delete_allowed_user(email: str, current_user=Depends(get_current_user)):
    """
    Delete a user from the allowed users list.

    Only administrators can access this endpoint.

    Parameters:
    - email: The email address of the user to delete from the allowed users list.
    """
    doc_ref = db.collection(ALLOWED_USERS).document(email)
    doc = doc_ref.get()

    if not doc.exists:
        raise HTTPException(
            status_code=404, detail="User not found in allowed users list"
        )

    doc_ref.delete()

    return {"message": f"User {email} has been removed from allowed users list"}


# -----------------------------------
# Edit access level of allowed user
# -----------------------------------
@router.put(
    "/allowed-users/access-level",
    dependencies=[Depends(require_access_level(ADMIN_LEVEL))],
)
async def update_allowed_user_access_level(
    payload: SetAccessLevelModel,
    current_user: dict = Depends(get_current_user),
):
    """
    Update the access level of a user in the allowed users list.

    Only administrators can access this endpoint.

    Parameters:
    - email: The email address of the user to update
    - new_access_level: The new access level to assign (0, 1, 5, or 9)
    """
    allowed_user_ref = db.collection(ALLOWED_USERS).document(payload.email)
    allowed_user_doc = allowed_user_ref.get()

    if not allowed_user_doc.exists:
        raise HTTPException(
            status_code=404, detail="User not found in allowed users list"
        )

    # Validate the new access level
    new_level = int(payload.new_access_level)
    allowed_levels = [9, 5, 1, 0]
    if new_level not in allowed_levels:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid access level: {new_level}. Allowed values are {allowed_levels}",
        )

    # Update the document with new access level and modification info
    now = datetime.datetime.utcnow()
    update_data = {
        ACCESS_LEVEL: new_level,
        MODIFIED_AT: now,
        MODIFIED_BY: current_user[USER_ID],
    }

    allowed_user_ref.update(update_data)

    return {
        "message": f"Access level updated for {payload.email} to {new_level} in allowed users list"
    }

# -----------------------------------
# Get Current User Info
# -----------------------------------

@router.get("/me", dependencies=[Depends(require_access_level(USER_LEVEL))])
def get_me(current_user: dict = Depends(get_current_user)):
    """
    Get the email and name of the currently logged-in user.
    """
    user_id = current_user.get(USER_ID)
    if not user_id:
        # This case should ideally not happen if get_current_user works correctly
        raise HTTPException(status_code=401, detail="Could not validate credentials")

    # Fetch user details from Firestore using USER_ID
    user_query = (
        db.collection(USERS)
        .where(filter=FieldFilter(USER_ID, "==", user_id))
        .limit(1)
        .get()
    )

    if not user_query:
        raise HTTPException(status_code=404, detail="User not found")

    user_data = user_query[0].to_dict()

    return {
        EMAIL: user_data.get(EMAIL),
        FIRST_NAME: user_data.get(FIRST_NAME),
        LAST_NAME: user_data.get(LAST_NAME),
        ACCESS_LEVEL: user_data.get(ACCESS_LEVEL), # Optionally return access level too
        USER_ID: user_data.get(USER_ID) # Optionally return user ID
    }
