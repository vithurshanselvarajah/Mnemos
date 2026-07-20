# Mnemos

Pronounced **nee-MOZ** after the greek god of goddess of memory.

A Decoupled & Python-native facial recognition system designed to process snapshot
images from Home Assistant, identify known individuals, and provide a
management interface for labeling unrecognized faces.

- **Backend** (`mnemos-backend`) — FastAPI + InsightFace (CPU via ONNX Runtime) + pgvector.
- **Frontend** (`mnemos-frontend`) — FastAPI + Jinja2 + HTMX + Alpine.js management UI.
- **Vector DB** (`mnemos-vector-db`) — PostgreSQL 18 with the `pgvector` extension.

## New Project Notice 
This is still a work in progress. It was born partially out of my WakeOnPi project. If you come across any bugs. Please raise a issue. 

## Quick start

There are two compose files, used for different audiences:

### End-users (production)

Each release will contain a docker-compose.yaml and a .env.example file. Please download these rather than directly from the repo.

```bash
# Copy the example env file and edit the secrets + image tag
cp .env.example .env
nano .env

# Pull + start the stack
docker compose pull
docker compose up -d

# Tail logs
docker compose logs -f

# Stop
docker compose down
```

#### `.env` file

`docker compose` automatically reads a `.env` file in the same directory as
`docker-compose.yml`. A fully-commented example lives at
[`.env.example`](.env.example) — copy it to `.env` and edit. The supported
variables are:

| Variable | Default | Purpose |
| --- | --- | --- |
| `MNEMOS_TAG` | `latest` | Image tag to pull from GHCR. Pin to a specific release (e.g. `0.1.0`) once you go to production. |
| `MNEMOS_PG_PASSWORD` | `mnemos-pgvector-changeme` | Password for the pgvector database. Used by both pgvector itself and the backend's `MNEMOS_VECTOR_DSN`. **Change before exposing anything beyond localhost.** |
| `MNEMOS_FE_SECRET` | `change-me-…-32bytes` | Frontend session-cookie signing key. Must be at least 32 random bytes. **Change before exposing anything beyond localhost.** Generate with `openssl rand -hex 32`. |
| `MNEMOS_DEFAULT_MODEL` | `buffalo_s` | Default face-recognition model. `buffalo_s` (fast, ~300MB) or `buffalo_l` (slower, more accurate, ~1GB). Can be changed at runtime from the Model page in the UI. |

> **Why isn't the master key in here?** The backend's *master pairing key* is
> a one-time secret that the backend generates and stores in its own SQLite
> volume on first boot. You read it once with
> `docker exec -it mnemos-backend python -m app.cli master-key view` and paste
> it into the UI's onboarding screen. It is not (and should not be) settable
> via `docker-compose.yml` — the whole point is that nobody else ever sees it.

You can also override any of these inline without a `.env` file:

```bash
MNEMOS_TAG=0.1.0 docker compose pull
MNEMOS_TAG=0.1.0 docker compose up -d
```

### Developers (build from source)

`docker-compose.dev.yml` builds the images from the local source.
Use the `bin/mnemos` helper for the usual dev workflow.

```bash
bin/mnemos up                       # build + start the dev stack
bin/mnemos status                   # show containers, volumes, images
bin/mnemos logs                     # tail all service logs
bin/mnemos down                     # stop the dev stack (keeps images + data)
bin/mnemos delete images [-y]       # remove dev images, keep data
bin/mnemos delete data   [-y]       # remove volumes (backend.db, crops, pgvector)
bin/mnemos delete all    [-y]       # nuke everything Mnemos-related on this host
```

`bin/mnemos` only manages the locally-built dev images — it will never
touch `ghcr.io/vithurshanselvarajah/mnemos-*`. Pass `-y` to any `delete`
subcommand to skip the confirmation prompt.

### First run (either compose)

```bash
# Once the backend is up, read the master pairing key
docker exec -it mnemos-backend python -m app.cli master-key view

# Open the UI at http://localhost:8080 and complete the two-step onboarding:
#   1. Create the first Admin user
#   2. Pair with the backend (paste the master key from the CLI)
```

### Healthcheck

```bash
curl -s http://localhost:8000/healthz | jq
curl -s http://localhost:8080/healthz | jq
```

Both services expose `GET /healthz`. The frontend's healthz reaches into the
backend and surfaces its `/healthz` payload so a single curl shows the state
of the whole stack. Both responses include a `version` field populated from
the `VERSION` file at the repository root.

## API documentation

The backend's OpenAPI schema is available at:

- Swagger UI — `http://localhost:8000/docs` (or via the frontend at `/swagger`)
- ReDoc — `http://localhost:8000/redoc`
- Raw schema — `http://localhost:8000/openapi.json`

The frontend exposes a themed, locally hosted Swagger UI at
`http://localhost:8080/swagger` that proxies the backend's OpenAPI document.
Every page in the frontend requires authentication except `/login`, `/onboarding`,
`/healthz`, and the public assets under `/static/`.

## API quick reference (backend)

| Method | Path | Auth | Notes |
| ------ | ---- | ---- | ----- |
| `POST` | `/api/v1/identify` | `X-API-Key` | Multipart upload; returns recognized people + unknown crops |
| `GET`  | `/api/v1/faces/unassigned?page=N` | any key | Inbox listing |
| `POST` | `/api/v1/faces/assign` | any key | `{crop_ids:[], person_id?, new_person_name?}` |
| `POST` | `/api/v1/faces/mark-non-face` | any key | Excludes from vector index |
| `POST` | `/api/v1/faces/ignore` | any key | Archived but not assigned |
| `GET`  | `/api/v1/persons` | any key | List persons with sample counts |
| `POST` | `/api/v1/persons` | any key | Create person (optional custom threshold) |
| `PATCH`| `/api/v1/persons/{id}` | any key | Rename or set custom threshold |
| `DELETE`| `/api/v1/persons/{id}` | any key | Unlinks crops, drops vector rows |
| `GET`  | `/api/v1/models` | any key | Active model + reindex state |
| `POST` | `/api/v1/models/switch` | any key | `{name: "buffalo_s"/"buffalo_l"}`; background reindex |
| `GET`  | `/api/v1/keys` | Full-Admin | List API keys |
| `POST` | `/api/v1/keys` | Full-Admin | Create a new key (raw shown once) |
| `POST` | `/api/v1/keys/{id}/revoke` | Full-Admin | Mark revoked |
| `DELETE`| `/api/v1/keys/{id}` | Full-Admin | Delete |
| `GET`  | `/api/v1/crops/{uuid}.jpg` | any key | Stream the cropped JPEG |
| `POST` | `/api/v1/system/pair` | none | Frontend onboarding; exchanges master key for a new Full-Admin key |
| `WS`   | `/ws/events` | none | Broadcasts: `inbox.new_face`, `inbox.bulk_changed`, `reindex.start/progress/done/error` |
| `GET`  | `/healthz` | none | Version + DB + vector DB + reindex status |

The Bruno collection under `bruno/collection/` mirrors this surface and is
the fastest way to exercise the API by hand.

## How the recognition pipeline works

1. `POST /api/v1/identify` decodes the image (JPEG/PNG/WebP) with OpenCV (PIL
   fallback for WebP).
2. InsightFace detects faces; detections smaller than `30x30` are dropped.
3. For each detection, the 512-D embedding is searched against pgvector using
   cosine distance (`<=>` operator). The HNSW index makes this sub-millisecond
   for typical home workloads.
4. If the best match has cosine distance <= the global threshold
   (`MNEMOS_DEFAULT_THRESHOLD`, default `0.40`, i.e. >= 60% similarity) — or
   the matched person has a custom threshold — it's recorded as a
   `recognized` hit.
5. Otherwise, the face is cropped with **50% extra padding** (per the spec
   formula) and saved to `/data/crops/<crop_id>.jpg`. A row with status
   `UNASSIGNED` is inserted, and the frontend's inbox is notified via the
   `/ws/events` WebSocket.

## Switching models

`POST /api/v1/models/switch {"name": "buffalo_l"}` triggers a background
worker that:

1. Initializes the new model in memory (lazy).
2. Walks every crop JPEG under `/data/crops/`.
3. Re-extracts embeddings and groups them by person.
4. Computes the averaged, unit-normalized vector for each person under the
   new model.
5. Atomically replaces the `face_embeddings` rows and updates the
   `active_model` system setting.

Progress is broadcast on the same `/ws/events` WebSocket. The frontend
displays a live progress bar via `/partials/reindex-status`.

## Configuration

All knobs live as `MNEMOS_*` / `MNEMOS_FE_*` environment variables in
`docker-compose.yml`. There is no `.env` file.

### Backend
- `MNEMOS_DB_PATH` — SQLite file (default `/data/backend.db`).
- `MNEMOS_CROPS_DIR` — Crop JPEG directory (default `/data/crops`).
- `MNEMOS_VECTOR_DSN` — pgvector DSN.
- `MNEMOS_DEFAULT_MODEL` — `buffalo_s` or `buffalo_l`.
- `MNEMOS_DEFAULT_THRESHOLD` — cosine distance; default `0.40` (= 60% similarity).
- `MNEMOS_MIN_FACE_PX` — minimum bounding-box side in pixels (default `30`).
- `MNEMOS_CROP_PAD_FRACTION` — padding as a fraction of bbox (default `0.50`).
- `MNEMOS_CORS_ORIGINS` — comma-separated origin list.

### Frontend
- `MNEMOS_FE_DB_PATH` — SQLite file (default `/data/frontend.db`).
- `MNEMOS_FE_SESSION_HOURS` — default session lifetime in hours (default `8`).
- `MNEMOS_FE_REMEMBER_DAYS` — "Keep me logged in" lifetime in days (default `30`).
- `MNEMOS_FE_DEFAULT_BACKEND_URL` — default backend URL when onboarding.
- `MNEMOS_FE_SECRET` — server-side cookie secret. **Rotate on first run.**

## Development

### Tooling

`ruff` (lint + format) and `pytest` (test runner) are the canonical
development tools. The shared `ruff.toml` at the repository root
configures both; run them from the repository root:

```bash
# Lint
ruff check mnemos-backend mnemos-frontend tests

# Auto-fix what's safe
ruff check --fix mnemos-backend mnemos-frontend tests

# Format
ruff format mnemos-backend mnemos-frontend tests

# Test (uses isolated tmpdirs, never touches your real DBs)
python3 -m pytest tests/
```

The test suite spins up both services' apps in-process with stubbed
backends. A `backend_imports` / `frontend_imports` fixture pair swaps
`sys.path` and `SQLModel.metadata` so the two `app.*` packages never
collide in the same interpreter.

### Project conventions

- Python 3.14. Use native generics (`list[int]`, `X | None`) and the
  `StrEnum` base for string-valued enumerations.
- Use `from contextlib import suppress` instead of bare
  `try/except: pass` for "best-effort" operations (close, cancel,
  rollback).
- Both services keep their own SQLite database. Don't add a cross-service
  import that touches the other's DB.
- `bcrypt` and `argon2-cffi` are imported directly; `passlib` is broken
  on 3.14 and must not be reintroduced.
- Settings come from environment variables via pydantic-settings. There
  is a `set_settings()` helper for tests; modules that hold a reference
  to the settings object should import it from `app.core.config` (which
  re-exports a proxy), not from the constructor.

## CLI

```bash
docker exec -it mnemos-backend python -m app.cli master-key view
docker exec -it mnemos-backend python -m app.cli master-key rotate
docker exec -it mnemos-backend python -m app.cli healthz --base http://mnemos-backend:8000
```

## License

See LICENSE file
