from fastapi import APIRouter, HTTPException, Depends
import datetime
import os
import openai
from google.cloud.firestore_v1.base_query import FieldFilter

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
    SCORE,
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
    PAGE,
    LIMIT,
    TOTAL,
)
from src.models.chat import SendMessageModel, CreateChatModel

router = APIRouter()

openai.api_key = os.getenv("OPENAI_API_KEY")

client = openai.OpenAI()


def get_openai_response(message_array: str):
    with client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=message_array,
        stream=True,
    ) as response:
        for chunk in response:
            if chunk.choices[0].delta.content is not None:
                new_text = chunk.choices[0].delta.content
                yield new_text


@router.post("/create", dependencies=[Depends(require_access_level(USER_LEVEL))])
def create_chat(
    request_data: CreateChatModel,
    current_user: dict = Depends(get_current_user),
):
    """
    send message to llm
    """
    agent_query = db.collection(MODULES).document(request_data.agent_id).get()
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

    # Get response from OpenAI
    response_content = "".join(list(get_openai_response([initial_message])))
    response_message = {
        ROLE: SYSTEM,
        CONTENT: response_content,
        ON: datetime.datetime.now().isoformat(),
    }

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
            SCORE: 0,
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
                    SCORE: 0,
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
def create_chat(
    agent_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    send message to llm
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

    if chat_data_query:
        chat_data = chat_data_query[0].to_dict()
        chat_id = chat_data_query[0].id
        current_version = chat_data.get(VERSION)
        chats = sorted(
            chat_data[CHAT][str(current_version)][MESSAGES], key=lambda x: x.get(ON)
        )
        response = {MESSAGES: chats, CHAT_ID: chat_id}

    return {MESSAGE: "Chat created successfully", DATA: response}


@router.post("/message", dependencies=[Depends(require_access_level(USER_LEVEL))])
def send_message(
    request_data: SendMessageModel,
    current_user: dict = Depends(get_current_user),
):
    """
    send message to llm
    """
    # Get chat by ID directly from the request
    chat_ref = db.collection(CHAT).document(request_data.chat_id)
    chat_doc = chat_ref.get()

    if not chat_doc.exists:
        raise HTTPException(status_code=404, detail="Chat not found")

    # Verify the chat belongs to the current user
    chat_data = chat_doc.to_dict()
    if chat_data.get(USER_ID) != current_user.get(USER_ID):
        raise HTTPException(
            status_code=403, detail="Not authorized to access this chat"
        )

    current_version = chat_data.get(VERSION)
    initial_ts = datetime.datetime.now().isoformat()

    # Create user message
    current_message = {
        ROLE: USER,
        CONTENT: request_data.message,
        ON: initial_ts,
    }

    # Get existing messages and add the new one
    messages = chat_data[CHAT][str(current_version)][MESSAGES].copy()
    messages.append(current_message)

    # Get response from OpenAI with all messages
    response_content = "".join(list(get_openai_response(messages)))
    response_message = {
        ROLE: SYSTEM,
        CONTENT: response_content,
        ON: datetime.datetime.now().isoformat(),
    }

    # Update messages in chat data
    chat_data[CHAT][str(current_version)][MESSAGES] = messages + [response_message]
    chat_data[CHAT][str(current_version)][STATUS] = STATUS_IN_PROGRESS
    # Update in database
    chat_ref.set(chat_data)

    return {MESSAGE: "Message sent successfully", DATA: response_message}


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
            if chat_data[CHAT][str(current_version)][STATUS] != status:
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
        chats.append(current_chat)

    return {
        MESSAGE: "Chats retrieved successfully",
        DATA: chats,
        PAGE: page,
        LIMIT: limit,
        TOTAL: len(chats),
    }
