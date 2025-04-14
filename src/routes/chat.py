# Copyright (c) 2024.
"""Chat API routes for the Eaton Call Center system."""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
import datetime
import os
import openai
from google.cloud.firestore_v1.base_query import FieldFilter
from fastapi.responses import StreamingResponse
from typing import List, Dict

from src.utils import generate_uuid, get_current_user, require_access_level
from firebase_config import db
from src.constants import (
    USER_LEVEL,
    AGENT_ID,
    USER_ID,
    STATUS_OPEN,
    STATUS_CLOSED,
    STATUS_IN_PROGRESS,
    STATUS,
    VERSION,
    CRITERIA,
    CHAT,
    STARTED_AT,
    COMPLETED_AT,
    MESSAGES,
    SYSTEM,
    ROLE,
    ON,
    CONTENT,
    MODULES,
    SYSTEM_PROMPT,
    OPENAI_MODEL,
    CHAT_ID,
    USER,
    DATA,
    MESSAGE,
    MODULE_RESOURCES,
    FILE_URL,
    ORIGINAL_FILENAME,
    PAGE,
    LIMIT,
    TOTAL,
)
from src.models.chat import (
    SendMessageModel,
    CreateChatModel,
    SourceDocumentResponse,
    ChatStatusUpdate,
)
from src.services.LangChainHelper import (
    chat_stream_with_retrieve,
    chat_with_rag,
)

router = APIRouter()

openai.api_key = os.getenv("OPENAI_API_KEY")

client = openai.OpenAI()


def validate_message_array(
    message_array: List[Dict[str, str]], chat_id: str, criteria: List[str], version: str
):
    if not isinstance(message_array, list):
        raise ValueError("Message array must be a list")

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    ROLE: USER,
                    CONTENT: f"from the following messages, check the relevant information based on the criteria: {criteria}. The messages are: {message_array}\n\nAnd return the relevant information in a JSON format with the following keys: {criteria}. It can only be true or false.",
                }
            ],
            response_format={"type": "json_object"},
        )

        # Parse the JSON response
        json_response = response.choices[0].message.content

        # Convert the JSON response to a dictionary
        criteria_dict = {}
        for item in criteria:
            criteria_dict[item] = json_response.get(item, False)

        # Update the chat data in Firestore
        chat_ref = db.collection(CHAT).document(chat_id)
        chat_doc = chat_ref.get()
        if chat_doc.exists:
            chat_data = chat_doc.to_dict()
            chat_data[CHAT][str(version)][CRITERIA] = criteria_dict
            chat_ref.set(chat_data)
        else:
            raise ValueError("Chat document not found")

    except Exception as e:
        print(f"Error during GPT query: {e}")


def get_rag_response(
    message_array: List[Dict[str, str]], agent_id: str, use_streaming: bool = True
):
    """Enhanced function for RAG-powered responses

    Args:
        message_array: List of message dictionaries with 'role' and 'content'
        agent_id: The ID of the agent/module to use for RAG context
        use_streaming: Whether to stream the response

    Returns:
        If streaming: Generator yielding response chunks
        If not streaming: Complete response as a string
    """
    # Extract user query (the last user message)
    user_query = ""
    for msg in reversed(message_array):
        if msg.get("role") == USER:
            user_query = msg.get("content", "")
            break

    # If no user query found, use the last message
    if not user_query and message_array:
        user_query = message_array[-1].get("content", "")

    # Get system prompt (if any)
    system_prompt = None
    for msg in message_array:
        if (
            msg.get("role") == SYSTEM
            and "system_prompt" in msg.get("content", "").lower()
        ):
            system_prompt = msg.get("content")
            break

    # Convert to format expected by LangChain
    chat_history = []
    for msg in message_array[:-1]:  # Exclude the last message (which is the query)
        if (
            msg.get("role") != SYSTEM
            or "system_prompt" not in msg.get("content", "").lower()
        ):
            chat_history.append(msg)

    # Generate response using RAG
    if use_streaming:
        return chat_stream_with_retrieve(
            query=user_query,
            agent_id=agent_id,
            chat_history=chat_history,
            system_prompt=system_prompt,
        )
    else:
        result = chat_with_rag(
            query=user_query,
            agent_id=agent_id,
            chat_history=chat_history,
            system_prompt=system_prompt,
        )

        return result["answer"]


@router.post("/create", dependencies=[Depends(require_access_level(USER_LEVEL))])
def create_chat(
    request_data: CreateChatModel,
    current_user: dict = Depends(get_current_user),
):
    """
    Create a new chat session with a module
    """
    agent_query = db.collection(MODULES).document(request_data.agent_id).get()
    if not agent_query.exists:
        raise HTTPException(status_code=404, detail="Module not found")

    agent_data = agent_query.to_dict()

    initial_ts = datetime.datetime.now().isoformat()
    initial_message = {
        ROLE: SYSTEM,
        CONTENT: agent_data.get(SYSTEM_PROMPT),
        ON: initial_ts,
    }

    # Get existing chat or create a new one
    chat_data_query = (
        db.collection(CHAT)
        .where(filter=FieldFilter(AGENT_ID, "==", request_data.agent_id))
        .where(filter=FieldFilter(USER_ID, "==", current_user.get(USER_ID)))
        .limit(1)
        .get()
    )

    # Get response from RAG-enhanced system
    # Use non-streaming for this initial response
    response_content = "".join(
        list(
            get_rag_response(
                message_array=[initial_message],
                agent_id=request_data.agent_id,
                use_streaming=False,
            )
        )
    )

    response_message = {
        ROLE: SYSTEM,
        CONTENT: response_content,
        ON: datetime.datetime.now().isoformat(),
    }

    criteria = agent_data.get(CRITERIA)
    if criteria:
        criteria = {k: False for k in criteria}

    # Prepare chat data
    if chat_data_query:
        chat_data = chat_data_query[0].to_dict()
        chat_id = chat_data_query[0].id
        current_version = chat_data.get(VERSION)

        # Update previous conversation
        chat_data[CHAT][str(current_version)][COMPLETED_AT] = initial_ts
        chat_data[CHAT][str(current_version)][STATUS] = STATUS_CLOSED

        # Increment version
        current_version += 1
        chat_data[VERSION] = current_version

        # Add new conversation
        chat_data[CHAT][str(current_version)] = {
            CRITERIA: criteria,
            STATUS: STATUS_OPEN,
            STARTED_AT: initial_ts,
            COMPLETED_AT: None,
            MESSAGES: [initial_message, response_message],
        }
    else:
        chat_id = generate_uuid()
        current_version = 1
        chat_data = {
            AGENT_ID: request_data.agent_id,
            USER_ID: current_user.get(USER_ID),
            VERSION: current_version,
            CHAT_ID: chat_id,  # Add the chat_id to the document data
            CHAT: {
                str(current_version): {
                    CRITERIA: criteria,
                    STATUS: STATUS_OPEN,
                    STARTED_AT: initial_ts,
                    COMPLETED_AT: None,
                    MESSAGES: [initial_message, response_message],
                }
            },
        }

    # Save to database
    db.collection(CHAT).document(chat_id).set(chat_data)

    return {MESSAGE: "Chat created successfully", CHAT_ID: chat_id}


@router.get(
    "/message/{agent_id}", dependencies=[Depends(require_access_level(USER_LEVEL))]
)
def get_chat(
    agent_id: str,
    criteria: bool = False,
    current_user: dict = Depends(get_current_user),
):
    """
    Get existing chat for a module or create a new one
    """
    if not agent_id:
        raise HTTPException(status_code=400, detail="Agent ID is required")

    # Get existing chat or create a new one
    chat_data_query = (
        db.collection(CHAT)
        .where(filter=FieldFilter(AGENT_ID, "==", agent_id))
        .where(filter=FieldFilter(USER_ID, "==", current_user.get(USER_ID)))
        .limit(1)
        .get()
    )

    response = None
    chats = []
    chat_id = None

    if chat_data_query:

        if criteria:
            # Get criteria from the first chat
            chat_data = chat_data_query[0].to_dict()
            current_version = chat_data.get(VERSION)
            criteria_json = chat_data[CHAT][str(current_version)].get(CRITERIA)
            response = {CHAT_ID: chat_data_query[0].id, CRITERIA: criteria_json}
        else:
            # Get chat messages
            chat_data = chat_data_query[0].to_dict()
            current_version = chat_data.get(VERSION)
            chats = sorted(
                chat_data[CHAT][str(current_version)][MESSAGES], key=lambda x: x.get(ON)
            )
            response = {MESSAGES: chats, CHAT_ID: chat_data_query[0].id}

    return {MESSAGE: "Chat retrieved successfully", DATA: response}


@router.post("/message", dependencies=[Depends(require_access_level(USER_LEVEL))])
def send_message(
    request_data: SendMessageModel,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    """
    Send a message to the chat with RAG-enhanced responses
    """
    chat_ref = db.collection(CHAT).document(request_data.chat_id)
    chat_doc = chat_ref.get()

    if not chat_doc.exists:
        raise HTTPException(status_code=404, detail="Chat not found")

    chat_data = chat_doc.to_dict()
    current_version = chat_data.get(VERSION)

    # Add user message
    current_message = {
        ROLE: USER,
        CONTENT: request_data.message,
        ON: datetime.datetime.now().isoformat(),
    }

    # Get current messages
    messages = chat_data[CHAT][str(current_version)][MESSAGES].copy()
    messages.append(current_message)

    # Get agent_id for RAG context retrieval
    agent_id = chat_data.get(AGENT_ID)

    # Get response from RAG-enhanced system
    response_content = "".join(
        list(get_rag_response(message_array=messages, agent_id=agent_id))
    )

    # Create response message with timestamp
    response_message = {
        ROLE: SYSTEM,
        CONTENT: response_content,
        ON: datetime.datetime.now().isoformat(),
    }

    # Store sources if available (extract from response format)
    sources = []
    if "Sources:" in response_content:
        try:
            # Extract source citations from the end of the response
            response_parts = response_content.split("\n\nSources:\n")
            if len(response_parts) > 1:
                # Clean response content by removing sources
                clean_response = response_parts[0]

                # Extract sources
                sources_text = response_parts[1]
                source_lines = sources_text.strip().split("\n")

                # Parse sources
                for line in source_lines:
                    if line.strip():
                        # Source format: [1] Document name
                        # or: [1] file.pdf - page 3
                        if "]" in line:
                            source_name = line.split("]", 1)[1].strip()
                            sources.append(source_name)

                # Update response message with clean content
                response_message[CONTENT] = clean_response

                # Add sources metadata
                response_message["sources"] = sources
        except Exception as e:
            print(f"Error extracting sources: {e}")

    # Update messages in chat data
    chat_data[CHAT][str(current_version)][MESSAGES] = messages + [response_message]
    chat_data[CHAT][str(current_version)][STATUS] = STATUS_IN_PROGRESS
    # Update in database
    chat_ref.set(chat_data)

    criteria = list(chat_data[CHAT][str(current_version)].get(CRITERIA).keys())

    background_tasks.add_task(
        validate_message_array,
        messages + [response_message],
        request_data.chat_id,
        criteria,
        current_version,
    )

    return {MESSAGE: "Message sent successfully", DATA: response_message}


@router.post(
    "/stream-message", dependencies=[Depends(require_access_level(USER_LEVEL))]
)
async def stream_message(
    request_data: SendMessageModel,
    current_user: dict = Depends(get_current_user),
):
    """
    Stream a RAG-enhanced response to a user message
    """
    chat_ref = db.collection(CHAT).document(request_data.chat_id)
    chat_doc = chat_ref.get()

    if not chat_doc.exists:
        raise HTTPException(status_code=404, detail="Chat not found")

    chat_data = chat_doc.to_dict()
    current_version = chat_data.get(VERSION)
    agent_id = chat_data.get(AGENT_ID)

    # Add user message
    current_message = {
        ROLE: USER,
        CONTENT: request_data.message,
        ON: datetime.datetime.now().isoformat(),
    }

    # Get current messages
    messages = chat_data[CHAT][str(current_version)][MESSAGES].copy()
    messages.append(current_message)

    # First save the user message to the database
    updated_messages = messages.copy()
    chat_data[CHAT][str(current_version)][MESSAGES] = updated_messages
    chat_ref.set(chat_data)

    # Function to stream response and update database when done
    async def stream_and_save():
        response_content = ""
        response_time = datetime.datetime.now().isoformat()

        # Stream the response
        for chunk in get_rag_response(message_array=messages, agent_id=agent_id):
            response_content += chunk
            yield f"data: {chunk}\n\n"

        # Create response message
        response_message = {
            ROLE: SYSTEM,
            CONTENT: response_content,
            ON: response_time,
        }

        # Extract sources if available
        sources = []
        if "Sources:" in response_content:
            try:
                # Extract source citations
                response_parts = response_content.split("\n\nSources:\n")
                if len(response_parts) > 1:
                    # Clean response for display
                    clean_response = response_parts[0]
                    sources_text = response_parts[1]
                    source_lines = sources_text.strip().split("\n")

                    for line in source_lines:
                        if line.strip():
                            if "]" in line:
                                source_name = line.split("]", 1)[1].strip()
                                sources.append(source_name)

                    response_message[CONTENT] = clean_response
                    response_message["sources"] = sources
            except Exception as e:
                print(f"Error extracting sources: {e}")

        # Update in database
        try:
            # Get latest chat data
            chat_doc = chat_ref.get()
            if chat_doc.exists:
                chat_data = chat_doc.to_dict()
                chat_data[CHAT][str(current_version)][MESSAGES] = updated_messages + [
                    response_message
                ]
                chat_ref.set(chat_data)
        except Exception as e:
            print(f"Error updating chat in database: {e}")

        yield "data: [DONE]\n\n"

    # Return streaming response
    return StreamingResponse(stream_and_save(), media_type="text/event-stream")


@router.get(
    "/sources/{chat_id}/{message_index}",
    dependencies=[Depends(require_access_level(USER_LEVEL))],
    response_model=SourceDocumentResponse,
)
async def get_message_sources(
    chat_id: str,
    message_index: int,
    current_user: dict = Depends(get_current_user),
):
    """
    Retrieve source documents for a specific message in a chat

    Args:
        chat_id: The ID of the chat
        message_index: The index of the message in the messages array

    Returns:
        Source document information
    """
    # Get chat
    chat_ref = db.collection(CHAT).document(chat_id)
    chat_doc = chat_ref.get()

    if not chat_doc.exists:
        raise HTTPException(status_code=404, detail="Chat not found")

    chat_data = chat_doc.to_dict()

    # Check access permission
    if chat_data.get(USER_ID) != current_user[USER_ID]:
        raise HTTPException(
            status_code=403, detail="You don't have permission to access this chat"
        )

    # Get current version
    current_version = chat_data.get(VERSION)

    # Get messages
    messages = chat_data[CHAT][str(current_version)].get(MESSAGES, [])

    # Check if message index is valid
    if message_index < 0 or message_index >= len(messages):
        raise HTTPException(status_code=400, detail="Invalid message index")

    message = messages[message_index]

    # Check if message has sources
    sources = message.get("sources", [])
    if not sources:
        return {"chat_id": chat_id, "message_index": message_index, "sources": []}

    # Get source documents from resources collection
    source_docs = []
    agent_id = chat_data.get(AGENT_ID)

    # Query resources for this module
    resource_query = (
        db.collection(MODULE_RESOURCES)
        .where(filter=FieldFilter(AGENT_ID, "==", agent_id))
        .get()
    )

    # Map resources for lookup
    resources_map = {doc.id: doc.to_dict() for doc in resource_query}

    # Collect source information
    for source in sources:
        # Try to match source with resource names
        for resource_id, resource_data in resources_map.items():
            filename = resource_data.get(ORIGINAL_FILENAME, "")
            if filename in source:
                source_docs.append(
                    {
                        "resource_id": resource_id,
                        "file_name": filename,
                        "file_url": resource_data.get(FILE_URL),
                        "source_text": source,
                    }
                )
                break
        else:
            # If no match found, add with limited info
            source_docs.append(
                {
                    "resource_id": None,
                    "file_name": source,
                    "file_url": None,
                    "source_text": source,
                }
            )

    return {"chat_id": chat_id, "message_index": message_index, "sources": source_docs}


@router.get("/list", dependencies=[Depends(require_access_level(USER_LEVEL))])
def list_chats(
    current_user: dict = Depends(get_current_user),
    status: str = None,
    page: int = 1,
    limit: int = 10,
):
    """
    List all chats for the current user
    """
    chat_data_query = (
        db.collection(CHAT)
        .where(filter=FieldFilter(USER_ID, "==", current_user.get(USER_ID)))
        .limit(limit)
        .offset((page - 1) * limit)
        .stream()
    )

    chats = []
    for chat in chat_data_query:
        chat_data = chat.to_dict()
        chat_id = chat.id
        current_version = chat_data.get(VERSION)

        if status:
            if chat_data[CHAT][str(current_version)].get(STATUS) != status:
                continue

        # Get the last message
        current_chat = chat_data[CHAT][str(current_version)]
        all_messages = chat_data[CHAT][str(current_version)][MESSAGES]
        sorted_messages = sorted(all_messages, key=lambda x: x.get("on"))
        last_five_messages = (
            sorted_messages[-5:] if len(sorted_messages) > 5 else sorted_messages
        )
        current_chat[MESSAGES] = last_five_messages
        current_chat[CHAT_ID] = chat_id
        current_chat[VERSION] = current_version
        current_chat[AGENT_ID] = chat_data.get(AGENT_ID)
        chats.append(current_chat)

    return {
        MESSAGE: "Chats retrieved successfully",
        DATA: chats,
        PAGE: page,
        LIMIT: limit,
        TOTAL: len(chats),
    }


@router.put(
    "/status/{chat_id}", dependencies=[Depends(require_access_level(USER_LEVEL))]
)
def update_chat_status(
    chat_id: str,
    status_update: ChatStatusUpdate,
    current_user: dict = Depends(get_current_user),
):
    """
    Update the status of a chat (open, closed, etc.)

    Args:
        chat_id: The ID of the chat to update
        status_update: The new status data

    Returns:
        Success message and chat ID
    """
    # Get chat document
    chat_ref = db.collection(CHAT).document(chat_id)
    chat_doc = chat_ref.get()

    if not chat_doc.exists:
        raise HTTPException(status_code=404, detail="Chat not found")

    chat_data = chat_doc.to_dict()

    # Check access permission
    if chat_data.get(USER_ID) != current_user[USER_ID]:
        raise HTTPException(
            status_code=403, detail="You don't have permission to modify this chat"
        )

    # Validate status value
    new_status = status_update.status.lower()
    valid_statuses = [STATUS_OPEN, STATUS_CLOSED, STATUS_IN_PROGRESS]
    if new_status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status value. Must be one of: {', '.join(valid_statuses)}",
        )

    # Get current version and update status
    current_version = chat_data.get(VERSION)

    # Update fields based on status
    update_data = {
        f"{CHAT}.{current_version}.{STATUS}": new_status,
    }

    # If closing the chat, add completion timestamp
    if new_status == STATUS_CLOSED:
        update_data[f"{CHAT}.{current_version}.{COMPLETED_AT}"] = (
            datetime.datetime.now().isoformat()
        )

    # Update the document
    chat_ref.update(update_data)

    return {"message": "Chat status updated successfully", "chat_id": chat_id}
