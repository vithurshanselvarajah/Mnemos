from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


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

    def warmup(self) -> bool: ...

    def is_loaded(self) -> bool: ...

    def detect(self, bgr_image: np.ndarray) -> list[Detection]: ...

    def switch_model(self, new_name: str) -> None: ...

    @property
    def last_error(self) -> str | None:
        """Most recent warmup/load error message, or None if the last load succeeded."""
        ...
