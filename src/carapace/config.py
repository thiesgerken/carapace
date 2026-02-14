from __future__ import annotations

import os
from pathlib import Path

import yaml

from carapace.models import Config, Rule, RulesConfig


def get_data_dir() -> Path:
    return Path(os.environ.get("CARAPACE_DATA_DIR", "./data")).resolve()


def load_config(data_dir: Path | None = None) -> Config:
    data_dir = data_dir or get_data_dir()
    config_path = data_dir / "config.yaml"
    if config_path.exists():
        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}
        return Config.model_validate(raw)
    return Config()


def load_rules(data_dir: Path | None = None) -> list[Rule]:
    data_dir = data_dir or get_data_dir()
    rules_path = data_dir / "rules.yaml"
    if rules_path.exists():
        with open(rules_path) as f:
            raw = yaml.safe_load(f) or {}
        rc = RulesConfig.model_validate(raw)
        return rc.rules
    return []


def load_workspace_file(data_dir: Path, name: str) -> str:
    path = data_dir / name
    if path.exists():
        return path.read_text()
    return ""
