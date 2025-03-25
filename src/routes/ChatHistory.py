from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
from datetime import datetime
import dateutil.parser

from google.cloud.firestore_v1.base_query import FieldFilter

from src.models.chat import (
    ChatListResponse,
    ChatDetailsResponse,
    ChatStatusUpdate,
)
from src.utils import get_current_user, require_access_level
from firebase_config import db
from src.constants import (
    USER_ID,
    CHATS,
    STATUS,
    AGENT_ID,
    STARTED_AT,
    CLOSED_AT,
    CURRENT_VERSION,
    CHAT,
    MESSAGES,
    USER_LEVEL,
    MANAGER_LEVEL,
    ACCESS_LEVEL,
    STATUS_OPEN,
    STATUS_CLOSED,
    STATUS_IN_PROGRESS,
    STATUS_REOPENED,
    VERSION,
    SCORE,
)

router = APIRouter()


@router.get(
    "/list",
    dependencies=[Depends(require_access_level(USER_LEVEL))],
    response_model=ChatListResponse,
)
async def list_chats(
    status: Optional[str] = None,
    agent_id: Optional[str] = None,
    user_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    page: int = 1,
    page_size: int = 10,
    current_user=Depends(get_current_user),
):
    """
    List chat sessions with optional filtering and pagination.

    Filters:
    - status: Filter by chat status (open, closed, in_progress, reopened)
    - agent_id: Filter by agent ID
    - user_id: Filter by user ID
    - start_date: Filter sessions after this date (ISO format)
    - end_date: Filter sessions before this date (ISO format)

    Pagination:
    - page: Page number (starting from 1)
    - page_size: Number of results per page
    """
    try:
        base_query = db.collection(CHATS)

        # Debug log the query
        print(f"Querying collection: {CHATS}")
        print(f"Filters: status={status}, agent_id={agent_id}, user_id={user_id}")

        # Apply filters if provided
        if status:
            base_query = base_query.where(filter=FieldFilter(STATUS, "==", status))

        if agent_id:
            base_query = base_query.where(filter=FieldFilter(AGENT_ID, "==", agent_id))

        # Regular users can only see their own chats, managers and admins can see all
        user_access_level = current_user.get(ACCESS_LEVEL, 0)
        if user_access_level < MANAGER_LEVEL:
            base_query = base_query.where(
                filter=FieldFilter(USER_ID, "==", current_user[USER_ID])
            )
        elif user_id:  # If manager/admin and user_id filter provided
            base_query = base_query.where(filter=FieldFilter(USER_ID, "==", user_id))

        # Date filters
        if start_date:
            try:
                start_datetime = dateutil.parser.parse(start_date)
                base_query = base_query.where(
                    filter=FieldFilter(STARTED_AT, ">=", start_datetime)
                )
            except (ValueError, TypeError) as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid start_date format. Use ISO format. Error: {str(e)}",
                )

        if end_date:
            try:
                end_datetime = dateutil.parser.parse(end_date)
                base_query = base_query.where(
                    filter=FieldFilter(STARTED_AT, "<=", end_datetime)
                )
            except (ValueError, TypeError) as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid end_date format. Use ISO format. Error: {str(e)}",
                )

        # Get all results for debugging and total count
        all_docs = list(base_query.get())
        print(f"Total docs found before pagination: {len(all_docs)}")

        # Apply pagination
        offset_val = (page - 1) * page_size
        query_result = base_query.offset(offset_val).limit(page_size).get()
        total_count = len(all_docs)

        chat_list = []
        for doc in query_result:
            doc_dict = doc.to_dict() or {}
            chat_versions = doc_dict.get(CHAT, [])

            # Add an entry for each version of the chat
            if isinstance(chat_versions, dict):
                for version_key, version_data in chat_versions.items():
                    chat_list.append(
                        {
                            "agent_id": doc_dict.get(AGENT_ID),
                            "user_id": doc_dict.get(USER_ID),
                            "chat_id": doc.id,
                            "version": version_key,  # Add version as a field
                            "status": version_data.get(STATUS, doc_dict.get(STATUS)),
                            "startedAt": version_data.get(STARTED_AT),
                            "closedAt": version_data.get(CLOSED_AT),
                            # Include message count if needed
                            "message_count": len(version_data.get(MESSAGES, [])),
                            "is_current": str(version_key)
                            == str(doc_dict.get(CURRENT_VERSION, 1)),
                        }
                    )
            else:  # Handle array format
                for version_data in chat_versions:
                    version_num = version_data.get(VERSION)
                    chat_list.append(
                        {
                            "agent_id": doc_dict.get(AGENT_ID),
                            "user_id": doc_dict.get(USER_ID),
                            "chat_id": doc.id,
                            "version": version_num,
                            "status": version_data.get(STATUS, doc_dict.get(STATUS)),
                            "startedAt": version_data.get(STARTED_AT),
                            "closedAt": version_data.get(CLOSED_AT),
                            "message_count": len(version_data.get(MESSAGES, [])),
                            "is_current": version_num
                            == doc_dict.get(CURRENT_VERSION, 1),
                        }
                    )
        return {
            "chats": chat_list,
            "page": page,
            "page_size": page_size,
            "total_count": total_count,
        }
    except Exception as e:
        print(f"Error in list_chats: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get(
    "/{chat_id}",
    dependencies=[Depends(require_access_level(USER_LEVEL))],
    response_model=ChatDetailsResponse,
)
async def get_chat_detail(
    chat_id: str, version: Optional[str] = None, current_user=Depends(get_current_user)
):
    """
    Get detailed information about a specific chat session including all messages.

    Parameters:
    - chat_id: The unique identifier for the chat session
    """
    chat_doc = db.collection(CHATS).document(chat_id).get()

    if not chat_doc.exists:
        raise HTTPException(status_code=404, detail="Chat session not found")

    chat_data = chat_doc.to_dict()

    # Check if user has permission to access this chat
    user_access_level = current_user.get("access_level", 0)
    if (
        user_access_level < MANAGER_LEVEL
        and chat_data.get(USER_ID) != current_user[USER_ID]
    ):
        raise HTTPException(
            status_code=403, detail="You do not have permission to access this chat"
        )

    # If version is specified, filter to just that version's messages
    if version is not None:
        # Handle both dict and array formats
        if isinstance(chat_data.get(CHAT), dict):
            if version in chat_data.get(CHAT, {}):
                specific_version = chat_data[CHAT][version]
                # Return just the specified version
                return {
                    "chat": {
                        "agent_id": chat_data.get(AGENT_ID),
                        "user_id": chat_data.get(USER_ID),
                        "status": specific_version.get(STATUS, chat_data.get(STATUS)),
                        "startedAt": specific_version.get(STARTED_AT),
                        "closedAt": specific_version.get(CLOSED_AT),
                        "version": version,
                        "messages": specific_version.get(MESSAGES, []),
                    }
                }
        else:  # Handle array format
            for v in chat_data.get(CHAT, []):
                if str(v.get(VERSION)) == str(version):
                    return {
                        "chat": {
                            "agent_id": chat_data.get(AGENT_ID),
                            "user_id": chat_data.get(USER_ID),
                            "status": v.get(STATUS, chat_data.get(STATUS)),
                            "startedAt": v.get(STARTED_AT),
                            "closedAt": v.get(CLOSED_AT),
                            "version": version,
                            "messages": v.get(MESSAGES, []),
                        }
                    }

    return {"chat": chat_data}


@router.put("/status", dependencies=[Depends(require_access_level(USER_LEVEL))])
async def update_chat_status(
    status_update: ChatStatusUpdate, current_user=Depends(get_current_user)
):
    """
    Update the status of a chat session.

    Parameters:
    - chat_id: The ID of the chat to update
    - status: The new status ('open', 'closed', 'in_progress', 'reopened')
    """
    # Validate status
    valid_statuses = [STATUS_OPEN, STATUS_CLOSED, STATUS_IN_PROGRESS, STATUS_REOPENED]
    if status_update.status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}",
        )

    chat_ref = db.collection(CHATS).document(status_update.chat_id)
    chat_doc = chat_ref.get()

    if not chat_doc.exists:
        raise HTTPException(status_code=404, detail="Chat session not found")

    chat_data = chat_doc.to_dict()

    # Check if user has permission to update this chat
    user_access_level = current_user.get("access_level", 0)
    if (
        user_access_level < MANAGER_LEVEL
        and chat_data.get(USER_ID) != current_user[USER_ID]
    ):
        raise HTTPException(
            status_code=403, detail="You do not have permission to update this chat"
        )

    now = datetime.now().isoformat()
    updates = {
        STATUS: status_update.status,
    }

    # If closing the chat, update the closedAt field
    if status_update.status == STATUS_CLOSED:
        updates[CLOSED_AT] = now

        # Also update the current version's closedAt
        current_version = chat_data.get(CURRENT_VERSION, 1)
        chat_versions = chat_data.get(CHAT, [])
        for i, version in enumerate(chat_versions):
            if version.get(VERSION) == current_version:
                chat_versions[i]["closedAt"] = now
                updates[CHAT] = chat_versions
                break

    # If reopening a closed chat, add a new version
    if (
        status_update.status == STATUS_REOPENED
        and chat_data.get(STATUS) == STATUS_CLOSED
    ):
        current_version = chat_data.get(CURRENT_VERSION, 1) + 1
        updates[CURRENT_VERSION] = current_version

        # Add new version
        new_version = {
            VERSION: current_version,
            SCORE: None,
            "startedAt": now,
            "closedAt": None,
            MESSAGES: [],
        }

        chat_versions = chat_data.get(CHAT, [])
        chat_versions.append(new_version)
        updates[CHAT] = chat_versions

        # Clear the closedAt if reopening
        updates[CLOSED_AT] = None

    chat_ref.update(updates)

    return {
        "message": f"Chat status updated to {status_update.status}",
        "chat_id": status_update.chat_id,
    }