"""Dispatches an agent/AI reply to a conversation's outbound channel
(email via Gmail, or a registered webhook). Does not touch persistence --
callers are responsible for recording the outcome (e.g. delivery_status)."""

import inspect
from typing import Any, Dict, Optional

from utils.logger import logger


async def _gmail_client_factory():
    """Indirection so tests can inject a fake Gmail client.

    Returns the process-wide client rather than building one per reply --
    googleapiclient's build() is blocking and must not run on the loop.
    Monkeypatched replacements may be sync or async; the call site handles
    both.
    """
    from services.gmail_client import get_client
    return await get_client()


class EmailDeliveryError(Exception):
    """Raised when an email reply was attempted and the send failed."""


class ReplyDeliveryService:
    """Outbound dispatch of a reply to a conversation's channel."""

    @staticmethod
    async def deliver_reply(conv_doc: Dict[str, Any], reply_text: str) -> None:
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

        if not settings.GMAIL_ENABLED:
            # The kill switch has to bite here, not only in the poll worker:
            # agent replies and AI replies to existing email conversations
            # reach this path through the API, with no poller involved.
            logger.info(
                f"⏭️  GMAIL_ENABLED is false — not sending email reply | Conv: {conversation_id}"
            )
            return

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
            if inspect.isawaitable(client):
                client = await client
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
            # Transient Gmail/network errors are expected and varied; log the
            # full traceback for diagnosis, but do not swallow the failure --
            # the caller (and eventually the email ingestion pipeline) must
            # learn the send did not happen so it isn't recorded as replied.
            logger.error(
                f"✗ Failed to send email reply | Conv: {conversation_id} | To: {to_address} | {e}",
                exc_info=True,
            )
            raise EmailDeliveryError(
                f"Failed to send email reply | Conv: {conversation_id} | To: {to_address}"
            ) from e

    @staticmethod
    async def send_webhook(webhook_url: str, payload: Dict[str, Any]) -> None:
        """Notify a tenant-registered webhook of an agent reply. Best-effort:
        failures are logged, not raised -- a broken client webhook must not
        block the reply itself."""
        import aiohttp

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(webhook_url, json=payload) as resp:
                    if resp.status == 200:
                        logger.info(f"✅ Webhook sent to {webhook_url}")
                    else:
                        logger.warning(
                            f"⚠️ Webhook failed ({resp.status}) for {webhook_url}: {await resp.text()}"
                        )
        except Exception as e:
            logger.error(f"❌ Error sending webhook to {webhook_url}: {str(e)}")
