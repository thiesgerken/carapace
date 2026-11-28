#!/bin/sh
# Lists the skills of a knowledge repo in skills/flake.nix, for repos from before it existed, and moves
# the SKILL.md frontmatter of its local skills into their flakes. Run it from anywhere inside the repo; it
# stages its changes and leaves the commit to you. See docs/upgrading-to-skill-flakes.md.
#
# With a skills/flake.nix already there, it only moves the frontmatter: each local skill's description
# goes into its mkSkill and SKILL.md keeps the instructions. Then it updates carapace and the bundled
# skills in skills/flake.lock, whose new versions expect exactly that.
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
# The script stages what it changes, so nothing else may be pending there.
if [ -n "$(git status --porcelain -- .)" ]; then
  echo "skills/ has uncommitted changes; commit or stash them first." >&2
  exit 1
fi

# The last bootstrap commit that wrote into the directory: the seed, or a later reset-assets.
seeded_at() { # dir
  git log --format='%H%x09%s' -- "$1" | awk -F '\t' -v subject="$BOOTSTRAP_SUBJECT" '$2 == subject { print $1; exit }'
}

# Nothing changed in the directory since bootstrap last wrote it.
untouched() { # dir
  base=$(seeded_at "$1")
  [ -n "$base" ] && git diff --quiet "$base" HEAD -- "$1"
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

# Whether SKILL.md starts with YAML frontmatter, which mkSkill refuses.
has_frontmatter() { # SKILL.md
  [ "$(head -n 1 "$1")" = "---" ]
}

# A top-level key of the frontmatter as a Nix string literal: a plain or quoted value, or a folded (>) or
# literal (|) block. Empty when the key is missing.
frontmatter_value() { # SKILL.md key
  awk -v key="$2" '
    function nix(value) {
      gsub(/\\/, "\\\\", value); gsub(/"/, "\\\"", value); gsub(/\$\{/, "\\${", value); gsub(/\n/, "\\n", value)
      return "\"" value "\""
    }
    NR == 1 { next }
    /^---[[:space:]]*$/ { exit }
    block {
      if ($0 != "" && $0 !~ /^[[:space:]]/) exit
      sub(/^[[:space:]]+/, "")
      value = value (value == "" ? "" : separator) $0
      next
    }
    index($0, key ":") == 1 {
      value = substr($0, length(key) + 2)
      sub(/^[[:space:]]+/, "", value)
      sub(/[[:space:]]+$/, "", value)
      if (value ~ /^[>|][-+]?$/) { separator = value ~ /^>/ ? " " : "\n"; value = ""; block = 1; next }
      if (value ~ /^".*"$/ || value ~ /^\047.*\047$/) value = substr(value, 2, length(value) - 2)
      print nix(value)
      done = 1
      exit
    }
    END { if (block && !done) { sub(/[[:space:]]+$/, "", value); print nix(value) } }
  ' "$1"
}

# The other top-level keys of the frontmatter, which have no place in the flake.
frontmatter_rest() { # SKILL.md
  awk 'NR == 1 { next } /^---[[:space:]]*$/ { exit } /^[A-Za-z_][A-Za-z0-9_-]*:/ { sub(/:.*/, ""); if ($0 != "name" && $0 != "description") print }' "$1" | tr '\n' ' '
}

strip_frontmatter() { # SKILL.md
  awk 'NR == 1 { inside = 1; next } inside { if ($0 ~ /^---[[:space:]]*$/) { inside = 0; leading = 1 } next } leading && /^[[:space:]]*$/ { next } { leading = 0; print }' "$1" > "$1.new"
  mv "$1.new" "$1"
}

# Moves the description from SKILL.md's frontmatter into the skill's mkSkill and strips the frontmatter.
move_frontmatter() { # dir
  has_frontmatter "$1/SKILL.md" || return 0
  description=$(frontmatter_value "$1/SKILL.md" description)
  if [ -z "$description" ]; then
    echo "skills/$1: its SKILL.md frontmatter has no description; add description = \"…\"; to its mkSkill by hand" >&2
    description='"TODO: describe the skill"'
  fi
  if ! MKSKILL_ARG="description = $description;" add_arg "$1/flake.nix" description; then
    echo "skills/$1: move the frontmatter description into mkSkill by hand; SKILL.md keeps its frontmatter until then" >&2
    return 0
  fi
  rest=$(frontmatter_rest "$1/SKILL.md")
  strip_frontmatter "$1/SKILL.md"
  [ -z "$rest" ] || echo "skills/$1: dropped frontmatter keys without a place in the flake: $rest"
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

# Adds the line $MKSKILL_ARG after mkSkill's `name` unless mkSkill sets <key> already. Only mkSkill's own
# arguments count (depth 1 of its braces), not a `src` of a package inside it. Fails when the flake has no
# `mkSkill {` it can read (`mkSkill rec {`, a brace on the next line) or that mkSkill has no `name` line.
add_arg() { # flake.nix key
  status=0
  awk -v key="$2" '
    function braces(line,  opened, closed) {
      opened = gsub(/\{/, "{", line); closed = gsub(/\}/, "}", line); return opened - closed
    }
    function flush(  i) {
      for (i = 0; i < n; i++) {
        print block[i]
        if (!has_key && i == name_at) { match(block[i], /^[[:space:]]*/); print substr(block[i], 1, RLENGTH) ENVIRON["MKSKILL_ARG"] }
      }
      if (has_key || name_at >= 0) set = 1
      inside = 0
    }
    inside {
      block[n++] = $0
      if (depth == 1 && $0 ~ "^[[:space:]]*" key "[[:space:]]*=") has_key = 1
      if (depth == 1 && $0 ~ /^[[:space:]]*name[[:space:]]*=/ && name_at < 0) name_at = n - 1
      depth += braces($0)
      if (depth <= 0) flush()
      next
    }
    /mkSkill[[:space:]]*\{/ { print; inside = 1; depth = braces($0); n = 0; has_key = 0; name_at = -1; next }
    { print }
    END { exit !set }
  ' "$1" > "$1.new" || status=$?
  mv "$1.new" "$1"
  return "$status"
}

# mkSkill takes the skill directory as `src` since the release that reads skills from their build.
add_src() { # flake.nix
  MKSKILL_ARG="src = ./.;" add_arg "$1" src || echo "$1: add src = ./.; to mkSkill by hand" >&2
}

# skills/flake.nix exists: only the frontmatter is left to move, then the helpers and bundled skills that
# expect it are updated.
if [ -e flake.nix ]; then
  for dir in */; do
    name=${dir%/}
    [ -f "$name/SKILL.md" ] && [ -f "$name/flake.nix" ] && move_frontmatter "$name"
  done
  git add -A .
  cd ..
  listed=$(nix eval --raw --impure --expr \
    'let lock = builtins.fromJSON (builtins.readFile ./skills/flake.lock); in toString (builtins.attrNames lock.nodes.${lock.root}.inputs)')
  bundled=""
  for attr in $FROM_CARAPACE carapace-cli ferret web; do
    one_of "$attr" "$listed" && bundled="$bundled $attr"
  done
  # shellcheck disable=SC2086 # one argument per input
  nix flake update --flake ./skills carapace $bundled
  git add skills/flake.lock
  echo "Done. Skills from other repos need the same move there (scripts/upgrade-skills-flake.sh in each)."
  echo "Review \`git diff --cached\`, then commit and push."
  exit 0
fi
if [ -e config.json ]; then
  echo "skills/config.json exists without skills/flake.nix; move it away first." >&2
  exit 1
fi

# Lines of SKILL.md that only switch a bundled skill on or off, which the release shipped and you may
# have changed to turn it on.
strip_switch() {
  grep -Ev '^[[:space:]]*(disabled:.*|metadata:|carapace:)[[:space:]]*$|^# Before enabling' || true
}

# Whether a bundled copy changed only in its configuration since bootstrap last wrote it: its flake.nix
# and lock, and the lines of SKILL.md that turn it on.
config_only() { # dir
  base=$(seeded_at "$1")
  [ -n "$base" ] || return 1
  [ -z "$(git diff --name-only "$base" HEAD -- "$1" ":(exclude)$1/flake.nix" ":(exclude)$1/flake.lock" ":(exclude)$1/SKILL.md")" ] || return 1
  [ "$(git show "$base:./$1/SKILL.md" | strip_switch)" = "$(strip_switch < "$1/SKILL.md")" ]
}

# One configuration value from a copy's flake.nix, a whole line `<name> = "<value>";` as the release wrote
# it, with a value starting with <prefix> (ferret's `url` is also the carapace input's attribute). Sets
# `found` and returns 0 for a value to carry over, 1 for the release's placeholder, 2 when the flake has
# no such line, several, or a value that is neither (reformatted, computed, or needing JSON escapes).
read_value() { # file name prefix placeholder
  matches=$(sed -n "s/^[[:space:]]*$2 = \"\($3[^\"]*\)\";[[:space:]]*$/\1/p" "$1")
  found=$matches
  [ -n "$matches" ] && [ "$(printf '%s\n' "$matches" | wc -l)" -eq 1 ] || return 2
  [ "$found" != "$4" ] || return 1
  printf '%s' "$found" | grep -Eq '^[A-Za-z0-9._:/@+=-]+$' || return 2
}

# Reads one value into the copy's config.json entry, or notes why it cannot.
carry() { # dir name prefix placeholder kind json-name
  if read_value "$1/flake.nix" "$2" "$3" "$4"; then
    pair="\"$6\": \"$found\""
    if [ "$5" = setting ]; then settings="$settings${settings:+, }$pair"; else credentials="$credentials${credentials:+, }$pair"; fi
  else
    case $? in
      1) missing="$missing $6" ;;
      *) unreadable="$unreadable $2" ;;
    esac
  fi
}

# The configuration of a bundled copy, read from its flake.nix: `settings` and `credentials` as JSON
# members, `missing` for values still at the release's placeholder, `unreadable` for lines not as shipped.
configure() { # dir
  settings=""
  credentials=""
  missing=""
  unreadable=""
  case "$1" in
    carapace)
      carry "$1" server "" carapace.example.com setting CARAPACE_HOST
      carry "$1" apiKey "" "<backend>/<your-carapace-api-key-id>" credential CARAPACE_API_KEY
      ;;
    web)
      carry "$1" 'credentials\.BRAVE_API_KEY' "" "" credential BRAVE_API_KEY
      ;;
    ferret)
      carry "$1" url "https:\/\/" https://ferret.example.invalid/mcp setting FERRET_URL
      carry "$1" bearer "" "" credential FERRET_API_KEY
      ;;
  esac
}

# The config.json entry for a bundled skill: its values, on when they are complete and it was not disabled.
entry() { # dir attr
  enable=true
  if [ -n "$missing" ]; then
    enable=false
    echo "skills/$1: not configured yet (missing:$missing); set it in skills/config.json and remove \"enable\": false"
  elif grep -Eq '^[[:space:]]+disabled:[[:space:]]*true[[:space:]]*(#.*)?$' "$1/SKILL.md"; then
    enable=false
    echo "skills/$1: was disabled; remove \"enable\": false in skills/config.json to turn it on"
  fi
  members=""
  [ -z "$credentials" ] || members="\"credentials\": {$credentials}, "
  members="$members\"enable\": $enable"
  [ -z "$settings" ] || members="$members, \"settings\": {$settings}"
  config="$config  \"$2\": {$members},
"
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
    bundled="$CARAPACE_URL?dir=src/carapace/assets/skills/$name"
    if [ ! -f "$name/flake.nix" ]; then
      # From before skill flakes, broken either way: the input replaces it, configured by hand.
      git rm -rq -- "$name"
      external="$external$(input "$attr" "$bundled")
"
      config="$config  \"$attr\": {\"enable\": false},
"
      echo "skills/$name: copy from before skill flakes, now an input on carapace; set it up in skills/config.json"
      continue
    fi
    configure "$name"
    if [ -z "$unreadable" ] && config_only "$name"; then
      # Before the removal: it reads the copy's SKILL.md.
      entry "$name" "$attr"
      git rm -rq -- "$name"
      external="$external$(input "$attr" "$bundled")
"
      echo "skills/$name: bundled copy, now an input on carapace; its configuration is in skills/config.json"
      continue
    fi
    # Its flake does not declare the settings and slots yet, and config.json may only set declared ones.
    add_src "$name/flake.nix"
    move_frontmatter "$name"
    local="$local$(input "$attr" "path:./$name")
"
    config="$config  \"$attr\": {\"enable\": false},
"
    if [ -n "$unreadable" ]; then
      echo "skills/$name: stays a local skill, because its flake.nix does not have these lines as shipped:$unreadable."
    else
      echo "skills/$name: stays a local skill, because you changed more than its configuration."
    fi
    echo "  Declare its settings and credential slots in its flake.nix as the bundled one does,"
    echo "  https://github.com/thiesgerken/carapace/blob/main/src/carapace/assets/skills/$name/flake.nix,"
    echo "  then replace its entry in skills/config.json with:"
    members=""
    [ -z "$credentials" ] || members="\"credentials\": {$credentials}, "
    echo "  \"$attr\": {$members\"settings\": {$settings}}"
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
    echo "skills/$name: disabled, listed commented out"
    move_frontmatter "$name"
  else
    move_frontmatter "$name"
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
