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
- `frontend/` — Next.js app (agent console UI: conversations, knowledge base, emails tab)

## Running it — backend

1. `cd backend && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill in `MONGODB_URL` (Atlas, for vector search) and `GEMINI_API_KEY`
3. `python -m scripts.seed_tenant --name "Acme Inc" --email admin@acme.com` — creates a tenant and prints an API key
4. `python main.py` (or `uvicorn main:app --reload`) — or, if the email
   channel is configured (see below), `./scripts/run_dev.sh` to also start
   the Gmail poller
5. `POST /api/chat/send` and `POST /api/knowledge-base/upload` with `Authorization: Bearer <api key>`

Shopify and the ecommerce demo-shop integration are optional — the AI
answers from the knowledge base alone if neither is configured.

## Running it — frontend

1. `cd frontend && npm install`
2. Create `frontend/.env.local` (no `.env.example` is committed) with:
   ```
   NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
   NEXT_PUBLIC_API_KEY=<api key printed by scripts.seed_tenant>
   ```
3. `npm run dev` — serves the UI at `http://localhost:3000`, talking to the
   backend over `NEXT_PUBLIC_BACKEND_URL`

The backend must already be running (see above) for the frontend to load
conversations or the knowledge base. `npm run build` / `npm run start` run
the production build; `npm run lint` runs ESLint.

## Email channel (Gmail)

The AI can read a Gmail inbox and auto-reply to support email.

1. Put `GMAIL_CLIENT_ID` and `GMAIL_CLIENT_SECRET` in `backend/.env` from your
   OAuth 2.0 Client ID (type: Desktop app)
2. `cd backend && python -m scripts.gmail_auth` — one-time browser consent;
   paste the printed `GMAIL_REFRESH_TOKEN` into `.env`
3. Fill in the rest of the `GMAIL_*` block (see `.env.example`)
4. `python -m scripts.poll_gmail --once` to run a single cycle, or
   `./scripts/run_dev.sh` to run the API and the poller together for local
   dev (starts both, stops both on Ctrl-C)

Bring it up in three steps, each a config change rather than a code change:

| Step | `GMAIL_DRY_RUN` | `GMAIL_ALLOWED_SENDERS` | Effect |
|---|---|---|---|
| 1 | `true` | your own address | Replies logged, nothing sent |
| 2 | `false` | your own address | Real sends, bounded audience |
| 3 | `false` | `*` | Open to all senders |

Defaults are the safe end: an unconfigured install sends nothing. The poller
runs as its own process — the API (`python main.py`) does not need it and is
unaffected if it stops. `GMAIL_ENABLED=false` is a full kill switch: it stops
the poller starting *and* stops outbound mail on the API's own send path
(agent replies from the Emails tab, AI replies to existing email threads).

**Deferred mail during steps 1–2 (and under rate limits):** a message whose
sender is not on `GMAIL_ALLOWED_SENDERS`, or that arrives once the hourly
send caps are reached, is counted as `deferred` in the cycle summary. It is
deliberately left **unread and unclaimed** — nothing is written to
`processed_emails` and nothing is marked read in Gmail — so it will be
reconsidered on every subsequent cycle and answered once the allowlist is
widened or the rate-limit window rolls over. The consequence is that such
messages keep reappearing in the unread window until they are answerable or
you deal with them by hand in Gmail. That is intended: claiming them would
be irreversible (see below) and would destroy legitimate customer mail
permanently, which is strictly worse than the noise.

This is only for *transient* reasons. Messages rejected for what they are —
autoresponders, bulk/mailing-list mail, bounces, `noreply` senders, mail from
the mailbox to itself, empty bodies, and senders whose
`Authentication-Results` show a hard `dkim=fail`/`spf=fail` — are counted as
`skipped`, recorded, and marked read, because no later cycle would decide
differently. (A missing or inconclusive authentication result is not treated
as a failure.)

**On failed sends:** the poller logs a count per outcome after every cycle
(e.g. `replied=2, delivery_failed=1`), including `delivery_failed` — the AI
produced an answer but the Gmail send itself failed (e.g. transient API
error). A single failed cycle is logged and the poller moves on to the next
interval rather than crashing. That email is recorded in the
`processed_emails` collection as `skipped` with `skip_reason: "delivery_failed"`.
Because `claim()` inserts into a unique index once per message, a
`delivery_failed` email is **not retried automatically** on the next poll —
recovering it means deleting that record from `processed_emails` so the
message is claimed again (and marking it unread in Gmail). It *is* marked
read: the claim cannot be released, so leaving it unread would only cost a
Gmail fetch every cycle forever while crowding out new mail in the capped
unread window.

If the AI answered and the send failed, the reply is still stored in the
conversation but stamped `delivery_status: "failed"`, and the Emails tab
renders it as visibly undelivered rather than as a normal sent message. The
same applies to a human agent's reply, whose send failure is returned to the
Emails tab as an error (HTTP 502) instead of a silent success.
