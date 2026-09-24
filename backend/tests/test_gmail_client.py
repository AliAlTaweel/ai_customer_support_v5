import asyncio
import base64
import threading
from email import message_from_bytes
from unittest.mock import MagicMock

import pytest

import services.gmail_client as gmail_client
from services.gmail_client import GMAIL_SCOPES, GmailClient, build_reply_mime


def _decode_mime(raw: str):
    padded = raw + "=" * (-len(raw) % 4)
    return message_from_bytes(base64.urlsafe_b64decode(padded))


def test_scopes_are_modify_and_send():
    assert set(GMAIL_SCOPES) == {
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.send",
    }
    # Full-mailbox access is deliberately NOT requested.
    assert "https://mail.google.com/" not in GMAIL_SCOPES


def test_reply_mime_sets_threading_headers():
    raw = build_reply_mime(
        to="customer@example.com",
        from_address="support@example.com",
        subject="Re: Order",
        body="Your order shipped.",
        in_reply_to="<abc@mail.example.com>",
        references="<abc@mail.example.com>",
    )
    msg = _decode_mime(raw)

    assert msg["To"] == "customer@example.com"
    assert msg["In-Reply-To"] == "<abc@mail.example.com>"
    assert msg["References"] == "<abc@mail.example.com>"


def test_reply_mime_always_sets_auto_submitted():
    raw = build_reply_mime(
        to="c@example.com", from_address="s@example.com", subject="Re: x",
        body="hi", in_reply_to=None, references=None,
    )
    assert _decode_mime(raw)["Auto-Submitted"] == "auto-replied"


def test_reply_mime_adds_re_prefix_when_missing():
    raw = build_reply_mime(
        to="c@example.com", from_address="s@example.com", subject="Order question",
        body="hi", in_reply_to=None, references=None,
    )
    assert _decode_mime(raw)["Subject"] == "Re: Order question"


def test_reply_mime_does_not_double_prefix():
    raw = build_reply_mime(
        to="c@example.com", from_address="s@example.com", subject="Re: Order question",
        body="hi", in_reply_to=None, references=None,
    )
    assert _decode_mime(raw)["Subject"] == "Re: Order question"


def test_reply_mime_carries_body():
    raw = build_reply_mime(
        to="c@example.com", from_address="s@example.com", subject="x",
        body="Your order shipped on Tuesday.", in_reply_to=None, references=None,
    )
    assert "Your order shipped on Tuesday." in _decode_mime(raw).get_payload()


async def test_list_unread_queries_inbox_excluding_spam():
    service = MagicMock()
    service.users().messages().list().execute.return_value = {
        "messages": [{"id": "m1"}, {"id": "m2"}]
    }
    client = GmailClient(service=service, mailbox_address="support@example.com")

    assert await client.list_unread() == ["m1", "m2"]

    kwargs = service.users().messages().list.call_args.kwargs
    assert kwargs["q"] == "is:unread in:inbox"


async def test_list_unread_returns_empty_when_no_messages():
    service = MagicMock()
    service.users().messages().list().execute.return_value = {}
    client = GmailClient(service=service, mailbox_address="support@example.com")

    assert await client.list_unread() == []


async def test_send_reply_passes_thread_id():
    service = MagicMock()
    service.users().messages().send().execute.return_value = {"id": "sent1"}
    client = GmailClient(service=service, mailbox_address="support@example.com")

    result = await client.send_reply(
        to="c@example.com", subject="Re: x", body="hi",
        thread_id="t1", in_reply_to="<a@b>", references="<a@b>",
    )

    assert result == "sent1"
    body = service.users().messages().send.call_args.kwargs["body"]
    assert body["threadId"] == "t1"
    assert "raw" in body


def test_from_settings_names_the_missing_credentials(monkeypatch):
    monkeypatch.setenv("GMAIL_CLIENT_ID", "id-123")
    monkeypatch.delenv("GMAIL_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GMAIL_REFRESH_TOKEN", raising=False)

    with pytest.raises(RuntimeError) as exc:
        GmailClient.from_settings()

    message = str(exc.value)
    assert "GMAIL_CLIENT_SECRET" in message
    assert "GMAIL_REFRESH_TOKEN" in message
    assert "GMAIL_CLIENT_ID" not in message  # this one was set
    assert "scripts.gmail_auth" in message


async def test_mark_read_removes_unread_label():
    service = MagicMock()
    service.users().messages().modify().execute.return_value = {}
    client = GmailClient(service=service, mailbox_address="support@example.com")

    await client.mark_read("m1")

    body = service.users().messages().modify.call_args.kwargs["body"]
    assert body == {"removeLabelIds": ["UNREAD"]}


# --- Process-wide client ---------------------------------------------------


@pytest.fixture
def counting_build(monkeypatch):
    """Replace the blocking from_settings with a thread-recording counter."""
    builds = []

    def fake_from_settings():
        builds.append(threading.current_thread())
        return object()

    monkeypatch.setattr(
        gmail_client.GmailClient, "from_settings", staticmethod(fake_from_settings)
    )
    gmail_client.reset_client()
    yield builds
    gmail_client.reset_client()


async def test_concurrent_callers_share_one_client(counting_build):
    """Single-flight: a burst of replies must not each build their own client
    (and their own credentials object)."""
    clients = await asyncio.gather(*(gmail_client.get_client() for _ in range(5)))

    assert len(counting_build) == 1
    assert len({id(c) for c in clients}) == 1


async def test_client_is_built_off_the_event_loop(counting_build):
    """googleapiclient's build() is blocking; the plan requires every call into
    it from async code to go through asyncio.to_thread."""
    await gmail_client.get_client()

    assert counting_build[0] is not threading.main_thread()


def test_lock_is_not_bound_to_the_first_event_loop(counting_build):
    """The API and the poll worker each run their own loop in their own
    process, and tests run one loop per test: a module-level asyncio.Lock
    created at import would bind to the first and break the rest."""
    first = asyncio.run(gmail_client.get_client())
    second = asyncio.run(gmail_client.get_client())

    assert first is second
    assert len(counting_build) == 1
