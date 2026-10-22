# Bitwarden CLI sidecar image

Runtime-only Nix image using nixpkgs `bitwarden-cli`: on startup it configures the server URL, logs in (API key or password), unlocks the vault, then **`exec`s `bw serve`** bound to `127.0.0.1` inside the container. carapace talks to that HTTP API from the main app or from another container on the same pod/network.

The entrypoint is [`entrypoint.sh`](./entrypoint.sh). Build with `nix build .#bitwarden-image` on Linux x64, or `nix build .#packages.aarch64-linux.bitwarden-image` on Apple Silicon with the native Linux builder. The flake lock pins the CLI and its runtime. The image runs as UID/GID 999 with a read-only root; mount writable storage at `/var/lib/bitwarden-cli` and `/tmp`.

## Environment variables

| Variable             | Required | Description                                                                                                                                                       |
| -------------------- | -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `BW_MASTER_PASSWORD` | Yes      | Master password for vault decryption. Can be supplied via env or secret file (see below).                                                                         |
| `BW_CLIENTID`        | No\*     | API key client ID (Bitwarden web → Account Settings → Keys). With `BW_CLIENTSECRET`, selects **API key login** (needed for 2FA accounts).                         |
| `BW_CLIENTSECRET`    | No\*     | API key client secret. Both must be set together, or both omitted for password login.                                                                             |
| `BW_EMAIL`           | No\*     | Account email for **password-only** login when API key vars are unset. Can be supplied via env or secret file (see below).                                        |
| `BW_SERVER_URL`      | No       | Vault server base URL (e.g. self-hosted Vaultwarden). Empty/unset applies US cloud (`bitwarden.com`) on first run or when the URL changes vs cached state.        |
| `BW_SERVE_PORT`      | No       | Port for `bw serve` (default `8087`).                                                                                                                             |
| `BW_SECRET_DIR`      | No       | Directory for optional file-backed credentials (default `/run/secrets/bitwarden`).                                                                                |
| `BW_DATA_DIR`        | No       | Writable root for Bitwarden CLI app data and carapace’s server-URL cache (default `/var/lib/bitwarden-cli`). Mount a volume here to survive container recreation. |

\* Either set both `BW_CLIENTID` and `BW_CLIENTSECRET`, or set `BW_EMAIL` for password login.

`BW_NOINTERACTION=true` is set by the entrypoint for non-interactive use.

The entrypoint sets **`BITWARDENCLI_APPDATA_DIR`** to `$BW_DATA_DIR/appdata` (Bitwarden CLI upstream) so login/device state is stored on disk. Without a volume on `BW_DATA_DIR`, a new container looks like a new client and many vaults send a “new login” email.

Compose volumes created by the root-running image may need a one-time cache reset or ownership change to `999:999`; follow the [upgrade instructions](../docs/quickstart.md). Kubernetes applies the existing fsGroup 999 recursively when mounting the PVC, so chart users do not need a manual migration.

## Secret files (optional)

For Kubernetes or Docker, you can avoid putting sensitive values in the container **environment** in the orchestrator manifest: mount files whose **names** match the variable names. The entrypoint reads them only when the corresponding env var is **unset or empty**; explicit env always wins.

- **Directory:** `BW_SECRET_DIR` (default `/run/secrets/bitwarden`).
- **Files:** `BW_MASTER_PASSWORD`, `BW_CLIENTID`, `BW_CLIENTSECRET`, `BW_EMAIL` (each optional; only missing/empty env is filled from disk).
- **Content:** read in full and trimmed of leading/trailing whitespace and CR characters (same trimming as `BW_SERVER_URL`).

After a successful `bw unlock --check`, the entrypoint **`unset`s** `BW_MASTER_PASSWORD`, `BW_CLIENTID`, `BW_CLIENTSECRET`, and `BW_EMAIL` before running `bw serve`, so the long-lived process keeps `BW_SESSION` and non-secret config but not those in its environment. Values still exist briefly during login/unlock child processes.

### Kubernetes

Create a Secret with the keys you need (for example `BW_MASTER_PASSWORD` plus either API keys or `BW_EMAIL`), mount it read-only (for example at `/run/secrets/bitwarden`). Set `defaultMode: 0400` on the volume if you like.

```yaml
volumeMounts:
  - name: bitwarden-creds
    mountPath: /run/secrets/bitwarden
    readOnly: true
volumes:
  - name: bitwarden-creds
    secret:
      secretName: your-bitwarden-secret
      defaultMode: 0400
```

Non-secret settings (`BW_SERVER_URL`, `BW_SERVE_PORT`) can remain plain env on the container; credential fields can live entirely in the mounted Secret files.

### Docker Compose

You can use [Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/) and mount them under a directory layout the entrypoint expects, or bind-mount a host directory with the expected filenames. Ensure the mount path matches `BW_SECRET_DIR` if you override it.

## Server URL caching

The desired `BW_SERVER_URL` (after trim) is stored under `$BW_DATA_DIR/carapace-state/last_bw_server_url`. If it matches the current env on the next start, the entrypoint skips `bw logout` and `bw config server`. With a persistent `BW_DATA_DIR`, that cache survives recreation; otherwise it is lost with the container.

## Logging

Progress messages go to **stderr** so they show promptly in `docker compose logs` when stdout is block-buffered. For the best experience, allocate a TTY for this service in Compose if you can.

## Vaultwarden / CLI compatibility

Vaultwarden **1.35.5 or newer** is required for API-key login with the bundled Bitwarden CLI 2026.4.2. Older servers can fail with `TypeError: ... toWrappedAccountCryptographicState`; see [vaultwarden#6912](https://github.com/dani-garcia/vaultwarden/issues/6912). Upgrade the server rather than pinning an older CLI.
