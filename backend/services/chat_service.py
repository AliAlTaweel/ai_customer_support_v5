"""Chat service for business logic operations."""

from datetime import datetime, timezone
import uuid
from typing import Optional, List, Dict, Any
from models.chat import (
    SendMessageRequest, ReplyToConversationRequest,
    SendMessageResponse, ListConversationsResponse,
    ConversationSummary, GetConversationResponse,
    ConversationDetailResponse, MessageResponse, ReplyResponse,
    StatusChangeResponse
)
from repositories.mongo_client import MongoConnection
from utils.logger import logger
from utils.logging_setup import setup_chat_logger, setup_ai_logger
from services.kb_service import KBService
from services.ai_reply_service import AIReplyService

# Dedicated loggers for chat and AI operations
chat_logger = setup_chat_logger()
ai_logger = setup_ai_logger()


def _gmail_client_factory():
    """Indirection so tests can inject a fake Gmail client."""
    from services.gmail_client import GmailClient
    return GmailClient.from_settings()


class ChatService:
    """Business logic for customer chat API"""

    @staticmethod
    def _get_db():
        """Get MongoDB database"""
        return MongoConnection.get_database()

    @staticmethod
    async def receive_message(
        tenant_id: str,
        channel: str,
        customer_identifier: Optional[str],
        message: str,
        customer_name: Optional[str] = None,
        webhook_url: Optional[str] = None,
        email_thread_id: Optional[str] = None,
        email_headers: Optional[Dict[str, str]] = None,
        whatsapp_message_id: Optional[str] = None,
    ) -> SendMessageResponse:
        """Ingest a customer message from any channel (widget, email, whatsapp),
        creating or reusing a conversation, then triggering an AI reply."""
        db = ChatService._get_db()

        conversation_id = None
        if customer_identifier:
            if channel == "widget":
                # Conversations created before the channel field existed have no
                # "channel" key at all -- treat those as widget conversations too.
                query = {
                    "tenant_id": tenant_id,
                    "customer_email": customer_identifier,
                    "channel": {"$in": ["widget", None]},
                }
            else:
                query = {
                    "tenant_id": tenant_id,
                    "channel": channel,
                    "customer_identifier": customer_identifier,
                }
            existing = await db["conversations"].find_one(query)
            if existing:
                conversation_id = existing["conversation_id"]
                logger.info(f"   Found existing {channel} conversation: {conversation_id}")

        now = datetime.now(timezone.utc)

        if not conversation_id:
            conversation_id = f"conv_{uuid.uuid4().hex[:24]}"
            conversation_doc = {
                "conversation_id": conversation_id,
                "tenant_id": tenant_id,
                "channel": channel,
                "customer_identifier": customer_identifier,
                "customer_email": customer_identifier if channel in ("widget", "email") else None,
                "customer_name": customer_name,
                "status": "open",
                "handling_mode": "ai",
                "created_at": now,
                "updated_at": now,
                "last_message_at": now,
                "message_count": 0,
                "last_message_preview": message[:100],
                "unread_count": 0,
            }
            if webhook_url:
                conversation_doc["webhook_url"] = webhook_url
            if email_thread_id:
                conversation_doc["email_thread_id"] = email_thread_id
            if email_headers:
                conversation_doc["last_email_message_id"] = email_headers.get("message_id")
                conversation_doc["last_email_subject"] = email_headers.get("subject")
            if whatsapp_message_id:
                conversation_doc["whatsapp_message_id"] = whatsapp_message_id

            result = await db["conversations"].insert_one(conversation_doc)
            logger.info(f"   Created new {channel} conversation: {conversation_id} (ID: {result.inserted_id})")
        else:
            updates = {}
            if webhook_url:
                updates["webhook_url"] = webhook_url
            if email_thread_id:
                updates["email_thread_id"] = email_thread_id
            if email_headers:
                updates["last_email_message_id"] = email_headers.get("message_id")
                updates["last_email_subject"] = email_headers.get("subject")
            if whatsapp_message_id:
                updates["whatsapp_message_id"] = whatsapp_message_id
            if updates:
                await db["conversations"].update_one({"conversation_id": conversation_id}, {"$set": updates})

        message_id = f"msg_{uuid.uuid4().hex[:12]}"
        result = await db["messages"].insert_one({
            "message_id": message_id,
            "conversation_id": conversation_id,
            "tenant_id": tenant_id,
            "sender": "customer",
            "sender_name": customer_name or "Customer",
            "content": message,
            "read": False,
            "created_at": now
        })
        chat_logger.info(f"📨 Customer message saved | Conv: {conversation_id} | User: {customer_identifier} | Channel: {channel} | MsgID: {message_id}")

        await db["conversations"].update_one(
            {"conversation_id": conversation_id},
            {
                "$set": {
                    "updated_at": now,
                    "last_message_at": now,
                    "last_message_preview": message[:100],
                    "status": "waiting_agent_response"
                },
                "$inc": {
                    "message_count": 1,
                    "unread_count": 1
                }
            }
        )

        chat_logger.info(f"📬 Conversation updated | Conv: {conversation_id} | Status: waiting_agent_response | Unread: +1")

        ai_answer = await ChatService._maybe_generate_ai_reply(tenant_id, conversation_id, message)

        return SendMessageResponse(
            success=True,
            conversation_id=conversation_id,
            message_id=message_id,
            created_at=now.isoformat().replace("+00:00", "Z"),
            ai_answer=ai_answer,
        )

    @staticmethod
    async def send_message(
        tenant_id: str,
        req: SendMessageRequest
    ) -> SendMessageResponse:
        """Customer sends a widget message, creates conversation if needed.
        Thin wrapper over receive_message, kept for the existing /api/chat/send
        endpoint and its request/response shape."""
        return await ChatService.receive_message(
            tenant_id=tenant_id,
            channel="widget",
            customer_identifier=req.customer_email,
            message=req.message,
            customer_name=req.customer_name,
            webhook_url=req.webhook_url,
        )

    @staticmethod
    async def _maybe_generate_ai_reply(tenant_id: str, conversation_id: str, customer_message: str) -> Optional[str]:
        """If the conversation is still AI-handled and the tenant has AI enabled with
        either knowledge base content or a live Shopify/ecommerce connection, generate
        an AI reply or escalate to a human. On success, dispatch the reply to the
        conversation's channel (email/whatsapp send, or no-op for widget/ecommerce,
        which return the answer synchronously to their own caller instead) and
        return the answer text so a synchronous caller can use it directly."""
        db = ChatService._get_db()

        conv_doc = await db["conversations"].find_one({"conversation_id": conversation_id})
        if not conv_doc:
            logger.info(f"🔍 AI reply skipped: conversation {conversation_id} not found")
            return None

        handling_mode = conv_doc.get("handling_mode", "ai")
        if handling_mode != "ai":
            ai_logger.info(f"⏭️  AI SKIPPED | Conv: {conversation_id} | Reason: handling_mode={handling_mode} (not 'ai')")
            return None

        ai_enabled = await KBService.get_ai_enabled(tenant_id)
        if not ai_enabled:
            ai_logger.info(f"⏭️  AI SKIPPED | Tenant: {tenant_id} | Reason: ai_enabled=False")
            return None

        can_use_ai = await AIReplyService.tenant_can_use_ai(tenant_id)
        if not can_use_ai:
            ai_logger.info(f"⏭️  AI SKIPPED | Tenant: {tenant_id} | Reason: no KB content or connections")
            return None

        result = await AIReplyService.generate_reply(
            tenant_id, customer_message, customer_identifier=conv_doc.get("customer_identifier")
        )
        now = datetime.now(timezone.utc)

        if result.answered:
            ai_message_id = f"msg_{uuid.uuid4().hex[:12]}"
            await db["messages"].insert_one({
                "message_id": ai_message_id,
                "conversation_id": conversation_id,
                "tenant_id": tenant_id,
                "sender": "ai",
                "sender_name": "AI Assistant",
                "content": result.answer,
                "redacted_input": result.redacted_input,
                "read": True,
                "created_at": now,
                "token_count": result.token_count,
                "duration_ms": result.duration_ms,
            })
            await db["conversations"].update_one(
                {"conversation_id": conversation_id},
                {
                    "$set": {
                        "updated_at": now,
                        "last_message_at": now,
                        "last_message_preview": result.answer[:100],
                        "status": "open"
                    },
                    "$inc": {"message_count": 1}
                }
            )
            ai_logger.info(f"✅ AI ANSWERED | Conv: {conversation_id} | Tokens: {result.token_count} | Duration: {result.duration_ms}ms")
            await ChatService._deliver_reply(conv_doc, result.answer)
            return result.answer
        else:
            await db["conversations"].update_one(
                {"conversation_id": conversation_id},
                {
                    "$set": {
                        "handling_mode": "human",
                        "status": "waiting_agent_response",
                        "updated_at": now
                    }
                }
            )
            ai_logger.info(f"🔄 AI ESCALATED | Conv: {conversation_id} | Reason: {result.escalate_reason}")
            return None

    @staticmethod
    async def _deliver_reply(conv_doc: Dict[str, Any], reply_text: str) -> None:
        """Dispatch an AI/agent reply to the conversation's channel.

        Widget and ecommerce replies are retrieved by the frontend via polling
        or the synchronous response, so they need no outbound send. Email
        replies must actually be mailed.
        """
        channel = conv_doc.get("channel", "widget")
        conversation_id = conv_doc.get("conversation_id")

        if channel != "email":
            logger.info(
                f"⏭️  No outbound delivery needed for {channel} channel "
                f"(frontend/polling will retrieve) | Conv: {conversation_id}"
            )
            return

        from config import get_settings
        settings = get_settings()

        to_address = conv_doc.get("customer_identifier") or conv_doc.get("customer_email")
        if not to_address:
            logger.error(f"✗ Email reply has no recipient | Conv: {conversation_id}")
            return

        if settings.GMAIL_DRY_RUN:
            logger.info(
                f"🧪 DRY RUN — would email {to_address} | Conv: {conversation_id}\n"
                f"{reply_text}"
            )
            return

        try:
            client = _gmail_client_factory()
            await client.send_reply(
                to=to_address,
                subject=conv_doc.get("last_email_subject", "") or "Your support request",
                body=reply_text,
                thread_id=conv_doc.get("email_thread_id", ""),
                in_reply_to=conv_doc.get("last_email_message_id"),
                references=conv_doc.get("last_email_message_id"),
            )
            logger.info(f"📧 Email reply sent to {to_address} | Conv: {conversation_id}")
        except Exception as e:
            # The reply is already persisted and visible in the UI; a delivery
            # failure must not break the pipeline.
            logger.error(f"✗ Failed to send email reply | Conv: {conversation_id} | {e}")

    @staticmethod
    async def list_conversations(
        tenant_id: str,
        limit: int = 20,
        offset: int = 0,
        status: Optional[str] = None,
        channel: Optional[str] = None
    ) -> ListConversationsResponse:
        """List all conversations for tenant with pagination"""
        db = ChatService._get_db()

        query = {"tenant_id": tenant_id}
        if status:
            query["status"] = status
        if channel:
            # Conversations created before the channel field existed have no
            # "channel" key -- treat those as "widget" too.
            query["channel"] = {"$in": ["widget", None]} if channel == "widget" else channel

        total = await db["conversations"].count_documents(query)
        docs = await db["conversations"].find(query) \
            .sort("created_at", -1) \
            .skip(offset) \
            .limit(limit) \
            .to_list(length=limit)

        conversations = [
            ConversationSummary(
                conversation_id=doc["conversation_id"],
                customer_email=doc.get("customer_email"),
                customer_name=doc.get("customer_name"),
                customer_identifier=doc.get("customer_identifier"),
                status=doc["status"],
                message_count=doc["message_count"],
                unread_count=doc["unread_count"],
                last_message_at=doc["last_message_at"].isoformat().replace("+00:00", "Z"),
                last_message_preview=doc["last_message_preview"],
                created_at=doc["created_at"].isoformat().replace("+00:00", "Z")
            )
            for doc in docs
        ]

        logger.info(f"Listed {len(conversations)} conversations for tenant {tenant_id}")

        return ListConversationsResponse(
            success=True,
            conversations=conversations,
            total=total,
            limit=limit,
            offset=offset
        )

    @staticmethod
    async def get_conversation(
        tenant_id: str,
        conversation_id: str
    ) -> Optional[GetConversationResponse]:
        """Get full conversation thread"""
        db = ChatService._get_db()

        # Verify conversation belongs to tenant
        conv_doc = await db["conversations"].find_one({
            "conversation_id": conversation_id,
            "tenant_id": tenant_id
        })
        if not conv_doc:
            return None  # Will be handled by endpoint as 404

        # Get all messages
        messages_docs = await db["messages"].find({
            "conversation_id": conversation_id,
            "tenant_id": tenant_id
        }).sort("created_at", 1).to_list(length=None)

        messages = [
            MessageResponse(
                message_id=doc["message_id"],
                sender=doc["sender"],
                sender_name=doc["sender_name"],
                content=doc["content"],
                read=doc["read"],
                created_at=doc["created_at"].isoformat().replace("+00:00", "Z"),
                token_count=doc.get("token_count"),
                duration_ms=doc.get("duration_ms"),
            )
            for doc in messages_docs
        ]

        conversation = ConversationDetailResponse(
            conversation_id=conv_doc["conversation_id"],
            customer_email=conv_doc.get("customer_email"),
            customer_name=conv_doc.get("customer_name"),
            status=conv_doc["status"],
            message_count=conv_doc["message_count"],
            unread_count=conv_doc["unread_count"],
            created_at=conv_doc["created_at"].isoformat().replace("+00:00", "Z"),
            updated_at=conv_doc["updated_at"].isoformat().replace("+00:00", "Z")
        )

        logger.info(f"Retrieved conversation {conversation_id} for tenant {tenant_id}")

        return GetConversationResponse(
            success=True,
            conversation=conversation,
            messages=messages
        )

    @staticmethod
    async def reply_to_conversation(
        tenant_id: str,
        conversation_id: str,
        req: ReplyToConversationRequest
    ) -> Optional[ReplyResponse]:
        """Agent sends reply to conversation"""
        import aiohttp

        db = ChatService._get_db()

        # Verify conversation exists and belongs to tenant
        conv_doc = await db["conversations"].find_one({
            "conversation_id": conversation_id,
            "tenant_id": tenant_id
        })
        if not conv_doc:
            logger.warning(f"Conversation {conversation_id} not found for tenant {tenant_id}")
            return None

        # Create message
        message_id = f"msg_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)
        # For ecommerce channel, agent replies should be unread until the client polls
        # For other channels (email/whatsapp), they're immediately delivered so marked as read
        is_read = conv_doc.get("channel") != "ecommerce"
        await db["messages"].insert_one({
            "message_id": message_id,
            "conversation_id": conversation_id,
            "tenant_id": tenant_id,
            "sender": "agent",
            "sender_name": req.agent_name,
            "content": req.message,
            "read": is_read,
            "created_at": now
        })
        channel = conv_doc.get("channel", "widget")
        read_status = "✓ Read" if is_read else "⏳ Unread (awaiting client poll)"
        chat_logger.info(f"👨‍💼 Agent reply saved | Conv: {conversation_id} | Agent: {req.agent_name} | Channel: {channel} | Status: {read_status}")

        # Update conversation
        await db["conversations"].update_one(
            {"conversation_id": conversation_id},
            {
                "$set": {
                    "updated_at": now,
                    "last_message_at": now,
                    "last_message_preview": req.message[:100],
                    "status": "open",
                    "handling_mode": "human"
                },
                "$inc": {"message_count": 1}
            }
        )

        logger.info(f"Agent reply sent to conversation {conversation_id} by tenant {tenant_id}")

        # Send webhook to client if webhook_url is registered
        webhook_url = conv_doc.get("webhook_url")
        if webhook_url:
            try:
                async with aiohttp.ClientSession() as session:
                    webhook_payload = {
                        "conversation_id": conversation_id,
                        "message_id": message_id,
                        "sender": "agent",
                        "content": req.message,
                        "agent_name": req.agent_name,
                        "created_at": now.isoformat().replace("+00:00", "Z")
                    }
                    async with session.post(webhook_url, json=webhook_payload) as resp:
                        if resp.status == 200:
                            logger.info(f"✅ Webhook sent to {webhook_url} for conversation {conversation_id}")
                        else:
                            logger.warning(f"⚠️ Webhook failed ({resp.status}) for {webhook_url}: {await resp.text()}")
            except Exception as e:
                logger.error(f"❌ Error sending webhook to {webhook_url}: {str(e)}")

        return ReplyResponse(
            success=True,
            message_id=message_id,
            conversation_id=conversation_id,
            created_at=now.isoformat().replace("+00:00", "Z")
        )

    @staticmethod
    async def mark_as_read(
        tenant_id: str,
        conversation_id: str
    ) -> Optional[Dict[str, Any]]:
        """Mark all messages in conversation as read"""
        db = ChatService._get_db()

        # Verify conversation and belongs to tenant
        conv_doc = await db["conversations"].find_one({
            "conversation_id": conversation_id,
            "tenant_id": tenant_id
        })
        if not conv_doc:
            logger.warning(f"Conversation {conversation_id} not found for tenant {tenant_id}")
            return None

        # Mark messages as read
        await db["messages"].update_many(
            {
                "conversation_id": conversation_id,
                "tenant_id": tenant_id,
                "sender": "customer"
            },
            {"$set": {"read": True}}
        )

        # Reset unread count
        await db["conversations"].update_one(
            {"conversation_id": conversation_id},
            {"$set": {"unread_count": 0}}
        )

        logger.info(f"Marked conversation {conversation_id} as read for tenant {tenant_id}")

        return {"success": True, "unread_count": 0}

    @staticmethod
    async def update_status(
        tenant_id: str,
        conversation_id: str,
        new_status: str
    ) -> Optional[StatusChangeResponse]:
        """Update conversation status"""
        db = ChatService._get_db()

        # Verify conversation and belongs to tenant
        conv_doc = await db["conversations"].find_one({
            "conversation_id": conversation_id,
            "tenant_id": tenant_id
        })
        if not conv_doc:
            logger.warning(f"Conversation {conversation_id} not found for tenant {tenant_id}")
            return None

        # Update status
        await db["conversations"].update_one(
            {"conversation_id": conversation_id},
            {
                "$set": {
                    "status": new_status,
                    "updated_at": datetime.now(timezone.utc)
                }
            }
        )

        logger.info(f"Status updated to {new_status} for conversation {conversation_id} by tenant {tenant_id}")

        return StatusChangeResponse(
            success=True,
            conversation_id=conversation_id,
            status=new_status
        )
