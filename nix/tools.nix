{ pkgs }:
let
  nodejs = pkgs.nodejs_24;
in
{
  inherit nodejs;
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
}
