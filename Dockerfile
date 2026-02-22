FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim AS builder

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src/ src/
RUN uv build --wheel --out-dir dist

FROM python:3.14-slim-trixie AS runner

WORKDIR /app
COPY --from=builder /app/dist/*.whl ./
RUN pip install --no-cache-dir *.whl && rm *.whl

EXPOSE 8321
CMD ["carapace-server"]
