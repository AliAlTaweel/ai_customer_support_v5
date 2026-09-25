# Backend coding standards

## Single Responsibility Principle

Each class/module should have one reason to change. Concretely:

- **Persistence** (Mongo reads/writes) lives in `repositories/`, never inline
  in a service or router. See `repositories/conversation_repository.py`.
- **Outbound dispatch** to an external channel (email, webhook) lives in its
  own service (e.g. `services/reply_delivery_service.py`), separate from the
  business logic that decides *whether* to send.
- **Orchestration** (services/*_service.py) decides what should happen and in
  what order, and calls repositories/dispatchers to do it. It should not
  contain raw `db["..."]` calls or raw HTTP client calls.
- **Routers** are thin HTTP glue: parse the request, call a service, shape
  the HTTP response/status code. No business logic, no direct Mongo access.
  See `routers/chat.py` for the target shape.
- Cross-cutting logic used from more than one place (e.g. API key
  authentication) belongs in exactly one service that all callers share —
  never copy-pasted into a second call site "for convenience."

When a file's own docstring lists more than one unrelated thing it handles
("X, Y, and Z"), that's the signal to split it — this is literally how
`chat_service.py` (persistence + delivery + orchestration) and
`kb_service.py` (documents + Q&A + tenant settings) were identified and
split in this codebase's history. Before adding to an existing file, check
whether the new code is actually a new responsibility or belongs to one
already there.

## Function length

There is no hard line-count limit, and 20 lines specifically is not
enforced — a from-scratch audit of this codebase found 51 existing
functions over 20 lines, including ones written deliberately as the *clean*
result of an SRP pass (`receive_message` at ~120 lines is a linear
orchestration sequence: create conversation, save message, update counters,
maybe reply, handle failure — splitting that into sub-20-line pieces would
mean either one-call helper functions that exist only to dodge the count,
or scattering one linear flow across several methods a reader has to jump
between).

Instead:

- Treat a function pushing past ~40 lines as a prompt to check: does this
  still do *one* thing, just with several sequential steps (fine), or has a
  second responsibility crept in (split it)?
- A long function that's a flat sequence of steps at the same level of
  abstraction, with no branching complexity, is usually fine.
- A long function mixing levels of abstraction (e.g. raw Mongo queries
  interleaved with business decisions interleaved with logging formatting)
  is the real smell — the fix is extracting the mismatched concern to its
  own collaborator, not just breaking lines arbitrarily.
- Prefer descriptive names and early returns over deep nesting; that does
  more for readability than a line count ever will.

## Other practices to follow

Each item is tagged:
- 🌐 **Universal** — a general software engineering principle, true well
  beyond this codebase. Non-negotiable regardless of what you're touching.
- 🏠 **App-specific** — this codebase's particular instantiation of a
  universal idea, or a concern unique to its domain (multi-tenant SaaS with
  an LLM and external sends). The specifics (which entry points, which
  seam) are local; don't assume they transfer to a different project as-is.

- 🌐 **Idempotency before side effects.** The email pipeline claims a
  message (unique index on `gmail_message_id`) *before* running the AI
  reply, so a crash mid-reply can't produce a duplicate send. Any new
  external side effect (send an email, charge a card, call a webhook) needs
  the same shape: record intent first, then act.
- 🌐 **Never swallow a failure that changes what the caller should tell the
  user.** `EmailDeliveryError` propagates all the way to the router so an
  agent sees "reply failed" instead of a false success. Don't
  `except Exception: pass` around an outbound call — check whether the
  caller needs to know it failed.
- 🌐 **Comments explain *why*, never *what*.** Every non-obvious comment in
  this codebase documents a constraint (event-loop blocking, a unique-index
  consequence, a prompt-injection boundary) — not what the next line does.
  This is what keeps the code safely refactorable later.
- 🌐 **Secrets are hashed, never stored plaintext, for new code paths.** API
  keys use bcrypt (`APIKeyService`); the plaintext `tenant.api_key` fallback
  is legacy, not a pattern to extend.
- 🌐 **Config is validated at import time, not first use.** `config.py`
  fails fast on missing env vars rather than surfacing a cryptic error deep
  in a request.
- 🏠 **Multi-tenancy: every query scoped by `tenant_id`.** Every repository
  method and every Mongo query filters by `tenant_id`. A query missing it is
  a cross-tenant data leak — the worst class of bug this app can have. (The
  universal principle underneath: enforce your isolation/authorization
  boundary at the data-access layer, not only at the API edge. A
  single-tenant app wouldn't have this rule at all.)
- 🏠 **Feature flags/kill switches get checked at every entry point that can
  trigger the effect, not just the "main" one.** `GMAIL_ENABLED` is checked
  both in the poll worker and in `ReplyDeliveryService`, because agent/AI
  replies to *existing* email conversations reach delivery through the API
  too, with no poller involved. (Universal underneath: a guard is only as
  good as its weakest call path — but *which* entry points exist is
  app-specific.)
- 🏠 **The prompt-injection boundary is a single seam.** Untrusted (email)
  content is wrapped for the model in exactly one place
  (`ChatService._maybe_generate_ai_reply`), never at storage or display
  time. Any new inbound channel to the AI must route through that same
  seam, not reimplement wrapping. Specific to systems that mix untrusted
  input with an LLM — not a general backend concern.
- 🏠 **Tests use hand-written fakes, not mocks.** `FakeGmailClient`,
  `_FakeDB`, `InMemoryProcessedEmailStore` — real (if minimal) behavior, not
  `MagicMock().assert_called_with(...)`. Fakes catch behavior bugs; mocks
  only catch "did I call this." This is a style choice with real tradeoffs
  (some teams reasonably prefer mocks for isolation) — it fits this
  codebase's async/Mongo shape, not a universal law.
