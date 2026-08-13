# Security

Mnemos is designed to be self-hosted on a trusted home network. This page covers the threat model, what's enforced, and the hardening checklist for exposing it beyond `localhost`.

- [Threat model](#threat-model)
- [Authentication](#authentication)
- [Authorization](#authorization)
- [Data at rest](#data-at-rest)
- [Data in transit](#data-in-transit)
- [Reporting a vulnerability](#reporting-a-vulnerability)
- [Hardening checklist](#hardening-checklist)
- [What Mnemos does NOT do](#what-mnemos-does-not-do)

---

## Threat model

Mnemos is designed to be safe to run on a trusted home network where:

- The host's user accounts are managed by the operator (no untrusted local users).
- The Docker daemon is not exposed beyond the host.
- The exposed ports (8000 backend, 8080 frontend) are reachable only from the home LAN.

Mnemos is **not** designed to be exposed to the public internet without additional hardening. The defaults assume localhost-or-VPN; if you want to expose it, follow the [hardening checklist](#hardening-checklist).

The threat model includes:

- ✅ A camera or integration on the same LAN abusing the API (rate-limited, scoped to its key).
- ✅ A leaked API key (revoke + rotate).
- ✅ A leaked master pairing key (rotate; new keys must use the new master).
- ✅ Disk theft of the host (data at rest is encrypted at the volume level by the operator; Mnemos stores API keys as HMAC, not plaintext).
- ✅ A man-in-the-middle on the LAN (TLS termination at the reverse proxy).
- ❌ A malicious local user with shell on the host. They own the SQLite databases, the pgvector data, and the master key. This is by design — the host is the trust boundary.

## Authentication

### API keys

`X-API-Key: mnemos_k_…` is the only auth header. The middleware:

- Looks up the key by HMAC-SHA-256 (`HMAC(MNEMOS_MASTER_KEY_PREFIX + "hmac", raw_key)`).
- Compares the hash against the `api_key.key_hash` column.
- Verifies the row is not revoked (`revoked_at IS NULL`) and not expired (`expires_at > now()`).
- Sets `request.state.api_key` for the handler.

The raw key is never read from disk. The HMAC is deterministic (no per-key salt needed for high-entropy inputs) and constant-time compared.

### Master pairing key

One-time secret used to bootstrap the first API key. Stored in `system_settings.master_key`. See [API System](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-System) for the protocol. The key is shown to the operator via:

```bash
docker exec -it mnemos-backend python -m app.cli master-key view
```

…and only on that command. It is never logged.

### Frontend sessions

Session cookie signed with `MNEMOS_FE_SECRET`. Argon2id-hashed passwords. The frontend's session DB is its own SQLite; the Full-Admin API key is stored encrypted (using a key derived from `MNEMOS_FE_SECRET`) in the same DB.

The session secret must be at least 32 random bytes. The compose file defaults to a placeholder; **change it before going to production**.

## Authorization

Two permission levels enforced at the API layer:

- **`Identify-Only`** — can call `/identify` and read public data. Cannot mutate.
- **`Full-Admin`** — everything Identify-Only can do, plus person / key / model / master-key management.

The level is checked via `Depends(require_full_admin)` on every Full-Admin endpoint. The middleware sets `request.state.api_key`; the dependency reads it and raises 403 if the level is wrong.

The default for newly-created keys is `Identify-Only`. Promote to `Full-Admin` only for the frontend integration and for trusted automation scripts.

## Data at rest

| Store | Encryption | Notes |
| --- | --- | --- |
| `backend.db` (SQLite) | None — relies on host FS encryption | Holds persons, crops metadata, API key HMACs, master key |
| `frontend.db` (SQLite) | Argon2id for passwords; AES-GCM for the API key | Frontend users + encrypted backend key |
| pgvector `vector-db` | None — relies on host FS encryption | 512-D embeddings |
| Crop JPEGs | None | Not sensitive by themselves; a face in a crop is a face in a photo |
| Model weights | None | Public anyway |

The host's filesystem encryption (LUKS, FileVault, ZFS native encryption) is what protects the data on a stolen disk. Mnemos does not add application-level encryption because the threat model puts the host in the trust boundary.

**Do back up the data**, but the backup is also unencrypted unless you encrypt it. See [Backup & Restore](https://github.com/vithurshanselvarajah/Mnemos/wiki/Backup-Restore) for backup strategies that include `gpg` or `restic` for at-rest encryption.

## Data in transit

By default, Mnemos speaks plain HTTP. For anything beyond localhost, terminate TLS at a reverse proxy:

- **Caddy** — automatic Let's Encrypt, one-line config.
- **Traefik** — automatic Let's Encrypt, label-based config in compose.
- **nginx** — manual cert, more configuration.

Caddy example:

```caddyfile
mnemos.example.com {
    reverse_proxy localhost:8080
}
```

This fronts the frontend; the backend (port 8000) is reachable only through the frontend's `/backend/*` proxy. If you need to expose the backend directly (e.g. for an external integration), add a second vhost:

```caddyfile
api.example.com {
    reverse_proxy localhost:8000
}
```

WebSocket upgrades (`/ws/events`) are handled correctly by Caddy, Traefik, and nginx out of the box.

## Reporting a vulnerability

Email security@selvarajah.co.uk (or the address in `SECURITY.md` at the repo root). Do not file a public issue.

Please include:

- The Mnemos version (`curl http://localhost:8000/healthz | jq .version`).
- A description of the issue.
- A reproducer (commands, screenshot, packet capture — whatever you have).
- The impact you believe it has.

The maintainer will respond within 72 hours. A coordinated disclosure timeline is fine; just ask.

## Hardening checklist

For any deployment beyond `localhost`:

- [ ] `MNEMOS_PG_PASSWORD` is a long random string, not the default.
- [ ] `MNEMOS_FE_SECRET` is at least 32 random bytes (`openssl rand -hex 32`).
- [ ] Master pairing key is read from the host and stored nowhere else.
- [ ] All API keys created after onboarding are `Identify-Only` unless they need more. The Full-Admin key from pairing is the only one that should be.
- [ ] All API keys have a non-null `expires_at`. Rotate them.
- [ ] The host's firewall allows only the ports you need (8000 / 8080 behind the reverse proxy, not directly).
- [ ] TLS is terminated at the reverse proxy.
- [ ] Backups are encrypted at rest (restic, borg with passphrase, etc.) and stored off-host.
- [ ] `docker compose logs` is captured by your logging stack; the master key is never logged.
- [ ] The compose file is not running with `--privileged`; the GPU runtime is configured per-service, not globally.
- [ ] The `pg_isready` healthcheck on the vector DB is monitored.
- [ ] The `/healthz` endpoint is monitored for `status == "ok"`.

## What Mnemos does NOT do

- **No application-level encryption of the SQLite databases.** If you need at-rest encryption, use LUKS / FileVault / ZFS native encryption on the host.
- **No multi-tenant isolation.** One backend = one dataset. If you need to host multiple tenants, run multiple backends.
- **No built-in WAF / rate limit per key.** The rate limiter is per-source-IP. A motivated attacker can bypass it with IP rotation; the defence in depth is to put Mnemos behind a reverse proxy that does per-key throttling if you need it.
- **No automatic key rotation.** API keys are minted once and live until revoked or expired.
- **No audit log on the backend.** Key creations / revocations / model switches are in the SQLite `system_settings` table, but the frontend's `audit_log` is the only place with operator-action history.
- **No compliance certifications.** This is a hobby project, not an enterprise product. If you need SOC2 / HIPAA / PCI, do not use Mnemos in production for those workloads.
