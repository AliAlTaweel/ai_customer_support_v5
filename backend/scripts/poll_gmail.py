"""Gmail poll worker for the email channel.

Runs as its own process so a crash here cannot take down the API.

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
        interval = args.interval or settings.GMAIL_POLL_INTERVAL_SECONDS

        while True:
            await run_once(gmail, store)
            if args.once:
                return 0
            await asyncio.sleep(interval)
    finally:
        await Database.disconnect()


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        logger.info("🛑 Poller stopped")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
