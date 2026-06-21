"""
cli.py — Command-line port.

Uses the same core.py / s3_reader.py as the HTTP server.
Local-file mode lets you test without AWS credentials.

Exit codes:
  0 — success, no alert
  1 — unexpected error
  2 — success, alert fired (total >= threshold)
"""

from __future__ import annotations

import argparse
import json
import sys

from log_analytics.core import analyze_lines, iter_file
from log_analytics.logging_config import configure_logging
from log_analytics.s3_reader import S3ReadError, iter_s3_lines


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="analyze",
        description="Analyze JSON Lines log files and report error summaries.",
    )
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--bucket", metavar="BUCKET", help="S3 bucket name")
    source.add_argument("--file", metavar="PATH", help="Local JSONL file path")

    p.add_argument("--prefix", default="", metavar="PREFIX", help="S3 key prefix (used with --bucket)")
    p.add_argument("--threshold", type=int, default=10, metavar="N", help="Alert threshold (default: 10)")
    p.add_argument("--since", metavar="ISO8601", help="[stretch] Filter logs after this timestamp")
    p.add_argument("--log-level", default="WARNING", help="Logging verbosity (default: WARNING)")
    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    configure_logging(args.log_level)

    # --- Source selection ---
    if args.file:
        try:
            lines = iter_file(args.file)
        except OSError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            sys.exit(1)
    else:
        try:
            lines = iter_s3_lines(args.bucket, args.prefix)
        except S3ReadError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            sys.exit(1)

    # --- Analysis ---
    try:
        result = analyze_lines(lines, threshold=args.threshold)
    except Exception as exc:
        print(json.dumps({"error": f"Analysis failed: {exc}"}), file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result.to_dict(), indent=2))

    sys.exit(2 if result.alert else 0)


if __name__ == "__main__":
    main()
