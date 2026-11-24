{
  pkgs,
  nixpkgs,
  nodejs,
  mcpBridgeEnv,
  # The Native Linux Builder on a Mac fails once one build opens about 100k files, and nixpkgs
  # alone has 90k; local images leave it out and fetch it on first use (see docs/development.md).
  withNixpkgsSource ? true,
}:
let
  inherit (pkgs) lib;
  platform = pkgs.stdenv.hostPlatform;
  cpu = platform.parsed.cpu.name;

  # Nix-built interpreters cannot load the native libraries of PyPI wheels, because they bypass
  # nix-ld (#548). The agent's python3 is therefore python-build-standalone, run through nix-ld.
  pythonVersion = "3.14.10";
  pythonRelease = "20261123";
  pythonBuildStandalone = pkgs.stdenvNoCC.mkDerivation {
    pname = "python-build-standalone";
    version = pythonVersion;
    src = pkgs.fetchurl {
      url = "https://github.com/astral-sh/python-build-standalone/releases/download/${pythonRelease}/cpython-${pythonVersion}+${pythonRelease}-${cpu}-unknown-linux-gnu-install_only_stripped.tar.gz";
      hash =
        {
          x86_64 = "sha256-khArFfUUnRJLW0svAPH/L4J88amdwaIkR61ShhvYCs4=";
          aarch64 = "sha256-8WQUASEBRMou6yd07lMfi/kD/X8F0Zi3/u1itAy/S6g=";
        }
        .${cpu};
    };
    dontUnpack = true;
    # Its terminfo duplicates /usr/share/terminfo and has names that differ only in case, which
    # the Native Linux Builder's case-insensitive store rejects.
    installPhase = ''
      mkdir $out
      tar -xzf $src -C $out --strip-components=1 --exclude=python/share/terminfo
    '';
    # Patching ELF headers would point the interpreter at Nix's loader and defeat nix-ld.
    dontFixup = true;
  };
  # The directory name is how uv recognises a managed interpreter.
  uvPythonDir = "/root/.local/share/uv/python/cpython-${pythonVersion}-linux-${cpu}-gnu";

  # The NixOS default nix-ld set without systemd, plus ICU (.NET), expat and libffi (#548).
  nixLdLibraries = pkgs.buildEnv {
    name = "carapace-sandbox-nix-ld-libraries";
    # getLib: buildEnv otherwise links only outputsToInstall, without the shared objects.
    paths = map lib.getLib (
      with pkgs;
      [
        stdenv.cc.cc
        zlib
        zstd
        bzip2
        xz
        openssl
        curl
        libssh
        libsodium
        attr
        acl
        util-linux
        libxml2
        icu
        expat
        libffi
      ]
    );
    extraPrefix = "/share/nix-ld";
    pathsToLink = [ "/lib" ];
    ignoreCollisions = true;
    postBuild = ''
      ln -s ${pkgs.stdenv.cc.bintools.dynamicLinker} "$out/share/nix-ld/lib/ld.so"
    '';
  };

  tools = pkgs.buildEnv {
    name = "carapace-sandbox-tools";
    paths = with pkgs; [
      bashInteractive
      coreutils
      findutils
      diffutils
      gnugrep
      gnused
      gawk
      gnutar
      gzip
      bzip2
      xz
      zstd
      unzip
      which
      procps
      getent
      hostname-debian
      less
      patch
      ncurses
      file
      tree
      gitMinimal
      curl
      jq
      ripgrep
      kubectl
      poppler-utils
      nodejs
      corepack_24
      uv
      nix
      sandboxScripts
    ];
    pathsToLink = [ "/bin" ];
  };

  sandboxScripts = pkgs.runCommand "carapace-sandbox-scripts" { } ''
    for script in ccred cgate mcp setup-proxy.sh carapace-mcp-bridge; do
      install -Dm755 ${../sandbox}/$script "$out/bin/$script"
    done
    sed -i '1c#!${mcpBridgeEnv}/bin/python' "$out/bin/carapace-mcp-bridge" "$out/bin/mcp"
  '';

  nixConf = pkgs.writeText "nix.conf" ''
    experimental-features = nix-command flakes
    # Single-user Nix as root; containers have no build users and no namespaces for the build sandbox.
    build-users-group =
    sandbox = false
    nix-path = nixpkgs=flake:nixpkgs
    # The global registry is a download from channels.nixos.org, which the sandbox cannot reach
    # without a domain approval; nixpkgs resolves from /etc/nix/registry.json instead.
    flake-registry =
  '';
  # The flake's own nixpkgs lock. `__final` is what makes Nix (2.34) use the already valid store
  # path for that narHash, which the full image ships; without it Nix fetches the tarball into its
  # Git cache anyway, and fails offline. Where the path is missing, Nix substitutes or downloads it.
  lock = builtins.fromJSON (builtins.readFile ../flake.lock);
  registry = pkgs.writeText "registry.json" (
    builtins.toJSON {
      version = 2;
      flakes = [
        {
          from = {
            type = "indirect";
            id = "nixpkgs";
          };
          to = lock.nodes.${lock.nodes.${lock.root}.inputs.nixpkgs}.locked // {
            __final = true;
          };
        }
      ];
    }
  );
  fontsConf = pkgs.makeFontsConf { fontDirectories = [ pkgs.dejavu_fonts ]; };
  locales = pkgs.glibcLocales.override {
    allLocales = false;
    locales = [ "en_US.UTF-8/UTF-8" ];
  };
  ldso = lib.last (lib.splitString "/" pkgs.stdenv.cc.bintools.dynamicLinker);

  # What an FHS system provides as files, as absolute links into the store. Everything lives in
  # image contents so that the image's Nix database registers and roots it.
  rootFiles = pkgs.runCommand "carapace-sandbox-root" { } ''
    mkdir -p $out/etc/nix $out/etc/ssl/certs $out/etc/fonts $out/${platform.libDir} \
      $out/run/current-system/sw/share $out/usr/share $out/usr/lib/locale \
      $out/root/.local/bin
    cat > $out/etc/passwd <<'EOF'
    root:x:0:0:root:/root:/bin/bash
    nobody:x:65534:65534:nobody:/var/empty:/bin/false
    EOF
    cat > $out/etc/group <<'EOF'
    root:x:0:
    nogroup:x:65534:
    EOF
    ln -s ${nixConf} $out/etc/nix/nix.conf
    ln -s ${registry} $out/etc/nix/registry.json
    ${lib.optionalString withNixpkgsSource ''
      # Puts the source into the image's closure and Nix database, which the registry entry relies on.
      ln -s ${nixpkgs} $out/etc/nix/nixpkgs
    ''}    ln -s ${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt $out/etc/ssl/certs/ca-certificates.crt
    ln -s ${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt $out/etc/ssl/cert.pem
    ln -s ${pkgs.iana-etc}/etc/services $out/etc/services
    ln -s ${pkgs.iana-etc}/etc/protocols $out/etc/protocols
    ln -s ${fontsConf} $out/etc/fonts/fonts.conf
    ln -s ${pkgs.ncurses}/share/terminfo $out/usr/share/terminfo
    ln -s ${locales}/lib/locale/locale-archive $out/usr/lib/locale/locale-archive
    ln -s ${pkgs.nix-ld}/libexec/nix-ld $out/${platform.libDir}/${ldso}
    ln -s ${nixLdLibraries}/share/nix-ld $out/run/current-system/sw/share/nix-ld
    for name in python python3 python3.14; do
      ln -s ${uvPythonDir}/bin/python3.14 $out/root/.local/bin/$name
    done
  '';
in
pkgs.dockerTools.buildLayeredImage {
  name = "carapace-sandbox";
  tag = "local";
  contents = [
    tools
    rootFiles
  ];
  includeNixDB = true;
  extraCommands = ''
    mkdir -p tmp workspace usr/local
    chmod 1777 tmp
    ln -s ../bin usr/bin
    ln -s ../../bin usr/local/bin
    # uv counts an interpreter as managed only if its real prefix is inside uv's directory, so the
    # files are copied there, as `uv python install` would.
    # The Carapace-managed skill profile (src/carapace/builder/profile.py); its bin is on PATH below.
    mkdir -p nix/var/nix/profiles/carapace
    mkdir -p root/.local/share/uv/python
    cp -R ${pythonBuildStandalone} .${uvPythonDir}
    chmod -R u+w .${uvPythonDir}
    printf '[safe]\n\tdirectory = /workspace\n' > root/.gitconfig
  '';
  config = {
    Cmd = [ "/bin/bash" ];
    WorkingDir = "/workspace";
    Env = [
      # Skill commands come last, so a skill cannot shadow a tool of the image or the agent's own.
      "PATH=/root/.local/bin:/root/.nix-profile/bin:/bin:/nix/var/nix/profiles/carapace/skills/bin"
      "HOME=/root"
      "USER=root"
      "LANG=C.UTF-8"
      # Nix's glibc reads only this variable, and nix-ld hands it to foreign binaries as well;
      # /usr/lib/locale is for the rare binary that bundles its own glibc.
      "LOCALE_ARCHIVE=${locales}/lib/locale/locale-archive"
      "NODE_USE_ENV_PROXY=1"
      "UV_PYTHON_PREFERENCE=only-managed"
    ];
  };
}
