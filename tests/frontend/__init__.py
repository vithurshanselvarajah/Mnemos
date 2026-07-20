"""Tests for the mnemos-frontend service.

These tests cover the auth flow, login redirects, the proxy layer
to the backend, and the partial-rendering endpoints. The frontend
hits the backend via an HTTP client; we stub the backend calls
with a `monkeypatch`-friendly fake so we don't need pgvector or
InsightFace for these tests.
"""
