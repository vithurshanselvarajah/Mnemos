# Crops

`GET /api/v1/crops/{uuid}.jpg` is the only way to fetch a face crop JPEG. The frontend proxies crop bytes from the backend; the bytes never come from the frontend's own volume.

- [Endpoint](#endpoint)
- [Filename format](#filename-format)
- [Caching](#caching)
- [Errors](#errors)
- [Examples](#examples)

---

## Endpoint

```http
GET /api/v1/crops/{uuid}.jpg
X-API-Key: <any key>
```

Returns the JPEG bytes of the requested crop, `Content-Type: image/jpeg`, with a `Cache-Control: private, max-age=300` header.

## Filename format

The filename is the crop's UUID followed by `.jpg`. For example, crop `7c4a8d09-ca38-4e2e-b27a-2c0e6a2c5e1f` is served at:

```
/api/v1/crops/7c4a8d09-ca38-4e2e-b27a-2c0e6a2c5e1f.jpg
```

The endpoint parses out the UUID by stripping the `.jpg` suffix and validating the remaining string as a UUID. Anything else returns 404.

## Caching

The `Cache-Control: private, max-age=300` header tells browsers and proxies to cache the response for 5 minutes. Crops are immutable once written (a crop's status can change, but its JPEG bytes don't), so a longer `max-age` would be safe. 5 minutes is short enough that a UI refresh after a bulk operation always sees the latest metadata, but the image bytes are usually served from the browser cache.

If you want stricter no-cache, the only way is to fetch via a custom proxy or to invalidate the browser cache. Mnemos has no `If-None-Match` / `ETag` support for crops.

## Errors

| Code | Reason |
| --- | --- |
| 401 | Missing or invalid API key |
| 404 | UUID didn't parse, crop doesn't exist, or the JPEG is missing from disk |
| 429 | Rate limit (in-memory, 600 req/min per source IP) |

A 404 from a known UUID but missing file is unusual — it means the SQLite row exists but the JPEG on disk was deleted out of band. Re-uploading the source image will create a new crop with a new UUID.

## Examples

### In a browser

```html
<img src="/api/v1/crops/7c4a8d09-ca38-4e2e-b27a-2c0e6a2c5e1f.jpg"
     alt="Unknown face"
     crossorigin="use-credentials">
```

> The frontend serves the UI on port 8080 but the API is on port 8000. The browser will hit the backend directly for crop images because `image_url` returned by the backend is a path-relative `/api/v1/crops/…`. You'll need to either (a) add a reverse proxy that maps `/api/v1/crops/` to the backend, or (b) include the backend base URL when rendering images. The bundled frontend does (a) via a server-side proxy.

### cURL

```bash
curl -s -H "X-API-Key: $KEY" \
  -o crop.jpg \
  http://localhost:8000/api/v1/crops/7c4a8d09-ca38-4e2e-b27a-2c0e6a2c5e1f.jpg
```

### Python (requests)

```python
import requests

r = requests.get(
    "http://localhost:8000/api/v1/crops/7c4a8d09-ca38-4e2e-b27a-2c0e6a2c5e1f.jpg",
    headers={"X-API-Key": "mnemos_k_…"},
)
r.raise_for_status()
with open("crop.jpg", "wb") as f:
    f.write(r.content)
```

---

## For developers

### Why server-side proxy and not direct serve

The frontend has no copy of the crop JPEGs. The crops live in the backend's volume, behind the API key, and behind the same auth as every other endpoint. The frontend's `backend_proxy` module is a thin reverse proxy that forwards `/api/v1/...` requests to the backend with the API key attached, then streams the response back. This means:

- The browser only talks to the frontend (one origin → no CORS).
- The API key never reaches the browser.
- A misconfigured frontend can't accidentally serve crops from its own (empty) volume.

### Storage layout

Crops are stored as `<MNEMOS_CROPS_DIR>/<uuid>.jpg` on the backend's volume. The directory is configured via `MNEMOS_CROPS_DIR` and defaults to `/data/crops`. Inside the container, the host directory is bind-mounted to `/data` (see [Storage Layout](https://github.com/vithurshanselvarajah/Mnemos/wiki/Storage-Layout)).

A bulk delete (`/api/v1/persons/{id}/crops/{crop_id}/delete`) removes the file from disk. A person-delete returns crops to the inbox but does **not** delete the files.

### The 600 req/min limit

The backend's in-memory rate limiter caps unauthenticated traffic at 600 req/min per source IP, applied before authentication. If you're scraping crops (don't, but if you must), batch via the inbox listing instead of fetching each one separately, and use HTTP keep-alive. The limit resets per minute.
