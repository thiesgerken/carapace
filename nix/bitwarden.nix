{ pkgs }:
let
  nodejs = pkgs.nodejs-slim_22;
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
    cp ${./prune-bitwarden.mjs} prune-bitwarden.mjs
    cp ${./prune-bitwarden.test.mjs} prune-bitwarden.test.mjs
    node --test prune-bitwarden.test.mjs
    node ${./prune-bitwarden.mjs} \
      ${pkgs.bitwarden-cli}/lib/node_modules/@bitwarden/clients \
      "$out/lib/node_modules/@bitwarden/clients" > "$TMPDIR/externals.json"
    mkdir -p "$out/bin"
    makeWrapper ${nodejs}/bin/node "$out/bin/bw" \
      --add-flags "$out/lib/node_modules/@bitwarden/clients/build/bw.js"
    runHook postInstall
  '';
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
