# Models

Mnemos can run on three different detection models from the InsightFace buffalo family. The active model is persisted across restarts; switching model triggers a background reindex.

- [Available models](#available-models)
- [Get active model info](#get-active-model-info)
- [Warmup](#warmup)
- [Switch](#switch)
- [Reindex lifecycle](#reindex-lifecycle)
- [WebSocket events](#websocket-events)

---

## Available models

| Name | Speed | Accuracy | Size | Notes |
| --- | --- | --- | --- | --- |
| `buffalo_s` | Fast | Good | ~300 MB | Default. Best for real-time camera pipelines |
| `buffalo_m` | Medium | Better | ~600 MB | Balanced |
| `buffalo_l` | Slow | Best | ~1 GB | Most accurate, recommended for batch / archival |

The model is **not** included in the image — it is downloaded on first warmup from the upstream manifest. The manifest is at `MNEMOS_MANIFEST_URL` (default: the project's GitHub-hosted manifest). Each artifact has a SHA-256 that the backend verifies after download. Downloads resume across restarts via HTTP `Range`.

For the Rockchip NPU provider, the variants are different — see [Providers](https://github.com/vithurshanselvarajah/Mnemos/wiki/Providers#rockchip) and the `rknn/<soc>` entries that show up in `GET /api/v1/models/available`.

## Get active model info

```http
GET /api/v1/models
```

```bash
curl -s -H "X-API-Key: $KEY" http://localhost:8000/api/v1/models | jq
```

Returns:

```json
{
  "name": "buffalo_s",
  "loaded": true,
  "embedding_dim": 512,
  "det_size": 640,
  "reindex_in_progress": false,
  "reindex_total": 0,
  "reindex_done": 0,
  "download_active": false,
  "download_model": null,
  "download_artifact": null,
  "download_done": 0,
  "download_total": 0
}
```

- `loaded` — true when the weights are in memory and ready to embed. False during cold boot, after a failed download, or while warming up.
- `reindex_in_progress` — true while a switch is running. `reindex_done` / `reindex_total` give live progress.
- `download_active` — true while artifacts are being downloaded. `download_artifact` is the filename currently being fetched. `download_done` / `download_total` are byte counters.

## Warmup

```http
GET /api/v1/models/warmup
```

Triggers a background warmup if the model isn't already loaded. Returns immediately:

```json
{
  "name": "buffalo_s",
  "loaded": false,
  "already_loaded": false
}
```

- `loaded: true, already_loaded: true` — the model was already warm.
- `loaded: false, already_loaded: false` — a background warmup is running. Subscribe to `ws://…/ws/events` for `warmup.download` (with `artifact` filename), `warmup.done`, and `warmup.error`.

The warmup is also called automatically on backend startup. Calling it manually is useful after a failed download that you've fixed, or to pre-warm after restoring a backup.

## Switch

```http
POST /api/v1/models/switch
Content-Type: application/json
X-API-Key: <Full-Admin>

{ "name": "buffalo_l" }
```

Triggers a background switch + reindex. Returns immediately with the new `ModelInfo` and `reindex_in_progress: true`. 409 if a reindex is already running.

> The new model must be in the list returned by `GET /api/v1/models/available` for the current provider. Trying to switch to `buffalo_l` on a Rockchip host returns 400 with a list of valid options.

While the switch runs, the active model field in the database is updated atomically. The old model stays in memory until the new one is ready, so `/identify` continues to serve — but matches are made under the old model until the reindex completes.

## Reindex lifecycle

A switch goes through these steps in a single background thread:

1. **Downloading** (only if the new model isn't on disk)
   - `reindex.download` events with `artifact` filename
   - `reindex.done` byte counter on the active artifact
2. **Preparing** (`reindex.preparing` event)
   - Loading the new model into memory
   - Freeing the old model
3. **Reindexing** (`reindex.start`, `reindex.progress` events)
   - For each person:
     - Read every `ASSIGNED` crop JPEG from `/data/crops/`
     - Re-embed under the new model
     - Compute the averaged, L2-normalised vector
     - Replace the row in `face_embeddings` for `(person_id, new_model_name)`
4. **Done** (`reindex.done` event) — `/identify` now uses the new model

While the reindex runs:

- `GET /api/v1/models` shows live `reindex_done` / `reindex_total` and `reindex_in_progress: true`.
- The dashboard shows a progress bar sourced from the same values via `/partials/reindex-status`.
- Switching to a third model mid-reindex returns 409. Wait for the current one to finish.

Approximate timing on CPU:

| Crops | Reindex time |
| --- | --- |
| 100 | ~30s + download |
| 1,000 | ~2 min + download |
| 10,000 | ~15 min + download |

NVIDIA is roughly 5-10× faster. Rockchip NPU is similar to NVIDIA for the detection and recognition stages, and faster for the data-prep.

## WebSocket events

The backend publishes a steady stream of events during warmup and reindex. See [WebSocket Events](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-WebSocket) for the full schema. The relevant types are:

- `warmup.download` — `{model, artifact, done, total}`
- `warmup.done` — `{model}`
- `warmup.error` — `{model, error}`
- `reindex.preparing` — `{model}`
- `reindex.download` — `{model, artifact, done, total}`
- `reindex.start` — `{model, total}`
- `reindex.progress` — `{model, done, total}`
- `reindex.done` — `{model, total}`
- `reindex.error` — `{model, error}`

---

## For developers

### How the model is loaded

A single `InsightFaceEngine` (`app.services.engine`) lazily binds to a provider-specific engine. The provider is determined by `MNEMOS_PROVIDER` at startup and never changes without a container restart. Calling `InsightFaceEngine.current().warmup()` is what materialises the in-memory weights.

The `InsightFaceEngine` does not know about the model name — that's tracked separately in the `system_settings` table under the `active_model` key. Switching the model is a four-step operation: write the new name to `system_settings`, switch the inner engine's `model_name` (which clears the in-memory state), trigger a reindex, and update progress events.

### Why the reindex is a separate process

The reindex holds the GIL while decoding + embedding each crop. Running it in a background thread keeps `/identify` responsive (FastAPI workers can still accept new requests on the same GIL, just not in parallel with the reindex). The thread is single — there is no concurrent reindex. The `state.snapshot()` in `app.services.reindex` is the source of truth for progress.

### Why a new model is required to be in `available`

`GET /api/v1/models/available` reflects the **current provider's** view of the manifest. CPU and NVIDIA see the `standard` ONNX entries; Rockchip sees only the `rknn/<soc>` entries that match the detected SoC. Restricting the switch endpoint to the available list prevents the user from requesting a model that the current provider physically cannot run.

If you need to add a new model, the path is:

1. Add the artifact to the manifest (URL + SHA-256 + size).
2. Tag a new release of the model weights.
3. Wait for the next Mnemos release that knows about the new entry.
