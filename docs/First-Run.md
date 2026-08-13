# First Run

Three steps. Takes about two minutes.

1. [Grab the master pairing key](#step-1-grab-the-master-pairing-key)
2. [Create the admin user](#step-2-create-the-admin-user)
3. [Pair with the backend](#step-3-pair-with-the-backend)
4. [Verify everything works](#step-4-verify-everything-works)

---

## Step 1 — Grab the master pairing key

The master key is a one-time secret that the backend mints on its first start and stores in its own SQLite volume. You only need it to bootstrap the very first admin; the frontend then exchanges it for a permanent Full-Admin API key.

```bash
docker exec -it mnemos-backend python -m app.cli master-key view
```

It prints a string that starts with `mnemos_master_`. Copy it.

> The master key is **not** an env var. It is intentionally not settable, and intentionally not logged. If you lose it you can rotate it (`python -m app.cli master-key rotate`) and re-pair the frontend. Existing API keys are unaffected.

---

## Step 2 — Create the admin user

Open `http://localhost:8080` in a browser. Because no admin user exists yet you are redirected to the onboarding wizard.

On the first screen:

- **Username** — anything you like, used to sign in to the UI
- **Password** — at least 8 characters; Mnemos uses Argon2id for hashing

Submit. The user is created and you advance to step 2.

---

## Step 3 — Pair with the backend

On the second screen:

- **Name** — a label for this frontend instance, e.g. "Home dashboard"
- **Master key** — paste the value from Step 1

Submit. The frontend POSTs to `POST /api/v1/system/pair` on the backend with the master key. The backend validates it, mints a new Full-Admin API key, and returns the raw key string. The frontend stores it encrypted at rest in its `frontend.db` and uses it for all subsequent API calls.

You are now logged in. From here on, you authenticate with the username + password from Step 2; the API key is used by the frontend's server-side proxy.

---

## Step 4 — Verify everything works

Open the dashboard. You should see:

- **Model status** — `buffalo_s` (or whatever you set) with a green "loaded" indicator. If it's red, see [Troubleshooting](https://github.com/vithurshanselvarajah/Mnemos/wiki/Troubleshooting#model-never-finishes-loading).
- **Vector DB** — `ok` (pgvector connected)
- **Inbox count** — 0 (nothing to review yet)

Test the API directly:

```bash
curl -s http://localhost:8000/healthz | jq
curl -s http://localhost:8080/healthz | jq
```

The frontend's `/healthz` response includes the backend's payload, so a single `curl` shows the state of the whole stack. See [Health & Versioning](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Health) for the full payload shape.

Smoke-test the identify endpoint with any photo that has a face:

```bash
curl -X POST http://localhost:8000/api/v1/identify \
  -H "X-API-Key: $MNEMOS_KEY" \
  -F "file=@/path/to/photo.jpg"
```

You should get back a JSON object with an empty `recognized` list and one entry in `unknown_faces` (the detected face with a crop URL). That face now lives in the inbox — go label it and you'll never have to label it again.

---

## What now?

- [Daily Use](https://github.com/vithurshanselvarajah/Mnemos/wiki/Daily-Use) — the typical workflow once you have a few labelled people.
- [API Overview](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Overview) — if you're wiring Mnemos into another system (Home Assistant, n8n, custom script, etc.).
- [Configuration](https://github.com/vithurshanselvarajah/Mnemos/wiki/Configuration) — tune thresholds, change the default model, switch providers.
- [Backup & Restore](https://github.com/vithurshanselvarajah/Mnemos/wiki/Backup-Restore) — before you spend an afternoon labelling people.

---

## For developers

### Why a master key?

The first run of the backend has no API keys in its database. The master key is a one-time bootstrap secret that lets the **first client** (your frontend) mint a permanent Full-Admin API key without needing one already. After pairing, the master key has effectively zero value — the API key has the same permissions and doesn't expire.

The flow is intentionally non-env-var. Anyone with shell on the host already has the keys to the kingdom, so the master key is for the case where you (a) trust the host and (b) want the frontend on a different host that doesn't have shell access. The host generates, stores, and shows the key. You read it once, paste it, and never look at it again.

### Pairing internals

`POST /api/v1/system/pair` is the only endpoint on the backend that requires no auth. The body is:

```json
{ "master_key": "mnemos_master_…", "name": "Home dashboard" }
```

It returns:

```json
{
  "api_key_id": "…",
  "key_prefix": "mnemos_k_…",
  "raw_key": "mnemos_k_…"
}
```

`raw_key` is shown once and never again. The frontend persists it in `frontend.db` (encrypted at rest with `MNEMOS_FE_SECRET`) and includes it in every server-side proxy call as the `X-API-Key` header.

The master key itself is stored in `backend.db` under the `system_settings` table. `rotate_master_key()` mints a new one and overwrites the row; existing API keys are unaffected.
