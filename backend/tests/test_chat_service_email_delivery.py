import pytest

import services.chat_service as chat_service_module
from services.chat_service import ChatService
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


async def test_send_failure_is_swallowed(fake_gmail, monkeypatch):
    async def boom(**kwargs):
        raise RuntimeError("gmail down")

    monkeypatch.setattr(fake_gmail, "send_reply", boom)

    # A delivery failure must not break the reply pipeline -- the message is
    # already persisted and visible in the UI.
    await ChatService._deliver_reply(_email_conv(), "Your order shipped.")
