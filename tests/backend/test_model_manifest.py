from __future__ import annotations

from unittest import mock

import pytest

MANIFEST_STANDARD = {
    "base_url": "https://models.example.com/",
    "models": {
        "buffalo_s": {
            "standard": {
                "detection": {
                    "path": "/models/buffalo_s/det.onnx",
                    "filename": "det.onnx",
                    "sha256": "a" * 64,
                    "size_bytes": 1024,
                },
                "recognition": {
                    "path": "/models/buffalo_s/rec.onnx",
                    "filename": "rec.onnx",
                    "sha256": "b" * 64,
                    "size_bytes": 2048,
                },
            }
        },
        "antelopev2": {
            "standard": {
                "detection": {
                    "path": "/models/antelopev2/det.onnx",
                    "filename": "det.onnx",
                    "sha256": "c" * 64,
                    "size_bytes": 4096,
                }
            }
        },
    },
}


MANIFEST_ROCKCHIP = {
    "base_url": "https://models.example.com/",
    "models": {
        "buffalo_s": {
            "standard": {
                "detection": {
                    "path": "/models/buffalo_s/det.onnx",
                    "filename": "det.onnx",
                    "sha256": "a" * 64,
                    "size_bytes": 1024,
                }
            },
            "rknn": {
                "rk3588": {
                    "detection": {
                        "path": "/models/buffalo_s/rk3588/det.rknn",
                        "filename": "det.rknn",
                        "sha256": "d" * 64,
                        "size_bytes": 8192,
                    }
                },
                "rk3568": {
                    "detection": {
                        "path": "/models/buffalo_s/rk3568/det.rknn",
                        "filename": "det.rknn",
                        "sha256": "e" * 64,
                        "size_bytes": 16384,
                    }
                },
            },
        }
    },
}


@pytest.fixture
def manifest_module(backend_imports):
    from app.services import model_manifest

    return model_manifest


def test_read_manifest_returns_data(manifest_module, monkeypatch):
    fake_resp = mock.Mock()
    fake_resp.content = b'{"base_url": "https://x/", "models": {}}'
    monkeypatch.setattr(manifest_module.requests, "get", lambda *a, **kw: fake_resp)
    out = manifest_module._read_manifest()
    assert out == {"base_url": "https://x/", "models": {}}


def test_read_manifest_rejects_bad_payload(manifest_module, monkeypatch):
    fake_resp = mock.Mock()
    fake_resp.content = b'{"foo": 1}'
    monkeypatch.setattr(manifest_module.requests, "get", lambda *a, **kw: fake_resp)
    with pytest.raises(ValueError):
        manifest_module._read_manifest()


def test_read_manifest_retries_on_failure(manifest_module, monkeypatch):
    """If every attempt fails, the final exception is raised."""
    sleeps: list[float] = []
    monkeypatch.setattr(manifest_module.time, "sleep", lambda d: sleeps.append(d))

    call_count = {"n": 0}

    def _fail(*a, **kw):
        call_count["n"] += 1
        raise RuntimeError("network down")

    monkeypatch.setattr(manifest_module.requests, "get", _fail)
    with pytest.raises(RuntimeError):
        manifest_module._read_manifest()
    assert call_count["n"] == 6


def test_read_manifest_succeeds_after_one_failure(manifest_module, monkeypatch):
    monkeypatch.setattr(manifest_module.time, "sleep", lambda d: None)

    good_resp = mock.Mock()
    good_resp.content = b'{"base_url": "https://x/", "models": {"m": {}}}'

    def _sometimes_fail(*a, **kw):
        if not hasattr(_sometimes_fail, "called"):
            _sometimes_fail.called = True
            raise RuntimeError("transient")
        return good_resp

    monkeypatch.setattr(manifest_module.requests, "get", _sometimes_fail)
    out = manifest_module._read_manifest()
    assert "models" in out


def test_artifact_to_url_and_path_strips_models_prefix(manifest_module):
    art = manifest_module._artifact_to_url_and_path(
        "https://models.example.com/",
        "buffalo_s",
        "standard",
        "",
        {
            "path": "/models/buffalo_s/det.onnx",
            "filename": "det.onnx",
            "sha256": "a" * 64,
            "size_bytes": 1024,
        },
    )
    assert art.url == "https://models.example.com/models/buffalo_s/det.onnx"
    assert art.filename == "det.onnx"
    assert art.size_bytes == 1024
    assert art.sha256 == "a" * 64
    assert "buffalo_s" in art.local_path


def test_artifact_to_url_and_path_keeps_path_without_models_prefix(manifest_module):
    art = manifest_module._artifact_to_url_and_path(
        "https://x/",
        "buffalo_s",
        "standard",
        "",
        {
            "path": "other/det.onnx",
            "filename": "det.onnx",
            "sha256": "a" * 64,
            "size_bytes": 1024,
        },
    )
    assert art.url == "https://x/other/det.onnx"


def test_artifact_to_url_and_path_rejects_missing_keys(manifest_module):
    with pytest.raises(ValueError):
        manifest_module._artifact_to_url_and_path(
            "https://x/",
            "buffalo_s",
            "standard",
            "",
            {"path": "/x", "filename": "det.onnx", "sha256": "a" * 64},
        )


def test_variants_for_provider_cpu(manifest_module, monkeypatch):
    monkeypatch.setattr(manifest_module.settings, "provider", "cpu")
    monkeypatch.setattr(manifest_module.settings, "models_root", "/tmp/models")
    variants = manifest_module._variants_for_provider(MANIFEST_STANDARD)
    assert {v.name for v in variants} == {"buffalo_s", "antelopev2"}
    buffalo = next(v for v in variants if v.name == "buffalo_s")
    assert buffalo.kind == "standard"
    assert len(buffalo.artifacts) == 2


def test_variants_for_provider_nvidia(manifest_module, monkeypatch):
    monkeypatch.setattr(manifest_module.settings, "provider", "nvidia")
    monkeypatch.setattr(manifest_module.settings, "models_root", "/tmp/models")
    variants = manifest_module._variants_for_provider(MANIFEST_STANDARD)
    assert {v.name for v in variants} == {"buffalo_s", "antelopev2"}


def test_variants_for_provider_rockchip(manifest_module, monkeypatch):
    monkeypatch.setattr(manifest_module.settings, "provider", "rockchip")
    monkeypatch.setattr(manifest_module.settings, "rockchip_soc", "rk3588")
    monkeypatch.setattr(manifest_module.settings, "models_root", "/tmp/models")
    variants = manifest_module._variants_for_provider(MANIFEST_ROCKCHIP)
    assert len(variants) == 1
    assert variants[0].kind == "rknn/rk3588"
    assert variants[0].name == "buffalo_s"


def test_variants_for_provider_rockchip_no_match(manifest_module, monkeypatch):
    monkeypatch.setattr(manifest_module.settings, "provider", "rockchip")
    monkeypatch.setattr(manifest_module.settings, "rockchip_soc", "rk3399")
    monkeypatch.setattr(manifest_module.settings, "models_root", "/tmp/models")
    variants = manifest_module._variants_for_provider(MANIFEST_ROCKCHIP)
    assert variants == []


def test_available_models_reads_manifest(manifest_module, monkeypatch):
    fake_resp = mock.Mock()
    fake_resp.content = b'{"base_url": "https://x/", "models": {}}'
    monkeypatch.setattr(manifest_module.requests, "get", lambda *a, **kw: fake_resp)
    monkeypatch.setattr(manifest_module.settings, "provider", "cpu")
    out = manifest_module.available_models()
    assert out == []


def test_variant_for_returns_match(manifest_module, monkeypatch):
    monkeypatch.setattr(manifest_module.settings, "provider", "cpu")
    monkeypatch.setattr(manifest_module.settings, "models_root", "/tmp/models")

    def _fake_read():
        return MANIFEST_STANDARD

    monkeypatch.setattr(manifest_module, "_read_manifest", _fake_read)
    v = manifest_module.variant_for("buffalo_s")
    assert v.name == "buffalo_s"


def test_variant_for_raises_on_missing(manifest_module, monkeypatch):
    monkeypatch.setattr(manifest_module.settings, "provider", "cpu")
    monkeypatch.setattr(manifest_module.settings, "models_root", "/tmp/models")

    def _fake_read():
        return MANIFEST_STANDARD

    monkeypatch.setattr(manifest_module, "_read_manifest", _fake_read)
    with pytest.raises(KeyError):
        manifest_module.variant_for("nonexistent_model")


def test_detect_rockchip_soc_uses_override(manifest_module, monkeypatch):
    monkeypatch.setattr(manifest_module.settings, "rockchip_soc", "rk3568")
    assert manifest_module._detect_rockchip_soc() == "rk3568"


def test_detect_rockchip_soc_strips_whitespace(manifest_module, monkeypatch):
    monkeypatch.setattr(manifest_module.settings, "rockchip_soc", "  rk3588  ")
    assert manifest_module._detect_rockchip_soc() == "rk3588"


def test_detect_rockchip_soc_defaults_when_no_dt(tmp_path, manifest_module, monkeypatch):
    monkeypatch.setattr(manifest_module.settings, "rockchip_soc", "")
    monkeypatch.setattr(manifest_module, "_RK_DT_COMPATIBLE", str(tmp_path / "missing"))
    assert manifest_module._detect_rockchip_soc() == "rk3588"


def test_detect_rockchip_soc_parses_dt(tmp_path, manifest_module, monkeypatch):
    p = tmp_path / "compatible"
    p.write_bytes(b"rockchip,rk3588\0rockchip,rk3568\0")
    monkeypatch.setattr(manifest_module.settings, "rockchip_soc", "")
    monkeypatch.setattr(manifest_module, "_RK_DT_COMPATIBLE", str(p))
    assert manifest_module._detect_rockchip_soc() == "rk3588"


def test_detect_rockchip_soc_prefers_known_order(tmp_path, manifest_module, monkeypatch):
    """Preference order is rk3588 > rk3576 > rk3568 > rk3566."""
    p = tmp_path / "compatible"
    p.write_bytes(b"rockchip,rk3568\0rockchip,rk3588\0")
    monkeypatch.setattr(manifest_module.settings, "rockchip_soc", "")
    monkeypatch.setattr(manifest_module, "_RK_DT_COMPATIBLE", str(p))
    assert manifest_module._detect_rockchip_soc() == "rk3588"


def test_detect_rockchip_soc_falls_back_to_sorted(tmp_path, manifest_module, monkeypatch):
    """Unknown SoCs sort alphabetically."""
    p = tmp_path / "compatible"
    p.write_bytes(b"rockchip,rk9999\0rockchip,rk1234\0")
    monkeypatch.setattr(manifest_module.settings, "rockchip_soc", "")
    monkeypatch.setattr(manifest_module, "_RK_DT_COMPATIBLE", str(p))
    assert manifest_module._detect_rockchip_soc() == "rk1234"


def test_supported_rockchip_socs(manifest_module, monkeypatch):
    monkeypatch.setattr(manifest_module, "_read_manifest", lambda: MANIFEST_ROCKCHIP)
    socs = manifest_module.supported_rockchip_socs()
    assert "rk3588" in socs
    assert "rk3568" in socs


def test_supported_rockchip_socs_empty_on_failure(manifest_module, monkeypatch):
    def _boom():
        raise RuntimeError("no net")

    monkeypatch.setattr(manifest_module, "_read_manifest", _boom)
    assert manifest_module.supported_rockchip_socs() == []


def test_preflight_provider_cpu_passes(manifest_module, monkeypatch):
    monkeypatch.setattr(manifest_module.settings, "provider", "cpu")
    manifest_module.preflight_provider()


def test_preflight_provider_rockchip_wrong_arch(manifest_module, monkeypatch):
    monkeypatch.setattr(manifest_module.settings, "provider", "rockchip")
    monkeypatch.setattr(manifest_module.settings, "rockchip_soc", "rk3588")
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    with pytest.raises(SystemExit):
        manifest_module.preflight_provider()


def test_preflight_provider_rockchip_unsupported_soc(manifest_module, monkeypatch):
    monkeypatch.setattr(manifest_module.settings, "provider", "rockchip")
    monkeypatch.setattr(manifest_module.settings, "rockchip_soc", "rk3399")
    monkeypatch.setattr("platform.machine", lambda: "aarch64")
    monkeypatch.setattr(manifest_module, "supported_rockchip_socs", lambda: ["rk3588"])
    with pytest.raises(SystemExit):
        manifest_module.preflight_provider()


def test_preflight_provider_rockchip_supported(manifest_module, monkeypatch):
    monkeypatch.setattr(manifest_module.settings, "provider", "rockchip")
    monkeypatch.setattr(manifest_module.settings, "rockchip_soc", "rk3588")
    monkeypatch.setattr("platform.machine", lambda: "aarch64")
    monkeypatch.setattr(manifest_module, "supported_rockchip_socs", lambda: ["rk3588"])
    manifest_module.preflight_provider()


def test_preflight_provider_nvidia_no_onnxruntime(manifest_module, monkeypatch):
    monkeypatch.setattr(manifest_module.settings, "provider", "nvidia")
    monkeypatch.setattr(
        "app.providers.nvidia.detect_cuda_provider",
        lambda: {"onnxruntime_available": False, "last_error": "no onnx"},
    )
    with pytest.raises(SystemExit):
        manifest_module.preflight_provider()


def test_preflight_provider_nvidia_no_cuda(manifest_module, monkeypatch):
    monkeypatch.setattr(manifest_module.settings, "provider", "nvidia")
    monkeypatch.setattr(
        "app.providers.nvidia.detect_cuda_provider",
        lambda: {
            "onnxruntime_available": True,
            "cuda_available": False,
            "available_providers": ["CPUExecutionProvider"],
            "device_count": 0,
            "last_error": "",
        },
    )
    with pytest.raises(SystemExit):
        manifest_module.preflight_provider()


def test_preflight_provider_nvidia_no_devices(manifest_module, monkeypatch):
    monkeypatch.setattr(manifest_module.settings, "provider", "nvidia")
    monkeypatch.setattr(
        "app.providers.nvidia.detect_cuda_provider",
        lambda: {
            "onnxruntime_available": True,
            "cuda_available": True,
            "available_providers": ["CUDAExecutionProvider"],
            "device_count": 0,
            "last_error": "",
        },
    )
    with pytest.raises(SystemExit):
        manifest_module.preflight_provider()


def test_preflight_provider_nvidia_success(manifest_module, monkeypatch):
    monkeypatch.setattr(manifest_module.settings, "provider", "nvidia")
    monkeypatch.setattr(
        "app.providers.nvidia.detect_cuda_provider",
        lambda: {
            "onnxruntime_available": True,
            "cuda_available": True,
            "available_providers": ["CUDAExecutionProvider"],
            "device_count": 1,
            "last_error": "",
        },
    )
    manifest_module.preflight_provider()
