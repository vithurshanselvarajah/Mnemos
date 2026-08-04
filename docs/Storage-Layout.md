# Storage Layout

Mnemos stores state in four places. This page describes each one, what's in it, and how to inspect / back it up.

- [At a glance](#at-a-glance)
- [Backend SQLite: `backend.db`](#backend-sqlite-backenddb)
- [Frontend SQLite: `frontend.db`](#frontend-sqlite-frontenddb)
- [PostgreSQL + pgvector: `vector-db`](#postgresql--pgvector-vector-db)
- [Crop JPEGs: `crops/`](#crop-jpegs-crops)
- [Model weights: `models/`](#model-weights-models)
- [Inspected via the CLI](#inspected-via-the-cli)

---

## At a glance

| Store | Where | What's in it | Default size |
| --- | --- | --- | --- |
| `backend.db` | `mnemos/backend/backend.db` | Persons, face crops metadata, API keys, master key, system settings | < 1 MB even with 10k persons |
| `frontend.db` | `mnemos/frontend/frontend.db` | Users, sessions, audit log, backup settings | < 1 MB |
| pgvector | `mnemos/vector-db/` | 512-D embeddings per (person, model) | ~1 MB per 1k persons per model |
| `crops/` | `mnemos/backend/crops/` | Cropped face JPEGs | ~50 KB each |
| `models/` | `mnemos/backend/models/` | Downloaded ONNX/RKNN weights | 300 MB - 1 GB per model |
| `backups/` | `mnemos/backend/backups/` | Generated `.tar.gz` snapshots of the system (see [Backup & Restore](Backup-Restore.md)) | Grows with `retention_count` × backup size |

The host paths are created by the default compose file's bind mounts. The in-container paths are `/data/backend.db`, `/data/frontend.db`, `/var/lib/postgresql`, `/data/crops`, `/data/models`.

## Backend SQLite: `backend.db`

`backend.db` is the relational store for everything except embeddings. Tables:

- **`person`** — the people Mnemos knows
- **`facecrop`** — every detected face
- **`apikey`** — API keys (hashed, never raw)
- **`systemsetting`** — key/value store; the master key and the active model name live here

### `person`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID | Primary key |
| `name` | TEXT | Case-insensitively unique |
| `custom_threshold` | FLOAT NULL | Per-person cosine distance threshold |
| `created_at` | DATETIME | UTC |
| `updated_at` | DATETIME | UTC, bumped on any change |

### `facecrop`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID | Primary key |
| `person_id` | UUID NULL | FK to `person.id`, NULL for unassigned |
| `file_path` | TEXT | Relative to `MNEMOS_CROPS_DIR` |
| `image_sha` | TEXT NULL | SHA-256 of the source image; used for cross-request dedup |
| `bounding_box` | TEXT | JSON `[x1, y1, x2, y2]` in source image pixel coords |
| `det_score` | FLOAT | Detector confidence 0-1 |
| `status` | TEXT | `UNASSIGNED` / `ASSIGNED` / `NON_FACE` / `IGNORED` |
| `created_at` | DATETIME | UTC |

Indexes:
- `facecrop.status` — drives the inbox listing
- `facecrop.image_sha` — drives the cross-request dedup
- `facecrop.person_id` — drives person-detail listing

### `apikey`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID | Primary key |
| `name` | TEXT | Display label |
| `key_hash` | TEXT | HMAC-SHA-256, never the raw key |
| `key_prefix` | TEXT | First 8 chars of the raw key (display only) |
| `permission_level` | TEXT | `Identify-Only` or `Full-Admin` |
| `expires_at` | DATETIME NULL | When the key stops working |
| `revoked_at` | DATETIME NULL | When the key was revoked |
| `created_at` | DATETIME | UTC |

### `systemsetting`

| Key | Value | Notes |
| --- | --- | --- |
| `master_key` | `mnemos_master_…` | One-time bootstrap secret |
| `active_model` | `buffalo_s` / `buffalo_m` / `buffalo_l` | The current detection model |

The table is a free-form key/value store; you can add more settings if needed (e.g. to persist a future global config).

## Frontend SQLite: `frontend.db`

Holds everything the browser-facing app needs to remember:

- **`user`** — admin users, Argon2id-hashed passwords
- **`session`** — server-side session store (the cookie is a session ID, not the data)
- **`apikey_credential`** — the encrypted Full-Admin API key the frontend uses to talk to the backend
- **`audit_log`** — login / logout / key rotation events

The `apikey_credential` row is encrypted at rest with a key derived from `MNEMOS_FE_SECRET`. The raw API key never appears in the database unencrypted.

## PostgreSQL + pgvector: `vector-db`

Single database `mnemos_vectors`, single table:

```sql
CREATE TABLE face_embeddings (
  person_id    UUID NOT NULL,
  model_name   TEXT NOT NULL,
  embedding    vector(512) NOT NULL,    -- pgvector type
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (person_id, model_name)
);

CREATE INDEX face_embeddings_embedding_hnsw
  ON face_embeddings USING hnsw (embedding vector_cosine_ops);
```

The primary key is `(person_id, model_name)` — one row per person per model. The HNSW index is built at first insert and updated incrementally.

The `vector(512)` column uses the cosine distance operator (`<=>`). On a 10k-person gallery with 512-D vectors, a single kNN query is sub-millisecond on commodity hardware.

### Extensions

The `pgvector-init/01-extensions.sql` runs `CREATE EXTENSION IF NOT EXISTS vector;` on first start. If you restore a logical dump (`pg_dumpall`) into a fresh cluster, the extension is recreated by the same init script on first start.

## Crop JPEGs: `crops/`

A flat directory of JPEGs, one per face crop. The filename is the crop's UUID with a `.jpg` suffix:

```
7c4a8d09-ca38-4e2e-b27a-2c0e6a2c5e1f.jpg
```

The relative path is stored in `facecrop.file_path`. The absolute path is `<MNEMOS_CROPS_DIR>/<file_path>`. Inside the container, the host directory is bind-mounted to `/data` (see [Architecture](https://github.com/vithurshanselvarajah/Mnemos/wiki/Architecture)).

Crops are written once and never rewritten. They are deleted when the corresponding `facecrop` row is hard-deleted (currently a `DELETE /api/v1/persons/{id}/crops/{crop_id}` is the only way to trigger this). Person-deletion returns the crops to the inbox but keeps the JPEGs on disk.

## Model weights: `models/`

Downloaded from the upstream manifest (see [Model Manifest](https://github.com/vithurshanselvarajah/Mnemos/wiki/Model-Manifest)). Layout:

```
models/
└── standard/
    ├── buffalo_s/
    │   ├── detection/
    │   │   └── det.onnx          (the file is the artifact `path` from the manifest)
    │   └── recognition/
    │       └── rec.onnx
    ├── buffalo_m/…
    └── buffalo_l/…
```

For Rockchip, the path is `rknn/<soc>/<model_name>/<detection|recognition>/…` and the file extension is `.rknn`.

Files are written via `Range` requests, so an interrupted download resumes where it left off. After completion, the SHA-256 is verified against the manifest. If it doesn't match, the file is deleted and the download is retried on the next warmup.

## Inspected via the CLI

```bash
# Master key
docker exec -it mnemos-backend python -m app.cli master-key view

# Persons
docker exec -it mnemos-backend sqlite3 /data/backend.db "SELECT id, name FROM person;"

# Inbox count
docker exec -it mnemos-backend sqlite3 /data/backend.db \
  "SELECT COUNT(*) FROM facecrop WHERE status = 'UNASSIGNED';"

# Crop on disk
docker exec -it mnemos-backend ls -la /data/crops/ | head

# Active model
docker exec -it mnemos-backend sqlite3 /data/backend.db \
  "SELECT value FROM systemsetting WHERE key = 'active_model';"
```

---

## For developers

### Why two SQLite databases

The frontend and backend are independent services. They could share a database, but the current design (one SQLite per service) means each can be restarted, scaled, and backed up independently. The trade-off is that the API key has to be passed across the trust boundary, which is solved by encrypting it at rest in the frontend.

### Why one row per person per model

Alternative: one row per crop in pgvector, then aggregate in SQL. That's slower (more rows, more index size, more kNN work per query) and doesn't change the matching algorithm (we still want one vector per person per model). The averaged-row design is a deliberate optimisation for the read path at the cost of more work on the write path (rebuild on every assignment).

### Why a flat `crops/` directory

Sharding by date or hash would help at very large scale, but for the home workload (a few thousand crops) a flat directory is the simplest thing that works. The lookup is `os.path.join(crops_dir, file_path)` — O(1) on every filesystem.

### Backup consistency

SQLite is in WAL mode by default, which means a `cp` of `backend.db` while the process is running is safe — you'll get the most recent committed state. PostgreSQL is more particular: a `pg_basebackup` while the cluster is running is safe; a `cp -r` of the PGDATA directory is not. The backup script in [Backup & Restore](https://github.com/vithurshanselvarajah/Mnemos/wiki/Backup-Restore) handles both correctly.
