# ─────────────────────────────────────────────────────────────────────────────
# Stage 1: builder — install Python deps into a clean venv
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

COPY pyproject.toml ./
COPY src/ ./src/

RUN pip install --upgrade pip --quiet \
 && pip install build --quiet \
 && pip install --no-cache-dir ".[dev]" --target /build/deps --quiet

# ─────────────────────────────────────────────────────────────────────────────
# Stage 2: runtime — minimal image, no build tools
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src

WORKDIR /app

# Non-root user
RUN addgroup --system app && adduser --system --ingroup app app

# Copy installed packages and source
COPY --from=builder /build/deps /usr/local/lib/python3.12/site-packages/
COPY --from=builder /build/src ./src

# Drop to non-root
USER app

EXPOSE 8000

# Health check so ECS marks the task unhealthy if the process dies
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"

CMD ["python", "-m", "uvicorn", "log_analytics.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--no-access-log"]