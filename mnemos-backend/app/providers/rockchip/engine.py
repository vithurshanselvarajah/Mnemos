from __future__ import annotations

import logging
import threading
import time
from typing import Any

import cv2
import numpy as np

from app.providers.base import Detection, ProviderNotAvailable
from app.providers.rockchip import _rknn_shim
from app.services.model_manifest import variant_for

log = logging.getLogger("mnemos.providers.rockchip")


_DET_INPUT_SIZE = 640
_REC_INPUT_SIZE = 112
_DET_MEAN = 127.5
_DET_SCALE = 1.0 / 128.0

_RETINA_STRIDES = (8, 16, 32)
_RETINA_ANCHORS_PER_CELL = 2


class RockchipEngine:
    _rw_lock = threading.Condition(threading.RLock())
    _instance: "RockchipEngine | None" = None
    _writers = 0
    _readers = 0

    def __init__(self, model_name: str, det_size: int) -> None:
        self._model_name = model_name
        self._det_size = det_size
        self._det_runtime: Any | None = None
        self._rec_runtime: Any | None = None
        self._det_variant: Any | None = None
        self._loaded_name: str | None = None
        self._last_error: str | None = None
        self._inference_lock = threading.Lock()

    @property
    def provider_name(self) -> str:
        return "rockchip"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @classmethod
    def _acquire_read(cls) -> None:
        with cls._rw_lock:
            while cls._writers > 0:
                cls._rw_lock.wait()
            cls._readers += 1

    @classmethod
    def _release_read(cls) -> None:
        with cls._rw_lock:
            cls._readers -= 1
            if cls._readers == 0:
                cls._rw_lock.notify_all()

    @classmethod
    def _acquire_write(cls) -> None:
        with cls._rw_lock:
            while cls._writers > 0 or cls._readers > 0:
                cls._rw_lock.wait()
            cls._writers += 1

    @classmethod
    def _release_write(cls) -> None:
        with cls._rw_lock:
            cls._writers -= 1
            cls._rw_lock.notify_all()

    def _local_path_for(self, variant: Any, kind: str) -> str:
        for art in variant.artifacts:
            if art.filename.startswith(kind):
                return art.local_path
        raise ProviderNotAvailable(
            f"variant {variant.name!r} ({variant.kind}) has no {kind} artifact"
        )

    def _ensure_loaded(self) -> None:
        if (
            self._det_runtime is not None
            and self._rec_runtime is not None
            and self._loaded_name == self._model_name
        ):
            return
        try:
            variant = variant_for(self._model_name)
        except KeyError as e:
            raise ProviderNotAvailable(str(e)) from e
        if not variant.kind.startswith("rknn/"):
            raise ProviderNotAvailable(
                f"variant {variant.name!r} ({variant.kind}) is not an RKNN variant"
            )

        det_path = self._local_path_for(variant, "detection")
        rec_path = self._local_path_for(variant, "recognition")

        try:
            det = _rknn_shim.RKNNLite()
            if det.load_rknn(det_path) != 0:
                raise ProviderNotAvailable(f"failed to load detection model: {det_path}")
            if det.init_runtime(core_mask=_rknn_shim._RKNN_NPU_CORE_0_1_2) != 0:
                raise ProviderNotAvailable("detection init_runtime failed")
        except ProviderNotAvailable:
            raise
        except RuntimeError as e:
            raise ProviderNotAvailable(str(e)) from e

        try:
            rec = _rknn_shim.RKNNLite()
            if rec.load_rknn(rec_path) != 0:
                raise ProviderNotAvailable(f"failed to load recognition model: {rec_path}")
            if rec.init_runtime(core_mask=_rknn_shim._RKNN_NPU_CORE_0_1_2) != 0:
                raise ProviderNotAvailable("recognition init_runtime failed")
        except ProviderNotAvailable:
            try:
                det.release()
            except Exception:
                pass
            raise
        except RuntimeError as e:
            try:
                det.release()
            except Exception:
                pass
            raise ProviderNotAvailable(str(e)) from e

        self._det_runtime = det
        self._rec_runtime = rec
        self._det_variant = variant
        self._loaded_name = self._model_name
        log.info("loaded rockchip variant=%s kind=%s", variant.name, variant.kind)

    def warmup(self) -> bool:
        try:
            self._ensure_loaded()
            dummy_image = np.zeros((_DET_INPUT_SIZE, _DET_INPUT_SIZE, 3), dtype=np.uint8)
            self.detect(dummy_image)
            
            self._last_error = None
            return True
        except Exception as e:
            self._last_error = f"{type(e).__name__}: {e}"
            log.warning("rockchip warmup failed: %s", self._last_error)
            return False

    def is_loaded(self) -> bool:
        return (
            self._det_runtime is not None
            and self._rec_runtime is not None
            and self._loaded_name == self._model_name
        )

    def _preprocess_detection(self, bgr_image: np.ndarray) -> tuple[np.ndarray, float, float, float, float, float]:
        h, w = bgr_image.shape[:2]
        scale = min(_DET_INPUT_SIZE / w, _DET_INPUT_SIZE / h)
        nw, nh = int(round(w * scale)), int(round(h * scale))
        resized = cv2.resize(bgr_image, (nw, nh))
        canvas = np.full((_DET_INPUT_SIZE, _DET_INPUT_SIZE, 3), 0, dtype=np.uint8)
        canvas[:nh, :nw] = resized
        bgr = canvas.astype(np.float32) * (1.0 / 255.0)
        nchw = np.transpose(bgr, (2, 0, 1))[None, :, :, :]
        return np.ascontiguousarray(nchw), scale, float(nw), float(nh), float(w), float(h)

    def _decode_retinaface(
        self,
        outputs: list[np.ndarray],
        scale: float,
        nw: float,
        nh: float,
        w: float,
        h: float,
        score_thresh: float = 0.3,
        nms_iou: float = 0.4,
    ) -> list[tuple[float, float, float, float, float, np.ndarray]]:
        if len(outputs) != 9:
            return []
        boxes_out: list[list[float]] = []
        landmarks_out: list[np.ndarray] = []
        for stride, scores, bbox_pred, kps_pred in zip(
            _RETINA_STRIDES,
            outputs[0:3], outputs[3:6], outputs[6:9],
        ):
            feat_h = max(1, _DET_INPUT_SIZE // stride)
            feat_w = max(1, _DET_INPUT_SIZE // stride)
            
            if scores.shape[1] == _RETINA_ANCHORS_PER_CELL:
                scores = scores.transpose((0, 2, 3, 1))
                bbox_pred = bbox_pred.transpose((0, 2, 3, 1))
                kps_pred = kps_pred.transpose((0, 2, 3, 1))

            s = scores.reshape(-1)
            bbox_pred = bbox_pred.reshape(-1, 4) * stride
            kps_pred = kps_pred.reshape(-1, 10) * stride
            keep = np.where(s >= score_thresh)[0]
            if keep.size == 0:
                continue
            ax = np.arange(feat_w, dtype=np.float32) + 0.5
            ay = np.arange(feat_h, dtype=np.float32) + 0.5
            xv, yv = np.meshgrid(ax, ay)
            anchor_centers = (
                np.stack([xv, yv], axis=-1).reshape(-1, 2) * stride
            )
            anchor_centers = np.repeat(anchor_centers, _RETINA_ANCHORS_PER_CELL, axis=0)
            sel_centers = anchor_centers[keep]
            sel_bbox = bbox_pred[keep]
            sel_kps = kps_pred[keep]
            x1 = sel_centers[:, 0] - sel_bbox[:, 0]
            y1 = sel_centers[:, 1] - sel_bbox[:, 1]
            x2 = sel_centers[:, 0] + sel_bbox[:, 2]
            y2 = sel_centers[:, 1] + sel_bbox[:, 3]
            x1 = np.maximum(0.0, x1)
            y1 = np.maximum(0.0, y1)
            x2 = np.minimum(float(_DET_INPUT_SIZE), x2)
            y2 = np.minimum(float(_DET_INPUT_SIZE), y2)
            kps_x = np.empty((sel_kps.shape[0], 5), dtype=np.float32)
            kps_y = np.empty((sel_kps.shape[0], 5), dtype=np.float32)
            for i in range(5):
                kps_x[:, i] = sel_centers[:, 0] + sel_kps[:, i * 2]
                kps_y[:, i] = sel_centers[:, 1] + sel_kps[:, i * 2 + 1]
            kps_x = np.clip(kps_x, 0, _DET_INPUT_SIZE)
            kps_y = np.clip(kps_y, 0, _DET_INPUT_SIZE)
            for k, idx in enumerate(keep):
                boxes_out.append(
                    [float(x1[k]), float(y1[k]), float(x2[k]), float(y2[k]), float(s[idx])]
                )
                pts = np.stack([kps_x[k], kps_y[k]], axis=1).astype(np.float32)
                landmarks_out.append(pts)

        if not boxes_out:
            return []
        rects = np.array(
            [[bx[0], bx[1], bx[2] - bx[0], bx[3] - bx[1]] for bx in boxes_out],
            dtype=np.float32,
        )
        scores_arr = np.array([bx[4] for bx in boxes_out], dtype=np.float32)
        idxs = cv2.dnn.NMSBoxes(rects.tolist(), scores_arr.tolist(), score_thresh, nms_iou)
        if len(idxs) == 0:
            return []
        idxs = idxs.flatten()
        out: list[tuple[float, float, float, float, float, np.ndarray]] = []
        for i in idxs:
            x1, y1, x2, y2, sc = boxes_out[i]
            x1_orig = max(0.0, min(x1 / scale, w))
            y1_orig = max(0.0, min(y1 / scale, h))
            x2_orig = max(0.0, min(x2 / scale, w))
            y2_orig = max(0.0, min(y2 / scale, h))
            lm = landmarks_out[i] / scale
            lm[:, 0] = np.clip(lm[:, 0], 0, w - 1)
            lm[:, 1] = np.clip(lm[:, 1], 0, h - 1)
            out.append((x1_orig, y1_orig, x2_orig, y2_orig, sc, lm))
        return out

    def _umeyama(self, src: np.ndarray, dst: np.ndarray) -> np.ndarray:
        num = src.shape[0]
        dim = src.shape[1]
        src_mean = src.mean(axis=0)
        dst_mean = dst.mean(axis=0)
        src_demean = src - src_mean
        dst_demean = dst - dst_mean
        A = dst_demean.T @ src_demean / num
        d = np.ones((dim,), dtype=np.float64)
        if np.linalg.det(A) < 0:
            d[dim - 1] = -1
        T = np.eye(dim + 1, dtype=np.float64)
        U, S, V = np.linalg.svd(A)
        rank = np.linalg.matrix_rank(A)
        if rank == 0:
            return np.nan * T
        elif rank == dim - 1:
            if np.linalg.det(U) * np.linalg.det(V) > 0:
                T[:dim, :dim] = U @ V
            else:
                s = d[dim - 1]
                d[dim - 1] = -1
                T[:dim, :dim] = U @ np.diag(d) @ V
                d[dim - 1] = s
        else:
            T[:dim, :dim] = U @ np.diag(d) @ V
        scale = 1.0 / src_demean.var(axis=0).sum() * (S @ d)
        T[:dim, :dim] *= scale
        T[:dim, dim] = dst_mean - T[:dim, :dim] @ src_mean
        return T[:dim, :]

    def _norm_crop(self, bgr_image: np.ndarray, landmark: np.ndarray, image_size: int = 112) -> np.ndarray:
        arcface_dst = np.array(
            [
                [38.2946, 51.6963],
                [73.5318, 51.5014],
                [56.0252, 71.7366],
                [41.5493, 92.3655],
                [70.7299, 92.2041],
            ],
            dtype=np.float32,
        )
        if image_size == 112:
            dst = arcface_dst
        else:
            dst = arcface_dst * (image_size / 112.0)

        M = self._umeyama(landmark, dst)
        if np.isnan(M).any():
            return np.zeros((image_size, image_size, 3), dtype=np.uint8)

        aligned = cv2.warpAffine(bgr_image, M, (image_size, image_size), borderValue=0.0)
        return aligned

    def _preprocess_recognition(self, aligned_bgr: np.ndarray) -> np.ndarray:
        bgr = aligned_bgr.astype(np.float32) * (1.0 / 255.0)
        nchw = np.transpose(bgr, (2, 0, 1))[None, :, :, :]
        return np.ascontiguousarray(nchw)

    def detect(self, bgr_image: np.ndarray) -> list[Detection]:
        if bgr_image is None or bgr_image.size == 0:
            return []
        RockchipEngine._acquire_read()
        try:
            self._ensure_loaded()
            assert self._det_runtime is not None
            assert self._rec_runtime is not None

            nchw, scale, nw, nh, w, h = self._preprocess_detection(bgr_image)
            with self._inference_lock:
                det_outputs = self._det_runtime.inference([nchw], data_format="nchw")
            boxes = self._decode_retinaface(det_outputs, scale, nw, nh, w, h)
            if not boxes:
                return []

            results: list[Detection] = []
            for x1, y1, x2, y2, score, lm in boxes:
                if x2 - x1 < 4 or y2 - y1 < 4:
                    continue
                aligned = self._norm_crop(bgr_image, lm, image_size=_REC_INPUT_SIZE)
                rec_input = self._preprocess_recognition(aligned)
                with self._inference_lock:
                    rec_outputs = self._rec_runtime.inference([rec_input], data_format="nchw")
                if not rec_outputs:
                    continue
                emb = rec_outputs[0].reshape(-1).astype(np.float32)
                n = float(np.linalg.norm(emb))
                if n > 0:
                    emb = emb / n
                results.append(
                    Detection(
                        bbox=(float(x1), float(y1), float(x2), float(y2)),
                        score=float(score),
                        embedding=emb,
                    )
                )
            return results
        finally:
            RockchipEngine._release_read()

    def switch_model(self, new_name: str) -> None:
        RockchipEngine._acquire_write()
        try:
            log.info("switching rockchip model %s -> %s", self._model_name, new_name)
            self._model_name = new_name
            for rt in (self._det_runtime, self._rec_runtime):
                if rt is not None:
                    try:
                        rt.release()
                    except Exception:
                        pass
            self._det_runtime = None
            self._rec_runtime = None
            self._det_variant = None
            self._loaded_name = None
        finally:
            RockchipEngine._release_write()
