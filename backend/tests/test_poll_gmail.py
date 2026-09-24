import argparse
import asyncio
from types import SimpleNamespace

import pytest

import scripts.poll_gmail as poll_gmail
from scripts.poll_gmail import build_parser


def test_defaults_to_once_false():
    args = build_parser().parse_args([])
    assert args.once is False


def test_once_flag():
    args = build_parser().parse_args(["--once"])
    assert args.once is True


def test_interval_override():
    args = build_parser().parse_args(["--interval", "15"])
    assert args.interval == 15


def test_interval_defaults_to_none_so_config_wins():
    args = build_parser().parse_args([])
    assert args.interval is None


def test_interval_zero_is_parsed_as_zero_not_falsy():
    args = build_parser().parse_args(["--interval", "0"])
    assert args.interval == 0


def test_resolve_interval_honours_explicit_zero():
    settings = SimpleNamespace(GMAIL_POLL_INTERVAL_SECONDS=60)
    args = argparse.Namespace(interval=0)
    assert poll_gmail._resolve_interval(args, settings) == 0


def test_resolve_interval_falls_back_to_settings_when_none():
    settings = SimpleNamespace(GMAIL_POLL_INTERVAL_SECONDS=60)
    args = argparse.Namespace(interval=None)
    assert poll_gmail._resolve_interval(args, settings) == 60


async def test_failed_cycle_does_not_kill_the_loop(monkeypatch):
    calls = []

    async def fake_run_once(gmail, store):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        # Stop the loop cleanly once we've proven a second cycle ran.
        raise asyncio.CancelledError()

    monkeypatch.setattr(poll_gmail, "run_once", fake_run_once)

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(poll_gmail.asyncio, "sleep", fake_sleep)

    args = argparse.Namespace(once=False, interval=0)

    with pytest.raises(asyncio.CancelledError):
        await poll_gmail._poll_forever(gmail=None, store=None, args=args, interval=0)

    assert len(calls) == 2


async def test_once_mode_lets_exception_propagate(monkeypatch):
    async def failing_run_once(gmail, store):
        raise RuntimeError("boom")

    monkeypatch.setattr(poll_gmail, "run_once", failing_run_once)

    args = argparse.Namespace(once=True, interval=0)

    with pytest.raises(RuntimeError):
        await poll_gmail._poll_forever(gmail=None, store=None, args=args, interval=0)


def test_log_result_handles_arbitrary_status_keys(caplog):
    import logging

    with caplog.at_level(logging.INFO):
        poll_gmail._log_result({"replied": 2, "delivery_failed": 1, "skipped": 3})

    assert "delivery_failed=1" in caplog.text


def test_log_result_handles_empty_result(caplog):
    import logging

    with caplog.at_level(logging.INFO):
        poll_gmail._log_result({})

    assert "no unread" in caplog.text.lower()
