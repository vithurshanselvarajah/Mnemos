# API Keys

Mnemos uses API keys for machine-to-machine authentication. Keys are 256-bit URL-safe tokens, prefixed with `mnemos_k_`, hashed with HMAC-SHA-256 in the database, and only ever shown in plaintext on creation.

- [Format](#format)
- [Permission levels](#permission-levels)
- [List](#list)
- [Create](#create)
- [Revoke](#revoke)
- [Delete](#delete)
- [Storage and rotation](#storage-and-rotation)

---

## Format

A raw API key looks like:

```
mnemos_k_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6
```

It's a prefix + 32 bytes of `secrets.token_urlsafe`. The first 8 characters (including the prefix) are stored as `key_prefix` so you can identify a key in the UI without exposing it.

Keys are **not** JWTs, **not** OAuth bearer tokens, **not** session cookies. They are opaque bearer tokens verified by HMAC lookup.

## Permission levels

Two levels:

- **`Identify-Only`** — can call `/identify` and read public data (persons, inbox, models, single person / crop). Cannot mutate.
- **`Full-Admin`** — everything Identify-Only can do, plus person / key / model / master-key management.

Default on creation is `Identify-Only`. Promote to `Full-Admin` only for trusted integrations (the frontend itself, a backup script, an automation that creates persons).

## List

```http
GET /api/v1/keys
X-API-Key: <Full-Admin>
```

```bash
curl -s -H "X-API-Key: $ADMIN_KEY" http://localhost:8000/api/v1/keys | jq
```

Returns every key (active and revoked), newest first. The `raw_key` is never included — only the `key_prefix` and metadata.

```json
[
  {
    "id": "f7e1…",
    "name": "Home Assistant",
    "key_prefix": "mnemos_k_a1",
    "permission_level": "Identify-Only",
    "expires_at": null,
    "created_at": "2026-07-25T10:00:00Z",
    "revoked_at": null
  }
]
```

## Create

```http
POST /api/v1/keys
Content-Type: application/json
X-API-Key: <Full-Admin>

{
  "name": "Home Assistant",
  "permission_level": "Identify-Only",
  "expires_at": "2027-01-01T00:00:00Z"
}
```

- `name` — required, non-empty after strip
- `permission_level` — required, one of `Identify-Only` or `Full-Admin`
- `expires_at` — optional, ISO 8601 datetime. `null` = never expires.

Response:

```json
{
  "api_key": {
    "id": "f7e1…",
    "name": "Home Assistant",
    "key_prefix": "mnemos_k_a1",
    "permission_level": "Identify-Only",
    "expires_at": "2027-01-01T00:00:00Z",
    "created_at": "2026-07-25T10:00:00Z",
    "revoked_at": null
  },
  "raw_key": "mnemos_k_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6"
}
```

> **`raw_key` is the only time you'll see the full key.** Store it now (in your password manager, secret manager, or wherever you keep credentials). The backend only stores the HMAC of the key, not the key itself.

## Revoke

```http
POST /api/v1/keys/{key_id}/revoke
X-API-Key: <Full-Admin>
```

Sets `revoked_at` to the current UTC time. The row stays in the database for audit. Any future request with that key returns 401.

Revoke is preferred over delete for most cases — you keep the audit trail.

## Delete

```http
DELETE /api/v1/keys/{key_id}
X-API-Key: <Full-Admin>
```

Hard-deletes the row. The key stops working immediately. There is no undo. Use this for keys you created by mistake or that you've fully decommissioned.

## Storage and rotation

- The `key_hash` column is `HMAC-SHA-256(MNEMOS_MASTER_KEY_PREFIX + "hmac", raw_key)`. Verification re-computes the hash and compares; the raw key is never read from disk.
- Rotate keys quarterly. The simplest rotation:
  1. Create a new key.
  2. Update the integration to use the new key.
  3. Revoke the old key.
- A leaked key should be **revoked immediately**, not deleted. Revocation is fast, deletion is audit-hostile.
- The frontend's Full-Admin key is bootstrapped once via the master key on first run. It does not rotate automatically; you can rotate it manually from the Keys page.

---

## For developers

### Why HMAC and not bcrypt / argon2

API keys are high-entropy random strings (256 bits). They don't need a slow hash because there is no brute-force risk — the attacker would need to guess 2^256 random bits. A fast HMAC is the right primitive: constant-time comparison, no per-key salt needed, deterministic. The `MNEMOS_MASTER_KEY_PREFIX` mixed in as the HMAC salt keeps hashes distinct across deployments.

### Why no "edit" endpoint

A key's only mutable state is `name`. Renaming is rare; the UI shows the `name` field inline-editable. An API endpoint for it would just be a second way to do the same thing. If you need to script renames, you can drop into the SQLite DB directly (`docker exec -it mnemos-backend sqlite3 /data/backend.db "UPDATE api_key SET name = …"`).

### Why per-key rate limiting isn't a thing yet

The current rate limiter is per-source-IP at 600 req/min, applied before authentication. It exists to protect the host from runaway clients, not to differentiate legitimate users. Per-key throttling is on the wishlist (see [Architecture](https://github.com/vithurshanselvarajah/Mnemos/wiki/Architecture#future-work)).

### Expiry semantics

`expires_at` is checked at request time. There is no background sweep that revokes expired keys; the row stays in the database with `expires_at` set, and authentication just rejects it. If you want clean rows, run a periodic `DELETE FROM api_key WHERE expires_at < now() AND revoked_at IS NULL`.
