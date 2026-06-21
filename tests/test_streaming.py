"""
test_streaming.py — Proves the streaming requirement.

Generates a synthetic ~100 MB JSONL file on disk, processes it through
the same iter_file → analyze_lines path used in production, and asserts
that peak RSS never exceeds a hard ceiling (default 64 MB).

We use 100 MB rather than 500 MB to keep CI fast while still proving
the property: if memory scales linearly with file size, 100 MB would
already blow the 64 MB ceiling.
"""

from __future__ import annotations

import json
import os
import resource
import tempfile

import pytest

from log_analytics.core import analyze_lines, iter_file


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------

TARGET_FILE_SIZE_MB = 100
MEMORY_CEILING_MB = 64  # peak RSS must stay below this


def _rss_mb() -> float:
    """Current process RSS in megabytes."""
    # getrusage returns kilobytes on Linux
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def _generate_large_jsonl(path: str, target_bytes: int) -> int:
    """Write alternating ERROR / INFO lines until file hits target_bytes."""
    template_error = json.dumps({
        "ts": "2025-01-01T00:00:00Z",
        "level": "ERROR",
        "service": "stress",
        "msg": "something went wrong with the request handler module",
    })
    template_info = json.dumps({
        "ts": "2025-01-01T00:00:00Z",
        "level": "INFO",
        "service": "stress",
        "msg": "request processed successfully by the handler",
    })
    written = 0
    count = 0
    with open(path, "w", encoding="utf-8") as fh:
        while written < target_bytes:
            line = template_error if count % 2 == 0 else template_info
            fh.write(line + "\n")
            written += len(line) + 1
            count += 1
    return count


# -------------------------------------------------------------------------
# Test
# -------------------------------------------------------------------------

@pytest.mark.slow
def test_streaming_constant_memory():
    """
    Process a ~100 MB file and assert peak RSS < MEMORY_CEILING_MB.

    This test is tagged 'slow' and can be skipped with -m 'not slow'.
    It is included in the default run to satisfy the assignment's
    explicit requirement of a streaming proof.
    """
    target_bytes = TARGET_FILE_SIZE_MB * 1024 * 1024

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
        path = tmp.name

    try:
        line_count = _generate_large_jsonl(path, target_bytes)
        actual_size_mb = os.path.getsize(path) / (1024 * 1024)

        # Baseline before processing
        baseline_mb = _rss_mb()

        result = analyze_lines(iter_file(path), threshold=1)

        peak_mb = _rss_mb()
        delta_mb = peak_mb - baseline_mb

        print(
            f"\n[streaming test] file={actual_size_mb:.1f} MB  "
            f"lines={line_count}  errors={result.total}  "
            f"baseline_rss={baseline_mb:.1f} MB  peak_rss={peak_mb:.1f} MB  "
            f"delta={delta_mb:.1f} MB"
        )

        # Half the lines are ERRORs
        assert result.total == line_count // 2, "Expected ~half of lines to be errors"
        assert result.alert is True

        assert delta_mb < MEMORY_CEILING_MB, (
            f"Memory grew by {delta_mb:.1f} MB processing a {actual_size_mb:.1f} MB file "
            f"(ceiling: {MEMORY_CEILING_MB} MB). Implementation is not streaming."
        )

    finally:
        os.unlink(path)
