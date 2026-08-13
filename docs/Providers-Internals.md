# Provider Internals

This is the developer-facing deep dive on the provider abstraction. For "which provider should I pick", see [Providers](https://github.com/vithurshanselvarajah/Mnemos/wiki/Providers). For the health / schema surface, see [API Health](https://github.com/vithurshanselvarajah/Mnemos/wiki/API-Health).

- [File layout](#file-layout)
- [The Protocol](#the-protocol)
- [Engine lifecycle](#engine-lifecycle)
- [`InsightFaceEngine` — the wrapper](#insightfaceengine--the-wrapper)
- [Hard-lockdown rules](#hard-lockdown-rules)
- [Preflight checks](#preflight-checks)
- [Extending: detect, embed, switch](#extending-detect-embed-switch)

---

## File layout

```
mnemos-backend/app/providers/
├── __init__.py              # re-exports InferenceEngine, Detection, ProviderNotAvailable
├── base.py                  # the Protocol, dataclass, and exception
├── cpu/
│   ├── __init__.py
│   └── engine.py            # CpuEngine
├── nvidia/
│   ├── __init__.py          # also re-exports detect_cuda_provider
│   └── engine.py            # NvidiaEngine + detect_cuda_provider()
└── rockchip/
    ├── __init__.py          # re-exports RockchipEngine and the ctypes shim
    ├── _rknn_shim.py        # ctypes bindings for librknnrt.so
    └── engine.py            # RockchipEngine
```

The protocol lives in `base.py`. Each provider implements it in a `engine.py` module under its own directory. The package `__init__.py` re-exports the public classes.

## The Protocol

```python
# app/providers/base.py

class ProviderNotAvailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Detection:
    bbox: tuple[float, float, float, float]
    score: float
    embedding: np.ndarray


class InferenceEngine(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    @property
    def active_providers(self) -> list[str]: ...

    @property
    def last_error(self) -> str | None: ...

    def warmup(self) -> bool: ...
    def is_loaded(self) -> bool: ...
    def detect(self, bgr_image: np.ndarray) -> list[Detection]: ...
    def switch_model(self, new_name: str) -> None: ...
```

### What `Detection` carries

- `bbox` — `(x1, y1, x2, y2)` in pixel coordinates of the input image. The caller is responsible for any coordinate-space transformations.
- `score` — detector confidence, 0-1. The provider may apply its own threshold or leave the decision to the caller; Mnemos's `/identify` handler applies `MNEMOS_MIN_FACE_PX` separately.
- `embedding` — a 512-D L2-normalised float32 vector. If the underlying model produces non-normalised embeddings, the engine normalises them before returning.

### What `ProviderNotAvailable` means

The provider can't run on this host. Possible causes:

- The variant-specific pip packages aren't installed (e.g. the CPU image was used with `MNEMOS_PROVIDER=nvidia`).
- The system-level runtime is missing (no CUDA driver, no `librknnrt.so`).
- The build is for one SoC and the host is another.

The right way to surface this is at startup, via the preflight check. The engine itself raises it as a defensive measure.

## Engine lifecycle

```
construction
   │
   │  (no model loaded yet; no I/O happens)
   ▼
warmup()
   │
   │  loads weights, runs a no-op detection to validate
   ├─► success  → is_loaded() == True, last_error == None
   └─► failure  → is_loaded() == False, last_error == "<Exception>: <message>"
   │
   ▼
detect() / is_loaded() / switch_model() / active_providers / last_error
   │
   │  all safe to call before warmup
   │  detect() will trigger warmup internally on first call (lazy)
   ▼
switch_model("buffalo_l")
   │
   │  clears in-memory state, sets new name
   │  next detect() triggers warmup of the new model
   ▼
```

Three properties of the lifecycle to note:

1. **Construction is cheap.** The engine doesn't load any weights in `__init__`. The cost is paid on the first `warmup()` or `detect()`.
2. **Lazy on first detect.** A bare `InsightFaceEngine(...)` followed by `engine.detect(img)` will load the model, then run the detection. Useful for code that wants "just give me detections" without an explicit warmup step.
3. **Failed warmup is recoverable.** `last_error` is set, `is_loaded()` is `False`, but the next `warmup()` (or the first `detect()` after the failure) will retry. This is how the model recovers from a transient download failure.

## `InsightFaceEngine` — the wrapper

The provider-specific engines are private. The rest of the backend talks to `InsightFaceEngine`:

```python
# app/services/engine.py

class InsightFaceEngine:
    @classmethod
    def current(cls) -> "InsightFaceEngine": ...

    @property
    def provider_name(self) -> str: ...
    @property
    def model_name(self) -> str: ...
    def active_providers(self) -> list[str]: ...
    def last_error(self) -> str | None: ...
    def warmup(self) -> bool: ...
    def is_loaded(self) -> bool: ...
    def detect(self, bgr_image) -> list[Detection]: ...
    def switch_model(self, new_name) -> None: ...
    @classmethod
    def reset(cls) -> None: ...
```

The wrapper:

- **Is a singleton** — `current()` returns the process-wide instance. The instance is created lazily on first call.
- **Knows the provider** — bound to one provider at construction time. The provider is taken from `settings.provider`. There is no runtime provider switch.
- **Forwards everything to the inner engine** — the wrapper is a thin facade. The interesting logic is in the inner engine.
- **Has a `reset()`** for tests that want to clear the singleton between cases.

### `_load_provider`

The factory:

```python
def _load_provider(provider: str, model_name: str, det_size: int) -> InferenceEngine:
    if provider == "cpu":
        from app.providers.cpu import CpuEngine
        return CpuEngine(model_name=model_name, det_size=det_size)
    if provider == "nvidia":
        from app.providers.nvidia import NvidiaEngine
        return NvidiaEngine(model_name=model_name, det_size=det_size)
    if provider == "rockchip":
        from app.providers.rockchip import RockchipEngine
        return RockchipEngine(model_name=model_name, det_size=det_size)
    raise ProviderNotAvailable(f"unknown MNEMOS_PROVIDER: {provider!r}")
```

To add a new provider, add a branch here. The rest of the backend picks it up automatically.

## Hard-lockdown rules

Three rules every provider must follow. They are enforced by the preflight check and by the Protocol-level invariants.

### 1. No cross-provider fallback

A provider must not silently fall back to a different one. The NVIDIA engine, for example, raises `ProviderNotAvailable` if `CUDAExecutionProvider` is not available — it does **not** fall back to `CPUExecutionProvider`.

The reason: silent fallback masks configuration errors. A deployment that picked `provider=nvidia` made a deliberate choice; if the choice can't be honoured, the right answer is "refuse to start" so the operator can see the problem immediately.

### 2. All-or-nothing init

If `warmup()` fails:

- `is_loaded()` returns `False`
- `last_error` is set to the exception message
- The next call to `detect()` or `warmup()` retries the init

There is no "half-loaded" state. The engine is either ready or it isn't.

### 3. Single active provider

`active_providers` returns exactly the providers the engine is using. For NVIDIA, this is `["CUDAExecutionProvider"]` (hard-locked). For CPU, `["CPUExecutionProvider"]`. For Rockchip, `["rknn"]`.

The `InsightFaceEngine.active_providers()` proxies this; `/healthz` exposes it to operators. If you ever see `["CUDAExecutionProvider", "CPUExecutionProvider"]` in `active_providers`, the provider has fallen back to CPU and you've found a bug.

## Preflight checks

`app.services.model_manifest.preflight_provider()` runs at backend startup. It hard-fails (`SystemExit`) if the configured provider can't run on this host. For each provider:

### CPU

No-op. Any host with `libgl1` (or the right OpenCV backend) can run the CPU engine.

### NVIDIA

```python
info = detect_cuda_provider()
if not info["onnxruntime_available"]: SystemExit("onnxruntime missing")
if not info["cuda_available"]:        SystemExit("CUDAExecutionProvider missing")
if info["device_count"] == 0:         SystemExit("libcuda could not be loaded")
```

`detect_cuda_provider()` probes `onnxruntime.get_available_providers()` and `ctypes.CDLL("libcuda.so.1")`. The function returns a dict so `/healthz` can surface the same state to operators.

### Rockchip

```python
machine = platform.machine().lower()           # must be aarch64 / arm64
detected_soc = _detect_rockchip_soc()          # /proc/device-tree/compatible
supported = supported_rockchip_socs()          # from the manifest
if detected_soc not in supported: SystemExit("SoC not in manifest")
```

The auto-detection is overridable via `MNEMOS_ROCKCHIP_SOC`.

## Extending: detect, embed, switch

### Detect

The default InsightFace detection call is:

```python
faces = self._app.get(bgr_image)
```

For each face, extract `bbox`, `det_score`, and `normed_embedding`. If `normed_embedding` is missing (older model variants), compute it from `embedding` by L2-normalising.

The bbox is `(x1, y1, x2, y2)` in the input image's pixel space. The caller is responsible for any coordinate-space transformation when cropping.

### Embed

InsightFace produces a 512-D vector for `buffalo_s/m/l`. The engine returns the L2-normalised vector in `Detection.embedding`. The unit-norm is a precondition for cosine distance; downstream code assumes it.

If the underlying model produces non-normalised embeddings, the engine must normalise them. Do this in the engine, not in the caller — the caller has no way to know whether the embedding is already normalised.

### Switch

`switch_model(new_name)` clears the in-memory state and updates the engine's `model_name`. The next call to `detect()` (or an explicit `warmup()`) loads the new weights.

The reindex — re-embedding every stored crop under the new model — is a separate operation owned by `app.services.reindex`. The engine does not know about the reindex; the reindex calls the engine.

---

## Future work

- **Compiled ctypes for RKNN.** The shim is small but interpreted-Python ctypes calls have non-trivial per-call overhead. A cffi binding would be faster. (Low priority; the per-call cost is dwarfed by the inference time.)
- **Batch detect.** Current `detect()` is per-image. A `detect_batch(images) -> list[list[Detection]]` would let the GPU pipeline be saturated for multi-camera setups.
- **Provider-level caching.** Some hosts have multiple GPUs or multiple NPUs. The current design assumes one. A `Device` abstraction would let a single engine use multiple devices.
- **Per-provider metrics.** `/metrics` would be a nice addition, but the project doesn't have one yet. When it does, per-provider counters (inference time, warmup success/failure, last_error count) are the first things to add.
