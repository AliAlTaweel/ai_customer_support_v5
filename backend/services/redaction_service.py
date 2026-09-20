"""PII/PCI redaction: masks sensitive data before it is sent to any external LLM API.

Structured data (card numbers, IBANs, US bank account/routing numbers, SSNs
and other government ID numbers, dates of birth, credential strings, emails,
phone numbers, and IPv4 addresses) is detected reliably via pattern matching.
Bank account/routing numbers and the broader government-ID formats (passport,
driver's license, national ID) are only redacted when they appear in a
clearly-labeled context (e.g. "account number: ...") -- bare unlabeled digit
sequences are intentionally left alone to avoid collisions with card/phone
detection and false positives. Free-text name/address detection is NOT
attempted here -- it requires a dedicated NER model and is a documented
limitation, not a gap in this module. See
docs/superpowers/specs/2026-07-25-ai-customer-support-rag-design.md.
"""

import re


_CREDENTIAL_RE = re.compile(r'\b(?:password|passwd|otp|pin)\s*[:=]\s*\S+', re.IGNORECASE)
_IP_RE = re.compile(
    r'\b(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b'
)
# Bank account / routing numbers: only redacted when a clear label precedes
# the digits, to avoid false positives against card/phone detection.
_BANK_LABEL_RE = re.compile(
    r'\b((?:bank\s+)?(?:account|routing)\s*number\s*[:#]?\s*)(\d{6,17})\b',
    re.IGNORECASE,
)
# Government ID numbers in a clearly-labeled context (passport, driver's
# license, national ID). Matches an alphanumeric ID token after the label.
_ID_LABEL_RE = re.compile(
    r"\b((?:passport\s*(?:number|no\.?)?|driver'?s?\s*licen[cs]e(?:\s*number)?"
    r"|national\s*id(?:\s*number)?)\s*[:#]?\s*)([A-Za-z0-9]{5,17})\b",
    re.IGNORECASE,
)
_CARD_RE = re.compile(r'\b\d(?:[ -]?\d){12,18}\b')
_IBAN_RE = re.compile(r'\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b')
_SSN_RE = re.compile(r'\b\d{3}-\d{2}-\d{4}\b')
_DOB_RE = re.compile(r'\b(0[1-9]|1[0-2])[/-](0[1-9]|[12]\d|3[01])[/-](19|20)\d{2}\b')
_EMAIL_RE = re.compile(r'\b[\w.+-]+@[\w-]+\.[\w.-]+\b')
_PHONE_RE = re.compile(r'\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b')


def _luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _redact_card_match(match: "re.Match") -> str:
    digits = re.sub(r'[ -]', '', match.group())
    if 13 <= len(digits) <= 19 and _luhn_valid(digits):
        return '[REDACTED_CARD]'
    return match.group()


def _keep_label(placeholder: str):
    """Build a re.sub replacement that keeps the matched label (group 1) and
    replaces only the ID/account digits (group 2) with the placeholder."""
    def _inner(match: "re.Match") -> str:
        return match.group(1) + placeholder
    return _inner


def redact_text(text: str) -> str:
    """Mask sensitive data in customer text before it leaves to an LLM vendor."""
    text = _CREDENTIAL_RE.sub('[REDACTED_CREDENTIAL]', text)
    text = _IP_RE.sub('[REDACTED_IP]', text)
    text = _BANK_LABEL_RE.sub(_keep_label('[REDACTED_BANK_ACCOUNT]'), text)
    text = _ID_LABEL_RE.sub(_keep_label('[REDACTED_ID]'), text)
    text = _CARD_RE.sub(_redact_card_match, text)
    text = _IBAN_RE.sub('[REDACTED_IBAN]', text)
    text = _SSN_RE.sub('[REDACTED_ID]', text)
    text = _DOB_RE.sub('[REDACTED_DOB]', text)
    text = _EMAIL_RE.sub('[REDACTED_EMAIL]', text)
    text = _PHONE_RE.sub('[REDACTED_PHONE]', text)
    return text
