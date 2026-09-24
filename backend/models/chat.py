from pydantic import BaseModel, Field, validator
from typing import Optional, List
from datetime import datetime

# Request models
class SendMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000)
    customer_email: Optional[str] = Field(None, max_length=255)
    customer_name: Optional[str] = Field(None, max_length=255)
    webhook_url: Optional[str] = Field(None, description="URL where backend should send agent responses")

class ReplyToConversationRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000)
    agent_name: Optional[str] = Field("Support Team", max_length=255)

# Response models
class MessageResponse(BaseModel):
    message_id: str
    sender: str  # "customer" | "agent"
    sender_name: str
    content: str
    read: bool
    created_at: str
    token_count: Optional[int] = None
    duration_ms: Optional[int] = None
    # Only ever set to "failed", and only on an outbound reply whose send
    # raised. None means "no outbound send was attempted or it succeeded".
    delivery_status: Optional[str] = None

class ConversationSummary(BaseModel):
    conversation_id: str
    customer_email: Optional[str]
    customer_name: Optional[str]
    customer_identifier: Optional[str] = None
    status: str  # "open" | "closed" | "waiting_agent_response"
    message_count: int
    unread_count: int
    last_message_at: str
    last_message_preview: str
    created_at: str

class ConversationDetailResponse(BaseModel):
    conversation_id: str
    customer_email: Optional[str]
    customer_name: Optional[str]
    status: str
    message_count: int
    unread_count: int
    created_at: str
    updated_at: str

class SendMessageResponse(BaseModel):
    success: bool
    conversation_id: str
    message_id: str
    created_at: str
    ai_answer: Optional[str] = None

class ListConversationsResponse(BaseModel):
    success: bool
    conversations: List[ConversationSummary]
    total: int
    limit: int
    offset: int

class GetConversationResponse(BaseModel):
    success: bool
    conversation: ConversationDetailResponse
    messages: List[MessageResponse]

class ReplyResponse(BaseModel):
    success: bool
    message_id: str
    conversation_id: str
    created_at: str

class StatusChangeResponse(BaseModel):
    success: bool
    conversation_id: str
    status: str

class ErrorResponse(BaseModel):
    success: bool = False
    error: dict = Field(..., description="Error details")
