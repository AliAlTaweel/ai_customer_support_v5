"""Models package re-exports from chat.py and base models"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel

from .chat import (
    ConversationDetailResponse,
    ConversationSummary,
    ErrorResponse,
    GetConversationResponse,
    ListConversationsResponse,
    MessageResponse,
    ReplyResponse,
    ReplyToConversationRequest,
    SendMessageRequest,
    SendMessageResponse,
    StatusChangeResponse,
)


# Base models needed by routers
class HealthResponse(BaseModel):
    """Health check response"""
    status: Literal["ok", "error"]
    timestamp: datetime
    message: str | None = None

__all__ = [
    "ConversationDetailResponse",
    "ConversationSummary",
    "ErrorResponse",
    "GetConversationResponse",
    "HealthResponse",
    "ListConversationsResponse",
    "MessageResponse",
    "ReplyResponse",
    "ReplyToConversationRequest",
    "SendMessageRequest",
    "SendMessageResponse",
    "StatusChangeResponse",
]
