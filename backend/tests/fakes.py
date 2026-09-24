"""In-memory test doubles for the email channel."""
import base64
from datetime import datetime, timezone
from typing import Any, Optional


def encode_body(text: str) -> str:
    """Gmail returns body data as base64url."""
    return base64.urlsafe_b64encode(text.encode()).decode()


def gmail_message(
    message_id: str = "m1",
    thread_id: str = "t1",
    from_address: str = "customer@example.com",
    subject: str = "Where is my order?",
    body: str = "Hi, where is order #4521?",
    extra_headers: Optional[dict] = None,
) -> dict:
    """Build a Gmail users.messages.get payload with a text/plain body."""
    headers = {
        "From": from_address,
        "Subject": subject,
        "Message-ID": f"<{message_id}@mail.example.com>",
        "Return-Path": f"<{from_address}>",
    }
    headers.update(extra_headers or {})
    return {
        "id": message_id,
        "threadId": thread_id,
        "payload": {
            "mimeType": "text/plain",
            "headers": [{"name": k, "value": v} for k, v in headers.items()],
            "body": {"data": encode_body(body)},
        },
    }


class FakeGmailClient:
    """Records sends instead of contacting Gmail."""

    def __init__(self, messages: Optional[list[dict]] = None):
        self._messages = {m["id"]: m for m in (messages or [])}
        self.sent: list[dict] = []
        self.marked_read: list[str] = []

    async def list_unread(self, max_results: int = 25) -> list[str]:
        return list(self._messages.keys())

    async def get_message(self, message_id: str) -> dict:
        return self._messages[message_id]

    async def send_reply(
        self, to: str, subject: str, body: str, thread_id: str,
        in_reply_to: Optional[str], references: Optional[str],
    ) -> str:
        self.sent.append({
            "to": to, "subject": subject, "body": body,
            "thread_id": thread_id, "in_reply_to": in_reply_to,
            "references": references,
        })
        return f"sent-{len(self.sent)}"

    async def mark_read(self, message_id: str) -> None:
        self.marked_read.append(message_id)


class InMemoryProcessedEmailStore:
    """Mirrors ProcessedEmailStore semantics without Mongo."""

    def __init__(self):
        self.records: dict[str, dict] = {}

    async def claim(
        self, gmail_message_id: str, gmail_thread_id: str,
        tenant_id: str, from_address: str,
    ) -> bool:
        if gmail_message_id in self.records:
            return False
        self.records[gmail_message_id] = {
            "gmail_message_id": gmail_message_id,
            "gmail_thread_id": gmail_thread_id,
            "tenant_id": tenant_id,
            "from_address": from_address,
            "status": "processing",
            "conversation_id": None,
            "skip_reason": None,
            "processed_at": datetime.now(timezone.utc),
        }
        return True

    async def mark(
        self, gmail_message_id: str, status: str,
        conversation_id: Optional[str] = None,
        skip_reason: Optional[str] = None,
    ) -> None:
        record = self.records[gmail_message_id]
        record["status"] = status
        if conversation_id:
            record["conversation_id"] = conversation_id
        if skip_reason:
            record["skip_reason"] = skip_reason

    async def count_replies_to_sender(
        self, tenant_id: str, from_address: str, since: datetime
    ) -> int:
        return sum(
            1 for r in self.records.values()
            if r["tenant_id"] == tenant_id
            and r["from_address"] == from_address
            and r["status"] in ("replied", "escalated")
            and r["processed_at"] >= since
        )

    async def count_sends(self, tenant_id: str, since: datetime) -> int:
        return sum(
            1 for r in self.records.values()
            if r["tenant_id"] == tenant_id
            and r["status"] in ("replied", "escalated")
            and r["processed_at"] >= since
        )
