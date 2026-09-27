# CI Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every push and pull request automatically runs the backend and frontend checks, and the backend is proven to package into a container that boots and serves traffic.

**Architecture:** Two path-filtered GitHub Actions workflows (`backend-ci.yml`, `frontend-ci.yml`). The backend gate runs `ruff` and `pytest`, then builds the Dockerfile and boots the image against a `mongo:7` service container to prove it serves `/health`. Because the repo currently has no pinned lint config and several hundred outstanding findings, the gate lands *last* — the toolchain is pinned and the debt cleared first, so the gate is green on arrival. No deployment, no registry, no cloud credentials.

**Tech Stack:** GitHub Actions, Python 3.12, ruff, pytest, Docker (multi-stage, `python:3.12-slim`), Node 26, Next.js 16.

**Spec:** `docs/superpowers/specs/2026-09-27-ci-cd-foundation-design.md`

## Global Constraints

- **Python is 3.12 everywhere** — local `backend/venv`, CI, and the container image. Never 3.14.
- `requires-python = ">=3.12"` and ruff `target-version = "py312"`.
- Ruff rule set is exactly `["E", "F", "I", "UP", "B", "SIM", "RUF"]` with `ignore = ["E501"]`. Do not add `S`, `BLE`, or `DTZ`.
- `ruff check .` and `pytest -q` **gate** (fail the build). `black --check .` and `mypy .` are **advisory** (`continue-on-error: true`). Never make black or mypy gate in this plan.
- `pytest -q` must report **139 passed** at the end of every task that touches backend Python. A drop is a regression; do not proceed.
- Never weaken the pinned ruff config to make a call site pass. Use `# noqa: <RULE>` with a reason comment at the call site instead.
- The container runs as a **non-root** user and reads `${PORT:-8000}`.
- No task adds a GCP dependency, a registry push, or any repository secret.
- Node version is 26, matching local v26.9.0.
- Commit messages end with the project's trailer: `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

## Review Focus

Failure modes the spec implies that no ordinary test would catch. Each has a test assigned to the task that owns the code.

1. **A secret baked into an image layer.** `.gitignore` and `.dockerignore` are separate lists, and a Docker build context does not consult `.gitignore` — `backend/credentials.json` and `backend/.env` exist locally and untracked, so a missing `.dockerignore` entry ships them. *Test: Task 4 Step 6 asserts they are absent from the built image's filesystem.*
2. **Import-time crash as non-root.** `utils/logging_setup.py` calls `LOGS_DIR.mkdir(exist_ok=True)` and attaches `RotatingFileHandler`s at module import. If `/app/logs` is not writable by the container user, every entrypoint dies before serving. *Test: Task 4 Step 5 boots the container as non-root and requires HTTP 200.*
3. **`PORT` ignored.** Cloud Run injects `PORT`; the app only reads `BACKEND_PORT`. If the `CMD` hardcodes 8000, the later deploy round silently fails health checks. *Test: Task 4 Step 7 boots with `PORT=9090` and requires `/health` on 9090.*
4. **A runtime dependency stranded in the dev requirements.** Splitting `requirements.txt` can move something the app imports at startup into `requirements-dev.txt`; tests would still pass in CI (they install the dev file) while the image breaks. *Test: Task 4 Step 5's boot succeeds using only `requirements.txt`.*
5. **A workflow that never runs.** A wrong `paths` filter or branch name produces a permanently green PR because the job is skipped, not passing. *Test: Task 5 Step 6 requires observing both workflows actually execute on the PR, and a skipped job counts as failure.*

---

### Task 1: Standardize on Python 3.12 and pin the tool config

Nothing else in this plan can be verified until the toolchain is fixed, so this comes first. Deliverable: a 3.12 venv, a pinned `pyproject.toml`, split requirements, and a recorded version so the skew cannot silently return.

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/requirements-dev.txt`
- Modify: `backend/requirements.txt` (remove the four dev tools)
- Modify: `backend/CLAUDE.md` (append a "Toolchain" section)
- Delete: `backend/pytest.ini`

**Interfaces:**
- Consumes: nothing.
- Produces: a `backend/venv` on Python 3.12; `ruff check .` and `pytest -q` both runnable from `backend/` with config read from `pyproject.toml`; `requirements-dev.txt` as the file CI installs; `requirements.txt` as the file the Dockerfile installs.

- [ ] **Step 1: Confirm python3.12 is available**

Run from `backend/`:
```bash
python3.12 -V
```
Expected: `Python 3.12.13` (any 3.12.x is fine). If this fails, stop and report — do not substitute another version.

- [ ] **Step 2: Rebuild the venv on 3.12**

The existing venv is 3.14.7 and must be replaced, not reused:
```bash
cd backend
rm -rf venv
python3.12 -m venv venv
./venv/bin/pip install --upgrade pip
```

- [ ] **Step 3: Split the requirements files**

Remove these four lines and the two comment headers above them from `backend/requirements.txt` (currently at the end of the file):
```
# Testing (optional)
pytest>=7.4.0
pytest-asyncio>=0.21.0

# Code Quality (optional)
black>=23.0.0
ruff>=0.1.0
mypy>=1.7.0
```

Create `backend/requirements-dev.txt`:
```
# Development and CI toolchain. Runtime deps live in requirements.txt --
# the container image installs only that file, so the production image
# never ships the test or lint tooling.
-r requirements.txt

# Testing
pytest>=7.4.0
pytest-asyncio>=0.21.0

# Code Quality
black>=23.0.0
ruff>=0.1.0
mypy>=1.7.0
```

- [ ] **Step 4: Install the dev requirements into the new venv**

```bash
cd backend
./venv/bin/pip install -r requirements-dev.txt
```
Expected: completes with no error. (Verified during design on a clean 3.12.13 venv.)

- [ ] **Step 5: Create the pinned config**

Create `backend/pyproject.toml`:
```toml
[project]
name = "ai-customer-support-backend"
version = "0.1.0"
# Pinned so ruff's UP autofixes never rewrite code into syntax newer than
# what CI and the container image actually run.
requires-python = ">=3.12"

[tool.ruff]
target-version = "py312"
exclude = ["venv", ".venv", "__pycache__", "logs"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "RUF"]
# E501 (line-too-long) fires 175 times and is not auto-fixable; line length
# is a formatter's job. Revisit if black is ever promoted to a gate.
# S/BLE/DTZ are deliberately unselected -- see the design doc: BLE001 would
# contradict the exception-handling rule in CLAUDE.md.
ignore = ["E501"]

[tool.mypy]
python_version = "3.12"
ignore_missing_imports = true
explicit_package_bases = true
mypy_path = "."
exclude = ["venv/", "logs/"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
pythonpath = "."
testpaths = ["tests"]
```

- [ ] **Step 6: Delete pytest.ini**

Its four settings now live in `[tool.pytest.ini_options]`. Two config sources would be ambiguous:
```bash
rm backend/pytest.ini
```

- [ ] **Step 7: Verify pytest still finds and passes everything on 3.12**

Run from `backend/`:
```bash
./venv/bin/python -m pytest -q
```
Expected: `139 passed`. If collection finds 0 tests, `[tool.pytest.ini_options]` was not picked up — check that `pyproject.toml` is in `backend/`, not the repo root.

- [ ] **Step 8: Verify ruff reads the pinned config**

Run from `backend/`:
```bash
./venv/bin/ruff check . --statistics
```
Expected: `230 errors`, with **no `E501` line** in the output. Seeing `E501` means `ignore` is not being read; seeing ~379 means the same. The 230 findings are expected here — Task 2 clears them.

- [ ] **Step 9: Record the Python version in backend/CLAUDE.md**

Append this section to the end of `backend/CLAUDE.md`. Without it, the next person to recreate the venv uses whatever `python3` is first on `PATH` and the skew returns:
```markdown
## Toolchain

- **Python 3.12.** Create the venv with `python3.12 -m venv venv` explicitly —
  not `python3`, which may point at a newer interpreter. CI and the container
  image both pin 3.12 (`pyproject.toml`, `Dockerfile`), and a local venv on a
  different version means CI can fail on code that passed locally.
- Install with `pip install -r requirements-dev.txt`. `requirements.txt` is
  runtime-only: it is what the container image installs.
- Lint and test config is pinned in `pyproject.toml`. `ruff check .` and
  `pytest -q` gate CI; `black --check .` and `mypy .` are advisory today.
```

- [ ] **Step 10: Commit**

```bash
cd "/Volumes/Samsung SSD 1TB/projects_Samsung 1TB/ai/ai_customer_support_v5"
git add backend/pyproject.toml backend/requirements-dev.txt backend/requirements.txt backend/CLAUDE.md
git rm --cached backend/pytest.ini
git commit -m "$(cat <<'EOF'
chore(backend): standardize on Python 3.12 and pin tool config

Moves pytest settings into pyproject.toml, pins ruff's rule set and
target-version, and splits the dev toolchain out of requirements.txt so the
container image installs runtime deps only. Records 3.12 in CLAUDE.md so a
recreated venv does not drift back onto whatever python3 is on PATH.

Verified: 139 tests pass on 3.12.13.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Clear the backend lint debt

Deliverable: `ruff check .` exits clean with 139 tests still passing. Measured during design: 200 of the 230 findings are auto-fixable; 22 need hand work (the count differs from 230−200 because autofix resolves some findings and reveals others).

**Files:**
- Modify: many files under `backend/` via autofix (imports, typing syntax)
- Modify by hand: `backend/routers/chat.py`, `backend/routers/knowledge_base.py`, `backend/services/api_key_service.py`, `backend/services/ecommerce_shop_client.py`, `backend/services/email_gates.py`, `backend/services/reply_delivery_service.py`, `backend/services/shopify_admin_client.py`, `backend/utils/logging_setup.py`

**Interfaces:**
- Consumes: `backend/pyproject.toml` and the 3.12 venv from Task 1.
- Produces: a lint-clean backend. No public function signatures change except `str = None` → `str | None = None`, which is a type-annotation correction only and alters no runtime behavior.

- [ ] **Step 1: Record the baseline**

Run from `backend/`:
```bash
./venv/bin/python -m pytest -q
```
Expected: `139 passed`. This is the number that must not change.

- [ ] **Step 2: Apply the autofixes**

```bash
cd backend
./venv/bin/ruff check . --fix
```
Expected: roughly `200 fixed, 22 remaining`. Do **not** pass `--unsafe-fixes`, though ruff will mention 6 more fixes behind it.

- [ ] **Step 3: Verify the autofixes broke nothing**

```bash
./venv/bin/python -m pytest -q
```
Expected: `139 passed`. (Verified during design on a throwaway copy.) If any test fails, the autofix touched something subtle — inspect with `git diff` on the failing module before continuing.

- [ ] **Step 4: Commit the mechanical diff on its own**

Keeping this separate means the hand-written fixes in Step 5 are reviewable without scrolling past 200 mechanical edits:
```bash
git add -A backend
git commit -m "$(cat <<'EOF'
style(backend): apply ruff autofixes

Mechanical only: PEP 604 optionals, PEP 585 generics, import sorting,
unused imports, f-string conversions. No behavior change; 139 tests still
pass.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 5: Fix the 9 `B904` findings in `routers/chat.py`**

At lines 29, 61, 64, 86, 117, 123, 142, 165, 188 (line numbers shift as you edit — re-run ruff to relocate). Each is a `raise HTTPException(...)` inside an `except Exception as e:` block. Add `from e` so the original traceback is preserved. The first one currently reads:
```python
    except Exception as e:
        logger.error(f"❌ Error sending message: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error sending message: {str(e)}"
        )
```
Change the `raise` to:
```python
        raise HTTPException(
            status_code=500,
            detail=f"Error sending message: {str(e)}"
        ) from e
```
Apply the same `from e` to all nine. Where the caught variable has a different name, use that name.

- [ ] **Step 6: Fix the 4 `RUF013` implicit-optional findings**

`routers/chat.py` lines 40-41, in `list_conversations`:
```python
    status: str = None,
    channel: str = None
```
becomes:
```python
    status: str | None = None,
    channel: str | None = None
```

`services/api_key_service.py` line 46, in `create_key`:
```python
        name: str = None
```
becomes:
```python
        name: str | None = None
```

`utils/logging_setup.py` line 39, in `setup_logging`:
```python
def setup_logging(logger_name: str = None) -> logging.Logger:
```
becomes:
```python
def setup_logging(logger_name: str | None = None) -> logging.Logger:
```

- [ ] **Step 7: Fix the 3 `SIM117` nested-`with` findings**

Three sites, each with different arguments. Combine the nested pair into one parenthesized `async with`, then dedent the body one level (4 spaces).

`services/ecommerce_shop_client.py:23` — replace:
```python
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers, params=params) as resp:
```
with:
```python
            async with (
                aiohttp.ClientSession(timeout=timeout) as session,
                session.get(url, headers=headers, params=params) as resp,
            ):
```

`services/reply_delivery_service.py:106` — replace:
```python
            async with aiohttp.ClientSession() as session:
                async with session.post(webhook_url, json=payload) as resp:
```
with:
```python
            async with (
                aiohttp.ClientSession() as session,
                session.post(webhook_url, json=payload) as resp,
            ):
```

`services/shopify_admin_client.py:28` — replace:
```python
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload, headers=headers) as resp:
```
with:
```python
            async with (
                aiohttp.ClientSession(timeout=timeout) as session,
                session.post(url, json=payload, headers=headers) as resp,
            ):
```

- [ ] **Step 8: Fix `SIM102` at `services/email_gates.py:87`**

Replace:
```python
    if headers.get("return-path", "").strip() in ("<>", ""):
        if "return-path" in headers:
            return SkipReason.BOUNCE
```
with:
```python
    # Presence first: an absent return-path defaults to "", which would
    # otherwise match the empty-string case and flag every mail as a bounce.
    if "return-path" in headers and headers["return-path"].strip() in ("<>", ""):
        return SkipReason.BOUNCE
```
This is equivalent to the original — the outer test only reached the inner one when the header was present — and reordering makes that requirement explicit rather than incidental. `tests/test_email_gates.py` covers this path, so Step 13 will catch a mistake here.

- [ ] **Step 9: Suppress `B008` at `routers/knowledge_base.py:22`**

This is FastAPI's documented idiom, not a bug — `File(...)` in the default is how the framework declares an upload parameter:
```python
async def upload_document(request: Request, file: UploadFile = File(...)):
```
Add the suppression with its reason:
```python
async def upload_document(
    request: Request,
    file: UploadFile = File(...),  # noqa: B008 -- FastAPI's dependency idiom; the call in the default IS the declaration
):
```

- [ ] **Step 10: Fix `RUF012` at `utils/logging_setup.py:23`**

The `COLORS` dict is a mutable class attribute. Annotate it as a class variable:
```python
from typing import ClassVar
```
and change the declaration to:
```python
    COLORS: ClassVar[dict[str, str]] = {
```
leaving the dict body exactly as it is.

- [ ] **Step 11: Fix the remaining `F401` and `F841`**

`services/api_key_service.py:82` assigns `result` and never uses it:
```python
            result = await db["tenant_api_keys"].insert_one(key_doc)
```
The call must still happen — drop only the assignment:
```python
            await db["tenant_api_keys"].insert_one(key_doc)
```
For any `F401` still reported, delete the unused import — but first check the module's `__all__` and confirm it is not a deliberate re-export. If it is, add `# noqa: F401 -- re-exported for <consumer>`.

- [ ] **Step 12: Verify ruff is clean**

```bash
cd backend
./venv/bin/ruff check .
```
Expected: `All checks passed!` If findings remain, fix them by the same rules — a real fix, or a `# noqa` with a reason. Do not edit `pyproject.toml`.

- [ ] **Step 13: Verify the tests still pass**

```bash
./venv/bin/python -m pytest -q
```
Expected: `139 passed`. The `from e` and `| None` changes must not alter behavior; a failure here means a hand-edit went wrong.

- [ ] **Step 14: Commit**

```bash
git add -A backend
git commit -m "$(cat <<'EOF'
style(backend): resolve remaining ruff findings by hand

Exception chaining (raise ... from e), explicit Optional annotations,
combined context managers, ClassVar on a mutable class default, and a
documented noqa for FastAPI's File(...) default. ruff check . is clean;
139 tests pass.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Clear the frontend lint debt

Deliverable: `npm run lint`, `npx tsc --noEmit`, and `npm run build` all pass. Two `react-hooks/set-state-in-effect` errors exist; both get a real fix, and both fixes improve behavior rather than merely silencing the rule.

**Files:**
- Modify: `frontend/app/knowledge-base/page.tsx` (the `useEffect` at line 31)
- Modify: `frontend/app/human-agent/page.tsx` (the `useEffect` at line 37 and the `onClick` at line 90)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: a lint-clean frontend. `loadPairs()` keeps its name and signature — other call sites in the file still use it.

- [ ] **Step 1: Reproduce both failures**

```bash
cd frontend
npm run lint
```
Expected: `✖ 2 problems (2 errors, 0 warnings)` at `app/human-agent/page.tsx:39` and `app/knowledge-base/page.tsx:32`.

- [ ] **Step 2: Fix `knowledge-base/page.tsx`**

The effect calls `loadPairs()`, whose first statement is a synchronous `setLoading(true)` — that is what the rule rejects. `loading` already initializes to `true`, so the mount path does not need it. Replace:
```tsx
  useEffect(() => {
    loadPairs();
  }, []);
```
with:
```tsx
  // Not loadPairs(): its synchronous setLoading(true) in an effect body is
  // what react-hooks/set-state-in-effect rejects, and `loading` already
  // starts true. The cancelled flag also stops a late response from setting
  // state after unmount.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await listQAPairs();
        if (!cancelled) {
          setPairs(data);
          setError(null);
        }
      } catch {
        if (!cancelled) setError("Failed to load knowledge base.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);
```
Leave the `loadPairs` function itself in place — `handleAdd` and the other mutation handlers still call it.

- [ ] **Step 3: Fix `human-agent/page.tsx`**

The effect body clears state synchronously:
```tsx
  useEffect(() => {
    if (!selectedId) {
      setMessages([]);
      return;
    }
```
Clearing belongs in the event handler that changes the selection — React's recommended place to adjust state in response to a user action. Change the guard to:
```tsx
  useEffect(() => {
    if (!selectedId) return;
```
and change the `onClick` at line 90 from:
```tsx
              onClick={() => setSelectedId(c.conversation_id)}
```
to:
```tsx
              onClick={() => {
                setSelectedId(c.conversation_id);
                // Clear here, not in the effect: switching threads should not
                // show the previous conversation's messages while the new one loads.
                setMessages([]);
              }}
```

- [ ] **Step 4: Verify lint is clean**

```bash
cd frontend
npm run lint
```
Expected: no errors. If a fix turns out to require restructuring how these pages fetch data, stop and downgrade `react-hooks/set-state-in-effect` to `"warn"` in `frontend/eslint.config.mjs` with a comment naming it as deferred — then say so explicitly in the final report. Do not silently disable the rule, and do not let a data-fetching refactor ride along in this task.

- [ ] **Step 5: Verify types and build**

```bash
npx tsc --noEmit
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000 NEXT_PUBLIC_API_KEY=ci-dummy npm run build
```
Expected: `tsc` exits 0 silently; the build succeeds and lists 5 routes (`/`, `/_not-found`, `/emails`, `/human-agent`, `/knowledge-base`).

- [ ] **Step 6: Commit**

```bash
git add frontend/app/knowledge-base/page.tsx frontend/app/human-agent/page.tsx
git commit -m "$(cat <<'EOF'
fix(frontend): stop setting state synchronously in effect bodies

Both sites tripped react-hooks/set-state-in-effect. The knowledge-base
mount load now awaits before touching state (and ignores a late response
after unmount); human-agent clears the thread in the click handler that
changes selection, which also stops the previous conversation's messages
showing while the new thread loads.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Dockerfile, .dockerignore, and local boot verification

Deliverable: an image that builds, boots as non-root against a real Mongo, serves `/health`, honors `PORT`, and contains no secrets. All four properties are verified locally in this task, before any CI step depends on them.

**Files:**
- Create: `backend/Dockerfile`
- Create: `backend/.dockerignore`

**Interfaces:**
- Consumes: `backend/requirements.txt` (runtime-only, from Task 1).
- Produces: an image whose default `CMD` serves the API on `${PORT:-8000}`, and which runs the Gmail poller when overridden with `python -m scripts.poll_gmail`.

- [ ] **Step 1: Write the .dockerignore first**

Writing it before the Dockerfile means the very first build already excludes secrets. A build context does **not** consult `.gitignore`, so `credentials.json` and `.env` must be listed here even though git already ignores them. Create `backend/.dockerignore`:
```
venv/
.venv/
__pycache__/
*.pyc
logs/
*.log
.pytest_cache/
.ruff_cache/
.mypy_cache/
tests/
# Present and untracked locally. .gitignore does not apply to a build
# context, so without these lines they would be baked into an image layer.
.env
credentials.json
client_secret*.json
```

- [ ] **Step 2: Write the Dockerfile**

Create `backend/Dockerfile`:
```dockerfile
# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder
WORKDIR /app
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
# Runtime deps only -- the test and lint toolchain lives in requirements-dev.txt.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"
RUN useradd --create-home --uid 1000 app
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY . .
# utils/logging_setup.py calls LOGS_DIR.mkdir() and attaches RotatingFileHandlers
# at import time, so /app/logs must exist and be writable by the non-root user
# or every entrypoint dies before serving a request.
RUN mkdir -p /app/logs && chown -R app:app /app
USER app
EXPOSE 8000
# PORT with a fallback: Cloud Run injects PORT, and reading it now means the
# deployment round needs no application change. The poller runs from this same
# image by overriding the command: python -m scripts.poll_gmail
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

- [ ] **Step 3: Build the image**

```bash
cd backend
docker build -t backend:ci .
```
Expected: builds successfully. If a module is missing at a later step, a runtime dependency was wrongly moved into `requirements-dev.txt` in Task 1 — fix it there, in `requirements.txt`.

- [ ] **Step 4: Start a local Mongo**

The app's `lifespan` calls `Database.connect()` and re-raises on failure, so the container cannot boot without one:
```bash
docker run -d --name ci-mongo -p 27017:27017 mongo:7
```

- [ ] **Step 5: Boot the container and require HTTP 200 from /health**

This is the Review Focus #2 and #4 check — non-root write access to `/app/logs`, and a complete runtime dependency set:
```bash
docker run -d --name backend-smoke \
  -e MONGODB_URL="mongodb://host.docker.internal:27017" \
  -e MONGODB_DATABASE_NAME=ci_smoke \
  -e GEMINI_API_KEY=ci-dummy \
  -p 8000:8000 \
  backend:ci
for i in $(seq 1 30); do
  curl -fsS http://localhost:8000/health && break
  sleep 1
done
docker exec backend-smoke id
```
Expected: `/health` returns JSON with `"status":"ok"`, and `id` reports `uid=1000(app)` — not root. On failure run `docker logs backend-smoke`; a `PermissionError` on `/app/logs` means the `mkdir`/`chown` line is wrong or lands before `COPY`.

Note: the `create_search_index` call for `kb_vector_index` is Atlas-only and will log a skip against plain Mongo. That is expected — it is wrapped in a `try/except` that logs and continues.

- [ ] **Step 6: Assert no secrets are in the image**

Review Focus #1:
```bash
docker run --rm backend:ci sh -c 'ls -a /app; test ! -e /app/credentials.json && test ! -e /app/.env && test ! -d /app/venv && test ! -d /app/tests && echo "CLEAN"'
```
Expected: prints `CLEAN`. If it does not, add the missing entry to `.dockerignore` and rebuild — never ship the image.

- [ ] **Step 7: Assert PORT is honored**

Review Focus #3:
```bash
docker rm -f backend-smoke
docker run -d --name backend-port \
  -e MONGODB_URL="mongodb://host.docker.internal:27017" \
  -e MONGODB_DATABASE_NAME=ci_smoke \
  -e GEMINI_API_KEY=ci-dummy \
  -e PORT=9090 \
  -p 9090:9090 \
  backend:ci
for i in $(seq 1 30); do
  curl -fsS http://localhost:9090/health && break
  sleep 1
done
```
Expected: `/health` answers on 9090. If it only ever answers on 8000, the `CMD` is not expanding `${PORT}` — it must go through `sh -c`, not exec form with a literal port.

- [ ] **Step 8: Verify the poller entrypoint uses the same image**

```bash
docker run --rm \
  -e MONGODB_URL="mongodb://host.docker.internal:27017" \
  -e MONGODB_DATABASE_NAME=ci_smoke \
  -e GEMINI_API_KEY=ci-dummy \
  backend:ci python -m scripts.poll_gmail --once
```
Expected: exits 0. With `GMAIL_ENABLED` unset it defaults to false, so the worker logs that the channel is disabled and does one no-op cycle. An `ImportError` or `ModuleNotFoundError` means `scripts/` was excluded from the image — check `.dockerignore`.

- [ ] **Step 9: Tear down**

```bash
docker rm -f backend-port ci-mongo 2>/dev/null || true
```

- [ ] **Step 10: Commit**

```bash
git add backend/Dockerfile backend/.dockerignore
git commit -m "$(cat <<'EOF'
build(backend): add container image with a non-root runtime

Multi-stage on python:3.12-slim, runtime deps only, non-root uid 1000, and
uvicorn bound to ${PORT:-8000} so the later Cloud Run round needs no code
change. /app/logs is created and chowned because logging_setup builds
RotatingFileHandlers at import time. The Gmail poller runs from this same
image with an overridden command, keeping the two processes separate.

Verified locally: boots against mongo:7 and serves /health as uid 1000,
answers on PORT=9090, ships no credentials.json/.env/venv/tests, and runs
poll_gmail --once cleanly.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Add both CI workflows

Deliverable: both workflows run and pass on the pull request that introduces them. Every command below has already been run locally in Tasks 1-4, so this task adds automation, not new checks.

**Files:**
- Create: `.github/workflows/backend-ci.yml`
- Create: `.github/workflows/frontend-ci.yml`

**Interfaces:**
- Consumes: `backend/requirements-dev.txt`, `backend/pyproject.toml`, `backend/Dockerfile` from Tasks 1 and 4.
- Produces: two required-checkable job names, `backend-ci / checks` and `frontend-ci / checks`.

- [ ] **Step 1: Write backend-ci.yml**

Create `.github/workflows/backend-ci.yml`:
```yaml
name: backend-ci

on:
  pull_request:
    branches: [main]
    paths:
      - 'backend/**'
      - '.github/workflows/backend-ci.yml'
  push:
    branches: [main]
    paths:
      - 'backend/**'
      - '.github/workflows/backend-ci.yml'

jobs:
  checks:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: backend
    services:
      # The app's lifespan calls Database.connect() and re-raises on failure,
      # so the container smoke test below needs a real Mongo. The unit tests
      # do not -- they use hand-written fakes.
      mongo:
        image: mongo:7
        ports:
          - 27017:27017

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: pip
          cache-dependency-path: backend/requirements-dev.txt

      - name: Install dependencies
        run: pip install -r requirements-dev.txt

      - name: Lint (gate)
        run: ruff check .

      - name: Tests (gate)
        run: pytest -q

      - name: Format check (advisory)
        run: black --check .
        continue-on-error: true

      - name: Type check (advisory)
        run: mypy .
        continue-on-error: true

      - name: Build image
        run: docker build -t backend:ci .

      - name: Boot the container and require /health
        run: |
          docker run -d --name backend-smoke --network host \
            -e MONGODB_URL="mongodb://localhost:27017" \
            -e MONGODB_DATABASE_NAME=ci_smoke \
            -e GEMINI_API_KEY=ci-dummy \
            -e PORT=8000 \
            backend:ci
          for i in $(seq 1 30); do
            if curl -fsS http://localhost:8000/health; then
              echo "container healthy"
              exit 0
            fi
            sleep 1
          done
          echo "::error::container did not serve /health within 30s"
          docker logs backend-smoke
          exit 1

      - name: Assert the image ships no secrets
        run: |
          docker run --rm backend:ci sh -c '
            test ! -e /app/credentials.json &&
            test ! -e /app/.env &&
            test ! -d /app/venv &&
            test ! -d /app/tests &&
            echo CLEAN'

      - name: Clean up the smoke container
        if: always()
        run: docker rm -f backend-smoke || true
```

`--network host` is what lets the container reach the `mongo` service on `localhost`; it works because the runner is Linux.

- [ ] **Step 2: Write frontend-ci.yml**

Create `.github/workflows/frontend-ci.yml`:
```yaml
name: frontend-ci

on:
  pull_request:
    branches: [main]
    paths:
      - 'frontend/**'
      - '.github/workflows/frontend-ci.yml'
  push:
    branches: [main]
    paths:
      - 'frontend/**'
      - '.github/workflows/frontend-ci.yml'

jobs:
  checks:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend
    env:
      # Build-time placeholders, not secrets. lib/api.ts non-null-asserts both,
      # and next build prerenders pages that reach that module.
      NEXT_PUBLIC_BACKEND_URL: http://localhost:8000
      NEXT_PUBLIC_API_KEY: ci-dummy

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: '26'
          cache: npm
          cache-dependency-path: frontend/package-lock.json

      - name: Install dependencies
        run: npm ci

      - name: Type check
        run: npx tsc --noEmit

      - name: Lint
        run: npm run lint

      - name: Build
        run: npm run build
```

If `setup-node` cannot resolve `26` (the action reports `Unable to find Node version '26'`), fall back to `'24'` — still newer than Next 16's floor — change the value, and say in the final report that CI runs 24 while local is 26.9.0. Do not silently pick a version without reporting the skew.

- [ ] **Step 3: Validate both files parse as YAML**

A typo here costs a full push/CI round-trip:
Use the backend venv's interpreter — PyYAML is present there as a transitive dependency of `uvicorn[standard]`, and the system `python3.12` may not have it:
```bash
cd "/Volumes/Samsung SSD 1TB/projects_Samsung 1TB/ai/ai_customer_support_v5"
./backend/venv/bin/python -c "
import yaml, pathlib
for p in sorted(pathlib.Path('.github/workflows').glob('*.yml')):
    yaml.safe_load(p.read_text())
    print(f'{p} OK')
"
```
Expected: both files print `OK`. A `ModuleNotFoundError: yaml` means the venv is not the one built in Task 1 — re-check Task 1 Step 4 rather than installing PyYAML by hand.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/backend-ci.yml .github/workflows/frontend-ci.yml
git commit -m "$(cat <<'EOF'
ci: gate the backend and frontend on every PR and push to main

Two path-filtered workflows. Backend gates ruff and pytest, then builds the
image and requires it to serve /health against a mongo:7 service container,
plus asserts no secrets shipped; black and mypy report without blocking.
Frontend gates tsc, lint, and build.

Every command here was run locally first -- a workflow whose steps have
never been executed by hand is a guess.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 5: Push the branch and open a pull request**

```bash
git push -u origin HEAD
gh pr create --title "CI foundation: automated checks and a verified container image" \
  --body "$(cat <<'EOF'
Implements `docs/superpowers/specs/2026-09-27-ci-cd-foundation-design.md`.

Adds path-filtered GitHub Actions workflows for backend and frontend, a
multi-stage Dockerfile for the backend, and the pinned tool config the gate
needs. Standardizes on Python 3.12 across local, CI, and the image.
Deployment to Cloud Run is a deliberate follow-up round.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 6: Confirm both workflows actually ran**

Review Focus #5 — a skipped job looks identical to a green one in a merge button:
```bash
gh pr checks --watch
```
Expected: both `backend-ci / checks` and `frontend-ci / checks` appear with status **pass**. If either is missing or reports `skipped`, the `paths` filter or branch name is wrong — fix the filter, push, and re-check. Do not report success while a job is skipped.

- [ ] **Step 7: Report what is deliberately left undone**

In the final summary, state explicitly:
- `black` (51 files unformatted) and `mypy` are advisory, not gates — check the run logs to see their current output.
- Branch protection requiring these two checks is a GitHub repository setting, not a file in this repo, and has not been configured.
- Deployment, Artifact Registry, and Workload Identity Federation are the next round.
- Logging still writes to rotating files on an ephemeral filesystem, and `NEXT_PUBLIC_API_KEY` is still compiled into the browser bundle. Both are recorded in the spec's deferred table with triggers.
