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
)

from firebase_config import db

router = APIRouter()


# -----------------------------------
# User Signup and Signin Endpoints
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
    token = create_token(user_data[USER_ID], user_data[ACCESS_LEVEL])

    return {"message": message, "token": token}


@router.post("/signin")
def sign_in(payload: UserSignInModel = Body(...)):
    """
    Sign in an existing user by verifying email and password.
    Returns a token if the credentials are valid.
    """
    user_ref = (
        db.collection(USERS)
        .where(filter=FieldFilter(EMAIL, "==", payload.email))
        .limit(1)
        .get()
    )
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
# User Listing and Deletion
# -----------------------------------


@router.get("/", dependencies=[Depends(require_access_level(USER_LEVEL))])
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


@router.delete("/{user_id}")
def delete_user(user_id: str, request: Request):
    """
    Soft delete a user by setting the 'isDeleted' field to the current timestamp.
    The user_id is provided as a path parameter.
    """
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

    return {"message": f"User {user_id} has been soft deleted."}
