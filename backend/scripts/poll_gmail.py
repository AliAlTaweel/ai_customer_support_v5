"""Gmail poll worker for the email channel.

Runs as its own process so a crash here cannot take down the API. A failed
poll cycle is logged and the worker moves on to the next interval rather
than dying -- only Ctrl-C (or a supervisor cancelling the process) stops it.

Usage:
    python -m scripts.poll_gmail --once           # one cycle, then exit
    python -m scripts.poll_gmail                  # loop forever
    python -m scripts.poll_gmail --interval 15    # loop every 15s
"""
import argparse
import asyncio
from typing import Optional

from config import get_settings
from database import Database
from repositories.processed_email_store import ProcessedEmailStore
from services.email_ingest_service import EmailIngestService
from services.gmail_client import GmailClient
from utils.logger import logger


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Poll Gmail and auto-answer support email")
    parser.add_argument("--once", action="store_true", help="Run a single cycle and exit")
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Seconds between cycles (defaults to GMAIL_POLL_INTERVAL_SECONDS)",
    )
    return parser


async def run_once(gmail, store) -> dict:
    return await EmailIngestService.process_unread(gmail=gmail, store=store)


def _resolve_interval(args, settings) -> int:
    """Honour an explicit --interval (including 0) over the settings default."""
    return args.interval if args.interval is not None else settings.GMAIL_POLL_INTERVAL_SECONDS


def _log_result(result: dict) -> None:
    """Log a poll cycle's outcome, iterating whatever status keys came back.

    Never hardcodes the status set -- delivery_failed and any future status
    must surface here automatically.
    """
    if not result:
        logger.info("📭 Poll cycle: no unread messages")
        return
    summary = ", ".join(f"{status}={count}" for status, count in result.items())
    logger.info(f"📊 Poll cycle: {summary}")


async def _poll_forever(*, gmail, store, args, interval: int) -> int:
    """Run cycles until --once is satisfied or the caller is cancelled.

    A cycle that raises is logged and the loop continues to the next
    interval -- one bad Gmail API call or Mongo hiccup must not kill the
    worker. In --once mode the exception is left to propagate so a
    supervisor sees a non-zero exit instead of a silently swallowed failure.
    """
    while True:
        if args.once:
            result = await run_once(gmail, store)
            _log_result(result)
            return 0

        try:
            result = await run_once(gmail, store)
            _log_result(result)
        except (KeyboardInterrupt, asyncio.CancelledError):
            raise
        except Exception:
            logger.error("✗ Poll cycle failed", exc_info=True)

        await asyncio.sleep(interval)


async def _run(args) -> int:
    settings = get_settings()

    if not settings.GMAIL_ENABLED:
        logger.error("✗ GMAIL_ENABLED is false — nothing to do")
        return 1
    if not settings.GMAIL_TENANT_ID:
        logger.error("✗ GMAIL_TENANT_ID is not set — cannot attribute email to a tenant")
        return 1

    if settings.GMAIL_DRY_RUN:
        logger.info("🧪 DRY RUN — replies will be logged, not sent")
    if not settings.GMAIL_ALLOWED_SENDERS:
        logger.info("🔒 Allowlist is empty — no sender will be auto-answered")

    await Database.connect()
    await Database.init_chat_collections()

    try:
        gmail = GmailClient.from_settings()
        store = ProcessedEmailStore()
        interval = _resolve_interval(args, settings)
        return await _poll_forever(gmail=gmail, store=store, args=args, interval=interval)
    finally:
        await Database.disconnect()


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        logger.info("🛑 Poller stopped")
        return 0
    except Exception:
        logger.error("✗ Poll worker failed", exc_info=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
