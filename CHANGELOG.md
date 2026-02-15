# CHANGELOG


## v0.2.0 (2026-02-15)

### Other

- 📝 Update README.md to include new security guideline for skills
  ([`83d90b1`](https://github.com/thiesgerken/carapace/commit/83d90b1f343811cdb8ffb278470680e3d8da4225))

- Added a section emphasizing the importance of reviewing skills before installation, highlighting
  that skills are considered trusted code and the user's responsibility in managing them.

### ✨

- ✨ Integrate Logfire for enhanced logging and tracing
  ([`7c1ddeb`](https://github.com/thiesgerken/carapace/commit/7c1ddeb0cb5787fa0ff3f6883c3a9b2a2c0c1008))

- Added `logfire` dependency to `pyproject.toml` and `uv.lock`. - Configured Logfire in the CLI to
  enable tracing based on user token. - Updated `CarapaceConfig` to include `logfire_token` field. -
  Modified example `config.yaml` to indicate where to set the Logfire token.


## v0.1.0 (2026-02-15)

### Other

- Fix url in readme
  ([`f2ece16`](https://github.com/thiesgerken/carapace/commit/f2ece16e3f29036c1b85d95b2c3fa39ab88fc564))

- Merge remote-tracking branch 'refs/remotes/origin/main'
  ([`85552db`](https://github.com/thiesgerken/carapace/commit/85552db18aa94bd696bc879fefca3801aecc3f34))

- Update readme
  ([`2f1daa1`](https://github.com/thiesgerken/carapace/commit/2f1daa15813b60241506afde11931881fd7d1e66))

- 💚 Fix CI: add pytest dev dep and gitmoji PR title check
  ([#2](https://github.com/thiesgerken/carapace/pull/2),
  [`7e0ba76`](https://github.com/thiesgerken/carapace/commit/7e0ba766fd6b13f7c68b191236fce903c06bb48f))

* 💚 Fix CI: add pytest dev dep and gitmoji PR title check

- Add pytest to dependency-groups so `uv sync --dev` installs it - Add pr-title job to enforce
  gitmoji prefix on PR titles

Co-authored-by: Cursor <cursoragent@cursor.com>

* 💚 Disable color in CLI test runner to fix CI assertions

* 💚 Use NO_COLOR env var instead of color kwarg in test runner

* 💚 Strip ANSI escape codes in CLI test assertions

---------

- 📝 Add AGENTS.md for project overview, setup, code style, structure, testing, and CI details
  ([`b79fbbb`](https://github.com/thiesgerken/carapace/commit/b79fbbba67733067727b8e7c4a539b06fe8b3184))

- 📝 Add MIT LICENSE file ([#3](https://github.com/thiesgerken/carapace/pull/3),
  [`1226e36`](https://github.com/thiesgerken/carapace/commit/1226e3622ac8a65335b3eb16367104af3cdfa7a2))

Co-authored-by: Cursor Agent <cursoragent@cursor.com>

- 📝 Add Python coding style guide for carapace project
  ([`8f91cf2`](https://github.com/thiesgerken/carapace/commit/8f91cf2e2b65f36a1e277533d6cba3cf5470ade0))

- 📝 Enrich README with getting started guide and demo output
  ([#1](https://github.com/thiesgerken/carapace/pull/1),
  [`593d395`](https://github.com/thiesgerken/carapace/commit/593d3952b870e44ebd94f5f376ca2cb31b5b5318))

* 📝 Enrich README with getting started guide and demo output

Add installation, running, and configuration instructions. Include a pruned demo session showcasing
  the interactive CLI.

Co-authored-by: Cursor <cursoragent@cursor.com>

* tired of that

---------

### ✨

- ✨ Add bootstrap module and initial asset files for Carapace
  ([#28](https://github.com/thiesgerken/carapace/pull/28),
  [`655e154`](https://github.com/thiesgerken/carapace/commit/655e154612384688fa5c25d6c20600de78ec1bd4))

- Introduced `bootstrap.py` to ensure the creation of critical files and directories. - Added asset
  files including `config.yaml`, `CORE.md`, `SOUL.md`, `USER.md`, and rules in `rules.yaml`. -
  Implemented functionality to seed skills and manage data directory initialization in the CLI.

- ✨ Implement message replay functionality in chat session
  ([`dfe883b`](https://github.com/thiesgerken/carapace/commit/dfe883bfaededd25087aa887a282114b3b2dcda7))

- Added `_replay_history` function to display previous conversation turns. - Introduced `--prev`
  option in the `chat` command to specify the number of previous turns to replay. - Updated response
  validation logic for improved readability.

- ✨ Update commit parser options in pyproject.toml
  ([`632eaf4`](https://github.com/thiesgerken/carapace/commit/632eaf494bc4a6a29472427323cd38efdcda368e))

- Added major, minor, and patch tags for semantic release. - Enhanced commit parsing configuration
  to support emoji and text tags.


## v0.0.0 (2026-02-14)

### Other

- Add ci
  ([`dd57de9`](https://github.com/thiesgerken/carapace/commit/dd57de9d6a1be3ba413bd8c20ed12d45fb5032e4))

- Add docs and brainstorming
  ([`54eacb2`](https://github.com/thiesgerken/carapace/commit/54eacb2091b136948e35bdd3ae7e3d305a4a1330))

- Add tests, add precommit, fix lints
  ([`3adb428`](https://github.com/thiesgerken/carapace/commit/3adb4283ae1ec76dc69a4df62bddd7db9a36985d))

- Let opus code a PoC
  ([`7e2f876`](https://github.com/thiesgerken/carapace/commit/7e2f876aa755be5176601f7a5fa217cca59f0694))

- Update build command in pyproject.toml to install uv before building
  ([`b67255c`](https://github.com/thiesgerken/carapace/commit/b67255ca8a177da256fcbcfaf40b1d84be8dafa8))
