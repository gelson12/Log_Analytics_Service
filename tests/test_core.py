"""
test_core.py — Unit tests for the pure analysis logic.

No I/O, no AWS.  Tests cover the interesting edge cases the spec calls out:
empty input, all errors, malformed lines, threshold boundary.
"""

import json
import pytest
from log_analytics.core import analyze_lines, AnalysisResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def lines(*entries: dict | str) -> list[str]:
    """Convert dicts/strings to a list of JSON-line strings."""
    result = []
    for e in entries:
        if isinstance(e, dict):
            result.append(json.dumps(e))
        else:
            result.append(e)  # raw string (for malformed-line tests)
    return result


def error(service: str, **kw) -> dict:
    return {"level": "ERROR", "service": service, "ts": "2025-01-01T00:00:00Z", "msg": "x", **kw}


def info(service: str) -> dict:
    return {"level": "INFO", "service": service, "ts": "2025-01-01T00:00:00Z", "msg": "x"}


# ---------------------------------------------------------------------------
# Basic counting
# ---------------------------------------------------------------------------

class TestBasicCounting:
    def test_empty_input_returns_zeros(self):
        r = analyze_lines([])
        assert r.total == 0
        assert r.by_service == {}
        assert r.parse_errors == 0
        assert r.alert is False

    def test_all_info_lines_no_errors(self):
        r = analyze_lines(lines(info("api"), info("api"), info("db")))
        assert r.total == 0
        assert r.by_service == {}

    def test_single_error(self):
        r = analyze_lines(lines(error("api")))
        assert r.total == 1
        assert r.by_service == {"api": 1}

    def test_multiple_services(self):
        r = analyze_lines(lines(
            error("api"),
            error("orders"),
            error("billing"),
            error("api"),
        ))
        assert r.total == 4
        assert r.by_service == {"api": 2, "orders": 1, "billing": 1}

    def test_mix_of_levels(self):
        r = analyze_lines(lines(
            error("api"),
            info("api"),
            error("db"),
            {"level": "WARN", "service": "cache", "ts": "2025-01-01T00:00:00Z", "msg": "x"},
        ))
        assert r.total == 2
        assert r.by_service == {"api": 1, "db": 1}

    def test_all_errors(self):
        r = analyze_lines(lines(*[error("svc") for _ in range(100)]))
        assert r.total == 100
        assert r.by_service == {"svc": 100}


# ---------------------------------------------------------------------------
# Malformed / edge-case lines
# ---------------------------------------------------------------------------

class TestMalformedLines:
    def test_single_malformed_not_counted_as_error(self):
        r = analyze_lines(["not json at all"])
        assert r.total == 0
        assert r.parse_errors == 1

    def test_malformed_lines_counted_separately(self):
        r = analyze_lines(lines(error("api")) + ["{bad json", "also bad"])
        assert r.total == 1
        assert r.parse_errors == 2

    def test_non_dict_json_is_malformed(self):
        r = analyze_lines(["[1, 2, 3]", '"just a string"'])
        assert r.parse_errors == 2
        assert r.total == 0

    def test_empty_lines_skipped(self):
        r = analyze_lines(["", "  ", "\n", json.dumps(error("api"))])
        assert r.total == 1
        assert r.parse_errors == 0

    def test_missing_service_field_grouped_as_unknown(self):
        r = analyze_lines([json.dumps({"level": "ERROR", "msg": "oops"})])
        assert r.total == 1
        assert r.by_service == {"unknown": 1}

    def test_bytes_input_decoded_correctly(self):
        raw = json.dumps(error("api")).encode("utf-8")
        r = analyze_lines([raw])
        assert r.total == 1

    def test_mix_of_valid_and_malformed(self):
        r = analyze_lines([
            json.dumps(error("api")),
            "garbage line",
            json.dumps(info("db")),
            "{}",                      # valid JSON, missing level — not ERROR
            json.dumps(error("auth")),
        ])
        assert r.total == 2
        assert r.parse_errors == 1
        assert r.by_service == {"api": 1, "auth": 1}


# ---------------------------------------------------------------------------
# Threshold / alert boundary
# ---------------------------------------------------------------------------

class TestThreshold:
    def test_alert_false_when_below_threshold(self):
        r = analyze_lines(lines(*[error("svc") for _ in range(4)]), threshold=5)
        assert r.alert is False
        assert r.total == 4

    def test_alert_true_at_exact_threshold(self):
        r = analyze_lines(lines(*[error("svc") for _ in range(5)]), threshold=5)
        assert r.alert is True

    def test_alert_true_above_threshold(self):
        r = analyze_lines(lines(*[error("svc") for _ in range(10)]), threshold=3)
        assert r.alert is True

    def test_threshold_zero_always_alerts(self):
        r = analyze_lines([], threshold=0)
        assert r.alert is True  # 0 >= 0

    def test_threshold_one(self):
        r = analyze_lines(lines(error("api")), threshold=1)
        assert r.alert is True

    def test_threshold_one_no_errors(self):
        r = analyze_lines(lines(info("api")), threshold=1)
        assert r.alert is False


# ---------------------------------------------------------------------------
# Result serialisation
# ---------------------------------------------------------------------------

class TestResultDict:
    def test_to_dict_shape(self):
        r = AnalysisResult(total=3, by_service={"api": 2, "db": 1}, alert=True, parse_errors=1)
        d = r.to_dict()
        assert d == {
            "total": 3,
            "byService": {"api": 2, "db": 1},
            "alert": True,
            "parseErrors": 1,
        }

    def test_sample_from_spec(self):
        """Reproduce the exact sample in the assignment brief."""
        sample = [
            '{"ts":"2025-09-15T14:10:04Z","service":"api","level":"ERROR","msg":"500 internal server error"}',
            '{"ts":"2025-09-15T14:10:07Z","service":"orders","level":"ERROR","msg":"db timeout"}',
            '{"ts":"2025-09-15T14:10:09Z","service":"billing","level":"ERROR","msg":"foreign key constraint"}',
            '{"ts":"2025-09-15T14:10:11Z","service":"auth","level":"ERROR","msg":"token expired"}',
        ]
        r = analyze_lines(sample, threshold=3)
        assert r.total == 4
        assert r.by_service == {"api": 1, "orders": 1, "billing": 1, "auth": 1}
        assert r.alert is True
        assert r.parse_errors == 0
