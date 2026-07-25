# Providers

Mnemos has three inference providers. Each is a separate Docker image tag and a separate install path. The provider is set at deploy time via `MNEMOS_PROVIDER` and **never changes without a container restart** — there is no runtime provider switch.

- [Why three providers?](#why-three-providers)
- [The provider contract](#the-provider-contract)
- [CPU (default)](#cpu-default)
- [NVIDIA GPU](#nvidia-gpu)
- [Rockchip NPU](#rockchip-npu)
- [Picking a provider](#picking-a-provider)
- [Troubleshooting provider issues](#troubleshooting-provider-issues)

---

## Why three providers?

InsightFace's ONNX models can run on:

- **CPU** — onnxruntime with the default `CPUExecutionProvider`. Universal compatibility, slowest.
- **NVIDIA GPU** — onnxruntime-gpu with `CUDAExecutionProvider`. Requires a host with an NVIDIA driver + CUDA runtime. ~5-10× faster than CPU.
- **Rockchip NPU** — RKNN runtime, on a Rockchip SoC (rk3588, rk3576, rk3568, rk3566). For low-power / edge devices.

A provider is more than just the inference library. The Dockerfile is multi-stage, swapping in:

- A different `pip install` (`-r variants/<provider>/requirements.txt`)
- A different runtime base image (`nvidia/cuda:…` for GPU, or a slim with `librknnrt` for Rockchip)
- Different system libraries (libgl, cudnn, rknn drivers)

The Python code in the backend is **the same** for all three providers. The provider is a class loaded at startup, exposed via the `InsightFaceEngine` wrapper.

## The provider contract

Every provider implements the same Protocol (`app.providers.base.InferenceEngine`):

```python
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

Three rules the providers must follow:

1. **No cross-provider fallback.** If a provider can't run on the current host, it must raise `ProviderNotAvailable`, not silently fall back to a different provider. The container refuses to start.
2. **All-or-nothing init.** If `warmup()` fails, `is_loaded()` returns `False` and the next `detect()` retries the init. `last_error` is set so the operator can see what went wrong.
3. **Single active provider.** The engine's `active_providers` always returns the providers it will actually use. For NVIDIA this is `["CUDAExecutionProvider"]` (hard-locked); for CPU it's `["CPUExecutionProvider"]`; for Rockchip it's `["rknn"]`. The provider is the only thing in the list — no fallbacks.

## CPU (default)

```dotenv
MNEMOS_PROVIDER=cpu
```

- Image: `ghcr.io/vithurshanselvarajah/mnemos-backend:latest-cpu`
- Base image: `python:3.14-slim` + `libgl1` for OpenCV
- onnxruntime: `onnxruntime` (CPU build)
- Works on: any Linux x86_64 / arm64, macOS, WSL2, basically anything
- Speed: 5-10 fps for typical 640px input on a modern desktop CPU. Slow but fine for a few cameras.

### Tuning

- `MNEMOS_DET_SIZE` — 320 is faster but less accurate on small faces; 640 is the default; 1024+ is for archival batch jobs.
- The InsightFace `buffalo_s` model is faster than `buffalo_l` on CPU. Stick with `buffalo_s` unless you have a reason.

## NVIDIA GPU

```dotenv
MNEMOS_PROVIDER=nvidia
```

- Image: `ghcr.io/vithurshanselvarajah/mnemos-backend:latest-nvidia`
- Base image: `nvidia/cuda:12.4.1-cudnn-runtime-ubuntu24.04`
- onnxruntime: `onnxruntime-gpu` (CUDA build)
- Works on: any Linux host with an NVIDIA driver and the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) installed
- Speed: 30-100 fps for typical input. ~5-10× faster than CPU.

### Hard-locked

The NVIDIA variant **never falls back to CPU**. If `CUDAExecutionProvider` is not available, the engine raises `ProviderNotAvailable` and the container refuses to start. The reasoning:

- Silent fallback masks driver / library / install problems.
- "Works but slow" is harder to diagnose than "doesn't start."
- A deployment that picked `provider=nvidia` made a deliberate choice — the operator wants the GPU, full stop.

The preflight check (`app.services.model_manifest.preflight_provider`) catches this at startup with a helpful error message:

```
preflight failed: provider=nvidia requires the CUDAExecutionProvider,
but it is not present in this onnxruntime build. Available providers: CPUExecutionProvider.
Install the NVIDIA variant (onnxruntime-gpu) and ensure the host has a working
CUDA driver + cuDNN runtime, or switch to provider=cpu.
```

### Prerequisites

The host must have:

- A CUDA-capable GPU (Compute capability ≥ 5.0, which is anything from the last 10 years)
- An NVIDIA driver compatible with CUDA 12.4
- The NVIDIA Container Toolkit (`nvidia-ctk`)
- The compose file's GPU runtime configured (it is, by default — `runtime: nvidia` on the `mnemos-backend` service)

To verify:

```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu24.04 nvidia-smi
```

If the second command works, the container toolkit is installed and the compose GPU passthrough is good.

### Health and diagnostics

`GET /healthz` includes an `nvidia` object:

```json
{
  "provider": "nvidia",
  "nvidia": {
    "onnxruntime_available": true,
    "cuda_available": true,
    "device_count": 1,
    "available_providers": ["CUDAExecutionProvider", "CPUExecutionProvider"],
    "active_providers": ["CUDAExecutionProvider"],
    "last_error": null
  }
}
```

`cuda_available: false` or `last_error: "..."` means something is wrong; the operator can see exactly what without grepping logs.

## Rockchip NPU

```dotenv
MNEMOS_PROVIDER=rockchip
```

- Image: `ghcr.io/vithurshanselvarajah/mnemos-backend:latest-rockchip`
- Base image: `python:3.14-slim` + `librknnrt` (vendored at build time)
- Runtime: RKNN via a ctypes shim
- Works on: Rockchip SoCs with an NPU. Supported: rk3588, rk3576, rk3568, rk3566.
- Speed: comparable to NVIDIA for the inference stages, faster for the preprocessing because the NPU is on-die.

### SoC detection

The SoC is auto-detected from `/proc/device-tree/compatible` (which every board-style Linux has). To force a specific SoC:

```dotenv
MNEMOS_ROCKCHIP_SOC=rk3576
```

The backend will refuse to start if the detected (or overridden) SoC has no entry in the manifest. The error message lists the supported SoCs.

### Why a ctypes shim

The RKNN runtime is shipped as `librknnrt.so`, a C library. Rather than bind to it with cffi or pybind11, the project uses a thin Python ctypes shim (`app.providers.rockchip._rknn_shim`). The shim is small and reads cleanly; the alternative (a compiled binding) would add a build step and a more complex Dockerfile.

## Picking a provider

| Hardware | Provider | Why |
| --- | --- | --- |
| Anything that runs Docker | `cpu` | Universal, slow but works |
| NVIDIA GPU (any 5xx+) on a Linux host with the toolkit | `nvidia` | Best performance per watt for x86 |
| Rockchip SoC (rk3588/rk3576/rk3568/rk3566) | `rockchip` | Best performance per watt for edge ARM |
| Apple Silicon | `cpu` (or contribute a CoreML provider) | The CoreML provider is a future-work item |

For most home installs, `cpu` is the right starting point. Move to `nvidia` when you have more than a few cameras, or when latency matters. The model is the same; only the runtime changes.

---

## For developers

### Adding a new provider

1. Create `app/providers/<name>/engine.py` implementing the `InferenceEngine` Protocol.
2. Create `app/providers/<name>/__init__.py` re-exporting the engine class.
3. Add a dispatch branch in `app.services.engine._load_provider()`.
4. Create `variants/<name>/requirements.txt` with the provider-specific pip packages.
5. Update the `mnemos-backend/Dockerfile` to handle the new variant:
   - Add a new `FROM` stage with the right base image
   - Add a conditional `RUN pip install -r variants/<name>/requirements.txt`
   - Add the new variant to the `case` statement that picks the runtime stage
6. If the new provider has system-level requirements (driver, NPU SDK, …), add a preflight branch in `model_manifest.py`.
7. Add a `detect_<name>_provider()` helper for `/healthz` reporting.
8. Update `HealthOut` schema with a per-provider info block.
9. Add tests under `tests/backend/test_<name>_preflight.py` mirroring the NVIDIA preflight tests.
10. Update the docs (`docs/Providers.md` and `docs/Configuration.md`).

The rest of the backend is provider-agnostic. If you find yourself reaching across the abstraction, that's a smell — fix the Protocol or add a method to it.

### Why no provider hot-swap

A runtime provider switch would require the process to unload one inference stack, load another, and keep `/identify` responsive throughout. The hot-swap path would also be heavily platform-specific (loading a CUDA context is not the same as initialising RKNN). Picking a provider at deploy time and restarting is simpler, safer, and matches how the rest of the project treats the inference stack as configuration, not state.

### Why three providers and not a plugin system

A plugin system (e.g. setuptools entry points) would let third parties ship a provider as a separate package. The cost is a lot of indirection: the protocol becomes public API, versioning becomes harder, and the multi-stage Docker build no longer controls the inference stack. The right level of abstraction is "one repo, one Dockerfile, three well-known providers." A plugin system can come later if there's demand.
