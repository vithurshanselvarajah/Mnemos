# Model Manifest & Weights

Mnemos doesn't ship model weights in the image. They're downloaded on first use from a manifest document that the backend fetches at startup. This page explains how that works and how to host your own mirror.

- [Why a manifest](#why-a-manifest)
- [The manifest document](#the-manifest-document)
- [The download lifecycle](#the-download-lifecycle)
- [Hosting your own mirror](#hosting-your-own-mirror)
- [Adding a new model](#adding-a-new-model)
- [Security model](#security-model)

---

## Why a manifest

A few reasons:

1. **Small images.** Buffalo_s alone is 300 MB. Buffalo_l is 1 GB. Bundling them in the image makes the image huge and forces a re-download on every image pull even when the user already has the weights locally.
2. **Versioning without re-tagging.** The manifest is a JSON document that can be updated without changing the image. If we want to ship a fixed version of `buffalo_s` weights, we update the manifest and point at a new URL.
3. **Provider awareness.** The same model name can resolve to different artifacts depending on the provider (CPU = ONNX, Rockchip = RKNN). The manifest encodes this per-provider.
4. **Reproducibility.** The manifest declares the exact SHA-256 of every artifact, so a download is verified before use.

The trade-off is one extra network fetch on startup (the manifest itself). That's cached in-memory for the lifetime of the process.

## The manifest document

Lives at `MNEMOS_MANIFEST_URL`. Default: the upstream GitHub-hosted JSON.

```json
{
  "base_url": "https://apps.selvarajah.co.uk/models",
  "models": {
    "buffalo_s": {
      "standard": {
        "detection": {
          "filename": "buffalo_s_det.onnx",
          "path": "/models/standard/buffalo_s_det.onnx",
          "size_bytes": 134217728,
          "sha256": "abc123…"
        },
        "recognition": {
          "filename": "buffalo_s_rec.onnx",
          "path": "/models/standard/buffalo_s_rec.onnx",
          "size_bytes": 167772160,
          "sha256": "def456…"
        }
      },
      "rknn": {
        "rk3588": { "detection": {…}, "recognition": {…} },
        "rk3576": { "detection": {…}, "recognition": {…} }
      }
    },
    "buffalo_l": { … },
    "buffalo_m": { … }
  }
}
```

### Schema

| Field | Type | Meaning |
| --- | --- | --- |
| `base_url` | string | Where artifacts live. Each artifact's `path` is appended to this. |
| `models.<name>.standard` | object | ONNX variants for CPU and NVIDIA. Has `detection` and `recognition` sub-objects. |
| `models.<name>.rknn.<soc>` | object | RKNN variants for Rockchip. The `<soc>` keys are the supported SoCs (e.g. `rk3588`, `rk3576`). Each has `detection` and `recognition` sub-objects. |
| `<artifact>.filename` | string | Filename as stored on disk. Used as a prefix key to find the right artifact. |
| `<artifact>.path` | string | URL path under `base_url`. Becomes `<base_url>/<path>`. |
| `<artifact>.size_bytes` | int | Expected file size; the download fails early if the server returns a different size. |
| `<artifact>.sha256` | string | Hex-encoded SHA-256 of the file. Verified after download. |

## The download lifecycle

```
backend startup
  │
  ├─► GET MNEMOS_MANIFEST_URL (with retry on transient failure, 10s timeout)
  │     └─► cached in-memory for the lifetime of the process
  │
  └─► first warmup of model X (lazy, on first /identify or explicit /models/warmup)
        ├─► for each artifact of model X under the current provider:
        │     ├─► exists on disk? → use as-is
        │     └─► missing or partial:
        │           ├─► GET <base_url>/<path>  (HTTP Range for resume)
        │           ├─► stream to <MNEMOS_MODELS_ROOT>/<local_path>
        │           ├─► ws.publish("warmup.download" or "reindex.download", {artifact, done, total})
        │           └─► on completion: sha256(file) == manifest.sha256?
        │                 ├─► yes → keep file, mark complete
        │                 └─► no  → delete file, raise, ws.publish("warmup.error")
        └─► load into memory, run a no-op detection to validate
              └─► ws.publish("warmup.done")
```

The download is interruptible. If the backend is restarted mid-download, the next start resumes via `Range`. The `<MNEMOS_MODELS_ROOT>/<local_path>` is the on-disk path; the filename is part of it for `find-the-right-artifact` lookups (the rockchip provider uses `filename.startswith("detection")` to find its detector).

## Hosting your own mirror

To pin a specific manifest version, or to host artifacts privately:

1. Mirror the artifacts to your own S3 / GCS / HTTP server.
2. Host the manifest JSON somewhere reachable. It can be a `file://` URL on a local network.
3. Set `MNEMOS_MANIFEST_URL` to the manifest URL.
4. Set `MNEMOS_MANIFEST_FETCH_TIMEOUT_S` if your server is slow.

The manifest's `base_url` can be different from the manifest's own URL — the manifest is just JSON, the artifacts are at `base_url + path`.

## Model licensing

The buffalo family of weights is distributed by deepinsight under the **MIT
license**. The full text is reproduced in [LICENSE-EXTERNAL](../LICENSE-EXTERNAL)
section 6. If you ship a derived image or redistribute a self-hosted mirror,
keep the upstream copyright notice with the weights. The detection / recognition
ONNX files themselves are unmodified from the upstream releases.

## Adding a new model

To add `buffalo_xl` to the supported set:

1. Upload the artifacts to your mirror.
2. Compute the SHA-256 of each:

   ```bash
   sha256sum buffalo_xl_det.onnx buffalo_xl_rec.onnx
   ```

3. Update the manifest:

   ```json
   "buffalo_xl": {
     "standard": {
       "detection": {
         "filename": "buffalo_xl_det.onnx",
         "path": "/models/standard/buffalo_xl_det.onnx",
         "size_bytes": 268435456,
         "sha256": "…"
       },
       "recognition": { … }
     }
   }
   ```

4. Push the manifest to `MNEMOS_MANIFEST_URL` (or your private mirror).
5. Restart the backend. The new model appears in `GET /api/v1/models/available`.

The frontend needs no change — it lists whatever the manifest exposes.

## Security model

The manifest is treated as trusted input. It says "this URL is at this SHA-256" and the backend downloads from that URL and verifies. The security property is:

- **A man-in-the-middle who can modify the manifest** can point the backend at a different URL, but the SHA-256 will then mismatch the served bytes and the download is rejected.
- **A man-in-the-middle who can modify the served bytes** can serve anything, but the SHA-256 won't match the manifest and the download is rejected.
- **A man-in-the-middle who can modify both** can substitute artifacts. Mitigations:
  - Pin `MNEMOS_MANIFEST_URL` to a known source (the default is `apps.selvarajah.co.uk`, which is HTTPS-pinned).
  - Audit the manifest before deploy — the manifest is a small JSON file.
  - For higher assurance, mirror the manifest yourself and audit it.

The first start of a fresh backend fetches the manifest over HTTPS and verifies every artifact's SHA-256. If you change `MNEMOS_MANIFEST_URL` to an HTTP source, the TLS guarantee is lost — only do this for a private mirror on a trusted network.

---

## For developers

### Why a small manifest instead of "pull weights from Git LFS"

Git LFS is great for small teams but the bandwidth costs at scale are non-trivial. A static JSON + an S3 mirror is operationally simpler and cheaper, and the manifest is small enough to read by eye.

### Why SHA-256 and not sha256sum-on-the-fly

The download is two-phase: stream to disk, then hash. The hash is fast (gigabytes per second) and the file is rewritten if the hash doesn't match. A streamed hash (e.g. `hashlib.file_digest`) would be faster but only catches mid-stream tampering; the on-disk hash also catches a corrupted file system.

### Why not store artifacts in the image

300 MB of weights in the image triples the image size. For a home user with a slow upstream, that's a big deal. For a CI build, it's worse — every image build downloads them. The lazy download pattern is one extra HTTP fetch on first use, which is much cheaper in aggregate.
