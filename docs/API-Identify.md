# Identify

`POST /api/v1/identify` is the endpoint you'll call from a camera, an automation script, or a webhook from Home Assistant. Send it a photo, get back a list of every face Mnemos recognised and every face it didn't.

- [Request](#request)
- [Response](#response)
- [Matching algorithm](#matching-algorithm)
- [Crop deduplication](#crop-deduplication)
- [Errors](#errors)
- [Examples](#examples)

---

## Request

```http
POST /api/v1/identify
Content-Type: multipart/form-data
X-API-Key: <key>

file=@photo.jpg
```

The form field is `file` and must be a single image. Accepted formats: JPEG, PNG, WebP. Maximum size: not enforced server-side but OpenCV's `imdecode` is memory-bound — a 20 MB JPEG is fine, a 200 MB one will OOM the worker.

## Response

```json
{
  "recognized": [
    {
      "person_id": "9f1b…",
      "name": "Alice",
      "confidence": 0.83,
      "image_url": "/api/v1/crops/<uuid>.jpg"
    }
  ],
  "unknown_count": 1,
  "unknown_faces": [
    {
      "crop_id": "7c4a…",
      "image_url": "/api/v1/crops/<uuid>.jpg",
      "bounding_box": [120, 80, 220, 200],
      "det_score": 0.91
    }
  ],
  "duplicates_skipped": 0
}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `recognized[].person_id` | UUID | The matched person's ID |
| `recognized[].name` | string | The matched person's name |
| `recognized[].confidence` | float (0-1) | Cosine **similarity** (`1 - cosine_distance`). 0.83 = the person is 83% similar to the matched reference vector |
| `recognized[].image_url` | string | A representative crop of the matched person (highest detection score among their assigned crops) |
| `unknown_count` | int | How many faces were detected but didn't match anyone |
| `unknown_faces[]` | object | Per unknown face: `crop_id` (UUID), `image_url`, `bounding_box` (4 floats: `x1, y1, x2, y2` in pixel coords of the source image), `det_score` (0-1) |
| `duplicates_skipped` | int | How many near-identical unknown faces within the same request were collapsed (see below) |

A face that is confidently below `MNEMOS_MIN_FACE_PX` (default 30px on either side) is dropped **before** the response is built — it never appears as an unknown and never enters the inbox. Raise the threshold to reduce noise on high-resolution photos.

## Matching algorithm

Mnemos does cosine similarity over 512-D L2-normalised embeddings. The active model is whatever is currently set in the backend (`MNEMOS_DEFAULT_MODEL` on first boot, changeable at runtime via [Models](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Models)).

1. Detect all faces in the image with the active model.
2. Drop any detection smaller than `MNEMOS_MIN_FACE_PX` on either side.
3. Drop near-duplicate detections within the same request (IoU ≥ 0.80 AND cosine distance ≤ 0.04 → merged, keep the higher `det_score`).
4. For each surviving detection, embed the face → 512-D vector.
5. Query pgvector for the 3 nearest neighbours across **every** known person under the current model.
6. The top result is a match iff:
   - the cosine **distance** to the top hit is ≤ `MNEMOS_DEFAULT_THRESHOLD` (default 0.40, i.e. ≥ 60% similarity), OR
   - the matched person has a `custom_threshold` and the distance is within that.
7. Crops that don't match anyone are saved (with `MNEMOS_CROP_PAD_FRACTION` extra padding, default 50%) to `/data/crops/<uuid>.jpg` and entered into the inbox as `UNASSIGNED`.

A single image with two faces can produce two `recognized` entries, two `unknown_faces` entries, or any mix. There is no per-image aggregation.

## Crop deduplication

Two layers of dedup, both tunable in code:

- **Within-request** — a group of detections with IoU ≥ 0.80 AND cosine distance ≤ 0.04 is collapsed to a single entry. The highest-`det_score` one wins. This stops the detector from returning the same face five times.
- **Cross-request** — when a new unknown crop is saved, Mnemos checks the most-recent 5 unassigned crops with the same image hash and similar bbox. If one matches, the new detection is associated with the existing `crop_id` instead of creating a new row. This is what stops the inbox from filling up with the same notification photo processed twice.

`duplicates_skipped` in the response counts the within-request collapses.

## Errors

| Code | Reason |
| --- | --- |
| 400 | Image could not be decoded (unsupported format, corrupt) |
| 401 | Missing or invalid API key |
| 413 | (Not enforced — see request size note above) |
| 503 | Model not loaded; the backend cannot embed yet. Retry after `model_loaded: true` in `/healthz` |

> While the backend is downloading or warming up the model, `/identify` will return 503. The dashboard's status pill mirrors this. Don't hammer the endpoint during warmup — wait for the `warmup.done` WebSocket event.

## Examples

### cURL

```bash
KEY="mnemos_k_…"
curl -s -X POST http://localhost:8000/api/v1/identify \
  -H "X-API-Key: $KEY" \
  -F "file=@/path/to/photo.jpg" | jq
```

### Python

```python
import requests

with open("photo.jpg", "rb") as f:
    r = requests.post(
        "http://localhost:8000/api/v1/identify",
        headers={"X-API-Key": "mnemos_k_…"},
        files={"file": f},
        timeout=30,
    )
r.raise_for_status()
body = r.json()
for hit in body["recognized"]:
    print(f"Recognised: {hit['name']} ({hit['confidence']:.0%})")
for unknown in body["unknown_faces"]:
    print(f"Unknown: see {unknown['image_url']}")
```

### Home Assistant

A `shell_command` (or a `python_script`) is the cleanest integration. Example:

```yaml
shell_command:
  mnemos_identify: >
    curl -s -X POST http://mnemos-backend:8000/api/v1/identify
    -H "X-API-Key: !secret mnemos_key"
    -F "file=@/config/www/snapshot.jpg"
```

### Node-RED

Use an `http request` node:

- Method: `POST`
- URL: `http://mnemos-backend:8000/api/v1/identify`
- Headers: `X-API-Key = <key>`
- Return: parsed JSON object

---

## For developers

### Why averaged embeddings

The vector index has one row per person per model, not one per crop. `/identify` is a single kNN query (limit=3) per detected face, returning at most 3 candidates; the top one is the match. This is much faster than searching over every crop.

The averaged vector is recomputed on every assignment operation (assign, mark-non-face, ignore) and on every model switch. The recomputation re-embeds every assigned crop from disk (`load_crop_jpeg` → `cv2.imdecode` → engine → mean → L2-normalise) so it always reflects the on-disk truth.

### Why cosine distance and not L2

Embeddings are L2-normalised so the L2 distance and the cosine distance are equivalent up to a constant. Cosine is more intuitive for users (0.0 = identical, 2.0 = opposite) and matches the InsightFace paper.

### How the cross-request dedup works

The dedup key is `(image_sha, bbox)`. `image_sha` is the SHA-256 of the uploaded image bytes. If two uploads have the same image bytes and a bounding box with IoU ≥ 0.80 to an existing UNASSIGNED crop, the new detection is associated with the existing `crop_id` rather than creating a new row. This catches the "same camera, same snapshot, posted twice" case.

If `image_sha` is missing (older clients) the dedup falls back to a vector similarity search with cosine distance ≤ 0.02. Slower, but works.
