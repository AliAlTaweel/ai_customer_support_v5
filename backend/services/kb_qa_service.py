"""Knowledge-base Q&A pair management."""

import uuid
from datetime import datetime, timezone
from typing import Optional
from repositories.mongo_client import MongoConnection
from services.gemini_client import GeminiClient
from utils.time_format import to_utc_iso_z


class KBQAService:
    """Business logic for tenant-authored knowledge-base Q&A pairs."""

    @staticmethod
    def _get_db():
        return MongoConnection.get_database()

    @staticmethod
    async def create_qa_pair(tenant_id: str, question: str, answer: str) -> dict:
        db = KBQAService._get_db()
        qa_id = f"qa_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        await db["kb_qa_pairs"].insert_one({
            "qa_id": qa_id,
            "tenant_id": tenant_id,
            "question": question,
            "answer": answer,
            "created_at": now,
            "updated_at": now,
        })

        await KBQAService._reembed_qa_pair(db, tenant_id, qa_id, question, answer)

        return {
            "qa_id": qa_id,
            "question": question,
            "answer": answer,
            "updated_at": to_utc_iso_z(now),
        }

    @staticmethod
    async def update_qa_pair(
        tenant_id: str, qa_id: str, question: Optional[str], answer: Optional[str]
    ) -> Optional[dict]:
        db = KBQAService._get_db()
        existing = await db["kb_qa_pairs"].find_one({"qa_id": qa_id, "tenant_id": tenant_id})
        if not existing:
            return None

        new_question = question if question is not None else existing["question"]
        new_answer = answer if answer is not None else existing["answer"]
        now = datetime.now(timezone.utc)

        await db["kb_qa_pairs"].update_one(
            {"qa_id": qa_id},
            {"$set": {"question": new_question, "answer": new_answer, "updated_at": now}}
        )

        await KBQAService._reembed_qa_pair(db, tenant_id, qa_id, new_question, new_answer)

        return {
            "qa_id": qa_id,
            "question": new_question,
            "answer": new_answer,
            "updated_at": to_utc_iso_z(now),
        }

    @staticmethod
    async def _reembed_qa_pair(db, tenant_id: str, qa_id: str, question: str, answer: str) -> None:
        await db["kb_chunks"].delete_many({"tenant_id": tenant_id, "source_id": qa_id})
        gemini = GeminiClient()
        text = f"Q: {question}\nA: {answer}"
        embedding = await gemini.embed_text(text)
        await db["kb_chunks"].insert_one({
            "tenant_id": tenant_id,
            "source_type": "qa",
            "source_id": qa_id,
            "chunk_index": 0,
            "text": text,
            "embedding": embedding,
        })

    @staticmethod
    async def list_qa_pairs(tenant_id: str) -> list:
        db = KBQAService._get_db()
        docs = await db["kb_qa_pairs"].find({"tenant_id": tenant_id}) \
            .sort("updated_at", -1).to_list(length=None)
        return [
            {
                "qa_id": doc["qa_id"],
                "question": doc["question"],
                "answer": doc["answer"],
                "updated_at": to_utc_iso_z(doc["updated_at"]),
            }
            for doc in docs
        ]

    @staticmethod
    async def delete_qa_pair(tenant_id: str, qa_id: str) -> bool:
        db = KBQAService._get_db()
        result = await db["kb_qa_pairs"].delete_one({"qa_id": qa_id, "tenant_id": tenant_id})
        if result.deleted_count == 0:
            return False
        await db["kb_chunks"].delete_many({"tenant_id": tenant_id, "source_id": qa_id})
        return True
