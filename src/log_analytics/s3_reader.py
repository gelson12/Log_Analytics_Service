"""
s3_reader.py — S3 input port.

Streams S3 objects line-by-line using chunked reads so that no object
(even 500 MB ones) is ever fully buffered in memory.

Depends on boto3 but nothing else from this project, keeping the
hexagonal boundary clean: swap this module for any other adapter and
the core logic never changes.
"""

from __future__ import annotations

import logging
from typing import Iterator

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

# Read S3 in 1 MB chunks to keep memory flat regardless of object size.
_CHUNK_SIZE = 1024 * 1024  # 1 MB


class S3ReadError(Exception):
    """Raised when an S3 operation fails in a way the caller should handle."""


def iter_s3_lines(bucket: str, prefix: str, s3_client=None) -> Iterator[str]:
    """
    Yield every line from every object under bucket/prefix, one at a time.

    Memory footprint: one 1 MB chunk + one partial line at a time.
    Skips objects that cannot be read, logging a warning.

    Args:
        bucket:    S3 bucket name.
        prefix:    Key prefix (e.g. "logs/2025/").
        s3_client: Optional pre-built boto3 S3 client (for testing / DI).

    Yields:
        str lines (without newline).

    Raises:
        S3ReadError: if the bucket itself is unreachable (caught by /readyz).
    """
    client = s3_client or boto3.client("s3")

    keys = list(_list_keys(client, bucket, prefix))
    logger.info("s3_reader found %d objects under s3://%s/%s", len(keys), bucket, prefix)

    for key in keys:
        logger.debug("streaming s3://%s/%s", bucket, key)
        try:
            yield from _stream_object(client, bucket, key)
        except (BotoCoreError, ClientError) as exc:
            logger.warning("skipping s3://%s/%s — %s", bucket, key, exc)


def _list_keys(client, bucket: str, prefix: str) -> Iterator[str]:
    """Paginate over ListObjectsV2 and yield every key."""
    paginator = client.get_paginator("list_objects_v2")
    try:
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                yield obj["Key"]
    except (BotoCoreError, ClientError) as exc:
        raise S3ReadError(f"Cannot list s3://{bucket}/{prefix}: {exc}") from exc


def _stream_object(client, bucket: str, key: str) -> Iterator[str]:
    """
    Stream a single S3 object and yield lines.

    Uses chunked reads + a leftover buffer so that even a line that
    spans two chunks is emitted correctly.
    """
    response = client.get_object(Bucket=bucket, Key=key)
    body = response["Body"]

    leftover = b""
    while True:
        chunk = body.read(_CHUNK_SIZE)
        if not chunk:
            break
        chunk = leftover + chunk
        lines = chunk.split(b"\n")
        # The last element may be an incomplete line — save it for next iteration
        leftover = lines.pop()
        for line in lines:
            decoded = line.decode("utf-8", errors="replace").rstrip("\r")
            if decoded:
                yield decoded

    # Flush whatever remains after the last chunk
    if leftover:
        decoded = leftover.decode("utf-8", errors="replace").rstrip("\r")
        if decoded:
            yield decoded


def check_s3_reachable(bucket: str, s3_client=None) -> None:
    """
    Probe S3 access.  Used by /readyz.

    Raises:
        S3ReadError: if S3 is unreachable or bucket not accessible.
    """
    client = s3_client or boto3.client("s3")
    try:
        client.head_bucket(Bucket=bucket)
    except (BotoCoreError, ClientError) as exc:
        raise S3ReadError(f"S3 bucket '{bucket}' not reachable: {exc}") from exc
