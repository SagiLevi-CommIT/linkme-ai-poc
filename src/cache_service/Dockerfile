# syntax=docker/dockerfile:1.7
# Build on Graviton — push ARM64 image to ECR, matches EKS m7g node group.
FROM --platform=linux/arm64 public.ecr.aws/docker/library/python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Only copy requirements first to maximise layer caching
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

# ----------------------------------------------------------------
# Runtime image — slim, non-root, tini for PID 1 signal forwarding
# ----------------------------------------------------------------
FROM --platform=linux/arm64 public.ecr.aws/docker/library/python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

RUN apt-get update \
 && apt-get install -y --no-install-recommends tini ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd -g 10001 app \
 && useradd -r -u 10001 -g app -d /home/app -s /sbin/nologin app \
 && mkdir -p /home/app /app/.logs \
 && chown -R app:app /home/app /app

COPY --from=builder /install /usr/local

WORKDIR /app
COPY src/common /app/src/common
COPY src/cache_processor /app/src/cache_processor
COPY src/cache_service /app/src/cache_service

RUN chown -R app:app /app

USER app

ENV LOG_LEVEL=INFO \
    WORKER_COUNT=20 \
    POLL_MAX_MESSAGES=10 \
    POLL_WAIT_SECONDS=20

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "cache_service.main"]
