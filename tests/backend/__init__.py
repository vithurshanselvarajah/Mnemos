"""Tests for mnemos-backend.

These tests focus on the API surface, security helpers, and
business logic that don't require a live InsightFace model or
pgvector. Tests that need the heavy model are marked `slow`
and skipped by default.
"""
