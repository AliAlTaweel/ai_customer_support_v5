"""Knowledge base service: PDF documents, Q&A pairs, and per-tenant AI settings."""

import uuid
from datetime import datetime, timezone
from io import BytesIO
from typing import Optional
from pypdf import PdfReader
from repositories.mongo_client import MongoConnection
from services.gemini_client import GeminiClient
from services.chunking import chunk_text
from utils.logger import logger


class KBService:
    """Business logic for the tenant Knowledge Base page."""

    @staticmethod
    def _get_db():
        return MongoConnection.get_database()

    @staticmethod
    def _to_utc_iso_z(dt: datetime) -> str:
        """Format a datetime as a UTC ISO-8601 string with a trailing 'Z'.

        MongoDB (via Motor, tz_aware=False) returns naive datetimes that are
        implicitly UTC. Treat naive datetimes as UTC explicitly before
        formatting so the result is always Z-suffixed, regardless of whether
        the datetime read back is naive or already tz-aware.
        """
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")

    @staticmethod
    async def upload_document(tenant_id: str, filename: str, file_bytes: bytes) -> dict:
        db = KBService._get_db()
        document_id = f"doc_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        await db["kb_documents"].insert_one({
            "document_id": document_id,
            "tenant_id": tenant_id,
            "filename": filename,
            "status": "processing",
            "chunk_count": 0,
            "uploaded_at": now,
            "updated_at": now,
        })

        try:
            reader = PdfReader(BytesIO(file_bytes))
            full_text = "\n".join(page.extract_text() or "" for page in reader.pages)

            if not full_text.strip():
                await db["kb_documents"].update_one(
                    {"document_id": document_id},
                    {"$set": {"status": "failed", "updated_at": datetime.now(timezone.utc)}}
                )
                return {"document_id": document_id, "filename": filename, "status": "failed"}

            chunks = chunk_text(full_text)
            gemini = GeminiClient()
            chunk_docs = []
            for index, chunk in enumerate(chunks):
                embedding = await gemini.embed_text(chunk)
                chunk_docs.append({
                    "tenant_id": tenant_id,
                    "source_type": "pdf",
                    "source_id": document_id,
                    "chunk_index": index,
                    "text": chunk,
                    "embedding": embedding,
                })

            if chunk_docs:
                await db["kb_chunks"].insert_many(chunk_docs)

            await db["kb_documents"].update_one(
                {"document_id": document_id},
                {"$set": {
                    "status": "ready",
                    "chunk_count": len(chunk_docs),
                    "updated_at": datetime.now(timezone.utc),
                }}
            )
            return {"document_id": document_id, "filename": filename, "status": "ready"}

        except Exception as e:
            logger.error(f"Failed to process document {document_id}: {e}")
            await db["kb_documents"].update_one(
                {"document_id": document_id},
                {"$set": {"status": "failed", "updated_at": datetime.now(timezone.utc)}}
            )
            return {"document_id": document_id, "filename": filename, "status": "failed"}

    @staticmethod
    async def list_documents(tenant_id: str) -> list:
        db = KBService._get_db()
        docs = await db["kb_documents"].find({"tenant_id": tenant_id}) \
            .sort("uploaded_at", -1).to_list(length=None)
        return [
            {
                "document_id": doc["document_id"],
                "filename": doc["filename"],
                "status": doc["status"],
                "chunk_count": doc["chunk_count"],
                "uploaded_at": KBService._to_utc_iso_z(doc["uploaded_at"]),
            }
            for doc in docs
        ]

    @staticmethod
    async def delete_document(tenant_id: str, document_id: str) -> bool:
        db = KBService._get_db()
        result = await db["kb_documents"].delete_one({"document_id": document_id, "tenant_id": tenant_id})
        if result.deleted_count == 0:
            return False
        await db["kb_chunks"].delete_many({"tenant_id": tenant_id, "source_id": document_id})
        return True

    @staticmethod
    async def create_qa_pair(tenant_id: str, question: str, answer: str) -> dict:
        db = KBService._get_db()
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

        await KBService._reembed_qa_pair(db, tenant_id, qa_id, question, answer)

        return {
            "qa_id": qa_id,
            "question": question,
            "answer": answer,
            "updated_at": KBService._to_utc_iso_z(now),
        }

    @staticmethod
    async def update_qa_pair(
        tenant_id: str, qa_id: str, question: Optional[str], answer: Optional[str]
    ) -> Optional[dict]:
        db = KBService._get_db()
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

        await KBService._reembed_qa_pair(db, tenant_id, qa_id, new_question, new_answer)

        return {
            "qa_id": qa_id,
            "question": new_question,
            "answer": new_answer,
            "updated_at": KBService._to_utc_iso_z(now),
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
        db = KBService._get_db()
        docs = await db["kb_qa_pairs"].find({"tenant_id": tenant_id}) \
            .sort("updated_at", -1).to_list(length=None)
        return [
            {
                "qa_id": doc["qa_id"],
                "question": doc["question"],
                "answer": doc["answer"],
                "updated_at": KBService._to_utc_iso_z(doc["updated_at"]),
            }
            for doc in docs
        ]

    @staticmethod
    async def delete_qa_pair(tenant_id: str, qa_id: str) -> bool:
        db = KBService._get_db()
        result = await db["kb_qa_pairs"].delete_one({"qa_id": qa_id, "tenant_id": tenant_id})
        if result.deleted_count == 0:
            return False
        await db["kb_chunks"].delete_many({"tenant_id": tenant_id, "source_id": qa_id})
        return True

    @staticmethod
    async def get_ai_enabled(tenant_id: str) -> bool:
        db = KBService._get_db()
        tenant = await db["tenants"].find_one({"tenant_id": tenant_id})
        return bool(tenant and tenant.get("ai_enabled", False))

    @staticmethod
    async def set_ai_enabled(tenant_id: str, ai_enabled: bool) -> bool:
        db = KBService._get_db()
        await db["tenants"].update_one(
            {"tenant_id": tenant_id},
            {"$set": {"ai_enabled": ai_enabled}}
        )
        return ai_enabled
