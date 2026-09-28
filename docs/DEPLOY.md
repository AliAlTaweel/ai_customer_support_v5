# Deploying the backend to a GCP VM

This walks through putting the backend on a single Compute Engine instance,
from nothing to a working `https://.../health`. Follow it top to bottom.

What ends up running: three containers on the VM — the API, the Gmail poll
worker, and Caddy (a small web server that handles HTTPS and forwards traffic
to the API). Only Caddy is reachable from the internet.

Files involved: `docker-compose.yml` and `Caddyfile` in the repo root.

---

## Part 1 — Things to prepare before touching the VM

### 1.1 A static IP for the VM

A VM's external IP changes when it restarts, which would break DNS and your
MongoDB allowlist. In the Google Cloud console:

**VPC network → IP addresses → Reserve external static address**, then attach
it to your instance. Write the IP down — call it `VM_IP` below.

### 1.2 Open the firewall

The VM must accept HTTPS. Easiest route: **Compute Engine → VM instances →
your VM → Edit → Firewalls → check "Allow HTTPS traffic" → Save.**

That opens 443 only, which is all this setup needs — the certificate is
obtained over the TLS-ALPN-01 challenge, which runs on 443 too. Port 80 stays
closed, so plain-HTTP requests are refused rather than redirected; the
`Caddyfile` is configured to match.

Do **not** open port 8000 — nothing should reach the API except through Caddy.

### 1.3 MongoDB Atlas

This project needs Atlas specifically, not a MongoDB you install on the VM:
the knowledge-base search uses Atlas vector search (`kb_vector_index`).

In Atlas: **Network Access → Add IP Address → `VM_IP`**. Without this, the API
starts and then fails every database call.

Have your Atlas connection string ready (`mongodb+srv://...`).

### 1.4 A hostname (required)

Point a DNS `A` record — for example `api.yourdomain.com` — at `VM_IP`. Caddy
uses it to get a free HTTPS certificate automatically.

A hostname is not optional here: **no public certificate authority will issue
a certificate for a bare IP address**, so `https://VM_IP` cannot work. If you
don't own a domain, a free dynamic-DNS hostname such as
`yourname.duckdns.org` works exactly the same way — register it and point it
at `VM_IP`.

Verify it resolves before deploying, or the first certificate request fails:

```bash
dig +short api.yourdomain.com     # must print VM_IP
```

### 1.5 The Gmail refresh token (only if you use the email channel)

`python -m scripts.gmail_auth` opens a browser and needs `credentials.json`,
so run it **on your laptop**, not the VM. Copy the `GMAIL_REFRESH_TOKEN` it
prints — that token is all the server needs. `credentials.json` never goes to
the VM.

---

## Part 2 — Set up the VM

SSH in from the console (the **SSH** button next to the instance), then paste
these blocks one at a time.

### 2.1 Install Docker

```bash
sudo apt-get update && sudo apt-get install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
# $ID and $VERSION_CODENAME come from /etc/os-release, so this is correct on
# both Debian and Ubuntu. The key path and the repo path must name the same
# distro -- mixing them is what produces a 404 from apt.
. /etc/os-release
sudo curl -fsSL "https://download.docker.com/linux/$ID/gpg" -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/$ID $VERSION_CODENAME stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update
sudo apt-get install -y docker-ce docker-compose-plugin
sudo usermod -aG docker $USER
```

A `404 Not Found` on the docker repo means Docker publishes nothing for this
release's codename yet. Check `https://download.docker.com/linux/$ID/dists/`,
then either substitute the previous stable codename in
`/etc/apt/sources.list.d/docker.list` or use the distro's own packages:
`sudo apt-get install -y docker.io docker-compose-v2`.

Now **log out and back in** so your user picks up Docker access. Verify:

```bash
docker run --rm hello-world
```

### 2.2 Get the code onto the VM

```bash
sudo mkdir -p /opt/acs && sudo chown $USER /opt/acs
git clone <your-repo-url> /opt/acs/app
cd /opt/acs/app
```

If the repo is private, create a read-only **deploy key**: run
`ssh-keygen -t ed25519 -C "acs-vm" -f ~/.ssh/id_ed25519 -N ""` on the VM,
then add the contents of `~/.ssh/id_ed25519.pub` under the repo's
**Settings → Deploy keys** on GitHub, and clone with the SSH URL
(`git@github.com:...`).

---

## Part 3 — Configuration

Two config files, both created by hand on the VM. Neither is in git — they
hold secrets.

### 3.1 `backend/.env` — the application's settings

```bash
cd /opt/acs/app
cp backend/.env.example backend/.env
nano backend/.env
```

Fill in at minimum:

```
ENVIRONMENT=production
BACKEND_DEBUG=false
LOG_LEVEL=INFO

MONGODB_URL=mongodb+srv://...           # from Atlas (step 1.3)
MONGODB_DATABASE_NAME=ai_customer_support_v5

GEMINI_API_KEY=...

FRONTEND_URL=https://app.yourdomain.com
```

Two things that will bite you if you skip them:

- **`MONGODB_URL` and `GEMINI_API_KEY` are required at startup.** `config.py`
  raises immediately if either is missing, so the container will restart in a
  loop rather than run in a degraded state.
- **`FRONTEND_URL` is the *only* allowed browser origin in production.** With
  `ENVIRONMENT=production`, CORS is restricted to exactly that one URL. If it
  is wrong or empty, the chat widget gets CORS errors even though the API is
  healthy.

For the Gmail block, keep the safe defaults on the first deploy:

```
GMAIL_ENABLED=true
GMAIL_DRY_RUN=true                      # replies are logged, not sent
GMAIL_ALLOWED_SENDERS=you@example.com   # only your own address is answered
GMAIL_REFRESH_TOKEN=...                 # from step 1.5
```

Leave `GMAIL_ENABLED=false` if you are not using email at all — the poller
container will simply idle.

Then lock the file down:

```bash
chmod 600 backend/.env
```

### 3.2 `.env` — the domain Caddy should serve

This one sits next to `docker-compose.yml` and holds a single line.

```bash
nano /opt/acs/app/.env
```

Use the hostname from step 1.4 — no `https://` prefix, no trailing slash:

```
APP_DOMAIN=api.yourdomain.com
```

An IP address here will not work: Caddy would fall back to a self-signed
certificate that every browser rejects.

---

## Part 4 — Start it

```bash
cd /opt/acs/app
docker compose up -d --build
```

The first run takes a few minutes: it builds the Python image, then Caddy
requests a certificate. Check it:

```bash
docker compose ps                       # all three should be Up
curl -fsS https://api.yourdomain.com/health
```

A healthy response looks like `{"status":"ok","timestamp":...}`.

Useful when it isn't:

```bash
docker compose logs -f api        # app errors, startup failures
docker compose logs -f caddy      # certificate / proxy problems
docker compose logs -f poller     # Gmail polling
```

`api` restarting over and over almost always means a missing or wrong value in
`backend/.env` — the logs name the variable.

---

## Part 5 — After it works

### Point the frontend at it

The frontend needs its API base URL set to `https://api.yourdomain.com`. That
value is baked in at build time (it is a `NEXT_PUBLIC_*` variable), so the
frontend has to be rebuilt after changing it — restarting is not enough.

### Turn on real email sending

Walk the three steps in the main README's email-channel table, one config
change at a time: dry-run with your own address, then real sends to your own
address, then open it up. After editing `backend/.env`:

```bash
docker compose up -d        # recreates containers with the new values
```

### Deploy a new version

```bash
cd /opt/acs/app
git pull
docker compose up -d --build
```

### Reboots

`restart: always` plus Docker's own systemd service means all three containers
come back on their own after a VM restart. Nothing extra to configure.

---

## Notes and trade-offs

- **This is a VM, not Cloud Run.** The design docs
  (`docs/superpowers/specs/2026-09-27-ci-cd-foundation-design.md`) plan Cloud
  Run, and the Dockerfile's `${PORT:-8000}` exists for it. A VM works and is
  actually a better home for the always-on Gmail poller, but you own OS
  patching, TLS (Caddy handles it), and monitoring yourself.
- **Building on the VM is the simple path, not the best one.** A small
  instance can be slow or run out of memory during `pip install`. The next
  step up is building the image in CI, pushing it to Artifact Registry, and
  having the VM only pull — worth doing once redeploys get frequent.
- **Logs** go to Docker (`docker compose logs`) and to rotating files in the
  `api_logs` / `poller_logs` volumes. Nothing ships them off the box yet.
