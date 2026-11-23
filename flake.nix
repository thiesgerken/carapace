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
      skillExamples = forLinux (
        system:
        nixpkgs.lib.mapAttrs' (
          name: _:
          nixpkgs.lib.nameValuePair "skill-example-${name}"
            ((import ./nix/skills/examples/${name}/flake.nix).outputs {
              inherit nixpkgs;
              carapace.lib = skillLib;
            }).packages.${system}.default
        ) (builtins.readDir ./nix/skills/examples)
      );
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
        // {
          skill-wrapper-contract = import ./nix/skills/tests.nix {
            inherit (p) pkgs;
            skillLib = skillLib.skill p.pkgs;
          };
          # The examples' local commands run: the venv imports its packages, Node finds node_modules.
          skill-examples-run =
            let
              examples = skillExamples.${system};
            in
            p.pkgs.runCommand "skill-examples-run" { } ''
              [ "$(${examples.skill-example-uv}/bin/demo-usage Ada)" = "hello, Ada" ]
              ${examples.skill-example-npm}/bin/demo-npm-hello Ada | grep -q "hello, Ada"
              ${examples.skill-example-pnpm}/bin/demo-pnpm-hello Ada | grep -q "hello, Ada"
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
        // p.images
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
            ];
            UV_PYTHON = pkgs.python314.interpreter;
            UV_PYTHON_DOWNLOADS = "never";
            shellHook = ''
              printf '🦀 \033[1m\033[38;2;231;76;60mc\033[38;2;220;78;77ma\033[38;2;209;80;95mr\033[38;2;198;82;112ma\033[38;2;188;83;130mp\033[38;2;177;85;147ma\033[38;2;166;87;165mc\033[38;2;155;89;182me\033[0m  \033[2m%s\033[0m\n' 'Python ${pkgs.python314.version} · node ${tools.nodejs.version} · 📖 docs/development.md'
              printf '  \033[32m%s\033[0m \033[2m·\033[0m \033[32m%s\033[0m\n' 'uv run python -m carapace' 'npm --prefix frontend run dev'
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
