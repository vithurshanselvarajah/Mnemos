# Services Reference

A module-by-module map of the backend's `app/services/` directory — what each one does, what it owns, and how to extend it.

- [`cropper.py`](#cropperpy)
- [`engine.py`](#enginepy)
- [`model_downloader.py`](#model_downloaderpy)
- [`model_manifest.py`](#model_manifestpy)
- [`reindex.py`](#reindexpy)
- [`vector_repo.py`](#vector_repopy)
- [`websocket_hub.py`](#websocket_hubpy)

---

## `cropper.py`

Owns the on-disk JPEG for a face crop. Two operations:

### `crop_and_save_padded(bgr_image: np.ndarray, bbox, person_id: UUID | None) -> tuple[FaceCrop, str]`

- Takes the source image (BGR), the bounding box, and an optional pre-assignment.
- Pads the bbox by `MNEMOS_CROP_PAD_FRACTION` (default 50% on each side).
- Clips to image bounds.
- Encodes the cropped region as JPEG.
- Writes to `<MNEMOS_CROPS_DIR>/<uuid>.jpg`.
- Returns a `FaceCrop` row and the file path.

The padding is symmetric and clipped — a face near the edge of the source image gets extra padding on the inside only. The UUID is generated on this function call, so the file exists before the row is inserted.

### `load_crop_jpeg(rel_path: str) -> bytes`

- Reads the JPEG from `<MNEMOS_CROPS_DIR>/<rel_path>`.
- Returns the raw bytes.
- Raises `FileNotFoundError` if the file is missing — the API handler turns this into a 404.

### `delete_crop_files(rel_path: str)`

- Unlinks the file. No-op if it doesn't exist.
- Used by person-delete and the `DELETE /api/v1/persons/{id}/crops/{crop_id}` endpoint.

## `engine.py`

The public face of the inference stack. Wraps a provider-specific engine in a singleton with read/write locking.

### `class InsightFaceEngine`

- **Singleton** — `current()` returns the active instance. The instance is created lazily on first call.
- **Provider-aware** — bound to one provider (`cpu`, `nvidia`, or `rockchip`) at construction time. The provider is taken from `settings.provider` and cached.
- **Lazy load** — the inner engine is created on first call to `_ensure_inner()`. Switches to a new model clear the inner state but keep the same provider.
- **Thread-safe** — read/write lock on the inner engine. The inner engines have their own per-class locks, so switching models while a detect is in flight is safe.

#### Methods

- `warmup() -> bool` — delegates to the inner engine. Returns `True` on success, `False` on `ProviderNotAvailable`.
- `is_loaded() -> bool` — whether the inner engine has its weights in memory.
- `detect(bgr_image) -> list[Detection]` — runs the inner engine's detect.
- `switch_model(new_name)` — clears the inner engine's in-memory state, sets the new model name. The reindex is a separate operation owned by `reindex.py`.
- `active_providers() -> list[str]` — the providers actually bound to the inner engine. For NVIDIA, this is `["CUDAExecutionProvider"]` (hard-locked).
- `last_error() -> str | None` — most recent warmup/load error, or `None`.
- `model_name`, `provider_name` — properties.

#### Replacing a provider

To add a new provider (e.g. CoreML):

1. Implement the `InferenceEngine` Protocol in `app/providers/coreml/engine.py`.
2. Add a dispatch branch in `_load_provider()`.
3. Add a variant requirements file at `variants/coreml/requirements.txt`.
4. Update the multi-stage Dockerfile to handle the new variant.
5. Add a preflight check in `model_manifest.py` if the new provider has system-level requirements (driver, NPU SDK).

The rest of the backend doesn't change.

## `model_downloader.py`

Owns the download + SHA-256 verify of model artifacts from the manifest.

### `download_artifact(artifact: ModelArtifact, on_progress: callable | None = None) -> Path`

- Streams the artifact to `<MNEMOS_MODELS_ROOT>/<local_path>` using HTTP `Range` for resume.
- Calls `on_progress(done_bytes, total_bytes)` periodically. The reindex / warmup publishes WebSocket events from this callback.
- On completion, computes SHA-256 and compares to `artifact.sha256`. Mismatch → delete file, raise.

The download is interruptible: kill the process, restart, the next start resumes from where it left off.

### `variant_files_present(variant: ModelVariant) -> bool`

- True if every artifact of the variant is on disk and verified.

Used by `GET /api/v1/models/available` to show the "ready" flag for each model.

## `model_manifest.py`

Owns the manifest document, the variant selection, and the preflight checks.

### Key functions

- `_read_manifest() -> dict` — fetches the manifest with retry. In-memory cached.
- `available_models() -> list[ModelVariant]` — returns the variants applicable to the current provider.
- `variant_for(name) -> ModelVariant` — raises `KeyError` if the model is not available for the current provider.
- `preflight_provider()` — runs at backend startup. Hard-fails (`SystemExit`) if the configured provider can't run on this host. For NVIDIA: missing onnxruntime, missing CUDA EP, missing libcuda. For Rockchip: wrong architecture, unsupported SoC. For CPU: no-op.

### When to add to this file

- Adding a new model → not this file. The manifest itself lives at `MNEMOS_MANIFEST_URL`.
- Adding a new provider → add a preflight branch here.
- Changing variant selection (e.g. supporting `rknn/<soc>` for a new Rockchip chip) → update `_variants_for_provider()`.

## `reindex.py`

The state machine for model switching + reindexing.

### `state` — `ReindexState`

A process-local singleton with the following fields:

- `running: bool` — reindex in progress
- `total: int` — total crops to re-embed
- `done: int` — crops re-embedded so far
- `download_active: bool` — currently downloading an artifact
- `download_model: str | None` — model being downloaded
- `download_artifact: str | None` — artifact filename
- `download_done: int` — bytes downloaded for current artifact
- `download_total: int` — total bytes for current artifact

`snapshot() -> dict` returns a dict-shaped copy of the current state. The `GET /api/v1/models` handler builds its `ModelInfo` from this.

### Background thread

`start_reindex(name)` spawns a single background thread that runs the lifecycle described in [Architecture](https://github.com/vithurshanselvarajah/Mnemos/wiki/Architecture#request-lifecycle-warmup--reindex). The thread holds the global reindex lock; a second `start_reindex` while the first is running returns `False` (the API returns 409).

### `start_warmup(name)`

Background warmup without reindex. Used by `GET /api/v1/models/warmup` after a failed download or to pre-warm a freshly-restored backup.

### `active_model()`

Reads the `active_model` row from `system_settings`. Used by `/identify` to know which model to query embeddings under.

## `vector_repo.py`

Thin wrapper over pgvector. All SQL goes through this module.

### `search_similar(embedding, model_name, limit=3, include_per_crop=False) -> list[dict]`

- kNN over `face_embeddings` for the given model.
- Returns a list of dicts: `person_id`, `model_name`, `similarity` (1 - cosine_distance), and optionally `is_averaged` (always True for the per-person rows).
- `include_per_crop=True` includes the per-crop vectors from `face_crop_embedding` if that table is populated (currently unused but kept for future).

### `upsert_averaged(person_id, embedding, model_name)`

- INSERT ON CONFLICT DO UPDATE for `(person_id, model_name)`.
- Called from the rebuild step of the reindex, and from `_rebuild_person_averaged()` after a single-person assign.

### `delete_for_person_model(person_id, model_name)`

- DELETE the row. Called on person-delete and on model switch when the new model is empty for the person.

### `ping() -> bool`

- `SELECT 1` against pgvector. Returns False on any error. Used by the `/healthz` handler.

## `websocket_hub.py`

Process-local broadcast.

### `register(ws: WebSocket)`

- Adds the connection to the in-memory set.
- Called by `app.api.websocket.events` on connection.

### `unregister(ws: WebSocket)`

- Removes the connection.
- Called on disconnect.

### `publish(event: dict)`

- Serialises to JSON, sends to every registered connection.
- Best-effort: a failed send is logged and the connection is removed from the set. The next publish skips it.
- No ordering guarantees across processes. No replay. No filtering. If you need any of those, see [Architecture](https://github.com/vithurshanselvarajah/Mnemos/wiki/Architecture#future-work) for the Redis-backed pub/sub design.

### Why a process-local hub

Single uvicorn worker, single process, all events go to all clients. The complexity of a distributed pub/sub is not worth it for the home workload. The protocol is small enough to swap in a different implementation later without changing the public event shape.

---

## Other services

A few modules that don't fit the "service" framing but are useful to know about:

- **`app.core.security`** — API key mint / hash / find. Master key mint / read / write. Used by the API middleware and the system endpoints.
- **`app.core.middleware`** — `APIKeyAuthMiddleware`. Reads the `X-API-Key` header, validates against the DB, populates `request.state.api_key`. Also does the in-memory rate limiter.
- **`app.core.events.lifespan`** — FastAPI lifespan that warms up the engine on startup and dumps a final log line on shutdown.
- **`app.db.session`** — `init_db()`, `reset_engine()`, `session_scope()`. The single source of truth for the SQLModel engine.
- **`app.providers.base`** — `InferenceEngine` Protocol, `Detection` dataclass, `ProviderNotAvailable` exception. The contract every provider implements.
