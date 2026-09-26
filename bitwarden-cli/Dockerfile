FROM alpine:3.24@sha256:294b683cb724975bec92580e1e685676bd4b50bda910ddb8c51d4cabeaec77e6

# 2026.2.0 has https://github.com/dani-garcia/vaultwarden/issues/6912
ARG BW_CLI_VERSION=2026.1.0

RUN apk add --no-cache nodejs npm ca-certificates curl \
 && npm install -g @bitwarden/cli@${BW_CLI_VERSION} \
 && npm cache clean --force \
 && rm -rf /root/.npm

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
