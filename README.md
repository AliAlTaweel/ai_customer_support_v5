# AI Customer Support v5

Standalone AI chat + knowledge-base engine, extracted from the full
`ai_customer_support_v4.11` multi-tenant platform. This project keeps only
the AI-facing slice: message ingestion, Gemini-powered reply generation,
knowledge-base retrieval, and optional Shopify/ecommerce order/product
lookups the AI can use to ground its answers. Tenant/agent management,
Clerk auth, Stripe billing, and admin dashboards were left behind — this is
not a full platform, just the engine.

## Table of contents

- [Features](#features)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Getting started](#getting-started)
  - [Backend](#backend)
  - [Frontend](#frontend)
- [Configuration](#configuration)
- [Testing](#testing)
- [CI](#ci)
- [Email channel (Gmail)](#email-channel-gmail)
- [Coding standards](#coding-standards)

## Features

- Multi-channel chat ingestion — widget, email (Gmail), and a synchronous
  ecommerce relay endpoint — all funneled through one conversation model
- Gemini-powered replies grounded in a per-tenant knowledge base (PDF
  documents + manually authored Q&A pairs, retrieved via vector search)
- Optional Shopify/ecommerce tool calls (order status, product info, order
  history) the model can invoke mid-reply instead of guessing
- Automatic escalation to a human agent when the knowledge base can't answer
- Per-tenant API key auth, with hashed keys and a legacy plaintext fallback
- Safety-first email auto-reply: dry-run mode, sender allowlisting, rate
  limits, loop/bounce detection, and a full kill switch

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI, Motor (async MongoDB driver) |
| Database | MongoDB Atlas (required for `$vectorSearch`) |
| AI | Google Gemini (generation + embeddings) |
| Frontend | Next.js, React |
| Email | Gmail API (OAuth2, poll-based) |
| Testing | pytest, pytest-asyncio |

## Project structure

```
backend/
  routers/            HTTP endpoints — thin glue over services, no business logic
    chat.py             send/list/get/reply/read/close/reopen conversations
    knowledge_base.py   upload docs, manage Q&A pairs, toggle AI
    ecommerce_chat.py   synchronous relay endpoint for an external shop frontend
  services/            Orchestration and business logic
    chat_service.py            decides what happens to an inbound message
    reply_delivery_service.py  dispatches a reply to email/webhook
    ai_reply_service.py        retrieves KB context, asks Gemini, or escalates
    kb_document_service.py     PDF upload, chunking, embedding
    kb_qa_service.py           Q&A pair CRUD + re-embedding
    tenant_settings_service.py per-tenant settings (e.g. AI on/off)
    api_key_auth_service.py    shared API key validation
    gmail_client.py             Gmail API wrapper
    shopify_*, ecommerce_*      optional order/product lookups used as tool calls
  repositories/        Mongo persistence, no business logic
    conversation_repository.py
    processed_email_store.py
    mongo_client.py
  middleware/          API key auth, rate limiting
  models/              Pydantic request/response schemas
  scripts/             seed_tenant, gmail_auth, poll_gmail, run_dev.sh
  tests/               pytest suite (fakes over mocks — see backend/CLAUDE.md)
frontend/
  app/                 Next.js pages (conversations, knowledge base, emails, human agent)
  components/          Shared UI components
  lib/                 Backend API client
```

See `backend/CLAUDE.md` for the reasoning behind this layering.

## Prerequisites

- Python 3.12 (pinned — CI and the container image both use it; see `backend/CLAUDE.md`)
- Node.js 20+ (CI uses 26)
- A MongoDB Atlas cluster (required for the `kb_vector_index` vector search index)
- A Gemini API key
- (Optional) Shopify app credentials, an ecommerce demo-shop integration, and/or a Gmail OAuth client — each feature degrades gracefully if unconfigured

## Getting started

### Backend

1. ```
   cd backend
   python3.12 -m venv venv && source venv/bin/activate
   pip install -r requirements-dev.txt
   ```
2. Copy `.env.example` to `.env` and fill in `MONGODB_URL` and `GEMINI_API_KEY` (see [Configuration](#configuration))
3. `python -m scripts.seed_tenant --name "Acme Inc" --email admin@acme.com` — creates a tenant and prints an API key
4. Start the API:
   ```
   python main.py            # or: uvicorn main:app --reload
   ```
   If the email channel is configured (see below), use `./scripts/run_dev.sh`
   instead to also start the Gmail poller (starts both, stops both on Ctrl-C).
5. Call the API with the printed key:
   ```
   curl -X POST http://localhost:8000/api/chat/send \
     -H "Authorization: Bearer <api key>" \
     -H "Content-Type: application/json" \
     -d '{"customer_email": "test@example.com", "message": "Hi"}'
   ```

Interactive API docs are served at `http://localhost:8000/docs` while the
backend is running. Shopify and the ecommerce demo-shop integration are
optional — the AI answers from the knowledge base alone if neither is
configured.

### Frontend

1. `cd frontend && npm install`
2. Create `frontend/.env.local` (no `.env.example` is committed):
   ```
   NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
   NEXT_PUBLIC_API_KEY=<api key printed by scripts.seed_tenant>
   ```
3. `npm run dev` — serves the UI at `http://localhost:3000`

The backend must already be running for the frontend to load conversations
or the knowledge base. `npm run build` / `npm run start` run the production
build; `npm run lint` runs ESLint.

## Configuration

All backend settings live in `backend/.env` (see `backend/.env.example` for
the full, commented list). The required ones:

| Variable | Purpose |
|---|---|
| `MONGODB_URL` | Atlas connection string (vector search requires Atlas, not a local `mongod`) |
| `MONGODB_DATABASE_NAME` | Database name |
| `GEMINI_API_KEY` | Google Gemini API key |

Everything else — Shopify, the ecommerce relay, CORS, and the entire
`GMAIL_*` block — is optional and off by default.

## Testing

```
cd backend
source venv/bin/activate
python -m pytest
```

Run it from `backend/`, not the repo root: `pythonpath` and `testpaths` in
`pyproject.toml` resolve against pytest's rootdir. The suite needs no
database and no API keys — `tests/conftest.py` supplies placeholder env vars
and the tests use fakes.

The suite (`backend/tests/`) uses hand-written in-memory fakes (e.g.
`FakeGmailClient`, `InMemoryProcessedEmailStore`) rather than mocks, so
assertions exercise real behavior, not just call counts. See
`backend/CLAUDE.md` for the testing conventions this codebase follows.

## CI

Two GitHub Actions workflows run on every pull request and push to `main`,
each filtered to the code it covers:

| Workflow | Gates | Advisory |
|---|---|---|
| `backend-ci` | `ruff check`, `pytest`, and a container build that must boot as a non-root user and serve `/health` against a `mongo:7` service | `black --check`, `mypy` |
| `frontend-ci` | `next typegen`, `tsc --noEmit`, `next lint`, `next build` | — |

The backend job also asserts the image ships no secrets: it plants decoy
`.env`/`credentials.json` files in the build context first, so the check
fails if `backend/.dockerignore` ever stops excluding them.

`backend/Dockerfile` builds the deployable image. It binds
`${PORT:-8000}`, so the same image runs on a platform that injects `PORT`;
the Gmail poller runs from that image with `python -m scripts.poll_gmail` as
the command, keeping it a separate process from the API.

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

## Coding standards

Backend conventions (SRP boundaries, function-length guidance, and other
practices) are documented in `backend/CLAUDE.md`. Frontend conventions are
in `frontend/CLAUDE.md`.
