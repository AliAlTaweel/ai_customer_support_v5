"""Mongo access for conversations and their messages. No business logic --
callers decide what to query for and what the results mean."""

from typing import Any, Dict, List, Optional, Tuple

from repositories.mongo_client import MongoConnection


class ConversationRepository:
    """CRUD over the `conversations` and `messages` collections."""

    @staticmethod
    def _get_db():
        return MongoConnection.get_database()

    @staticmethod
    async def find_conversation(query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        db = ConversationRepository._get_db()
        return await db["conversations"].find_one(query)

    @staticmethod
    async def insert_conversation(doc: Dict[str, Any]) -> str:
        db = ConversationRepository._get_db()
        result = await db["conversations"].insert_one(doc)
        return str(result.inserted_id)

    @staticmethod
    async def update_conversation(
        conversation_id: str,
        set_fields: Optional[Dict[str, Any]] = None,
        inc_fields: Optional[Dict[str, Any]] = None,
    ) -> None:
        update: Dict[str, Any] = {}
        if set_fields:
            update["$set"] = set_fields
        if inc_fields:
            update["$inc"] = inc_fields
        if not update:
            return
        db = ConversationRepository._get_db()
        await db["conversations"].update_one({"conversation_id": conversation_id}, update)

    @staticmethod
    async def insert_message(doc: Dict[str, Any]) -> str:
        db = ConversationRepository._get_db()
        result = await db["messages"].insert_one(doc)
        return str(result.inserted_id)

    @staticmethod
    async def mark_message(message_id: str, set_fields: Dict[str, Any]) -> None:
        db = ConversationRepository._get_db()
        await db["messages"].update_one({"message_id": message_id}, {"$set": set_fields})

    @staticmethod
    async def find_conversation_for_tenant(
        conversation_id: str, tenant_id: str
    ) -> Optional[Dict[str, Any]]:
        return await ConversationRepository.find_conversation(
            {"conversation_id": conversation_id, "tenant_id": tenant_id}
        )

    @staticmethod
    async def list_conversations(
        query: Dict[str, Any], limit: int, offset: int
    ) -> Tuple[List[Dict[str, Any]], int]:
        db = ConversationRepository._get_db()
        total = await db["conversations"].count_documents(query)
        docs = await db["conversations"].find(query) \
            .sort("created_at", -1) \
            .skip(offset) \
            .limit(limit) \
            .to_list(length=limit)
        return docs, total

    @staticmethod
    async def get_messages(conversation_id: str, tenant_id: str) -> List[Dict[str, Any]]:
        db = ConversationRepository._get_db()
        return await db["messages"].find({
            "conversation_id": conversation_id,
            "tenant_id": tenant_id,
        }).sort("created_at", 1).to_list(length=None)

    @staticmethod
    async def mark_customer_messages_read(conversation_id: str, tenant_id: str) -> None:
        db = ConversationRepository._get_db()
        await db["messages"].update_many(
            {
                "conversation_id": conversation_id,
                "tenant_id": tenant_id,
                "sender": "customer",
            },
            {"$set": {"read": True}},
        )

    @staticmethod
    async def get_unread_outbound_messages(
        conversation_id: str, tenant_id: str
    ) -> List[Dict[str, Any]]:
        """Agent/AI messages not yet delivered to the customer's own client
        (used by channels, like ecommerce, where the customer polls for replies)."""
        db = ConversationRepository._get_db()
        return await db["messages"].find({
            "conversation_id": conversation_id,
            "tenant_id": tenant_id,
            "sender": {"$in": ["agent", "ai"]},
            "read": False,
        }).sort("created_at", 1).to_list(length=None)

    @staticmethod
    async def mark_outbound_messages_read(conversation_id: str) -> None:
        db = ConversationRepository._get_db()
        await db["messages"].update_many(
            {
                "conversation_id": conversation_id,
                "sender": {"$in": ["agent", "ai"]},
                "read": False,
            },
            {"$set": {"read": True}},
        )
