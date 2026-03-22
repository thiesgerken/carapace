"""Git integration: HTTP backend and repository store."""

from __future__ import annotations

from carapace.git.author import parse_author_template
from carapace.git.http import GitHttpHandler
from carapace.git.store import GitStore

__all__ = ["GitHttpHandler", "GitStore", "parse_author_template"]
