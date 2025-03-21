from pydantic import BaseModel, Field, field_validator


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
