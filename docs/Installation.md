# Installation

Two ways to install Mnemos. End-users take the **prebuilt images** path. Developers who want to hack on the code take the **build from source** path.

- [Prebuilt images (production)](#prebuilt-images-production)
- [Build from source (development)](#build-from-source-development)
- [Uninstalling](#uninstalling)

---

## Prebuilt images (production)

Each release ships a `docker-compose.yml` and a `.env.example`. Download both into an empty directory.

### Requirements

- Linux, macOS, or Windows + WSL2
- Docker Engine 24+
- Docker Compose v2 (`docker compose`, not `docker-compose`)
- 2 GB free disk for the base images and `buffalo_s` model
- A reachable network on first start (model weights are downloaded from the manifest at runtime)

### Step-by-step

```bash
mkdir mnemos && cd mnemos
curl -L -O https://github.com/vithurshanselvarajah/Mnemos/releases/latest/download/docker-compose.yml
curl -L -O https://github.com/vithurshanselvarajah/Mnemos/releases/latest/download/.env.example
cp .env.example .env
```

Edit `.env` and set at minimum:

```dotenv
MNEMOS_PG_PASSWORD=replace-with-something-long-and-random
MNEMOS_FE_SECRET=$(openssl rand -hex 32)
MNEMOS_TAG=latest          # pin to a specific release once you go to production
MNEMOS_PROVIDER=cpu        # cpu | nvidia | rockchip
```

Then:

```bash
docker compose pull
docker compose up -d
docker compose logs -f
```

The first start downloads the detection model from the upstream manifest. The backend is healthy once `/healthz` returns `{"status": "ok", "model_loaded": true, ...}`.

### Upgrading

```bash
docker compose pull
docker compose up -d
```

Data is preserved in the `./mnemos/` host directory (created on first run). To pin to a specific version, set `MNEMOS_TAG=0.1.0` (or whatever the release tag is) in `.env` before pulling.

### Rolling back

```bash
MNEMOS_TAG=0.0.9 docker compose pull
MNEMOS_TAG=0.0.9 docker compose up -d
```

If the data layout changed between versions, see the [release notes](https://github.com/vithurshanselvarajah/Mnemos/releases) before rolling back.

---

## Build from source (development)

For hacking on the code. Uses `docker-compose.dev.yml`, which builds images from the local source tree.

### Helper script

The `bin/mnemos` wrapper covers the day-to-day dev commands:

```bash
bin/mnemos up                       # build + start the dev stack
bin/mnemos status                   # show containers, volumes, images
bin/mnemos logs                     # tail all service logs
bin/mnemos down                     # stop the dev stack (keeps images + data)
bin/mnemos delete images [-y]       # remove dev images, keep data
bin/mnemos delete data   [-y]       # remove volumes (backend.db, crops, pgvector)
bin/mnemos delete all    [-y]       # nuke everything Mnemos-related on this host
```

It only touches locally-built images — it will never pull or delete `ghcr.io/vithurshanselvarajah/mnemos-*`.

### Manual control

If you'd rather drive Compose yourself:

```bash
docker compose -f docker-compose.dev.yml up --build
```

The dev compose file picks the inference provider via the `MNEMOS_PROVIDER` env var. The `mnemos-backend/Dockerfile` uses `INSTALL_PROVIDER` and `BASE_IMAGE` build args to inject the right onnxruntime variant and system libraries. Setting `MNEMOS_PROVIDER` to `nvidia` automatically sets the matching build args; same for `rockchip`.

### Running the test suite

```bash
python3 -m pip install -r tests/requirements.txt  # if you maintain a dev reqs file; otherwise install dev deps
python3 -m pytest tests/
```

See [Testing](https://github.com/vithurshanselvarajah/Mnemos/wiki/Testing) for the full layout, fixtures, and how to add a case.

---

## Uninstalling

To stop and remove the stack but keep data:

```bash
docker compose down
```

To remove everything (containers, images, volumes) on this host:

```bash
# For prebuilt install:
docker compose down --rmi all -v

# For dev install (uses the helper):
bin/mnemos delete all -y
```

This deletes the `./mnemos/` host directory and the `.env` file. There is no remote state — Mnemos is 100% local.

---

## For developers

### Image layout

Each backend image is multi-stage:

1. **Builder** (`python:3.14-slim`) — installs the variant-specific requirements (`variants/<provider>/requirements.txt`) plus the base `mnemos-backend/requirements.txt`.
2. **Runtime** — varies by provider:
   - CPU: `python:3.14-slim` + `libgl1` for OpenCV
   - NVIDIA: `nvidia/cuda:12.4.1-cudnn-runtime-ubuntu24.04`
   - Rockchip: `python:3.14-slim` + `librknnrt` (vendored at build time)

The `INSTALL_PROVIDER` build arg selects which `variants/<provider>/requirements.txt` to merge in. The `BASE_IMAGE` build arg selects the runtime stage. The entrypoint is a single `uvicorn app.main:app`; the rest of the backend has no provider awareness — the provider is just a class loaded by `app.services.engine.InsightFaceEngine`.

### Where the secrets live

- **PG password** — set via `MNEMOS_PG_PASSWORD` env, used by both pgvector and the backend's `MNEMOS_VECTOR_DSN`.
- **Frontend session secret** — `MNEMOS_FE_SECRET`, must be at least 32 bytes.
- **Master pairing key** — generated on first start, stored in `mnemos/backend/master_key` row in SQLite, surfaced via the CLI and `GET /api/v1/system/master`.

There is intentionally no way to set the master key via env. The whole point of it is that nobody else ever sees it; it is bootstrapped from the host.
