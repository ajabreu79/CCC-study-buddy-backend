from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime


class Message(BaseModel):
    role: str
    content: str
    on: str = Field(default_factory=lambda: datetime.now().isoformat())


class ChatVersion(BaseModel):
    version: int
    score: Optional[float] = None
    progress: Optional[float] = None
    startedAt: str = Field(default_factory=lambda: datetime.now().isoformat())
    closedAt: Optional[str] = None
    messages: List[Message] = []


class Chat(BaseModel):
    agent_id: str
    user_id: str
    chat_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "open"
    current_version: int = 1
    chat: List[ChatVersion]


class ChatCreate(BaseModel):
    agent_id: str
    user_id: str
    initial_message: str


class MessageAdd(BaseModel):
    chat_id: str
    role: str
    content: str


class ChatListResponse(BaseModel):
    chats: List[Dict[str, Any]]


class ChatDetailsResponse(BaseModel):
    chat: Dict[str, Any]


class ChatStatusUpdate(BaseModel):
    chat_id: str
    status: str


class CreateChatModel(BaseModel):
    agent_id: str = Field(..., description="Agent ID of the agent creating the chat")

    @field_validator("agent_id")
    def validate_non_empty(cls, value, field):
        if value is not None and not value.strip():
            raise ValueError(f"{field.name} cannot be empty if provided")
        return value


class SendMessageModel(BaseModel):
    message: str = Field(..., description="Message to be sent")
    chat_id: str = Field(..., description="Chat ID")

    @field_validator("message", "chat_id")
    def validate_non_empty(cls, value, field):
        if value is not None and not value.strip():
            raise ValueError(f"{field.name} cannot be empty if provided")
        return value
