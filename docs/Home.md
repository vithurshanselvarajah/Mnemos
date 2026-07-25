# Mnemos Wiki

> Pronounced **nee-MOZ** — Greek goddess of memory.

Mnemos is a self-hosted, Python-native facial recognition stack. It ingests photos, finds the faces in them, and tells you who each one is. When it doesn't recognise someone it saves the cropped face to an "inbox" so you can label it once and have every future photo recognise that person automatically.

This wiki is the canonical documentation. It syncs from the `docs/` folder in the [main repository](https://github.com/vithurshanselvarajah/Mnemos). If you find something missing or wrong, please open an issue.

---

## I just want to run it

1. [Quick Start](https://github.com/vithurshanselvarajah/Mnemos/wiki/Quick-Start) — get from zero to a working server in 5 minutes.
2. [Installation](https://github.com/vithurshanselvarajah/Mnemos/wiki/Installation) — Docker (production) vs. building from source.
3. [First Run](https://github.com/vithurshanselvarajah/Mnemos/wiki/First-Run) — pair the backend, create your admin, configure your first camera.
4. [Daily Use](https://github.com/vithurshanselvarajah/Mnemos/wiki/Daily-Use) — what the dashboard does and the typical workflow.

## I want to integrate with it

5. [API Overview](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Overview) — base URL, auth, conventions.
6. [Identify](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Identify) — `POST /identify` — the endpoint you probably came for.
7. [Persons](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Persons) — list / create / rename / delete.
8. [Inbox (Faces)](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Faces-Inbox) — assign, mark non-face, ignore.
9. [Models](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Models) — switch detection model, see reindex status.
10. [API Keys](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Keys) — mint, revoke, permission levels.
11. [WebSocket Events](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-WebSocket) — live `inbox.*` and `reindex.*` events.
12. [Health & Versioning](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Health) — `/healthz` payload, version negotiation.

## I want to host it

13. [Configuration](https://github.com/vithurshanselvarajah/Mnemos/wiki/Configuration) — every environment variable, with defaults.
14. [Providers (CPU / NVIDIA / Rockchip)](https://github.com/vithurshanselvarajah/Mnemos/wiki/Providers) — pick the right inference backend for your hardware.
15. [Backup & Restore](https://github.com/vithurshanselvarajah/Mnemos/wiki/Backup-Restore) — what to copy, what to throw away, how to migrate.
16. [Security](https://github.com/vithurshanselvarajah/Mnemos/wiki/Security) — authentication model, threat surface, hardening checklist.
17. [Troubleshooting](https://github.com/vithurshanselvarajah/Mnemos/wiki/Troubleshooting) — common errors and what they actually mean.
18. [FAQ](https://github.com/vithurshanselvarajah/Mnemos/wiki/FAQ) — short answers to questions that come up a lot.

## I want to develop it

19. [Architecture](https://github.com/vithurshanselvarajah/Mnemos/wiki/Architecture) — service boundaries, request lifecycles, data flow.
20. [Provider Internals](https://github.com/vithurshanselvarajah/Mnemos/wiki/Providers-Internals) — protocol, lockdown rules, the `_select_providers()` contract.
21. [Model Manifest & Weights](https://github.com/vithurshanselvarajah/Mnemos/wiki/Model-Manifest) — how artifact URLs / SHA-256 verification work.
22. [Storage Layout](https://github.com/vithurshanselvarajah/Mnemos/wiki/Storage-Layout) — SQLite, pgvector, crop directory, what lives where.
23. [Services Reference](https://github.com/vithurshanselvarajah/Mnemos/wiki/Services-Reference) — every module under `app/services/`.
24. [Webhooks / Inbox Patterns](https://github.com/vithurshanselvarajah/Mnemos/wiki/Webhooks-Patterns) — building integrations on top of `ws://…/ws/events`.
25. [Testing](https://github.com/vithurshanselvarajah/Mnemos/wiki/Testing) — how the test suite is structured, how to add a case, fixtures.
26. [Contributing](https://github.com/vithurshanselvarajah/Mnemos/wiki/Contributing) — workflow, code style, PR conventions.

---

## Project at a glance

- **Stack** — Python 3.14, FastAPI, InsightFace, pgvector, Jinja2 + HTMX + Alpine.js
- **Storage** — SQLite for relations, PostgreSQL 18 + pgvector for embeddings, JPEG on disk for face crops
- **License** — see [LICENSE](../LICENSE) in the repo root

## How to read this wiki

Every page is structured the same way:

1. **What this is** — a one-paragraph summary for end-users.
2. **How to do the common thing** — copy-pasteable examples.
3. **For developers** — internals, knobs, gotchas.

If you only read the first two sections you can use Mnemos. The third section is there when something breaks or you're extending it.
