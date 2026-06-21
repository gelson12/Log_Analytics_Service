"""
main.py — Uvicorn entrypoint.

  uvicorn log_analytics.main:app
"""

from log_analytics.server import app  # noqa: F401 – re-exported for uvicorn
