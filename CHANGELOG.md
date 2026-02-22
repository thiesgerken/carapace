# CHANGELOG


## v0.6.0 (2026-02-22)

### ✨

- ✨ Docker sandboxing for sessions ([#35](https://github.com/thiesgerken/carapace/pull/35),
  [`ce5ca5b`](https://github.com/thiesgerken/carapace/commit/ce5ca5bcc4a7e94e89c5e09c01088e46dedc6e6c))

* ✨ Docker sandboxing for sessions

* ✨ Update logging guidelines in AGENTS.md and python-style.mdc

- Added a section on logging best practices, specifying the exclusive use of `loguru` over stdlib
  `logging`. - Included instructions for importing `loguru` and using f-strings in log calls for
  improved readability and performance.

* add loguru

* Refactor logging to use loguru across the codebase

- Replaced instances of the standard logging library with loguru for improved logging capabilities.
  - Updated log messages to utilize f-strings for better readability and performance. - Removed the
  `enabled` field from `SandboxConfig` as it is no longer needed. - Enhanced error handling and
  logging in the Docker runtime and sandbox manager for better debugging and maintenance.

* ✨ Enhance Docker runtime with network management

- Added a method to ensure the existence of Docker networks before container creation. - Improved
  the DockerRuntime class to manage and log network creation, enhancing the overall functionality of
  the sandbox environment.

* Fix input prompt formatting in approval request to escape brackets for proper display

* Refactor sandbox configuration and Docker integration

- Removed the carapace-sandbox-image service from docker-compose.yml and deleted its Dockerfile. -
  Updated SandboxConfig to allow an empty base_image, enabling auto-building from a bundled
  Dockerfile. - Introduced a method to read the bundled Dockerfile content in bootstrap.py. -
  Enhanced DockerRuntime with a build_image method to build the sandbox image from the bundled
  Dockerfile. - Adjusted server lifespan logic to build the sandbox image if no base_image is
  specified in the configuration.

* Enhance error handling and logging in sandbox and Docker runtime

- Introduced custom exceptions `ContainerGoneError` and `SkillVenvError` for better error management
  in the sandbox environment. - Updated the `DockerRuntime` and `SandboxManager` classes to handle
  these exceptions, improving robustness during container execution and skill virtual environment
  building. - Enhanced logging to provide clearer insights into errors and warnings related to
  container management and skill activation.

* Set logging levels for specific libraries to WARNING in server.py

- Adjusted logging configuration to set the logging level to WARNING for the "httpcore", "httpx",
  and "docker" libraries, improving log clarity and reducing verbosity.

* Enhance logging configuration in server.py

- Added "anthropic" and "websockets" to the list of libraries with WARNING logging level. -
  Introduced a custom emoji patcher for log records to replace specific prefixes with emojis,
  improving log readability.

* Update Python style guidelines in python-style.mdc

- Clarified the use of Pydantic `BaseModel` for structured data, removing references to stdlib
  `@dataclass`. - Introduced the use of `Annotated[type, Field(...)]` for field metadata and
  defaults, emphasizing correct usage. - Specified that non-nullable fields should not be assigned
  `None` with `# type: ignore`, promoting better type safety. - Updated guidance on avoiding mutable
  default arguments to use `Annotated` for consistency.

* Refactor agent and sandbox management for improved structure and logging

- Removed the local command execution fallback in favor of a more streamlined sandbox execution
  approach. - Enhanced the `Deps` class to utilize Pydantic's `BaseModel` and `Annotated` for better
  type safety and field management. - Updated the `SessionContainer` and `Mount` classes to inherit
  from `BaseModel`, ensuring consistent data handling. - Improved error handling in the agent's
  skill activation process with enhanced logging using `loguru`. - Adjusted server cleanup logic to
  ensure proper management of sandbox resources.

* Rename `bash` tool to `shell` in agent.py for clarity and update command execution in
  DockerRuntime to use `bash` instead of `sh` for consistency in command handling.

* Update Dockerfile to use specific version of uv and remove unnecessary apt-get commands

* Update default server host in ServerConfig to allow external access

* Improve WebSocket error handling in _chat_loop function

- Added reconnection logic for both sending messages and reading server responses upon
  ConnectionClosed exceptions. - Enhanced user feedback during reconnection attempts to improve user
  experience.

* Refactor WebSocket connection handling in cli.py

- Updated the WebSocket connection logic to use the `websockets.asyncio.client` module directly for
  improved clarity and consistency. - Enhanced type hinting for the `_connect_ws` function to
  specify the return type as `ClientConnection`.

* Refactor skill management in Deps class and server dependency building

- Updated the `Deps` class to initialize `skill_catalog` and `activated_skills` with default empty
  lists for improved clarity and consistency. - Modified the `_build_deps` function in `server.py`
  to pass an empty list for `activated_skills`, ensuring proper initialization during dependency
  construction.

* Add CARAPACE_HOST_DATA_DIR environment variable and update SandboxManager for host path handling

- Introduced the `CARAPACE_HOST_DATA_DIR` environment variable in `docker-compose.yml` to specify
  the host data directory. - Updated `server.py` to retrieve and pass the host data directory to the
  `SandboxManager`. - Enhanced `SandboxManager` to handle host paths for bind mounts, ensuring
  correct path resolution when running in Docker. - Improved logging to provide feedback on host
  data directory overrides during sandbox initialization.

* Implement skill name validation in SandboxManager

- Added a regex-based validation function for skill names to ensure they are non-empty, start with
  an alphanumeric character, and contain only valid characters. - Integrated the validation function
  into the `activate_skill`, `_build_skill_venv`, and `save_skill` methods to enforce skill name
  rules and return appropriate error messages when invalid names are provided. - Refactored the
  `SessionContainer` class to initialize `activated_skills` with an empty list for consistency.

* fix lint issues

* Enhance documentation in agent.py for skill activation and command execution

- Updated the prompt for skill activation to clarify the setup of a virtual environment. - Improved
  the docstring for the exec function to specify that it typically runs bash commands. - Removed the
  unused shell function to streamline the code.

* Refactor session directory structure in SandboxManager

- Changed the session directory structure to use a single 'workspace' directory for skills and
  temporary files. - Updated the relevant methods to reflect the new paths for skill and temporary
  directories, ensuring consistent handling of session data.


## v0.5.0 (2026-02-20)

### ✨

- ✨ Implement token usage tracking and reporting
  ([#34](https://github.com/thiesgerken/carapace/pull/34),
  [`00fbd8e`](https://github.com/thiesgerken/carapace/commit/00fbd8eab83a2906cb6902064ce06e1ab65a15f8))

* ✨ Implement token usage tracking and reporting

- Added a new `UsageTracker` class to monitor token usage across models and categories. - Introduced
  a `/usage` command in the CLI to display token usage statistics. - Enhanced the
  `classify_operation` and `check_rules` functions to record usage data. - Updated the frontend to
  visualize usage data with a new `UsageView` component. - Bumped `carapace` version to 0.4.0 to
  reflect these changes.

* ✨ Enhance usage tracking and reporting features

- Updated `pyproject.toml` to specify version constraints for dependencies. - Added new `costs`
  field to `UsagePayload` for tracking costs associated with token usage. - Implemented cost
  estimation in `UsageTracker` to calculate total costs based on token usage. - Enhanced frontend
  components to display command results and usage costs. - Improved session management to persist
  usage data and events for better tracking. - Updated CLI to include costs in the `/usage` command
  output.

This commit builds upon the previous implementation of token usage tracking, providing a more
  comprehensive view of resource utilization.


## v0.4.0 (2026-02-20)

### ✨

- ✨ Add a web frontend ([#31](https://github.com/thiesgerken/carapace/pull/31),
  [`4d7e028`](https://github.com/thiesgerken/carapace/commit/4d7e0281acdb0fef1c252d0ce818fe6afc98ba6e))


## v0.3.0 (2026-02-19)

### Other

- 💚 Update build command in pyproject.toml to include 'uv lock'
  ([`5cedc87`](https://github.com/thiesgerken/carapace/commit/5cedc87e2c8a74a142eaab058013e8993fcbdc45))

### ✨

- ✨ Revamp Carapace architecture with server and CLI client integration
  ([#30](https://github.com/thiesgerken/carapace/pull/30),
  [`6644bfe`](https://github.com/thiesgerken/carapace/commit/6644bfe8bca5e79801320c76fed669e1775fa4f5))

* ✨ Revamp Carapace architecture with server and CLI client integration

- Introduced a FastAPI server for handling requests and WebSocket connections. - Updated CLI to
  connect to the server, replacing the previous interactive model. - Enhanced documentation in
  AGENTS.md and README.md to reflect new server and client structure. - Added bearer token
  authentication for secure communication between CLI and server. - Updated project dependencies to
  include FastAPI, Uvicorn, and WebSockets. - Version bump to 0.2.0 to signify major architectural
  changes.

* ✨ Implement session locking in WebSocket chat handler

- Added asyncio locks to manage concurrent access to session data, ensuring serialized agent turns.
  - Refactored chat_ws function to utilize session locks for loading and saving message history and
  session state. - Improved error handling and logging during agent execution.

* 🧹 Clean up unused server URL function in CLI

- Removed the `_server_url` function as it was no longer needed in the updated architecture. -
  Streamlined the code for better readability and maintenance.

* ✨ Improve error handling for approval requests in CLI and server

- Added exception handling for keyboard interruptions during approval requests in the CLI, ensuring
  a graceful denial message is displayed. - Updated server logic to handle interrupted approvals by
  marking them as denied and clearing pending requests, enhancing overall robustness.

* Fix 5 bugs: WebSocket auth exception, token permissions, session lock cleanup, async input
  blocking, and verbose output routing

- Use WebSocketException instead of HTTPException for WebSocket auth failures - Set token file
  permissions to 0600 for security - Clean up session locks on WebSocket disconnect to prevent
  memory leak - Use run_in_executor for approval prompt input to avoid blocking event loop - Route
  verbose tool call output via WebSocket instead of server stdout

Applied via @cursor push command

* Fix fire-and-forget WebSocket send by saving task references

- Save created tasks in a set to prevent garbage collection - Add error handling to log WebSocket
  send failures - Cancel pending tasks on client disconnect - This ensures the server detects
  dropped clients and stops expensive LLM calls

* pc

* Refactor WebSocket chat handler for improved control flow and error handling

- Changed return statement to break in command handling for better flow control. - Added a finally
  block to ensure session locks are cleaned up on disconnect. - Enhanced error handling for
  unexpected agent output types during message sending.

* Enhance session management in WebSocket chat handler

- Introduced an async context manager for session connections to manage locks more effectively. -
  Updated chat_ws function to utilize the new session connection management, ensuring proper lock
  handling during WebSocket interactions. - Improved error handling and cleanup on client disconnect
  to prevent memory leaks and ensure session integrity.

---------

Co-authored-by: Cursor Agent <cursoragent@cursor.com>


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
