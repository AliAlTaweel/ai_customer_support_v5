"""Gmail API wrapper.

Knows Gmail; knows nothing about tenants or conversations. googleapiclient
is blocking, so every API call is pushed to a worker thread.
"""
import asyncio
import base64
from email.message import EmailMessage
from typing import Optional

from config import get_settings
from utils.logger import logger

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",  # read + mark as read
    "https://www.googleapis.com/auth/gmail.send",    # send replies
]

UNREAD_QUERY = "is:unread in:inbox"  # in:inbox excludes Gmail-classified spam


def build_reply_mime(
    to: str,
    from_address: str,
    subject: str,
    body: str,
    in_reply_to: Optional[str],
    references: Optional[str],
) -> str:
    """Build a base64url-encoded reply that threads correctly in the client."""
    message = EmailMessage()
    message["To"] = to
    message["From"] = from_address
    message["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"

    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
    if references:
        message["References"] = references

    # Tells well-behaved autoresponders on the far end not to volley with us.
    message["Auto-Submitted"] = "auto-replied"

    message.set_content(body)
    return base64.urlsafe_b64encode(message.as_bytes()).decode()


class GmailClient:

    def __init__(self, service, mailbox_address: str):
        self._service = service
        self._mailbox_address = mailbox_address

    @classmethod
    def from_settings(cls) -> "GmailClient":
        """Build a client from the refresh token in .env.

        Same approach as v4.11's email_ingestion_service. Passing token=None
        makes the library fetch a fresh access token on first use, so nothing
        expiring is ever persisted.

        Run scripts/gmail_auth.py once to obtain GMAIL_REFRESH_TOKEN.
        """
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        settings = get_settings()

        missing = [
            name
            for name in ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN")
            if not getattr(settings, name)
        ]
        if missing:
            raise RuntimeError(
                f"Gmail credentials missing from .env: {', '.join(missing)}. "
                "Run: python -m scripts.gmail_auth"
            )

        creds = Credentials(
            token=None,
            refresh_token=settings.GMAIL_REFRESH_TOKEN,
            client_id=settings.GMAIL_CLIENT_ID,
            client_secret=settings.GMAIL_CLIENT_SECRET,
            token_uri="https://oauth2.googleapis.com/token",
            scopes=GMAIL_SCOPES,
        )

        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return cls(service=service, mailbox_address=settings.GMAIL_ADDRESS)

    async def list_unread(self, max_results: int = 25) -> list[str]:
        def _call():
            return (
                self._service.users()
                .messages()
                .list(userId="me", q=UNREAD_QUERY, maxResults=max_results)
                .execute()
            )

        response = await asyncio.to_thread(_call)
        return [m["id"] for m in response.get("messages", [])]

    async def get_message(self, message_id: str) -> dict:
        def _call():
            return (
                self._service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )

        return await asyncio.to_thread(_call)

    async def send_reply(
        self,
        to: str,
        subject: str,
        body: str,
        thread_id: str,
        in_reply_to: Optional[str],
        references: Optional[str],
    ) -> str:
        raw = build_reply_mime(
            to=to,
            from_address=self._mailbox_address,
            subject=subject,
            body=body,
            in_reply_to=in_reply_to,
            references=references,
        )

        def _call():
            return (
                self._service.users()
                .messages()
                .send(userId="me", body={"raw": raw, "threadId": thread_id})
                .execute()
            )

        response = await asyncio.to_thread(_call)
        return response.get("id", "")

    async def mark_read(self, message_id: str) -> None:
        def _call():
            return (
                self._service.users()
                .messages()
                .modify(
                    userId="me",
                    id=message_id,
                    body={"removeLabelIds": ["UNREAD"]},
                )
                .execute()
            )

        await asyncio.to_thread(_call)


_client: Optional[GmailClient] = None
_client_lock = asyncio.Lock()


async def get_client() -> GmailClient:
    """The process-wide Gmail client, built once, off the event loop.

    `from_settings` calls googleapiclient's `build()`, which does blocking
    discovery I/O; calling it inline from async code stalls the loop, and
    calling it per reply also means every send carries its own credentials
    object with its own token refresh. One lazily-built instance, constructed
    in a worker thread, fixes both. The client itself is stateless beyond the
    service handle, so sharing it across the API and the poll worker is safe.
    """
    global _client
    if _client is None:
        async with _client_lock:
            if _client is None:
                _client = await asyncio.to_thread(GmailClient.from_settings)
    return _client


def reset_client() -> None:
    """Drop the cached client. For tests and credential rotation."""
    global _client
    _client = None
