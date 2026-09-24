"""Pure parsing of Gmail API message payloads.

No Mongo, no network, no config -- everything here is a function of its
input so the tests can cover the awkward cases cheaply.
"""
import base64
import re
from dataclasses import dataclass, field
from email.utils import parseaddr
from html import unescape
from typing import Optional

MAX_BODY_CHARS = 5000

# "On <date>, <someone> wrote:" -- the standard reply attribution line.
_ATTRIBUTION_RE = re.compile(
    r"^\s*On\s.{0,200}?\bwrote:\s*$", re.IGNORECASE | re.MULTILINE
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_BLOCKQUOTE_RE = re.compile(
    r"<blockquote.*?</blockquote>", re.IGNORECASE | re.DOTALL
)


@dataclass(frozen=True)
class ParsedEmail:
    gmail_message_id: str
    gmail_thread_id: str
    from_address: str
    from_name: Optional[str]
    subject: str
    body: str
    message_id_header: Optional[str]
    references: Optional[str]
    headers: dict[str, str] = field(default_factory=dict)


def _decode(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _html_to_text(html: str) -> str:
    without_quotes = _BLOCKQUOTE_RE.sub("", html)
    return unescape(_HTML_TAG_RE.sub("", without_quotes))


def _walk_parts(part: dict):
    yield part
    for child in part.get("parts", []) or []:
        yield from _walk_parts(child)


def extract_plain_body(payload: dict) -> str:
    """Prefer text/plain anywhere in the MIME tree; fall back to stripped HTML."""
    root = payload.get("payload", {})
    html_fallback = ""

    for part in _walk_parts(root):
        data = (part.get("body") or {}).get("data")
        if not data:
            continue
        mime = part.get("mimeType", "")
        if mime == "text/plain":
            return _decode(data)
        if mime == "text/html" and not html_fallback:
            html_fallback = _html_to_text(_decode(data))

    return html_fallback


def strip_quoted_history(text: str) -> str:
    """Remove the quoted reply chain.

    Without this the AI re-reads its own previous answer as customer input,
    and the prompt grows on every round trip.
    """
    match = _ATTRIBUTION_RE.search(text)
    if match:
        text = text[: match.start()]

    lines = [line for line in text.splitlines() if not line.lstrip().startswith(">")]
    return "\n".join(lines).strip()


def truncate_body(text: str, limit: int = MAX_BODY_CHARS) -> str:
    return text[:limit]


def _header_map(payload: dict) -> dict[str, str]:
    raw = (payload.get("payload") or {}).get("headers") or []
    return {h["name"].lower(): h["value"] for h in raw}


def parse_gmail_message(payload: dict) -> ParsedEmail:
    headers = _header_map(payload)
    display_name, address = parseaddr(headers.get("from", ""))
    body = truncate_body(strip_quoted_history(extract_plain_body(payload)))

    return ParsedEmail(
        gmail_message_id=payload.get("id", ""),
        gmail_thread_id=payload.get("threadId", ""),
        from_address=address.lower(),
        from_name=display_name or None,
        subject=headers.get("subject", ""),
        body=body,
        message_id_header=headers.get("message-id"),
        references=headers.get("references"),
        headers=headers,
    )
