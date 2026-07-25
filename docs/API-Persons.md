# Persons

Persons are the people Mnemos knows. Each person has a name, an optional custom threshold, and a set of assigned face crops. Their averaged embedding is computed and stored in pgvector under the active model.

- [Data model](#data-model)
- [List](#list)
- [Get one](#get-one)
- [Create](#create)
- [Update (rename / set custom threshold)](#update-rename--set-custom-threshold)
- [Delete](#delete)
- [List a person's crops](#list-a-persons-crops)
- [Custom thresholds explained](#custom-thresholds-explained)

---

## Data model

| Field | Type | Notes |
| --- | --- | --- |
| `id` | UUID | Server-assigned |
| `name` | string | Case-insensitively unique within the database |
| `custom_threshold` | float \| null | Per-person cosine distance threshold; overrides the global default. `null` means use the global |
| `sample_count` | int | Number of `ASSIGNED` crops (computed; not stored) |
| `thumbnail_url` | string \| null | URL of the highest-`det_score` assigned crop; used as the avatar in the UI |
| `best_det_score` | float | 0-1 confidence of the thumbnail crop, 0 if the person has no assigned crops |
| `created_at` | datetime | ISO 8601 |
| `updated_at` | datetime | ISO 8601, bumped on any rename or threshold change |

> A person with zero assigned crops still exists. Their averaged embedding has been removed from pgvector (or never written). They will not match any `/identify` call.

## List

```http
GET /api/v1/persons
```

```bash
curl -s -H "X-API-Key: $KEY" http://localhost:8000/api/v1/persons | jq
```

Returns an array, alphabetical by name. Each entry includes `sample_count`, `thumbnail_url`, and `best_det_score`.

## Get one

```http
GET /api/v1/persons/{id}
```

```bash
curl -s -H "X-API-Key: $KEY" http://localhost:8000/api/v1/persons/9f1b… | jq
```

Returns 404 if not found.

## Create

```http
POST /api/v1/persons
Content-Type: application/json
X-API-Key: <Full-Admin>

{ "name": "Alice", "custom_threshold": null }
```

```bash
curl -s -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"name": "Alice"}' http://localhost:8000/api/v1/persons | jq
```

- `name` is required and stripped of leading/trailing whitespace. Empty after stripping → 400.
- `custom_threshold` is optional. If omitted, the person uses the global threshold.
- Names are case-insensitively unique. Creating "alice" when "Alice" exists returns 409.

## Update (rename / set custom threshold)

```http
PATCH /api/v1/persons/{id}
Content-Type: application/json
X-API-Key: <Full-Admin>

{ "name": "Alice Smith", "custom_threshold": 0.30 }
```

Both fields are optional. Pass `null` for `custom_threshold` to revert to the global default.

Rename rules are the same as create: case-insensitively unique, non-empty after strip, 409 on collision.

## Delete

```http
DELETE /api/v1/persons/{id}
X-API-Key: <Full-Admin>
```

Deleting a person:

- Unlinks all of their assigned crops (sets `person_id` to `null`, status back to `UNASSIGNED`). The crop JPEGs are **not** deleted.
- Removes the person's averaged embedding from pgvector under every model.

The crops are returned to the inbox. This is intentional: it lets you re-review them and either reassign to a different person or mark as non-face. There is no "merge two people" endpoint because merges are lossy.

## List a person's crops

```http
GET /api/v1/persons/{id}/crops
```

Returns the assigned crops for the person, ordered by detection score (highest first), then by creation time. Each crop is a [`FaceCropOut`](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Faces-Inbox#face-crop-output).

```bash
curl -s -H "X-API-Key: $KEY" http://localhost:8000/api/v1/persons/9f1b…/crops | jq
```

## Custom thresholds explained

The global `MNEMOS_DEFAULT_THRESHOLD` is the cosine distance below which a face counts as a match. Default 0.40 (i.e. ≥ 60% similarity).

If a person has `custom_threshold`, that value is used **only** when the top match is that person. So Alice can be matched at 0.30 while Bob uses the global 0.40.

Useful when:

- A person has a lookalike (sibling, twin) — raise their threshold (stricter) to avoid cross-matches.
- A person is consistently detected at low confidence (profile shots, hats, glasses) — lower their threshold (more lenient).

The value must be in `[0.0, 1.0]`. Values outside the range return 400.

---

## For developers

### Why case-insensitive unique

Users will create "Alice" and then try to create "alice" because their camera pipeline lowercased the name. Making the unique check case-insensitive at the storage layer prevents the UI from showing two "Alice" entries that differ only in capitalisation. Display always uses the originally-cased name.

### Why no merge endpoint

A merge is "for every crop in B, set `person_id` = A.id, then delete B." A bulk version of that is straightforward to write, but the bulk operation is also the one that hides mistakes: if a crop was miscategorised, the bulk merge propagates the error. By returning B's crops to the inbox, we force a human to look at them again.

### Storage details

- `Person` is a SQLModel class in `app.models.entities`.
- `name` has a `func.lower()`-based unique index.
- `custom_threshold` is a `float | None` column.
- The averaged embedding is **not** stored on the `Person` row — it lives in pgvector with a composite key `(person_id, model_name)` in the `face_embeddings` table. The averaging itself is recomputed on every assignment and every model switch.

See [Storage Layout](https://github.com/vithurshanselvarajah/Mnemos/wiki/Storage-Layout) for the full schema and [Services Reference](https://github.com/vithurshanselvarajah/Mnemos/wiki/Services-Reference#rebuild_person_averaged) for the rebuild function.
