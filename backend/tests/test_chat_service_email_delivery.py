import pytest

import services.chat_service as chat_service_module
from services.chat_service import ChatService, EmailDeliveryError
from services.ai_reply_service import AIReplyResult, AIReplyService
from services.kb_service import KBService
from tests.fakes import FakeGmailClient


@pytest.fixture
def fake_gmail(monkeypatch):
    client = FakeGmailClient()
    monkeypatch.setattr(
        chat_service_module, "_gmail_client_factory", lambda: client
    )
    monkeypatch.setenv("GMAIL_DRY_RUN", "false")
    monkeypatch.setenv("GMAIL_ADDRESS", "support@example.com")
    return client


def _email_conv(**overrides):
    doc = {
        "conversation_id": "conv_1",
        "channel": "email",
        "customer_identifier": "customer@example.com",
        "email_thread_id": "t1",
        "last_email_message_id": "<abc@mail.example.com>",
        "last_email_subject": "Order question",
    }
    doc.update(overrides)
    return doc


async def test_widget_conversation_sends_nothing(fake_gmail):
    await ChatService._deliver_reply(
        {"conversation_id": "conv_2", "channel": "widget"}, "Hello"
    )
    assert fake_gmail.sent == []


async def test_email_conversation_sends_reply(fake_gmail):
    await ChatService._deliver_reply(_email_conv(), "Your order shipped.")

    assert len(fake_gmail.sent) == 1
    sent = fake_gmail.sent[0]
    assert sent["to"] == "customer@example.com"
    assert sent["body"] == "Your order shipped."
    assert sent["thread_id"] == "t1"
    assert sent["in_reply_to"] == "<abc@mail.example.com>"
    assert sent["subject"] == "Order question"


async def test_dry_run_does_not_send(fake_gmail, monkeypatch):
    monkeypatch.setenv("GMAIL_DRY_RUN", "true")

    await ChatService._deliver_reply(_email_conv(), "Your order shipped.")

    assert fake_gmail.sent == []


async def test_missing_recipient_does_not_raise(fake_gmail):
    await ChatService._deliver_reply(
        _email_conv(customer_identifier=None), "Your order shipped."
    )
    assert fake_gmail.sent == []


async def test_send_failure_raises_email_delivery_error(fake_gmail, monkeypatch):
    async def boom(**kwargs):
        raise RuntimeError("gmail down")

    monkeypatch.setattr(fake_gmail, "send_reply", boom)

    # A delivery failure must be signalled to the caller -- silently swallowing
    # it would let the email-ingestion pipeline record the message as replied
    # (and, via ProcessedEmailStore's unique index, never retry) even though
    # the customer never received anything.
    with pytest.raises(EmailDeliveryError):
        await ChatService._deliver_reply(_email_conv(), "Your order shipped.")

    assert fake_gmail.sent == []


class _FakeConversationsCollection:
    """Minimal find_one/insert_one/update_one double, just enough to drive
    ChatService.receive_message through the email path for the propagation
    test below. Not a general-purpose Mongo fake."""

    def __init__(self):
        self.docs = {}

    def _matches(self, doc, query):
        return all(
            doc.get(k) == v for k, v in query.items() if not isinstance(v, dict)
        )

    async def find_one(self, query):
        for doc in self.docs.values():
            if self._matches(doc, query):
                return doc
        return None

    async def insert_one(self, doc):
        self.docs[doc["conversation_id"]] = doc

        class _Result:
            inserted_id = "fake_id"

        return _Result()

    async def update_one(self, query, update):
        doc = await self.find_one(query)
        if doc is None:
            return
        for k, v in update.get("$set", {}).items():
            doc[k] = v
        for k, v in update.get("$inc", {}).items():
            doc[k] = doc.get(k, 0) + v


class _FakeMessagesCollection:
    def __init__(self):
        self.docs = []

    async def insert_one(self, doc):
        self.docs.append(doc)

        class _Result:
            inserted_id = "fake_id"

        return _Result()


class _FakeDB:
    def __init__(self):
        self._collections = {
            "conversations": _FakeConversationsCollection(),
            "messages": _FakeMessagesCollection(),
        }

    def __getitem__(self, name):
        return self._collections[name]


@pytest.fixture
def fake_db(monkeypatch):
    db = _FakeDB()
    monkeypatch.setattr(ChatService, "_get_db", staticmethod(lambda: db))
    return db


@pytest.fixture
def ai_answers(monkeypatch):
    """Route the AI-reply pipeline straight to an "answered" result so
    receive_message reaches _deliver_reply without needing real KB/AI calls."""
    monkeypatch.setattr(KBService, "get_ai_enabled", staticmethod(lambda tenant_id: _true()))
    monkeypatch.setattr(AIReplyService, "tenant_can_use_ai", staticmethod(lambda tenant_id: _true()))

    async def fake_generate_reply(tenant_id, customer_message, customer_identifier=None):
        return AIReplyResult(
            answered=True,
            answer="Your order shipped.",
            escalate_reason=None,
            redacted_input=customer_message,
            token_count=10,
            duration_ms=5,
        )

    monkeypatch.setattr(AIReplyService, "generate_reply", fake_generate_reply)


async def _true():
    return True


async def test_send_failure_propagates_out_of_receive_message(
    fake_gmail, fake_db, ai_answers, monkeypatch
):
    async def boom(**kwargs):
        raise RuntimeError("gmail down")

    monkeypatch.setattr(fake_gmail, "send_reply", boom)

    with pytest.raises(EmailDeliveryError):
        await ChatService.receive_message(
            tenant_id="tenant_1",
            channel="email",
            customer_identifier="customer@example.com",
            message="Where is my order?",
            email_thread_id="t1",
            email_headers={
                "message_id": "<abc@mail.example.com>",
                "subject": "Order question",
            },
        )

    assert fake_gmail.sent == []


async def test_dry_run_does_not_raise(fake_gmail, monkeypatch):
    monkeypatch.setenv("GMAIL_DRY_RUN", "true")

    # Should complete without raising.
    await ChatService._deliver_reply(_email_conv(), "Your order shipped.")


async def test_widget_conversation_does_not_raise(fake_gmail):
    # Should complete without raising.
    await ChatService._deliver_reply(
        {"conversation_id": "conv_2", "channel": "widget"}, "Hello"
    )
