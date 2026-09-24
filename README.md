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

## Email channel (Gmail)

The AI can read a Gmail inbox and auto-reply to support email.

1. Put `GMAIL_CLIENT_ID` and `GMAIL_CLIENT_SECRET` in `backend/.env` from your
   OAuth 2.0 Client ID (type: Desktop app)
2. `cd backend && python -m scripts.gmail_auth` — one-time browser consent;
   paste the printed `GMAIL_REFRESH_TOKEN` into `.env`
3. Fill in the rest of the `GMAIL_*` block (see `.env.example`)
4. `python -m scripts.poll_gmail --once` to run a single cycle

Bring it up in three steps, each a config change rather than a code change:

| Step | `GMAIL_DRY_RUN` | `GMAIL_ALLOWED_SENDERS` | Effect |
|---|---|---|---|
| 1 | `true` | your own address | Replies logged, nothing sent |
| 2 | `false` | your own address | Real sends, bounded audience |
| 3 | `false` | `*` | Open to all senders |

Defaults are the safe end: an unconfigured install sends nothing. The poller
runs as its own process — the API (`python main.py`) does not need it and is
unaffected if it stops.

**On failed sends:** each poll cycle's result includes a count per outcome,
including `delivery_failed` — the AI produced an answer but the Gmail send
itself failed (e.g. transient API error). That email is recorded in the
`processed_emails` collection as `skipped` with `skip_reason: "delivery_failed"`.
Because `claim()` inserts into a unique index once per message, a
`delivery_failed` email is **not retried automatically** on the next poll —
recovering it means deleting that record from `processed_emails` so the
message is claimed again.
