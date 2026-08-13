# API Overview

Mnemos exposes a single JSON HTTP API. Everything you'll probably want to call is under `/api/v1/`. The backend also serves live Swagger UI at `/docs` and ReDoc at `/redoc`, and the frontend hosts a themed proxy of Swagger at `/swagger`.

- [Base URL](#base-url)
- [Authentication](#authentication)
- [Permission levels](#permission-levels)
- [Request format](#request-format)
- [Response format](#response-format)
- [Error format](#error-format)
- [Rate limiting](#rate-limiting)
- [Versioning](#versioning)
- [Endpoint index](#endpoint-index)

---

## Base URL

```
http://<host>:8000/api/v1
```

Inside the compose network the backend is reachable at `http://mnemos-backend:8000`. The frontend's `MNEMOS_FE_DEFAULT_BACKEND_URL` is set to that.

## Authentication

Every `/api/v1/*` endpoint except `/system/pair` requires an API key. Pass it as the `X-API-Key` header:

```bash
curl -H "X-API-Key: mnemos_k_…" http://localhost:8000/api/v1/persons
```

The `/healthz` endpoint and the `/ws/events` WebSocket do not require auth. `/system/pair` requires the master pairing key (see [First Run](https://github.com/vithurshanselvarajah/Mnemos/wiki/First-Run)).

> Browser clients cannot easily set the `X-API-Key` header from a session cookie. The frontend acts as a server-side proxy: it stores the API key encrypted in its own SQLite and forwards the request to the backend with the header attached. If you build a browser UI, follow the same pattern.

## Permission levels

API keys have one of two permission levels:

- **Identify-Only** — can call `/identify` and read public data (persons, inbox, models, model list, available models, single person, single crop, single key listing if it's themselves). Cannot mutate anything.
- **Full-Admin** — everything Identify-Only can do, plus create / rename / delete persons, create / revoke / delete API keys, switch models, rotate the master key, view the master key.

The default permission is `Identify-Only` when creating a key from the UI. Promote to `Full-Admin` only for the frontend integration and for scripts that need to mutate state.

## Request format

JSON body for most endpoints, multipart upload for `/identify`:

```bash
# JSON
curl -X POST http://localhost:8000/api/v1/persons \
  -H "X-API-Key: $KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "Alice"}'

# Multipart (file upload)
curl -X POST http://localhost:8000/api/v1/identify \
  -H "X-API-Key: $KEY" \
  -F "file=@/path/to/photo.jpg"
```

## Response format

JSON. All timestamps are ISO 8601 UTC. All IDs are UUIDs as strings. The schema for every endpoint is published as OpenAPI at `http://<host>:8000/openapi.json` and rendered at `/docs`.

## Error format

HTTP status code + JSON body with a `detail` field:

```json
{ "detail": "person_id not found" }
```

Status codes used:

| Code | When |
| --- | --- |
| 400 | Malformed input (missing field, empty list, invalid name, etc.) |
| 401 | Missing or invalid API key (also: invalid master key on `/system/pair`) |
| 403 | Valid key but insufficient permission (e.g. Identify-Only calling a Full-Admin endpoint) |
| 404 | Resource not found (person, crop, key, model) |
| 409 | Conflict (duplicate person name, reindex already in progress) |
| 422 | Pydantic validation error (often returned as a structured `detail` array) |
| 429 | Rate limit exceeded (see below) |
| 5xx | Internal error (check logs, report the bug) |

## Rate limiting

A simple in-memory rate limiter on the backend caps unauthenticated traffic at 600 requests/minute per source IP, applied before authentication. Authenticated endpoints are not throttled at the request level beyond that. WebSocket connections are exempt.

## Versioning

The API prefix is `/api/v1/`. Breaking changes will bump the prefix to `/v2/`. Additive changes (new fields, new endpoints) happen within `/v1/`.

The response from `/healthz` includes a `version` field set from the `VERSION` file at the repo root. Use it to detect deployments.

## Endpoint index

| Method | Path | Auth | Doc |
| --- | --- | --- | --- |
| `GET` | `/healthz` | none | [Health](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Health) |
| `WS` | `/ws/events` | none | [WebSocket](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-WebSocket) |
| `POST` | `/api/v1/identify` | any key | [Identify](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Identify) |
| `GET` | `/api/v1/faces/unassigned` | any key | [Inbox](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Faces-Inbox) |
| `POST` | `/api/v1/faces/assign` | any key | [Inbox](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Faces-Inbox) |
| `POST` | `/api/v1/faces/mark-non-face` | any key | [Inbox](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Faces-Inbox) |
| `POST` | `/api/v1/faces/ignore` | any key | [Inbox](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Faces-Inbox) |
| `GET` | `/api/v1/persons` | any key | [Persons](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Persons) |
| `POST` | `/api/v1/persons` | Full-Admin | [Persons](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Persons) |
| `GET` | `/api/v1/persons/{id}` | any key | [Persons](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Persons) |
| `PATCH` | `/api/v1/persons/{id}` | Full-Admin | [Persons](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Persons) |
| `DELETE` | `/api/v1/persons/{id}` | Full-Admin | [Persons](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Persons) |
| `GET` | `/api/v1/persons/{id}/crops` | any key | [Persons](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Persons) |
| `GET` | `/api/v1/models` | any key | [Models](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Models) |
| `GET` | `/api/v1/models/warmup` | any key | [Models](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Models) |
| `GET` | `/api/v1/models/available` | any key | [Models](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Models) |
| `POST` | `/api/v1/models/switch` | Full-Admin | [Models](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Models) |
| `GET` | `/api/v1/keys` | Full-Admin | [API Keys](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Keys) |
| `POST` | `/api/v1/keys` | Full-Admin | [API Keys](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Keys) |
| `POST` | `/api/v1/keys/{id}/revoke` | Full-Admin | [API Keys](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Keys) |
| `DELETE` | `/api/v1/keys/{id}` | Full-Admin | [API Keys](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Keys) |
| `GET` | `/api/v1/crops/{uuid}.jpg` | any key | [Crops](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Crops) |
| `GET` | `/api/v1/system/master` | Full-Admin | [System](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-System) |
| `POST` | `/api/v1/system/master/rotate` | Full-Admin | [System](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-System) |
| `POST` | `/api/v1/system/pair` | master key | [System](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-System) |
| `GET` | `/api/v1/backup` | Full-Admin | [Backup & Restore](Backup-Restore.md) |
| `POST` | `/api/v1/backup` | Full-Admin | [Backup & Restore](Backup-Restore.md) |
| `GET` | `/api/v1/backup/{filename}/inspect` | Full-Admin | [Backup & Restore](Backup-Restore.md) |
| `GET` | `/api/v1/backup/{filename}/download` | Full-Admin | [Backup & Restore](Backup-Restore.md) |
| `DELETE` | `/api/v1/backup/{filename}` | Full-Admin | [Backup & Restore](Backup-Restore.md) |
| `POST` | `/api/v1/backup/restore` | Full-Admin | [Backup & Restore](Backup-Restore.md) |
| `GET` | `/api/v1/backup/restore/{job_id}` | Full-Admin | [Backup & Restore](Backup-Restore.md) |

---

## For developers

### Why `/api/v1/` and not `/api/`

The v1 prefix is cheap insurance. When the embedding schema or authentication model changes in a non-additive way, bumping to `/v2/` lets the old clients keep working until they're updated. The backend mounts everything under `prefix="/api/v1"` in `app.main.create_app` — change there if you need a new version.

### Why one proxy

The frontend is a server-side proxy, not a SPA. The browser only talks to the frontend; the frontend talks to the backend. This means:

- The browser never sees the `X-API-Key` header (the frontend adds it server-side).
- CORS is bounded to `mnemos-frontend ↔ mnemos-backend` (default allow-list in compose).
- The browser can use session cookies without leaking them.

If you're writing a custom client, replicate the same pattern: keep the API key on the server, not the browser.
