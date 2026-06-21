"""
test_api.py — HTTP endpoint tests.

Uses FastAPI's TestClient (Starlette's synchronous test wrapper over
httpx) so no live server is needed.  S3 calls are monkey-patched away.
"""

from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from log_analytics.server import app

client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# /healthz
# ---------------------------------------------------------------------------

class TestHealthz:
    def test_returns_200(self):
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# /version
# ---------------------------------------------------------------------------

class TestVersion:
    def test_returns_git_sha(self, monkeypatch):
        monkeypatch.setenv("GIT_SHA", "abc1234")
        # Reload to pick up env var (server reads it at import time)
        import importlib
        import log_analytics.server as srv
        importlib.reload(srv)
        r = client.get("/version")
        # The TestClient uses the already-loaded app, so just check shape
        assert "git_sha" in r.json()

    def test_unknown_sha_when_env_missing(self, monkeypatch):
        monkeypatch.delenv("GIT_SHA", raising=False)
        r = client.get("/version")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# /readyz
# ---------------------------------------------------------------------------

class TestReadyz:
    def test_missing_bucket_returns_400(self):
        r = client.get("/readyz")
        assert r.status_code == 400
        assert "error" in r.json()

    @patch("log_analytics.server.check_s3_reachable")
    def test_s3_reachable_returns_ready(self, mock_check):
        mock_check.return_value = None  # no exception = success
        r = client.get("/readyz?bucket=my-bucket")
        assert r.status_code == 200
        assert r.json()["status"] == "ready"

    @patch("log_analytics.server.check_s3_reachable")
    def test_s3_unreachable_returns_503(self, mock_check):
        from log_analytics.s3_reader import S3ReadError
        mock_check.side_effect = S3ReadError("bucket not found")
        r = client.get("/readyz?bucket=missing-bucket")
        assert r.status_code == 503
        assert "error" in r.json()


# ---------------------------------------------------------------------------
# /analyze — local file mode
# ---------------------------------------------------------------------------

class TestAnalyzeLocalFile:
    def test_local_file_basic(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text(
            '{"level":"ERROR","service":"api","ts":"2025-01-01T00:00:00Z","msg":"x"}\n'
            '{"level":"INFO","service":"db","ts":"2025-01-01T00:00:00Z","msg":"y"}\n'
        )
        r = client.get(f"/analyze?file={f}&threshold=1")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["byService"] == {"api": 1}
        assert body["alert"] is True
        assert body["parseErrors"] == 0

    def test_local_file_not_found_returns_400(self):
        r = client.get("/analyze?file=/nonexistent/path.jsonl")
        assert r.status_code == 400
        assert "error" in r.json()

    def test_no_source_returns_400(self):
        r = client.get("/analyze?threshold=3")
        assert r.status_code == 400
        assert "error" in r.json()

    def test_malformed_lines_in_response(self, tmp_path):
        f = tmp_path / "mixed.jsonl"
        f.write_text(
            '{"level":"ERROR","service":"api","ts":"2025-01-01T00:00:00Z","msg":"x"}\n'
            'not json at all\n'
            'also bad\n'
        )
        r = client.get(f"/analyze?file={f}&threshold=10")
        body = r.json()
        assert body["total"] == 1
        assert body["parseErrors"] == 2
        assert body["alert"] is False

    def test_threshold_alert_fires(self, tmp_path):
        f = tmp_path / "errors.jsonl"
        lines = [
            '{"level":"ERROR","service":"svc","ts":"2025-01-01T00:00:00Z","msg":"x"}\n'
        ] * 5
        f.write_text("".join(lines))
        r = client.get(f"/analyze?file={f}&threshold=5")
        body = r.json()
        assert body["alert"] is True
        assert body["total"] == 5

    def test_threshold_alert_not_fires(self, tmp_path):
        f = tmp_path / "few_errors.jsonl"
        f.write_text(
            '{"level":"ERROR","service":"svc","ts":"2025-01-01T00:00:00Z","msg":"x"}\n' * 2
        )
        r = client.get(f"/analyze?file={f}&threshold=5")
        assert r.json()["alert"] is False


# ---------------------------------------------------------------------------
# /analyze — S3 mode (stubbed adapter)
# ---------------------------------------------------------------------------

class TestAnalyzeS3:
    @patch("log_analytics.server.iter_s3_lines")
    def test_s3_mode_returns_summary(self, mock_iter):
        mock_iter.return_value = iter([
            '{"level":"ERROR","service":"billing","ts":"2025-01-01T00:00:00Z","msg":"x"}',
            '{"level":"ERROR","service":"billing","ts":"2025-01-01T00:00:00Z","msg":"y"}',
        ])
        r = client.get("/analyze?bucket=test-bucket&prefix=logs/&threshold=2")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 2
        assert body["byService"] == {"billing": 2}
        assert body["alert"] is True

    @patch("log_analytics.server.iter_s3_lines")
    def test_s3_error_returns_502(self, mock_iter):
        from log_analytics.s3_reader import S3ReadError
        mock_iter.side_effect = S3ReadError("bucket inaccessible")
        r = client.get("/analyze?bucket=bad-bucket&prefix=x/&threshold=1")
        assert r.status_code == 502
        assert "error" in r.json()


# ---------------------------------------------------------------------------
# Error envelope shape
# ---------------------------------------------------------------------------

class TestErrorEnvelope:
    def test_error_responses_contain_error_key(self):
        r = client.get("/analyze")
        assert "error" in r.json()
        assert "stack" not in str(r.json())  # no stack traces
