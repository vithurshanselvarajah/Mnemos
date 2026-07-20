"""Tests for the frontend's auth helpers (Argon2id password hashing)."""

from __future__ import annotations


def test_hash_and_verify_round_trip(frontend_imports):
    from app.core.auth import hash_password, verify_password

    h = hash_password("hunter2-correct-horse")
    assert h != "hunter2-correct-horse"
    assert verify_password(h, "hunter2-correct-horse") is True


def test_verify_rejects_wrong_password(frontend_imports):
    from app.core.auth import hash_password, verify_password

    h = hash_password("real-password-12345")
    assert verify_password(h, "guess-12345") is False


def test_verify_rejects_corrupt_hash(frontend_imports):
    from app.core.auth import verify_password

    assert verify_password("not-a-real-argon2-hash", "anything") is False
