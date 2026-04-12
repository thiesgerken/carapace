FROM debian:trixie@sha256:3352c2e13876c8a5c5873ef20870e1939e73cb9a3c1aeba5e3e72172a85ce9ed

RUN apt-get update \
   && apt-get install -y --no-install-recommends \
   ca-certificates curl file jq git kubectl \
   && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv@sha256:b1e699368d24c57cda93c338a57a8c5a119009ba809305cc8e86986d4a006754 /uv /usr/local/bin/uv

ENV PATH="/root/.local/bin:${PATH}"
RUN uv python install 3.14 --default --preview-features python-install-default

# Proxy setup script — reads HTTP(S)_PROXY env vars and writes per-tool
# config files so that apt, git, pip, npm etc. all route through the proxy.
COPY setup-proxy.sh /usr/local/bin/setup-proxy.sh
RUN chmod +x /usr/local/bin/setup-proxy.sh

COPY ccred /usr/local/bin/ccred
RUN chmod +x /usr/local/bin/ccred

RUN mkdir -p /workspace \
   && git config --global --add safe.directory /workspace

WORKDIR /workspace
