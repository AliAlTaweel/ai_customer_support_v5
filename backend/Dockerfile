# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder
WORKDIR /app
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
# Runtime deps only -- the test and lint toolchain lives in requirements-dev.txt.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"
RUN useradd --create-home --uid 1000 app
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY . .
# utils/logging_setup.py calls LOGS_DIR.mkdir() and attaches RotatingFileHandlers
# at import time, so /app/logs must exist and be writable by the non-root user
# or every entrypoint dies before serving a request.
RUN mkdir -p /app/logs && chown -R app:app /app
USER app
EXPOSE 8000
# PORT with a fallback: Cloud Run injects PORT, and reading it now means the
# deployment round needs no application change. The poller runs from this same
# image by overriding the command: python -m scripts.poll_gmail
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
