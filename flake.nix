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
  };

  outputs =
    {
      self,
      nixpkgs,
      pyproject-nix,
      uv2nix,
      pyproject-build-systems,
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
            inherit pkgs;
            inherit (backend) server tokenizerCache;
            inherit (frontend) frontend;
          };
        in
        {
          inherit
            pkgs
            tools
            backend
            frontend
            images
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
          release-tools = p.tools.release;
        }
        // nixpkgs.lib.optionalAttrs (builtins.elem system linuxSystems) (
          {
            inherit (p.backend) server;
            inherit (p.frontend) frontend twemoji;
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
        // {
          helm =
            p.pkgs.runCommand "carapace-helm"
              {
                nativeBuildInputs = [ p.pkgs.kubernetes-helm ];
                src = ./charts/carapace;
              }
              ''
                helm lint "$src"
                helm template carapace "$src" > "$out"
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
          tools = project.${system}.tools.ci;
          release-tools = project.${system}.tools.release;
        }
        // p.images
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
    };
}
