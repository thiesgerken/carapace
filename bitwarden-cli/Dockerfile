FROM alpine:3.23@sha256:5b10f432ef3da1b8d4c7eb6c487f2f5a8f096bc91145e68878dd4a5019afde11

# 2026.2.0 has https://github.com/dani-garcia/vaultwarden/issues/6912
ARG BW_CLI_VERSION=2026.1.0

RUN apk add --no-cache nodejs npm ca-certificates curl \
 && npm install -g @bitwarden/cli@${BW_CLI_VERSION} \
 && npm cache clean --force \
 && rm -rf /root/.npm

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
