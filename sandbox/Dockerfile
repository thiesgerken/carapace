FROM debian:trixie-20260421@sha256:35b8ff74ead4880f22090b617372daff0ccae742eb5674455d542bef71ef1999

RUN apt-get update \
   && apt-get install -y --no-install-recommends \
   ca-certificates curl file gnupg jq git kubectl ripgrep \
   && mkdir -p /etc/apt/keyrings \
   && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
   | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
   && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_24.x nodistro main" \
   > /etc/apt/sources.list.d/nodesource.list \
   && apt-get update \
   && apt-get install -y --no-install-recommends nodejs \
   && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv@sha256:3b7b60a81d3c57ef471703e5c83fd4aaa33abcd403596fb22ab07db85ae91347 /uv /usr/local/bin/uv

ENV PATH="/root/.local/bin:${PATH}" \
   NODE_USE_ENV_PROXY=1
RUN uv python install 3.14 --default --preview-features python-install-default
RUN corepack enable

# Proxy setup script — reads HTTP(S)_PROXY env vars and writes per-tool
# config files so that apt, git, pip, npm etc. all route through the proxy.
COPY setup-proxy.sh /usr/local/bin/setup-proxy.sh
RUN chmod +x /usr/local/bin/setup-proxy.sh

COPY ccred /usr/local/bin/ccred
RUN chmod +x /usr/local/bin/ccred

RUN mkdir -p /workspace \
   && git config --global --add safe.directory /workspace

WORKDIR /workspace
