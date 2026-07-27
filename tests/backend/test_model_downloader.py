from __future__ import annotations

import hashlib
from unittest import mock

import pytest


@pytest.fixture
def classes(backend_imports):
    from app.services.model_manifest import ModelArtifact, ModelVariant

    return ModelArtifact, ModelVariant


@pytest.fixture
def dl(backend_imports):
    from app.services import model_downloader

    return model_downloader


def _artifact(classes, tmp_path, *, name="det.onnx", size=1024, sha=None):
    ModelArtifact, _ = classes
    if sha is None:
        sha = hashlib.sha256(b"\0" * size).hexdigest()
    local = tmp_path / "models" / "buffalo_s" / name
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(b"\0" * size)
    return ModelArtifact(
        filename=name,
        url=f"https://example.com/{name}",
        size_bytes=size,
        sha256=sha,
        local_path=str(local),
    )


class _FakeResponse:
    def __init__(
        self,
        *,
        chunks: list[bytes],
        status: int = 200,
        headers: dict | None = None,
    ) -> None:
        self._chunks = list(chunks)
        self.status_code = status
        self.headers = headers or {}
        self._iter_idx = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def iter_content(self, chunk_size: int):
        while self._iter_idx < len(self._chunks):
            yield self._chunks[self._iter_idx]
            self._iter_idx += 1


def test_hash_file_matches(tmp_path, dl):
    p = tmp_path / "x.bin"
    p.write_bytes(b"hello")
    expected = hashlib.sha256(b"hello").hexdigest()
    assert dl._hash_file(str(p), expected) is True


def test_hash_file_mismatch(tmp_path, dl):
    p = tmp_path / "x.bin"
    p.write_bytes(b"hello")
    assert dl._hash_file(str(p), "0" * 64) is False


def test_hash_file_case_insensitive(tmp_path, dl):
    p = tmp_path / "x.bin"
    p.write_bytes(b"hi")
    expected = hashlib.sha256(b"hi").hexdigest().upper()
    assert dl._hash_file(str(p), expected) is True


def test_download_artifact_already_verified(classes, tmp_path, dl, monkeypatch):
    art = _artifact(classes, tmp_path, size=8)
    downloads = {"called": 0}

    def _no_get(*a, **kw):
        downloads["called"] += 1
        raise AssertionError("should not be called")

    monkeypatch.setattr(dl.requests, "get", _no_get)
    dl.download_artifact(art, model_name="buffalo_s")
    assert downloads["called"] == 0
    assert (tmp_path / "models" / "buffalo_s" / "det.onnx").is_file()


def test_download_artifact_existing_bad_sha_redownloads(classes, tmp_path, dl, monkeypatch):
    real_art = _artifact(classes, tmp_path, size=8)
    (tmp_path / "models" / "buffalo_s" / "det.onnx").write_bytes(b"corrupted")
    body = b"\0" * 8
    fake = _FakeResponse(chunks=[body], status=200, headers={"Content-Length": "8"})
    monkeypatch.setattr(dl.requests, "get", lambda *a, **kw: fake)
    dl.download_artifact(real_art, model_name="buffalo_s")
    assert (tmp_path / "models" / "buffalo_s" / "det.onnx").is_file()


def test_download_artifact_full_download(classes, tmp_path, dl, monkeypatch):
    ModelArtifact, _ = classes
    expected_sha = hashlib.sha256(b"\0" * 64).hexdigest()
    real_art = ModelArtifact(
        filename="det.onnx",
        url="https://x/det.onnx",
        size_bytes=64,
        sha256=expected_sha,
        local_path=str(tmp_path / "fresh" / "det.onnx"),
    )
    fake = _FakeResponse(chunks=[b"\0" * 32, b"\0" * 32], status=200, headers={"Content-Length": "64"})
    monkeypatch.setattr(dl.requests, "get", lambda *a, **kw: fake)
    dl.download_artifact(real_art, model_name="buffalo_s")
    assert (tmp_path / "fresh" / "det.onnx").is_file()
    assert not (tmp_path / "fresh" / "det.onnx.part").exists()


def test_download_artifact_progress_callback(classes, tmp_path, dl, monkeypatch):
    ModelArtifact, _ = classes
    expected_sha = hashlib.sha256(b"\0" * 64).hexdigest()
    real_art = ModelArtifact(
        filename="det.onnx",
        url="https://x/det.onnx",
        size_bytes=64,
        sha256=expected_sha,
        local_path=str(tmp_path / "p" / "det.onnx"),
    )
    fake = _FakeResponse(chunks=[b"\0" * 64], status=200, headers={"Content-Length": "64"})
    monkeypatch.setattr(dl.requests, "get", lambda *a, **kw: fake)
    calls: list = []

    def _cb(done, total, model, artifact=None):
        calls.append((done, total, model, artifact))

    dl.download_artifact(real_art, model_name="buffalo_s", on_progress=_cb)
    assert calls[-1][0] == 64


def test_download_artifact_range_resume(classes, tmp_path, dl, monkeypatch):
    ModelArtifact, _ = classes
    expected_sha = hashlib.sha256(b"\0" * 64).hexdigest()
    real_art = ModelArtifact(
        filename="det.onnx",
        url="https://x/det.onnx",
        size_bytes=64,
        sha256=expected_sha,
        local_path=str(tmp_path / "r" / "det.onnx"),
    )
    (tmp_path / "r").mkdir(parents=True, exist_ok=True)
    (tmp_path / "r" / "det.onnx.part").write_bytes(b"\0" * 32)
    fake = _FakeResponse(chunks=[b"\0" * 32], status=206, headers={})
    seen_headers: dict = {}

    def _capture(url, headers=None, **_kw):
        seen_headers.update(headers or {})
        return fake

    monkeypatch.setattr(dl.requests, "get", _capture)
    dl.download_artifact(real_art, model_name="buffalo_s")
    assert seen_headers.get("Range") == "bytes=32-"
    assert (tmp_path / "r" / "det.onnx").is_file()


def test_download_artifact_server_ignores_range_restarts(classes, tmp_path, dl, monkeypatch):
    ModelArtifact, _ = classes
    expected_sha = hashlib.sha256(b"\0" * 64).hexdigest()
    real_art = ModelArtifact(
        filename="det.onnx",
        url="https://x/det.onnx",
        size_bytes=64,
        sha256=expected_sha,
        local_path=str(tmp_path / "q" / "det.onnx"),
    )
    (tmp_path / "q").mkdir(parents=True, exist_ok=True)
    (tmp_path / "q" / "det.onnx.part").write_bytes(b"\0" * 32)
    fake = _FakeResponse(chunks=[b"\0" * 64], status=200, headers={"Content-Length": "64"})
    monkeypatch.setattr(dl.requests, "get", lambda *a, **kw: fake)
    dl.download_artifact(real_art, model_name="buffalo_s")
    assert (tmp_path / "q" / "det.onnx").is_file()


def test_download_artifact_truncation_raises(classes, tmp_path, dl, monkeypatch):
    ModelArtifact, _ = classes
    real_art = ModelArtifact(
        filename="det.onnx",
        url="https://x/det.onnx",
        size_bytes=128,
        sha256="00",
        local_path=str(tmp_path / "t" / "det.onnx"),
    )
    fake = _FakeResponse(chunks=[b"\0" * 32], status=200, headers={"Content-Length": "128"})
    monkeypatch.setattr(dl.requests, "get", lambda *a, **kw: fake)
    with pytest.raises(dl.DownloadError):
        dl.download_artifact(real_art, model_name="buffalo_s")


def test_download_artifact_sha_mismatch_raises(classes, tmp_path, dl, monkeypatch):
    ModelArtifact, _ = classes
    real_art = ModelArtifact(
        filename="det.onnx",
        url="https://x/det.onnx",
        size_bytes=8,
        sha256="f" * 64,
        local_path=str(tmp_path / "m" / "det.onnx"),
    )
    fake = _FakeResponse(chunks=[b"\0" * 8], status=200, headers={"Content-Length": "8"})
    monkeypatch.setattr(dl.requests, "get", lambda *a, **kw: fake)
    with pytest.raises(dl.DownloadError):
        dl.download_artifact(real_art, model_name="buffalo_s")


def test_download_artifact_http_error(classes, tmp_path, dl, monkeypatch):
    ModelArtifact, _ = classes
    real_art = ModelArtifact(
        filename="det.onnx",
        url="https://x/det.onnx",
        size_bytes=8,
        sha256="0" * 64,
        local_path=str(tmp_path / "h" / "det.onnx"),
    )
    fake = _FakeResponse(chunks=[], status=500, headers={})
    monkeypatch.setattr(dl.requests, "get", lambda *a, **kw: fake)
    with pytest.raises(dl.DownloadError):
        dl.download_artifact(real_art, model_name="buffalo_s")


def test_download_artifact_broadcasts(classes, tmp_path, dl, monkeypatch):
    ModelArtifact, _ = classes
    real_art = ModelArtifact(
        filename="det.onnx",
        url="https://x/det.onnx",
        size_bytes=8,
        sha256=hashlib.sha256(b"\0" * 8).hexdigest(),
        local_path=str(tmp_path / "b" / "det.onnx"),
    )
    fake = _FakeResponse(chunks=[b"\0" * 8], status=200, headers={"Content-Length": "8"})
    monkeypatch.setattr(dl.requests, "get", lambda *a, **kw: fake)
    broadcasts: list = []
    monkeypatch.setattr(dl.websocket_hub, "publish", lambda payload: broadcasts.append(payload))
    dl.download_artifact(real_art, model_name="buffalo_s")
    assert any(p.get("type") == "reindex.download" for p in broadcasts)


def test_download_variant_calls_each_artifact(classes, tmp_path, dl, monkeypatch):
    _, ModelVariant = classes
    arts = (
        _artifact(classes, tmp_path, name="a.onnx", size=4),
        _artifact(classes, tmp_path, name="b.onnx", size=8),
    )
    variant = ModelVariant(name="buffalo_s", kind="standard", artifacts=arts)
    downloads = {"calls": 0}

    def _already(*a, **kw):
        downloads["calls"] += 1

    monkeypatch.setattr(dl, "download_artifact", _already)
    dl.download_variant(variant)
    assert downloads["calls"] == 2


def test_variant_files_present_returns_true(classes, tmp_path, dl):
    _, ModelVariant = classes
    art = _artifact(classes, tmp_path, size=8)
    variant = ModelVariant(name="buffalo_s", kind="standard", artifacts=(art,))
    assert dl.variant_files_present(variant) is True


def test_variant_files_present_missing_file(classes, tmp_path, dl):
    ModelArtifact, ModelVariant = classes
    real_art = ModelArtifact(
        filename="missing.onnx",
        url="https://x",
        size_bytes=8,
        sha256=hashlib.sha256(b"\0" * 8).hexdigest(),
        local_path=str(tmp_path / "missing.onnx"),
    )
    variant = ModelVariant(name="buffalo_s", kind="standard", artifacts=(real_art,))
    assert dl.variant_files_present(variant) is False


def test_variant_files_present_wrong_size(classes, tmp_path, dl):
    ModelArtifact, ModelVariant = classes
    real_art = _artifact(classes, tmp_path, size=8)
    real_art_wrong_size = ModelArtifact(
        filename=real_art.filename,
        url=real_art.url,
        size_bytes=99999,
        sha256=real_art.sha256,
        local_path=real_art.local_path,
    )
    variant = ModelVariant(name="buffalo_s", kind="standard", artifacts=(real_art_wrong_size,))
    assert dl.variant_files_present(variant) is False


def test_is_model_ready_checks_variant(dl, monkeypatch):
    fake_variant = mock.Mock()
    monkeypatch.setattr(dl, "variant_files_present", lambda v: True)
    monkeypatch.setattr("app.services.model_manifest.variant_for", lambda n: fake_variant)
    assert dl.is_model_ready("buffalo_s") is True
