"""Persistence for the processed_emails collection.

The unique index on gmail_message_id (created in database.py) is what makes
double-sending structurally impossible rather than something we remember to
check.
"""
from datetime import datetime, timezone
from typing import Optional

from pymongo.errors import DuplicateKeyError

from repositories.mongo_client import MongoConnection

SENT_STATUSES = ["replied", "escalated"]


class ProcessedEmailStore:

    @staticmethod
    def _collection():
        return MongoConnection.get_database()["processed_emails"]

    async def claim(
        self,
        gmail_message_id: str,
        gmail_thread_id: str,
        tenant_id: str,
        from_address: str,
    ) -> bool:
        """Claim a message for processing. False means someone already has it.

        Written BEFORE the reply is generated: if the worker dies mid-reply,
        the restart skips this message instead of mailing the customer twice.
        """
        try:
            await self._collection().insert_one({
                "gmail_message_id": gmail_message_id,
                "gmail_thread_id": gmail_thread_id,
                "tenant_id": tenant_id,
                "from_address": from_address,
                "status": "processing",
                "conversation_id": None,
                "skip_reason": None,
                "processed_at": datetime.now(timezone.utc),
            })
            return True
        except DuplicateKeyError:
            return False

    async def mark(
        self,
        gmail_message_id: str,
        status: str,
        conversation_id: Optional[str] = None,
        skip_reason: Optional[str] = None,
    ) -> None:
        updates = {"status": status, "processed_at": datetime.now(timezone.utc)}
        if conversation_id:
            updates["conversation_id"] = conversation_id
        if skip_reason:
            updates["skip_reason"] = skip_reason

        await self._collection().update_one(
            {"gmail_message_id": gmail_message_id}, {"$set": updates}
        )

    async def count_replies_to_sender(
        self, tenant_id: str, from_address: str, since: datetime
    ) -> int:
        return await self._collection().count_documents({
            "tenant_id": tenant_id,
            "from_address": from_address,
            "status": {"$in": SENT_STATUSES},
            "processed_at": {"$gte": since},
        })

    async def count_sends(self, tenant_id: str, since: datetime) -> int:
        return await self._collection().count_documents({
            "tenant_id": tenant_id,
            "status": {"$in": SENT_STATUSES},
            "processed_at": {"$gte": since},
        })
