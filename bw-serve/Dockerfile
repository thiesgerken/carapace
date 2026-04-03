FROM debian:bookworm-slim

ARG BW_CLI_VERSION=2026.2.0

RUN apt-get update \
 && apt-get install -y --no-install-recommends wget unzip ca-certificates \
 && wget -q "https://github.com/bitwarden/clients/releases/download/cli-v${BW_CLI_VERSION}/bw-linux-${BW_CLI_VERSION}.zip" \
 && unzip "bw-linux-${BW_CLI_VERSION}.zip" \
 && chmod +x bw \
 && mv bw /usr/local/bin/bw \
 && rm -f *.zip \
 && apt-get purge -y wget unzip \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
