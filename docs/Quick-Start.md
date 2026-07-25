# Quick Start

Get from zero to a working Mnemos stack in five minutes. If anything here is unclear, see the full [Installation](https://github.com/vithurshanselvarajah/Mnemos/wiki/Installation) page.

## What you need

- A Linux host (Ubuntu 24.04 is what we test on), macOS, or Windows + WSL2
- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/) v2+
- About 2 GB of free disk space for the base images and the small InsightFace model
- Ports 8000 (backend API) and 8080 (frontend UI) free on the host

## 1. Get the compose file

For a production install, download the release artifacts (do **not** just clone the repo):

```bash
mkdir mnemos && cd mnemos
curl -L -O https://github.com/vithurshanselvarajah/Mnemos/releases/latest/download/docker-compose.yml
curl -L -O https://github.com/vithurshanselvarajah/Mnemos/releases/latest/download/.env.example
cp .env.example .env
```

For a developer install, clone the repo and use `docker-compose.dev.yml` (see [Installation](https://github.com/vithurshanselvarajah/Mnemos/wiki/Installation#from-source)).

## 2. Edit two secrets

Open `.env` and change at least:

```dotenv
MNEMOS_PG_PASSWORD=your-random-pg-password-here
MNEMOS_FE_SECRET=$(openssl rand -hex 32)
```

See [Configuration](https://github.com/vithurshanselvarajah/Mnemos/wiki/Configuration#secrets) for what every variable does.

## 3. Pull and start

```bash
docker compose pull
docker compose up -d
```

Watch the first boot:

```bash
docker compose logs -f
```

The first start downloads the `buffalo_s` detection model (~300 MB). The backend will refuse to accept traffic until the warmup finishes (usually under a minute on a modern CPU).

## 4. Read the master pairing key

The backend generates a one-time secret the first time it starts and stores it in its database. You need it once to bootstrap the admin:

```bash
docker exec -it mnemos-backend python -m app.cli master-key view
```

Copy the value it prints.

## 5. Open the UI and finish onboarding

Open `http://localhost:8080` in a browser. You'll be taken straight to the onboarding wizard:

1. **Create the first admin** — username and password (Argon2id hashed, 8 hours session lifetime).
2. **Pair with the backend** — paste the master key from step 4. The frontend exchanges it for a Full-Admin API key and stores it.

That's it. You're done. Next:

- Upload a test image to `/api/v1/identify` to see detection working.
- Open the dashboard to review the inbox of unknown faces.
- See [Daily Use](https://github.com/vithurshanselvarajah/Mnemos/wiki/Daily-Use) for the typical workflow.

## Verifying it works

```bash
curl -s http://localhost:8000/healthz | jq
curl -s http://localhost:8080/healthz | jq
```

Both endpoints return JSON with a `status` field that should read `"ok"`. The frontend's response includes the backend's payload so a single `curl` shows the state of the whole stack.

See [Health & Versioning](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Health) for the full payload shape.

## What's next?

| You want to… | Read |
| --- | --- |
| Integrate Mnemos with Home Assistant, Node-RED, n8n, etc. | [API Overview](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Overview) and [API Identify](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Identify) |
| Tune detection accuracy | [Models](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Models), [Configuration](https://github.com/vithurshanselvarajah/Mnemos/wiki/Configuration) |
| Run on NVIDIA GPU or Rockchip NPU | [Providers](https://github.com/vithurshanselvarajah/Mnemos/wiki/Providers) |
| Back up your data | [Backup & Restore](https://github.com/vithurshanselvarajah/Mnemos/wiki/Backup-Restore) |
| Something is broken | [Troubleshooting](https://github.com/vithurshanselvarajah/Mnemos/wiki/Troubleshooting) |

---

## For developers

The `docker compose up -d` flow above pulls three prebuilt images from `ghcr.io/vithurshanselvarajah/mnemos-*`. Image tags encode the inference provider:

- `…/mnemos-backend:latest-cpu` — CPU ONNX Runtime
- `…/mnemos-backend:latest-nvidia` — CUDA ONNX Runtime (needs NVIDIA driver + container toolkit on the host)
- `…/mnemos-backend:latest-rockchip` — RKNN runtime (needs a Rockchip SoC, e.g. rk3588)

`MNEMOS_PROVIDER` in `.env` picks which one to run. The matching multi-stage build in `mnemos-backend/Dockerfile` uses `INSTALL_PROVIDER` and `BASE_IMAGE` build args to swap the inference stack; only the runtime libraries and onnxruntime variant change, the rest of the backend is byte-identical.

The frontend image has no provider variant — it talks to the backend over HTTP and is provider-agnostic.
