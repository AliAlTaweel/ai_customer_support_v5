"""PDF knowledge-base document ingestion and management."""

import uuid
from datetime import datetime, timezone
from io import BytesIO
from pypdf import PdfReader
from repositories.mongo_client import MongoConnection
from services.gemini_client import GeminiClient
from services.chunking import chunk_text
from utils.logger import logger
from utils.time_format import to_utc_iso_z


class KBDocumentService:
    """Business logic for uploading and managing PDF knowledge-base documents."""

    @staticmethod
    def _get_db():
        return MongoConnection.get_database()

    @staticmethod
    async def upload_document(tenant_id: str, filename: str, file_bytes: bytes) -> dict:
        db = KBDocumentService._get_db()
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
        db = KBDocumentService._get_db()
        docs = await db["kb_documents"].find({"tenant_id": tenant_id}) \
            .sort("uploaded_at", -1).to_list(length=None)
        return [
            {
                "document_id": doc["document_id"],
                "filename": doc["filename"],
                "status": doc["status"],
                "chunk_count": doc["chunk_count"],
                "uploaded_at": to_utc_iso_z(doc["uploaded_at"]),
            }
            for doc in docs
        ]

    @staticmethod
    async def delete_document(tenant_id: str, document_id: str) -> bool:
        db = KBDocumentService._get_db()
        result = await db["kb_documents"].delete_one({"document_id": document_id, "tenant_id": tenant_id})
        if result.deleted_count == 0:
            return False
        await db["kb_chunks"].delete_many({"tenant_id": tenant_id, "source_id": document_id})
        return True
