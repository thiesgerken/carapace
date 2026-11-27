# Ferret setup

Ferret is bundled but not listed in `skills/flake.nix`, so it is off by default.
Configure it in `skills/config.json` and its `SKILL.md` before listing
it. This operator guide is not returned by `read_skill`.

## Manual opt-in

1. Set the skill's `FERRET_URL` setting to your deployment's HTTPS `/mcp` URL
   in `skills/config.json`: `{"ferret": {"settings": {"FERRET_URL": "https://…/mcp"}}}`. The deployment must include Ferret MCP support and route that
   endpoint to Ferret.
2. Create a Ferret API key with only `search:read`. Optionally restrict it to
   the source roots the agent should read. Omit restrictions for all your
   sources; an explicit empty list is invalid. Do not grant `ingest:write`.
   Ferret uses API-key bearer auth, not OAuth or a browser session cookie.
3. Store the actual key in the vault and bind the skill's `FERRET_API_KEY` slot
   to that entry in `skills/config.json`:
   `{"ferret": {"credentials": {"FERRET_API_KEY": "<backend>/<id>"}}}`. Never put the
   key in chat or the skill file.
4. Replace the `X, Y, Z` source placeholder in the frontmatter `description`
   with your actual indexed sources. The description is an always-visible
   coverage hint; `ferret list_sources` shows the sources currently authorized
   for the key.
5. Uncomment the `ferret` input in `skills/flake.nix`, run `nix flake lock ./skills`,
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

Being listed in `skills/flake.nix` controls the catalog and builds. A session that
is already running keeps the catalog it started with.

Normal bootstrap seeds missing bundled skill directories and preserves existing
directories and user edits. Explicit `reset-assets` overwrites bundled
customization, including the source description. It never touches `skills/flake.nix`.
