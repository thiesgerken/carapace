{
  pkgs,
  pyproject-nix,
  uv2nix,
  pyproject-build-systems,
}:
let
  inherit (pkgs) lib;
  python = pkgs.python314.override {
    # The interpreter passthru follows self, otherwise uv still selects the unstripped build.
    self = python;
    stripConfig = true;
    stripIdlelib = true;
    stripTests = true;
  };
  workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = ../.; };
  pythonSet =
    (pkgs.callPackage pyproject-nix.build.packages {
      inherit python;
    }).overrideScope
      (
        lib.composeManyExtensions [
          pyproject-build-systems.overlays.wheel
          (workspace.mkPyprojectOverlay { sourcePreference = "wheel"; })
          (final: prev: {
            carapace = prev.carapace.overrideAttrs {
              src = lib.fileset.toSource {
                root = ../.;
                fileset = lib.fileset.unions [
                  ../pyproject.toml
                  ../README.md
                  ../src
                ];
              };
            };
            # http-ece ships only an sdist with a legacy setuptools build backend.
            http-ece = prev.http-ece.overrideAttrs (old: {
              nativeBuildInputs =
                (old.nativeBuildInputs or [ ])
                ++ final.resolveBuildSystem {
                  setuptools = [ ];
                };
            });
          })
        ]
      );
  server = pythonSet.mkVirtualEnv "carapace-server" (
    workspace.deps.default
    // {
      carapace = [ "server" ];
    }
  );
  dev = pythonSet.mkVirtualEnv "carapace-checks" workspace.deps.all;
  encodingCacheEntry =
    name: sha256:
    let
      url = "https://openaipublic.blob.core.windows.net/encodings/${name}.tiktoken";
    in
    {
      name = builtins.hashString "sha1" url;
      path = pkgs.fetchurl { inherit url sha256; };
    };
  # The wheels omit BPE tables; pinned cache files keep checks and fresh pods offline.
  tokenizerCache = pkgs.linkFarm "carapace-tokenizer-cache" [
    (encodingCacheEntry "cl100k_base" "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7")
    (encodingCacheEntry "o200k_base" "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d")
  ];
  src = lib.fileset.toSource {
    root = ../.;
    fileset = lib.fileset.unions [
      ../src
      ../tests
      ../sandbox
      ../scripts
      ../pyproject.toml
      ../uv.lock
      ../README.md
      ../ruff.toml
    ];
  };
  check =
    name: command:
    pkgs.runCommand "carapace-${name}"
      {
        inherit src;
        TIKTOKEN_CACHE_DIR = tokenizerCache;
        # HTTPX loads trust roots at construction, even in network-isolated tests.
        SSL_CERT_FILE = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
        nativeBuildInputs = [
          dev
          pkgs.gitMinimal
          pkgs.bash
          pkgs.coreutils
          pkgs.jq
        ];
      }
      ''
        export HOME="$TMPDIR/home"
        mkdir -p "$HOME"
        cp -R "$src" source
        chmod -R u+w source
        cd source
        # Activator paths bypass agent-controlled PATH; only this check copy uses Nix paths.
        substituteInPlace sandbox/carapace-skill-activator \
          --replace-fail /usr/bin/jq ${pkgs.jq}/bin/jq \
          --replace-fail /usr/bin/git ${pkgs.gitMinimal}/bin/git \
          --replace-fail /usr/bin/base64 ${pkgs.coreutils}/bin/base64 \
          --replace-fail /usr/bin/mktemp ${pkgs.coreutils}/bin/mktemp \
          --replace-fail /bin/mkdir ${pkgs.coreutils}/bin/mkdir \
          --replace-fail /bin/rm ${pkgs.coreutils}/bin/rm \
          --replace-fail /bin/chmod ${pkgs.coreutils}/bin/chmod \
          --replace-fail /bin/mv ${pkgs.coreutils}/bin/mv \
          --replace-fail " /bin/sh " " ${pkgs.bash}/bin/sh "
        patchShebangs sandbox
        ${command}
        touch "$out"
      '';
in
{
  inherit python server tokenizerCache;
  checks = {
    pytest = check "pytest" "pytest";
    pyrefly = check "pyrefly" "pyrefly check --python-interpreter-path ${dev}/bin/python";
    ruff = check "ruff" "ruff check src/";
  };
}
