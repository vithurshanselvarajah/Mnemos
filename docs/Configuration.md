# Configuration

All Mnemos configuration is done through environment variables. There is no `.env` file by default (the production compose file expects to be configured by the user before `up -d`), and no in-app settings UI for runtime knobs. Set the variables, restart the container, done.

- [Secrets](#secrets)
- [Backend environment variables](#backend-environment-variables)
- [Frontend environment variables](#frontend-environment-variables)
- [Where to set them](#where-to-set-them)
- [How settings are loaded](#how-settings-are-loaded)

---

## Secrets

These are the only ones you absolutely must change before exposing Mnemos to anything beyond localhost.

| Variable | Where | Purpose |
| --- | --- | --- |
| `MNEMOS_PG_PASSWORD` | Backend + pgvector | PostgreSQL password for the pgvector database. Used by both pgvector itself and the backend's `MNEMOS_VECTOR_DSN`. Pick something long and random. |
| `MNEMOS_FE_SECRET` | Frontend | Session-cookie signing key. **Must be at least 32 random bytes.** Generate with `openssl rand -hex 32`. Rotating it logs everyone out. |
| Master pairing key | Backend (auto-generated) | A one-time secret the backend mints on first boot and stores in its own SQLite volume. Read it with `docker exec -it mnemos-backend python -m app.cli master-key view` and paste it into the onboarding wizard. It is not settable via env on purpose — the whole point is that nobody else ever sees it. |

> Mnemos's API keys (`mnemos_k_…`) and the master key (`mnemos_master_…`) live in `backend.db` and never appear in any env file.

---

## Backend environment variables

All are prefixed `MNEMOS_`. Defaults are shown — only override if you have a reason.

### Storage

| Variable | Default | Purpose |
| --- | --- | --- |
| `MNEMOS_DB_PATH` | `/data/backend.db` | SQLite file for persons, crops, API keys, master key, reindex state. |
| `MNEMOS_CROPS_DIR` | `/data/crops` | Directory where cropped face JPEGs are stored. |
| `MNEMOS_BACKUP_DIR` | `/data/backups` | Where generated `.tar.gz` backups are stored. Created on first use. |
| `MNEMOS_VECTOR_DSN` | `postgresql://mnemos:mnemos@localhost:5432/mnemos_vectors` | pgvector DSN. The compose file injects the password from `MNEMOS_PG_PASSWORD`. |

### Inference

| Variable | Default | Purpose |
| --- | --- | --- |
| `MNEMOS_PROVIDER` | `cpu` | One of `cpu`, `nvidia`, `rockchip`. Controls which image tag is pulled and which onnxruntime variant is loaded. See [Providers](https://github.com/vithurshanselvarajah/Mnemos/wiki/Providers). |
| `MNEMOS_DEFAULT_MODEL` | `buffalo_s` | One of `buffalo_s` (fast), `buffalo_m` (balanced), `buffalo_l` (accurate, ~3× slower). Can be changed at runtime from the Models page. |
| `MNEMOS_DET_SIZE` | `640` | Detector input side length in pixels. Larger is more accurate on small faces but slower. |
| `MNEMOS_DEFAULT_THRESHOLD` | `0.40` | Cosine distance below which a face counts as recognised (i.e. ≥ 60% similarity). Lower is stricter. Per-person overrides are available. |
| `MNEMOS_MIN_FACE_PX` | `30` | Detections smaller than this on either side are dropped before matching. |
| `MNEMOS_CROP_PAD_FRACTION` | `0.50` | Extra padding around the bounding box when saving unknown crops (as a fraction of bbox size). |
| `MNEMOS_EMBEDDING_DIM` | `512` | Embedding dimensionality. Buffalo models produce 512-D vectors; this is used for pgvector column definition. |

### Model manifest / downloads

| Variable | Default | Purpose |
| --- | --- | --- |
| `MNEMOS_MANIFEST_URL` | (GitHub) | URL of the manifest JSON that lists model artifact URLs and SHA-256s. Override to host a private mirror. |
| `MNEMOS_MANIFEST_FETCH_TIMEOUT_S` | `10` | HTTP timeout (seconds) for fetching the manifest. |
| `MNEMOS_DOWNLOAD_TIMEOUT_S` | `120` | Per-artifact HTTP timeout (seconds) for downloading model weights. |
| `MNEMOS_MODELS_ROOT` | `/data/models` | Directory where downloaded weights are stored. |

### Rockchip only

| Variable | Default | Purpose |
| --- | --- | --- |
| `MNEMOS_ROCKCHIP_SOC` | (auto-detect) | Force a specific SoC. Otherwise read from `/proc/device-tree/compatible`. |

### API server

| Variable | Default | Purpose |
| --- | --- | --- |
| `MNEMOS_API_HOST` | `0.0.0.0` | Listen address. Inside the compose network the backend binds to all interfaces. |
| `MNEMOS_API_PORT` | `8000` | Listen port. |
| `MNEMOS_CORS_ORIGINS` | `*` | Comma-separated list of allowed origins for the browser-based Swagger UI and any direct browser clients. The default `*` is fine for a local install; tighten for production. |

### Security

| Variable | Default | Purpose |
| --- | --- | --- |
| `MNEMOS_MASTER_KEY_PREFIX` | `mnemos_master_` | Prefix for the auto-generated master pairing key. Change only if you want the prefix to identify your deployment. |

---

## Frontend environment variables

All are prefixed `MNEMOS_FE_`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `MNEMOS_FE_DB_PATH` | `/data/frontend.db` | SQLite file for users, sessions, audit log. |
| `MNEMOS_FE_SESSION_HOURS` | `8` | Session cookie lifetime for active sessions in hours. |
| `MNEMOS_FE_REMEMBER_DAYS` | `30` | Lifetime of the "remember me" cookie in days. |
| `MNEMOS_FE_DEFAULT_BACKEND_URL` | `http://mnemos-backend:8000` | Where the frontend finds the backend. Inside the compose network this is the service name. Outside, point to `http://<host>:8000`. |
| `MNEMOS_FE_LISTEN_HOST` | `0.0.0.0` | Listen address for the frontend's uvicorn. |
| `MNEMOS_FE_LISTEN_PORT` | `8080` | Listen port for the frontend. |
| `MNEMOS_FE_SECRET` | (required) | Session cookie signing key. **Must be at least 32 bytes.** |
| `MNEMOS_FE_BACKUP_DIR` | `<MNEMOS_FE_DB_PATH parent>/backups/` | Where the frontend caches uploaded backup files. |

---

## Backup schedule (SQLite, not env)

The auto-backup schedule lives in the `backup_settings` table in the frontend SQLite. Configure it from the UI at **Settings → Backup & restore → Auto-backup schedule**. Fields:

| Field | Default | Notes |
| --- | --- | --- |
| `enabled` | `false` | Master switch. |
| `cadence` | `daily` | `daily` or `weekly`. |
| `hour_utc` | `3` | 0–23, when the scheduler runs. |
| `weekday_utc` | `0` | 0=Mon … 6=Sun. Used only when `cadence=weekly`. |
| `retention_count` | `7` | Keep the N most recent; older backups are deleted after each create. |

There is no environment variable for these — they're runtime configuration that the user changes from the UI.

---

## Where to set them

### Prebuilt install

In `.env` next to `docker-compose.yml`. Docker Compose interpolates the file automatically.

### Dev install

`docker-compose.dev.yml` reads the same `.env` file. For one-off overrides:

```bash
MNEMOS_TAG=dev MNEMOS_PROVIDER=nvidia docker compose -f docker-compose.dev.yml up --build
```

### Bare-metal (no Docker)

Export them in your shell, or use a process supervisor that injects env. See [Architecture](https://github.com/vithurshanselvarajah/Mnemos/wiki/Architecture) for the env var contract the pydantic-settings classes expect.

---

## How settings are loaded

Backend uses pydantic-settings. Each `MNEMOS_*` env var maps to a field on `app.core.config.Settings` (defined in [code](https://github.com/vithurshanselvarajah/Mnemos)). Defaults are applied if the var is missing. The active `Settings` instance is exposed through a module-level proxy (`from app.core.config import settings`) so tests can swap it without re-importing.

Frontend uses the same pattern (`app.core.config.settings`) but with the `MNEMOS_FE_*` prefix.

If you add a new setting, you must:

1. Add the field to the right `Settings` class with a default.
2. Use it through the proxy, never by `os.getenv()` directly.
3. Document it on this page.

There is no `.env` loader; environment variables are the only source.
