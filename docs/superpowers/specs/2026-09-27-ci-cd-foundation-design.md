# CI foundation: automated checks and a verified container image

**Date:** 2026-09-27
**Status:** Design — awaiting review
**Scope:** CI only. Deployment to GCP Cloud Run is explicitly a follow-up
round; this design's job is to make that round small.

## Intent

Every check that protects this codebase today runs only when someone
remembers to run it by hand. Make the checks automatic on every push and
pull request, and prove the backend packages into a container that actually
boots — so that adding Cloud Run deployment later is a push-and-deploy step
on an already-verified image, not a first encounter with containerization.

**Success criteria:**

- A pull request that breaks the backend tests or violates the pinned lint
  rules cannot be merged without the failure being visible.
- The backend image is known to build *and* serve traffic, not merely to
  compile.
- The CI test job requires no secrets. Nothing in this design needs a GCP
  project, cloud credentials, or a registry.
- Adding deployment later touches the workflow files and GCP setup only —
  no application code changes.

**Non-goals:** deploying anything; pushing images to a registry; GCP or
Workload Identity Federation setup; GitHub branch-protection rules (a
repository settings change, made by hand); restructuring application code
beyond what a green gate requires.

## Measured baseline

Everything below was run against the working tree on 2026-09-27. The
numbers drive the design, so they are recorded rather than assumed.

| Check | Result |
|---|---|
| `pytest -q` (backend) | 139 passed, ~1.1s, no external services needed |
| `ruff check .` (backend, unpinned) | 235 findings; 179 auto-fixable |
| `ruff check .` (backend, default rules only) | 13 findings |
| `ruff check .` (backend, rule set selected below) | 379 findings — of which 175 are `E501` |
| same, ignoring `E501`, after `--fix` | **21 findings remain**; `pytest` still 139 passed |
| `black --check .` (backend) | 51 of 61 files would be reformatted |
| `mypy .` (backend) | Does not run: 3 errors, module-path resolution on `tests/` |
| `npx tsc --noEmit` (frontend) | exit 0 |
| `next build` (frontend, placeholder env) | succeeds, 5 static routes |
| `npm run lint` (frontend) | 2 errors |

Two facts explain most of what follows:

**There is no `pyproject.toml`, `ruff.toml`, or `mypy.ini` anywhere in the
repo.** That is why `ruff` reports 235 findings one way and 13 another — the
rule set is whatever the installed tool version defaults to, which is not a
stable contract. CI cannot gate on that; pinning the config is a
prerequisite, not a nicety.

**The backend test suite needs no secrets and no database.** `config.py`
validates env vars at import time and raises on missing `MONGODB_URL` or
`GEMINI_API_KEY` (deliberate, per `backend/CLAUDE.md`: "config is validated
at import time, not first use"), and `tests/conftest.py` already supplies
both via `os.environ.setdefault`. Tests use hand-written fakes, not live
services. This design preserves that property rather than adding service
containers to the test job.

Local toolchain versions, which CI matches to avoid version skew:
Python **3.14.7**, Node **v26.9.0**.

## Files added

```
.github/workflows/backend-ci.yml     paths: backend/**, .github/workflows/backend-ci.yml
.github/workflows/frontend-ci.yml    paths: frontend/**, .github/workflows/frontend-ci.yml
backend/pyproject.toml               ruff + mypy + pytest config (replaces pytest.ini)
backend/requirements-dev.txt         -r requirements.txt plus the four dev tools
backend/Dockerfile
backend/.dockerignore
```

Both workflows trigger on pull requests targeting `main` and on pushes to
`main`, each path-filtered so a backend-only change does not run frontend
jobs.

## Landing order

A gate added on top of a few hundred existing findings is a gate that is red the
moment it lands, and a red gate teaches everyone to ignore it. The work
therefore lands as an ordered sequence, each step verified before the next:

1. **Pin the tool config.** Add `backend/pyproject.toml`; delete
   `backend/pytest.ini` (its three settings move into
   `[tool.pytest.ini_options]` unchanged). Split `requirements.txt` into
   runtime and `requirements-dev.txt`.
2. **Clear the backend lint debt.** Apply `ruff check --fix` (174
   mechanical fixes), then resolve the 21 that remain. Both numbers were
   measured by doing exactly this on a throwaway copy of `backend/`, after
   which `pytest` still reported 139 passed. `--unsafe-fixes` is not used,
   though ruff offers 5 more fixes behind it.
3. **Clear the frontend lint debt.** The two `react-hooks/set-state-in-effect`
   errors (below).
4. **Add the Dockerfile and `.dockerignore`.** Verified locally: image
   builds, and the container boots and serves `/health` against a local
   Mongo.
5. **Add both workflows.** They land green because steps 1–4 already made
   them green.

Steps 2 and 3 are separate commits from step 5 so that the mechanical
reformatting diff never obscures the review of the CI logic.

### Ruff rule selection

Select `E, F, I, UP, B, SIM, RUF`, with `E501` ignored. Deliberately **not**
selected:

- **`E501` (line-too-long), 175 occurrences, none auto-fixable.** Line
  length is a formatter's job, and gating on it here would mean reflowing
  175 lines by hand in a change that is supposed to be about CI. It stays
  ignored for as long as `black` is advisory; adopting `black` as a gate is
  what should settle line length, in one pass, mechanically.

- **`BLE001` (blind-except), 24 occurrences.** `backend/CLAUDE.md` already
  governs this with a more precise rule — "never swallow a failure that
  changes what the caller should tell the user" — which permits a logged
  `except Exception` around a tolerated failure (for example the
  `create_search_index` call in `database.py`, where an already-existing
  index must not break startup) while forbidding one around an outbound
  send. A blanket ban would contradict the standards doc, and a linter that
  contradicts your own documented standards trains you to ignore the
  linter.
- **`S` (bandit) and `DTZ`.** One `DTZ005` finding and a handful of `S110`
  findings, none of which this round has the context to adjudicate. Can be
  adopted later as a deliberate decision rather than as a side effect.

The 21 findings surviving autofix, which step 2 resolves by hand:

| Rule | Count | Nature of the fix |
|---|---|---|
| `B904` raise-without-from-inside-except | 9 | Add `from e` — mechanical, but changes tracebacks, so worth reading each |
| `RUF013` implicit-optional | 4 | `x: str = None` → `x: str | None = None` |
| `SIM117` nested `with` | 3 | Combine context managers |
| `SIM102` collapsible `if` | 1 | Merge conditions |
| `B008` function-call-in-default-argument | 1 | Likely a FastAPI `Depends()`, which is the framework's idiom — expect a `# noqa` with a reason, not a "fix" |
| `RUF012` mutable-class-default | 1 | Needs `ClassVar` annotation |
| `F401` unused-import, `F841` unused-variable | 2 | Delete, after confirming neither is a re-export |

Each gets a real fix where correct, or a `# noqa: <rule>` with a reason
comment where the rule is wrong for the call site. Weakening the
pinned config to make a specific call site pass is not an option — the
suppression stays visible at the call site.

### The two frontend lint errors

`app/human-agent/page.tsx:39` and `app/knowledge-base/page.tsx:32` both
call an async loader directly in a `useEffect` body, which
`react-hooks/set-state-in-effect` rejects. Attempt the idiomatic fix. If a
correct fix turns out to require restructuring how these pages fetch data,
that is outside this round's scope: downgrade the rule to `warn` in
`eslint.config.mjs` with a comment naming it as deferred, and say so. Do
not silently disable the rule, and do not let a data-fetching refactor ride
along inside a CI change.

## `backend-ci.yml`

One job on `ubuntu-latest`, with `defaults.run.working-directory: backend`
so no step repeats the `cd`.

| Step | Command | Gates? |
|---|---|---|
| Setup | `actions/setup-python@v5`, `python-version: "3.14"`, `cache: pip` | — |
| Install | `pip install -r requirements-dev.txt` | — |
| Lint | `ruff check .` | **yes** |
| Tests | `pytest -q` | **yes** |
| Format | `black --check .` | advisory (`continue-on-error`) |
| Types | `mypy .` | advisory (`continue-on-error`) |
| Container | build image, boot it, poll `/health` | **yes** |

`black` and `mypy` are advisory because the repo has never been
black-formatted (51 files) and `mypy` does not currently run at all.
Reporting their findings without blocking makes the size of each adoption
visible; promoting either to a gate is a later, separate decision with its
own cleanup commit.

### Requirements split

`requirements.txt` currently carries `pytest`, `black`, `ruff`, and `mypy`
under a comment marking them optional, which would ship the test and lint
toolchain inside the production image. After the split:

- `requirements.txt` — runtime only. What the Dockerfile installs.
- `requirements-dev.txt` — `-r requirements.txt` plus the four dev tools.
  What CI installs.

## `frontend-ci.yml`

One job, `working-directory: frontend`, `actions/setup-node@v4` with
`node-version: 26` (matching local v26.9.0) and `cache: npm`.

`npm ci` → `npx tsc --noEmit` → `npm run lint` → `npm run build`, all
gating. All four are known to pass once the two lint errors are cleared.

`lib/api.ts` reads `process.env.NEXT_PUBLIC_BACKEND_URL!` and
`NEXT_PUBLIC_API_KEY!`, so the job sets throwaway job-level values
(`http://localhost:8000` and `ci-dummy`). These are build-time placeholders
for a type-and-build check, not secrets. The local `next build` succeeded
with exactly these values.

Noted for the deployment round, not fixed here: `NEXT_PUBLIC_*` means the
tenant API key is compiled into the browser bundle. The SaaS readiness
design (`2026-09-25-saas-readiness-design.md`) already states that no
browser should ever hold a tenant API key, so this is a known open conflict
with a home of its own.

## Dockerfile

Two-stage build on `python:3.14-slim` (tag existence verified against
Docker Hub). Builder stage installs `requirements.txt` into a virtualenv;
runtime stage copies that venv plus the application source and runs as a
non-root `app` user.

`.dockerignore` must exclude `venv/`, `logs/`, `tests/`, `__pycache__/`,
`.env`, and `credentials.json`. The last two are already gitignored and
untracked, but `.dockerignore` is a separate list and a build context does
not consult `.gitignore` — omitting them risks baking real credentials into
an image layer.

The container `CMD` runs uvicorn bound to `0.0.0.0` on `${PORT:-8000}`.
Reading `PORT` with a fallback costs nothing now and is what Cloud Run
injects later, so deployment needs no code change for the port.

### One image, two entrypoints

The default `CMD` runs the API. The Gmail poller is the *same image* run
with a different command (`python -m scripts.poll_gmail`).

`scripts/run_dev.sh` documents that these stay separate OS processes on
purpose — "a crash in the poll loop must not take the API down." One image
with two commands preserves that isolation while leaving a single artifact
to build, version, and later deploy, and it matches the "same image,
deployed again" shape already described in the SaaS readiness design. On
Cloud Run this becomes one request-driven service plus one always-on
worker; that mapping belongs to the deployment round.

### Logging inside a container

`utils/logging_setup.py` computes `LOGS_DIR` and calls
`LOGS_DIR.mkdir(exist_ok=True)` at **import time**, and every logger
attaches a `RotatingFileHandler` beneath it. Two consequences:

1. The image must create `/app/logs` and `chown` it to the non-root user,
   or the application crashes on import. The Dockerfile does this
   explicitly.
2. Rotating log files inside a container write to an ephemeral filesystem
   that nothing collects, and Cloud Run collects **stdout**. This design
   does not change the logging setup — that is application work, not CI
   work — but records it as a known gap, because it is the difference
   between having and not having production logs after deployment.

## Container smoke test

`docker build` exiting 0 proves only that dependencies resolved. The app's
`lifespan` calls `Database.connect()` and re-raises on failure, so a
booting container is a strictly stronger claim, and it is the claim that
matters before deploying.

The step runs a `mongo:7` service container, starts the built image against
it, and polls `/health` until it returns 200, failing after roughly 30
seconds. This works against a plain Mongo — not Atlas — because the only
Atlas-specific call at startup, `create_search_index` for
`kb_vector_index`, is wrapped in a `try/except` that logs and continues.
Verified by reading `database.py`.

What this does *not* cover: Atlas vector search itself, which is what
`$vectorSearch` in `ai_reply_service.py` needs at runtime. The smoke test
proves the process serves HTTP; it does not prove knowledge-base retrieval
works against a real Atlas cluster. That gap is inherent to testing without
Atlas and is accepted here rather than papered over.

## Testing this design

The workflows themselves are verified by the pull request that introduces
them: both must run and pass on that PR. Before pushing, each piece is
verified locally with the command that CI will run —
`ruff check .`, `pytest -q`, `npm run lint`, `npm run build`, and a local
`docker build` plus boot against a local Mongo. A workflow file whose steps
have never been run locally is a guess.

Deliberately not attempted: a local GitHub Actions emulator. The steps are
ordinary shell commands, and running them directly is a better check than
emulating the runner.

## Deferred, with triggers named

| Deferred | Revisit when |
|---|---|
| Cloud Run deployment, Artifact Registry, Workload Identity Federation | The next round. This design's output is its prerequisite. |
| `black` as a gate | You decide a repo-wide reformat is worth one noisy commit. |
| `mypy` as a gate | Someone makes `mypy` run clean; the config here gets it running at all. |
| Logging to stdout instead of rotating files | Before deployment, or production has no logs. |
| `NEXT_PUBLIC_API_KEY` in the browser bundle | Before the frontend is deployed anywhere public. |
| Branch protection requiring these checks | After the first green run on `main`. A GitHub settings change, not a file. |
| Bandit (`S`) and `DTZ` lint rules | As a deliberate security-lint decision, with time to adjudicate each finding. |
