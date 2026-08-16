from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ROOT = REPO_ROOT / "examples" / "sdk"
CATALOG_PATH = EXAMPLE_ROOT / "README.md"


def sdk_examples() -> tuple[Path, ...]:
    return tuple(sorted(EXAMPLE_ROOT.glob("*.py")))


def test_every_sdk_example_is_documented_in_the_catalog() -> None:
    catalog = CATALOG_PATH.read_text(encoding="utf-8")

    missing = [path.name for path in sdk_examples() if f"`{path.name}`" not in catalog]

    assert missing == []


def test_every_sdk_example_has_a_module_docstring() -> None:
    missing = []
    for path in sdk_examples():
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if not ast.get_docstring(module):
            missing.append(path.name)

    assert missing == []
