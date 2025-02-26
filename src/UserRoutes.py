from dotenv import load_dotenv, dotenv_values
import os

try:
    config = dotenv_values(".env")
except FileNotFoundError:
    config = {}

load_dotenv(dotenv_path="/run/secrets/xlab_secret")
load_dotenv()

from src.classes.AllowedUserModel import AllowedUserModel

from fastapi import APIRouter, HTTPException, Body, Depends, Request
import datetime

import firebase_admin
from firebase_admin import credentials, firestore

if not firebase_admin._apps:
    cred = credentials.ApplicationDefault()
    firebase_admin.initialize_app(cred)

db = firestore.client()

router = APIRouter()


def get_current_user(request: Request):
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="User not authenticated")
    return user


# POST endpoint: <dev/prod>/user/allowed-users
@router.post("/allowed-users")
async def allowed_users(
    payload: AllowedUserModel = Body(...), current_user=Depends(get_current_user)
):
    """
    Add a list of allowed users to the Firestore collection 'allowed_users'.
    The payload should contain a comma-separated list of emails and an access level.
    """
    if current_user["access_level"] != 9:
        raise HTTPException(
            status_code=403, detail="Insufficient privileges to add users"
        )

    email_list = [email.strip() for email in payload.emails.split(",") if email.strip()]

    batch = db.batch()

    for email in email_list:
        allowed_user_data = {
            "email": email,
            "access_level": payload.access_level,
            "added_by": current_user["user_id"],
            "added_at": datetime.datetime.utcnow(),
        }
        doc_ref = db.collection("allowed_users").document(email)
        batch.set(doc_ref, allowed_user_data)

    batch.commit()

    return {"message": f"Invitations sent to {len(email_list)} user(s)"}


@router.delete("/delete/{user_id}")
def delete_user(
    user_id: str, request: Request, current_user: dict = Depends(get_current_user)
):
    """
    Soft delete a user by setting the 'isDeleted' field to the current timestamp.
    The user_id is passed as a path parameter.
    """
    # Retrieve the user document from Firestore using the provided user_id.
    user_ref = db.collection("users").document(user_id)
    user_doc = user_ref.get()

    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="User not found")

    user_ref.update({"isDeleted": datetime.datetime.utcnow()})

    return {"message": f"User {user_id} has been soft deleted."}
