from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from pymongo.errors import DuplicateKeyError

from repositories.processed_email_store import ProcessedEmailStore
from tests.fakes import InMemoryProcessedEmailStore


@pytest.fixture
def collection(monkeypatch):
    coll = MagicMock()
    coll.insert_one = AsyncMock()
    coll.update_one = AsyncMock()
    coll.count_documents = AsyncMock(return_value=0)

    db = {"processed_emails": coll}
    import repositories.mongo_client as mongo_client
    monkeypatch.setattr(
        mongo_client.MongoConnection, "get_database", classmethod(lambda cls: db)
    )
    return coll


async def test_claim_returns_true_on_first_insert(collection):
    store = ProcessedEmailStore()
    assert await store.claim("m1", "t1", "T-1", "a@b.com") is True
    collection.insert_one.assert_awaited_once()


async def test_claim_returns_false_on_duplicate_key(collection):
    collection.insert_one.side_effect = DuplicateKeyError("dup")
    store = ProcessedEmailStore()

    assert await store.claim("m1", "t1", "T-1", "a@b.com") is False


async def test_claim_writes_processing_status_and_sender(collection):
    store = ProcessedEmailStore()
    await store.claim("m1", "t1", "T-1", "a@b.com")

    doc = collection.insert_one.await_args.args[0]
    assert doc["status"] == "processing"
    assert doc["from_address"] == "a@b.com"
    assert doc["gmail_message_id"] == "m1"
    assert doc["conversation_id"] is None


async def test_mark_updates_status_and_conversation(collection):
    store = ProcessedEmailStore()
    await store.mark("m1", "replied", conversation_id="conv_1")

    filter_arg, update_arg = collection.update_one.await_args.args
    assert filter_arg == {"gmail_message_id": "m1"}
    assert update_arg["$set"]["status"] == "replied"
    assert update_arg["$set"]["conversation_id"] == "conv_1"


async def test_count_replies_filters_by_sender_and_status(collection):
    store = ProcessedEmailStore()
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    await store.count_replies_to_sender("T-1", "a@b.com", since)

    query = collection.count_documents.await_args.args[0]
    assert query["tenant_id"] == "T-1"
    assert query["from_address"] == "a@b.com"
    assert query["status"] == {"$in": ["replied", "escalated"]}
    assert query["processed_at"] == {"$gte": since}


# The in-memory fake must behave like the real store, since Tasks 6-8
# test against it. These tests pin that contract.

async def test_fake_claim_is_idempotent():
    store = InMemoryProcessedEmailStore()
    assert await store.claim("m1", "t1", "T-1", "a@b.com") is True
    assert await store.claim("m1", "t1", "T-1", "a@b.com") is False


async def test_fake_counts_only_sent_statuses():
    store = InMemoryProcessedEmailStore()
    since = datetime.now(timezone.utc) - timedelta(hours=1)

    await store.claim("m1", "t1", "T-1", "a@b.com")
    await store.mark("m1", "replied")
    await store.claim("m2", "t2", "T-1", "a@b.com")
    await store.mark("m2", "skipped")

    assert await store.count_replies_to_sender("T-1", "a@b.com", since) == 1
