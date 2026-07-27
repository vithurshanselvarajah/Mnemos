from __future__ import annotations

import pytest


@pytest.fixture
def reindex(backend_imports):
    from app.db.session import init_db
    from app.services import reindex as reindex_mod

    init_db()
    return reindex_mod


def test_reindex_state_initial(reindex):
    s = reindex.ReindexState()
    snap = s.snapshot()
    assert snap == {
        "running": False,
        "model": "",
        "total": 0,
        "done": 0,
        "error": None,
        "download_active": False,
        "download_model": "",
        "download_artifact": None,
        "download_done": 0,
        "download_total": 0,
    }


def test_reindex_state_start(reindex):
    s = reindex.ReindexState()
    s.start("buffalo_s", 100)
    snap = s.snapshot()
    assert snap["running"] is True
    assert snap["model"] == "buffalo_s"
    assert snap["total"] == 100
    assert snap["done"] == 0
    assert snap["error"] is None


def test_reindex_state_progress(reindex):
    s = reindex.ReindexState()
    s.start("buffalo_s", 100)
    s.progress(42)
    assert s.snapshot()["done"] == 42


def test_reindex_state_finish_clears_running(reindex):
    s = reindex.ReindexState()
    s.start("buffalo_s", 100)
    s.finish()
    assert s.snapshot()["running"] is False
    assert s.snapshot()["error"] is None


def test_reindex_state_finish_with_error(reindex):
    s = reindex.ReindexState()
    s.start("buffalo_s", 100)
    s.finish(error="boom")
    snap = s.snapshot()
    assert snap["running"] is False
    assert snap["error"] == "boom"


def test_reindex_state_download_begin(reindex):
    s = reindex.ReindexState()
    s.download_begin("buffalo_s")
    snap = s.snapshot()
    assert snap["download_active"] is True
    assert snap["download_model"] == "buffalo_s"
    assert snap["download_artifact"] is None
    assert snap["download_done"] == 0
    assert snap["download_total"] == 0


def test_reindex_state_download_update(reindex):
    s = reindex.ReindexState()
    s.download_begin("buffalo_s")
    s.download_update(50, 100, "det.onnx")
    snap = s.snapshot()
    assert snap["download_done"] == 50
    assert snap["download_total"] == 100
    assert snap["download_artifact"] == "det.onnx"


def test_reindex_state_download_update_without_artifact_keeps_previous(reindex):
    s = reindex.ReindexState()
    s.download_begin("buffalo_s")
    s.download_update(10, 100, "a.onnx")
    s.download_update(50, 100)
    assert s.snapshot()["download_artifact"] == "a.onnx"


def test_reindex_state_download_end(reindex):
    s = reindex.ReindexState()
    s.download_begin("buffalo_s")
    s.download_update(50, 100, "det.onnx")
    s.download_end()
    snap = s.snapshot()
    assert snap["download_active"] is False
    assert snap["download_artifact"] is None
    assert snap["download_done"] == 0
    assert snap["download_total"] == 0


def test_state_singleton(reindex):
    assert reindex.state is reindex.state


def test_ensure_model_ready_returns_false_for_unknown_model(reindex, monkeypatch):
    def _raise(_):
        raise KeyError("unknown")

    monkeypatch.setattr("app.services.model_manifest.variant_for", _raise)
    assert reindex.ensure_model_ready("nope") is False
    assert "nope" in reindex.state.last_error or "unknown" in (reindex.state.last_error or "")


def test_ensure_model_ready_returns_true_when_files_present(reindex, monkeypatch):
    fake_variant = object()

    def _variant_for(name):
        return fake_variant

    monkeypatch.setattr("app.services.model_manifest.variant_for", _variant_for)
    monkeypatch.setattr(reindex, "variant_files_present", lambda v: True)
    monkeypatch.setattr(reindex, "_link_into_insightface_cache", lambda v: None)
    broadcasts: list = []
    monkeypatch.setattr(reindex.websocket_hub, "publish", lambda payload: broadcasts.append(payload))
    assert reindex.ensure_model_ready("buffalo_s") is True
    assert any(p.get("type") == "reindex.download" for p in broadcasts)


def test_ensure_model_ready_downloads_when_missing(reindex, monkeypatch):
    fake_variant = object()

    def _variant_for(name):
        return fake_variant

    monkeypatch.setattr("app.services.model_manifest.variant_for", _variant_for)

    state = {"present_count": 0}

    def _files_present(_):
        state["present_count"] += 1
        return state["present_count"] >= 2

    monkeypatch.setattr(reindex, "variant_files_present", _files_present)
    monkeypatch.setattr(reindex, "download_variant", lambda *_a, **_kw: None)
    monkeypatch.setattr(reindex, "_link_into_insightface_cache", lambda _v: None)
    assert reindex.ensure_model_ready("buffalo_s") is True
    assert state["present_count"] == 2


def test_ensure_model_ready_returns_false_when_download_fails(reindex, monkeypatch):
    fake_variant = object()
    monkeypatch.setattr("app.services.model_manifest.variant_for", lambda n: fake_variant)
    monkeypatch.setattr(reindex, "variant_files_present", lambda v: False)

    def _explode(*_a, **_kw):
        raise reindex.DownloadError("net down")

    monkeypatch.setattr(reindex, "download_variant", _explode)
    monkeypatch.setattr(reindex.websocket_hub, "publish", lambda _p: None)
    assert reindex.ensure_model_ready("buffalo_s") is False


def test_ensure_model_ready_warmup_ends_download(reindex, monkeypatch):
    fake_variant = object()
    monkeypatch.setattr("app.services.model_manifest.variant_for", lambda n: fake_variant)
    monkeypatch.setattr(reindex, "variant_files_present", lambda v: False)
    monkeypatch.setattr(reindex, "download_variant", lambda *_a, **_kw: None)
    monkeypatch.setattr(reindex, "_link_into_insightface_cache", lambda _v: None)

    def _files_present(_):
        return True

    monkeypatch.setattr(reindex, "variant_files_present", _files_present)
    reindex.ensure_model_ready("buffalo_s", kind="warmup")
    assert reindex.state.download_active is False


def test_start_reindex_returns_false_when_already_running(reindex, monkeypatch):
    reindex.state.running = True
    assert reindex.start_reindex("buffalo_s") is False
    reindex.state.running = False


def test_start_reindex_spawns_thread(reindex, monkeypatch):
    reindex.state.running = False
    threads = []

    class _T:
        def __init__(self, *a, **kw):
            self._args = a
            self._kwargs = kw
            self.daemon = kw.get("daemon", False)
            threads.append(self)

        def start(self):
            pass

    monkeypatch.setattr(reindex.threading, "Thread", _T)
    assert reindex.start_reindex("buffalo_s") is True
    assert len(threads) == 1
    assert threads[0].daemon is True


def test_active_model_returns_default_when_no_row(reindex):
    from app.core.config import settings

    assert reindex.active_model() == settings.default_model


def test_active_model_returns_stored_value(reindex):
    from app.db.session import session_scope
    from app.models.entities import SystemSetting

    with session_scope() as s:
        s.merge(SystemSetting(key="active_model", value="buffalo_l"))
    val = reindex.active_model()
    assert val == "buffalo_l"
