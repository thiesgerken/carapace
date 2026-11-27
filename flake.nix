{
  description = "Carapace packages, checks, runtime images, and developer tooling";

  # Release CI pushes its x86_64-linux builds here.
  nixConfig = {
    extra-substituters = [ "https://thiesgerken.cachix.org" ];
    extra-trusted-public-keys = [
      "thiesgerken.cachix.org-1:SpR6r/0v3OYrmAITqLiN+XxzJLKZg+zT4nzs4GlpTGE="
    ];
  };

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    # The CLI runs from this input (`nix run --inputs-from . presswerk`), so CLI and declaration
    # schema always move together. Its own nixpkgs stays: that is the combination upstream tests.
    presswerk.url = "github:jkuball/presswerk/v0.16.0";
  };

  outputs =
    {
      self,
      nixpkgs,
      pyproject-nix,
      uv2nix,
      pyproject-build-systems,
      presswerk,
    }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "aarch64-darwin"
      ];
      linuxSystems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forSystems = nixpkgs.lib.genAttrs systems;
      forLinux = nixpkgs.lib.genAttrs linuxSystems;
      linuxFor = system: if system == "aarch64-darwin" then "aarch64-linux" else system;
      # What skills get from the skills subflake (nix/skills/flake.nix), here on this flake's inputs.
      skillLib = import ./nix/skills {
        inherit
          nixpkgs
          pyproject-nix
          uv2nix
          pyproject-build-systems
          ;
      };
      # Built against this checkout's lib, as the skills of a knowledge repo are against their pinned one.
      # CI also builds the bundled ones against their own flake.lock (.github/workflows/nix-verify.yml).
      skillFlakes =
        prefix: dir:
        forLinux (
          system:
          nixpkgs.lib.mapAttrs' (
            name: _:
            nixpkgs.lib.nameValuePair "${prefix}-${name}"
              ((import "${dir}/${name}/flake.nix").outputs {
                inherit nixpkgs;
                carapace.lib = skillLib;
              }).packages.${system}.default
          ) (nixpkgs.lib.filterAttrs (name: _: builtins.pathExists "${dir}/${name}/flake.nix") (builtins.readDir dir))
        );
      skillExamples = skillFlakes "skill-example" ./nix/skills/examples;
      bundledSkills = skillFlakes "skill-bundled" ./src/carapace/assets/skills;
      project = forSystems (
        system:
        let
          pkgs = import nixpkgs { inherit system; };
          tools = import ./nix/tools.nix { inherit pkgs; };
          backend = import ./nix/python.nix {
            inherit
              pkgs
              pyproject-nix
              uv2nix
              pyproject-build-systems
              ;
          };
          frontend = import ./nix/frontend.nix {
            inherit pkgs;
            inherit (tools) nodejs;
          };
          images = import ./nix/images.nix {
            inherit pkgs nixpkgs;
            inherit (tools) nodejs;
            inherit (backend)
              server
              builder
              tokenizerCache
              mcpBridgeEnv
              ;
            inherit (frontend) frontend;
          };
          # The version comes from the committed Chart.yaml, which the release commit bumps.
          chart =
            pkgs.runCommand "carapace-chart.tgz"
              {
                nativeBuildInputs = [ pkgs.kubernetes-helm ];
                src = ./charts/carapace;
              }
              ''
                helm package "$src" --destination .
                mv carapace-*.tgz "$out"
              '';
        in
        {
          inherit
            pkgs
            tools
            backend
            frontend
            images
            chart
            ;
        }
      );
    in
    {
      packages = forSystems (
        system:
        let
          p = project.${system};
        in
        {
          ci-tools = p.tools.ci;
        }
        // nixpkgs.lib.optionalAttrs (builtins.elem system linuxSystems) (
          {
            inherit (p.backend) server;
            inherit (p.frontend) frontend twemoji;
            inherit (p) chart;
            default = p.backend.server;
          }
          // p.images
        )
      );
      checks = forLinux (
        system:
        let
          p = project.${system};
        in
        p.backend.checks
        // p.frontend.checks
        // skillExamples.${system}
        // bundledSkills.${system}
        // {
          skill-wrapper-contract = import ./nix/skills/tests.nix {
            inherit (p) pkgs;
            skillLib = skillLib.skill p.pkgs;
            inherit (skillLib) skillsFlake;
          };
          # The examples' local commands run: the venv imports its packages, Node finds node_modules, the
          # nixpkgs script finds its runtimeInputs.
          skill-examples-run =
            let
              examples = skillExamples.${system};
            in
            p.pkgs.runCommand "skill-examples-run" { } ''
              [ "$(${examples.skill-example-uv}/bin/demo-usage Ada)" = "hello, Ada" ]
              ${examples.skill-example-npm}/bin/demo-npm-hello Ada | grep -q "hello, Ada"
              # A hand-written one-page PDF: qpdf adds the missing cross-reference table (with warnings),
              # then doubles it.
              printf '%s\n' '%PDF-1.4' '1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj' \
                '2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj' \
                '3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 10 10]/Resources<<>>>>endobj' \
                'trailer<</Size 4/Root 1 0 R>>' '%%EOF' > broken.pdf
              ${p.pkgs.qpdf}/bin/qpdf --warning-exit-0 broken.pdf one.pdf
              ${p.pkgs.qpdf}/bin/qpdf --empty --pages one.pdf one.pdf -- two.pdf
              # Warnings alone must not fail the command. An assignment, so its exit status counts.
              pages="$(${examples.skill-example-nix}/bin/demo-nix-pages broken.pdf)"
              [ "$pages" = 1 ]
              [ "$(${examples.skill-example-nix}/bin/demo-nix-pages two.pdf)" = 2 ]
              [ "$(echo '{"a":1}' | ${examples.skill-example-nix}/bin/demo-nix-jq .a)" = 1 ]
              touch $out
            '';
          # The bundled commands start: their wrappers ask cgate and ccred first, stubbed here.
          skill-bundled-run =
            let
              bundled = bundledSkills.${system};
              # Answers like Carapace with the settings a wrapper exports (`cgate request --command`).
              cgate = p.pkgs.writeShellScriptBin "cgate" "echo export CARAPACE_HOST=carapace.example.com";
              ccred = p.pkgs.writeShellScriptBin "ccred" "echo demo-secret";
            in
            p.pkgs.runCommand "skill-bundled-run" { nativeBuildInputs = [ cgate ccred ]; } ''
              # Into a file: grep -q would stop reading and fail the writer with SIGPIPE under pipefail.
              shows_usage() { "$1" --help > help.txt; grep -qi usage help.txt; }
              shows_usage ${bundled.skill-bundled-wikipedia}/bin/wiki-search
              shows_usage ${bundled.skill-bundled-wikipedia}/bin/wiki-fetch
              shows_usage ${bundled.skill-bundled-web}/bin/web_search
              shows_usage ${bundled.skill-bundled-web}/bin/web_fetch
              shows_usage ${bundled.skill-bundled-carapace}/bin/carapace
              touch $out
            '';
          helm =
            p.pkgs.runCommand "carapace-helm"
              {
                nativeBuildInputs = [ p.pkgs.kubernetes-helm ];
                src = ./charts/carapace;
              }
              ''
                helm lint "$src" --set postgres.image.tag=19-alpine
                helm template carapace "$src" --set postgres.image.tag=19-alpine > "$out"
              '';
        }
      );
      ciBuilds = forSystems (
        system:
        let
          linux = linuxFor system;
          p = project.${linux};
        in
        self.checks.${linux}
        // {
          inherit (p.backend) server;
          inherit (p.frontend) frontend;
          inherit (p) chart;
          tools = project.${system}.tools.ci;
        }
        # The lite sandbox image is for local Mac builds only; CI builds and publishes the full one.
        // removeAttrs p.images [ "sandbox-image-lite" ]
        # The release jobs run there and substitute the CLI from our cache, not a third party's.
        // nixpkgs.lib.optionalAttrs (system == "x86_64-linux") {
          presswerk = presswerk.packages.${system}.default;
        }
      );
      devShells = forSystems (
        system:
        let
          inherit (project.${system}) pkgs tools;
          linux = linuxFor system;
        in
        {
          default = pkgs.mkShell {
            packages = [
              pkgs.python314
              pkgs.uv
              tools.nodejs
              pkgs.git
              pkgs.kubernetes-helm
              pkgs.skopeo
              pkgs.jq
              pkgs.process-compose
              pkgs.redis
              pkgs.socat
            ];
            UV_PYTHON = pkgs.python314.interpreter;
            UV_PYTHON_DOWNLOADS = "never";
            # The process-compose dev stack's ports and Docker names (docs/development.md#dev-stack). Only the
            # CARAPACE_DEV_STACK key of .env is read, never the whole file, so the shell gets no secrets.
            shellHook = ''
              carapace_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
              carapace_stack=$(sed -n 's/^CARAPACE_DEV_STACK=//p' "$carapace_root/.env" 2>/dev/null | tail -n 1)
              carapace_stack=''${carapace_stack:-0}
              if [[ $carapace_stack =~ ^[0-9]$ ]]; then
                carapace_base=$((7500 + 10 * carapace_stack))
                export CARAPACE_DEV_STACK=$carapace_stack
                export CARAPACE_DEV_FRONTEND_PORT=$carapace_base
                export CARAPACE_DEV_SERVER_PORT=$((carapace_base + 1))
                export CARAPACE_DEV_SANDBOX_PORT=$((carapace_base + 2))
                export CARAPACE_DEV_INTERNAL_PORT=$((carapace_base + 3))
                export CARAPACE_DEV_PROXY_PORT=$((carapace_base + 4))
                export CARAPACE_DEV_REDIS_PORT=$((carapace_base + 5))
                export CARAPACE_DEV_BUILDER_PORT=$((carapace_base + 6))
                export CARAPACE_DEV_BUILDER_CACHE_PORT=$((carapace_base + 7))
                export PC_PORT_NUM=$((carapace_base + 8))
                # A Kubernetes label value: at most 63 of [A-Za-z0-9_.-].
                carapace_dir=$(basename "$carapace_root" | tr -c 'A-Za-z0-9_.\n-' '-')
                export CARAPACE_DEV_INSTANCE="dev-''${carapace_dir:0:59}"
                export CARAPACE_DEV_SANDBOX_NETWORK="carapace-sandbox-$CARAPACE_DEV_INSTANCE"
                export CARAPACE_DEV_RELAY="carapace-relay-$CARAPACE_DEV_INSTANCE"
                export CARAPACE_DEV_BUILDER="carapace-builder-$CARAPACE_DEV_INSTANCE"
                export CARAPACE_DEV_BUILDER_VOLUME="carapace-builder-nix-$CARAPACE_DEV_INSTANCE"
                export CARAPACE_DEV_LINUX_SYSTEM=${linux}
              else
                printf '\033[31mCARAPACE_DEV_STACK=%s in .env is not a digit 0-9; the dev stack is not configured.\033[0m\n' "$carapace_stack" >&2
              fi
              unset carapace_root carapace_stack carapace_base carapace_dir
              printf '🦀 \033[1m\033[38;2;231;76;60mc\033[38;2;220;78;77ma\033[38;2;209;80;95mr\033[38;2;198;82;112ma\033[38;2;188;83;130mp\033[38;2;177;85;147ma\033[38;2;166;87;165mc\033[38;2;155;89;182me\033[0m  \033[2m%s\033[0m\n' 'Python ${pkgs.python314.version} · node ${tools.nodejs.version} · 📖 docs/development.md'
              printf '  \033[32m%s\033[0m \033[2m%s\033[0m\n' 'process-compose up' "stack ''${CARAPACE_DEV_STACK:-?} · http://localhost:''${CARAPACE_DEV_FRONTEND_PORT:-?}"
              printf '  \033[32m%s\033[0m\n' 'nix build .#checks.${linux}.<check>'
            '';
          };
        }
      );
      presswerk.default = presswerk.lib.mkRelease {
        sourceRoot = self.outPath;
        versionFiles = {
          toml.pyproject = {
            path = "pyproject.toml";
            key = "project.version";
          };
          json = {
            frontend = {
              path = "frontend/package.json";
              key = "version";
            };
            frontend-lock = {
              path = "frontend/package-lock.json";
              key = "version";
            };
            frontend-lock-root = {
              path = "frontend/package-lock.json";
              key = ''packages."".version'';
            };
          };
          regex = {
            uv-lock = {
              path = "uv.lock";
              pattern = ''^name = "carapace"\nversion = "(?<version>[^"]+)"$'';
            };
            chart = {
              path = "charts/carapace/Chart.yaml";
              pattern = ''^version: (?<version>\S+)$'';
            };
            chart-app = {
              path = "charts/carapace/Chart.yaml";
              pattern = ''^appVersion: "(?<version>[^"]+)"$'';
            };
          };
        };
        analyzer.gitmoji = {
          enable = true;
          # Refactorings and CI changes ship in the images, so they release a patch like fixes do.
          catalog.recycle.semver = "patch";
          catalog.construction_worker.semver = "patch";
        };
        # The format python-semantic-release wrote, so the existing sections stay recognized.
        changelog.heading = "## v{version} ({date})";
        publishers =
          let
            # The packages are public, so `plan` and `prepare` check the previous release anonymously.
            ghcr = {
              public = true;
              username.secret = "GITHUB_ACTOR";
              password.secret = "GITHUB_TOKEN";
            };
            artifacts = self.packages.x86_64-linux;
          in
          {
            oci-image =
              nixpkgs.lib.mapAttrs
                (
                  name: image:
                  ghcr
                  // {
                    repository = "ghcr.io/thiesgerken/${name}";
                    platforms."linux/amd64" = image;
                    aliases = [ "latest" ];
                  }
                )
                {
                  carapace = artifacts.server-image;
                  carapace-frontend = artifacts.frontend-image;
                  carapace-bitwarden-cli = artifacts.bitwarden-image;
                  carapace-sandbox = artifacts.sandbox-image;
                  carapace-builder = artifacts.builder-image;
                };
            oci-helm.carapace = ghcr // {
              repository = "ghcr.io/thiesgerken/charts/carapace";
              inherit (artifacts) chart;
            };
            github-release.default = {
              repository = "thiesgerken/carapace";
              body = ''
                {{ notes }}

                ## Docker Images

                ```
                docker pull ghcr.io/thiesgerken/carapace:{{ version }}
                docker pull ghcr.io/thiesgerken/carapace-frontend:{{ version }}
                docker pull ghcr.io/thiesgerken/carapace-sandbox:{{ version }}
                docker pull ghcr.io/thiesgerken/carapace-bitwarden-cli:{{ version }}
                docker pull ghcr.io/thiesgerken/carapace-builder:{{ version }}
                ```

                ## Helm Chart

                ```
                helm install carapace oci://ghcr.io/thiesgerken/charts/carapace --version {{ version }}
                ```
              '';
            };
          };
      };
    };
}
