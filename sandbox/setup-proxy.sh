#!/bin/sh
# Configure proxy settings for all common tools from HTTP(S)_PROXY env vars.
# Sourced at container startup before the main process.
set -e

if [ -z "$HTTP_PROXY" ]; then
  exit 0
fi

# --- apt-get ---
# apt sometimes ignores the http_proxy env var; a config file is more reliable.
cat > /etc/apt/apt.conf.d/99proxy <<EOF
Acquire::http::Proxy "$HTTP_PROXY";
Acquire::https::Proxy "$HTTPS_PROXY";
EOF

# --- git ---
git config --global http.proxy "$HTTP_PROXY"
git config --global http.proxyAuthMethod basic

# --- pip ---
mkdir -p /etc/pip
cat > /etc/pip/pip.conf <<EOF
[global]
proxy = $HTTPS_PROXY
EOF

# --- uv ---
# uv reads HTTPS_PROXY directly; nothing extra needed.

# --- npm / node ---
# npm reads npm_config_proxy / npm_config_https_proxy env vars (set in
# _build_proxy_env), but also honours /root/.npmrc for the root user.
cat > /root/.npmrc <<EOF
proxy=$HTTP_PROXY
https-proxy=$HTTPS_PROXY
EOF

echo "Proxy configured for apt, git, pip, npm"
