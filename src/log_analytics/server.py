"""
server.py — HTTP port (FastAPI).

Exposes the core analysis logic over HTTP.  This module is responsible
only for HTTP concerns: routing, request/response shaping, error
envelopes, and logging middleware.  It delegates all analysis to core.py
and I/O to s3_reader.py.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

import boto3
from fastapi import FastAPI, Query, Request, Response
from fastapi.responses import JSONResponse

from log_analytics.core import analyze_lines, iter_file
from log_analytics.s3_reader import S3ReadError, check_s3_reachable, iter_s3_lines
from log_analytics.logging_config import configure_logging

# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

GIT_SHA = os.getenv("GIT_SHA", "unknown")
DEFAULT_BUCKET = os.getenv("LOG_BUCKET", "")

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("log-analytics starting", extra={"git_sha": GIT_SHA})
    yield
    logger.info("log-analytics shutting down")


app = FastAPI(title="Log Analytics Service", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Middleware: structured JSON logging with request ID
# ---------------------------------------------------------------------------

@app.middleware("http")
async def request_logging(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    start = time.perf_counter()

    response: Response = await call_next(request)

    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    logger.info(
        "http request",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    response.headers["X-Request-Id"] = request_id
    return response


# ---------------------------------------------------------------------------
# Error helpers
# ---------------------------------------------------------------------------

def _error(status: int, message: str, request_id: str = "") -> JSONResponse:
    """Consistent error envelope — never leaks stack traces."""
    return JSONResponse(
        status_code=status,
        content={"error": message, "request_id": request_id},
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/healthz")
async def healthz():
    """Liveness — no external dependencies."""
    return {"status": "ok"}


@app.get("/readyz")
async def readyz(request: Request, bucket: str = Query(default=DEFAULT_BUCKET)):
    """Readiness — verifies S3 is reachable."""
    rid = getattr(request.state, "request_id", "")
    if not bucket:
        return _error(400, "bucket parameter required (or set LOG_BUCKET env var)", rid)
    try:
        check_s3_reachable(bucket)
        return {"status": "ready", "s3": "reachable", "bucket": bucket}
    except S3ReadError as exc:
        logger.warning("readyz s3 check failed: %s", exc, extra={"request_id": rid})
        return _error(503, str(exc), rid)


@app.get("/version")
async def version():
    """Returns the git SHA the image was built from."""
    return {"git_sha": GIT_SHA}


@app.get("/analyze")
async def analyze(
    request: Request,
    bucket: str = Query(default=""),
    prefix: str = Query(default=""),
    threshold: int = Query(default=10, ge=1),
    file: str = Query(default=""),
):
    """
    Analyze log files and return an error summary.

    Either (bucket + prefix) or file must be provided.
    Streams data — safe to call against 500 MB objects.
    """
    rid = getattr(request.state, "request_id", "")

    # --- Input selection ---
    if file:
        try:
            lines = iter_file(file)
        except OSError as exc:
            return _error(400, f"Cannot open file: {exc}", rid)
    elif bucket:
        try:
            lines = iter_s3_lines(bucket, prefix)
        except S3ReadError as exc:
            return _error(502, str(exc), rid)
    else:
        return _error(400, "Provide either 'bucket' or 'file' query parameter.", rid)

    # --- Analysis ---
    try:
        result = analyze_lines(lines, threshold=threshold)
    except OSError as exc:
        # Generator opened the file lazily; catch FileNotFoundError etc. here
        return _error(400, f"Cannot read file: {exc}", rid)
    except Exception as exc:
        logger.exception("unexpected analysis error", extra={"request_id": rid})
        return _error(500, "Internal analysis error.", rid)

    logger.info(
        "analysis complete",
        extra={
            "request_id": rid,
            "total_errors": result.total,
            "parse_errors": result.parse_errors,
            "alert": result.alert,
        },
    )
    return result.to_dict()
