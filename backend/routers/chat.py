"""Chat API endpoints for customer support conversations."""

import logging
from fastapi import APIRouter, Request, HTTPException
from models.chat import (
    SendMessageRequest, ReplyToConversationRequest,
    SendMessageResponse, ListConversationsResponse,
    GetConversationResponse, ReplyResponse, StatusChangeResponse
)
from services.chat_service import ChatService, EmailDeliveryError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/send", response_model=SendMessageResponse)
async def send_message(request: Request, req: SendMessageRequest):
    """Customer sends a message to tenant"""
    try:
        tenant_id = request.state.tenant_id
        logger.info(f"📨 Message received - Tenant: {tenant_id}, Email: {req.customer_email}, Name: {req.customer_name}")
        logger.info(f"   Message: {req.message[:50]}...")
        response = await ChatService.send_message(tenant_id, req)
        logger.info(f"✅ Message saved - ConvID: {response.conversation_id}, MsgID: {response.message_id}")
        return response
    except Exception as e:
        logger.error(f"❌ Error sending message: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error sending message: {str(e)}"
        )


@router.get("/conversations", response_model=ListConversationsResponse)
async def list_conversations(
    request: Request,
    limit: int = 20,
    offset: int = 0,
    status: str = None,
    channel: str = None
):
    """List all conversations for tenant, optionally filtered by channel"""
    try:
        # Validate limit
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        if offset < 0:
            raise ValueError("offset must be >= 0")

        tenant_id = request.state.tenant_id
        response = await ChatService.list_conversations(
            tenant_id,
            limit=limit,
            offset=offset,
            status=status,
            channel=channel
        )
        return response
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error listing conversations: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error listing conversations: {str(e)}"
        )


@router.get("/conversations/{conversation_id}", response_model=GetConversationResponse)
async def get_conversation(
    request: Request,
    conversation_id: str
):
    """Get full conversation thread"""
    try:
        tenant_id = request.state.tenant_id
        response = await ChatService.get_conversation(tenant_id, conversation_id)
        if not response:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving conversation: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving conversation: {str(e)}"
        )


@router.post("/conversations/{conversation_id}/reply", response_model=ReplyResponse)
async def reply_to_conversation(
    request: Request,
    conversation_id: str,
    req: ReplyToConversationRequest
):
    """Agent sends reply to customer"""
    try:
        tenant_id = request.state.tenant_id
        response = await ChatService.reply_to_conversation(
            tenant_id,
            conversation_id,
            req
        )
        if not response:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return response
    except HTTPException:
        raise
    except EmailDeliveryError as e:
        # The reply is saved and stamped delivery_status=failed, but it never
        # reached the customer. 502 rather than 500: the failure is in the
        # upstream mail provider, and the agent must see it as a failed send
        # instead of a silent success.
        logger.error(f"Agent reply saved but email delivery failed: {str(e)}")
        raise HTTPException(
            status_code=502,
            detail="Reply saved but the email could not be sent. Please retry.",
        )
    except Exception as e:
        logger.error(f"Error sending reply: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error sending reply: {str(e)}"
        )


@router.patch("/conversations/{conversation_id}/read")
async def mark_as_read(request: Request, conversation_id: str):
    """Mark conversation messages as read"""
    try:
        tenant_id = request.state.tenant_id
        response = await ChatService.mark_as_read(tenant_id, conversation_id)
        if not response:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error marking as read: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error marking as read: {str(e)}"
        )


@router.patch("/conversations/{conversation_id}/close", response_model=StatusChangeResponse)
async def close_conversation(request: Request, conversation_id: str):
    """Close a conversation"""
    try:
        tenant_id = request.state.tenant_id
        response = await ChatService.update_status(
            tenant_id,
            conversation_id,
            "closed"
        )
        if not response:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error closing conversation: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error closing conversation: {str(e)}"
        )


@router.patch("/conversations/{conversation_id}/reopen", response_model=StatusChangeResponse)
async def reopen_conversation(request: Request, conversation_id: str):
    """Reopen a closed conversation"""
    try:
        tenant_id = request.state.tenant_id
        response = await ChatService.update_status(
            tenant_id,
            conversation_id,
            "open"
        )
        if not response:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reopening conversation: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error reopening conversation: {str(e)}"
        )
