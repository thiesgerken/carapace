FROM ghcr.io/astral-sh/uv:0.10.4-python3.14-trixie  AS uv

FROM python:3.14-slim

COPY --from=uv /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --no-install-project --no-dev --frozen

COPY src/ src/
RUN uv sync --no-dev --frozen

EXPOSE 8321

CMD ["uv", "run", "carapace-server"]
