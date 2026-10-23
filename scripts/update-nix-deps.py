#!/usr/bin/env python3
"""Refresh pinned pnpm binaries and fetchPnpmDeps after frontend dependency updates."""

from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def asset_hash(version: str, asset: str) -> str:
    url = f"https://github.com/pnpm/pnpm/releases/download/v{version}/{asset}"
    result = subprocess.check_output(["nix", "store", "prefetch-file", "--json", url], text=True)
    return json.loads(result)["hash"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--system",
        choices=("x86_64-linux", "aarch64-linux"),
        default="aarch64-linux" if platform.machine() in ("arm64", "aarch64") else "x86_64-linux",
    )
    args = parser.parse_args()
    manager = json.loads((ROOT / "frontend/package.json").read_text())["packageManager"]
    match = re.fullmatch(r"pnpm@([0-9]+\.[0-9]+\.[0-9]+)", manager)
    if not match:
        raise ValueError(f"Expected an exact pnpm packageManager, got {manager!r}")
    pins_path = ROOT / "nix/pnpm-binaries.json"
    pins = json.loads(pins_path.read_text())
    if pins["version"] != match[1]:
        for binary in pins["platforms"].values():
            binary["hash"] = asset_hash(match[1], binary["asset"])
        pins["version"] = match[1]
        pins_path.write_text(json.dumps(pins, indent=2) + "\n")

    hash_file = ROOT / "nix/pnpm-deps-hash"
    previous_hash = hash_file.read_text()
    hash_file.write_text("")
    command = ["nix", "build", f".#packages.{args.system}.pnpmDeps", "--no-link", "--print-build-logs"]
    try:
        hashes: list[str] = []
        with subprocess.Popen(
            command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        ) as process:
            assert process.stdout is not None
            for line in process.stdout:
                print(line, end="", flush=True)
                hashes.extend(re.findall(r"got:\s+(sha256-[A-Za-z0-9+/]+=*)", line))
            returncode = process.wait()
        if returncode == 0 or len(hashes) != 1:
            raise RuntimeError("Expected one fetchPnpmDeps hash mismatch; resolve the actual build failure first")
        hash_file.write_text(hashes[0] + "\n")
        subprocess.run(command, cwd=ROOT, check=True)
    except BaseException:
        hash_file.write_text(previous_hash)
        raise
    print("Updated pnpm binary pins and dependency hash. Commit them with the dependency change.")


if __name__ == "__main__":
    main()
