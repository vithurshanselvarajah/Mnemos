# Backup & Restore

Mnemos is fully self-hosted. There is no cloud service, no remote state. A complete backup is just a copy of two host directories.

- [What to back up](#what-to-back-up)
- [What NOT to back up](#what-not-to-back-up)
- [Backup strategy](#backup-strategy)
- [Restoring](#restoring)
- [Migrating to a new host](#migrating-to-a-new-host)

---

## What to back up

Two host directories created on first run by the compose stack. Both live under the directory you ran `docker compose up` from:

| Path | Contents | Why it matters |
| --- | --- | --- |
| `./mnemos/backend/` | `backend.db` (SQLite: persons, crops metadata, API keys, master key, system settings) and `crops/` (JPEG files) | This is everything Mnemos has learned. |
| `./mnemos/frontend/` | `frontend.db` (SQLite: users, sessions, audit log) | Your admin login and any session cookies live here. |
| `./mnemos/vector-db/` | PostgreSQL data directory (pgvector) | The 512-D embeddings for every person under every model. |

Optional but recommended:

- Your `.env` (secrets — pg password, frontend session secret)
- Any custom `manifest.json` if you mirror the model artifacts privately

> The PostgreSQL data directory must be backed up while Postgres is running and consistent, or shut down cleanly. Backing up the raw PGDATA directory on a running cluster without `pg_basebackup` may produce a torn write.

---

## What NOT to back up

- The Docker images themselves (`docker images` output) — pull them again from GHCR.
- The model weights under `/data/models` inside the backend container — these are re-downloaded from the manifest. Backing them up is fine but unnecessary unless you have a slow connection and a paranoid streak.
- Any logs — they're in JSON to stdout and your logging stack should already be capturing them.

---

## Backup strategy

The default compose file uses Docker named volumes mounted into `./mnemos/*` on the host. A simple `tar` snapshot is enough for a home install.

### Manual snapshot

```bash
# Stop the stack so the SQLite files are quiescent
docker compose down

# Snapshot the data
tar -czf mnemos-backup-$(date +%F).tar.gz ./mnemos/ ./.env

# Bring it back up
docker compose up -d
```

The downtime is the time it takes `tar` to run, typically seconds. SQLite is durable across hard kills, but stopping the stack is the safe option.

### Hot snapshot (no downtime)

If you can't tolerate the restart:

```bash
# SQLite: ask it to checkpoint + copy
docker exec mnemos-backend sqlite3 /data/backend.db ".backup /data/backup/backend.db"
cp ./mnemos/backend/backup/backend.db ./mnemos/backend/backend.db.snapshot
rm -rf ./mnemos/backend/backup

# PostgreSQL: use pg_basebackup or pg_dump
docker exec mnemos-vector-db pg_dumpall -U mnemos > mnemos-pg-$(date +%F).sql
```

The hot snapshot is a few seconds behind the live database, but acceptable for most use cases.

### Automated snapshots

Any host-level tool works (cron + `tar`, restic, borg, kopia, …). One-line cron:

```cron
0 3 * * *  cd /opt/mnemos && docker compose stop backend frontend && tar -czf /backups/mnemos-$(date +\%F).tar.gz ./mnemos/ ./.env && docker compose start backend frontend
```

---

## Restoring

Stop the stack, replace the data, restart:

```bash
docker compose down
rm -rf ./mnemos
tar -xzf mnemos-backup-2026-07-25.tar.gz
docker compose up -d
```

The backend will pick up the existing `backend.db` and the existing `master_key` row. The frontend will resume serving the existing admin session. No re-onboarding needed.

### Restoring into a different Docker Compose project

If you've changed the project name (`-p mnemos-test`), the volume names will differ. The data on disk is path-based (the compose file uses bind mounts) so restoring from a host path works regardless of the project name.

### Restoring pgvector only

```bash
# Drop the existing cluster and restore
docker compose down mnemos-vector-db
rm -rf ./mnemos/vector-db
docker compose up -d mnemos-vector-db
# Wait for the init scripts to run (creates the pgvector extension)
docker exec -i mnemos-vector-db psql -U mnemos -d mnemos_vectors < mnemos-pg-2026-07-25.sql
docker compose up -d
```

If only the vector DB is restored, the persons and crops are still there but the averaged embeddings will be missing. The next `/identify` call will rebuild them on demand from the crops, but it will be slow for the first hour. To force an immediate rebuild, trigger a reindex (`POST /api/v1/models/switch {"name": "buffalo_s"}`).

---

## Migrating to a new host

1. On the old host: take a backup as above.
2. Copy the tarball to the new host (scp, rsync, USB stick, whatever).
3. On the new host: install Docker, follow [Quick Start](https://github.com/vithurshanselvarajah/Mnemos/wiki/Quick-Start) but **don't** run `up -d` yet.
4. Replace the freshly-created `./mnemos/` and `.env` with the ones from the backup.
5. `docker compose up -d`.

The new host takes over with the same admin users, the same known people, and the same embeddings. The master key is the same, the API keys are the same, the model state is the same. No re-pairing.

---

## For developers

### SQLite-on-host instead of in-container

The compose file binds `./mnemos/backend` to `/data` inside the container. This is intentional: it means a `docker volume ls` and prune is safe, and the data is on a filesystem the operator already has backup tooling for. The trade-off is that file permissions need to be readable by the container's UID — the images run as non-root, so make sure the host directory is `chmod -R o+rX`.

### pgvector resilience

PostgreSQL is much pickier than SQLite about being backed up while running. The official recipe is `pg_basebackup` for a physical copy or `pg_dumpall` for a logical copy. The compose file's `/docker-entrypoint-initdb.d/01-extensions.sql` runs `CREATE EXTENSION IF NOT EXISTS vector;` so a fresh cluster is functional as soon as Postgres is up.

If you restore only the logical dump and not the physical PGDATA, you must also drop the existing cluster first — restoring a logical dump on top of an existing PGDATA with the same DB name will conflict.
