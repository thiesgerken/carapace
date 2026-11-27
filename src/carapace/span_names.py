"""Names of the spans that clients match on (see "Span names clients match on" in docs/websocket-session.md).

Kept free of server dependencies, so the thin CLI client can import it.
"""

from __future__ import annotations

# `skill`: `read_skill` waits for a skill's build.
SKILL_BUILD_WAIT_SPAN = "build wait"
# `skill`: the sandbox's skill profile gets the built commands.
SKILL_PROFILE_SYNC_SPAN = "profile sync"
# `wait`: a call queued behind another command holding the session's exec lock.
EXEC_LOCK_WAIT_SPAN = "exec lock"
