FROM ghcr.io/astral-sh/uv:latest AS uv

FROM alpine:3.21

COPY --from=uv /uv /usr/local/bin/uv

RUN apk add --no-cache \
    python3 \
    py3-pip \
    bash \
    curl \
    jq \
    git \
    grep \
    findutils \
    coreutils

RUN mkdir -p /workspace

WORKDIR /workspace
