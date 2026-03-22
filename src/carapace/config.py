from __future__ import annotations

import os
from pathlib import Path

import yaml

from carapace.models import Config


def get_config_path() -> Path:
    """Return the resolved path to ``config.yaml``.

    Reads from ``CARAPACE_CONFIG`` env var, defaulting to ``./data/config.yaml``.
    """
    explicit = os.environ.get("CARAPACE_CONFIG")
    if explicit:
        return Path(explicit).resolve()
    return Path("./data/config.yaml").resolve()


def get_data_dir() -> Path:
    """Legacy helper — resolves ``data_dir`` from config file location."""
    config_path = get_config_path()
    return _resolve_data_dir(config_path)


def _resolve_data_dir(config_path: Path, config: Config | None = None) -> Path:
    """Resolve ``data_dir`` relative to the config file's directory."""
    config_dir = config_path.parent
    if config and config.data_dir:
        return (config_dir / config.data_dir).resolve()
    return config_dir.resolve()


def _resolve_knowledge_dir(config_path: Path, config: Config) -> Path:
    """Resolve ``knowledge_dir`` relative to the config file's directory."""
    config_dir = config_path.parent
    if config.knowledge_dir:
        return (config_dir / config.knowledge_dir).resolve()
    return (config_dir / "knowledge").resolve()


def load_config(data_dir: Path | None = None) -> Config:
    config_path = get_config_path() if data_dir is None else data_dir / "config.yaml"
    if config_path.exists():
        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}
        return Config.model_validate(raw)
    return Config()


def load_workspace_file(base_dir: Path, name: str) -> str:
    path = base_dir / name
    if path.exists():
        return path.read_text()
    return ""
