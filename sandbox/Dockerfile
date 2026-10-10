FROM debian:13@sha256:913f6706df59a68922d1dd08f78c2476560a8d367897200a6005b00e5f67c2d5

RUN apt-get update \
   && apt-get install -y --no-install-recommends tree \
   ca-certificates curl file gnupg jq git kubectl poppler-utils ripgrep \
   && mkdir -p /etc/apt/keyrings \
   && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
   | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
   && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_24.x nodistro main" \
   > /etc/apt/sources.list.d/nodesource.list \
   && apt-get update \
   && apt-get install -y --no-install-recommends nodejs \
   && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv@sha256:cdc6093146eb3ff6a40107b38f008b789e050e77ad87865e381d9917da55a168 /uv /usr/local/bin/uv

ENV PATH="/workspace/.carapace/bin:/root/.local/bin:${PATH}" \
   NODE_USE_ENV_PROXY=1
RUN uv python install 3.14 --default --preview-features python-install-default
RUN corepack enable

# Proxy setup script — reads HTTP(S)_PROXY env vars and writes per-tool
# config files so that apt, git, pip, npm etc. all route through the proxy.
COPY setup-proxy.sh /usr/local/bin/setup-proxy.sh
RUN chmod +x /usr/local/bin/setup-proxy.sh

COPY ccred /usr/local/bin/ccred
RUN chmod +x /usr/local/bin/ccred

COPY carapace-skill-activator /usr/local/bin/carapace-skill-activator
RUN chmod +x /usr/local/bin/carapace-skill-activator

# Self-contained venv for the stdio MCP bridge (skill-declared stdio MCP servers).
# Baked at build time so no dependency resolution happens at runtime (the sandbox's
# egress is proxy/domain-gated and would block a runtime `pip`/`uv` fetch).
RUN uv venv /opt/carapace-mcp --python 3.14 \
   && uv pip install --python /opt/carapace-mcp/bin/python "mcp>=2.2,<3"
COPY carapace-mcp-bridge /usr/local/bin/carapace-mcp-bridge
RUN chmod +x /usr/local/bin/carapace-mcp-bridge

RUN mkdir -p /workspace \
   && git config --global --add safe.directory /workspace

WORKDIR /workspace
