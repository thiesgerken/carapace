FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim@sha256:abc097534bf1c917a8ed6408e28c87cf191560c4da3ced2016bf8b9da74b5831

# Install git, jq, curl — needed for git http-backend and pre-receive hooks
RUN apt-get update && apt-get install -y --no-install-recommends \
    git jq curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 999 nonroot \
    && useradd --system --gid 999 --uid 999 --create-home nonroot
WORKDIR /app

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# Install dependencies first (cached layer)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

# Copy project source and install the project itself
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

ENV PATH="/app/.venv/bin:$PATH"
ENTRYPOINT []
USER nonroot

EXPOSE 8321
CMD ["carapace-server"]
