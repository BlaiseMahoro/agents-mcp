# Image the execute agent runs plan steps in. Rebuild with: make sandbox
FROM python:3.12-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends git curl ca-certificates nodejs npm coreutils jq procps \
 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv
WORKDIR /workspace
