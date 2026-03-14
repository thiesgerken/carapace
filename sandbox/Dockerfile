FROM alpine:3.23

RUN apk add --no-cache \
    python3 py3-pip bash \
    curl jq git grep \
    findutils coreutils uv \
    ca-certificates \
 && update-ca-certificates

RUN mkdir -p /workspace

WORKDIR /workspace
