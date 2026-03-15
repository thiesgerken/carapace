FROM python:3.14-slim-trixie

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    curl jq git grep \
    findutils coreutils \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN mkdir -p /workspace

WORKDIR /workspace
