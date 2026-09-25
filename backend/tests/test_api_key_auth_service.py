import bcrypt
import pytest
from datetime import datetime, timezone

from repositories.mongo_client import MongoConnection
from services.api_key_auth_service import APIKeyAuthService


class _FakeCollection:
    def __init__(self, docs):
        self._docs = docs

    async def find_one(self, query):
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return doc
        return None

    async def update_one(self, query, update):
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in query.items()):
                doc.update(update.get("$set", {}))
                return


class _FakeDB:
    def __init__(self, api_keys=None, tenants=None):
        self._collections = {
            "tenant_api_keys": _FakeCollection(api_keys or []),
            "tenants": _FakeCollection(tenants or []),
        }

    def __getitem__(self, name):
        return self._collections[name]


def _hash(raw: str) -> str:
    return bcrypt.hashpw(raw.encode(), bcrypt.gensalt(rounds=4)).decode()


@pytest.fixture
def fake_db(monkeypatch):
    def _install(api_keys=None, tenants=None):
        db = _FakeDB(api_keys=api_keys, tenants=tenants)
        monkeypatch.setattr(MongoConnection, "get_database", staticmethod(lambda: db))
        return db

    return _install


async def test_valid_hashed_key_resolves_tenant_and_stamps_last_used(fake_db):
    raw_key = "sk_live_abcdef1234567890"
    db = fake_db(api_keys=[{
        "_id": "1",
        "active": True,
        "api_key_prefix": raw_key[:12],
        "api_key_hash": _hash(raw_key),
        "tenant_id": "tenant_1",
        "last_used_at": None,
    }])

    tenant_id = await APIKeyAuthService.authenticate(raw_key)

    assert tenant_id == "tenant_1"
    assert db["tenant_api_keys"]._docs[0]["last_used_at"] is not None


async def test_wrong_key_does_not_resolve(fake_db):
    fake_db(api_keys=[{
        "_id": "1",
        "active": True,
        "api_key_prefix": "sk_live_abcd",
        "api_key_hash": _hash("sk_live_abcdef1234567890"),
        "tenant_id": "tenant_1",
    }])

    tenant_id = await APIKeyAuthService.authenticate("sk_live_wrongwrongwrong")

    assert tenant_id is None


async def test_inactive_key_does_not_resolve(fake_db):
    raw_key = "sk_live_abcdef1234567890"
    fake_db(api_keys=[{
        "_id": "1",
        "active": False,
        "api_key_prefix": raw_key[:12],
        "api_key_hash": _hash(raw_key),
        "tenant_id": "tenant_1",
    }])

    tenant_id = await APIKeyAuthService.authenticate(raw_key)

    assert tenant_id is None


async def test_legacy_plaintext_key_resolves_tenant(fake_db):
    fake_db(tenants=[{
        "tenant_id": "tenant_legacy",
        "api_key": "legacy-plain-key",
        "status": "active",
    }])

    tenant_id = await APIKeyAuthService.authenticate("legacy-plain-key")

    assert tenant_id == "tenant_legacy"


async def test_legacy_key_on_inactive_tenant_does_not_resolve(fake_db):
    fake_db(tenants=[{
        "tenant_id": "tenant_legacy",
        "api_key": "legacy-plain-key",
        "status": "suspended",
    }])

    tenant_id = await APIKeyAuthService.authenticate("legacy-plain-key")

    assert tenant_id is None


async def test_unknown_key_does_not_resolve(fake_db):
    fake_db()

    tenant_id = await APIKeyAuthService.authenticate("sk_live_nope")

    assert tenant_id is None
