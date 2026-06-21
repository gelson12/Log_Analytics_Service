"""
test_s3_reader.py — Tests for the S3 input adapter.

boto3 is fully mocked so no AWS credentials needed.
Covers chunked streaming, multi-object prefix, and error handling.
"""

from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch

import pytest

from log_analytics.s3_reader import S3ReadError, _stream_object, check_s3_reachable, iter_s3_lines


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_body(content: str | bytes) -> MagicMock:
    """Return a mock boto3 streaming body that reads from a buffer."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    buf = io.BytesIO(content)
    body = MagicMock()
    body.read = buf.read
    return body


def _make_s3_client(objects: dict[str, str]) -> MagicMock:
    """
    Build a mock S3 client that:
      - list_objects_v2 → yields keys from objects dict
      - get_object → returns body for each key
    """
    client = MagicMock()

    # Paginator for list_objects_v2
    paginator = MagicMock()
    paginator.paginate.return_value = iter([{
        "Contents": [{"Key": k} for k in objects.keys()]
    }])
    client.get_paginator.return_value = paginator

    # get_object per key
    def get_object(Bucket, Key):
        return {"Body": _make_body(objects[Key])}

    client.get_object.side_effect = get_object
    return client


# ---------------------------------------------------------------------------
# _stream_object (unit)
# ---------------------------------------------------------------------------

class TestStreamObject:
    def test_simple_lines(self):
        content = "line1\nline2\nline3\n"
        client = MagicMock()
        client.get_object.return_value = {"Body": _make_body(content)}
        result = list(_stream_object(client, "bucket", "key"))
        assert result == ["line1", "line2", "line3"]

    def test_no_trailing_newline(self):
        content = "line1\nline2"
        client = MagicMock()
        client.get_object.return_value = {"Body": _make_body(content)}
        result = list(_stream_object(client, "bucket", "key"))
        assert result == ["line1", "line2"]

    def test_empty_object(self):
        client = MagicMock()
        client.get_object.return_value = {"Body": _make_body(b"")}
        result = list(_stream_object(client, "bucket", "key"))
        assert result == []

    def test_windows_line_endings(self):
        content = "line1\r\nline2\r\n"
        client = MagicMock()
        client.get_object.return_value = {"Body": _make_body(content)}
        result = list(_stream_object(client, "bucket", "key"))
        assert result == ["line1", "line2"]


# ---------------------------------------------------------------------------
# iter_s3_lines (integration with mocked client)
# ---------------------------------------------------------------------------

class TestIterS3Lines:
    def test_single_object(self):
        line = json.dumps({"level": "ERROR", "service": "api", "msg": "x"})
        client = _make_s3_client({"logs/file.jsonl": line + "\n"})
        result = list(iter_s3_lines("bucket", "logs/", s3_client=client))
        assert result == [line]

    def test_multiple_objects_concatenated(self):
        l1 = json.dumps({"level": "ERROR", "service": "a", "msg": "x"})
        l2 = json.dumps({"level": "INFO", "service": "b", "msg": "y"})
        client = _make_s3_client({
            "logs/a.jsonl": l1 + "\n",
            "logs/b.jsonl": l2 + "\n",
        })
        result = list(iter_s3_lines("bucket", "logs/", s3_client=client))
        assert set(result) == {l1, l2}

    def test_empty_prefix_returns_empty(self):
        client = _make_s3_client({})
        result = list(iter_s3_lines("bucket", "empty/", s3_client=client))
        assert result == []


# ---------------------------------------------------------------------------
# check_s3_reachable
# ---------------------------------------------------------------------------

class TestCheckS3Reachable:
    def test_reachable_bucket_no_exception(self):
        client = MagicMock()
        client.head_bucket.return_value = {}
        check_s3_reachable("my-bucket", s3_client=client)

    def test_unreachable_bucket_raises(self):
        from botocore.exceptions import ClientError
        client = MagicMock()
        client.head_bucket.side_effect = ClientError(
            {"Error": {"Code": "NoSuchBucket", "Message": ""}}, "HeadBucket"
        )
        with pytest.raises(S3ReadError):
            check_s3_reachable("missing-bucket", s3_client=client)
