# Architecture

Mnemos is a small system. The whole point of the project is to be inspectable, debuggable, and easy to host on a single machine. This page describes the moving parts and how they talk.

- [Service topology](#service-topology)
- [Backend architecture](#backend-architecture)
- [Frontend architecture](#frontend-architecture)
- [Request lifecycle: `/identify`](#request-lifecycle-identify)
- [Request lifecycle: warmup + reindex](#request-lifecycle-warmup--reindex)
- [Data flow: live UI updates](#data-flow-live-ui-updates)
- [Cross-cutting concerns](#cross-cutting-concerns)
- [Future work](#future-work)

---

## Service topology

```
┌──────────────┐    ┌────────────────────┐    ┌────────────────────┐
│   Browser    │◄──►│  mnemos-frontend    │◄──►│  mnemos-backend     │
│  (your UI)   │    │  FastAPI + Jinja2   │    │  FastAPI + ORT     │
└──────────────┘    │  + HTMX + Alpine.js │    │  + InsightFace     │
                    │  port 8080          │    │  port 8000         │
                    └─────────┬───────────┘    └─────────┬──────────┘
                              │                          │
                              │         ┌────────────────┘
                              │         │
                              ▼         ▼
                      ┌──────────────────────────┐
                      │    mnemos-vector-db       │
                      │    PostgreSQL 18 +        │
                      │    pgvector extension     │
                      │    port 5432 (internal)   │
                      └──────────────────────────┘
```

Three services. They share nothing except the network. The frontend and backend have their own SQLite databases. The vector DB is the only stateful service that's queryable from both.

The frontend is a server-rendered app, not a SPA. The browser only talks to the frontend; the frontend proxies API calls to the backend with the API key attached. The browser never sees the `X-API-Key` header.

## Backend architecture

The backend is a single FastAPI app, ~30 Python files, all in `mnemos-backend/app/`. Layout:

```
app/
├── main.py                  # create_app(), startup/shutdown via lifespan
├── cli.py                   # python -m app.cli (master-key view/rotate, …)
├── api/                     # FastAPI routers — one file per resource
│   ├── health.py
│   ├── identify.py
│   ├── faces.py             # /faces/{unassigned, assign, mark-non-face, ignore}
│   ├── persons.py
│   ├── models_routes.py     # /models, /models/switch, /models/warmup, /models/available
│   ├── keys.py
│   ├── crops.py
│   ├── system.py            # /system/master, /system/master/rotate, /system/pair
│   ├── websocket.py         # /ws/events
│   └── deps.py              # require_full_admin, etc.
├── core/
│   ├── config.py            # pydantic-settings Settings + proxy
│   ├── security.py          # API key hashing, master key mint/rotate
│   ├── middleware.py        # API key auth + rate limit
│   ├── events.py            # lifespan (startup/shutdown hooks)
│   ├── logging.py
│   └── version.py           # reads VERSION file
├── db/
│   ├── session.py           # SQLModel engine, session_scope()
│   └── __init__.py
├── models/
│   └── entities.py          # Person, FaceCrop, ApiKey, SystemSetting
├── schemas/
│   └── dto.py               # Pydantic request/response models
├── providers/
│   ├── base.py              # InferenceEngine Protocol, Detection, ProviderNotAvailable
│   ├── cpu/engine.py        # CpuEngine
│   ├── nvidia/engine.py     # NvidiaEngine (CUDA-locked)
│   └── rockchip/engine.py   # RockchipEngine (RKNN shim)
└── services/
    ├── engine.py            # InsightFaceEngine — the public face of the provider stack
    ├── model_manifest.py    # reads upstream manifest, preflight checks
    ├── model_downloader.py  # downloads + sha256 verifies model weights
    ├── reindex.py           # background switch + reindex state machine
    ├── vector_repo.py       # pgvector queries (search, upsert, delete)
    ├── cropper.py           # crop + save JPEG with padding
    └── websocket_hub.py     # process-local broadcast
```

### Key abstractions

- **`InferenceEngine` Protocol** — providers implement a small interface (warmup, is_loaded, detect, switch_model, active_providers, last_error). All three providers implement it identically. `InsightFaceEngine` is the public-facing wrapper.
- **`InsightFaceEngine`** — singleton, provider-aware, lazy-loads the inner engine. The rest of the backend never imports a provider directly; it goes through this class.
- **`session_scope()`** — SQLModel session factory. Used as `with session_scope() as s: …` to ensure sessions are committed/rolled back/closed cleanly.
- **`vector_repo`** — thin wrapper over pgvector SQL. All vector reads/writes go through here.

## Frontend architecture

Server-rendered FastAPI + Jinja2 + HTMX + Alpine.js. Each page is a full server response; HTMX handles partial swaps (e.g. the live reindex progress bar). Alpine.js handles the small bits of interactivity (modals, dropdowns) without a build step.

```
mnemos-frontend/app/
├── main.py
├── api/
│   ├── backend_proxy.py     # /backend/* → backend with X-API-Key attached
│   ├── pages.py             # full-page renders (/, /dashboard, /login, …)
│   ├── partials.py          # HTMX partials (/partials/reindex-status, …)
│   ├── health.py
│   ├── ws_proxy.py          # server-side WebSocket proxy
│   └── ws_target.py         # browser-facing WebSocket
├── core/
│   ├── config.py
│   ├── security.py          # Argon2id password hashing, session cookies
│   ├── middleware.py
│   ├── events.py
│   ├── logging.py
│   └── version.py
├── db/, models/, schemas/, services/  # mirror backend layout
├── static/                  # CSS, JS, HTMX/Alpine from CDN (or vendored)
└── templates/               # Jinja2 templates
```

The frontend holds a Full-Admin API key in its own SQLite, encrypted at rest with `MNEMOS_FE_SECRET`. Every page render that needs backend data goes through `backend_proxy` which decrypts the key, attaches it, and forwards.

## Request lifecycle: `/identify`

```
client → POST /api/v1/identify (multipart, file=…, X-API-Key)
        │
        ├─► APIKeyAuthMiddleware
        │     ├─► rate limit (600 req/min per IP)
        │     └─► find_api_key_by_raw() → ApiKey row → request.state.api_key
        │
        ├─► /api/v1/identify handler
        │     ├─► _read_image(file bytes) → np.ndarray (BGR)
        │     ├─► InsightFaceEngine.current().detect(bgr_image) → list[Detection]
        │     │     └─► provider-specific engine: detect() → bounding boxes + 512-D embeddings
        │     ├─► _dedupe_within_request(detections)
        │     ├─► for each surviving detection:
        │     │     ├─► is face big enough? (MNEMOS_MIN_FACE_PX)
        │     │     ├─► vector_repo.search_similar(emb, model, limit=3) → kNN over face_embeddings
        │     │     ├─► match? → IdentifyMatch (with image_url)
        │     │     └─► no match? → save crop JPEG, create FaceCrop row, push to inbox
        │     │              └─► websocket_hub.publish("inbox.new_face")
        │     └─► return IdentifyResponse
        │
        ◄─ JSON response
```

## Request lifecycle: warmup + reindex

`POST /api/v1/models/switch` runs synchronously to validate the request, then spawns a background thread that owns the rest:

```
client → POST /api/v1/models/switch {name: "buffalo_l"}
        │
        ├─► write new name to system_settings table
        ├─► InsightFaceEngine.switch_model("buffalo_l")   # clears in-memory state
        ├─► start_reindex("buffalo_l") → thread starts
        │     ├─► state.download_active = True
        │     ├─► download each missing artifact (sha256 verify, range-resume)
        │     │     └─► ws.publish("reindex.download", {model, artifact, done, total})
        │     ├─► state.reindex_in_progress = True, state.total = N (count of assigned crops)
        │     ├─► ws.publish("reindex.preparing")
        │     ├─► for each (person_id, model):
        │     │     ├─► read every assigned crop JPEG
        │     │     ├─► engine.detect() → pick largest face → embedding
        │     │     ├─► average + L2-normalise
        │     │     └─► vector_repo.upsert_averaged(person_id, vec, "buffalo_l")
        │     │     └─► every N crops: ws.publish("reindex.progress", {done, total})
        │     ├─► ws.publish("reindex.done")
        │     └─► state.reindex_in_progress = False
        └─► return ModelInfo with reindex_in_progress: true
```

While the reindex is running, `/identify` keeps serving on the old model. The model field in the database has been updated, but the old weights stay in memory until the new ones are ready. A second switch during a reindex returns 409.

## Data flow: live UI updates

The backend's `websocket_hub` is a process-local `set[WebSocket]`. Every state-changing operation publishes a small JSON event. The frontend subscribes once on dashboard load via a server-side WebSocket proxy (`/ws/events`), and patches the DOM via HTMX partials.

```
backend operation              publishes to ws://…/ws/events
─────────────                  ───────────────────────────
POST /identify (new crop) →    inbox.new_face
POST /faces/assign        →    inbox.bulk_changed
POST /faces/mark-non-face →    inbox.bulk_changed
POST /faces/ignore        →    inbox.bulk_changed
GET  /models/warmup       →    warmup.download / warmup.done / warmup.error
POST /models/switch       →    reindex.preparing / reindex.download /
                              reindex.start / reindex.progress / reindex.done /
                              reindex.error
```

The frontend's `partials.py` exposes HTMX endpoints that re-render just the affected chunks of HTML (e.g. `/partials/reindex-status` returns a `<progress>` element with the current value). The browser uses HTMX's `hx-trigger="sse:reindex.progress"` to listen for those events and swap the partial.

## Cross-cutting concerns

### Configuration

`app.core.config.Settings` is a pydantic-settings class. Reads from env at construction time, exposed via a module-level proxy so tests can swap it. See [Configuration](https://github.com/vithurshanselvarajah/Mnemos/wiki/Configuration) for the user-facing list.

### Logging

Structured JSON to stdout (configurable to plain text in dev). Every log line includes `service`, `level`, `logger`, `message`, and the call-site. The standard `logging` module is used; no fancy wrapper.

### Security

API keys are HMAC-hashed, never stored. The master key is in the database, not in env. The frontend encrypts the API key at rest with Argon2id-derived key material. See [Security](https://github.com/vithurshanselvarajah/Mnemos/wiki/Security).

### Auth

Single middleware (`APIKeyAuthMiddleware`) that runs before any router. Sets `request.state.api_key` for downstream handlers. Bypasses `/healthz`, `/docs`, `/openapi.json`, `/redoc`, `/ws/`.

### Rate limiting

In-memory per-IP, 600 req/min. Resets per minute via lazy pruning. Not thread-safe across processes (single worker only).

### Errors

Pydantic validation errors → 422 with a `detail` array. Business-logic errors raise `HTTPException(status_code, detail="…")` → JSON body `{"detail": "…"}`. Unhandled exceptions are logged with full traceback and the response is 500 with `{"detail": "Internal server error"}` — never a stack trace.

## Future work

A non-exhaustive list of things we'd like to do but haven't yet:

- **Multi-worker backend** — currently the WebSocket hub is per-process. Multi-worker needs a Redis pub/sub fan-out.
- **PostgreSQL instead of SQLite for the backend** — SQLite is fine for home use but limits write concurrency. A migration to PG would also let us share the `system_settings` table with the frontend cleanly.
- **Per-key rate limits** — currently per-IP only.
- **More providers** — CoreML on macOS, Qualcomm QNN, Google EdgeTPU, … The provider interface is deliberately narrow; the work is in the build matrix.
- **Clustered recogniser** — for very large galleries (>100k people), an approximate nearest-neighbour index over per-crop vectors is faster than per-person averaging. The averaged-vector scheme is a deliberate simplification.
- **Bigger reindex concurrency** — currently the reindex is single-threaded. For a 100k-crop install this is hours; a process pool would help.

See [Testing](https://github.com/vithurshanselvarajah/Mnemos/wiki/Testing), [Services Reference](https://github.com/vithurshanselvarajah/Mnemos/wiki/Services-Reference), and [Model Manifest](https://github.com/vithurshanselvarajah/Mnemos/wiki/Model-Manifest) for the internals of specific subsystems.
