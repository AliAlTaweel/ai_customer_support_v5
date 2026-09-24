"""Turns an unread Gmail message into an answered support conversation.

Order of operations matters:

- Gates and rate limits run BEFORE the claim, so a *deferrable* rejection
  (rate limit, not-yet-allowlisted) can bail out without claiming. Claiming
  is irreversible -- the store's unique index means a claimed message can
  never be reprocessed -- so anything that might become answerable later
  must not be claimed. Permanent rejections still get claimed, deliberately,
  so they are recorded and never looked at again.
- The claim is written BEFORE the AI runs, so a crash mid-reply cannot
  produce a duplicate reply.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import get_settings
from services.chat_service import ChatService, EmailDeliveryError
from services.email_gates import (
    SkipReason,
    check_loop_gates,
    check_sender_authentication,
    is_allowed_sender,
    is_deferrable,
)
from services.email_parser import ParsedEmail, parse_gmail_message
from utils.logger import logger

HOLDING_REPLY = (
    "Thanks for getting in touch — we've received your message and a member "
    "of our team will get back to you shortly."
)


class EmailIngestService:

    @staticmethod
    async def process_unread(*, gmail, store, chat=ChatService) -> dict:
        """Process one poll cycle. Returns counts keyed by final status."""
        message_ids = await gmail.list_unread()
        counts: Counter = Counter()

        for message_id in message_ids:
            try:
                status = await EmailIngestService.process_one(
                    message_id, gmail=gmail, store=store, chat=chat
                )
            except Exception as e:
                logger.error(f"✗ Failed processing email {message_id}: {e}", exc_info=True)
                # The message may already be claimed, and a claim can never be
                # released (unique index). Leaving it unread buys nothing but a
                # users.messages.get every cycle forever, crowding the capped
                # unread window. Recovery is manual deletion of the record.
                await EmailIngestService._mark_read_quietly(gmail, message_id)
                status = "error"
            counts[status] += 1

        logger.info(f"📮 Poll cycle complete: {dict(counts)}")
        return dict(counts)

    @staticmethod
    async def process_one(message_id: str, *, gmail, store, chat=ChatService) -> str:
        settings = get_settings()
        tenant_id = settings.GMAIL_TENANT_ID

        payload = await gmail.get_message(message_id)
        email = parse_gmail_message(payload)

        skip_reason = await EmailIngestService._rejection_reason(
            email, settings, store, tenant_id
        )

        if skip_reason and is_deferrable(skip_reason):
            # Deliberately NOT claimed and NOT marked read: the condition is
            # temporary (rate limit window, staged-rollout allowlist), so the
            # message must survive to be reconsidered. It will keep
            # reappearing in the unread window until it is answerable or a
            # human deals with it in Gmail -- which is strictly better than
            # destroying a customer's email.
            logger.info(
                f"⏸️  Email {email.gmail_message_id} deferred: {skip_reason} "
                f"(left unread for a later cycle)"
            )
            return "deferred"

        claimed = await store.claim(
            gmail_message_id=email.gmail_message_id,
            gmail_thread_id=email.gmail_thread_id,
            tenant_id=tenant_id,
            from_address=email.from_address,
        )
        if not claimed:
            logger.info(f"⏭️  Email {email.gmail_message_id} already processed")
            return "duplicate"

        if skip_reason:
            await store.mark(
                email.gmail_message_id, "skipped", skip_reason=skip_reason
            )
            await gmail.mark_read(email.gmail_message_id)
            logger.info(f"🚫 Email {email.gmail_message_id} skipped: {skip_reason}")
            return "skipped"

        try:
            response = await chat.receive_message(
                tenant_id=tenant_id,
                channel="email",
                customer_identifier=email.from_address,
                # The raw body, not the injection-wrapped one: this string is
                # persisted verbatim as the customer's message and drives
                # last_message_preview. The untrusted-content wrapper is
                # applied at the prompt boundary in ChatService instead.
                message=email.body,
                customer_name=email.from_name,
                email_thread_id=email.gmail_thread_id,
                email_headers={
                    "message_id": email.message_id_header,
                    "subject": email.subject,
                },
            )
        except EmailDeliveryError as e:
            # The AI answered but the Gmail send itself failed. Marking this
            # "replied" would be a lie -- the customer got nothing -- and
            # because claim() is idempotent on a unique index, that lie would
            # be permanent. Mark it "skipped" instead, which is deliberately
            # outside SENT_STATUSES, so it doesn't burn the sender's own rate
            # limit either. Do not re-raise: one failed send must not abort
            # the rest of the batch.
            #
            # This message is NOT retried automatically and cannot be: the
            # claim is already written and claim() can never be released.
            # Recovery is manual -- delete the processed_emails record (see
            # the README) and re-mark the mail unread. It is marked read here
            # precisely because leaving it unread would cost a
            # users.messages.get every cycle in perpetuity while still
            # returning "duplicate", crowding out new mail in the capped
            # unread window.
            logger.error(
                f"✗ Email {email.gmail_message_id} not delivered; the claim "
                f"cannot be released, so recovery needs the processed_emails "
                f"record deleted by hand: {e}"
            )
            await store.mark(
                email.gmail_message_id, "skipped", skip_reason="delivery_failed"
            )
            await EmailIngestService._mark_read_quietly(gmail, email.gmail_message_id)
            return "delivery_failed"

        conversation_id = response.conversation_id

        if response.ai_answer:
            await store.mark(
                email.gmail_message_id, "replied", conversation_id=conversation_id
            )
            await gmail.mark_read(email.gmail_message_id)
            return "replied"

        # No answer means the AI escalated (or was unable to run). The customer
        # gets an acknowledgement rather than silence.
        try:
            await EmailIngestService._send_holding_reply(
                gmail=gmail, email=email, conversation_id=conversation_id
            )
        except Exception as e:
            # Without this the exception escapes to process_unread and the
            # record is left in "processing" forever -- claimed, unmarked,
            # and invisible to every status query.
            logger.error(
                f"✗ Holding reply failed for email {email.gmail_message_id}; "
                f"the conversation exists and is escalated to a human: {e}",
                exc_info=True,
            )
            await store.mark(
                email.gmail_message_id,
                "skipped",
                conversation_id=conversation_id,
                skip_reason="holding_reply_failed",
            )
            await EmailIngestService._mark_read_quietly(gmail, email.gmail_message_id)
            return "holding_reply_failed"
        # Marked "escalated", which count_replies_to_sender counts as a send --
        # a holding reply is real outbound mail and can loop like any other.
        await store.mark(
            email.gmail_message_id, "escalated", conversation_id=conversation_id
        )
        await gmail.mark_read(email.gmail_message_id)
        return "escalated"

    @staticmethod
    async def _mark_read_quietly(gmail, message_id: str) -> None:
        """Mark read on a failure path, where a second failure must not mask
        the first. Never raises."""
        try:
            await gmail.mark_read(message_id)
        except Exception as e:
            logger.error(f"✗ Could not mark email {message_id} read: {e}")

    @staticmethod
    async def _rejection_reason(
        email: ParsedEmail, settings, store, tenant_id: str
    ) -> Optional[str]:
        loop_reason = check_loop_gates(email, settings.GMAIL_ADDRESS)
        if loop_reason:
            return loop_reason

        auth_reason = check_sender_authentication(email)
        if auth_reason:
            return auth_reason

        if not is_allowed_sender(email.from_address, settings.GMAIL_ALLOWED_SENDERS):
            return SkipReason.NOT_ALLOWLISTED

        since = datetime.now(timezone.utc) - timedelta(hours=1)

        sender_count = await store.count_replies_to_sender(
            tenant_id, email.from_address, since
        )
        if sender_count >= settings.GMAIL_MAX_REPLIES_PER_SENDER_HOUR:
            return SkipReason.RATE_LIMITED_SENDER

        total_count = await store.count_sends(tenant_id, since)
        if total_count >= settings.GMAIL_MAX_SENDS_PER_HOUR:
            return SkipReason.RATE_LIMITED_GLOBAL

        return None

    @staticmethod
    async def _send_holding_reply(*, gmail, email: ParsedEmail, conversation_id: str) -> None:
        """Acknowledge an escalated thread, at most once per conversation."""
        from repositories.mongo_client import MongoConnection

        settings = get_settings()
        db = MongoConnection.get_database()

        conv = await db["conversations"].find_one({"conversation_id": conversation_id})
        if conv and conv.get("email_holding_reply_sent"):
            logger.info(f"⏭️  Holding reply already sent | Conv: {conversation_id}")
            return

        if settings.GMAIL_DRY_RUN:
            # Do NOT set email_holding_reply_sent here. A dry run sends
            # nothing, and flagging it anyway means these conversations are
            # permanently barred from their acknowledgement once
            # GMAIL_DRY_RUN is turned off.
            logger.info(f"🧪 DRY RUN — would send holding reply | Conv: {conversation_id}")
            return

        await gmail.send_reply(
            to=email.from_address,
            subject=email.subject,
            body=HOLDING_REPLY,
            thread_id=email.gmail_thread_id,
            in_reply_to=email.message_id_header,
            references=email.message_id_header,
        )
        logger.info(f"📧 Holding reply sent | Conv: {conversation_id}")

        await db["conversations"].update_one(
            {"conversation_id": conversation_id},
            {"$set": {"email_holding_reply_sent": True}},
        )
