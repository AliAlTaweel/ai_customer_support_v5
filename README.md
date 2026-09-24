# AI Customer Support v5

Standalone AI chat + knowledge-base engine, extracted from the full
`ai_customer_support_v4.11` multi-tenant platform. This project keeps only
the AI-facing slice: message ingestion, Gemini-powered reply generation,
knowledge-base retrieval, and optional Shopify/ecommerce order/product
lookups the AI can use to ground its answers. Tenant/agent management,
Clerk auth, Stripe billing, admin dashboards, and the WhatsApp/email
channels were left behind — this is not a full platform, just the engine.

## What's here

- `backend/` — FastAPI service
  - `routers/chat.py` — send/list/get/reply/read/close/reopen conversations
  - `routers/knowledge_base.py` — upload docs, manage Q&A pairs, toggle AI
  - `routers/ecommerce_chat.py` — synchronous relay endpoint for an external shop frontend
  - `services/ai_reply_service.py`, `kb_service.py`, `gemini_client.py` — the AI engine
  - `services/shopify_*`, `ecommerce_*` — optional order/product lookups used as tool calls during reply generation
  - `middleware/api_key_auth.py` — bearer API key → tenant_id (no Clerk)

## Running it

1. `cd backend && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill in `MONGODB_URL` (Atlas, for vector search) and `GEMINI_API_KEY`
3. `python -m scripts.seed_tenant --name "Acme Inc" --email admin@acme.com` — creates a tenant and prints an API key
4. `python main.py` (or `uvicorn main:app --reload`)
5. `POST /api/chat/send` and `POST /api/knowledge-base/upload` with `Authorization: Bearer <api key>`

Shopify and the ecommerce demo-shop integration are optional — the AI
answers from the knowledge base alone if neither is configured.
