# Ferret setup

Ferret is bundled and listed in `skills/flake.nix`, but the seeded
`skills/config.json` turns it off until it is configured there. This operator guide is not returned by `read_skill`.

## Manual opt-in

1. Note your deployment's HTTPS `/mcp` URL; step 5 sets it as the skill's
   `FERRET_URL` setting. The deployment must include Ferret MCP support and route that
   endpoint to Ferret.
2. Create a Ferret API key with only `search:read`. Optionally restrict it to
   the source roots the agent should read. Omit restrictions for all your
   sources; an explicit empty list is invalid. Do not grant `ingest:write`.
   Ferret uses API-key bearer auth, not OAuth or a browser session cookie.
3. Store the actual key in the vault and note its `<backend>/<id>` path. Never put
   the key in chat or the skill file.
4. Optionally, name your actual indexed sources in the skill's description, an
   always-visible coverage hint (`ferret list_sources` shows the sources the key
   may read). Override it in `skills/flake.nix`, which replaces the `X, Y, Z`
   placeholder without a copy of the skill:

   ```nix
   overrides.ferret = skill: skill.override (old: {
     description = builtins.replaceStrings [ "X, Y, Z (TODO: add specific sources here!)" ] [ "mail, notes and documents" ] old.description;
   });
   ```

5. In `skills/config.json`, replace ferret's `"enable": false` with
   `{"settings": {"FERRET_URL": "https://…/mcp"}, "credentials": {"FERRET_API_KEY": "<backend>/<id>"}}`,
   commit and push. The builder builds the skill, and a new session lists it in
   its catalog.

The `ferret` command runs the MCP bridge in the sandbox. Each time it starts it
asks for the endpoint's domain and the API key with `cgate`, and the sentinel
decides for that exec. `read_skill` lists the server's tools the same way. The
tools are `search`, `get_document` and `list_sources`.

## Discovery and lifecycle

The enabled skill directs the agent to search Ferret first for anything the
user may have stored, received, or discussed, unless the exact target or a
clearly better lookup path is known. Knowing the origin alone does not imply
its search is better. Ferret is personal indexed-source discovery, not public
metasearch or routine code navigation. Agents can answer from indexed text or
optionally follow origin links with source-specific skills for freshness or
actions.

Being listed in `skills/flake.nix` and on in `skills/config.json` controls the
catalog and builds. A session that is already running keeps the catalog it
started with.
