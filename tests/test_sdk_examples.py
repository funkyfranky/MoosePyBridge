from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ROOT = REPO_ROOT / "examples" / "sdk"
CATALOG_PATH = EXAMPLE_ROOT / "README.md"
DIRECT_CONTROL_EXAMPLES = {
    "release_smoke_test.py",
    "test_mission_reset.py",
}
COMPATIBILITY_EXAMPLES = {"auftrag.py"}


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


def test_regular_sdk_examples_use_shared_runtime_support() -> None:
    missing_support = []
    direct_control = []
    for path in sdk_examples():
        if (
            path.name == "example_support.py"
            or path.name in DIRECT_CONTROL_EXAMPLES
            or path.name in COMPATIBILITY_EXAMPLES
        ):
            continue
        source = path.read_text(encoding="utf-8")
        if "from example_support import" not in source:
            missing_support.append(path.name)
        if "MooseBridgeControlClient" in source:
            direct_control.append(path.name)

    assert missing_support == []
    assert direct_control == []
