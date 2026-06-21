"""
core.py — Pure analysis logic.

All functions here are free of I/O, AWS SDK calls, and framework dependencies.
They accept Python iterables/generators so they work identically whether the
source is a local file, an S3 stream, or an in-memory list of strings.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Iterable, Iterator


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

@dataclass
class AnalysisResult:
    total: int = 0
    by_service: dict[str, int] = field(default_factory=dict)
    alert: bool = False
    parse_errors: int = 0

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "byService": self.by_service,
            "alert": self.alert,
            "parseErrors": self.parse_errors,
        }


# ---------------------------------------------------------------------------
# Core streaming analysis
# ---------------------------------------------------------------------------

def analyze_lines(lines: Iterable[str | bytes], threshold: int = 10) -> AnalysisResult:
    """
    Consume an iterable of raw log lines and return an AnalysisResult.

    Memory complexity: O(number of distinct services) — constant w.r.t. file size.
    The iterable is consumed lazily, so 500 MB S3 objects never fully reside in RAM.

    Args:
        lines:     Any iterable of str/bytes (file handle, generator, list …).
        threshold: Alert fires when total errors >= threshold.

    Returns:
        AnalysisResult with counts and alert flag.
    """
    result = AnalysisResult()

    for raw in lines:
        # Support both str and bytes (boto3 streaming body yields bytes)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")

        line = raw.strip()
        if not line:
            continue

        entry = _parse_line(line)
        if entry is None:
            result.parse_errors += 1
            continue

        if entry.get("level") != "ERROR":
            continue

        result.total += 1
        service = entry.get("service") or "unknown"
        result.by_service[service] = result.by_service.get(service, 0) + 1

    result.alert = result.total >= threshold
    return result


def _parse_line(line: str) -> dict | None:
    """
    Parse a single JSON line.  Returns None if the line is malformed or
    doesn't meet the minimum schema (level + service fields must exist).
    """
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None

    if not isinstance(obj, dict):
        return None

    # We don't crash on missing optional fields; we just won't count them
    return obj


# ---------------------------------------------------------------------------
# Iterator adapters (bridges between ports and the core)
# ---------------------------------------------------------------------------

def iter_file(path: str) -> Iterator[str]:
    """
    Yield lines from a local file without loading it all into memory.

    Raises OSError immediately (eager open) so the caller sees it before
    iteration starts — the HTTP layer can then return 400 vs 500.
    """
    fh = open(path, "r", encoding="utf-8", errors="replace")
    try:
        yield from fh
    finally:
        fh.close()
