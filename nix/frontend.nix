{
  pkgs,
  nodejs,
}:
let
  manifest = builtins.fromJSON (builtins.readFile ../frontend/package.json);
  src = pkgs.lib.cleanSource ../frontend;
  twemoji = pkgs.fetchurl {
    url = "https://codeload.github.com/jdecked/twemoji/tar.gz/40c2213";
    hash = pkgs.lib.trim (builtins.readFile ./twemoji-hash);
    downloadToTemp = true;
    recursiveHash = true;
    postFetch = ''
      mkdir -p "$out"
      tar -xzf "$downloadedFile" -C "$out" --strip-components=4 --wildcards '*/v/17.0.2/svg/*'
    '';
  };
  # importNpmLock fetches each package from the integrity hashes in package-lock.json,
  # so dependency updates need no separate fixed-output hash.
  npmDeps = pkgs.importNpmLock { npmRoot = ../frontend; };
  common = {
    pname = "carapace-frontend";
    inherit (manifest) version;
    inherit src npmDeps;
    nativeBuildInputs = [
      nodejs
      pkgs.importNpmLock.npmConfigHook
    ];
    NEXT_TELEMETRY_DISABLED = "1";
    CI = "true";
    env.HOME = "/tmp/carapace-frontend-home";
    preConfigure = "mkdir -p $HOME";
    preBuild = ''
      mkdir -p node_modules/.cache/twemoji-40c2213/twemoji-40c2213/v/17.0.2
      cp -R ${twemoji} node_modules/.cache/twemoji-40c2213/twemoji-40c2213/v/17.0.2/svg
    '';
  };
  check =
    name: command:
    pkgs.stdenvNoCC.mkDerivation (
      common
      // {
        pname = "carapace-frontend-${name}";
        buildPhase = ''
          runHook preBuild
          ${command}
          runHook postBuild
        '';
        installPhase = "touch $out";
      }
    );
  frontend = pkgs.stdenvNoCC.mkDerivation (
    common
    // {
      buildPhase = ''
        runHook preBuild
        npm run build
        runHook postBuild
      '';
      installPhase = ''
        mkdir -p "$out"
        cp -R out/. "$out/"
      '';
    }
  );
in
{
  inherit frontend npmDeps twemoji;
  checks = {
    frontend-lint = check "lint" "npm run lint";
    frontend-test = check "test" "npm run test";
    frontend-build = frontend;
  };
}
