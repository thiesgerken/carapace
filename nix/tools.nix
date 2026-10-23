{ pkgs }:
let
  manifest = builtins.fromJSON (builtins.readFile ../frontend/package.json);
  pnpmVersion = pkgs.lib.removePrefix "pnpm@" manifest.packageManager;
  nodejs = pkgs.nodejs_24;
  binaries = builtins.fromJSON (builtins.readFile ./pnpm-binaries.json);
  binary = binaries.platforms.${pkgs.stdenv.hostPlatform.system};
  pnpm =
    assert pkgs.lib.assertMsg (
      binaries.version == pnpmVersion
    ) "pnpm binary pins must match frontend/package.json; run scripts/update-nix-deps.py";
    pkgs.stdenvNoCC.mkDerivation {
      pname = "pnpm";
      version = pnpmVersion;
      src = pkgs.fetchurl {
        url = "https://github.com/pnpm/pnpm/releases/download/v${pnpmVersion}/${binary.asset}";
        inherit (binary) hash;
      };
      unpackPhase = ''
        runHook preUnpack
        mkdir source
        tar -xzf "$src" -C source
        cd source
        runHook postUnpack
      '';
      dontBuild = true;
      nativeBuildInputs = [
        pkgs.makeWrapper
      ]
      ++ pkgs.lib.optionals pkgs.stdenv.isLinux [ pkgs.autoPatchelfHook ];
      buildInputs = pkgs.lib.optionals pkgs.stdenv.isLinux [ pkgs.stdenv.cc.cc.lib ];
      installPhase = ''
        runHook preInstall
        mkdir -p "$out/libexec/pnpm" "$out/bin"
        install -m755 pnpm "$out/libexec/pnpm/pnpm"
        cp -R dist "$out/libexec/pnpm/"
        makeWrapper "$out/libexec/pnpm/pnpm" "$out/bin/pnpm" \
          --prefix PATH : ${pkgs.lib.makeBinPath [ nodejs ]}
        makeWrapper "$out/bin/pnpm" "$out/bin/pnpx" --add-flags dlx
        runHook postInstall
      '';
      doInstallCheck = true;
      installCheckPhase = ''
        pushd "$TMPDIR"
        test "$("$out/bin/pnpm" --version)" = "${pnpmVersion}"
        popd
      '';
      passthru = {
        nodejs-slim = nodejs;
        majorVersion = pkgs.lib.versions.major pnpmVersion;
      };
    };
in
{
  inherit nodejs pnpm;
  ci = pkgs.buildEnv {
    name = "carapace-ci-tools";
    paths = with pkgs; [
      bash
      coreutils
      skopeo
      kubernetes-helm
      python314
      git
      curl
      jq
      gh
      cacert
    ];
    pathsToLink = [
      "/bin"
      "/etc/ssl/certs"
    ];
  };
  release = pkgs.buildEnv {
    name = "carapace-release-tools";
    paths = with pkgs; [
      bash
      coreutils
      uv
      python314
      git
      cacert
    ];
    pathsToLink = [
      "/bin"
      "/etc/ssl/certs"
    ];
  };
}
