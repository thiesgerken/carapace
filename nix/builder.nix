{ pkgs, builder }:
let
  inherit (pkgs) lib;
  apiUid = "999";
  cacheUid = "998";
  # Root-owned, so the API user (and with it any evaluation) can neither read nor swap the key.
  keyDir = "/nix/var/carapace-builder-key";
  upstreamCaches = [
    {
      url = "https://cache.nixos.org";
      public_key = "cache.nixos.org-1:6NCHdD59X431o0gWypbMrAURkbJ16ZPMQFGspcDShjY=";
    }
  ];

  harmoniaConf = pkgs.writeText "harmonia.toml" ''
    bind = "127.0.0.1:5000"
    enable_compression = true
    priority = 30
    sign_key_paths = [ "${keyDir}/secret" ]
  '';
  buildUsers = lib.genList (i: i + 1) 32;

  nixConf = pkgs.writeText "nix.conf" ''
    experimental-features = nix-command flakes
    build-users-group = nixbld
    # No fallback: the start-up probe refuses to serve if the sandbox cannot be set up.
    sandbox = true
    sandbox-fallback = false
    max-jobs = auto
    allow-import-from-derivation = false
    # Only root may change daemon settings; the API user's evaluations cannot turn the sandbox off.
    trusted-users = root
  '';

  start = pkgs.writeShellApplication {
    name = "carapace-builder-start";
    runtimeInputs = [
      pkgs.nix
      pkgs.util-linuxMinimal
      pkgs.jq
      pkgs.harmonia
      builder
    ];
    text = ''
      trap 'kill $(jobs -p) 2>/dev/null; wait' TERM INT
      if [ ! -e ${keyDir}/secret ]; then
        mkdir -p ${keyDir}
        nix-store --generate-binary-cache-key carapace-builder-1 ${keyDir}/secret ${keyDir}/public
      fi
      chown ${cacheUid}:${cacheUid} ${keyDir}/secret
      chmod 600 ${keyDir}/secret
      chmod 644 ${keyDir}/public
      # The daemon substitutes from the same upstreams the cache passes through.
      NIX_CONFIG="substituters = $(jq -r 'map(.url) | join(" ")' <<< "$CARAPACE_BUILDER_UPSTREAM_CACHES")
      trusted-public-keys = $(jq -r 'map(.public_key) | join(" ")' <<< "$CARAPACE_BUILDER_UPSTREAM_CACHES")" \
        nix-daemon &
      until [ -S /nix/var/nix/daemon-socket/socket ]; do sleep 0.1; done
      # The API and every evaluation it starts run unprivileged, through the daemon.
      HOME=/tmp NIX_REMOTE=daemon setpriv --reuid=${apiUid} --regid=${apiUid} --clear-groups carapace-builder &
      # harmonia serves the store to the cache listener on loopback and is the only one with the key.
      CONFIG_FILE=${harmoniaConf} setpriv --reuid=${cacheUid} --regid=${cacheUid} --clear-groups harmonia-cache &
      # Whichever stops first takes the container down with it.
      wait -n
      echo 'carapace-builder: the daemon, the API or the cache stopped' >&2
      exit 1
    '';
  };

  tools = pkgs.buildEnv {
    name = "carapace-builder-tools";
    paths = [
      pkgs.bash
      pkgs.coreutils
      pkgs.gitMinimal
      pkgs.nix
      start
      builder
    ];
    pathsToLink = [ "/bin" ];
  };

  rootFiles = pkgs.runCommand "carapace-builder-root" { } ''
    mkdir -p $out/etc/nix $out/etc/ssl/certs
    {
      echo 'root:x:0:0:root:/root:/bin/bash'
      echo 'carapace-builder:x:${apiUid}:${apiUid}:Carapace builder:/tmp:/bin/false'
      echo 'harmonia:x:${cacheUid}:${cacheUid}:Carapace builder cache:/var/empty:/bin/false'
      ${lib.concatMapStrings (
        i:
        "echo 'nixbld${toString i}:x:${toString (30000 + i)}:30000:Nix build user:/var/empty:/bin/false'\n"
      ) buildUsers}
    } > $out/etc/passwd
    {
      echo 'root:x:0:'
      echo 'carapace-builder:x:${apiUid}:'
      echo 'harmonia:x:${cacheUid}:'
      echo 'nixbld:x:30000:${lib.concatMapStringsSep "," (i: "nixbld${toString i}") buildUsers}'
    } > $out/etc/group
    ln -s ${nixConf} $out/etc/nix/nix.conf
    ln -s ${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt $out/etc/ssl/certs/ca-certificates.crt
  '';

  # The builder's store is a volume mounted over /nix, so it outlives image updates. This step,
  # run with the volume at /mnt/nix before the builder starts, puts the image's own closure into it.
  init = pkgs.writeShellApplication {
    name = "carapace-builder-init";
    runtimeInputs = [
      pkgs.nix
      pkgs.coreutils
    ];
    text = ''
      # Files plus the image's own registration, as dockerTools does: `nix copy` would re-hash every
      # path, and images built on a Mac carry case-hacked names that fail that check.
      mkdir -p /mnt/nix/store
      for path in $(nix-store -qR ${tools} ${rootFiles}); do
        if [ ! -e "/mnt$path" ]; then
          cp -a "$path" "/mnt$path.partial"
          mv "/mnt$path.partial" "/mnt$path"
        fi
      done
      # shellcheck disable=SC2046
      nix-store --dump-db $(nix-store -qR ${tools} ${rootFiles}) | NIX_REMOTE='local?root=/mnt' nix-store --load-db
      # Roots for the current image only, so GC can collect the closure of earlier images.
      roots=/mnt/nix/var/nix/gcroots/carapace-builder-image
      rm -rf "$roots"
      mkdir -p "$roots" /mnt/nix/var/carapace-builder
      ln -s ${tools} "$roots/tools"
      ln -s ${rootFiles} "$roots/root"
      chown ${apiUid}:${apiUid} /mnt/nix/var/carapace-builder
    '';
  };
in
pkgs.dockerTools.buildLayeredImage {
  name = "carapace-builder";
  tag = "local";
  contents = [
    tools
    rootFiles
    init
  ];
  includeNixDB = true;
  extraCommands = ''
    mkdir -p tmp root
    chmod 1777 tmp
  '';
  config = {
    Cmd = [ "/bin/carapace-builder-start" ];
    Env = [
      "PATH=/bin"
      "CARAPACE_BUILDER_UPSTREAM_CACHES=${builtins.toJSON upstreamCaches}"
    ];
    ExposedPorts = {
      "8330/tcp" = { };
      "8331/tcp" = { };
    };
  };
}
