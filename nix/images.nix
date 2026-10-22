{
  pkgs,
  server,
  tokenizerCache,
  frontend,
}:
let
  identity = pkgs.runCommand "carapace-runtime-identity" { } ''
    mkdir -p "$out/etc"
    echo 'carapace:x:999:999:Carapace:/tmp:/sbin/nologin' > "$out/etc/passwd"
    echo 'carapace:x:999:' > "$out/etc/group"
  '';
  image =
    name: contents: config:
    pkgs.dockerTools.buildLayeredImage {
      inherit name;
      tag = "local";
      contents = contents ++ [ identity ];
      extraCommands = ''
        mkdir -p tmp var/lib/carapace var/lib/bitwarden-cli
        chmod 1777 tmp
      '';
      fakeRootCommands = ''
        chown 999:999 var/lib/carapace var/lib/bitwarden-cli
      '';
      config = {
        User = "999:999";
        WorkingDir = "/tmp";
      }
      // config
      // {
        Env = [
          "HOME=/tmp"
          "TMPDIR=/tmp"
        ]
        ++ (config.Env or [ ]);
      };
    };
  tlsEnv = [
    "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
    "SSL_CERT_DIR=${pkgs.cacert}/etc/ssl/certs"
    "GIT_SSL_CAINFO=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
  ];
  frontendRoutes = pkgs.writeText "carapace-frontend-routes.conf" (
    builtins.replaceStrings [ "/usr/share/nginx/html" ] [ "${frontend}" ] (
      builtins.readFile ../frontend/nginx.conf
    )
  );
  nginxConfig = pkgs.writeText "carapace-nginx.conf" ''
    pid /tmp/nginx.pid;
    error_log /dev/stderr;
    events { worker_connections 1024; }
    http {
      include ${pkgs.nginx}/conf/mime.types;
      access_log /dev/stdout;
      client_body_temp_path /tmp/client_body;
      proxy_temp_path /tmp/proxy;
      fastcgi_temp_path /tmp/fastcgi;
      uwsgi_temp_path /tmp/uwsgi;
      scgi_temp_path /tmp/scgi;
      include ${frontendRoutes};
    }
  '';
  shell = pkgs.runCommand "carapace-bitwarden-shell" { } ''
    mkdir -p "$out/bin"
    ln -s ${pkgs.dash}/bin/dash "$out/bin/sh"
  '';
in
{
  server-image = image "carapace" [ server pkgs.gitMinimal pkgs.cacert ] {
    Cmd = [ "${server}/bin/carapace-server" ];
    Env = tlsEnv ++ [
      "PATH=${
        pkgs.lib.makeBinPath [
          server
          pkgs.gitMinimal
        ]
      }"
      "CARAPACE_DATA_DIR=/var/lib/carapace"
      "TIKTOKEN_CACHE_DIR=${tokenizerCache}"
      "PYTHONDONTWRITEBYTECODE=1"
      "PYTHONUNBUFFERED=1"
    ];
    ExposedPorts = {
      "8321/tcp" = { };
      "8322/tcp" = { };
      "3128/tcp" = { };
    };
  };
  frontend-image = image "carapace-frontend" [ pkgs.nginx frontend ] {
    Cmd = [
      "${pkgs.nginx}/bin/nginx"
      "-e"
      "/dev/stderr"
      "-c"
      "${nginxConfig}"
      "-g"
      "daemon off;"
    ];
    ExposedPorts."8080/tcp" = { };
  };
  bitwarden-image =
    image "carapace-bitwarden-cli"
      [
        pkgs.bitwarden-cli
        shell
        pkgs.coreutils
        pkgs.gnused
        pkgs.curl
        pkgs.cacert
      ]
      {
        Cmd = [
          "${shell}/bin/sh"
          "${../bitwarden-cli/entrypoint.sh}"
        ];
        Env = tlsEnv ++ [
          "PATH=${
            pkgs.lib.makeBinPath [
              pkgs.bitwarden-cli
              shell
              pkgs.coreutils
              pkgs.gnused
              pkgs.curl
            ]
          }"
          "NODE_EXTRA_CA_CERTS=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
        ];
        ExposedPorts."8087/tcp" = { };
      };
}
