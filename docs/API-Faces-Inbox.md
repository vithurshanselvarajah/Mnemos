# Inbox (Faces)

The Inbox is the list of every face Mnemos has detected but couldn't confidently match. It's a list of `FaceCrop` records with status `UNASSIGNED`. Use these endpoints to triage: assign to a known person, mark as non-face, or ignore.

- [Face crop output](#face-crop-output)
- [List unassigned](#list-unassigned)
- [Assign](#assign)
- [Mark as non-face](#mark-as-non-face)
- [Ignore](#ignore)
- [WebSocket events](#websocket-events)

---

## Face crop output

Every crop endpoint returns this shape:

```json
{
  "id": "7c4a…",
  "person_id": null,
  "image_url": "/api/v1/crops/7c4a….jpg",
  "bounding_box": [120, 80, 220, 200],
  "det_score": 0.91,
  "status": "UNASSIGNED",
  "created_at": "2026-07-25T10:30:00Z"
}
```

| Field | Meaning |
| --- | --- |
| `id` | UUID. Use this to reference the crop in `assign` / `mark-non-face` / `ignore` |
| `person_id` | `null` for unassigned; the person's UUID once assigned |
| `image_url` | Path to the cropped JPEG (fetch with `X-API-Key`, see [Crops](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Crops)) |
| `bounding_box` | `[x1, y1, x2, y2]` in pixel coords of the **source** image |
| `det_score` | Detector confidence, 0-1 |
| `status` | `UNASSIGNED`, `ASSIGNED`, `NON_FACE`, or `IGNORED` |
| `created_at` | When the crop was first detected |

## List unassigned

```http
GET /api/v1/faces/unassigned?page=1&page_size=24
```

```bash
curl -s -H "X-API-Key: $KEY" "http://localhost:8000/api/v1/faces/unassigned?page=1&page_size=24" | jq
```

| Param | Default | Range | Notes |
| --- | --- | --- | --- |
| `page` | 1 | ≥ 1 | 1-indexed |
| `page_size` | 24 | 1-200 | Hard upper limit is 200 to avoid OOMing the response |
| `count_only` | `false` | — | Return only `{total, page: 1, page_size: 0, items: []}` without materialising the page. Cheap for polling clients (e.g. Home Assistant) that only need the count. |

Returns:

```json
{
  "total": 137,
  "page": 1,
  "page_size": 24,
  "items": [ { ...FaceCrop... }, ... ]
}
```

Ordered by `created_at DESC` (newest first).

**Count-only example:**

```bash
curl -s -H "X-API-Key: $KEY" "http://localhost:8000/api/v1/faces/unassigned?count_only=true" | jq
# { "total": 137, "page": 1, "page_size": 0, "items": [] }
```

## Assign

```http
POST /api/v1/faces/assign
Content-Type: application/json
X-API-Key: <any key>

{
  "crop_ids": ["7c4a…", "8d5e…"],
  "person_id": "9f1b…"
}
```

OR

```json
{
  "crop_ids": ["7c4a…", "8d5e…"],
  "new_person_name": "Alice"
}
```

Provide **one** of `person_id` or `new_person_name`. If both or neither, the request is rejected with 400. `crop_ids` must be non-empty.

Side effects:

- The crop(s) get `person_id` set and `status` = `ASSIGNED`.
- The person's averaged embedding is rebuilt (mean of all their `ASSIGNED` crops, L2-normalised) and re-inserted into pgvector under the active model.
- A `inbox.bulk_changed` event is published on the WebSocket.

Returns:

```json
{
  "ok": true,
  "person_id": "9f1b…",
  "count": 2,
  "person": { "id": "9f1b…", "name": "Alice" }
}
```

If any of the `crop_ids` don't exist, returns 404.

## Mark as non-face

```http
POST /api/v1/faces/mark-non-face
Content-Type: application/json
X-API-Key: <any key>

{ "crop_ids": ["7c4a…"] }
```

Sets status to `NON_FACE`, removes the crop from the vector index (it had no person, so no averaging impact). The crop JPEG stays on disk. Re-uploading the same source image will produce a new detection and a new crop — there's no "learned negatives" memory.

Use this for false positives: a pattern that the detector thinks is a face but isn't.

## Ignore

```http
POST /api/v1/faces/ignore
Content-Type: application/json
X-API-Key: <any key>

{ "crop_ids": ["7c4a…"] }
```

Sets status to `IGNORED`. The crop is hidden from the inbox but kept in the database. Use this when you're not sure if a crop is a face or a misdetection — `NON_FACE` is permanent in spirit, `IGNORED` is "parked here for now."

## WebSocket events

The inbox endpoints publish a single WebSocket event:

```json
{ "type": "inbox.bulk_changed", "count": 2, "person_id": "9f1b…" }
```

`count` is the number of crops affected. `person_id` is included on `assign` only. See [WebSocket Events](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-WebSocket).

---

## For developers

### Why `UNASSIGNED` and not `INBOX`

The status field is a small enum, not a workflow. `UNASSIGNED` is the entry state for every crop; `ASSIGNED` is the terminal state for known people; `NON_FACE` and `IGNORED` are terminal states for rejections. The "inbox" is just a SQL filter on `status = UNASSIGNED` — no separate table, no separate index. This keeps the schema simple and means every state transition is a single `UPDATE`.

### Why rebuild the average on every assign

The averaged embedding is the only vector indexed for the person. If we did incremental updates (e.g. running mean) we'd need to keep the per-crop count and sum vectors, then serialise them to disk. The simpler implementation is to re-embed every assigned crop on every change. Crops are JPEGs on local disk and embedding is sub-second per face on CPU, so the cost is acceptable for typical home use (a few hundred crops per person). When it stops being acceptable, see [Performance](https://github.com/vithurshanselvarajah/Mnemos/wiki/Troubleshooting#performance) for the upgrade path.

### Concurrency

Two simultaneous `assign` calls for the same person will both rebuild the average. The last one wins. There is no locking; the rebuild reads from the database, computes the mean, and writes the new vector. If a third call lands in between, it may see a partially-stale view. For the home workload this is acceptable. For higher concurrency, see the future-work note in [Architecture](https://github.com/vithurshanselvarajah/Mnemos/wiki/Architecture).
