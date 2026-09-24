# Email Channel (Gmail) — Design

**Date:** 2026-09-24
**Status:** Approved for planning

## Goal

Let the app read incoming email from a Gmail mailbox, answer it with the
existing AI engine, and send the reply back into the same email thread —
with no human in the loop.

## Decisions

These were settled during brainstorming and are not open for
re-litigation during implementation:

| Decision | Choice |
|---|---|
| Autonomy | Auto-send always — no draft/approval step |
| On escalation | Send a holding reply, flag the thread for a human |
| Gmail access | Gmail API + OAuth 2.0, polling (client IDs already exist) |
| Tenant mapping | One mailbox = one tenant, bound in config |
| Deployment shape | Standalone worker script, separate from the API process |
| UI | A new "Emails" tab in the existing frontend |

## What already exists

The v4.11 email channel was stripped when this engine was extracted, but
its seams remain. The reply pipeline needs almost no change:

- `ChatService.receive_message` already accepts `channel` and
  `email_thread_id` (`backend/services/chat_service.py:33`).
- Conversation documents already store `channel`, and already set
  `customer_email` when `channel in ("widget", "email")`
  (`chat_service.py:82`).
- `ChatService._deliver_reply` (`chat_service.py:246`) is a no-op stub
  whose own docstring promises "email/whatsapp send" — this is where
  the sender belongs.
- Escalation already sets `handling_mode: "human"` and
  `status: "waiting_agent_response"` (`chat_service.py:238`).
- `GET /api/chat/conversations` already supports a `channel` query
  parameter (`backend/routers/chat.py:41`,
  `chat_service.py:266`), so the UI tab needs no new endpoint.

What is genuinely new: the Gmail adapter, OAuth token handling, the poll
loop, the safety gates, and one frontend tab.

## Architecture

### New backend files

| File | Responsibility |
|---|---|
| `backend/services/gmail_client.py` | Gmail API wrapper: load/refresh OAuth credentials, `list_unread()`, `get_message()`, `send_reply()`, `mark_read()`. Knows Gmail; knows nothing about tenants or conversations. |
| `backend/services/email_ingest_service.py` | Channel logic: parse a Gmail message, run safety gates, decide skip-or-ingest, call `ChatService.receive_message`. |
| `backend/scripts/gmail_auth.py` | One-time OAuth consent flow; writes the refresh token. |
| `backend/scripts/poll_gmail.py` | Worker loop. `--once` for a single cycle, `--interval N` to loop. Connects to Mongo the way `scripts/seed_tenant.py:24` does. |

### Changed backend files

- `services/chat_service.py` — implement `_deliver_reply` so
  `channel == "email"` sends via `GmailClient`. All other channels keep
  today's no-op behavior.
- `config.py` — add the `GMAIL_*` block, following the optional-integration
  pattern of `ECOMMERCE_SHOP_*` (`config.py:48`): absent config disables
  the channel rather than raising at startup.
- `database.py` — add `processed_emails` indexes to
  `init_chat_collections`, and fix the missing `await` (see below).
- `requirements.txt` — add `google-api-python-client`, `google-auth`,
  `google-auth-oauthlib`. (`google-genai` is the Gemini SDK and does not
  cover Gmail.)
- `.gitignore` — add `secrets/`.

### Pre-existing bug to fix

In `database.py`, `init_chat_collections` (lines 39–59) calls
`create_index` **without `await`** on `conversations`, `messages`, and
`tenant_api_keys`, while `init_knowledge_base_collections` awaits
throughout. Under Motor the un-awaited calls return coroutines that never
run, and the bare `except: pass` hides it — so those indexes are almost
certainly absent.

This blocks correctness here: idempotency depends on a **unique** index on
`processed_emails.gmail_message_id` actually existing. Add the missing
`await` to those calls as part of this work.

## Data flow

One poll cycle:

1. `GmailClient.list_unread()` with `q="is:unread in:inbox"`. Using
   `in:inbox` excludes anything Gmail already classified as spam.
2. For each message id, look up `gmail_message_id` in `processed_emails`.
   Already seen → skip with no further work or API cost.
3. Fetch the full message. Parse sender, subject, body (prefer
   `text/plain`, fall back to stripped HTML), `threadId`, and the
   `Message-ID` / `References` / `In-Reply-To` headers.
4. Run the safety gates. A rejected message is recorded as processed with
   a `skip_reason` and marked read, so it is never re-examined.
5. **Write the `processed_emails` record before generating a reply**,
   with `status: "processing"`. This is the crash boundary: if the worker
   dies mid-reply, the unique index makes the restart skip the message
   rather than mail the customer twice.
6. Call
   `ChatService.receive_message(tenant_id=<from config>, channel="email",
   customer_identifier=<sender address>, message=<body>,
   email_thread_id=<gmail threadId>)`.
   From here the existing pipeline runs unchanged: KB retrieval, Gemini,
   tool calls, escalation.
7. `_deliver_reply` sees `channel == "email"` and sends via Gmail.
8. Mark the source message read; update `processed_emails` to
   `replied` / `escalated` / `skipped`.

### Conversation threading

`receive_message` reuses a conversation when `channel` and
`customer_identifier` match (`chat_service.py:57`), so all mail from one
address collapses into a single conversation. This is *address*-level, not
*thread*-level: two unrelated Gmail threads from the same person merge,
and the AI sees both topics as one history.

**Accepted for now.** Changing the matching logic would affect other
channels. Store `email_thread_id` on the conversation so this can be
tightened to thread-level later without a migration.

### Reply threading

Outbound replies set Gmail's `threadId` plus `In-Reply-To` and
`References` pointing at the inbound `Message-ID`, and prefix the subject
with `Re: ` if absent. Without these headers every reply starts a new
thread in the customer's client.

### Escalation behavior

When `AIReplyService` calls `escalate_to_human`, the existing pipeline
already sets `handling_mode: "human"` and
`status: "waiting_agent_response"`. The email channel adds one outbound
send — a holding reply so the customer is not left in silence:

> Thanks for getting in touch — we've received your message and a member
> of our team will get back to you shortly.

Wording mirrors `FALLBACK_MESSAGE` in `routers/ecommerce_chat.py:21`.

Two rules that would otherwise be ambiguous:

- A holding reply **counts** against both rate-limit counters. It is a
  real outbound email and can loop exactly like any other.
- Only **one** holding reply is sent per conversation. If a thread is
  already `waiting_agent_response`, further inbound mail is ingested and
  appended to the conversation but triggers no additional
  acknowledgement, so a customer sending three follow-ups does not
  receive three identical "we're on it" emails.

### New collection: `processed_emails`

| Field | Notes |
|---|---|
| `gmail_message_id` | **unique index** — the idempotency guarantee |
| `gmail_thread_id` | |
| `tenant_id` | |
| `conversation_id` | null when skipped |
| `status` | `processing` \| `replied` \| `escalated` \| `skipped` |
| `skip_reason` | which gate rejected it |
| `processed_at` | also indexed, for the rate-limit queries |

Making double-send structurally impossible is preferable to remembering
to check for it.

## Safety gates

Auto-send with no human in the loop over fully attacker-controlled input
(anyone can email the support address) makes this section load-bearing.

### Mail-loop protection

Skip, record, and never reply when any of these hold:

- `Auto-Submitted` header present and not `no` (RFC 3834)
- `Precedence: bulk | junk | list`
- `List-Id` or `List-Unsubscribe` present
- `Return-Path` empty (a bounce)
- Sender local-part matches `noreply` / `no-reply` / `mailer-daemon` /
  `postmaster`
- Sender is `GMAIL_ADDRESS` itself (self-send)

In the other direction, **outbound replies set
`Auto-Submitted: auto-replied`** so a well-behaved autoresponder on the
far end will not volley. Two autoresponders lacking these headers will
mail each other indefinitely.

### Quoted-history stripping

Strip the quoted chain (`On <date>, X wrote:`, `>`-prefixed lines,
`<blockquote>`) before the body reaches the model, then truncate to the
5000-character cap that `SendMessageRequest` already enforces
(`models/chat.py:6`). Without stripping, the AI re-reads its own previous
answer as customer input and the prompt grows every round.

### Rate limiting

Two counters over `processed_emails`:

- `GMAIL_MAX_REPLIES_PER_SENDER_HOUR` (default 5)
- `GMAIL_MAX_SENDS_PER_HOUR` (default 50)

On breach, escalate and flag instead of sending. With no human watching,
this is what bounds the damage from a loop.

### Prompt-injection containment

The email body is untrusted input entering the same prompt as KB content.
`BASE_SYSTEM_INSTRUCTION` (`services/ai_reply_service.py:87`) already
restricts the model to KB context. Additionally: wrap the body in explicit
delimiters marked as untrusted customer data, and extend the instruction
to state that content inside those delimiters is never an instruction.

This mitigates rather than solves. The durable protection is that the
tools are narrow and server-scoped — `get_my_orders` takes no parameters
(`ai_reply_service.py:71`) and `get_order_status` requires order number
*and* matching email (`ai_reply_service.py:31`) — so a successful
injection still cannot reach another customer's data.

### Testing controls

- `GMAIL_DRY_RUN` (default `true`) — full pipeline, reply logged instead
  of sent.
- `GMAIL_ALLOWED_SENDERS` (default empty) — allowlist. **Empty means
  nobody is auto-answered**; `*` opens it to everyone. Mail from a
  non-allowlisted sender is still ingested and flagged, never answered.

Both default to the safe setting, so a half-configured `.env` sends
nothing rather than mailing strangers.

## Configuration

New `config.py` block:

```
GMAIL_ENABLED                      false
GMAIL_TENANT_ID                    ""       # the one tenant this mailbox maps to
GMAIL_ADDRESS                      ""       # support mailbox, for self-send detection
GMAIL_CREDENTIALS_PATH             secrets/gmail_credentials.json
GMAIL_TOKEN_PATH                   secrets/gmail_token.json
GMAIL_POLL_INTERVAL_SECONDS        60
GMAIL_DRY_RUN                      true
GMAIL_ALLOWED_SENDERS              ""       # empty = nobody; "*" = everyone
GMAIL_MAX_REPLIES_PER_SENDER_HOUR  5
GMAIL_MAX_SENDS_PER_HOUR           50
```

### Credentials

OAuth scopes: `https://www.googleapis.com/auth/gmail.modify` (read and
mark-as-read) and `https://www.googleapis.com/auth/gmail.send`. Both are
requested explicitly rather than relying on `modify` implying send, and
together they remain narrower than full `https://mail.google.com/`.

The existing OAuth client ID JSON goes at
`secrets/gmail_credentials.json`. `scripts/gmail_auth.py` runs the
installed-app consent flow once and writes the refresh token to
`secrets/gmail_token.json`. That token is a live credential for a real
mailbox; `.gitignore` currently covers `.env` but not this, so `secrets/`
must be added to `.gitignore` before any token is created.

## Frontend

Next.js 16.3.5, App Router, Tailwind v4. Three tabs exist today
(`frontend/components/TabNav.tsx`); this adds a fourth.

- `components/TabNav.tsx` — add `{ href: "/emails", label: "Emails" }` to
  the `TABS` array.
- `app/emails/page.tsx` — new page, modeled on
  `app/human-agent/page.tsx`: conversation list on the left, thread on
  the right, 4-second polling, agent reply box. An agent reply on an
  email conversation goes out as email through the same
  `_deliver_reply` path.
- `lib/api.ts` — add an optional `channel` parameter to
  `listConversations()` and pass it through as a query parameter. No new
  endpoint is needed; `GET /api/chat/conversations?channel=email` already
  works.

The Emails tab shows the sender address, subject-derived preview, and
status — with `waiting_agent_response` visually distinct, since that is
how an escalated thread surfaces to a human.

**Implementation note:** `frontend/AGENTS.md` warns that this Next.js
version differs from training data. Read the relevant guide in
`node_modules/next/dist/docs/` before writing frontend code.

## Testing

TDD, with `GmailClient` faked at the boundary so no test touches the
network.

- **Parsing** — multipart `text/plain` vs HTML-only; quoted-history
  stripping; truncation at 5000 characters.
- **Loop gates** — one test per rejection rule (`Auto-Submitted`,
  `List-Id`, `Precedence`, empty `Return-Path`, noreply sender,
  self-send); each asserts no send occurred.
- **Idempotency** — the same `gmail_message_id` twice produces exactly one
  reply; a simulated crash after the `processing` record produces zero
  replies on restart.
- **Rate limiting** — the 6th reply to one sender escalates instead of
  sending.
- **Allowlist / dry-run** — a non-allowlisted sender is ingested but never
  sent to; dry-run logs and never calls send.
- **Escalation** — `escalate_to_human` produces the holding reply and sets
  `waiting_agent_response`.
- **Threading** — outbound carries `threadId`, `In-Reply-To`,
  `References`, and `Auto-Submitted: auto-replied`.

Manual verification is a three-step ladder, each step a config change
rather than a code change:

1. `GMAIL_DRY_RUN=true`, allowlist set to your own address — watch the
   pipeline run without sending.
2. `GMAIL_DRY_RUN=false`, allowlist still your own address — real sends,
   bounded audience.
3. Widen `GMAIL_ALLOWED_SENDERS` once answer quality is proven.

## Out of scope

- Attachments (ignored entirely).
- Pub/Sub push delivery — polling first; `watch()` + `history.list` is the
  later upgrade and reuses the same reader.
- Per-tenant mailboxes and an encrypted OAuth token store — the production
  multi-tenant answer, deferred behind the single-mailbox config binding.
- Thread-level conversation matching (see "Conversation threading").
- Draft/approval workflow — explicitly rejected in favor of auto-send.
