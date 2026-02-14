from __future__ import annotations

from pathlib import Path


class MemoryStore:
    def __init__(self, data_dir: Path):
        self.memory_dir = data_dir / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def read(self, relative_path: str) -> str | None:
        path = (self.memory_dir / relative_path).resolve()
        if not str(path).startswith(str(self.memory_dir.resolve())):
            return None
        if not path.exists():
            return None
        return path.read_text()

    def write(self, relative_path: str, content: str) -> str:
        path = (self.memory_dir / relative_path).resolve()
        if not str(path).startswith(str(self.memory_dir.resolve())):
            return "Error: path escapes memory directory"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return f"Written to memory/{relative_path}"

    def search(self, query: str) -> list[dict[str, str]]:
        """Simple grep-based search over memory files (PoC, no vector search)."""
        results: list[dict[str, str]] = []
        query_lower = query.lower()
        for path in self.memory_dir.rglob("*.md"):
            if path.name.startswith("."):
                continue
            text = path.read_text()
            if query_lower in text.lower():
                relative = path.relative_to(self.memory_dir)
                # Extract matching lines
                lines = [
                    line.strip()
                    for line in text.splitlines()
                    if query_lower in line.lower()
                ]
                results.append(
                    {
                        "file": str(relative),
                        "matches": "; ".join(lines[:3]),
                    }
                )
        return results

    def list_files(self) -> list[str]:
        files: list[str] = []
        for path in sorted(self.memory_dir.rglob("*.md")):
            if path.name.startswith("."):
                continue
            files.append(str(path.relative_to(self.memory_dir)))
        return files
