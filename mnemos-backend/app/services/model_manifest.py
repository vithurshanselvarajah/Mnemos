from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any

import requests

from app.core.config import settings

log = logging.getLogger("mnemos.model_manifest")


@dataclass(frozen=True)
class ModelArtifact:
    filename: str
    url: str
    size_bytes: int
    sha256: str
    local_path: str


@dataclass(frozen=True)
class ModelVariant:
    name: str
    kind: str
    artifacts: tuple[ModelArtifact, ...]


def _read_manifest() -> dict[str, Any]:
    return _read_manifest_with_retry(settings.manifest_url)


def _read_manifest_with_retry(url: str) -> dict[str, Any]:
    timeout = settings.manifest_fetch_timeout_s
    delays = [0.0, 1.0, 2.0, 4.0, 8.0, 16.0]
    last_err: Exception | None = None
    for attempt, delay in enumerate(delays):
        if delay:
            log.info("retrying manifest fetch in %.1fs (attempt %d/%d)", delay, attempt + 1, len(delays))
            time.sleep(delay)
        log.info("fetching model manifest from %s", url)
        try:
            r = requests.get(url, timeout=timeout)
            r.raise_for_status()
            data = json.loads(r.content)
            if not isinstance(data, dict) or "models" not in data or "base_url" not in data:
                raise ValueError("manifest missing required top-level keys (base_url, models)")
            return data
        except Exception as e:
            last_err = e
            log.warning("manifest fetch attempt %d failed: %s", attempt + 1, e)
    assert last_err is not None
    raise last_err


def _artifact_to_url_and_path(base_url: str, model_name: str, kind: str, soc: str, art: dict[str, Any]) -> ModelArtifact:
    path = art.get("path")
    filename = art.get("filename")
    sha = art.get("sha256")
    size = art.get("size_bytes")
    if not (isinstance(path, str) and isinstance(filename, str) and isinstance(sha, str) and isinstance(size, int)):
        raise ValueError(f"manifest entry malformed for {model_name}/{kind}: {art!r}")
    rel = path.lstrip("/")
    idx = rel.find("/models/")
    if idx >= 0:
        local_rel = rel[idx + 1:]
    else:
        local_rel = rel
    local = os.path.join(settings.models_root, local_rel)
    url = base_url.rstrip("/") + "/" + rel
    return ModelArtifact(
        filename=filename,
        url=url,
        size_bytes=size,
        sha256=sha.lower(),
        local_path=local,
    )


def _variants_for_provider(raw: dict[str, Any]) -> list[ModelVariant]:
    base_url = raw["base_url"]
    provider = settings.provider
    out: list[ModelVariant] = []
    for model_name, entry in raw["models"].items():
        if provider in ("cpu", "nvidia"):
            std = entry.get("standard")
            if not isinstance(std, dict):
                continue
            arts: list[ModelArtifact] = []
            for slot in ("detection", "recognition"):
                a = std.get(slot)
                if isinstance(a, dict):
                    arts.append(_artifact_to_url_and_path(base_url, model_name, "standard", "", a))
            if arts:
                out.append(ModelVariant(name=model_name, kind="standard", artifacts=tuple(arts)))
        elif provider == "rockchip":
            soc = _detect_rockchip_soc()
            rknn = entry.get("rknn", {}).get(soc)
            if not isinstance(rknn, dict):
                continue
            arts = []
            for slot in ("detection", "recognition"):
                a = rknn.get(slot)
                if isinstance(a, dict):
                    arts.append(_artifact_to_url_and_path(base_url, model_name, f"rknn/{soc}", soc, a))
            if arts:
                out.append(ModelVariant(name=model_name, kind=f"rknn/{soc}", artifacts=tuple(arts)))
    return out


def available_models() -> list[ModelVariant]:
    return _variants_for_provider(_read_manifest())


def variant_for(name: str) -> ModelVariant:
    for v in available_models():
        if v.name == name:
            return v
    raise KeyError(f"model {name!r} is not available for provider={settings.provider}")


_RK_DT_COMPATIBLE = "/proc/device-tree/compatible"

_RK_PREFERENCE = ["rk3588", "rk3576", "rk3568", "rk3566"]


def _detect_rockchip_soc() -> str:
    override = settings.rockchip_soc.strip()
    if override:
        return override
    try:
        with open(_RK_DT_COMPATIBLE, "rb") as f:
            blob = f.read().decode("utf-8", errors="ignore")
    except OSError:
        return "rk3588"
    found = {m.group(1).lower() for m in re.finditer(r"rockchip,(rk\d+)", blob)}
    if not found:
        return "rk3588"
    for cand in _RK_PREFERENCE:
        if cand in found:
            return cand
    return sorted(found)[0]


def supported_rockchip_socs() -> list[str]:
    try:
        raw = _read_manifest()
    except Exception as e:
        log.warning("could not read manifest for supported_rockchip_socs: %s", e)
        return []
    out: set[str] = set()
    for entry in raw.get("models", {}).values():
        rknn = entry.get("rknn") if isinstance(entry, dict) else None
        if isinstance(rknn, dict):
            out.update(k for k in rknn.keys() if isinstance(k, str))
    return sorted(out)


def preflight_provider() -> None:
    provider = settings.provider
    if provider != "rockchip":
        return
    import platform

    machine = platform.machine().lower()
    if machine not in ("aarch64", "arm64"):
        raise SystemExit(
            f"provider=rockchip requires an aarch64/arm64 host "
            f"(detected machine={machine!r}). Please use the CPU or NVIDIA variant on this host."
        )
    detected = _detect_rockchip_soc()
    try:
        supported = supported_rockchip_socs()
    except Exception as e:
        raise SystemExit(
            f"preflight failed: provider=rockchip detected_soc={detected} "
            f"could not load manifest: {e}"
        ) from e
    if detected not in supported:
        supported_list = ", ".join(supported) if supported else "(none)"
        raise SystemExit(
            f"unsupported Rockchip SoC detected={detected} (supported: {supported_list}). "
            f"Please use the CPU variant, or set MNEMOS_ROCKCHIP_SOC to a supported value."
        )
