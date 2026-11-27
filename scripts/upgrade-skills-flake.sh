#!/bin/sh
# Lists the skills of a knowledge repo in skills/flake.nix, for repos from before it existed.
# Run it from anywhere inside the repo; it stages its changes and leaves the commit to you.
# See docs/upgrading-to-skill-flakes.md ("The skills flake").
#
# - A bundled skill that Carapace now ships from its main branch, and that only bootstrap ever
#   touched, becomes an input on carapace and its copy is removed. A copy you changed stays local.
# - carapace, web and ferret kept their configuration in their flake.nix: the script moves it into
#   skills/config.json (settings and credential bindings) and turns the skill on when it is complete.
#   A copy changed only there becomes an input; one with other changes stays local, and the script
#   says what its flake needs.
# - Every other skill directory with a SKILL.md becomes a `path:` input. One without a flake.nix
#   gets a flake of a few lines; a flake whose mkSkill has no `src` gets `src = ./.;`.
# - A skill whose SKILL.md still sets `disabled: true` is written as a commented-out input.
# - Every input follows the repo's nixpkgs and carapace. Then `nix flake lock` writes skills/flake.lock.
set -eu

# Bundled with Carapace and taken from its main branch (src/carapace/assets/skills/flake.nix).
FROM_CARAPACE="artifacts create-skill credentials mermaid wikipedia"
# Bundled too, with this instance's configuration in skills/config.json.
CONFIGURED="carapace ferret web"
BOOTSTRAP_SUBJECT="🔧 bootstrap: seed default files"
CARAPACE_URL="github:thiesgerken/carapace"

cd "$(git rev-parse --show-toplevel)/skills"
if [ -e flake.nix ] || [ -e config.json ]; then
  echo "skills/flake.nix or skills/config.json exists already; nothing to do." >&2
  exit 1
fi
# The script stages what it changes, so nothing else may be pending there.
if [ -n "$(git status --porcelain -- .)" ]; then
  echo "skills/ has uncommitted changes; commit or stash them first." >&2
  exit 1
fi

# Only bootstrap commits touched the directory.
untouched() {
  ! git log --format=%s -- "$1" | grep -qvxF "$BOOTSTRAP_SUBJECT"
}

one_of() { # word list
  case " $2 " in *" $1 "*) return 0 ;; esac
  return 1
}

attribute() {
  case "$1" in
    # `carapace` is the helpers' input, so the bundled skill of that name is listed as carapace-cli.
    carapace) echo carapace-cli ;;
    nixpkgs | self)
      echo "skills/$1: rename the directory, $1 is reserved in skills/flake.nix" >&2
      exit 1
      ;;
    *)
      if ! printf '%s' "$1" | grep -Eq "^[A-Za-z_][A-Za-z0-9_'-]*$"; then
        echo "skills/$1: rename the directory to something a Nix attribute can be (letters, digits, - _ ')" >&2
        exit 1
      fi
      echo "$1"
      ;;
  esac
}

input() { # name url [prefix]
  printf '%s%s = {\n%s  url = "%s";\n%s  inputs.nixpkgs.follows = "nixpkgs";\n%s  inputs.carapace.follows = "carapace";\n%s};\n' \
    "${3:-}" "$1" "${3:-}" "$2" "${3:-}" "${3:-}" "${3:-}" | sed 's/^/    /'
}

mini_flake() { # name
  cat <<EOF
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    carapace = {
      url = "$CARAPACE_URL?dir=nix/skills";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    { nixpkgs, carapace, ... }:
    {
      packages = carapace.lib.forSkillSystems (system: {
        default = (carapace.lib.skill nixpkgs.legacyPackages.\${system}).mkSkill {
          name = "$1";
          src = ./.;
        };
      });
    };
}
EOF
}

# mkSkill takes the skill directory as `src` since the release that reads skills from their build. Only
# mkSkill's own arguments count (depth 1 of its braces), not a `src` of a package inside it.
add_src() { # flake.nix
  awk '
    function braces(line,  opened, closed) {
      opened = gsub(/\{/, "{", line); closed = gsub(/\}/, "}", line); return opened - closed
    }
    function flush(  i) {
      for (i = 0; i < n; i++) {
        print block[i]
        if (!has_src && i == name_at) { match(block[i], /^[[:space:]]*/); print substr(block[i], 1, RLENGTH) "src = ./.;" }
      }
      if (!has_src && name_at < 0) print FILENAME ": add src = ./.; to mkSkill by hand" > "/dev/stderr"
      inside = 0
    }
    inside {
      block[n++] = $0
      if (depth == 1 && $0 ~ /^[[:space:]]*src[[:space:]]*=/) has_src = 1
      if (depth == 1 && $0 ~ /^[[:space:]]*name[[:space:]]*=/ && name_at < 0) name_at = n - 1
      depth += braces($0)
      if (depth <= 0) flush()
      next
    }
    /mkSkill[[:space:]]*\{/ { print; inside = 1; depth = braces($0); n = 0; has_src = 0; name_at = -1; next }
    { print }
  ' "$1" > "$1.new"
  mv "$1.new" "$1"
}

# Lines of SKILL.md that only switch a bundled skill on or off, which the release shipped and you may
# have changed to turn it on.
strip_switch() {
  grep -Ev '^[[:space:]]*(disabled:.*|metadata:|carapace:)[[:space:]]*$|^# Before enabling' || true
}

# Whether a bundled copy changed only in its configuration since bootstrap added it: its flake.nix and
# lock, and the lines that turn it on.
config_only() { # dir
  base=$(git log --diff-filter=A --format=%H -- "$1" | tail -n 1)
  [ -n "$base" ] || return 1
  [ -z "$(git diff --name-only "$base" HEAD -- "$1" ":(exclude)$1/flake.nix" ":(exclude)$1/flake.lock" ":(exclude)$1/SKILL.md")" ] || return 1
  [ "$(git show "$base:./$1/SKILL.md" | strip_switch)" = "$(strip_switch < "$1/SKILL.md")" ]
}

# The value of `<name> = "<value>";` in a flake, as the release's bundled flakes wrote their configuration.
literal() { # file name-pattern
  sed -n "s/^[[:space:]]*$2 = \"\([^\"]*\)\";.*/\1/p" "$1" | head -n 1
}

# A value worth carrying over: no placeholder from the release, nothing JSON would need escaped.
usable() {
  printf '%s' "$1" | grep -Eq '^[A-Za-z0-9._:/@+=-]+$' && ! printf '%s' "$1" | grep -Eq '\.example\.(com|invalid)'
}

entry() { # json-name [json-value-or-empty]
  [ -z "${2:-}" ] || printf '"%s": "%s"' "$1" "$2"
}

# The config.json entry of a bundled skill from its copy, and whether it is complete enough to turn on.
configure() { # dir attr
  case "$1" in
    carapace)
      setting=$(entry CARAPACE_HOST "$(value "$1/flake.nix" server)")
      credential=$(entry CARAPACE_API_KEY "$(value "$1/flake.nix" apiKey)")
      ;;
    web)
      setting=""
      credential=$(entry BRAVE_API_KEY "$(value "$1/flake.nix" 'credentials\.BRAVE_API_KEY')")
      ;;
    ferret)
      setting=$(entry FERRET_URL "$(value "$1/flake.nix" url)")
      credential=$(entry FERRET_API_KEY "$(value "$1/flake.nix" bearer)")
      ;;
  esac
  enable=true
  if [ -z "$credential" ] || { [ "$1" != web ] && [ -z "$setting" ]; }; then
    enable=false
    echo "skills/$1: not configured yet; set its values in skills/config.json and remove \"enable\": false (see its SKILL.md)"
  elif grep -Eq '^[[:space:]]+disabled:[[:space:]]*true[[:space:]]*(#.*)?$' "$1/SKILL.md"; then
    enable=false
    echo "skills/$1: was disabled; its values are in skills/config.json, remove \"enable\": false there to turn it on"
  fi
  config="$config  \"$2\": {"
  [ -z "$credential" ] || config="$config\"credentials\": {$credential}, "
  config="$config\"enable\": $enable"
  [ -z "$setting" ] || config="$config, \"settings\": {$setting}"
  config="$config},
"
}

value() { # file name-pattern
  found=$(literal "$1" "$2")
  if usable "$found"; then printf '%s' "$found"; fi
}

# Every skill that stays in the repo needs an attribute name; check them all before changing anything.
for dir in */; do
  name=${dir%/}
  [ -f "$name/SKILL.md" ] || continue
  one_of "$name" "$FROM_CARAPACE" && untouched "$name" && continue
  attribute "$name" > /dev/null
done

external=""
local=""
off=""
config=""
for dir in */; do
  name=${dir%/}
  [ -f "$name/SKILL.md" ] || continue
  if one_of "$name" "$CONFIGURED"; then
    attr=$(attribute "$name")
    configure "$name" "$attr"
    if config_only "$name"; then
      git rm -rq -- "$name"
      external="$external$(input "$attr" "$CARAPACE_URL?dir=src/carapace/assets/skills/$name")
"
      echo "skills/$name: bundled copy, now an input on carapace; its configuration is in skills/config.json"
    else
      add_src "$name/flake.nix"
      local="$local$(input "$attr" "path:./$name")
"
      echo "skills/$name: you changed more than its configuration, so it stays a local skill. Its flake.nix must"
      echo "  declare its settings and credential slots instead of literal values, as the bundled one does:"
      echo "  https://github.com/thiesgerken/carapace/blob/main/src/carapace/assets/skills/$name/flake.nix"
      echo "  The values are already in skills/config.json."
    fi
    continue
  fi
  if one_of "$name" "$FROM_CARAPACE" && untouched "$name"; then
    git rm -rq -- "$name"
    external="$external$(input "$name" "$CARAPACE_URL?dir=src/carapace/assets/skills/$name")
"
    echo "skills/$name: unchanged bundled copy, now an input on carapace"
    continue
  fi
  attr=$(attribute "$name")
  if [ -f "$name/flake.nix" ]; then
    add_src "$name/flake.nix"
  else
    mini_flake "$attr" > "$name/flake.nix"
    echo "skills/$name: wrote a flake for a skill with only instructions"
  fi
  if grep -Eq '^[[:space:]]+disabled:[[:space:]]*true[[:space:]]*(#.*)?$' "$name/SKILL.md"; then
    off="$off$(input "$attr" "path:./$name" "# ")
"
    echo "skills/$name: disabled, listed commented out; delete \`disabled\` from its SKILL.md before listing it"
  else
    local="$local$(input "$attr" "path:./$name")
"
  fi
done

{
  cat <<EOF
{
  # The skills of this knowledge repo: every input except nixpkgs and carapace is one, named by its
  # attribute. See docs/skill-flakes.md in the Carapace repo.
  description = "Carapace skills";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    carapace = {
      url = "$CARAPACE_URL?dir=nix/skills";
      inputs.nixpkgs.follows = "nixpkgs";
    };
EOF
  [ -z "$external" ] || printf '\n    # Bundled with Carapace and taken from its main branch.\n%s' "$external"
  [ -z "$local" ] || printf '\n    # The skills in this repo.\n%s' "$local"
  # shellcheck disable=SC2016 # the backticks are text for the reader
  [ -z "$off" ] || printf '\n    # Turned off: uncomment one and run `nix flake lock ./skills` to list it.\n%s' "$off"
  cat <<'EOF'
  };

  # Every input but nixpkgs and carapace is a skill; config.json holds the values of their settings.
  outputs =
    { carapace, ... }@inputs:
    carapace.lib.skillsFlake {
      inherit inputs;
      config = ./config.json;
    };
}
EOF
} > flake.nix
# The entries end in a comma each; JSON wants none after the last.
printf '{\n%s}\n' "$(printf '%s' "$config" | sed '$ s/,$//')
" > config.json

# A flake in a Git repo sees only tracked files. skills/ was clean, so this stages only what the script wrote.
git add -A .
cd ..
nix flake lock ./skills
git add skills/flake.lock
echo "Done. Review \`git diff --cached\`, then commit and push."
