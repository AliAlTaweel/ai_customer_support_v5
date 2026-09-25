# SaaS: control-plane / data-plane split and agent authentication

**Date:** 2026-09-25
**Status:** Design — awaiting review

## Intent

Turn this single-tenant-in-practice engine into something that can be sold
to strangers, without paying enterprise isolation costs at MVP scale.

Two threats are treated as equally important:

1. **Privilege pivot** — an attacker who breaches the customer-facing API
   reaches tenant management, billing, or cross-tenant data.
2. **Tenant crossover** — a bug in tenant scoping leaks Tenant A's
   conversations or knowledge base to Tenant B.

The design addresses (1) now with a control-plane / data-plane split, and
makes (2) solvable later by per-tenant siloing *without a rewrite*. It also
closes an existing hole that SaaS would make serious: the agent console
currently ships a tenant API key to the browser.

**Stage:** launch / MVP. Few tenants, manual onboarding, no billing yet.

**Success criteria:**

- A fully compromised data-plane process yields no admin credential, no
  cross-tenant read, and no route into tenant lifecycle or billing.
- Onboarding a tenant onto dedicated infrastructure later is a deployment
  change, not a code change.
- No browser ever holds a tenant API key.

**Explicitly out of scope:** billing and metering, self-serve signup,
per-tenant Gmail mailboxes. Each needs its own design; none blocks this one.

## Architecture

Two independently deployed services.

### Data plane

Today's `backend/` FastAPI app, unchanged in purpose: chat ingestion, KB
retrieval, Gemini replies, the Gmail channel. It serves untrusted,
internet-facing tenant traffic and is assumed to be the thing that gets
breached.

Constraints it must hold:

- Every query is scoped by `tenant_id` (already true).
- It holds **no** control-plane credential and has **no** network path to
  the control plane. Trust flows one way only.
- It keeps no cross-tenant state in process memory (see *Rate limiting*).
- Its database connection arrives as configuration (`MONGODB_URL`,
  `MONGODB_DATABASE_NAME`), never assumed or hardcoded (already true).

### Control plane

A new, separate service owning tenant lifecycle: create / suspend / delete
a tenant, mint and revoke API keys, and later, usage and billing views. It
is what `scripts/seed_tenant.py` becomes — the same operations, over an
authenticated HTTP API instead of a shell script run by hand.

It is deployed on its own host, and should not be publicly reachable:
VPN or IP allowlist only, since the sole legitimate caller is the operator.

It may reach the tenant database (it must, to write tenant and key records).
The data plane may not reach it. That asymmetry is the entire security
benefit — a breached data plane has nothing to pivot into.

### Why not the alternatives

- **Per-tenant silo now:** correct for the tenant-crossover threat, but
  multiplies provisioning, monitoring, patching, and cost by tenant count
  before there is revenue to justify it. Deferred, not rejected.
- **Status quo (one server):** leaves tenant lifecycle reachable from the
  same process serving untrusted traffic.

## The silo-later property

The rule that keeps option (2) open: **one data-plane deployment = one
database connection, supplied as config.**

| Mode | Deployment | Database | Tenants served |
|---|---|---|---|
| Shared (MVP) | one instance | one Atlas database | many `tenant_id`s |
| Siloed (later) | same image, deployed again | that tenant's own database | exactly one |

Siloing a demanding customer later is then a deploy with a different
`MONGODB_URL` — no code change. This holds only while the data plane stays
self-sufficient: it must be able to authenticate its own agents and serve
its own tenants without calling the control plane at request time.

That is why agent identities live in the tenant database (below), not in
the control plane.

## Agent authentication

Two kinds of caller, split cleanly. This is the fix for the browser-exposed
key.

### API keys — machine-to-machine only

Unchanged from today: hashed, validated by `services/api_key_auth_service.py`,
resolved to a `tenant_id` by `middleware/api_key_auth.py`. Used by server
integrations and the ecommerce relay. **Never sent to a browser.**

### Agent sessions — humans

New. The data plane gains login endpoints returning a session token scoped
to one agent within one tenant. The Next.js server holds it in an httpOnly
cookie and attaches it server-side; the browser receives no long-lived
credential and no API key.

Agent records live in the **tenant** database, carrying `tenant_id`, email,
a hashed password, and status. Login email resolves the agent record, which
supplies the tenant — no subdomain routing needed for MVP.

This replaces `NEXT_PUBLIC_API_KEY` in `frontend/.env.local`, which is
shipped to the browser by Next.js and is readable by anyone who opens
devtools. Acceptable for a console you run yourself; not acceptable when
each tenant's console exposes that tenant's full-access key.

There is no agent identity model today — `agent_name` is free text on a
reply (`services/chat_service.py:376`). Agent accounts are genuinely new
work, not a refactor of something existing.

## Components

Following `backend/CLAUDE.md`: persistence in `repositories/`, orchestration
in `services/`, thin HTTP glue in `routers/`.

| Component | Responsibility |
|---|---|
| `repositories/agent_repository.py` | Agent record persistence. No business logic. |
| `repositories/session_repository.py` | Session token storage, lookup, expiry. |
| `services/agent_auth_service.py` | Credential verification, session issue/revoke. The one shared call site for agent auth. |
| `middleware/` (extended) | Resolve a session cookie to `tenant_id` + agent, alongside today's API-key path. |
| `routers/auth.py` | Login / logout / current-agent endpoints. |
| Control-plane service (new deploy) | Tenant lifecycle and key issuance. Absorbs `scripts/seed_tenant.py`. |

Both credential paths must converge on one request-state shape
(`tenant_id`, plus agent identity when present) so downstream services stay
unaware of *how* the caller authenticated.

## Rate limiting

`middleware/rate_limit.py` keeps counters in a module-level dict
(`rate_limit_store = {}`). This breaks twice under this design: it is wrong
across multiple instances, and it holds cross-tenant state in one process,
violating the silo constraint. It moves to shared storage (Mongo or Redis)
as part of this work.

## Error handling

- Invalid, expired, or forged session → 401, no distinction leaked between
  "no such agent" and "wrong password" on login.
- Suspended tenant or agent → 403, checked on every request, not only at
  login, so revocation takes effect immediately.
- Control plane unreachable → the data plane is unaffected by design; it
  never calls the control plane at request time.

## Testing

Per this repo's convention (hand-written in-memory fakes over mocks, see
`backend/CLAUDE.md` and `backend/tests/`):

- **Tenant scoping** — a Tenant A session cannot read Tenant B's
  conversations, KB documents, or Q&A pairs. One test per data surface.
- **Session auth** — expired, forged, and revoked sessions are rejected;
  suspension takes effect mid-session, not just at login.
- **Credential separation** — an API key cannot be used where a session is
  required, and vice versa; both land on the same request-state shape.
- **No pivot path** — the data plane exposes no route reaching
  control-plane functions.
- **Rate limiting** — counters survive across instances and are
  tenant-scoped.

## Open questions

Deliberately deferred, each needing its own design before implementation:

- Billing and usage metering, which self-serve signup depends on.
- Per-tenant Gmail mailboxes — the channel is currently bound to one
  mailbox via a single `GMAIL_TENANT_ID` in `.env`.
- Agent roles and permissions within a tenant; MVP assumes all agents of a
  tenant are equivalent.
