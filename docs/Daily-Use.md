# Daily Use

Once you've got past [First Run](https://github.com/vithurshanselvarajah/Mnemos/wiki/First-Run), the typical Mnemos workflow looks like this.

- [The Inbox](#the-inbox)
- [Labelling a new person](#labelling-a-new-person)
- [Adding more photos of the same person](#adding-more-photos-of-the-same-person)
- [Renaming or merging duplicates](#renaming-or-merging-duplicates)
- [Marking non-faces and ignored crops](#marking-non-faces-and-ignored-crops)
- [Per-person thresholds](#per-person-thresholds)
- [Switching the detection model](#switching-the-detection-model)
- [Rotating the master key](#rotating-the-master-key)

---

## The Inbox

The dashboard's "Inbox" page shows every face Mnemos has detected but couldn't match against a known person. Each entry is a single cropped face JPEG, sorted newest-first.

- **Status** — `UNASSIGNED` (waiting for you), `ASSIGNED` (linked to a person), `NON_FACE` (false positive), `IGNORED` (not a face we care about).
- **Bounding box** — the original detection's coordinates, drawn on the source image.
- **Detection score** — how confident the detector was, 0-1. Below `MNEMOS_MIN_FACE_PX` the crop is dropped before it ever hits the inbox.

The inbox auto-updates: the backend pushes `inbox.new_face` and `inbox.bulk_changed` events to `ws://…/ws/events`, and the dashboard subscribes via [WebSocket Events](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-WebSocket). You don't need to refresh.

---

## Labelling a new person

1. Open the inbox.
2. Click a face you want to label.
3. In the side panel, click **Assign to new person**.
4. Type the name. Names are case-insensitively unique; you cannot create two people called "Alice" and "alice".
5. Submit.

Behind the scenes Mnemos:

- Sets the crop's `person_id` and status to `ASSIGNED`.
- Builds an averaged embedding for the person (mean of all their assigned crops, L2-normalised).
- Writes that vector into pgvector under the current model name.
- Publishes `inbox.bulk_changed` to the WebSocket so other dashboard sessions refresh.

The next time a photo containing this person is uploaded to `/identify`, the averaged embedding is the closest match and the face is reported as `recognized` with the person's name and a confidence score.

---

## Adding more photos of the same person

Drop more photos via the same `/identify` endpoint. For each new detection:

- If it's confidently the same person, the new crop is **also** routed into the inbox as `UNASSIGNED`. This is intentional — you decide whether it's a new sample.
- If you want to bulk-accept: open the inbox, select multiple crops, choose **Assign to existing person**, pick the name. The averaged embedding is recomputed across all assigned samples.

A good rule of thumb: 3-5 well-lit, front-facing samples per person gives 95%+ accuracy. More helps; the diminishing return kicks in around 10.

---

## Renaming or merging duplicates

If you accidentally created two people ("Alice" and "alice smith") with the same face:

1. Pick one to keep (the older one is usually safest).
2. Open the duplicate's detail page, click **Delete person**. The duplicate's crops are returned to the inbox as `UNASSIGNED`. They are **not** deleted.
3. Re-assign those crops to the kept person from the inbox. The kept person's averaged embedding is recomputed across all of them.

There is no atomic "merge" because merges are lossy — by returning the crops to the inbox you can re-review them and drop any that aren't actually the same person.

To rename: detail page → **Edit** → change the name. Existing crops keep their assignment.

---

## Marking non-faces and ignored crops

If the inbox fills up with the same misdetection over and over (a wall pattern that looks like a face, a logo, etc.):

- **Mark non-face** — tells the system "this isn't a face, ever." The crop is removed from the vector index. Re-uploading the same image will still produce a detection, but the saved crop will be deleted.
- **Ignore** — softer than non-face. The crop is archived but the original detection is kept. Use this when you're not sure yet.

Neither is permanent. Both can be reversed by re-uploading the source image.

---

## Per-person thresholds

Each person has an optional `custom_threshold`. If set, it overrides `MNEMOS_DEFAULT_THRESHOLD` for that person only.

When to use it:

- A person has a twin or very-similar sibling → raise the threshold (stricter).
- A person is consistently detected at low confidence (looking away, partial occlusion) → lower the threshold (more lenient).

Set it from the person detail page or `PATCH /api/v1/persons/{id}` with `{"custom_threshold": 0.25}`.

---

## Switching the detection model

1. Open the **Models** page.
2. Pick a model: `buffalo_s` (fast), `buffalo_m` (balanced), `buffalo_l` (accurate).
3. Click **Switch**. The download + reindex starts in a background thread.

While it runs:

- `/identify` keeps serving on the current model.
- The dashboard shows a live progress bar sourced from `reindex.start` → `reindex.progress` → `reindex.done` WebSocket events.
- The averaged embeddings for every person are recomputed under the new model.

Reindex time is roughly: `(<number of crops> × 0.05s) + 30s download`. For 1,000 crops on CPU, expect about 1-2 minutes. For 10,000 crops, 10-20 minutes. NVIDIA cuts this ~5-10×.

The active model setting is persisted across restarts.

---

## Rotating the master key

If you think the master key has leaked:

```bash
docker exec -it mnemos-backend python -m app.cli master-key rotate
```

A new key is generated and overwrites the old one. Existing API keys are unaffected. You do not need to re-pair the frontend unless the frontend's Full-Admin key was the one that leaked, in which case revoke it from the **Keys** page and re-pair.

---

## For developers

### Why a hard inbox?

The alternative is "auto-cluster" — group similar unknown faces and ask "are these all the same person?" Mnemos deliberately doesn't do that. Auto-clustering errors compound: a single mis-merge poisons every future match for that person. Keeping each unknown crop as an individual unit means a human is always in the loop on the first time we see a face.

### Why averaged embeddings instead of per-crop

The vector index is one row per person per model, not one per crop. This means `/identify` is a single nearest-neighbour query instead of a k-NN merge across the person's gallery. The averaged vector is L2-normalised after each assignment so adding more samples doesn't blow up the magnitude.

Trade-off: if a person has 50 samples of mostly the same angle, the averaged vector is over-fitted to that angle. The remedy is to curate the assigned crops — Mnemos's `best_det_score` ordering in the UI makes it easy to drop the bottom half.

### Live UI without polling

The WebSocket hub (`app.services.websocket_hub`) is a process-local broadcast. Every backend action that changes state publishes a small JSON event:

- `inbox.new_face` — single new crop
- `inbox.bulk_changed` — bulk operation (assign, mark-non-face, ignore)
- `reindex.*` — model switch progress
- `warmup.*` — model warmup progress (includes `download` sub-events with `artifact` filename)

The frontend subscribes once on dashboard load and patches the DOM via HTMX partial swaps. No client-side state to keep in sync.
