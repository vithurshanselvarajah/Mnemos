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

- A CUDA-capable GPU (Compute capability ≥ 5.0 — anything from the last 10 years)
- An NVIDIA proprietary driver ≥ 535, recent enough to satisfy CUDA 13.x userspace (the in-container runtime is CUDA 13.3)
- The [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) (`nvidia-container-toolkit` package) configured for Docker
- A 64-bit Linux kernel (the toolkit does not support macOS, Windows, or WSL2 with native Docker)
- `curl` and `gnupg` (for adding NVIDIA's apt repo inside the image build)

On the host, install and configure the toolkit:

```bash
# Debian / Ubuntu
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

```bash
# RHEL / Fedora / Rocky
curl -s -L https://nvidia.github.io/libnvidia-container/stable/rpm/nvidia-container-toolkit.repo \
  | sudo tee /etc/yum.repos.d/nvidia-container-toolkit.repo
sudo dnf install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Then the compose stack's `mnemos-backend` service needs the GPU attached. Production `docker-compose.yml` and `docker-compose.dev.yml` declare it on the `mnemos-backend` service via:

```yaml
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
```

If you fork the compose file, copy that block. (Older setups used `runtime: nvidia` — the `deploy.resources` form is the current Docker Compose v2 idiom and works on both rootless and rootful Docker.)

To verify the whole chain:

```bash
# 1. The driver works at all
nvidia-smi

# 2. The toolkit can hand the GPU to a container
docker run --rm --gpus all nvidia/cuda:13.0.0-base-ubuntu24.04 nvidia-smi

# 3. The compose stack is wired up
./bin/mnemos up nvidia
docker compose -f docker-compose.dev.yml logs -f mnemos-backend
# Look for: providers=['TensorrtExecutionProvider', 'CUDAExecutionProvider', 'CPUExecutionProvider']
# Look for: GET /healthz → nvidia.cuda_available: true
```

If the second command works but the third doesn't, the compose file is missing the `deploy.resources` block. If neither works, the toolkit isn't configured.

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

### Prerequisites

The Rockchip variant only works on a host that is actually a supported Rockchip SoC. The full list is `rk3588`, `rk3576`, `rk3568`, `rk3566`. Anything else (and anything x86) will fail preflight with an `unsupported Rockchip SoC detected` error.

#### Board Support Package (BSP) kernel

The **mandatory** prerequisite is that the host is running the board vendor's BSP kernel (the one that ships `librknnrt.so` and exposes the NPU device node). Distro kernels (Debian `arm64`, Ubuntu Server `arm64`, Armbian generic) do **not** include the NPU driver, and there is no upstream `rknpu` driver you can build separately. The supported boards and their BSPs are:

| SoC | Typical boards | BSP source |
| --- | --- | --- |
| `rk3588` | Orange Pi 5 / 5 Plus, Rock 5B, Radxa Rock 5A, FriendlyElec NanoPC-T6 | Vendor image (e.g. `orangepi-build`, `radxa-debian-bsp`) |
| `rk3576` | Rock 4D, HDP-RK3576, Radxa NX5 | Vendor image |
| `rk3568` | Rock 3A, Orange Pi 3B, Radxa CM3 | Vendor image |
| `rk3566` | Rock 3C, ZeroTier RK3566 boards | Vendor image |

On the BSP:

1. Identify which device-node convention the kernel uses — see [NPU device nodes](#npu-device-nodes) below.
2. Confirm `librknnrt.so` is shipped by the BSP. Most vendors put it in `/usr/lib/aarch64-linux-gnu/librknnrt.so`. If `ldconfig -p | grep rknnrt` is empty, the BSP is incomplete.
3. Confirm the user running the container can read the NPU device (i.e. is in the `render` or `video` group, or you're running as root).

#### NPU device nodes

The Rockchip NPU surfaces through **two different device-node conventions** depending on the BSP kernel version. Use the one your board actually exposes:

| Convention | Kernel | How to check | Device nodes |
| --- | --- | --- | --- |
| **Legacy char-misc** | Older BSPs (< 5.10), some vendor 4.4 kernels | `ls -l /dev/rknpu*` shows entries | `/dev/rknpu` (single NPU), `/dev/rknpu2` (rk3588's second NPU) |
| **DRM render-node** | Newer BSPs (5.10+) with the upstream DRM rknpu driver | `ls -l /dev/dri/` shows `renderD128`, `renderD129`, … | `/dev/dri/renderD129` (NPU), `/dev/dri/renderD128` (rkvdec/VPU — not MNEMOS) |

Concrete mapping you see on a typical `rk3588` MediaServer-style BSP:

| Node | What it is |
| --- | --- |
| `/dev/dri/card0` | Primary DRM card (display + GPU/composer) |
| `/dev/dri/card1` | Secondary DRM card (VPU/NPU auxiliary domain) |
| `/dev/dri/renderD128` | `rkvdec2` / `rkvenc` — hardware video decoder pipeline |
| `/dev/dri/renderD129` | `rknpu` — the NPU (RKNN runtime talks to this) |
| `/dev/dma_heap/system` | DMA-BUF heap used by VPU and NPU buffers (no pass-through needed; RKNN uses `librknnrt.so`'s own allocator) |

The key point: **`renderD128` is the video decoder, `renderD129` is the NPU** — passthrough `renderD129` (and only `renderD129`) for MNEMOS. If you map `card0`/`card1` you don't gain anything and you risk confusing Compose if the underlying kernel objects change naming at boot. `renderD128` belongs to the VPU and is **not** required by MNEMOS — leave it out.

If both forms exist on the host, the engine prefers the legacy char-misc device (its IOCTL surface is older and more stable across runtime versions); if only the DRM render-node form exists (the common case on current `rk3588` BSPs), it falls back to `renderD129`. The `/healthz` response records which one was used.

#### Host packages

The build image already contains everything Python-side. The host only needs:

- A 64-bit ARM (aarch64) Linux kernel 5.10+ with the vendor's NPU driver loaded (5.10+ if you rely on the DRM render-node path; < 5.10 still works via the legacy char-misc form)
- `librknnrt.so` (vendored at build time from the BSP; the Dockerfile downloads a pinned copy at build time, but the host must have the matching driver)
- `libgl1` and `libglib2.0-0` for OpenCV (pulled by the standard image)

#### Device passthrough into the container

The `mnemos-backend` service must have the NPU device bind-mounted. Apply one of the blocks below to **both** `docker-compose.yml` and `docker-compose.dev.yml` for the `mnemos-backend` service. The block is commented out by default so it doesn't affect non-rockchip deployments.

**DRM render-node form** — what current `rk3588` BSPs (kernel 5.10+) need:

```yaml
    devices:
      # rk3588 NPU via the upstream DRM render-node API.
      # On rk3588 it's /dev/dri/renderD129; on rk3568/rk3576/rk3566 the
      # exact render-node number can differ — replace with whatever
      # `ls /dev/dri/renderD*` reports for the node owned by `root:render`.
      - /dev/dri/renderD129:/dev/dri/renderD129
    group_add:
      - render                    # or "video", whichever the BSP uses
    volumes:
      # Bind the host BSP's librknnrt.so so it matches the host driver.
      - /usr/lib/aarch64-linux-gnu/librknnrt.so:/usr/lib/librknnrt.so:ro
```

**Legacy char-misc form** — older BSPs that still register `/dev/rknpu{,2}`:

```yaml
    devices:
      - /dev/rknpu:/dev/rknpu
      - /dev/rknpu2:/dev/rknpu2   # only on rk3588 (dual-core NPU); omit on others
    group_add:
      - render                    # or "video", whichever the BSP uses
    volumes:
      - /usr/lib/aarch64-linux-gnu/librknnrt.so:/usr/lib/librknnrt.so:ro
```

If both forms exist (you'll see both `/dev/rknpu*` and `/dev/dri/renderD129`), mount both — the engine will pick whichever responds first. Mounting both is harmless; only the first reachable one is used.

The `:ro` mount of `librknnrt.so` is intentional: the in-container ctypes shim loads the **host's** RKNN runtime (so it always matches the host driver). The Dockerfile's vendored copy is only a fallback for `aarch64` builds on systems without a BSP at build time.

#### Verifying

```bash
# On the host (BSP)
ls -l /dev/rknpu* /dev/dri/renderD* /usr/lib/aarch64-linux-gnu/librknnrt.so 2>/dev/null
cat /proc/device-tree/compatible

# From a throwaway container (DRM render-node form — current BSPs)
docker run --rm \
  --device /dev/dri/renderD129 \
  --group-add render \
  -v /usr/lib/aarch64-linux-gnu/librknnrt.so:/usr/lib/librknnrt.so:ro \
  ghcr.io/vithurshanselvarajah/mnemos-backend:latest-rockchip \
  python -c "from ctypes import CDLL; CDLL('librknnrt.so'); print('ok')"

# From a throwaway container (legacy char-misc form — older BSPs)
docker run --rm \
  --device /dev/rknpu --device /dev/rknpu2 \
  --group-add render \
  -v /usr/lib/aarch64-linux-gnu/librknnrt.so:/usr/lib/librknnrt.so:ro \
  ghcr.io/vithurshanselvarajah/mnemos-backend:latest-rockchip \
  python -c "from ctypes import CDLL; CDLL('librknnrt.so'); print('ok')"

# Full stack
MNEMOS_PROVIDER=rockchip docker compose up -d
docker compose logs -f mnemos-backend
# Look for: provider=rockchip, GET /healthz → rockchip.npu_available: true, rockchip.npu_device: "renderD129" (or "/dev/rknpu")
```

If `/dev/dri/renderD129` (and `/dev/rknpu`) are missing, the BSP kernel isn't loaded with the NPU driver. If the ctypes load fails with `cannot open shared object file`, the bind-mount path is wrong (the vendor's library path may differ). If you see `init_runtime: DRV` in the logs, the host's `librknnrt.so` is older than the kernel driver — upgrade the BSP runtime, or reflash the BSP image.

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
