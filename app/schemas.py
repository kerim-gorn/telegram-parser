from typing import Optional, Union
from datetime import datetime

from pydantic import BaseModel, Field


class ChatHistoryRequest(BaseModel):
    account_phone: str = Field(..., description="Account phone used as session key in Redis")
    chat_entity: Union[int, str] = Field(
        ..., description="Chat ID/username/invite link to fetch history for"
    )
    days: Optional[int] = Field(
        default=7, description="How many days back to fetch (from now)"
    )


class ScheduleResponse(BaseModel):
    task_id: str
    status: str = "scheduled"


class ParsedMessage(BaseModel):
    """
    Pydantic schema for parsed Telegram message.
    """
    message_id: int
    chat_id: int
    sender_username: Optional[str] = None
    chat_username: Optional[str] = None
    text: Optional[str] = None
    sender_id: Optional[int] = None
    message_date: datetime

