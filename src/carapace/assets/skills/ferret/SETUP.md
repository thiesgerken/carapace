# Ferret setup

Ferret is bundled **disabled by default**. Configure your copied `SKILL.md` in
this directory before enabling it. This operator guide is not automatically
loaded by `use_skill`.

## Manual opt-in

1. Replace `https://ferret.example.invalid/mcp` with your deployment's HTTPS
   `/mcp` URL. The deployment must include Ferret MCP support and route that
   endpoint to Ferret.
2. Create a Ferret API key with only `search:read`. Optionally restrict it to
   the source roots the agent should read. Omit restrictions for all your
   sources; an explicit empty list is invalid. Do not grant `ingest:write`.
   Ferret uses API-key bearer auth, not OAuth or a browser session cookie.
3. Store the actual key in the vault and point `auth.vault_path` at that entry
   (the bundled reference is `vault/ferret-api-key`). Never put the key in chat
   or the skill file.
4. Replace the `X, Y, Z` source placeholder in the frontmatter `description`
   with your actual indexed sources. The description is an always-visible
   coverage hint; `ferret_list_sources` provides the current sources authorized
   for the key after activation.
5. Set `metadata.carapace.disabled: false` and start a new session.

The native MCP connection is made by the backend. No sandbox network grants,
credential injection, scripts, or additional dependencies are needed. The tools
are `ferret_search`, `ferret_get_document`, and `ferret_list_sources`.

## Discovery and lifecycle

The enabled skill directs the agent to search Ferret first for anything the
user may have stored, received, or discussed, unless the exact target or a
clearly better lookup path is known. Knowing the origin alone does not imply
its search is better. Ferret is personal indexed-source discovery, not public
metasearch or routine code navigation. Agents can answer from indexed text or
optionally follow origin links with source-specific skills for freshness or
actions.

The disabled flag controls discovery and future activation, not revocation of
existing activations, grants, or tools, including in resumed sessions.

Normal bootstrap seeds missing bundled skill directories and preserves existing
directories and user edits. Explicit `reset-assets` overwrites bundled
customization, including Ferret's endpoint, vault reference, source description,
and disabled flag.
