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
    ACCESS_LEVEL,
    MANAGER_LEVEL,
    DELETED_LEVEL,
    USER_LEVEL,
    CREATED_AT,
    CREATED_BY,
)

router = APIRouter()


# ------------------------------------------------
# List Modules Endpoint (GET /)
# ------------------------------------------------
@router.get("/list", dependencies=[Depends(require_access_level(USER_LEVEL))])
def list_modules(
    filter_deleted: bool = False, page: int = 1, page_size: int = 10, search: str = None
):
    """
    List modules with pagination and search.

    - **filter_deleted**: Include deleted modules in the results.
    - **page**: The page number (starting from 1).
    - **page_size**: The number of modules to return per page.
    - **search**: Optional keyword to filter modules by their title (prefix search).
    """
    if page < 1:
        raise HTTPException(
            status_code=400, detail="Page number must be greater than 0"
        )
    if page_size < 1:
        raise HTTPException(status_code=400, detail="Page size must be greater than 0")

    offset = (page - 1) * page_size
    query = db.collection(MODULES)

    if filter_deleted:
        query = query.where(filter=FieldFilter(IS_DELETED, "!=", None))
    else:
        query = query.where(filter=FieldFilter(IS_DELETED, "==", None))

    if search:
        query = query.order_by(NAME).start_at([search]).end_at([search + "\uf8ff"])

    modules_ref = query.offset(offset).limit(page_size).get()

    modules = [module.to_dict() for module in modules_ref]

    return {"modules": modules, "page": page, "page_size": page_size}


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
            ACCESS_LEVEL: DELETED_LEVEL,
        }
    )

    return {"message": f"Training module {agent_id} has been soft deleted."}
