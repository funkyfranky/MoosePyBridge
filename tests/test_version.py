from __future__ import annotations

import configparser
from pathlib import Path

import moosebridge


def test_sdk_version_matches_package_metadata() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    config = configparser.ConfigParser()
    config.read(repository_root / "setup.cfg", encoding="utf-8")

    assert moosebridge.__version__ == config["metadata"]["version"]
