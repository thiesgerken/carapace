"""What the sandbox's skill profile should hold: the built skills, minus those whose command names collide."""

from __future__ import annotations

import hashlib
import re
import shlex
from dataclasses import dataclass

from .skill_builds import SkillBuild

# In the container layer: ephemeral like the store it points into, and separate from the agent's own profile.
# The sandbox image creates its directory and puts its `bin` on PATH (nix/sandbox.nix).
SKILLS_PROFILE = "/nix/var/nix/profiles/carapace/skills"
# The digest of the path set the profile was last set to, written only after `nix-env` succeeded.
SKILLS_PROFILE_MARKER = "/nix/var/nix/profiles/carapace/skills.wanted"
# By absolute path: the agent can write to directories on PATH and plant a `nix-env` there.
_NIX_ENV = "/bin/nix-env"
# Nix base32 leaves out e, o, t and u.
_STORE_PATH = re.compile(r"/nix/store/[0-9a-df-np-sv-z]{32}-[^/\s]+")


@dataclass(frozen=True, slots=True)
class ProfilePlan:
    store_paths: tuple[str, ...]
    # Skill name -> why its commands are not on PATH.
    excluded: dict[str, str]

    @property
    def digest(self) -> str:
        return hashlib.sha256("\n".join(self.store_paths).encode()).hexdigest()


def profile_plan(builds: list[SkillBuild]) -> ProfilePlan:
    """Every succeeded skill's store paths, except skills that share a command name with another.

    Nix refuses to install two packages with the same file, and the whole transaction fails, so both
    skills of a collision stay out rather than letting one of them win by accident.
    """
    built = [build for build in builds if build.state == "succeeded"]
    providers: dict[str, list[str]] = {}
    for build in built:
        for command in build.commands:
            providers.setdefault(command, []).append(build.skill)
    excluded: dict[str, str] = {}
    for command, skills in sorted(providers.items()):
        if len(skills) > 1:
            for skill in skills:
                others = ", ".join(other for other in skills if other != skill)
                excluded.setdefault(skill, f"its command {command!r} is also a command of {others}")
    paths = sorted({path for build in built if build.skill not in excluded for path in build.store_paths})
    # They end up on the `nix-env` command line: a leading `-` would be an option, not a path.
    if invalid := [path for path in paths if not _STORE_PATH.fullmatch(path)]:
        raise ValueError(f"The builder reported paths that are not store paths: {invalid}")
    return ProfilePlan(store_paths=tuple(paths), excluded=excluded)


def sync_script(plan: ProfilePlan) -> str:
    """Set the profile to exactly the plan's paths in one transaction, then record what it holds.

    `nix-env -i -r` installs by store path (no evaluation, missing paths are substituted) and removes
    everything else; it is a no-op when nothing changed. An empty plan empties the profile.
    """
    profile, marker = shlex.quote(SKILLS_PROFILE), shlex.quote(SKILLS_PROFILE_MARKER)
    change = (
        f"{_NIX_ENV} -p {profile} -i -r {' '.join(map(shlex.quote, plan.store_paths))}"
        if plan.store_paths
        else f"{_NIX_ENV} -p {profile} -e '.*'"
    )
    return f"set -e\n{change}\nprintf %s {plan.digest} > {marker}\n"
