# System

The `/api/v1/system` endpoints manage bootstrap state — the master pairing key and the initial pairing handshake. All require Full-Admin permission except `/pair` (which uses the master key as auth).

- [Get the master key](#get-the-master-key)
- [Rotate the master key](#rotate-the-master-key)
- [Pair with the master key](#pair-with-the-master-key)

---

## Get the master key

```http
GET /api/v1/system/master
X-API-Key: <Full-Admin>
```

Returns the current master pairing key as a plain string:

```
mnemos_master_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6
```

> Treat the master key as a secret. It's equivalent to a permanent Full-Admin API key: anyone holding it can mint new keys at any time.

The same value is also available via the CLI:

```bash
docker exec -it mnemos-backend python -m app.cli master-key view
```

## Rotate the master key

```http
POST /api/v1/system/master/rotate
X-API-Key: <Full-Admin>
```

Generates a new master key and returns it. The old key is immediately invalidated. **Existing API keys are not affected** — only new pairing flows must use the new value.

If you suspect the master key has leaked:

1. Rotate it.
2. Audit your API keys. The leaked key holder may have already minted themselves a Full-Admin key.
3. Revoke any keys you don't recognise.

## Pair with the master key

```http
POST /api/v1/system/pair
Content-Type: application/json
{
  "master_key": "mnemos_master_…",
  "name": "Home dashboard"
}
```

**No `X-API-Key` header required.** The master key itself is the authentication. This is the only endpoint on the backend that works without an existing API key.

The backend validates the master key with a constant-time comparison. If it matches, the backend mints a brand-new API key with `permission_level: Full-Admin` and the requested name, and returns the raw key:

```json
{
  "api_key_id": "f7e1…",
  "key_prefix": "mnemos_k_a1",
  "raw_key": "mnemos_k_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6"
}
```

> `raw_key` is shown only in this response. Store it immediately. The backend never stores the raw value — only an HMAC of it.

### Failure modes

- 401 — invalid master key. The endpoint does not distinguish between "no master key has been set" and "wrong key." Both return the same error to avoid leaking which case you're in.
- The master key is read from the `system_settings` table on every request. If the database is corrupted, the endpoint will 500.

### What "pair" means

In a fresh install:

1. The backend has no API keys.
2. The first client (your frontend) doesn't have an API key either.
3. The master key is the bootstrap secret that lets the first client get an API key.

After the first pairing, the master key has no special role. The API key it minted can do everything the master key can (and more, in the sense that it can't be rotated out from under you by a stray admin). Subsequent frontends on the same backend should use an existing Full-Admin API key to mint themselves an Identify-Only key via `POST /api/v1/keys`.

---

## For developers

### Why constant-time compare

`hmac.compare_digest()` (used in `app.api.system.pair_with_master_key`) avoids a timing side channel. A naive `==` would short-circuit on the first mismatched byte, leaking the prefix of the correct key through response-time measurement. Constant-time compare touches every byte regardless.

### Why the master key is in the database, not in env

The whole point of the master key is to bootstrap the system without leaving a secret lying around in env files or compose files. If the master key were in env, the env would have to be readable by the operator, which means the operator can mint Full-Admin keys at any time — at which point the master key is no longer the root of trust.

By generating it on first start and persisting it in the database, the master key is owned by the host, not by the configuration. The operator reads it with `docker exec`, pastes it into the UI once, and never looks at it again.

### Why no "list past master keys" endpoint

Rotated master keys are gone — overwritten in the `system_settings` table. There is no history. If you rotated because of a suspected leak, the old key has zero validity. Storing it for display would invite confusion.

### What `name` does

The `name` is just a label for the API key. It shows up in `GET /api/v1/keys` so you can identify which key is which. It is not unique and not enforced to be non-empty in the API contract, but the UI rejects empty names at the form level.
