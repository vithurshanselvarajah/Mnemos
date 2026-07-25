# WebSocket Events

The backend pushes live state changes over a single WebSocket endpoint. Use it to keep the dashboard, a custom UI, or a notification pipeline up to date without polling.

- [Connection](#connection)
- [Event format](#event-format)
- [Event types](#event-types)
- [Heartbeat](#heartbeat)
- [Client example](#client-example)

---

## Connection

```
ws://<host>:8000/ws/events
```

No authentication required. The endpoint is in the middleware's `EXCLUDED_PATHS` so it accepts any connection. The connection is long-lived — keep it open as long as you need updates.

The connection is process-local: the backend broadcasts events to every connected client. If you scale the backend to multiple workers, the broadcast is per-worker (a single event reaches clients on the same worker). For the home workload this is fine. For multi-worker setups, see [Architecture](https://github.com/vithurshanselvarajah/Mnemos/wiki/Architecture#future-work).

## Event format

Every event is a JSON object with a `type` field:

```json
{ "type": "inbox.new_face", "crop_id": "7c4a…", "image_url": "/api/v1/crops/7c4a….jpg" }
```

There is no envelope or sequence number. The backend publishes as events happen, not from a queue, so out-of-order delivery is theoretically possible (e.g. `inbox.bulk_changed` arriving before the `inbox.new_face` for one of the affected crops). For UI consumption this doesn't matter — the UI re-fetches state when it sees `inbox.bulk_changed`.

## Event types

### Inbox

- **`inbox.new_face`** — published when `/identify` saves a new unknown crop to disk.

  ```json
  { "type": "inbox.new_face", "crop_id": "7c4a…", "image_url": "/api/v1/crops/7c4a….jpg" }
  ```

- **`inbox.bulk_changed`** — published when one of the bulk endpoints (`assign`, `mark-non-face`, `ignore`) changes state.

  ```json
  { "type": "inbox.bulk_changed", "count": 2, "person_id": "9f1b…" }
  ```

  `person_id` is included only for `assign`. `count` is the number of crops affected.

### Warmup

- **`warmup.download`** — fires repeatedly during the model download.

  ```json
  { "type": "warmup.download", "model": "buffalo_l", "artifact": "buffalo_l.onnx", "done": 134217728, "total": 1073741824 }
  ```

  `done` / `total` are bytes.

- **`warmup.done`** — the model is loaded and ready to embed.

  ```json
  { "type": "warmup.done", "model": "buffalo_s" }
  ```

- **`warmup.error`** — the warmup failed; the model is not loaded.

  ```json
  { "type": "warmup.error", "model": "buffalo_s", "error": "ProviderNotAvailable: CUDAExecutionProvider missing" }
  ```

### Reindex

Same event names as warmup, with `reindex.` instead of `warmup.`, plus:

- **`reindex.preparing`** — old model unloaded, new model loading.

  ```json
  { "type": "reindex.preparing", "model": "buffalo_l" }
  ```

- **`reindex.download`** — same shape as `warmup.download` but for the reindex's model artifact download.

- **`reindex.start`** — reindex actually started, here's the total work.

  ```json
  { "type": "reindex.start", "model": "buffalo_l", "total": 1247 }
  ```

- **`reindex.progress`** — fires every N crops during the reindex.

  ```json
  { "type": "reindex.progress", "model": "buffalo_l", "done": 247, "total": 1247 }
  ```

- **`reindex.done`** — reindex completed; `/identify` now uses the new model.

  ```json
  { "type": "reindex.done", "model": "buffalo_l", "total": 1247 }
  ```

- **`reindex.error`** — reindex aborted; `/identify` is still using the old model.

  ```json
  { "type": "reindex.error", "model": "buffalo_l", "error": "OSError: disk full" }
  ```

## Heartbeat

Send `ping` as a text message; the server replies `pong`. Use this to detect dead connections from behind NAT or load balancers.

```javascript
ws.send("ping");
// → ws.onmessage receives "pong"
```

## Client example

### JavaScript (browser)

```javascript
const ws = new WebSocket("ws://localhost:8000/ws/events");

ws.onmessage = (ev) => {
  const evt = JSON.parse(ev.data);
  switch (evt.type) {
    case "inbox.new_face":
      console.log("New face:", evt.crop_id);
      break;
    case "reindex.progress":
      console.log(`Reindex ${evt.done}/${evt.total}`);
      break;
    case "warmup.done":
      console.log("Model ready:", evt.model);
      break;
  }
};

// Keep-alive
setInterval(() => ws.send("ping"), 30000);
```

### Python

```python
import json
import websockets

async def listen():
    async with websockets.connect("ws://localhost:8000/ws/events") as ws:
        async for raw in ws:
            if raw == "pong":
                continue
            evt = json.loads(raw)
            print(evt)

import asyncio
asyncio.run(listen())
```

---

## For developers

### Why a single endpoint and not one per topic

The number of distinct event types is small (~10), and clients usually want all of them. A single `/ws/events` endpoint with a typed payload is simpler than a topic-based pub/sub for this scale. If a future use case needs filtered subscriptions, the protocol can grow a `subscribe` message without breaking the existing one-way firehose.

### Why no auth on the WebSocket

The events are not sensitive. They tell you "a new unknown face was added" and "reindex is at 247/1247" — no person names, no embeddings, no file paths you couldn't guess. Treating the WebSocket as a public read-only firehose keeps browser-based UIs (the dashboard) simple: they connect once on page load, no token juggling, no per-tab re-auth.

If you want to expose the WebSocket over the public internet, put it behind the same reverse proxy + auth as the rest of the API. The backend has no built-in WSS / TLS termination — terminate at the proxy (Caddy, Traefik, nginx) and forward as `ws://` to the backend.

### Per-worker broadcast

`app.services.websocket_hub` is a process-local `set[WebSocket]`. When the backend is running with a single uvicorn worker (the default), every client sees every event. With multiple workers, the load balancer will send different clients to different workers, and an event published on worker A is not seen by clients on worker B.

For the home workload (one client, one worker) this is a non-issue. For larger deployments, the right fix is a Redis pub/sub fan-out — see [Architecture](https://github.com/vithurshanselvarajah/Mnemos/wiki/Architecture#future-work) for the design notes.
