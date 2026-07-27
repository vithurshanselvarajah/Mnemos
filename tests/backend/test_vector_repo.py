from __future__ import annotations

import uuid
from collections import deque

import numpy as np
import pytest


class _FakeCursor:
    def __init__(self, store: FakeConn) -> None:
        self.store = store
        self.last_sql: str = ""
        self.last_params: tuple = ()

    def execute(self, sql, params=None):
        self.last_sql = " ".join(str(sql).split())
        self.last_params = params if params is not None else ()
        self.store.executed.append((self.last_sql, self.last_params))
        return self

    def fetchone(self):
        return (1,) if "SELECT 1" in self.last_sql else None

    def fetchall(self):
        return []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConn:
    def __init__(self) -> None:
        self.closed: bool = False
        self.broken: bool = False
        self.executed: list = []
        self.committed: int = 0
        self.rolled_back: int = 0

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        self.rolled_back += 1

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_psycopg(monkeypatch, backend_imports):
    """Replace psycopg.connect with a factory that returns FakeConn
    instances and tracks them in `connections`. Each new connect
    also returns the next conn from `scripted` if queued, otherwise
    creates a fresh FakeConn."""
    from app.services import vector_repo

    state = {
        "connections": [],
        "scripted": deque(),
    }

    def _connect(_dsn, **_kw):
        if state["scripted"]:
            c = state["scripted"].popleft()
        else:
            c = FakeConn()
        state["connections"].append(c)
        return c

    monkeypatch.setattr(vector_repo.psycopg, "connect", _connect)
    monkeypatch.setattr("psycopg.connect", _connect)
    vector_repo.reset_for_tests()
    yield state
    vector_repo.reset_for_tests()


def test_vec_literal_formats_512_dims(backend_imports):
    from app.services.vector_repo import _vec_literal

    arr = np.zeros(512, dtype=np.float32)
    s = _vec_literal(arr)
    assert s.startswith("[") and s.endswith("]")
    assert s.count(",") == 511


def test_vec_literal_rejects_wrong_dim(backend_imports):
    from app.services.vector_repo import _vec_literal

    with pytest.raises(ValueError):
        _vec_literal(np.zeros(511, dtype=np.float32))


def test_get_conn_opens_and_pools_connections(fake_psycopg):
    from app.services import vector_repo

    vector_repo.reset_for_tests()
    with vector_repo.get_conn() as c:
        assert isinstance(c, FakeConn)
    with vector_repo.get_conn() as c2:
        assert isinstance(c2, FakeConn)
    assert len(fake_psycopg["connections"]) >= 1


def test_get_conn_recycles_pooled_connections(fake_psycopg):
    from app.services import vector_repo

    vector_repo.reset_for_tests()
    with vector_repo.get_conn() as c:
        c.committed = 0
    with vector_repo.get_conn():
        pass
    assert len(fake_psycopg["connections"]) == 1


def test_get_conn_reopens_closed_connections(fake_psycopg):
    from app.services import vector_repo

    vector_repo.reset_for_tests()
    with vector_repo.get_conn() as c:
        c.closed = True
        c.broken = False
    with vector_repo.get_conn() as c2:
        assert c2 is not c
    assert len(fake_psycopg["connections"]) == 2


def test_get_conn_reopens_broken_connections(fake_psycopg):
    from app.services import vector_repo

    vector_repo.reset_for_tests()
    with vector_repo.get_conn() as c:
        c.broken = True
    with vector_repo.get_conn() as c2:
        assert c2 is not c


def test_get_conn_rolls_back_on_exception(fake_psycopg):
    from app.services import vector_repo

    vector_repo.reset_for_tests()
    try:
        with vector_repo.get_conn() as c:
            assert c.rolled_back == 0
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert len(fake_psycopg["connections"]) >= 1


def test_get_conn_closes_on_exception_when_pool_full(fake_psycopg):
    from app.services import vector_repo

    vector_repo.reset_for_tests()
    original_size = vector_repo._POOL_SIZE
    vector_repo._POOL_SIZE = 0
    try:
        with pytest.raises(RuntimeError):
            with vector_repo.get_conn():
                raise RuntimeError("boom")
    finally:
        vector_repo._POOL_SIZE = original_size


def test_ping_success(fake_psycopg):
    from app.services import vector_repo

    assert vector_repo.ping() is True
    assert len(fake_psycopg["connections"]) >= 1


def test_ping_failure_on_open_error(monkeypatch, backend_imports):
    from app.services import vector_repo

    def _explode(*_a, **_kw):
        raise RuntimeError("no db")

    monkeypatch.setattr(vector_repo.psycopg, "connect", _explode)
    vector_repo.reset_for_tests()
    assert vector_repo.ping() is False


def test_insert_embedding_executes_insert(fake_psycopg):
    from app.services import vector_repo

    eid = uuid.uuid4()
    crop_id = uuid.uuid4()
    pid = uuid.uuid4()
    emb = np.ones(512, dtype=np.float32) * 0.5
    vector_repo.insert_embedding(
        embed_id=eid,
        crop_id=crop_id,
        person_id=pid,
        embedding=emb,
        model_name="buffalo_s",
        is_averaged=False,
    )
    assert fake_psycopg["connections"], "should have opened at least one connection"
    last = fake_psycopg["connections"][-1]
    assert any("INSERT INTO face_embeddings" in s for s, _p in last.executed)


def test_insert_embedding_rejects_wrong_dim(fake_psycopg):
    from app.services import vector_repo

    with pytest.raises(ValueError):
        vector_repo.insert_embedding(
            embed_id=uuid.uuid4(),
            crop_id=uuid.uuid4(),
            person_id=uuid.uuid4(),
            embedding=np.zeros(100, dtype=np.float32),
            model_name="buffalo_s",
            is_averaged=False,
        )


def test_delete_for_crop_executes_delete(fake_psycopg):
    from app.services import vector_repo

    crop_id = uuid.uuid4()
    vector_repo.delete_for_crop(crop_id)
    last = fake_psycopg["connections"][-1]
    assert any("DELETE FROM face_embeddings" in s for s, _p in last.executed)
    assert any(str(crop_id) in str(p) for _s, p in last.executed)


def test_delete_for_person_model_executes_delete(fake_psycopg):
    from app.services import vector_repo

    pid = uuid.uuid4()
    vector_repo.delete_for_person_model(pid, "buffalo_s")
    last = fake_psycopg["connections"][-1]
    assert any("DELETE FROM face_embeddings" in s for s, _p in last.executed)
    assert any("model_name" in s for s, _p in last.executed)


def test_delete_all_clears_table(fake_psycopg):
    from app.services import vector_repo

    vector_repo.delete_all()
    last = fake_psycopg["connections"][-1]
    assert any("DELETE FROM face_embeddings" in s for s, _p in last.executed)


def test_upsert_averaged_deletes_and_inserts(fake_psycopg):
    from app.services import vector_repo

    pid = uuid.uuid4()
    emb = np.ones(512, dtype=np.float32) * 0.1
    vector_repo.upsert_averaged(pid, emb, "buffalo_s")
    last = fake_psycopg["connections"][-1]
    sqls = [s for s, _p in last.executed]
    assert any("DELETE FROM face_embeddings" in s for s in sqls)
    assert any("INSERT INTO face_embeddings" in s for s in sqls)
    assert any("is_averaged" in s for s in sqls)


def test_search_similar_executes_query(fake_psycopg):
    from app.services import vector_repo

    emb = np.ones(512, dtype=np.float32)
    out = vector_repo.search_similar(emb, "buffalo_s", limit=3)
    last = fake_psycopg["connections"][-1]
    assert any("ORDER BY embedding" in s for s, _p in last.executed)
    assert isinstance(out, list)


def test_search_similar_returns_rows_from_fake_cursor(fake_psycopg):
    """When the fake cursor's fetchall returns rows, search_similar
    should shape them into dicts with the expected keys."""
    from app.services import vector_repo

    pid = str(uuid.uuid4())
    cid = str(uuid.uuid4())

    class _RowCursor(_FakeCursor):
        def fetchall(self):
            return [(pid, cid, True, 0.92)]

    class _ConnWithRows(FakeConn):
        def cursor(self):
            return _RowCursor(self)

    fake_psycopg["scripted"].append(_ConnWithRows())
    emb = np.ones(512, dtype=np.float32)
    out = vector_repo.search_similar(emb, "buffalo_s", limit=5)
    assert len(out) == 1
    assert out[0]["person_id"] == pid
    assert out[0]["crop_id"] == cid
    assert out[0]["is_averaged"] is True
    assert out[0]["similarity"] >= 0.92


def test_search_similar_is_avg_boost(fake_psycopg):
    """is_averaged rows should have their similarity clamped at 1.0
    (boosted by 1e-6 then min(1.0))."""
    from app.services import vector_repo

    pid = str(uuid.uuid4())
    cid = str(uuid.uuid4())

    class _RowCursor(_FakeCursor):
        def fetchall(self):
            return [(pid, cid, True, 1.0)]

    class _ConnWithRows(FakeConn):
        def cursor(self):
            return _RowCursor(self)

    fake_psycopg["scripted"].append(_ConnWithRows())
    emb = np.ones(512, dtype=np.float32)
    out = vector_repo.search_similar(emb, "buffalo_s", limit=5)
    assert out[0]["similarity"] == 1.0


def test_reindex_hnsw_runs_reindex(fake_psycopg):
    from app.services import vector_repo

    vector_repo.reindex_hnsw()
    last = fake_psycopg["connections"][-1]
    assert any("REINDEX INDEX face_embeddings_embedding_hnsw" in s for s, _p in last.executed)


def test_reset_for_tests_closes_pool(monkeypatch, backend_imports):
    from app.services import vector_repo

    c = FakeConn()
    vector_repo._pool.append(c)
    vector_repo.reset_for_tests()
    assert vector_repo._pool == []


def test_ensure_schema_executes_ddl(fake_psycopg):
    from app.services import vector_repo

    vector_repo.ensure_schema()
    last = fake_psycopg["connections"][-1]
    sqls = [s for s, _p in last.executed]
    assert any("CREATE EXTENSION" in s for s in sqls)
    assert any("CREATE TABLE" in s for s in sqls)
    assert any("hnsw" in s for s in sqls)
