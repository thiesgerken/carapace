#!/bin/sh
# Lists the skills of a knowledge repo in skills/flake.nix, for repos from before it existed.
# Run it from anywhere inside the repo; it stages its changes and leaves the commit to you.
# See docs/upgrading-to-skill-flakes.md ("The skills flake").
#
# - A bundled skill that Carapace now ships from its main branch, and that only bootstrap ever
#   touched, becomes an input on carapace and its copy is removed. A copy you changed stays local.
# - Every other skill directory with a SKILL.md becomes a `path:` input. One without a flake.nix
#   gets a flake of a few lines; a flake whose mkSkill has no `src` gets `src = ./.;`.
# - A skill whose SKILL.md still sets `disabled: true` is written as a commented-out input.
# - Every input follows the repo's nixpkgs and carapace. Then `nix flake lock` writes skills/flake.lock.
set -eu

# Bundled with Carapace and taken from its main branch (src/carapace/assets/skills/flake.nix).
FROM_CARAPACE="artifacts create-skill credentials mermaid wikipedia"
BOOTSTRAP_SUBJECT="🔧 bootstrap: seed default files"
CARAPACE_URL="github:thiesgerken/carapace"

cd "$(git rev-parse --show-toplevel)/skills"
if [ -e flake.nix ]; then
  echo "skills/flake.nix exists already; nothing to do." >&2
  exit 1
fi

# Only bootstrap commits touched the directory, and nothing in it is uncommitted.
untouched() {
  [ -z "$(git status --porcelain -- "$1")" ] || return 1
  ! git log --format=%s -- "$1" | grep -qvxF "$BOOTSTRAP_SUBJECT"
}

from_carapace() {
  case " $FROM_CARAPACE " in *" $1 "*) return 0 ;; esac
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

# mkSkill takes the skill directory as `src` since the release that reads skills from their build.
add_src() { # flake.nix
  grep -q 'mkSkill' "$1" && ! grep -Eq '^[[:space:]]*src = ' "$1" || return 0
  awk '
    { print }
    pending && /^[[:space:]]*name = / { match($0, /^[[:space:]]*/); print substr($0, 1, RLENGTH) "src = ./.;"; pending = 0 }
    /mkSkill[[:space:]]*\{/ { pending = 1 }
  ' "$1" > "$1.new"
  mv "$1.new" "$1"
  grep -Eq '^[[:space:]]*src = ' "$1" || echo "$1: add src = ./.; to mkSkill by hand" >&2
}

external=""
local=""
off=""
for dir in */; do
  name=${dir%/}
  [ -f "$name/SKILL.md" ] || continue
  if from_carapace "$name" && untouched "$name"; then
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
  if grep -Eq '^[[:space:]]+disabled:[[:space:]]*true[[:space:]]*$' "$name/SKILL.md"; then
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

  outputs =
    { carapace, ... }@inputs:
    let
      skills = removeAttrs inputs [
        "self"
        "nixpkgs"
        "carapace"
      ];
    in
    {
      packages = carapace.lib.forSkillSystems (
        system: builtins.mapAttrs (_name: skill: skill.packages.${system}.default) skills
      );
    };
}
EOF
} > flake.nix

# A flake in a Git repo sees only tracked files.
git add -A .
cd ..
nix flake lock ./skills
git add skills/flake.lock
echo "Done. Review \`git diff --cached\`, then commit and push."
