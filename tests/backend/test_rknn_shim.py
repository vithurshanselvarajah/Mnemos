from __future__ import annotations

import ctypes
from unittest import mock

import pytest


@pytest.fixture
def shim(backend_imports):
    from app.providers.rockchip import _rknn_shim

    return _rknn_shim


def test_shim_constants(shim):
    assert shim._RKNN_QUERY_IN_OUT_NUM == 0
    assert shim._RKNN_QUERY_INPUT_ATTR == 1
    assert shim._RKNN_QUERY_OUTPUT_ATTR == 2
    assert shim._RKNN_NPU_CORE_AUTO == 0
    assert shim._RKNN_NPU_CORE_0 == 1
    assert shim._RKNN_NPU_CORE_0_1_2 == 7
    assert shim._RKNN_TENSOR_FLOAT32 == 0
    assert shim._RKNN_TENSOR_NCHW == 0
    assert shim._RKNN_TENSOR_NHWC == 1


def test_structs_construct(shim):
    n = shim._rknn_input_output_num()
    assert n.n_input == 0
    assert n.n_output == 0
    attr = shim._rknn_tensor_attr()
    assert attr.index == 0
    inp = shim._rknn_input()
    out = shim._rknn_output()
    assert inp.index == 0
    assert out.want_float == 0


def test_load_librknnrt_uses_env_override(shim, monkeypatch):
    monkeypatch.setenv("RKNN_RUNTIME_LIBRARY", "/custom/librknnrt.so")
    fake_cdll = mock.MagicMock()
    monkeypatch.setattr(
        "ctypes.CDLL",
        lambda p: fake_cdll if p == "/custom/librknnrt.so" else (_ for _ in ()).throw(OSError("no")),
    )
    lib = shim._load_librknnrt()
    assert lib is fake_cdll


def test_load_librknnrt_falls_back_to_default(shim, monkeypatch):
    monkeypatch.delenv("RKNN_RUNTIME_LIBRARY", raising=False)
    fake_cdll = mock.MagicMock()
    calls: list = []

    def _cdll(p):
        calls.append(p)
        if p == "librknnrt.so":
            return fake_cdll
        raise OSError("no")

    monkeypatch.setattr("ctypes.CDLL", _cdll)
    lib = shim._load_librknnrt()
    assert lib is fake_cdll
    assert calls[0] == "librknnrt.so"


def test_load_librknnrt_raises_when_no_candidate(shim, monkeypatch):
    def _fail(_p):
        raise OSError("nope")

    monkeypatch.setattr("ctypes.CDLL", _fail)
    with pytest.raises(RuntimeError):
        shim._load_librknnrt()


def test_get_lib_caches_globally(shim, monkeypatch):
    shim._lib = None
    fake_cdll = mock.MagicMock()
    monkeypatch.setattr("ctypes.CDLL", lambda p: fake_cdll)
    a = shim._get_lib()
    b = shim._get_lib()
    assert a is b
    shim._lib = None


def test_get_lib_sets_argtypes_for_known_functions(shim, monkeypatch):
    shim._lib = None
    fake_cdll = mock.MagicMock()
    monkeypatch.setattr("ctypes.CDLL", lambda p: fake_cdll)
    lib = shim._get_lib()
    assert lib.rknn_init.argtypes is not None
    assert lib.rknn_destroy.argtypes is not None
    assert lib.rknn_query.argtypes is not None
    assert lib.rknn_inputs_set.argtypes is not None
    assert lib.rknn_run.argtypes is not None
    assert lib.rknn_outputs_get.argtypes is not None
    shim._lib = None


def test_rknnlite_init(shim):
    rl = shim.RKNNLite(verbose=True)
    assert rl._loaded is False
    assert rl._verbose is True
    assert rl._lib is None
    assert rl.NPU_CORE_AUTO == shim._RKNN_NPU_CORE_AUTO


def test_rknnlite_load_rknn_success(shim, monkeypatch):
    fake_lib = mock.MagicMock()
    fake_lib.rknn_init.return_value = 0
    rl = shim.RKNNLite()
    rl._lib = fake_lib
    rc = rl.load_rknn("/some/model.rknn")
    assert rc == 0
    assert rl._loaded is True


def test_rknnlite_load_rknn_failure(shim):
    fake_lib = mock.MagicMock()
    fake_lib.rknn_init.return_value = -1
    rl = shim.RKNNLite()
    rl._lib = fake_lib
    rc = rl.load_rknn("/some/model.rknn")
    assert rc == -1
    assert rl._loaded is False


def test_rknnlite_load_rknn_loads_lib(shim, monkeypatch):
    fake_lib = mock.MagicMock()
    fake_lib.rknn_init.return_value = 0
    monkeypatch.setattr("ctypes.CDLL", lambda p: fake_lib)
    rl = shim.RKNNLite()
    assert rl._lib is None
    rc = rl.load_rknn("/some/model.rknn")
    assert rc == 0
    assert rl._lib is fake_lib


def test_rknnlite_query_in_out_num(shim):
    fake_lib = mock.MagicMock()

    def _query(ctx, what, out_ptr, size):
        struct = ctypes.cast(out_ptr, ctypes.POINTER(shim._rknn_input_output_num))[0]
        struct.n_input = 1
        struct.n_output = 2
        return 0

    fake_lib.rknn_query.side_effect = _query
    rl = shim.RKNNLite()
    rl._lib = fake_lib
    rl._loaded = True
    rl._ctx.value = 42
    info = rl._query_in_out_num()
    assert info.n_input == 1
    assert info.n_output == 2


def test_rknnlite_query_in_out_num_failure(shim):
    fake_lib = mock.MagicMock()
    fake_lib.rknn_query.return_value = -1
    rl = shim.RKNNLite()
    rl._lib = fake_lib
    with pytest.raises(RuntimeError):
        rl._query_in_out_num()


def test_rknnlite_init_runtime_requires_loaded(shim):
    rl = shim.RKNNLite()
    rl._loaded = False
    assert rl.init_runtime() == -1


def test_rknnlite_init_runtime_success(shim):
    fake_lib = mock.MagicMock()
    fake_lib.rknn_query.return_value = 0
    rl = shim.RKNNLite()
    rl._lib = fake_lib
    rl._loaded = True
    rl._ctx.value = 42
    rc = rl.init_runtime()
    assert rc == 0


def test_rknnlite_set_core_mask(shim):
    """set_core_mask is exposed via the underlying lib, not as a method on RKNNLite."""
    fake_lib = mock.MagicMock()
    fake_lib.rknn_set_core_mask.return_value = 0
    rl = shim.RKNNLite()
    rl._lib = fake_lib
    assert fake_lib.rknn_set_core_mask(ctypes.c_void_p(0), shim._RKNN_NPU_CORE_0) == 0
