from fastapi import (
    APIRouter,
    Body,
    HTTPException,
    Depends,
    UploadFile,
    File,
    BackgroundTasks,
    Form,
)
import datetime
from typing import List, Optional
import os
import boto3
import json

from src.utils import generate_uuid, get_current_user, require_access_level
from supabase_config import table
from src.constants import (
    MODULES,
    MODULE_RESOURCES,
    AGENT_ID,
    DELIMITER,
    NAME,
    SYSTEM_PROMPT,
    CREATED_BY,
    CREATED_AT,
    MODIFIED_AT,
    MODIFIED_BY,
    IS_DELETED,
    USER_ID,
    MANAGER_LEVEL,
    USER_LEVEL,
    RESOURCE_ID,
    ORIGINAL_FILENAME,
    S3_KEY,
    UPLOAD_TIMESTAMP,
    UPLOADER_ID,
    FILE_SIZE,
    RESOURCE_TYPE,
    FILE_URL,
    PROCESSING_STATUS,
    MIME_TYPE,
    PDF_TYPE,
    CRITERIA,
    MANAGER_LEVEL,
    USER_LEVEL,
    CREATED_AT,
    CREATED_BY,
    CHAT,
)
from src.models.module import (
    CreateTrainingModuleRequest,
    EditTrainingModuleRequest,
    ResourceListResponse,
)
from src.services.S3Handler import S3Handler

# Initialize S3 handler
s3_handler = S3Handler()

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
    current_user: dict = Depends(get_current_user),
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

    # Fetch modules from Supabase and filter in-Python for simplicity
    res = table(MODULES).select("*").execute()
    limited_modules_docs = getattr(res, "data", None) or []

    filtered_modules = []
    limited_modules = []
    for module_data in limited_modules_docs:
        # Respect deletion filter
        if filter_deleted:
            if module_data.get(IS_DELETED) is None:
                continue
        else:
            if module_data.get(IS_DELETED) is not None:
                continue

        criteria_value = module_data.get(CRITERIA)
        if criteria_value:
            module_data[CRITERIA] = criteria_value.split(DELIMITER)
        else:
            module_data[CRITERIA] = []

        # Apply search prefix match on name if provided
        if search:
            name_val = module_data.get(NAME) or ""
            if not name_val.startswith(search):
                continue

        limited_modules.append(module_data)

    if limited_modules:
        # Get all modules
        module_ids_dict = {m[AGENT_ID]: m for m in limited_modules}

        # Get all chats for the current user
        chats_res = table(CHAT).select("*").eq(USER_ID, current_user.get(USER_ID)).execute()
        chats_query = getattr(chats_res, "data", None) or []

        # Create set of module IDs that have chats
        chat_module_ids = set()
        for chat in chats_query:
            if chat.get(AGENT_ID) in module_ids_dict:
                chat_module_ids.add(chat.get(AGENT_ID))

        # Filter out modules with existing chats
        filtered_modules = [
            m for m in limited_modules if m[AGENT_ID] not in chat_module_ids
        ]

        # Pagination
        start_index = (page - 1) * page_size
        end_index = start_index + page_size
        filtered_modules = filtered_modules[start_index:end_index]

    total_count = len(filtered_modules)

    return {
        "modules": filtered_modules,
        "page": page,
        "page_size": page_size,
        "total_count": total_count,
    }


async def process_pdf_upload(
    agent_id: str,
    pdf_file: UploadFile,
    current_user: dict,
    background_tasks: BackgroundTasks,
):
    """
    Validates the PDF file, stores its metadata in Firestore, updates the module
    document with the new resource, and schedules a background task to process the PDF.
    """
    # Validate that the file is a PDF.
    if (
        pdf_file.content_type != "application/pdf"
        and not pdf_file.filename.lower().endswith(".pdf")
    ):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    # Read file content
    file_content = await pdf_file.read()

    # Reset file pointer to the beginning
    await pdf_file.seek(0)

    resource_id = generate_uuid()
    now = datetime.datetime.utcnow()
    s3_key = f"module/{agent_id}/resources/{resource_id}.pdf"
    placeholder_url = f"/api/module/{agent_id}/resource/{resource_id}"

    # Prepare the resource metadata.
    resource_data = {
        RESOURCE_ID: resource_id,
        AGENT_ID: agent_id,
        ORIGINAL_FILENAME: pdf_file.filename,
        S3_KEY: s3_key,  # For future S3 storage.
        UPLOAD_TIMESTAMP: now,
        UPLOADER_ID: current_user[USER_ID],
        FILE_SIZE: len(file_content),
        RESOURCE_TYPE: PDF_TYPE,
        FILE_URL: placeholder_url,  # Placeholder until S3 is set up.
        PROCESSING_STATUS: "pending",
        MIME_TYPE: pdf_file.content_type,
        CREATED_AT: now,
        CREATED_BY: current_user[USER_ID],
        MODIFIED_AT: now,
        MODIFIED_BY: current_user[USER_ID],
        IS_DELETED: None,
    }

    # Store the PDF metadata in Supabase
    table(MODULE_RESOURCES).insert(resource_data).execute()

    # Update the module row to reference this resource (append to JSON array)
    mod_res = table(MODULES).select("*").eq("id", agent_id).limit(1).execute()
    mod_rows = getattr(mod_res, "data", None) or []
    if mod_rows:
        mod = mod_rows[0]
        resources_list = mod.get("resources") or []
        if resource_id not in resources_list:
            resources_list.append(resource_id)
            table(MODULES).update(
                {"resources": resources_list, MODIFIED_AT: now, MODIFIED_BY: current_user[USER_ID]}
            ).eq("id", agent_id).execute()

    try:
        # Upload the PDF file to S3
        s3_handler.upload_file(
            file_obj=pdf_file.file, s3_key=s3_key, content_type=pdf_file.content_type
        )
    except Exception as e:
        print("Failed to upload PDF: ", str(e))
        raise HTTPException(status_code=500, detail=f"Failed to upload PDF: {str(e)}")

    # Schedule PDF processing in the background.
    from src.services.PDFProcessor import PDFProcessor

    pdf_processor = PDFProcessor()
    background_tasks.add_task(
        pdf_processor.process_s3_pdf_for_embedding,
        s3_key=s3_key,
        resource_id=resource_id,
        agent_id=agent_id,
        metadata={
            "original_filename": pdf_file.filename,
            "uploader_id": current_user[USER_ID],
        },
    )

    # Return the PDF resource details.
    return {
        "resource_id": resource_id,
        "file_url": placeholder_url,
        "filename": pdf_file.filename,
        "status": "stored",
    }


# ------------------------------------------------
# Create Training Module Endpoint (POST /)
# ------------------------------------------------


@router.post("/create", dependencies=[Depends(require_access_level(MANAGER_LEVEL))])
async def create_training_module(
    background_tasks: BackgroundTasks,
    request_data: CreateTrainingModuleRequest = Depends(
        CreateTrainingModuleRequest.as_form
    ),
    pdf_file: UploadFile | None = File(None),
    current_user: dict = Depends(get_current_user),
):
    """
    Create a new training module. Optionally, if a PDF file is provided, process it
    in the background using the shared `process_pdf_upload` function.
    """
    agent_id = generate_uuid()
    now = datetime.datetime.utcnow()

    # Check the criteria
    if not request_data.criteria:
        raise HTTPException(status_code=400, detail="Criteria cannot be empty")

    # --- Modification Start ---
    parsed_criteria = []
    if isinstance(request_data.criteria, list) and len(request_data.criteria) == 1:
        try:
            # Attempt to parse the first element as JSON if it's a string
            potential_list = json.loads(request_data.criteria[0])
            if isinstance(potential_list, list):
                # Ensure items are strings
                parsed_criteria = [str(item) for item in potential_list]
            else:
                # It wasn't a JSON list, treat the original list as intended if items are strings
                if all(isinstance(item, str) for item in request_data.criteria):
                    parsed_criteria = request_data.criteria
                else:
                    raise HTTPException(
                        status_code=400,
                        detail="Criteria must be a list of strings or a single JSON string representing a list",
                    )

        except (json.JSONDecodeError, TypeError):
            # It wasn't a JSON string, treat the original list as intended if items are strings
            if all(isinstance(item, str) for item in request_data.criteria):
                parsed_criteria = request_data.criteria
            else:
                raise HTTPException(
                    status_code=400,
                    detail="Criteria format is invalid. Expected list of strings or a single JSON string list.",
                )
    elif isinstance(request_data.criteria, list) and all(
        isinstance(item, str) for item in request_data.criteria
    ):
        # It's already a list of strings
        parsed_criteria = request_data.criteria
    else:
        raise HTTPException(
            status_code=400, detail="Criteria must be a list of strings"
        )

    if not parsed_criteria:
        raise HTTPException(
            status_code=400, detail="Criteria cannot be empty after parsing"
        )

    module_data = {
        AGENT_ID: agent_id,
        NAME: request_data.title,
        SYSTEM_PROMPT: request_data.system_prompt,
        CREATED_BY: current_user[USER_ID],
        CREATED_AT: now,
        MODIFIED_AT: now,
        MODIFIED_BY: current_user[USER_ID],
        IS_DELETED: None,
        # Use the parsed list and DELIMITER
        CRITERIA: DELIMITER.join(parsed_criteria),
    }

    # Save the module in Supabase.
    # Ensure `id` column matches agent_id
    module_row = {"id": agent_id, **module_data}
    table(MODULES).insert(module_row).execute()

    response = {
        "message": "Training module created successfully.",
        # Return the parsed criteria list in the response for clarity
        "module": {**module_data, CRITERIA: parsed_criteria},
    }

    # If a PDF file was uploaded, process it.
    if pdf_file:
        try:
            pdf_response = await process_pdf_upload(
                agent_id, pdf_file, current_user, background_tasks
            )
            response["pdf_resource"] = pdf_response
            # Update the module in the response if pdf processing adds resource info
            response["module"]["resources"] = [pdf_response["resource_id"]]
        except Exception as e:
            # Consider rolling back the module creation or marking it as incomplete
            raise HTTPException(
                status_code=500,
                detail=f"Module created, but failed to process PDF: {str(e)}",
            )

    return response


# ------------------------------------------------
# Edit Training Module Endpoint (PUT /{agent_id})
# ------------------------------------------------


@router.put("/{agent_id}", dependencies=[Depends(require_access_level(MANAGER_LEVEL))])
async def edit_training_module(
    agent_id: str,
    background_tasks: BackgroundTasks,
    request_data: EditTrainingModuleRequest = Depends(
        EditTrainingModuleRequest.as_form
    ),
    pdf_file: UploadFile | None = File(None),
    current_user: dict = Depends(get_current_user),
):
    """
    Edit an existing training module. Optionally, if a new PDF file is provided,
    process it in the background using the shared `process_pdf_upload` function.
    If keep_existing_pdf is False and no new PDF is uploaded, delete all existing PDFs.
    """
    module_res = table(MODULES).select("*").eq("id", agent_id).limit(1).execute()
    module_rows = getattr(module_res, "data", None) or []
    if not module_rows:
        raise HTTPException(status_code=404, detail="Training module not found")
    module_doc = module_rows[0]

    now = datetime.datetime.utcnow()

    # --- Criteria Parsing Start ---
    if not request_data.criteria:
        raise HTTPException(status_code=400, detail="Criteria cannot be empty")

    parsed_criteria = []
    if isinstance(request_data.criteria, list) and len(request_data.criteria) == 1:
        try:
            # Attempt to parse the first element as JSON if it's a string
            potential_list = json.loads(request_data.criteria[0])
            if isinstance(potential_list, list):
                # Ensure items are strings and validate length
                parsed_criteria = []
                for item in potential_list:
                    item_str = str(item)
                    if len(item_str) > 100:
                        raise HTTPException(
                            status_code=400,
                            detail="Each criterion cannot exceed 100 characters",
                        )
                    parsed_criteria.append(item_str)
            else:
                # It wasn't a JSON list, treat the original list as intended if items are strings
                if all(isinstance(item, str) for item in request_data.criteria):
                    parsed_criteria = []
                    for item in request_data.criteria:
                        if len(item) > 100:
                            raise HTTPException(
                                status_code=400,
                                detail="Each criterion cannot exceed 100 characters",
                            )
                        parsed_criteria.append(item)
                else:
                    raise HTTPException(
                        status_code=400,
                        detail="Criteria must be a list of strings or a single JSON string representing a list",
                    )

        except (json.JSONDecodeError, TypeError):
            # It wasn't a JSON string, treat the original list as intended if items are strings
            if all(isinstance(item, str) for item in request_data.criteria):
                parsed_criteria = []
                for item in request_data.criteria:
                    if len(item) > 100:
                        raise HTTPException(
                            status_code=400,
                            detail="Each criterion cannot exceed 100 characters",
                        )
                    parsed_criteria.append(item)
            else:
                raise HTTPException(
                    status_code=400,
                    detail="Criteria format is invalid. Expected list of strings or a single JSON string list.",
                )

    elif isinstance(request_data.criteria, list) and all(
        isinstance(item, str) for item in request_data.criteria
    ):
        # It's already a list of strings, validate length
        parsed_criteria = []
        for item in request_data.criteria:
            if len(item) > 100:
                raise HTTPException(
                    status_code=400,
                    detail="Each criterion cannot exceed 100 characters",
                )
            parsed_criteria.append(item)
    else:
        raise HTTPException(
            status_code=400, detail="Criteria must be a list of strings"
        )

    if not parsed_criteria:
        raise HTTPException(
            status_code=400, detail="Criteria cannot be empty after parsing"
        )

    updated_data = {
        NAME: request_data.title,
        SYSTEM_PROMPT: request_data.system_prompt,
        MODIFIED_AT: now,
        MODIFIED_BY: current_user[USER_ID],
        CRITERIA: DELIMITER.join(parsed_criteria),  # Use parsed criteria
    }

    table(MODULES).update(updated_data).eq("id", agent_id).execute()

    # Prepare response module data with criteria as a list
    response_module_data = updated_data.copy()
    response_module_data[CRITERIA] = parsed_criteria

    response = {
        "message": "Training module updated successfully.",
        "module": response_module_data,  # Return criteria as list
    }

    # If a new PDF file is provided, process it.
    if pdf_file:
        try:
            pdf_response = await process_pdf_upload(
                agent_id, pdf_file, current_user, background_tasks
            )
            response["pdf_resource"] = pdf_response
            # Refresh module resources from Supabase (process_pdf_upload already appends)
            mod_res = table(MODULES).select("*").eq("id", agent_id).limit(1).execute()
            mod_rows = getattr(mod_res, "data", None) or []
            if mod_rows:
                response["module"]["resources"] = mod_rows[0].get("resources", [])
            else:
                response["module"]["resources"] = [pdf_response["resource_id"]]
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to upload PDF: {str(e)}"
            )
    # If keep_existing_pdf is False and no new PDF is uploaded, delete existing PDFs
    elif not request_data.keep_existing_pdf:
        try:
            # Query all non-deleted PDF resources for this module
            res = (
                table(MODULE_RESOURCES)
                .select("*")
                .eq(AGENT_ID, agent_id)
                .execute()
            )
            resources_rows = getattr(res, "data", None) or []

            resource_ids_to_remove = []
            for resource in resources_rows:
                if resource.get(IS_DELETED) is None and resource.get(RESOURCE_TYPE) == PDF_TYPE:
                    resource_id_to_remove = resource.get("id") or resource.get(RESOURCE_ID)
                    if resource_id_to_remove:
                        resource_ids_to_remove.append(resource_id_to_remove)
                        table(MODULE_RESOURCES).update(
                            {IS_DELETED: now, MODIFIED_AT: now, MODIFIED_BY: current_user[USER_ID]}
                        ).eq("id", resource_id_to_remove).execute()

            if resource_ids_to_remove:
                # Remove ids from module resources JSON array
                mod_res = table(MODULES).select("*").eq("id", agent_id).limit(1).execute()
                mod_rows = getattr(mod_res, "data", None) or []
                if mod_rows:
                    mod = mod_rows[0]
                    current_resources = mod.get("resources") or []
                    new_resources = [r for r in current_resources if r not in resource_ids_to_remove]
                    table(MODULES).update({"resources": new_resources, MODIFIED_AT: now, MODIFIED_BY: current_user[USER_ID]}).eq("id", agent_id).execute()
                    response["removed_pdf_count"] = len(resource_ids_to_remove)
                    response["module"]["resources"] = new_resources
                else:
                    response["removed_pdf_count"] = len(resource_ids_to_remove)
                    response["module"]["resources"] = []

        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to remove existing PDFs: {str(e)}"
            )

    return response


# ------------------------------------------------
# Delete Training Module Endpoint (DELETE /{agent_id})
# ------------------------------------------------


@router.delete(
    "/{agent_id}", dependencies=[Depends(require_access_level(MANAGER_LEVEL))]
)
async def delete_training_module(
    agent_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Soft delete a training module and permanently delete all its associated resources.

    This function:
    - Checks if the training module exists.
    - Queries all non-deleted resources associated with the module.
    - Deletes the corresponding file from S3.
    - Permanently deletes the Firestore resource documents.
    - Soft deletes the training module (by updating the IS_DELETED field).
    """
    # Check if the module exists.
    module_res = table(MODULES).select("*").eq("id", agent_id).limit(1).execute()
    module_rows = getattr(module_res, "data", None) or []
    if not module_rows:
        raise HTTPException(status_code=404, detail="Training module not found")

    now = datetime.datetime.utcnow()

    # Initialize S3 client and bucket name from configuration.
    s3 = boto3.client("s3")
    S3_BUCKET = os.getenv("S3_BUCKET")
    if not S3_BUCKET:
        raise HTTPException(status_code=500, detail="S3 bucket not configured")

    # Query resources for this module and delete associated S3 files and DB rows
    res = table(MODULE_RESOURCES).select("*").eq(AGENT_ID, agent_id).execute()
    resources_rows = getattr(res, "data", None) or []

    for resource in resources_rows:
        if resource.get(IS_DELETED) is None:
            resource_data = resource
            s3_key = resource_data.get(S3_KEY)
            resource_id_to_del = resource_data.get("id") or resource_data.get(RESOURCE_ID)
            if s3_key:
                try:
                    s3.delete_object(Bucket=S3_BUCKET, Key=s3_key)
                except Exception as e:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to delete file from S3 for resource {resource_id_to_del}: {str(e)}",
                    )
            # Permanently delete the resource row
            if resource_id_to_del:
                table(MODULE_RESOURCES).delete().eq("id", resource_id_to_del).execute()

    # Soft delete the training module (mark as deleted).
    table(MODULES).update({IS_DELETED: now, MODIFIED_AT: now, MODIFIED_BY: current_user[USER_ID]}).eq("id", agent_id).execute()

    return {
        "message": f"Training module {agent_id} has been deleted. All associated resource files have been removed from S3 and their Firestore documents deleted."
    }


# ------------------------------------------------
# Get Module Title Endpoint (GET /{agent_id}/title)
# ------------------------------------------------


@router.get("/{agent_id}/title")
def get_module_title(agent_id: str):
    """
    Get the title of a training module by its ID.
    """
    module_res = table(MODULES).select("*").eq("id", agent_id).limit(1).execute()
    module_rows = getattr(module_res, "data", None) or []
    if not module_rows:
        raise HTTPException(status_code=404, detail="Training module not found.")

    module_data = module_rows[0]
    return {"title": module_data.get(NAME)}


# ------------------------------------------------
# List Module Resources Endpoint (GET /{agent_id}/resources)
# ------------------------------------------------


@router.get(
    "/{agent_id}/resources",
    dependencies=[Depends(require_access_level(USER_LEVEL))],
    response_model=ResourceListResponse,
)
async def list_module_resources(
    agent_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    List all resources associated with a training module.
    """
    # Validate module exists
    module_ref = db.collection(MODULES).document(agent_id)
    module_doc = module_ref.get()

    if not module_doc.exists:
        raise HTTPException(status_code=404, detail="Training module not found")

    # Query resources for this module
    resources_query = (
        db.collection(MODULE_RESOURCES)
        .where(filter=FieldFilter(AGENT_ID, "==", agent_id))
        .where(filter=FieldFilter(IS_DELETED, "==", None))
        .get()
    )

    # Build response
    resources = []
    for doc in resources_query:
        resource_data = doc.to_dict()
        resources.append(
            {
                "resource_id": resource_data.get(RESOURCE_ID),
                "original_filename": resource_data.get(ORIGINAL_FILENAME),
                "file_url": resource_data.get(FILE_URL),
                "upload_timestamp": resource_data.get(UPLOAD_TIMESTAMP),
                "file_size": resource_data.get(FILE_SIZE),
                "processing_status": resource_data.get(PROCESSING_STATUS),
                "resource_type": resource_data.get(RESOURCE_TYPE),
            }
        )

    return {"resources": resources, "module_id": agent_id, "count": len(resources)}


# ------------------------------------------------
# Delete Resource Endpoint (DELETE /{agent_id}/resource/{resource_id})
# ------------------------------------------------


@router.delete(
    "/{agent_id}/resource/{resource_id}",
    dependencies=[Depends(require_access_level(MANAGER_LEVEL))],
)
async def delete_resource(
    agent_id: str,
    resource_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Delete a specific resource from a module.
    This is a soft delete that marks the resource as deleted in Firestore.
    The S3 object is not deleted immediately to allow for recovery.
    """
    # Verify module exists
    module_res = table(MODULES).select("*").eq("id", agent_id).limit(1).execute()
    module_rows = getattr(module_res, "data", None) or []

    if not module_rows:
        raise HTTPException(status_code=404, detail="Training module not found")

    # Verify resource exists and belongs to this module
    resource_res = table(MODULE_RESOURCES).select("*").eq("id", resource_id).limit(1).execute()
    resource_rows = getattr(resource_res, "data", None) or []

    if not resource_rows:
        raise HTTPException(status_code=404, detail="Resource not found")

    resource_data = resource_rows[0]
    if resource_data.get(AGENT_ID) != agent_id:
        raise HTTPException(status_code=403, detail="Resource does not belong to this module")

    now = datetime.datetime.utcnow()

    # Soft delete the resource
    table(MODULE_RESOURCES).update({IS_DELETED: now, MODIFIED_AT: now, MODIFIED_BY: current_user[USER_ID]}).eq("id", resource_id).execute()

    # Remove from module's resources list (update JSON array)
    current_resources = module_rows[0].get("resources") or []
    new_resources = [r for r in current_resources if r != resource_id]
    table(MODULES).update({"resources": new_resources, MODIFIED_AT: now, MODIFIED_BY: current_user[USER_ID]}).eq("id", agent_id).execute()

    return {"message": f"Resource {resource_id} has been deleted from module {agent_id}"}
