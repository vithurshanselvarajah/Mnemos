# Mnemos V2 — Bruno API Collection

A ready-to-use [Bruno](https://www.usebruno.com/) collection covering every
endpoint of the Mnemos V2 FastAPI backend.

## Layout

```
bruno/
└── collection/
    ├── bruno.json                              # collection manifest
    ├── Mnemos V2 API.bru                       # collection-level metadata + auth script
    ├── environments/
    │   └── Local.bru                           # Local env (baseUrl, apiKey, masterKey)
    ├── Health/
    │   └── Health check.bru
    ├── System/
    │   ├── Get master key.bru
    │   ├── Pair (bootstrap).bru                # ← START HERE
    │   └── Rotate master key.bru
    ├── Identify/
    │   └── Identify image (upload).bru
    ├── Faces/
    │   ├── List unassigned crops (inbox).bru
    │   ├── Assign crops to person.bru
    │   ├── Assign crops to NEW person.bru
    │   ├── Mark crops as non-face.bru
    │   └── Ignore crops.bru
    ├── Persons/
    │   ├── List persons.bru
    │   ├── Create person.bru
    │   ├── Get person.bru
    │   ├── Update person.bru
    │   ├── Delete person.bru
    │   ├── List a person's crops.bru
    │   └── Delete a crop from a person.bru
    ├── Models/
    │   ├── Get active model info.bru
    │   └── Switch model.bru
    ├── API Keys/
    │   ├── List API keys.bru
    │   ├── Create API key.bru
    │   ├── Revoke API key.bru
    │   └── Delete API key.bru
    └── Crops/
        └── Get crop image.bru
```

## Quick start

1. **Install Bruno** — download from [usebruno.com](https://www.usebruno.com/downloads) (it's free, cross-platform, no account needed).
2. **Open the collection** — File → Open Collection → point at `bruno/collection/`. Bruno will pick up the `Local` environment automatically.
3. **Set your secrets** — open `Local` env and replace the placeholders:
   - `baseUrl` — where the backend is reachable. Default: `http://localhost:8000`.
   - `masterKey` — the backend's master key (printed in the backend container's startup logs, or visible at `GET /api/v1/system/master` if you already have a Full-Admin key).
   - `apiKey` — a Full-Admin API key. If you don't have one yet, leave it blank and call **System → Pair (bootstrap)** first; it will write the resulting key into `apiKey` automatically.
4. **Send a request** — pick any `.bru` file and hit `Cmd/Ctrl-Enter`.

## Auth

The `X-API-Key` header is attached automatically by the collection-level
`script:pre-request` in `Mnemos V2 API.bru`. As long as the `apiKey` env var
is set and doesn't still contain a `REPLACE_…` placeholder, every request
gets the header.

If you need to use a different key for one specific call (e.g. testing with
an Identify-Only key), clear `apiKey` in the env, then set the header
manually in that request's **Headers** tab.

## Env vars set at runtime

Some requests populate env vars in their `script:post-response` so other
requests can chain off the result:

| Var             | Set by                                                              | Used by                                      |
|-----------------|---------------------------------------------------------------------|----------------------------------------------|
| `apiKey`        | `Pair (bootstrap)`, `Create API key`                                | every other request (auth header)            |
| `lastPersonId`  | `Assign crops…`, `Create person`                                    | `Get person`, `Update person`, `Delete…`     |
| `lastKeyId`     | `Create API key`                                                    | `Revoke API key`, `Delete API key`           |

## WebSocket

The backend has a WebSocket at `ws://<host>:8000/ws/events` that streams
`inbox.new_face` and `inbox.bulk_changed` events. Bruno does not natively
exercise WebSockets — for that, use the browser DevTools on the frontend
(`/inbox`) or a CLI client like `websocat`.
