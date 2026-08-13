# Health & Versioning

Mnemos exposes two `/healthz` endpoints — one on the backend (`http://<host>:8000/healthz`) and one on the frontend (`http://<host>:8080/healthz`). Both return JSON. The frontend's response includes the backend's response so a single `curl` shows the state of the whole stack.

- [Backend /healthz](#backend-healthz)
- [Frontend /healthz](#frontend-healthz)
- [Status values](#status-values)
- [Versioning](#versioning)

---

## Backend /healthz

```http
GET /healthz
```

No auth required. Always returns 200 — the response body tells you whether everything is healthy.

```json
{
  "status": "ok",
  "version": "0.1.0",
  "model": "buffalo_s",
  "model_loaded": true,
  "db": true,
  "vector_db": true,
  "reindex_in_progress": false,
  "reindex_done": 0,
  "reindex_total": 0,
  "provider": "nvidia",
  "rockchip_soc": null,
  "nvidia": {
    "onnxruntime_available": true,
    "cuda_available": true,
    "device_count": 1,
    "available_providers": ["CUDAExecutionProvider", "CPUExecutionProvider"],
    "active_providers": ["CUDAExecutionProvider"],
    "last_error": null
  }
}
```

### Field reference

| Field | Type | Meaning |
| --- | --- | --- |
| `status` | string | `"ok"` if DB, vector DB, and model are all healthy. `"degraded"` otherwise |
| `version` | string | Backend version, from the `VERSION` file at the repo root |
| `model` | string \| null | The active model name (e.g. `buffalo_s`), or `null` if unset |
| `model_loaded` | bool | True when the weights are in memory and ready to embed |
| `db` | bool | True if the local SQLite database is reachable |
| `vector_db` | bool | True if pgvector is reachable |
| `reindex_in_progress` | bool | True while a switch-and-reindex is running |
| `reindex_done` | int | Crops re-embedded so far in the current reindex |
| `reindex_total` | int | Total crops to re-embed (0 when idle) |
| `provider` | string | The active inference provider: `cpu`, `nvidia`, or `rockchip` |
| `rockchip_soc` | string \| null | Detected (or overridden) Rockchip SoC. `null` when provider is not Rockchip |
| `nvidia` | object \| null | NVIDIA / CUDA state. `null` when provider is not NVIDIA. See below |

### `nvidia` object (only on `provider=="nvidia"`)

| Field | Type | Meaning |
| --- | --- | --- |
| `onnxruntime_available` | bool | True when the `onnxruntime` package imported successfully |
| `cuda_available` | bool | True when onnxruntime reports `CUDAExecutionProvider` is available |
| `device_count` | int | Number of NVIDIA GPUs that successfully loaded `libcuda` at boot |
| `available_providers` | string[] | All execution providers onnxruntime sees |
| `active_providers` | string[] | The providers actually bound to the running engine. For NVIDIA this is **always exactly `["CUDAExecutionProvider"]`** — the engine is hard-locked and never falls back to CPU |
| `last_error` | string \| null | The most recent CUDA-side error, or `null` if healthy |

> If `nvidia.cuda_available` is `false` or `nvidia.last_error` is set, the backend is unhealthy and `/identify` will return 503.

## Frontend /healthz

```http
GET /healthz
```

No auth required. Proxies the backend's `/healthz` and adds a few frontend fields:

```json
{
  "status": "ok",
  "version": "0.1.0",
  "backend_reachable": true,
  "backend": { /* full backend /healthz payload */ }
}
```

- `backend_reachable` — false if the frontend couldn't reach the backend at all (network error, wrong URL, backend down). When false, `backend` is `null`.
- `backend` — the entire backend `/healthz` response, or `null` if unreachable.

The frontend itself is always considered healthy as long as it can serve a response (it has no in-process state to check).

## Status values

| Value | Meaning | Action |
| --- | --- | --- |
| `"ok"` | DB, vector DB, and model all healthy | None — everything is working |
| `"degraded"` | At least one of the above is unhealthy | Check `db`, `vector_db`, `model_loaded`, `nvidia.last_error` (if applicable) |

The HTTP status code is always 200. The `status` field is the source of truth for liveness.

If you want a strict liveness probe (e.g. for Kubernetes), you have two options:

1. Use a custom probe that runs the JSON query and checks `status == "ok"`.
2. Wait for the `/healthz` to also return a non-200 code on failure (currently not implemented; tracked as a future enhancement).

## Versioning

The `version` field is read from the `VERSION` file at the repository root and baked into the image at build time. The frontend and backend each carry their own copy.

The format is plain semver: `MAJOR.MINOR.PATCH`. There is no build metadata. The current version is also rendered in the OpenAPI schema (`/openapi.json` → `info.version`) and the FastAPI app title.

Use `version` in your monitoring to detect when deployments have rolled out successfully.

---

## For developers

### Why no non-200 on degraded

The container orchestrator's healthcheck (Docker, Kubernetes, …) interprets a non-2xx HTTP code as "restart me." For Mnemos, the right response to a temporarily-unhealthy dependency is *not* to restart the container — it would just get unhealthy again on the next start. The current design is "report the state, let the operator decide."

If you want restart-on-degraded behaviour, wrap `/healthz` in a script:

```bash
status=$(curl -sf http://localhost:8000/healthz | jq -r .status)
[ "$status" = "ok" ]
```

### Why the frontend proxies the backend's health

The frontend exists to give a UI to the backend. If the backend is unhealthy, the UI is useless. The frontend's `/healthz` collapses "is the stack working?" into a single call so monitoring can do `curl http://<frontend>/healthz` and be done. The `backend_reachable` flag surfaces the network-layer failure mode separately from the backend's own internal status.

### Why the `nvidia` object is verbose

A simple `"gpu": true` would be enough for a healthy system, but the failure modes are the interesting part. `cuda_available: false`, `device_count: 0`, and `last_error: "..."` together tell the operator exactly what to fix — install the right onnxruntime variant, load the NVIDIA driver, etc. See [Providers](https://github.com/vithurshanselvarajah/Mnemos/wiki/Providers#nvidia-gpu) for the diagnostic recipe.
