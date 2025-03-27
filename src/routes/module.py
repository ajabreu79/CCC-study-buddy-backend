from fastapi import APIRouter, HTTPException, Depends
import datetime
from src.utils import generate_uuid, get_current_user, require_access_level
from src.models.module import CreateTrainingModuleRequest, EditTrainingModuleRequest
from google.cloud.firestore_v1.base_query import FieldFilter
from firebase_config import db
from src.constants import (
    IS_DELETED,
    MODULES,
    AGENT_ID,
    NAME,
    SYSTEM_PROMPT,
    USER_ID,
    MODIFIED_AT,
    MODIFIED_BY,
    MANAGER_LEVEL,
    USER_LEVEL,
    CREATED_AT,
    CREATED_BY,
    PASSING_SCORE,
    CHAT,
)

router = APIRouter()


# ------------------------------------------------
# List Modules Endpoint (GET /)
# ------------------------------------------------


@router.get("/list", dependencies=[Depends(require_access_level(USER_LEVEL))])
def list_modules(
    filter_deleted: bool = False,
    page: int = 1,
    page_size: int = 10,
    search: str = None,
):
    """
    List modules with pagination and search, excluding those with an associated chat.

    - **filter_deleted**: Include deleted modules if True.
    - **page**: The page number (starting from 1).
    - **page_size**: The number of modules to return per page.
    - **search**: Optional prefix search on module title.

    Returns only modules that do not have a related chat document.
    """
    if page < 1:
        raise HTTPException(
            status_code=400, detail="Page number must be greater than 0"
        )
    if page_size < 1:
        raise HTTPException(status_code=400, detail="Page size must be greater than 0")

    query = db.collection(MODULES)
    if filter_deleted:
        query = query.where(filter=FieldFilter(IS_DELETED, "!=", None))
    else:
        query = query.where(filter=FieldFilter(IS_DELETED, "==", None))

    if search:
        query = query.order_by(NAME).start_at([search]).end_at([search + "\uf8ff"])

    offset = (page - 1) * page_size
    limited_modules_docs = query.offset(offset).limit(page_size).get()

    limited_modules = []
    for doc in limited_modules_docs:
        module = doc.to_dict()
        module[AGENT_ID] = doc.id
        limited_modules.append(module)
    print(limited_modules)
    if limited_modules:
        module_ids = [m[AGENT_ID] for m in limited_modules]
        chats_docs = db.collection(CHAT).where(AGENT_ID, "in", module_ids).get()
        chat_module_ids = {chat.to_dict()[AGENT_ID] for chat in chats_docs}
        print(chat_module_ids)
        filtered_modules = [
            m for m in limited_modules if m[AGENT_ID] not in chat_module_ids
        ]
    else:
        filtered_modules = []

    total_count = len(filtered_modules)

    return {
        "modules": filtered_modules,
        "page": page,
        "page_size": page_size,
        "total_count": total_count,
    }


# ------------------------------------------------
# Create Training Module Endpoint (POST /)
# ------------------------------------------------


@router.post("/create", dependencies=[Depends(require_access_level(MANAGER_LEVEL))])
def create_training_module(
    request_data: CreateTrainingModuleRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Create a new training module.

    - Generates a unique module ID.
    - Stores the title and system prompt.
    - Captures the creator's ID from the identity provider.
    """
    agent_id = generate_uuid()
    now = datetime.datetime.utcnow()

    module_data = {
        AGENT_ID: agent_id,
        NAME: request_data.title,
        SYSTEM_PROMPT: request_data.system_prompt,
        CREATED_BY: current_user[USER_ID],
        CREATED_AT: now,
        MODIFIED_AT: now,
        MODIFIED_BY: current_user[USER_ID],
        IS_DELETED: None,
        PASSING_SCORE: request_data.passing_score,
    }

    db.collection(MODULES).document(agent_id).set(module_data)
    return {"message": "Training module created successfully.", "module": module_data}


# ------------------------------------------------
# Edit Training Module Endpoint (PUT /{agent_id})
# ------------------------------------------------


@router.put("/{agent_id}", dependencies=[Depends(require_access_level(MANAGER_LEVEL))])
def edit_training_module(
    agent_id: str,
    request_data: EditTrainingModuleRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Edit an existing training module.

    - Updates the module's title and system prompt.
    - Updates the modification timestamp and modifier.
    """
    module_ref = db.collection(MODULES).document(agent_id)
    module_doc = module_ref.get()
    if not module_doc.exists:
        raise HTTPException(status_code=404, detail="Training module not found.")

    now = datetime.datetime.utcnow()
    update_data = {
        NAME: request_data.title,
        SYSTEM_PROMPT: request_data.system_prompt,
        MODIFIED_AT: now,
        MODIFIED_BY: current_user[USER_ID],
        PASSING_SCORE: request_data.passing_score,
    }

    module_ref.update(update_data)
    return {
        "message": "Training module updated successfully.",
        "updated_fields": update_data,
    }


# ------------------------------------------------
# Delete Training Module Endpoint (DELETE /{agent_id})
# ------------------------------------------------
@router.delete(
    "/{agent_id}", dependencies=[Depends(require_access_level(MANAGER_LEVEL))]
)
async def delete_training_module(
    agent_id: str, current_user: dict = Depends(get_current_user)
):
    """
    Soft delete a training module by:
    - Setting the 'is_deleted' field to the current timestamp.
    - Dropping its ACCESS_LEVEL to 0.
    """
    if not agent_id:
        raise HTTPException(status_code=400, detail="Training module ID is required")

    module_ref = db.collection(MODULES).document(agent_id)
    module_doc = module_ref.get()
    if not module_doc.exists:
        raise HTTPException(status_code=404, detail="Training module not found")

    now = datetime.datetime.utcnow()
    module_ref.update(
        {
            IS_DELETED: now,
            MODIFIED_AT: now,
            MODIFIED_BY: current_user[USER_ID],
        }
    )

    return {"message": f"Training module {agent_id} has been soft deleted."}


# ------------------------------------------------
# Get Module Title Endpoint (GET /{agent_id}/title)
# ------------------------------------------------


@router.get("/{agent_id}/title")
def get_module_title(agent_id: str):
    """
    Get the title of a training module by its ID.
    """
    module_ref = db.collection(MODULES).document(agent_id)
    module_doc = module_ref.get()
    if not module_doc.exists:
        raise HTTPException(status_code=404, detail="Training module not found.")

    module_data = module_doc.to_dict()
    return {"title": module_data.get(NAME)}
