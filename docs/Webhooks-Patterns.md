# Webhooks / Inbox Patterns

This page shows common patterns for building integrations on top of the `ws://…/ws/events` WebSocket and the `/api/v1/identify` endpoint. Pick a pattern, copy it, adapt it.

- [Pattern 1: live inbox dashboard](#pattern-1-live-inbox-dashboard)
- [Pattern 2: per-person notification on a new sample](#pattern-2-per-person-notification-on-a-new-sample)
- [Pattern 3: forward recognise events to Home Assistant](#pattern-3-forward-recognise-events-to-home-assistant)
- [Pattern 4: dead-letter queue for failed crops](#pattern-4-dead-letter-queue-for-failed-crops)
- [Pattern 5: model-state alarm](#pattern-5-model-state-alarm)

---

## Pattern 1: live inbox dashboard

A WebSocket client that mirrors the inbox in real time without polling.

```python
import json
import websockets
import requests

API = "http://localhost:8000"
KEY = "mnemos_k_…"


def list_inbox(page=1):
    return requests.get(
        f"{API}/api/v1/faces/unassigned",
        params={"page": page, "page_size": 50},
        headers={"X-API-Key": KEY},
    ).json()


async def run():
    # Seed the UI with whatever is already in the inbox.
    initial = list_inbox()
    print(f"Initial inbox: {initial['total']} items")

    async with websockets.connect("ws://localhost:8000/ws/events") as ws:
        async for raw in ws:
            if raw == "pong":
                continue
            evt = json.loads(raw)
            if evt["type"] == "inbox.new_face":
                print(f"  + new: {evt['crop_id']}  → {evt['image_url']}")
            elif evt["type"] == "inbox.bulk_changed":
                # Re-fetch the inbox page because the state changed.
                inbox = list_inbox()
                print(f"  ↻ {evt['count']} changed, now {inbox['total']} unassigned")

import asyncio
asyncio.run(run())
```

The `inbox.bulk_changed` event doesn't carry the affected crop IDs — you have to re-fetch the listing. This is intentional: it keeps the event payload small and lets the server publish before the DB commit completes.

## Pattern 2: per-person notification on a new sample

Watch for "this is Alice" recognitions and fire a webhook.

The `/identify` response is the authoritative source for recognition. There is no WebSocket event for "a recognised face was seen" — the event only fires for **unassigned** crops. For per-person notifications, you have two options:

**Option A: call /identify yourself.** The cleanest path for camera integrations. You have full control over the trigger (motion event, scheduled poll, etc.) and the response is the recognised faces.

**Option B: poll the inbox.** Cheaper for low-traffic setups. The inbox is by definition only the unknowns, so this doesn't help you detect *new* recognitions — but it does let you detect *deletions* of assigned crops (the next time the same face is unknown, the recognition stops happening).

For the home workload, Option A is the right call.

## Pattern 3: forward recognise events to Home Assistant

A tiny Python service that bridges Mnemos to an HA `rest_command`.

```python
import requests
from fastapi import FastAPI, File, UploadFile, HTTPException

app = FastAPI()
MNEMOS = "http://localhost:8000"
MNEMOS_KEY = "mnemos_k_…"
HA_WEBHOOK = "http://homeassistant:8123/api/webhook/mnemos_event"

@app.post("/ha/snapshot")
def ha_snapshot(file: UploadFile = File(...)):
    # Call Mnemos /identify
    r = requests.post(
        f"{MNEMOS}/api/v1/identify",
        headers={"X-API-Key": MNEMOS_KEY},
        files={"file": (file.filename, file.file, file.content_type)},
        timeout=30,
    )
    r.raise_for_status()
    body = r.json()

    # Forward to HA
    requests.post(
        HA_WEBHOOK,
        json={
            "recognized": body["recognized"],
            "unknown_count": body["unknown_count"],
        },
        timeout=5,
    )

    return {"ok": True, "recognized": [m["name"] for m in body["recognized"]]}
```

Run it as a sidecar container in the compose file, expose port 8001, point Home Assistant at it. HA calls `/ha/snapshot` with the camera's JPEG; the service runs `/identify` and forwards the recognised names to an HA webhook which fires an automation.

## Pattern 4: dead-letter queue for failed crops

If you have a camera that intermittently sends bad JPEGs, you want to be able to retry. Mnemos already retries the model download, but the `/identify` endpoint itself doesn't retry — a failed decode returns 400 and the JPEG is lost.

The cleanest pattern is to wrap the call:

```python
import time
import requests
from pathlib import Path

DEAD_LETTER = Path("/var/log/mnemos/dead-letter")
DEAD_LETTER.mkdir(parents=True, exist_ok=True)


def identify_with_retry(path: Path, max_tries=3):
    for attempt in range(1, max_tries + 1):
        try:
            with path.open("rb") as f:
                r = requests.post(
                    "http://localhost:8000/api/v1/identify",
                    headers={"X-API-Key": "mnemos_k_…"},
                    files={"file": (path.name, f, "image/jpeg")},
                    timeout=30,
                )
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, requests.HTTPError) as e:
            if attempt == max_tries:
                # Park the file for manual inspection.
                target = DEAD_LETTER / f"{int(time.time())}_{path.name}"
                path.rename(target)
                raise
            time.sleep(2 ** attempt)
```

The dead-letter directory is then easy to triage (`ls -ltr`) and you can re-run the failed files once you've figured out what was wrong.

## Pattern 5: model-state alarm

Watch the WebSocket for any non-`done` / non-`progress` event during a warmup or reindex and trigger an alert.

```python
import json
import websockets
import smtplib
from email.message import EmailMessage


def alert(subject: str, body: str):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = "mnemos@example.com"
    msg["To"] = "you@example.com"
    msg.set_content(body)
    with smtplib.SMTP("localhost") as s:
        s.send_message(msg)


async def watch():
    last_done = 0
    stuck_for = 0
    async with websockets.connect("ws://localhost:8000/ws/events") as ws:
        async for raw in ws:
            if raw == "pong":
                continue
            evt = json.loads(raw)
            t = evt.get("type", "")

            if t == "warmup.error" or t == "reindex.error":
                alert(f"Mnemos: {t}", json.dumps(evt, indent=2))

            if t == "reindex.progress":
                if evt["done"] == last_done:
                    stuck_for += 1
                    if stuck_for > 30:  # 30 progress events without movement
                        alert(
                            "Mnemos: reindex appears stuck",
                            f"done={evt['done']} total={evt['total']}",
                        )
                else:
                    stuck_for = 0
                last_done = evt["done"]
```

This is the most "operational" of the patterns. Drop it into a systemd timer, run it on a small VM, and you'll get an email if Mnemos is having a bad day.

---

## For developers

### Why no webhook delivery in Mnemos itself

A "Mnemos calls out to a URL when X happens" feature is small to write but large to operate: retries, exponential backoff, dead-letter storage, idempotency keys, signing, replay. The current design is the opposite: Mnemos publishes events; the operator's integration is responsible for delivery. This is the same shape as a message queue — easier to scale, easier to debug, no hidden state in Mnemos.

If you really want server-push delivery, the patterns above are 20-30 lines each. The official integration story will be documented when there's a common shape that benefits everyone.
