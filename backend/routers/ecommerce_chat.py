"""Synchronous chat relay endpoint for the ecommerce_shop_01 demo integration.

The shop's own /api/chat route (in the ecommerce_shop_01 project) forwards
each signed-in customer's message here with a bearer token and expects the
AI's answer back in the same HTTP response — unlike the widget channel,
which polls for the reply instead.
"""

import bcrypt
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from config import get_settings
from repositories.mongo_client import MongoConnection
from services.chat_service import ChatService
from utils.logger import logger

router = APIRouter()

FALLBACK_MESSAGE = (
    "Thanks for your message — I've noted it and a member of our team "
    "will follow up if needed."
)


class EcommerceChatRequest(BaseModel):
    userId: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1, max_length=5000)


class EcommerceChatResponse(BaseModel):
    message: str


async def _verify_bearer_tenant(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = auth_header[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    db = MongoConnection.get_database()
    tenant_id = None

    if token.startswith("sk_live_") or token.startswith("sk_test_"):
        api_key_doc = await db["tenant_api_keys"].find_one({
            "active": True,
            "api_key_prefix": token[:12],
        })
        if api_key_doc:
            stored_hash = api_key_doc.get("api_key_hash", b"")
            if isinstance(stored_hash, str):
                stored_hash = stored_hash.encode()
            if bcrypt.checkpw(token.encode(), stored_hash):
                tenant_id = api_key_doc["tenant_id"]

    if not tenant_id:
        tenant_doc = await db["tenants"].find_one({"api_key": token, "status": "active"})
        if tenant_doc:
            tenant_id = tenant_doc["tenant_id"]

    if not tenant_id:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return tenant_id


@router.post("/api/ecommerce/chat", response_model=EcommerceChatResponse)
async def ecommerce_chat(request: Request, req: EcommerceChatRequest):
    tenant_id = await _verify_bearer_tenant(request)

    settings = get_settings()
    if not settings.ECOMMERCE_SHOP_TENANT_ID or tenant_id != settings.ECOMMERCE_SHOP_TENANT_ID:
        raise HTTPException(status_code=403, detail="Tenant not configured for the ecommerce channel")

    result = await ChatService.receive_message(
        tenant_id=tenant_id,
        channel="ecommerce",
        customer_identifier=req.userId,
        message=req.message,
    )
    logger.info(f"Ecommerce chat message handled for tenant {tenant_id}, user {req.userId}")

    return EcommerceChatResponse(message=result.ai_answer or FALLBACK_MESSAGE)


@router.get("/api/ecommerce/messages")
async def get_ecommerce_messages(request: Request, userId: str):
    """Retrieve all unread agent replies for an ecommerce customer.
    Used by the shop frontend to fetch support team responses."""
    tenant_id = await _verify_bearer_tenant(request)

    settings = get_settings()
    if not settings.ECOMMERCE_SHOP_TENANT_ID or tenant_id != settings.ECOMMERCE_SHOP_TENANT_ID:
        raise HTTPException(status_code=403, detail="Tenant not configured for the ecommerce channel")

    if not userId or not isinstance(userId, str):
        raise HTTPException(status_code=400, detail="userId is required")

    db = MongoConnection.get_database()

    # Find conversation for this user
    conv_doc = await db["conversations"].find_one({
        "tenant_id": tenant_id,
        "channel": "ecommerce",
        "customer_identifier": userId
    })

    if not conv_doc:
        return {"messages": [], "conversation_id": None}

    conversation_id = conv_doc["conversation_id"]

    # Get all unread agent/AI messages (exclude customer messages)
    messages = await db["messages"].find({
        "conversation_id": conversation_id,
        "tenant_id": tenant_id,
        "sender": {"$in": ["agent", "ai"]},
        "read": False
    }).sort("created_at", 1).to_list(length=None)

    # Mark these messages as read
    if messages:
        await db["messages"].update_many({
            "conversation_id": conversation_id,
            "sender": {"$in": ["agent", "ai"]},
            "read": False
        }, {"$set": {"read": True}})

    return {
        "conversation_id": conversation_id,
        "messages": [
            {
                "message_id": m["message_id"],
                "sender": m["sender"],
                "sender_name": m["sender_name"],
                "content": m["content"],
                "created_at": m["created_at"].isoformat().replace("+00:00", "Z"),
                "token_count": m.get("token_count"),
                "duration_ms": m.get("duration_ms"),
            }
            for m in messages
        ]
    }
