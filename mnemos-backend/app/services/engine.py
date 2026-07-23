from __future__ import annotations

import logging
import threading
from typing import Any

import numpy as np

from app.providers.base import Detection, ProviderNotAvailable

log = logging.getLogger("mnemos.engine")


def _load_provider(provider: str, model_name: str, det_size: int) -> Any:
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


class InsightFaceEngine:
    _rw_lock = threading.Condition(threading.RLock())
    _instance: "InsightFaceEngine | None" = None

    def __init__(self, model_name: str, det_size: int, provider: str | None = None) -> None:
        from app.core.config import settings

        self._model_name = model_name
        self._det_size = det_size
        self._provider_name = provider or getattr(settings, "provider", "cpu")
        self._inner: Any | None = None
        self._loaded_provider: str | None = None

    @classmethod
    def current(cls) -> "InsightFaceEngine":
        if cls._instance is None:
            from app.core.config import settings

            cls._instance = InsightFaceEngine(
                model_name=settings.default_model,
                det_size=settings.det_size,
                provider=getattr(settings, "provider", "cpu"),
            )
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        with cls._rw_lock:
            cls._instance = None

    def _ensure_inner(self) -> Any:
        if self._inner is None or self._loaded_provider != self._provider_name:
            log.info("binding engine to provider=%s", self._provider_name)
            self._inner = _load_provider(
                self._provider_name,
                model_name=self._model_name,
                det_size=self._det_size,
            )
            self._loaded_provider = self._provider_name
        return self._inner

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def provider_name(self) -> str:
        return self._provider_name

    def warmup(self) -> bool:
        try:
            return self._ensure_inner().warmup()
        except ProviderNotAvailable as e:
            log.error("provider unavailable during warmup: %s", e)
            return False

    def is_loaded(self) -> bool:
        if self._inner is None:
            return False
        return self._inner.is_loaded()

    def detect(self, bgr_image: np.ndarray) -> list[Detection]:
        return self._ensure_inner().detect(bgr_image)

    def switch_model(self, new_name: str) -> None:
        self._model_name = new_name
        if self._inner is not None:
            self._inner.switch_model(new_name)


__all__ = ["InsightFaceEngine", "Detection"]
