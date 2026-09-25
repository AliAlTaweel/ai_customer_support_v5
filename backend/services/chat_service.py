"""Chat service: orchestrates the customer chat API. Persistence lives in
ConversationRepository, outbound dispatch in ReplyDeliveryService -- this
module decides *what* should happen and in what order."""

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
from repositories.conversation_repository import ConversationRepository
from utils.logger import logger
from utils.logging_setup import setup_chat_logger, setup_ai_logger
from services.tenant_settings_service import TenantSettingsService
from services.ai_reply_service import AIReplyService
from services.reply_delivery_service import EmailDeliveryError, ReplyDeliveryService

__all__ = ["ChatService", "EmailDeliveryError"]

# Dedicated loggers for chat and AI operations
chat_logger = setup_chat_logger()
ai_logger = setup_ai_logger()


class ChatService:
    """Business logic for customer chat API"""

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
            existing = await ConversationRepository.find_conversation(query)
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

            inserted_id = await ConversationRepository.insert_conversation(conversation_doc)
            logger.info(f"   Created new {channel} conversation: {conversation_id} (ID: {inserted_id})")
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
                await ConversationRepository.update_conversation(conversation_id, set_fields=updates)

        message_id = f"msg_{uuid.uuid4().hex[:12]}"
        await ConversationRepository.insert_message({
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

        await ConversationRepository.update_conversation(
            conversation_id,
            set_fields={
                "updated_at": now,
                "last_message_at": now,
                "last_message_preview": message[:100],
                "status": "waiting_agent_response",
            },
            inc_fields={
                "message_count": 1,
                "unread_count": 1,
            },
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
        conv_doc = await ConversationRepository.find_conversation({"conversation_id": conversation_id})
        if not conv_doc:
            logger.info(f"🔍 AI reply skipped: conversation {conversation_id} not found")
            return None

        handling_mode = conv_doc.get("handling_mode", "ai")
        if handling_mode != "ai":
            ai_logger.info(f"⏭️  AI SKIPPED | Conv: {conversation_id} | Reason: handling_mode={handling_mode} (not 'ai')")
            return None

        ai_enabled = await TenantSettingsService.get_ai_enabled(tenant_id)
        if not ai_enabled:
            ai_logger.info(f"⏭️  AI SKIPPED | Tenant: {tenant_id} | Reason: ai_enabled=False")
            return None

        can_use_ai = await AIReplyService.tenant_can_use_ai(tenant_id)
        if not can_use_ai:
            ai_logger.info(f"⏭️  AI SKIPPED | Tenant: {tenant_id} | Reason: no KB content or connections")
            return None

        # Prompt boundary. The email body is stored raw (so the thread and its
        # preview show the customer's actual words), and the untrusted-content
        # delimiters are added here, on the way to the model and nowhere else.
        prompt_message = customer_message
        if conv_doc.get("channel") == "email":
            from services.email_gates import wrap_untrusted_body
            prompt_message = wrap_untrusted_body(customer_message)

        result = await AIReplyService.generate_reply(
            tenant_id, prompt_message, customer_identifier=conv_doc.get("customer_identifier")
        )
        now = datetime.now(timezone.utc)

        if result.answered:
            ai_message_id = f"msg_{uuid.uuid4().hex[:12]}"
            await ConversationRepository.insert_message({
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
            await ConversationRepository.update_conversation(
                conversation_id,
                set_fields={
                    "updated_at": now,
                    "last_message_at": now,
                    "last_message_preview": result.answer[:100],
                    "status": "open",
                },
                inc_fields={"message_count": 1},
            )
            ai_logger.info(f"✅ AI ANSWERED | Conv: {conversation_id} | Tokens: {result.token_count} | Duration: {result.duration_ms}ms")
            try:
                await ReplyDeliveryService.deliver_reply(conv_doc, result.answer)
            except EmailDeliveryError:
                # The message row is already written, so without this marker
                # the Emails tab shows an ordinary sent bubble for a reply the
                # customer never received. Re-raise so the ingestion pipeline
                # still records delivery_failed.
                await ConversationRepository.mark_message(ai_message_id, {"delivery_status": "failed"})
                chat_logger.warning(f"⚠️  Message {ai_message_id} marked delivery_status=failed")
                raise
            return result.answer
        else:
            await ConversationRepository.update_conversation(
                conversation_id,
                set_fields={
                    "handling_mode": "human",
                    "status": "waiting_agent_response",
                    "updated_at": now,
                },
            )
            ai_logger.info(f"🔄 AI ESCALATED | Conv: {conversation_id} | Reason: {result.escalate_reason}")
            return None

    @staticmethod
    async def list_conversations(
        tenant_id: str,
        limit: int = 20,
        offset: int = 0,
        status: Optional[str] = None,
        channel: Optional[str] = None
    ) -> ListConversationsResponse:
        """List all conversations for tenant with pagination"""
        query = {"tenant_id": tenant_id}
        if status:
            query["status"] = status
        if channel:
            # Conversations created before the channel field existed have no
            # "channel" key -- treat those as "widget" too.
            query["channel"] = {"$in": ["widget", None]} if channel == "widget" else channel

        docs, total = await ConversationRepository.list_conversations(query, limit, offset)

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
        conv_doc = await ConversationRepository.find_conversation_for_tenant(conversation_id, tenant_id)
        if not conv_doc:
            return None  # Will be handled by endpoint as 404

        messages_docs = await ConversationRepository.get_messages(conversation_id, tenant_id)

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
                delivery_status=doc.get("delivery_status"),
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
        conv_doc = await ConversationRepository.find_conversation_for_tenant(conversation_id, tenant_id)
        if not conv_doc:
            logger.warning(f"Conversation {conversation_id} not found for tenant {tenant_id}")
            return None

        # Create message
        message_id = f"msg_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)
        # For ecommerce channel, agent replies should be unread until the client polls.
        # For other channels they are marked read on the assumption that the reply is
        # pushed out from here -- for email that assumption is made true by the
        # ReplyDeliveryService.deliver_reply call below, and if that send fails the
        # message is stamped delivery_status=failed and the caller gets an error.
        is_read = conv_doc.get("channel") != "ecommerce"
        await ConversationRepository.insert_message({
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
        await ConversationRepository.update_conversation(
            conversation_id,
            set_fields={
                "updated_at": now,
                "last_message_at": now,
                "last_message_preview": req.message[:100],
                "status": "open",
                "handling_mode": "human",
            },
            inc_fields={"message_count": 1},
        )

        logger.info(f"Agent reply sent to conversation {conversation_id} by tenant {tenant_id}")

        # Send webhook to client if webhook_url is registered
        webhook_url = conv_doc.get("webhook_url")
        if webhook_url:
            await ReplyDeliveryService.send_webhook(webhook_url, {
                "conversation_id": conversation_id,
                "message_id": message_id,
                "sender": "agent",
                "content": req.message,
                "agent_name": req.agent_name,
                "created_at": now.isoformat().replace("+00:00", "Z")
            })

        # Actually deliver the reply on channels that need an outbound send.
        # Without this an agent answering an escalated email conversation sees
        # their message in the thread while the customer receives nothing.
        # conv_doc was read before the insert, so it still carries the inbound
        # last_email_message_id / email_thread_id needed to thread the reply.
        try:
            await ReplyDeliveryService.deliver_reply(conv_doc, req.message)
        except EmailDeliveryError:
            await ConversationRepository.mark_message(message_id, {"delivery_status": "failed"})
            chat_logger.warning(f"⚠️  Message {message_id} marked delivery_status=failed")
            # Propagate: an agent must not be told their reply was sent when
            # it was not. The message row is kept (stamped as failed) so the
            # text is not lost.
            raise

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
        conv_doc = await ConversationRepository.find_conversation_for_tenant(conversation_id, tenant_id)
        if not conv_doc:
            logger.warning(f"Conversation {conversation_id} not found for tenant {tenant_id}")
            return None

        await ConversationRepository.mark_customer_messages_read(conversation_id, tenant_id)
        await ConversationRepository.update_conversation(conversation_id, set_fields={"unread_count": 0})

        logger.info(f"Marked conversation {conversation_id} as read for tenant {tenant_id}")

        return {"success": True, "unread_count": 0}

    @staticmethod
    async def update_status(
        tenant_id: str,
        conversation_id: str,
        new_status: str
    ) -> Optional[StatusChangeResponse]:
        """Update conversation status"""
        conv_doc = await ConversationRepository.find_conversation_for_tenant(conversation_id, tenant_id)
        if not conv_doc:
            logger.warning(f"Conversation {conversation_id} not found for tenant {tenant_id}")
            return None

        await ConversationRepository.update_conversation(
            conversation_id,
            set_fields={
                "status": new_status,
                "updated_at": datetime.now(timezone.utc),
            },
        )

        logger.info(f"Status updated to {new_status} for conversation {conversation_id} by tenant {tenant_id}")

        return StatusChangeResponse(
            success=True,
            conversation_id=conversation_id,
            status=new_status
        )
