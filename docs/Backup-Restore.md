# Backup & Restore

Mnemos is fully self-hosted. There is no cloud service, no remote state. The recommended way to back up is from the **Settings → Backup & restore** page in the web UI. The CLI / shell recipes at the bottom of this page are still available for scripting and for hot/cold snapshots outside the UI.

- [Using the UI](#using-the-ui)
- [What's in a backup](#whats-in-a-backup)
- [What NOT to back up](#what-not-to-back-up)
- [Restore flow & re-pairing](#restore-flow--re-pairing)
- [Auto-backup scheduler](#auto-backup-scheduler)
- [Backup & restore API](#backup--restore-api)
- [CLI: `python -m app.cli backup …`](#cli-python--m-appcli-backup-)
- [Manual / advanced](#manual--advanced)
- [Migrating to a new host](#migrating-to-a-new-host)

---

## Using the UI

Open **Settings → Backup & restore** (Admin menu → Backup & restore). From there you can:

| Action | What it does |
| --- | --- |
| **Create backup now** | Bundles the backend SQLite, crop JPEGs, the pgvector SQL dump, and the frontend SQLite into a single `.tar.gz` stored under `mnemos/backend/backups/`. |
| **Download** | Streams the `.tar.gz` with a stable filename and an `X-Backup-SHA256` header. |
| **Delete** | Removes the backup file from disk. |
| **Upload** | Brings an existing `.tar.gz` back into the manager so it can be restored. |
| **Restore (per row)** | Each backup in the list has its own inline confirm form. Submitting starts a background restore and polls the status into the same row. When the restore finishes the UI runs an automatic **pairing check** — if the stored API key still works against the restored backend, you stay signed in; if the backend's master key is different (for example the backup came from a different installation) the UI sends you back through the pairing flow. |
| **Auto-backup schedule** | Daily or weekly cadence, retention count, and the hour (UTC) the scheduler runs at. Backed by a row in the frontend SQLite. |

### Where backups live

`./mnemos/backend/backups/` on the host (bind-mounted to `/data/backups/` in the backend container). The directory is created automatically on first use.

### Naming convention

Backups are named `mnemos-backup-YYYYMMDD-HHMMSS.tar.gz`. The UI and CLI both refuse to operate on files that don't match this pattern.

---

## What's in a backup

A backup is a single gzipped tarball with this layout:

```
manifest.json        # version, app version, timestamp, sha256 of every part
backend.db           # sqlite3 .backup of /data/backend.db
crops.tar            # tar of /data/crops
pg.sql               # pg_dumpall output for the vector database
frontend.db          # (optional) sqlite3 .backup of the frontend DB
```

The manifest is the source of truth for the restorer's integrity checks. Every restore verifies the `backend_db_sha` against the file it just wrote.

## What NOT to back up

- The Docker images themselves (`docker images`) — pull them again from GHCR.
- The model weights under `/data/models` — re-downloaded from the manifest.
- Log streams (JSON to stdout) — your logging stack already captures them.
- The `.env` file — secrets are not bundled. Restore `.env` manually after a restore.

---

## Restore flow & re-pairing

A restore is destructive: it overwrites the backend SQLite, replaces the crop directory, drops and recreates the `public` schema in pgvector, and (optionally) replaces the frontend SQLite. Because the backend's master key is derived from the values in `.env` at first run, restoring a backup on a host with a different `.env` produces a backend whose master key no longer matches the one the frontend encrypted its API key against.

The UI handles this with a **conditional re-pair check**:

1. The restore job runs to completion on the backend (`status: done`).
2. The UI automatically issues `GET /api/v1/backup` against the freshly-restored backend using the locally-stored API key — a lightweight, idempotent read.
3. **If the request succeeds (200)** the pairing is still valid, the model re-warms in the background, and the UI shows "Restore complete and pairing still valid." No re-pairing required.
4. **If the request returns 401/403 (or the backend is unreachable)** the UI shows the re-pairing screen and walks you through `/api/v1/system/pair` with the master key from `.env`. The previous API key is discarded.

When you restore on the same host with the same `.env` (the common case) the pairing check succeeds and you stay logged in. When you restore across hosts or after rotating `.env`, expect the re-pairing step.

> The bundling/restore logic never touches `.env` or any secret store directly. If you want a guaranteed-clean restore, treat `.env` as a separate artifact and place it on disk before launching the stack.

---

## Auto-backup scheduler

Stored in the `backup_settings` table in the frontend SQLite. One row total. Fields:

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `enabled` | bool | false | |
| `cadence` | str | `daily` | `daily` or `weekly` |
| `hour_utc` | int | 3 | 0–23, when the scheduler runs |
| `weekday_utc` | int | 0 | 0=Mon … 6=Sun, used only when `cadence=weekly` |
| `retention_count` | int | 7 | keep the N most recent (1–365); older backups are deleted |
| `next_run_at` | datetime | None | Set by the scheduler when it computes the next due time |
| `updated_at` | datetime | now | Refreshed on every settings PUT |

The scheduler runs in the frontend's FastAPI lifespan. It wakes up at most every 60 seconds, checks the schedule, and asks the backend to create a backup when due. After each create, the most recent `retention_count` backups are kept on both the backend (`/data/backups`) and the local frontend cache.

> The scheduler is best-effort: it only runs while the frontend container is up. If the frontend is down at the scheduled hour, that backup is skipped.

---

## Backup & restore API

The backend exposes a small set of admin-only endpoints under `/api/v1/backup`:

| Method | Path | Body | Notes |
| --- | --- | --- | --- |
| `GET` | `/api/v1/backup` | – | List backups + disk free bytes |
| `POST` | `/api/v1/backup` | – | Create a new backup. 201 with `{filename, size_bytes}` |
| `GET` | `/api/v1/backup/{filename}/inspect` | – | Manifest + sha256 |
| `GET` | `/api/v1/backup/{filename}/download` | – | Streamed `.tar.gz` |
| `DELETE` | `/api/v1/backup/{filename}` | – | Delete |
| `POST` | `/api/v1/backup/restore` | `{filename, confirm: true}` | 202 with `{id, status, …}` |
| `GET` | `/api/v1/backup/restore/{job_id}` | – | Poll restore job |

All require a `Full-Admin` API key. Filenames must match `mnemos-backup-\d{8}-\d{6}\.tar\.gz`. Restore is destructive and runs as a background thread; the UI polls the status endpoint.

---

## CLI: `python -m app.cli backup …`

The backend also ships a CLI for scripts:

```bash
docker exec -it mnemos-backend python -m app.cli backup list
docker exec -it mnemos-backend python -m app.cli backup create
docker exec -it mnemos-backend python -m app.cli backup inspect <filename.tar.gz>
docker exec -it mnemos-backend python -m app.cli backup restore <filename.tar.gz>
docker exec -it mnemos-backend python -m app.cli backup delete <filename.tar.gz>
```

Set `MNEMOS_BACKUP_DIR` (default `/data/backups`) to change the storage location. `create` accepts `--out <path>` and `--frontend-db <path>` to bundle the frontend SQLite.

---

## Manual / advanced

The same targets are still on disk. A `tar` snapshot of the host directories is still enough for a home install.

### Cold snapshot (no downtime impact)

```bash
docker compose down
tar -czf mnemos-backup-$(date +%F).tar.gz ./mnemos/
docker compose up -d
```

### Hot snapshot (no downtime)

```bash
# Backend SQLite
docker exec mnemos-backend sqlite3 /data/backend.db ".backup /data/backups/manual.db"
cp ./mnemos/backend/backups/manual.db ./mnemos/backend/manual-backend.db

# pgvector
docker exec mnemos-vector-db pg_dumpall -U mnemos > mnemos-pg-$(date +%F).sql

# Frontend SQLite
docker exec mnemos-frontend sqlite3 /data/frontend.db ".backup /data/manual-fe.db"
cp ./mnemos/frontend/manual-fe.db ./mnemos/frontend/manual-frontend.db

# Crops
tar -czf mnemos-crops-$(date +%F).tar.gz ./mnemos/backend/crops/
```

### Manual restore

```bash
docker compose down
rm -rf ./mnemos
tar -xzf mnemos-backup-2026-07-25.tar.gz
docker compose up -d
```

> Restoring pgvector only is more involved: drop the existing cluster first, then replay the SQL dump. See [Storage Layout](Storage-Layout.md).

---

## Migrating to a new host

1. On the old host: create a backup from the UI, download the `.tar.gz`, and also save the `.env` separately (it is not bundled).
2. Copy the tarball + `.env` to the new host.
3. Install Docker, follow [Quick Start](Quick-Start.md) but **don't** run `up -d` yet.
4. Place `.env` in the install dir, then drop the tarball into `mnemos/backend/backups/`.
5. From the UI, restore the backup. The new host takes over with the same admin users, the same known people, and the same embeddings.

Because the master key is derived from `.env` on first run, moving the backup to a host with an identical `.env` keeps the pairing intact and the UI shows "Restore complete and pairing still valid." If `.env` differs (or only the backend SQLite was restored without the bundled frontend SQLite), the UI detects the 401 from the pairing check and routes you through the re-pairing flow automatically — see [Restore flow & re-pairing](#restore-flow--re-pairing).
