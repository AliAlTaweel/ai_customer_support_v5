"""
Database connection and collection/index setup, backed directly by Motor/PyMongo
via MongoConnection (no ORM layer).
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)


class Database:
    """Database connection and schema lifecycle manager"""

    @classmethod
    async def connect(cls) -> None:
        """Connect to MongoDB"""
        from config import get_settings
        from repositories.mongo_client import MongoConnection

        settings = get_settings()
        await MongoConnection.connect(settings.MONGODB_URL, settings.MONGODB_DATABASE_NAME)
        logger.info("✓ Connected to MongoDB")

    @classmethod
    async def disconnect(cls) -> None:
        """Disconnect from MongoDB"""
        from repositories.mongo_client import MongoConnection

        await MongoConnection.disconnect()
        logger.info("✓ Disconnected from MongoDB")

    @classmethod
    async def init_chat_collections(cls) -> None:
        """Initialize chat collections with proper indexes"""
        from repositories.mongo_client import MongoConnection

        db = MongoConnection.get_database()

        try:
            conversations = db["conversations"]
            conversations.create_index([("tenant_id", 1), ("created_at", -1)])
            conversations.create_index([("tenant_id", 1), ("customer_email", 1)])
            conversations.create_index([("tenant_id", 1), ("status", 1)])
        except Exception:
            pass  # Collection or index may already exist

        try:
            messages = db["messages"]
            messages.create_index([("conversation_id", 1), ("created_at", -1)])
            messages.create_index([("tenant_id", 1), ("created_at", -1)])
            messages.create_index([("conversation_id", 1), ("read", 1)])
        except Exception:
            pass

        try:
            api_keys = db["tenant_api_keys"]
            api_keys.create_index([("tenant_id", 1)])
            api_keys.create_index([("api_key_prefix", 1)])
        except Exception:
            pass

    @classmethod
    async def init_knowledge_base_collections(cls) -> None:
        """Initialize knowledge base collections with proper indexes"""
        from pymongo.operations import SearchIndexModel
        from repositories.mongo_client import MongoConnection

        db = MongoConnection.get_database()

        try:
            kb_documents = db["kb_documents"]
            await kb_documents.create_index([("tenant_id", 1), ("uploaded_at", -1)])
        except Exception:
            pass

        try:
            kb_qa_pairs = db["kb_qa_pairs"]
            await kb_qa_pairs.create_index([("tenant_id", 1), ("updated_at", -1)])
        except Exception:
            pass

        try:
            kb_chunks = db["kb_chunks"]
            await kb_chunks.create_index([("tenant_id", 1), ("source_id", 1)])
        except Exception:
            pass

        try:
            vector_index = SearchIndexModel(
                definition={
                    "fields": [
                        {
                            "type": "vector",
                            "path": "embedding",
                            "numDimensions": 3072,
                            "similarity": "cosine",
                        },
                        {
                            "type": "filter",
                            "path": "tenant_id",
                        },
                    ]
                },
                name="kb_vector_index",
                type="vectorSearch",
            )
            await db["kb_chunks"].create_search_index(model=vector_index)
        except Exception as e:
            logger.info(f"kb_vector_index setup skipped (may already exist): {e}")

    @classmethod
    def get_database(cls) -> Any:
        """Get the Motor database instance"""
        from repositories.mongo_client import MongoConnection

        return MongoConnection.get_database()
