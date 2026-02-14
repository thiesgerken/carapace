"""Tests for MemoryStore (no LLM tokens needed)."""

from pathlib import Path

from carapace.memory import MemoryStore


def test_write_and_read(tmp_path: Path):
    store = MemoryStore(tmp_path)
    store.write("notes.md", "hello world")
    assert store.read("notes.md") == "hello world"


def test_read_missing(tmp_path: Path):
    store = MemoryStore(tmp_path)
    assert store.read("nonexistent.md") is None


def test_path_traversal_blocked(tmp_path: Path):
    store = MemoryStore(tmp_path)
    assert store.read("../../etc/passwd") is None
    result = store.write("../../escape.md", "bad")
    assert "Error" in result


def test_list_files(tmp_path: Path):
    store = MemoryStore(tmp_path)
    store.write("a.md", "aaa")
    store.write("sub/b.md", "bbb")
    files = store.list_files()
    assert "a.md" in files
    assert "sub/b.md" in files


def test_search(tmp_path: Path):
    store = MemoryStore(tmp_path)
    store.write("note1.md", "The quick brown fox")
    store.write("note2.md", "Lazy dog sleeps")
    results = store.search("fox")
    assert len(results) == 1
    assert results[0]["file"] == "note1.md"


def test_search_case_insensitive(tmp_path: Path):
    store = MemoryStore(tmp_path)
    store.write("note.md", "Hello World")
    results = store.search("hello")
    assert len(results) == 1
