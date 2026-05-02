"""Example skill demonstrating provider setup and exec-scoped tunnel usage.

Run with: uv run --directory /workspace/skills/example hello
"""

import imaplib
import json
import os
import sys
from pathlib import Path

WORKSPACE = Path("/workspace")
CONFIG_PATH = WORKSPACE / "skills" / "example" / ".example-skill" / "imap-demo.json"


def main() -> None:
    print("Hello from the example skill!")
    print(f"Python: {sys.version}")
    print(f"Working dir: {os.getcwd()}")

    # Read-only workspace files
    for name in ("AGENTS.md", "SOUL.md", "USER.md"):
        path = WORKSPACE / name
        status = "present" if path.exists() else "not mounted"
        print(f"  /workspace/{name}: {status}")

    # Read-only memory
    memory = WORKSPACE / "memory"
    if memory.exists():
        files = list(memory.rglob("*"))
        print(f"  /workspace/memory/: {len(files)} file(s)")

    print(f"\nReading tunnel config from {CONFIG_PATH} ...")
    try:
        config = json.loads(CONFIG_PATH.read_text())
    except OSError as exc:
        print(f"  Could not read config: {exc}")
        return

    host = str(config.get("host", "imap.gmail.com"))
    port = int(config.get("port", 1993))
    print(f"  Connecting to {host}:{port} via carapace-managed tunnel ...")

    try:
        client = imaplib.IMAP4_SSL(host=host, port=port)
        _tag, capabilities = client.capability()
        client.logout()
    except OSError as exc:
        print(f"  IMAP capability probe failed: {exc}")
    else:
        capability_text = " ".join(part.decode("utf-8", errors="replace") for part in capabilities)
        print("  CAPABILITY succeeded")
        print(f"  {capability_text}")

    # Writable scratch space
    tmp = WORKSPACE / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    result = {"message": "Hello from example skill", "python": sys.version, "imap_host": host, "imap_port": port}
    output_file = tmp / "example-output.json"
    output_file.write_text(json.dumps(result, indent=2))
    print(f"\nWrote result to {output_file}")


if __name__ == "__main__":
    main()
