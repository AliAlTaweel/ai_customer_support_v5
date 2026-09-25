# SaaS readiness: agent auth, tenant isolation, and what to defer

**Date:** 2026-09-25
**Status:** Design — awaiting review
**Supersedes:** `2026-09-25-saas-control-data-plane-design.md` (commit
`3746795`), which proposed a control-plane HTTP service, hand-rolled agent
auth, and a four-service deployment. Renamed because the design no longer
centers on that split. See *What changed and why* below.

## Intent

Make this engine safe to sell to strangers at MVP scale — a handful of
tenants, onboarded by hand, no billing yet — without building
infrastructure that only pays off at a scale you have not reached.

Two threats matter equally:

1. **Privilege pivot** — an attacker who breaches the customer-facing API
   reaches tenant management or cross-tenant data.
2. **Tenant crossover** — a bug leaks Tenant A's conversations or knowledge
   base to Tenant B.

**Success criteria:**

- No browser ever holds a tenant API key.
- A missing tenant filter in a query is impossible to express in code, not
  merely caught by review.
- Moving a demanding customer onto isolated infrastructure later is a
  deployment change, not a rewrite.

## What changed and why

The first draft split tenant lifecycle onto a new control-plane HTTP
service. That was wrong for this stage, for three reasons:

- **It added attack surface in the name of removing it.** Today,
  `scripts/seed_tenant.py` requires shell access to the machine — no
  network surface at all. Replacing it with an authenticated HTTP API that
  can create and delete tenants is strictly more exposed than a CLI, not
  less. The CLI *is* the isolation, and it is free.
- **It proposed hand-rolled authentication.** Rebuilding password hashing,
  session storage, and revocation is a well-known source of
  vulnerabilities, and unnecessary — this platform used Clerk before the
  extraction.
- **It skipped cheaper answers to tenant crossover.** It jumped from
  "shared everything" to "separate deployments" without considering
  enforcement at the code layer, which addresses the realistic failure mode
  at near-zero cost.

What survived: the silo-later discipline, the browser-key fix, and the
rate-limit fix.

## Priority 1: the browser-exposed tenant key

This is the only issue here that is exploitable **today**.

`frontend/.env.local` holds `NEXT_PUBLIC_API_KEY`. The `NEXT_PUBLIC_`
prefix means Next.js ships that value to the browser, where anyone who
opens devtools can read it. A tenant API key is full access to that
tenant's data. Tolerable for a console you run yourself; disqualifying for
SaaS.

**Fix:** real agent login, using a hosted auth provider (Clerk, Auth0,
WorkOS — Clerk has prior art in this codebase's history). The provider owns
credentials, sessions, and revocation. The Next.js server exchanges the
session for backend access and attaches it server-side; the browser
receives no long-lived credential and no API key.

Two caller types, split cleanly:

| Caller | Credential | Reaches browser? |
|---|---|---|
| Humans (agents in the console) | Provider-issued session | Session cookie only, httpOnly |
| Machines (integrations, ecommerce relay) | API key, as today | Never |

Both paths converge on one request-state shape (`tenant_id`, plus agent
identity when present) so services stay unaware of how the caller
authenticated. Agent → tenant mapping lives in the tenant database, which
keeps the data plane self-sufficient (see *Preserved: silo-later*).

There is no agent identity model today — `agent_name` is free text on a
reply (`services/chat_service.py:376`), so this is new work either way.
Using a provider makes it substantially less new work.

## Priority 2: make unscoped queries unwritable

The realistic cause of tenant crossover at this scale is not a sophisticated
attack. It is a forgotten `tenant_id` filter in one query — silent, easy,
and invisible in review.

**Fix:** enforce it structurally in `repositories/`, where all persistence
already lives per `backend/CLAUDE.md`. Repositories take the tenant as a
required constructor argument and apply it to every query internally; a
query that omits it cannot be expressed through the repository API. This
costs almost nothing, requires no new infrastructure, and eliminates the
entire bug class rather than testing for instances of it.

**Not per-tenant databases, yet.** A database per tenant also eliminates
this bug class, but carries ongoing cost: a vector index
(`kb_vector_index`) provisioned per tenant, schema migrations run across N
databases, and connection management for all of them. It becomes the right
answer when a customer requires *demonstrable* separation, and the
silo-later discipline below keeps it a config change away. It is not worth
the operational weight for tenants who have not asked for it.

Honest limit of both approaches: they protect against **bugs**, not against
a fully compromised process. A process holding credentials for tenant data
can read that data regardless of how it is partitioned. Defending against
that requires siloed deployments — deferred, below, with the trigger named.

## Priority 3: rate limiting holds cross-tenant state in memory

`middleware/rate_limit.py` keeps counters in a module-level dict
(`rate_limit_store = {}`). This is wrong the moment you run more than one
instance — which you will need to — and it holds cross-tenant state in one
process. It moves to shared storage (Mongo or Redis).

This is a correctness bug independent of everything else here.

## Preserved: the silo-later discipline

The rule that keeps expensive isolation available without paying for it
now: **one data-plane deployment = one database connection, supplied as
configuration.** This is already true (`MONGODB_URL`,
`MONGODB_DATABASE_NAME`, passed into `MongoConnection.connect()`).

| Mode | Deployment | Database | Tenants served |
|---|---|---|---|
| Shared (now) | one instance | one database | many `tenant_id`s |
| Siloed (when required) | same image, deployed again | that tenant's own | exactly one |

This holds only while the data plane stays self-sufficient: it must
authenticate its own callers and serve its own tenants without calling a
central service at request time. That is the reason agent → tenant mapping
lives in the tenant database.

Cost today: zero. It is a constraint on new code, not new code.

## Deferred, with triggers

Each of these is a reasonable thing to build later. None blocks MVP, and
each has a condition that should prompt revisiting it.

| Deferred | Build it when |
|---|---|
| Control-plane service + admin UI | Onboarding by hand is the bottleneck — roughly, when someone other than you needs to create tenants. Until then `seed_tenant.py` is both sufficient and more secure. |
| Per-tenant databases | A customer requires demonstrable data separation, or a compliance review asks for it. |
| Siloed per-tenant deployments | A customer's threat model includes your process being compromised, and they will pay for dedicated infrastructure. |
| Billing and usage metering | Before self-serve signup, which depends on it. |
| Per-tenant Gmail mailboxes | A second tenant wants the email channel. It is currently bound to one mailbox via `GMAIL_TENANT_ID`. |

**On separate admin and tenant frontends:** with no control plane, there is
no admin UI to build, so the question is moot for now. When it arrives, it
should be a separately deployed app behind the same network boundary as the
control plane — not a route inside the public tenant console, which would
put a public door in front of a service that is supposed to be
network-restricted.

## Components

Following `backend/CLAUDE.md`: persistence in `repositories/`,
orchestration in `services/`, thin HTTP glue in `routers/`.

| Component | Responsibility | Status |
|---|---|---|
| `repositories/*` | Take tenant as a required argument; apply scoping internally | Modified |
| `services/agent_auth_service.py` | Verify provider sessions, resolve agent → tenant | New |
| `middleware/` | Resolve a session *or* an API key to one request-state shape | Extended |
| `middleware/rate_limit.py` | Counters in shared storage | Modified |
| `frontend/` | Server-side session handling; no `NEXT_PUBLIC_API_KEY` | Modified |
| `scripts/seed_tenant.py` | Unchanged — still the provisioning path | Unchanged |

## Error handling

- Invalid, expired, or revoked session → 401. Login failures leak no
  distinction between "no such agent" and "wrong password" (the provider
  handles this).
- Suspended tenant or agent → 403, re-checked on every request rather than
  only at login, so revocation takes effect immediately.
- Auth provider unreachable → existing sessions continue to validate if the
  provider's model allows it; new logins fail closed. Decide this
  explicitly when the provider is chosen.

## Testing

Per this repo's convention — hand-written in-memory fakes over mocks, see
`backend/CLAUDE.md` and `backend/tests/`:

- **Tenant scoping** — a Tenant A caller cannot reach Tenant B's
  conversations, KB documents, or Q&A pairs; one test per data surface.
- **Structural enforcement** — the repository API cannot express an
  unscoped query. This is the test that matters most; if it is awkward to
  write, the enforcement is not structural enough.
- **Credential separation** — an API key cannot be used where a session is
  required and vice versa; both produce the same request-state shape.
- **Session lifecycle** — expired, forged, and revoked sessions are
  rejected; suspension takes effect mid-session.
- **Rate limiting** — counters are shared across instances and
  tenant-scoped.

## Open questions

- **Which auth provider.** Clerk has prior art here; the choice affects the
  offline/unreachable behavior above.
- **Where the agent → tenant mapping is written** during onboarding —
  `seed_tenant.py` will need to create the first agent, which means talking
  to the provider.
- **Atlas limits** on databases and collections per cluster, before
  per-tenant databases become viable at scale.
