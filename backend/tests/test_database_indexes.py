from unittest.mock import AsyncMock, MagicMock

import pytest

from database import Database


class FakeDB:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        if name not in self.collections:
            collection = MagicMock()
            collection.create_index = AsyncMock()
            self.collections[name] = collection
        return self.collections[name]


@pytest.fixture
def fake_db(monkeypatch):
    db = FakeDB()
    import repositories.mongo_client as mongo_client
    monkeypatch.setattr(
        mongo_client.MongoConnection, "get_database", classmethod(lambda cls: db)
    )
    return db


async def test_chat_indexes_are_actually_awaited(fake_db):
    await Database.init_chat_collections()

    for name in ("conversations", "messages", "tenant_api_keys"):
        assert fake_db.collections[name].create_index.await_count > 0, (
            f"{name} indexes were created without await -- they never run"
        )


async def test_processed_emails_has_unique_message_id_index(fake_db):
    await Database.init_chat_collections()

    calls = fake_db.collections["processed_emails"].create_index.await_args_list
    unique_calls = [c for c in calls if c.kwargs.get("unique") is True]

    assert len(unique_calls) == 1
    assert unique_calls[0].args[0] == [("gmail_message_id", 1)]


async def test_processed_emails_has_rate_limit_index(fake_db):
    await Database.init_chat_collections()

    calls = fake_db.collections["processed_emails"].create_index.await_args_list
    indexed = [c.args[0] for c in calls]

    assert [("tenant_id", 1), ("from_address", 1), ("processed_at", -1)] in indexed
