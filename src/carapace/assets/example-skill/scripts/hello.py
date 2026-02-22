"""Example skill script demonstrating the sandbox environment.

Run with:  uv run --directory /workspace/skills/example scripts/hello.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

WORKSPACE = Path("/workspace")


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

    # HTTP request (tests network access and httpx dependency)
    print("\nFetching https://httpbin.org/get ...")
    try:
        resp = httpx.get("https://httpbin.org/get", timeout=10)
        print(f"  Status: {resp.status_code}")
        print(f"  Origin: {resp.json().get('origin', 'unknown')}")
    except httpx.HTTPError as exc:
        print(f"  Request failed: {exc}")

    # Writable scratch space
    tmp = WORKSPACE / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    result = {"message": "Hello from example skill", "python": sys.version}
    output_file = tmp / "example-output.json"
    output_file.write_text(json.dumps(result, indent=2))
    print(f"\nWrote result to {output_file}")


if __name__ == "__main__":
    main()
