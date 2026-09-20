"""Models package re-exports from chat.py and base models"""
from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel

from .chat import (
    SendMessageRequest,
    ReplyToConversationRequest,
    MessageResponse,
    ConversationSummary,
    ConversationDetailResponse,
    SendMessageResponse,
    ListConversationsResponse,
    GetConversationResponse,
    ReplyResponse,
    StatusChangeResponse,
    ErrorResponse,
)

# Base models needed by routers
class HealthResponse(BaseModel):
    """Health check response"""
    status: Literal["ok", "error"]
    timestamp: datetime
    message: Optional[str] = None

__all__ = [
    "HealthResponse",
    "SendMessageRequest",
    "ReplyToConversationRequest",
    "MessageResponse",
    "ConversationSummary",
    "ConversationDetailResponse",
    "SendMessageResponse",
    "ListConversationsResponse",
    "GetConversationResponse",
    "ReplyResponse",
    "StatusChangeResponse",
    "ErrorResponse",
]
