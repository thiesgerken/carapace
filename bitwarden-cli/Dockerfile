FROM alpine:3.21

# 2026.2.0 has https://github.com/dani-garcia/vaultwarden/issues/6912
ARG BW_CLI_VERSION=2026.1.0

RUN apk add --no-cache nodejs npm ca-certificates curl \
 && npm install -g @bitwarden/cli@${BW_CLI_VERSION} \
 && npm cache clean --force \
 && rm -rf /root/.npm

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
