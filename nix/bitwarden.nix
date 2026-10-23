{ pkgs }:
let
  fullNodejs = pkgs.bitwarden-cli.nodejs;
  nodejs = pkgs."nodejs-slim_${pkgs.lib.versions.major fullNodejs.version}";
in
pkgs.stdenvNoCC.mkDerivation {
  pname = "carapace-bitwarden-cli";
  inherit (pkgs.bitwarden-cli) version;
  dontUnpack = true;
  nativeBuildInputs = [
    nodejs
    pkgs.makeBinaryWrapper
  ];
  installPhase = ''
    runHook preInstall
    node ${./prune-bitwarden.mjs} \
      ${pkgs.bitwarden-cli}/lib/node_modules/@bitwarden/clients \
      "$out/lib/node_modules/@bitwarden/clients" > "$TMPDIR/externals.json"
    mkdir -p "$out/bin"
    makeWrapper ${nodejs}/bin/node "$out/bin/bw" \
      --add-flags "$out/lib/node_modules/@bitwarden/clients/build/bw.js"
    runHook postInstall
  '';
  postFixup = ''
    # Inherited shebangs otherwise retain the npm-enabled interpreter.
    patchShebangs --build --update "$out"
  '';
  disallowedRequisites = [
    pkgs.bitwarden-cli
    fullNodejs
    nodejs.npm
  ];
  doInstallCheck = true;
  installCheckPhase = ''
    runHook preInstallCheck
    node --input-type=module - "$out/lib/node_modules/@bitwarden/clients/build/bw.js" "$TMPDIR/externals.json" <<'JS'
    import { readFileSync } from "node:fs";
    import { createRequire } from "node:module";
    const require = createRequire(process.argv[2]);
    for (const external of JSON.parse(readFileSync(process.argv[3], "utf8"))) require(external);
    JS
    runHook postInstallCheck
  '';
}
