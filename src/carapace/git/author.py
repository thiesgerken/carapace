from __future__ import annotations


def parse_author_template(template: str, session_id: str) -> tuple[str, str]:
    """Parse an author template string into (name, email).

    The template should contain ``%s`` placeholders that will be replaced with
    the session ID. Expected format: ``"Name <email>"``.

    If the format doesn't match, returns ``(template, "{session_id}@carapace")``.
    """
    filled = template.replace("%s", session_id)
    if "<" in filled and filled.endswith(">"):
        name, _, email = filled.rpartition("<")
        return name.strip(), email.rstrip(">").strip()
    return filled, f"{session_id}@carapace"
