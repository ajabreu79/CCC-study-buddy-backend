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
from google.cloud.firestore_v1.base_query import FieldFilter
import os
import boto3
from firebase_admin import firestore

from src.utils import generate_uuid, get_current_user, require_access_level
from firebase_config import db
from src.constants import (
    MODULES,
    MODULE_RESOURCES,
    AGENT_ID,
    NAME,
    SYSTEM_PROMPT,
    CREATED_BY,
    CREATED_AT,
    MODIFIED_AT,
    MODIFIED_BY,
    IS_DELETED,
    USER_ID,
    ADMIN_LEVEL,
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
    ModuleListResponse,
    ResourceListResponse,
    ResourceUploadResponse,
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

    if limited_modules:
        module_ids = [m[AGENT_ID] for m in limited_modules]
        # Filter chats by both agent_id and the current user
        chats_docs = (
            db.collection(CHAT)
            .where(AGENT_ID, "in", module_ids)
            .where(
                USER_ID, "==", current_user.get(USER_ID)
            )  # Only filter current user's chats
            .get()
        )
        chat_module_ids = {chat.to_dict()[AGENT_ID] for chat in chats_docs}
        filtered_modules = [
            m for m in limited_modules if m[AGENT_ID] not in chat_module_ids
        ]

        # Query for PDF resources associated with these modules
        if filtered_modules:
            filtered_module_ids = [m[AGENT_ID] for m in filtered_modules]
            resources_query = (
                db.collection(MODULE_RESOURCES)
                .where(filter=FieldFilter(AGENT_ID, "in", filtered_module_ids))
                .where(filter=FieldFilter(IS_DELETED, "==", None))
                .where(filter=FieldFilter(RESOURCE_TYPE, "==", PDF_TYPE))
                .get()
            )

            # Create a map of module IDs to whether they have PDFs
            modules_with_pdfs = {
                resource.to_dict()[AGENT_ID] for resource in resources_query
            }

            # Add has_pdf flag to each module
            for module in filtered_modules:
                module["has_pdf"] = module[AGENT_ID] in modules_with_pdfs
    else:
        filtered_modules = []

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

    # Store the PDF metadata in Firestore.
    db.collection(MODULE_RESOURCES).document(resource_id).set(resource_data)

    # Update the module document to reference this resource.
    module_ref = db.collection(MODULES).document(agent_id)
    module_ref.update(
        {
            "resources": firestore.ArrayUnion([resource_id]),
            MODIFIED_AT: now,
            MODIFIED_BY: current_user[USER_ID],
        }
    )

    try:
        # Upload the PDF file to S3
        s3_handler.upload_file(file_obj=pdf_file.file, s3_key=s3_key, content_type=pdf_file.content_type)
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
    module_data = {
        AGENT_ID: agent_id,
        NAME: request_data.title,
        SYSTEM_PROMPT: request_data.system_prompt,
        CREATED_BY: current_user[USER_ID],
        CREATED_AT: now,
        MODIFIED_AT: now,
        MODIFIED_BY: current_user[USER_ID],
        IS_DELETED: None,
        CRITERIA: request_data.criteria,
    }

    # Save the module in Firestore.
    db.collection(MODULES).document(agent_id).set(module_data)

    response = {
        "message": "Training module created successfully.",
        "module": module_data,
    }

    # If a PDF file was uploaded, process it.
    if pdf_file:
        try:
            pdf_response = await process_pdf_upload(
                agent_id, pdf_file, current_user, background_tasks
            )
            response["pdf_resource"] = pdf_response
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to upload PDF: {str(e)}"
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
    module_ref = db.collection(MODULES).document(agent_id)
    module_doc = module_ref.get()
    if not module_doc.exists:
        raise HTTPException(status_code=404, detail="Training module not found")

    now = datetime.datetime.utcnow()
    # Update the module's fields as needed.
    updated_data = {
        NAME: request_data.title,
        SYSTEM_PROMPT: request_data.system_prompt,
        MODIFIED_AT: now,
        MODIFIED_BY: current_user[USER_ID],
        CRITERIA: request_data.criteria,
    }
    module_ref.update(updated_data)

    response = {
        "message": "Training module updated successfully.",
        "module": updated_data,
    }

    # If a new PDF file is provided, process it.
    if pdf_file:
        try:
            pdf_response = await process_pdf_upload(
                agent_id, pdf_file, current_user, background_tasks
            )
            response["pdf_resource"] = pdf_response
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to upload PDF: {str(e)}"
            )
    # If keep_existing_pdf is False and no new PDF is uploaded, delete existing PDFs
    elif not request_data.keep_existing_pdf:
        try:
            # Query all non-deleted PDF resources for this module
            resources_query = (
                db.collection(MODULE_RESOURCES)
                .where(filter=FieldFilter(AGENT_ID, "==", agent_id))
                .where(filter=FieldFilter(IS_DELETED, "==", None))
                .where(filter=FieldFilter(RESOURCE_TYPE, "==", PDF_TYPE))
                .get()
            )

            # Prepare a batch for efficient updates
            batch = db.batch()

            # Track resource IDs to remove from module
            resource_ids_to_remove = []

            for resource_doc in resources_query:
                resource_ref = db.collection(MODULE_RESOURCES).document(resource_doc.id)
                resource_ids_to_remove.append(resource_doc.id)

                # Soft delete the resource
                batch.update(
                    resource_ref,
                    {
                        IS_DELETED: now,
                        MODIFIED_AT: now,
                        MODIFIED_BY: current_user[USER_ID],
                    },
                )

            if resource_ids_to_remove:
                # Remove resources from module's resources array
                batch.update(
                    module_ref,
                    {
                        "resources": firestore.ArrayRemove(resource_ids_to_remove),
                        MODIFIED_AT: now,
                        MODIFIED_BY: current_user[USER_ID],
                    },
                )

                # Commit all updates
                batch.commit()
                response["removed_pdf_count"] = len(resource_ids_to_remove)

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
    module_ref = db.collection(MODULES).document(agent_id)
    module_doc = module_ref.get()
    if not module_doc.exists:
        raise HTTPException(status_code=404, detail="Training module not found")

    now = datetime.datetime.utcnow()

    # Initialize S3 client and bucket name from configuration.
    s3 = boto3.client("s3")
    S3_BUCKET = os.getenv("S3_BUCKET")
    if not S3_BUCKET:
        raise HTTPException(status_code=500, detail="S3 bucket not configured")

    # Query all non-deleted resources associated with this module.
    resources_query = (
        db.collection(MODULE_RESOURCES)
        .where(filter=FieldFilter(AGENT_ID, "==", agent_id))
        .where(filter=FieldFilter(IS_DELETED, "==", None))
        .get()
    )

    # Prepare a Firestore batch.
    batch = db.batch()

    for resource_doc in resources_query:
        resource_data = resource_doc.to_dict()
        s3_key = resource_data.get(S3_KEY)
        if s3_key:
            try:
                # Delete the file from S3.
                s3.delete_object(Bucket=S3_BUCKET, Key=s3_key)
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to delete file from S3 for resource {resource_doc.id}: {str(e)}",
                )
        # Permanently delete the Firestore document for the resource.
        resource_ref = db.collection(MODULE_RESOURCES).document(resource_doc.id)
        batch.delete(resource_ref)

    # Soft delete the training module (mark as deleted).
    batch.update(
        module_ref,
        {
            IS_DELETED: now,
            MODIFIED_AT: now,
            MODIFIED_BY: current_user[USER_ID],
        },
    )

    # Commit the batch operations.
    batch.commit()

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
    module_ref = db.collection(MODULES).document(agent_id)
    module_doc = module_ref.get()
    if not module_doc.exists:
        raise HTTPException(status_code=404, detail="Training module not found.")

    module_data = module_doc.to_dict()
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
    module_ref = db.collection(MODULES).document(agent_id)
    module_doc = module_ref.get()

    if not module_doc.exists:
        raise HTTPException(status_code=404, detail="Training module not found")

    # Verify resource exists and belongs to this module
    resource_ref = db.collection(MODULE_RESOURCES).document(resource_id)
    resource_doc = resource_ref.get()

    if not resource_doc.exists:
        raise HTTPException(status_code=404, detail="Resource not found")

    resource_data = resource_doc.to_dict()
    if resource_data.get(AGENT_ID) != agent_id:
        raise HTTPException(
            status_code=403, detail="Resource does not belong to this module"
        )

    now = datetime.datetime.utcnow()

    # Soft delete the resource
    resource_ref.update(
        {IS_DELETED: now, MODIFIED_AT: now, MODIFIED_BY: current_user[USER_ID]}
    )

    # Remove from module's resources list
    module_ref.update(
        {
            "resources": firestore.ArrayRemove([resource_id]),
            MODIFIED_AT: now,
            MODIFIED_BY: current_user[USER_ID],
        }
    )

    return {
        "message": f"Resource {resource_id} has been deleted from module {agent_id}"
    }
