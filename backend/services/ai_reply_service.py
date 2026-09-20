"""Retrieves knowledge base context and asks Gemini to answer, use a Shopify tool,
or escalate."""

import time
from dataclasses import dataclass
from typing import Optional
from repositories.mongo_client import MongoConnection
from services.redaction_service import redact_text
from services.gemini_client import GeminiClient
from services.shopify_order_service import ShopifyOrderService
from services.shopify_product_service import ShopifyProductService
from services.ecommerce_order_service import EcommerceOrderService
from config import get_settings
from utils.logger import logger


ESCALATE_TOOL = {
    "name": "escalate_to_human",
    "description": (
        "Call this when the provided knowledge base context does not contain enough "
        "information to answer the customer's question, or when the question is "
        "off-topic, angry, or ambiguous."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "reason": {"type": "string", "description": "Brief reason for escalating"}
        },
        "required": ["reason"],
    },
}

GET_ORDER_STATUS_TOOL = {
    "name": "get_order_status",
    "description": (
        "Call this when the customer asks about their order status, shipping, "
        "tracking, or delivery. Requires both the order number and the email "
        "address used on the order to verify identity — if either is missing "
        "from the conversation, ask the customer for it before calling this "
        "tool. Do not guess at order details."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "order_number": {"type": "string", "description": "The order number, e.g. #4521."},
            "email": {"type": "string", "description": "The email address used on the order."},
        },
        "required": ["order_number", "email"],
    },
}

GET_PRODUCT_INFO_TOOL = {
    "name": "get_product_info",
    "description": (
        "Call this when the customer asks about a specific product's price, "
        "description, variants (size/color/etc), or whether it's in stock. "
        "Do not guess at product details — if you can't find a clear product "
        "name or SKU in the customer's message, ask them to clarify which "
        "product they mean before calling this tool."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "product_query": {
                "type": "string",
                "description": "Product name, SKU, or search term as mentioned by the customer.",
            }
        },
        "required": ["product_query"],
    },
}

GET_MY_ORDERS_TOOL = {
    "name": "get_my_orders",
    "description": (
        "Call this when the customer asks about their own orders, order "
        "status, or order history. No parameters needed — the customer is "
        "already signed in and their identity is known from the session, "
        "so never ask them for an order number or email to use this tool."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
    },
}

BASE_SYSTEM_INSTRUCTION = (
    "You are a customer support assistant. Answer the customer's question using ONLY "
    "the information in the provided knowledge base context. Do not use outside "
    "knowledge and do not guess. If the context does not contain the answer, call "
    "the escalate_to_human function instead of answering."
)

SHOPIFY_SYSTEM_INSTRUCTION_ADDENDUM = (
    " You also have tools to check live order status and product information "
    "directly from the store. Use get_order_status for order/shipping/tracking "
    "questions and get_product_info for product price/availability/description "
    "questions, instead of guessing or relying on the knowledge base context for "
    "these topics."
)

ECOMMERCE_SYSTEM_INSTRUCTION_ADDENDUM = (
    " You also have a tool to look up the signed-in customer's own orders. "
    "Use get_my_orders for questions about their orders, order status, or "
    "order history instead of guessing or relying on the knowledge base "
    "context for these topics."
)


@dataclass
class AIReplyResult:
    answered: bool
    answer: Optional[str]
    escalate_reason: Optional[str]
    redacted_input: Optional[str] = None
    token_count: Optional[int] = None
    duration_ms: Optional[int] = None


class AIReplyService:
    @staticmethod
    async def has_knowledge_base_content(tenant_id: str) -> bool:
        db = MongoConnection.get_database()
        doc = await db["kb_chunks"].find_one({"tenant_id": tenant_id}, {"_id": 1})
        return doc is not None

    @staticmethod
    async def tenant_can_use_ai(tenant_id: str) -> bool:
        """True if the tenant has knowledge base content or a live Shopify/ecommerce
        connection — any of these is enough for generate_reply to potentially answer."""
        has_kb = await AIReplyService.has_knowledge_base_content(tenant_id)
        if has_kb:
            return True
        if await AIReplyService._has_shopify_connection(tenant_id):
            return True
        return AIReplyService._has_ecommerce_connection(tenant_id)

    @staticmethod
    async def _has_shopify_connection(tenant_id: str) -> bool:
        db = MongoConnection.get_database()
        tenant = await db["tenants"].find_one({"tenant_id": tenant_id})
        if not tenant:
            return False
        return bool(tenant.get("shopify_shop_domain") and tenant.get("shopify_access_token"))

    @staticmethod
    def _has_ecommerce_connection(tenant_id: str) -> bool:
        settings = get_settings()
        return bool(
            tenant_id
            and tenant_id == settings.ECOMMERCE_SHOP_TENANT_ID
            and settings.ECOMMERCE_SHOP_BASE_URL
            and settings.ECOMMERCE_SHOP_API_SECRET
        )

    @staticmethod
    async def generate_reply(
        tenant_id: str, customer_message: str, customer_identifier: Optional[str] = None
    ) -> AIReplyResult:
        try:
            redacted_message = redact_text(customer_message)
            gemini = GeminiClient()
            query_embedding = await gemini.embed_text(redacted_message)

            db = MongoConnection.get_database()
            chunks = await AIReplyService._search_chunks(db, tenant_id, query_embedding)
            shopify_connected = await AIReplyService._has_shopify_connection(tenant_id)
            ecommerce_connected = AIReplyService._has_ecommerce_connection(tenant_id)

            if not chunks and not shopify_connected and not ecommerce_connected:
                return AIReplyResult(
                    answered=False, answer=None,
                    escalate_reason="no_kb_match", redacted_input=redacted_message,
                )

            tools = [ESCALATE_TOOL]
            system_instruction = BASE_SYSTEM_INSTRUCTION
            if shopify_connected:
                tools += [GET_ORDER_STATUS_TOOL, GET_PRODUCT_INFO_TOOL]
                system_instruction += SHOPIFY_SYSTEM_INSTRUCTION_ADDENDUM
            if ecommerce_connected:
                tools += [GET_MY_ORDERS_TOOL]
                system_instruction += ECOMMERCE_SYSTEM_INSTRUCTION_ADDENDUM

            context = "\n\n".join(chunk["text"] for chunk in chunks) if chunks else "(no matching knowledge base content)"
            prompt = f"Knowledge base context:\n{context}\n\nCustomer question:\n{redacted_message}"
            start = time.monotonic()
            response = await gemini.generate_content(
                system_instruction=system_instruction,
                tools=tools,
                prompt=prompt,
            )
            duration_ms = round((time.monotonic() - start) * 1000)
            usage = getattr(response, "usage_metadata", None)
            token_count = getattr(usage, "total_token_count", None) if usage else None

            part = response.candidates[0].content.parts[0]
            function_call = part.function_call

            if function_call and function_call.name == "escalate_to_human":
                reason = function_call.args.get("reason", "model_escalated")
                return AIReplyResult(
                    answered=False, answer=None,
                    escalate_reason=reason, redacted_input=redacted_message,
                    token_count=token_count, duration_ms=duration_ms,
                )

            if function_call and function_call.name == "get_order_status":
                return await AIReplyService._handle_order_status_call(
                    tenant_id, function_call.args, redacted_message, token_count, duration_ms
                )

            if function_call and function_call.name == "get_product_info":
                return await AIReplyService._handle_product_info_call(
                    tenant_id, function_call.args, redacted_message, token_count, duration_ms
                )

            if function_call and function_call.name == "get_my_orders":
                return await AIReplyService._handle_my_orders_call(
                    tenant_id, customer_identifier, redacted_message, token_count, duration_ms
                )

            return AIReplyResult(
                answered=True, answer=response.text,
                escalate_reason=None, redacted_input=redacted_message,
                token_count=token_count, duration_ms=duration_ms,
            )

        except Exception as e:
            logger.error(f"AI reply generation failed for tenant {tenant_id}: {e}")
            return AIReplyResult(
                answered=False, answer=None,
                escalate_reason="ai_service_error", redacted_input=None,
            )

    @staticmethod
    async def _handle_order_status_call(
        tenant_id: str, args: dict, redacted_message: str,
        token_count: Optional[int], duration_ms: Optional[int],
    ) -> AIReplyResult:
        result = await ShopifyOrderService.get_order_status(
            tenant_id=tenant_id,
            order_number=args.get("order_number", ""),
            email=args.get("email", ""),
        )

        if result.get("error"):
            return AIReplyResult(
                answered=False, answer=None,
                escalate_reason="shopify_api_error", redacted_input=redacted_message,
                token_count=token_count, duration_ms=duration_ms,
            )

        if not result.get("verified"):
            return AIReplyResult(
                answered=True,
                answer="I couldn't verify that order — please double check the order number and email.",
                escalate_reason=None, redacted_input=redacted_message,
                token_count=token_count, duration_ms=duration_ms,
            )

        tracking_url = result.get("tracking_url")
        tracking_line = f" Track it here: {tracking_url}" if tracking_url else ""
        return AIReplyResult(
            answered=True,
            answer=f"Your order status is: {result['status']}.{tracking_line}",
            escalate_reason=None, redacted_input=redacted_message,
            token_count=token_count, duration_ms=duration_ms,
        )

    @staticmethod
    async def _handle_product_info_call(
        tenant_id: str, args: dict, redacted_message: str,
        token_count: Optional[int], duration_ms: Optional[int],
    ) -> AIReplyResult:
        result = await ShopifyProductService.get_product_info(
            tenant_id=tenant_id,
            product_query=args.get("product_query", ""),
        )

        if result.get("error"):
            return AIReplyResult(
                answered=False, answer=None,
                escalate_reason="shopify_api_error", redacted_input=redacted_message,
                token_count=token_count, duration_ms=duration_ms,
            )

        if not result.get("found"):
            return AIReplyResult(
                answered=True,
                answer="I couldn't find that product — could you tell me the exact product name?",
                escalate_reason=None, redacted_input=redacted_message,
                token_count=token_count, duration_ms=duration_ms,
            )

        availability = "Currently in stock." if result.get("available") else "Currently out of stock."
        return AIReplyResult(
            answered=True,
            answer=f"{result['title']} is priced at ${result['price']}. {result['description']} {availability}",
            escalate_reason=None, redacted_input=redacted_message,
            token_count=token_count, duration_ms=duration_ms,
        )

    @staticmethod
    async def _handle_my_orders_call(
        tenant_id: str, customer_identifier: Optional[str], redacted_message: str,
        token_count: Optional[int], duration_ms: Optional[int],
    ) -> AIReplyResult:
        if not customer_identifier:
            return AIReplyResult(
                answered=True,
                answer="I couldn't find your account on this conversation — please try signing in again.",
                escalate_reason=None, redacted_input=redacted_message,
                token_count=token_count, duration_ms=duration_ms,
            )

        result = await EcommerceOrderService.get_customer_orders(tenant_id, customer_identifier)

        if result.get("error"):
            return AIReplyResult(
                answered=False, answer=None,
                escalate_reason="ecommerce_api_error", redacted_input=redacted_message,
                token_count=token_count, duration_ms=duration_ms,
            )

        if not result.get("found"):
            return AIReplyResult(
                answered=True,
                answer="I don't see any orders on your account yet.",
                escalate_reason=None, redacted_input=redacted_message,
                token_count=token_count, duration_ms=duration_ms,
            )

        lines = []
        for order in result["orders"][:5]:
            placed = str(order.get("createdAt", ""))[:10]
            lines.append(
                f"- Order {order.get('id')}: {order.get('status')}, "
                f"${order.get('total')}, placed {placed}"
            )
        return AIReplyResult(
            answered=True,
            answer="Here are your orders:\n" + "\n".join(lines),
            escalate_reason=None, redacted_input=redacted_message,
            token_count=token_count, duration_ms=duration_ms,
        )

    @staticmethod
    async def _search_chunks(db, tenant_id: str, query_embedding: list, limit: int = 5) -> list:
        pipeline = [
            {
                "$vectorSearch": {
                    "index": "kb_vector_index",
                    "path": "embedding",
                    "queryVector": query_embedding,
                    "numCandidates": 50,
                    "limit": limit,
                    "filter": {"tenant_id": tenant_id},
                }
            },
            {"$project": {"text": 1, "_id": 0}},
        ]
        cursor = db["kb_chunks"].aggregate(pipeline)
        return [doc async for doc in cursor]
