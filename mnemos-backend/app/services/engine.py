from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import numpy as np

log = logging.getLogger("mnemos.engine")


@dataclass
class Detection:
    bbox: tuple[float, float, float, float]
    score: float
    embedding: np.ndarray


class InsightFaceEngine:
    _rw_lock = threading.Condition(threading.RLock())
    _instance: InsightFaceEngine | None = None
    _writers = 0
    _readers = 0

    def __init__(self, model_name: str, det_size: int) -> None:
        self._model_name = model_name
        self._det_size = det_size
        self._app = None
        self._loaded_name: str | None = None

    @classmethod
    def _acquire_read(cls):
        cond = cls._rw_lock
        with cond:
            while cls._writers > 0:
                cond.wait()
            cls._readers += 1

    @classmethod
    def _release_read(cls):
        cond = cls._rw_lock
        with cond:
            cls._readers -= 1
            if cls._readers == 0:
                cond.notify_all()

    @classmethod
    def _acquire_write(cls):
        cond = cls._rw_lock
        with cond:
            while cls._writers > 0 or cls._readers > 0:
                cond.wait()
            cls._writers += 1

    @classmethod
    def _release_write(cls):
        cond = cls._rw_lock
        with cond:
            cls._writers -= 1
            cond.notify_all()

    @classmethod
    def current(cls) -> InsightFaceEngine:
        if cls._instance is None:
            from app.core.config import settings

            cls._instance = InsightFaceEngine(settings.default_model, settings.det_size)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._instance = None

    @property
    def model_name(self) -> str:
        return self._model_name

    def _ensure_loaded(self) -> None:
        if self._app is not None and self._loaded_name == self._model_name:
            return
        from insightface.app import FaceAnalysis

        log.info("loading InsightFace model=%s det_size=%d", self._model_name, self._det_size)
        self._app = FaceAnalysis(
            name=self._model_name,
            allowed_modules=["detection", "recognition"],
            providers=["CPUExecutionProvider"],
        )
        self._app.prepare(ctx_id=0, det_size=(self._det_size, self._det_size))
        self._loaded_name = self._model_name

    def warmup(self) -> bool:
        try:
            self._ensure_loaded()
            return True
        except Exception as e:
            log.warning("warmup failed: %s", e)
            return False

    def is_loaded(self) -> bool:
        return self._app is not None and self._loaded_name == self._model_name

    def detect(self, bgr_image: np.ndarray) -> list[Detection]:
        InsightFaceEngine._acquire_read()
        try:
            self._ensure_loaded()
            faces = self._app.get(bgr_image)
        finally:
            InsightFaceEngine._release_read()
        out: list[Detection] = []
        for f in faces:
            bbox = tuple(map(float, f.bbox))
            score = float(getattr(f, "det_score", 1.0))
            emb = getattr(f, "normed_embedding", None)
            if emb is None:
                emb = np.asarray(f.embedding, dtype=np.float32)
                n = float(np.linalg.norm(emb))
                if n > 0:
                    emb = emb / n
            out.append(Detection(bbox=bbox, score=score, embedding=np.asarray(emb, dtype=np.float32)))
        return out

    def switch_model(self, new_name: str) -> None:
        InsightFaceEngine._acquire_write()
        try:
            log.info("switching model %s -> %s", self._model_name, new_name)
            self._model_name = new_name
            self._app = None
            self._loaded_name = None
        finally:
            InsightFaceEngine._release_write()
