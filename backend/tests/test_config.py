from config import Settings


def test_gmail_defaults_are_safe(monkeypatch):
    monkeypatch.delenv("GMAIL_DRY_RUN", raising=False)
    monkeypatch.delenv("GMAIL_ALLOWED_SENDERS", raising=False)
    monkeypatch.delenv("GMAIL_ENABLED", raising=False)
    settings = Settings()

    assert settings.GMAIL_ENABLED is False
    assert settings.GMAIL_DRY_RUN is True
    assert settings.GMAIL_ALLOWED_SENDERS == []


def test_allowlist_parses_comma_separated_and_lowercases(monkeypatch):
    monkeypatch.setenv("GMAIL_ALLOWED_SENDERS", "A@x.com, b@y.com ")
    assert Settings().GMAIL_ALLOWED_SENDERS == ["a@x.com", "b@y.com"]


def test_allowlist_wildcard(monkeypatch):
    monkeypatch.setenv("GMAIL_ALLOWED_SENDERS", "*")
    assert Settings().GMAIL_ALLOWED_SENDERS == ["*"]


def test_rate_limit_defaults(monkeypatch):
    monkeypatch.delenv("GMAIL_MAX_REPLIES_PER_SENDER_HOUR", raising=False)
    monkeypatch.delenv("GMAIL_MAX_SENDS_PER_HOUR", raising=False)
    settings = Settings()
    assert settings.GMAIL_MAX_REPLIES_PER_SENDER_HOUR == 5
    assert settings.GMAIL_MAX_SENDS_PER_HOUR == 50
