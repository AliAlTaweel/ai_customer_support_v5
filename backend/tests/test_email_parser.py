from services.email_parser import (
    ParsedEmail,
    extract_plain_body,
    parse_gmail_message,
    strip_quoted_history,
    truncate_body,
)
from tests.fakes import encode_body, gmail_message


def test_parses_basic_message():
    email = parse_gmail_message(gmail_message())

    assert isinstance(email, ParsedEmail)
    assert email.gmail_message_id == "m1"
    assert email.gmail_thread_id == "t1"
    assert email.from_address == "customer@example.com"
    assert email.subject == "Where is my order?"
    assert "order #4521" in email.body


def test_from_header_with_display_name():
    payload = gmail_message(from_address="Jane Doe <Jane@Example.com>")
    email = parse_gmail_message(payload)

    assert email.from_address == "jane@example.com"  # normalized lowercase
    assert email.from_name == "Jane Doe"


def test_headers_are_lowercased_for_lookup():
    payload = gmail_message(extra_headers={"Auto-Submitted": "auto-replied"})
    email = parse_gmail_message(payload)

    assert email.headers["auto-submitted"] == "auto-replied"


def test_prefers_text_plain_part_in_multipart():
    payload = {
        "id": "m2",
        "threadId": "t2",
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [{"name": "From", "value": "a@b.com"}],
            "parts": [
                {"mimeType": "text/plain", "body": {"data": encode_body("plain version")}},
                {"mimeType": "text/html", "body": {"data": encode_body("<p>html version</p>")}},
            ],
        },
    }
    assert extract_plain_body(payload) == "plain version"


def test_falls_back_to_stripped_html_when_no_plain_part():
    payload = {
        "id": "m3",
        "threadId": "t3",
        "payload": {
            "mimeType": "text/html",
            "headers": [],
            "body": {"data": encode_body("<p>Hello <b>there</b></p>")},
        },
    }
    assert extract_plain_body(payload).strip() == "Hello there"


def test_strips_on_date_wrote_quote_block():
    text = (
        "Thanks, that worked!\n"
        "\n"
        "On Mon, 22 Sep 2026 at 10:04, Support <support@example.com> wrote:\n"
        "> Have you tried resetting it?\n"
        "> Let us know.\n"
    )
    assert strip_quoted_history(text).strip() == "Thanks, that worked!"


def test_strips_leading_angle_bracket_quotes():
    text = "My reply\n\n> old message\n> more old message"
    assert strip_quoted_history(text).strip() == "My reply"


def test_strip_preserves_text_with_no_quotes():
    text = "Just a normal question about shipping."
    assert strip_quoted_history(text) == text


def test_truncate_caps_at_limit():
    assert len(truncate_body("x" * 9000, limit=5000)) == 5000


def test_truncate_leaves_short_text_alone():
    assert truncate_body("short") == "short"


def test_parse_strips_and_truncates_body():
    long_reply = "Answer here.\n\nOn Mon, X wrote:\n" + "> noise\n" * 5000
    email = parse_gmail_message(gmail_message(body=long_reply))

    assert email.body.strip() == "Answer here."
    assert len(email.body) <= 5000
