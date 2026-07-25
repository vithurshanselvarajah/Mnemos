# FAQ

Short answers to questions that come up a lot. If your question isn't here, check the [Troubleshooting](https://github.com/vithurshanselvarajah/Mnemos/wiki/Troubleshooting) page or open an issue.

- [General](#general)
- [Models and accuracy](#models-and-accuracy)
- [Performance](#performance)
- [Integrations](#integrations)
- [Backup and recovery](#backup-and-recovery)
- [Privacy](#privacy)

---

## General

### What does "Mnemos" mean?

Mnemosyne (Νημοσύνη) is the Greek goddess of memory. Pronounced **nee-MOZ** (or **nee-MOZ-ee-nee** for the longer form). Mnemos is the project name — same pronunciation, shorter spelling.

### Is Mnemos free?

Yes. The code is open-source (see [LICENSE](../LICENSE)) and the model weights are public (InsightFace buffalo family, Apache 2.0). There is no paid tier and no "pro" features.

### Can I use Mnemos commercially?

Yes. The license is permissive. The only restriction is the upstream InsightFace license (which is also permissive). If you ship a product that uses Mnemos, please link back to the repo.

### Does Mnemos work offline?

Yes, after the first model download. The model manifest is fetched from the upstream URL on startup, but the manifest itself is a small JSON; once it's cached in memory, the backend doesn't talk to the network for normal operation. Model weights are downloaded once and cached in `models/`. If you want full air-gapped operation, mirror the manifest and artifacts on a local server (see [Model Manifest](https://github.com/vithurshanselvarajah/Mnemos/wiki/Model-Manifest#hosting-your-own-mirror)).

### Why three databases (two SQLite + one Postgres)?

- **SQLite for `backend.db`** — single-writer, durable, file-on-disk. Perfect for the relational store of a single-user application. No separate process to manage.
- **SQLite for `frontend.db`** — same logic for the frontend's users and sessions. Independent of the backend so the frontend can be redeployed without losing the backend's data.
- **PostgreSQL + pgvector for embeddings** — the only data structure that benefits from a real database server is the vector index. SQLite doesn't have pgvector, and shipping a custom kNN in SQLite would be slower than just running Postgres.

### Can I run Mnemos on Windows?

Yes, via WSL2. The host must be Linux because the Docker base images are Linux. WSL2 with the Docker Desktop WSL2 backend works; bare Windows does not (no `linux/amd64` container support).

### Can I run Mnemos on a Raspberry Pi?

Yes, with caveats. The CPU provider works on ARM64 (aarch64). It's slow — expect ~1 fps for `/identify` on a Pi 4. The Rockchip variant is much faster but only on Rockchip SoCs (the Pi isn't one). For multiple cameras, run the backend on a more powerful host and the frontend on the Pi.

### Why no built-in motion detection or video support?

Out of scope. Mnemos is a face-recognition service, not a video pipeline. Use an external motion detector (Frigate, Home Assistant, ZoneMinder) to trigger `/identify` snapshots.

## Models and accuracy

### Which model should I use?

`buffalo_s` for most cases. It's 5-10× faster than `buffalo_l` and the accuracy difference is small for typical home use. Switch to `buffalo_l` if you have the GPU and you care about edge cases (twins, partial occlusion, very low light).

### How many photos do I need per person?

3-5 well-lit, front-facing samples is a good minimum. More helps; the diminishing return kicks in around 10. Quality matters more than quantity — five different angles is better than 50 of the same angle.

### How accurate is Mnemos?

For the home use case (a small known set of people, well-lit photos, no occlusions), >95% top-1 accuracy with `buffalo_s` after a handful of samples per person. The `buffalo_l` model pushes this higher. For professional / security use cases, Mnemos is not the right tool — it's a hobby-grade recogniser, not a forensic system.

### Does Mnemos handle glasses, hats, masks?

Glasses and hats: yes, with sufficient samples that include them. Masks: no, not reliably. The buffalo models were trained before COVID-era masked-face data was standard, and 50% of a face is not enough signal for a 512-D embedding.

### Can Mnemos tell identical twins apart?

Not reliably. Identical twins are genetically the same face; the buffalo models' embedding space treats them as the same person. The only way to differentiate is per-person threshold tuning and very large sample sets. The professional face-recognition field has the same problem.

### Will adding more training data help?

No. The buffalo models are pre-trained; Mnemos does not fine-tune them. Adding samples adds to the per-person averaged embedding, which is the only thing the embedding space sees. The underlying model doesn't change.

## Performance

### How fast is `/identify` on CPU?

~150 ms per image with one face on a modern desktop CPU. Scales linearly with face count.

### How much RAM does Mnemos use?

- `buffalo_s` in memory: ~600 MB
- `buffalo_l` in memory: ~1.2 GB
- Plus the uvicorn worker, FastAPI, SQLModel, etc.: ~200 MB
- Plus pgvector: ~200 MB + a few MB per 1k persons

For a single-person install: 2 GB total. For a 10k-person install: 4-6 GB total.

### Can I run multiple backends for load balancing?

Not yet. The WebSocket hub is per-process, so events don't fan out across workers. Multi-worker is on the wishlist (see [Architecture](https://github.com/vithurshanselvarajah/Mnemos/wiki/Architecture#future-work)). For now, the right answer is "one backend per host, scale up the host."

### How many cameras can a single Mnemos host handle?

Depends on the model and the recognition rate. As a rough guide:

- `buffalo_s` on a modern CPU: 5-10 cameras at 1 fps
- `buffalo_l` on CPU: 2-3 cameras at 1 fps
- `buffalo_s` on an NVIDIA GPU: 50+ cameras at 1 fps
- `buffalo_l` on NVIDIA: 30+ cameras at 1 fps

If your cameras are slow (a snapshot every 30 seconds), a single backend handles essentially unlimited cameras.

## Integrations

### Does Mnemos integrate with Home Assistant?

Yes, via a webhook or a `shell_command` from HA to the backend's `/identify` endpoint. See [Webhooks Patterns](https://github.com/vithurshanselvarajah/Mnemos/wiki/Webhooks-Patterns#pattern-3-forward-recognise-events-to-home-assistant) for a working example. The official HA integration is on the wishlist.

### Does Mnemos integrate with Frigate?

Yes, via Frigate's "send snapshot to URL" feature. Point it at `http://<mnemos-backend>:8000/api/v1/identify` with the `X-API-Key` header.

### Does Mnemos integrate with n8n / Node-RED / …?

Yes, anything that can `POST` multipart and parse JSON works. See [Webhooks Patterns](https://github.com/vithurshanselvarajah/Mnemos/wiki/Webhooks-Patterns) for working snippets in Python, JavaScript, and the standard cURL.

### Is there a mobile app?

No. The web UI is the only client. Mobile users can use the browser; the UI is responsive but not a PWA.

## Backup and recovery

### How do I back up Mnemos?

Stop the stack, copy `./mnemos/` and `.env`. See [Backup & Restore](https://github.com/vithurshanselvarajah/Mnemos/wiki/Backup-Restore) for the full recipe.

### Can I back up while the stack is running?

Yes, with a small lag (the SQLite checkpoint). See [Backup & Restore](https://github.com/vithurshanselvarajah/Mnemos/wiki/Backup-Restore#hot-snapshot-no-downtime) for the hot-snapshot recipe.

### What happens if I lose the master key?

Generate a new one (`python -m app.cli master-key rotate`) and re-pair the frontend. Existing API keys are unaffected.

### What happens if I lose the frontend's admin password?

Wipe the frontend's `frontend.db` and go through [First Run](https://github.com/vithurshanselvarajah/Mnemos/wiki/First-Run) again. The backend's data is untouched; only the frontend login is lost.

## Privacy

### Does Mnemos send my photos anywhere?

No. Photos are decoded in memory, embedded, and either matched against the local pgvector index or stored as cropped JPEGs in `crops/`. The only outbound network calls are:

- Manifest fetch on backend startup
- Model weight download on first warmup

Both are HTTPS to the configured upstream. There is no telemetry, no analytics, no error reporting.

### Is the data encrypted at rest?

Mnemos does not encrypt at the application level. The host's filesystem encryption (LUKS, FileVault, ZFS native) is what protects the SQLite databases, the pgvector data, and the crop JPEGs from a stolen disk. See [Security](https://github.com/vithurshanselvarajah/Mnemos/wiki/Security#data-at-rest) for details.

### Is the data encrypted in transit?

Only if you put a reverse proxy in front. The default is plain HTTP. For anything beyond localhost, terminate TLS at Caddy / Traefik / nginx. See [Security](https://github.com/vithurshanselvarajah/Mnemos/wiki/Security#data-in-transit).

### Who can see the crops?

The crops are exposed via `GET /api/v1/crops/{uuid}.jpg`, which requires an API key. The frontend proxies these to the browser when the user is logged in. The bytes never appear in any logs.

### Can I delete a specific person and all their data?

Yes. `DELETE /api/v1/persons/{id}` (Full-Admin). The person's crops are returned to the inbox as `UNASSIGNED`; the JPEGs are not deleted. To delete the JPEGs too, query the SQLite DB for the relevant `facecrop.file_path` rows and `rm` them.
