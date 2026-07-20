from __future__ import annotations

import logging
import threading
from contextlib import contextmanager, suppress
from uuid import UUID

import numpy as np
import psycopg
from psycopg import sql

from app.core.config import settings

log = logging.getLogger("mnemos.vector")

_lock = threading.RLock()
_pool: list[psycopg.Connection] = []
_POOL_SIZE = 4


def _open() -> psycopg.Connection:
    return psycopg.connect(settings.vector_dsn, autocommit=False, connect_timeout=5)


@contextmanager
def get_conn():
    with _lock:
        if _pool:
            conn = _pool.pop()
            try:
                if conn.closed or conn.broken:
                    conn.close()
                    conn = _open()
            except Exception:
                conn = _open()
        else:
            conn = _open()
    try:
        yield conn
    except Exception:
        with suppress(Exception):
            conn.rollback()
        with suppress(Exception):
            conn.close()
        conn = None
        raise
    finally:
        if conn is not None and not conn.closed and len(_pool) < _POOL_SIZE:
            with _lock:
                _pool.append(conn)
        elif conn is not None:
            conn.close()


def ping() -> bool:
    try:
        with get_conn() as c, c.cursor() as cur:
            cur.execute("SELECT 1")
            return cur.fetchone() is not None
    except Exception as e:
        log.warning("pgvector ping failed: %s", e)
        return False


def reset_for_tests() -> None:
    with _lock:
        for c in _pool:
            with suppress(Exception):
                c.close()
        _pool.clear()


_EMBEDDING_DIM = 512


def _vec_literal(v: np.ndarray) -> str:
    arr = np.asarray(v, dtype=np.float32).reshape(-1)
    if arr.shape[0] != _EMBEDDING_DIM:
        raise ValueError(f"embedding must have {_EMBEDDING_DIM} dims, got {arr.shape[0]}")
    return "[" + ",".join(f"{x:.7f}" for x in arr) + "]"


def insert_embedding(
    *,
    embed_id: UUID,
    crop_id: UUID,
    person_id: UUID,
    embedding: np.ndarray,
    model_name: str,
    is_averaged: bool,
) -> None:
    with get_conn() as c, c.cursor() as cur:
        cur.execute(
            sql.SQL(
                "INSERT INTO face_embeddings (id, crop_id, person_id, embedding, model_name, is_averaged) "
                "VALUES (%s, %s, %s, %s::vector, %s, %s)"
            ),
            (str(embed_id), str(crop_id), str(person_id), _vec_literal(embedding), model_name, is_averaged),
        )
        c.commit()


def delete_for_crop(crop_id: UUID) -> None:
    with get_conn() as c, c.cursor() as cur:
        cur.execute("DELETE FROM face_embeddings WHERE crop_id = %s", (str(crop_id),))
        c.commit()


def delete_for_person_model(person_id: UUID, model_name: str) -> None:
    with get_conn() as c, c.cursor() as cur:
        cur.execute(
            "DELETE FROM face_embeddings WHERE person_id = %s AND model_name = %s",
            (str(person_id), model_name),
        )
        c.commit()


def delete_all() -> None:
    with get_conn() as c, c.cursor() as cur:
        cur.execute("DELETE FROM face_embeddings")
        c.commit()


def upsert_averaged(person_id: UUID, embedding: np.ndarray, model_name: str) -> None:
    with get_conn() as c, c.cursor() as cur:
        cur.execute(
            "DELETE FROM face_embeddings WHERE person_id = %s AND model_name = %s AND is_averaged = TRUE",
            (str(person_id), model_name),
        )
        cur.execute(
            sql.SQL(
                "INSERT INTO face_embeddings (id, crop_id, person_id, embedding, model_name, is_averaged) "
                "VALUES (gen_random_uuid(), %s, %s, %s::vector, %s, TRUE)"
            ),
            (str(person_id), str(person_id), _vec_literal(embedding), model_name),
        )
        c.commit()


def search_similar(
    embedding: np.ndarray,
    model_name: str,
    limit: int = 5,
    include_per_crop: bool = True,
) -> list[dict]:
    with get_conn() as c, c.cursor() as cur:
        cur.execute(
            sql.SQL(
                """
                SELECT person_id::text,
                       crop_id::text,
                       is_averaged,
                       1 - (embedding <=> %s::vector) AS similarity
                  FROM face_embeddings
                 WHERE model_name = %s
                 ORDER BY embedding <=> %s::vector
                 LIMIT %s
                """
            ),
            (_vec_literal(embedding), model_name, _vec_literal(embedding), limit),
        )
        rows = cur.fetchall()
    out = []
    for r in rows:
        sim = float(r[3])
        is_avg = bool(r[2])
        if is_avg:
            sim = min(1.0, sim + 1e-6)
        out.append(
            {
                "person_id": r[0],
                "crop_id": r[1],
                "is_averaged": is_avg,
                "similarity": sim,
            }
        )
    out.sort(key=lambda d: d["similarity"], reverse=True)
    return out


def reindex_hnsw() -> None:
    with get_conn() as c, c.cursor() as cur:
        cur.execute("REINDEX INDEX face_embeddings_embedding_hnsw;")
        c.commit()
