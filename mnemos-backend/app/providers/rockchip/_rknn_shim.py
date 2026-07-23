from __future__ import annotations

import ctypes
import os
import sys
import types
from typing import Any

import numpy as np


_RKNN_QUERY_IN_OUT_NUM = 0
_RKNN_QUERY_INPUT_ATTR = 1
_RKNN_QUERY_OUTPUT_ATTR = 2
_RKNN_QUERY_PERF_DETAIL = 3
_RKNN_QUERY_PERF_RUN = 4
_RKNN_QUERY_SDK_VERSION = 5
_RKNN_QUERY_MEM_SIZE = 6
_RKNN_NPU_CORE_AUTO = 0
_RKNN_NPU_CORE_0 = 1
_RKNN_NPU_CORE_1 = 2
_RKNN_NPU_CORE_2 = 4
_RKNN_NPU_CORE_0_1_2 = 7
_RKNN_TENSOR_FLOAT32 = 0
_RKNN_TENSOR_NCHW = 0
_RKNN_TENSOR_NHWC = 1


class _rknn_input_output_num(ctypes.Structure):
    _fields_ = [
        ("n_input", ctypes.c_uint32),
        ("n_output", ctypes.c_uint32),
    ]


class _rknn_tensor_attr(ctypes.Structure):
    _fields_ = [
        ("index", ctypes.c_uint32),
        ("n_dims", ctypes.c_uint32),
        ("dims", ctypes.c_uint32 * 16),
        ("name", ctypes.c_char * 256),
        ("n_elems", ctypes.c_uint32),
        ("size", ctypes.c_uint32),
        ("fmt", ctypes.c_int32),
        ("type", ctypes.c_int32),
        ("qnt_type", ctypes.c_int32),
        ("fl", ctypes.c_int8),
        ("zp", ctypes.c_int32),
        ("scale", ctypes.c_float),
        ("w_stride", ctypes.c_uint32),
        ("size_with_stride", ctypes.c_uint32),
        ("pass_through", ctypes.c_uint8),
        ("h_stride", ctypes.c_uint32),
    ]


class _rknn_input(ctypes.Structure):
    _fields_ = [
        ("index", ctypes.c_uint32),
        ("buf", ctypes.c_void_p),
        ("size", ctypes.c_uint32),
        ("pass_through", ctypes.c_uint8),
        ("type", ctypes.c_int32),
        ("fmt", ctypes.c_int32),
    ]


class _rknn_output(ctypes.Structure):
    _fields_ = [
        ("want_float", ctypes.c_uint8),
        ("is_prealloc", ctypes.c_uint8),
        ("index", ctypes.c_uint32),
        ("buf", ctypes.c_void_p),
        ("size", ctypes.c_uint32),
    ]


def _load_librknnrt() -> ctypes.CDLL:
    candidates = (
        os.environ.get("RKNN_RUNTIME_LIBRARY"),
        "librknnrt.so",
        "/usr/lib/librknnrt.so",
        "/usr/lib/aarch64-linux-gnu/librknnrt.so",
        "/usr/local/lib/librknnrt.so",
    )
    last_err: OSError | None = None
    for path in candidates:
        if not path:
            continue
        try:
            return ctypes.CDLL(path)
        except OSError as e:
            last_err = e
    raise RuntimeError(
        f"could not load librknnrt.so (looked at: {[c for c in candidates if c]}); "
        f"last error: {last_err}"
    )


_lib: ctypes.CDLL | None = None


def _get_lib() -> ctypes.CDLL:
    global _lib
    if _lib is None:
        _lib = _load_librknnrt()
        _lib.rknn_init.argtypes = [
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.c_char_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        _lib.rknn_init.restype = ctypes.c_int

        _lib.rknn_destroy.argtypes = [ctypes.c_void_p]
        _lib.rknn_destroy.restype = ctypes.c_int

        _lib.rknn_query.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        ]
        _lib.rknn_query.restype = ctypes.c_int

        _lib.rknn_inputs_set.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
        _lib.rknn_inputs_set.restype = ctypes.c_int

        _lib.rknn_run.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        _lib.rknn_run.restype = ctypes.c_int

        _lib.rknn_outputs_get.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        _lib.rknn_outputs_get.restype = ctypes.c_int

        if hasattr(_lib, "rknn_set_core_mask"):
            _lib.rknn_set_core_mask.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            _lib.rknn_set_core_mask.restype = ctypes.c_int

    return _lib


class RKNNLite:
    NPU_CORE_AUTO = _RKNN_NPU_CORE_AUTO

    def __init__(self, verbose: bool = False) -> None:
        self._ctx: ctypes.c_uint64 = ctypes.c_uint64(0)
        self._loaded = False
        self._verbose = verbose
        self._lib: ctypes.CDLL | None = None
        self._input_attrs: list[_rknn_tensor_attr] = []
        self._output_attrs: list[_rknn_tensor_attr] = []

    def _ensure_lib(self) -> ctypes.CDLL:
        if self._lib is None:
            self._lib = _get_lib()
        return self._lib

    def load_rknn(self, model_path: str | os.PathLike[str]) -> int:
        lib = self._ensure_lib()
        ret = lib.rknn_init(
            ctypes.byref(self._ctx),
            os.fsencode(model_path) if isinstance(model_path, str) else model_path,
            0,
            0,
            ctypes.c_void_p(0),
        )
        if ret == 0:
            self._loaded = True
        return ret

    def _query_in_out_num(self) -> _rknn_input_output_num:
        lib = self._ensure_lib()
        out = _rknn_input_output_num()
        ret = lib.rknn_query(
            self._ctx.value,
            _RKNN_QUERY_IN_OUT_NUM,
            ctypes.byref(out),
            ctypes.sizeof(out),
        )
        if ret != 0:
            raise RuntimeError(f"rknn_query(IN_OUT_NUM) failed: {ret}")
        return out

    def _query_attrs(self, what: int, n: int) -> list[_rknn_tensor_attr]:
        lib = self._ensure_lib()
        results: list[_rknn_tensor_attr] = []
        for i in range(n):
            attr = _rknn_tensor_attr()
            attr.index = i
            ret = lib.rknn_query(
                self._ctx.value, what, ctypes.byref(attr), ctypes.sizeof(attr)
            )
            if ret != 0:
                raise RuntimeError(f"rknn_query({what}, index={i}) failed: {ret}")
            results.append(attr)
        return results

    def init_runtime(self, core_mask: int | None = None) -> int:
        if not self._loaded:
            return -1
        lib = self._ensure_lib()
        if core_mask is not None and hasattr(lib, "rknn_set_core_mask"):
            ret = lib.rknn_set_core_mask(self._ctx.value, core_mask)
            if ret != 0:
                print(f"Warning: rknn_set_core_mask({core_mask}) failed with {ret}. Falling back to AUTO.")
                lib.rknn_set_core_mask(self._ctx.value, _RKNN_NPU_CORE_AUTO)

        counts = self._query_in_out_num()
        n_in, n_out = int(counts.n_input), int(counts.n_output)
        if n_in > 0:
            self._input_attrs = self._query_attrs(_RKNN_QUERY_INPUT_ATTR, n_in)
        if n_out > 0:
            self._output_attrs = self._query_attrs(_RKNN_QUERY_OUTPUT_ATTR, n_out)
        return 0

    @property
    def input_attrs(self) -> list[_rknn_tensor_attr]:
        return list(self._input_attrs)

    @property
    def output_attrs(self) -> list[_rknn_tensor_attr]:
        return list(self._output_attrs)

    def inference(self, inputs: list[np.ndarray], data_format: str = "nchw") -> list[np.ndarray]:
        if not self._loaded:
            raise RuntimeError("model not loaded")
        if len(inputs) != len(self._input_attrs):
            raise ValueError(
                f"expected {len(self._input_attrs)} input(s), got {len(inputs)}"
            )
        lib = self._ensure_lib()

        input_structs = (_rknn_input * len(inputs))()
        bufs: list[tuple[np.ndarray, int]] = []
        try:
            for i, (arr, attr) in enumerate(zip(inputs, self._input_attrs)):
                if arr.dtype != np.float32:
                    arr = arr.astype(np.float32, copy=False)
                if int(attr.fmt) == _RKNN_TENSOR_NHWC and arr.ndim == 4:
                    arr = np.transpose(arr, (0, 2, 3, 1))
                arr = np.ascontiguousarray(arr)
                if not arr.flags["C_CONTIGUOUS"]:
                    raise ValueError("input must be C-contiguous")
                buf = arr.ctypes.data_as(ctypes.c_void_p)
                size = arr.nbytes
                bufs.append((arr, size))
                input_structs[i].index = i
                input_structs[i].buf = buf
                input_structs[i].size = ctypes.c_uint32(size)
                input_structs[i].type = _RKNN_TENSOR_FLOAT32
                input_structs[i].fmt = int(attr.fmt)
                input_structs[i].pass_through = 0

            ret = lib.rknn_inputs_set(self._ctx.value, len(inputs), ctypes.byref(input_structs))
            if ret != 0:
                raise RuntimeError(f"rknn_inputs_set failed: {ret}")

            ret = lib.rknn_run(self._ctx.value, ctypes.c_void_p(0))
            if ret != 0:
                raise RuntimeError(f"rknn_run failed: {ret}")

            n_out = len(self._output_attrs)
            out_structs = (_rknn_output * n_out)()
            for i, attr in enumerate(self._output_attrs):
                out_structs[i].want_float = 1
                out_structs[i].is_prealloc = 0
                out_structs[i].index = i
                out_structs[i].buf = ctypes.c_void_p(0)
                out_structs[i].size = 0

            ret = lib.rknn_outputs_get(
                self._ctx.value, n_out, ctypes.byref(out_structs), ctypes.c_void_p(0)
            )
            if ret != 0:
                raise RuntimeError(f"rknn_outputs_get failed: {ret}")

            results: list[np.ndarray] = []
            for i, attr in enumerate(self._output_attrs):
                buf_ptr = out_structs[i].buf
                if not buf_ptr:
                    n_elems = max(int(attr.n_elems), 1)
                    results.append(np.zeros((n_elems,), dtype=np.float32))
                    continue
                n_bytes = int(out_structs[i].size)
                n_floats = max(n_bytes // 4, 1)
                raw = (ctypes.c_float * n_floats).from_address(buf_ptr)
                arr = np.ctypeslib.as_array(raw).copy()
                logical_shape = tuple(int(d) for d in attr.dims[: attr.n_dims])
                expected = 1
                for d in logical_shape:
                    expected *= d
                if expected == n_floats and len(logical_shape) > 1:
                    arr = arr.reshape(logical_shape)
                else:
                    arr = arr.reshape((n_floats,))
                results.append(arr)

            return results
        finally:
            del bufs

    def release(self) -> int:
        if not self._loaded:
            return 0
        lib = self._ensure_lib()
        ret = lib.rknn_destroy(self._ctx.value)
        self._ctx = ctypes.c_uint64(0)
        self._loaded = False
        self._input_attrs = []
        self._output_attrs = []
        return ret


def _register() -> None:
    if "rknnlite" in sys.modules:
        return
    pkg = types.ModuleType("rknnlite")
    pkg.__path__ = []
    api = types.ModuleType("rknnlite.api")
    api.RKNNLite = RKNNLite
    pkg.api = api
    pkg.RKNNLite = RKNNLite
    sys.modules["rknnlite"] = pkg
    sys.modules["rknnlite.api"] = api


_register()
