# Troubleshooting

Most Mnemos problems fall into a few categories. This page walks through the common symptoms, what they actually mean, and how to fix them.

- [Container won't start](#container-wont-start)
- [Model never finishes loading](#model-never-finishes-loading)
- [`/identify` returns 503](#identify-returns-503)
- [`/identify` returns 400](#identify-returns-400)
- [Recognition accuracy is bad](#recognition-accuracy-is-bad)
- [Inbox fills up with the same face](#inbox-fills-up-with-the-same-face)
- [Reindex is stuck](#reindex-is-stuck)
- [Frontend can't log in](#frontend-cant-log-in)
- [WebSocket disconnects every minute](#websocket-disconnects-every-minute)
- [Performance](#performance)
- [Where to get help](#where-to-get-help)

---

## Container won't start

```bash
docker compose ps
docker compose logs mnemos-backend
```

Common messages:

- `preflight failed: provider=nvidia requires the CUDAExecutionProvider, but it is not present in this onnxruntime build.` — You're using the wrong image tag. Switch to `-nvidia` (or fix the build), or change `MNEMOS_PROVIDER=cpu`.
- `preflight failed: provider=nvidia … libcuda could not be loaded.` — The host's NVIDIA driver isn't visible to the container. Install the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) and confirm `nvidia-ctk runtime configure --runtime=docker`.
- `preflight failed: provider=rockchip detected_soc=rk3588 (supported: rk3576).` — Your SoC isn't in the manifest. Either set `MNEMOS_ROCKCHIP_SOC=rk3576` (if you have one) or use `provider=cpu`.
- `psycopg2.OperationalError: could not connect to server` — The vector DB isn't ready yet. Wait 10 seconds and check `docker compose ps mnemos-vector-db` — its healthcheck has a 10-retry loop. If it stays unhealthy, see [pgvector health](#pgvector-health).
- `sqlite3.OperationalError: database is locked` — A previous process didn't release the SQLite lock. `docker compose restart mnemos-backend`.

## Model never finishes loading

`GET /healthz` shows `model_loaded: false` indefinitely. Check the logs:

```bash
docker compose logs -f mnemos-backend
```

What you might see:

- `Fetching model manifest from …` — normal on first start; takes a few seconds.
- `Downloading <artifact> …` — could be slow if your upstream is constrained. The progress is reported on the WebSocket.
- `sha256 mismatch` — the file was corrupted mid-download (or you have a man-in-the-middle). `rm -rf mnemos/backend/models/*` and restart.
- `CUDAExecutionProvider missing` — see [Container won't start](#container-wont-start).
- `insightface … failed to load` — corrupted weights, same fix as above.
- Stuck on `Loading InsightFace model=buffalo_l det_size=640` — likely running on a host without enough RAM. `buffalo_l` is ~1 GB on disk and ~2 GB in memory.

To force a re-download:

```bash
docker compose down
rm -rf mnemos/backend/models/
docker compose up -d
```

## `/identify` returns 503

```json
{ "detail": "Model not loaded" }
```

The backend is up but the model isn't warm. Either:

- The first warmup is still running (wait).
- The warmup failed (check logs and `last_error` in `/healthz`).
- The model was switched and the new one is downloading (wait for `reindex.done`).

The dashboard's status pill mirrors this. The fix is almost always "give it a minute and try again."

## `/identify` returns 400

```json
{ "detail": "Unsupported image: …" }
```

OpenCV's `imdecode` couldn't read the bytes. Common causes:

- Corrupt JPEG (camera buffer issue, network glitch).
- HEIC / AVIF — not supported. Convert to JPEG first.
- Animated GIF / WebP — only the first frame is read; some tools produce a multi-frame file that OpenCV can't decode.
- Empty file or 0 bytes.

Test with a known-good JPEG (e.g. one of your camera's older snapshots). If that works, the failing input is the problem.

## Recognition accuracy is bad

A few common causes:

1. **Too few samples per person.** 3-5 is a good minimum. Add more by uploading more photos of the same person.
2. **All samples are the same angle.** If all of "Alice's" samples are profile shots, front-facing detections of Alice won't match. Add variety.
3. **Threshold is too lenient.** Drop `MNEMOS_DEFAULT_THRESHOLD` from 0.40 to 0.30. The risk is more false negatives (Alice not recognised); the benefit is fewer false positives (Bob recognised as Alice).
4. **Threshold is too strict.** Raise it from 0.40 to 0.50. The risk is the reverse.
5. **Wrong model.** `buffalo_s` is fast but less accurate than `buffalo_l`. Switch via `POST /api/v1/models/switch {"name": "buffalo_l"}` (triggers a reindex).
6. **Misaligned crops.** The 50% padding is generous; if your custom threshold is at the edge, the cropping matters. Don't change `MNEMOS_CROP_PAD_FRACTION` without a reason.
7. **Cross-person threshold mismatch.** A person with a lookalike sibling should have a higher `custom_threshold`. See [API Persons](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Persons#custom-thresholds-explained).

## Inbox fills up with the same face

The cross-request dedup uses `(image_sha, bbox)`. If the same image bytes arrive with a different bbox, it's a new row. Causes:

- The image bytes are different (re-encoded JPEG, different camera resolution).
- The face moved (different bbox).
- The image hash isn't being computed (older client, or `image_sha` is null).

Fix: usually nothing. The inbox review queue is the right place to triage.

If the same exact photo keeps appearing every 30 seconds, the source integration is stuck. Check the camera / webhook.

## Reindex is stuck

`GET /api/v1/models` shows `reindex_in_progress: true` and `reindex_done` not advancing.

```bash
docker compose logs -f mnemos-backend
```

What you might see:

- A traceback for a specific crop. The reindex continues past errors, but a flood of failures (e.g. all crops unreadable) can make it look stuck.
- A traceback for the model download. The reindex can't proceed without the new model.

If a single crop is corrupt, identify it from the logs and either:

- Move the file out of the way: `mv mnemos/backend/crops/<uuid>.jpg /tmp/`.
- Set the corresponding `facecrop.status` to `IGNORED` in SQLite (the next reindex will skip it).

To force-cancel a stuck reindex, restart the container:

```bash
docker compose restart mnemos-backend
```

The new model name is already in `system_settings.active_model`; the reindex will resume on the next start.

## Frontend can't log in

```bash
docker compose logs -f mnemos-frontend
```

Common messages:

- `500 Internal Server Error` on `POST /login` — the frontend's SQLite is locked or corrupt. `docker compose restart mnemos-frontend` is usually enough.
- `Backend unreachable` banner — the frontend can't reach the backend. Check `MNEMOS_FE_DEFAULT_BACKEND_URL`; inside the compose network it should be `http://mnemos-backend:8000`.
- `Invalid username or password` — the admin user doesn't exist. If the SQLite was lost, you'll need to re-do [First Run](https://github.com/vithurshanselvarajah/Mnemos/wiki/First-Run).

## WebSocket disconnects every minute

A reverse proxy in front of the WebSocket that's misconfigured will close idle connections. The fix depends on the proxy:

- **nginx** — set `proxy_read_timeout 3600s;` and `proxy_send_timeout 3600s;` for the `/ws/` location.
- **Caddy** — defaults are fine; check the `rewrite` rules.
- **Traefik** — defaults are fine.

You can also send `ping` from the client every 30s (the server responds `pong`), which keeps the connection alive through most proxies.

## Performance

Typical numbers on a modern desktop CPU with `buffalo_s`:

| Operation | Time |
| --- | --- |
| `/identify` (single image, 1 face) | ~150 ms |
| `/identify` (single image, 4 faces) | ~400 ms |
| Reindex 1,000 crops | ~2 min |
| Reindex 10,000 crops | ~15-20 min |
| Warmup (cold start, with download) | ~30-60 s |

NVIDIA is roughly 5-10× faster on inference; download dominates the warmup time either way.

If `/identify` is slow:

- Check the model — `buffalo_l` is ~3× slower than `buffalo_s` per detection.
- Check the image size — the detector is sized for 640px input. A 4K image is downscaled to 640 internally; uploading smaller images doesn't help, but uploading much larger ones wastes bandwidth.
- Check for log noise — InsightFace writes verbose logs at INFO. Set `MNEMOS_LOG_LEVEL=WARNING` to silence.
- If you're on a Raspberry Pi, expect ~5× slower. Consider running the backend on a more powerful host and only the frontend on the Pi.

## pgvector health

```bash
docker compose ps mnemos-vector-db
docker exec -it mnemos-vector-db pg_isready -U mnemos -d mnemos_vectors
```

If the healthcheck is failing:

- The init script (`pgvector-init/01-extensions.sql`) didn't run. Drop the data volume and restart: `docker compose down -v && docker compose up -d mnemos-vector-db`.
- The disk is full. `df -h` on the host.

## Where to get help

- Search the issue tracker: <https://github.com/vithurshanselvarajah/Mnemos/issues>
- Open a new issue with the version, the provider, the relevant `/healthz` payload, and the relevant logs.
- For security issues, see [Security](https://github.com/vithurshanselvarajah/Mnemos/wiki/Security#reporting-a-vulnerability).

---

## For developers

### Where the diagnostic surfaces live

- **`/healthz`** — the at-a-glance state. The richest field is `nvidia` (for provider-specific diagnostics). Always include this in a bug report.
- **Backend logs** — `docker compose logs mnemos-backend`. The structured logger writes to stdout in JSON by default; switch to text with `MNEMOS_LOG_LEVEL=INFO` for human-readable output.
- **Frontend logs** — `docker compose logs mnemos-frontend`. Same format.
- **Reindex state** — `GET /api/v1/models` returns the current snapshot. Use it to drive a progress bar in your own UI.
- **WebSocket events** — every state change publishes a typed event. Subscribe to debug a live system.
