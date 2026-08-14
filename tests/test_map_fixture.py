from __future__ import annotations

import importlib.util
from pathlib import Path
import re


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "run_map_fixture_server.py"
SPEC = importlib.util.spec_from_file_location("run_map_fixture_server", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_map_fixture_covers_every_dynamic_map_layer_with_unique_ids() -> None:
    picture = MODULE.build_fixture_picture()
    features = picture["features"]
    layers = {feature["properties"]["layer"] for feature in features}
    object_ids = [feature["properties"]["object_id"] for feature in features]

    assert layers == {
        "airbases", "frontlines", "groups", "incursions", "intel_clusters", "intel_contacts",
        "legions", "loss_reports", "mission_links", "missions", "opsgroups", "opszones",
        "pressure_frontlines", "recon_coverage", "statics", "territories", "trajectories", "units", "zones",
        "strategic_objectives",
    }
    assert len(object_ids) == len(set(object_ids))
    assert picture["properties"]["diplomacy"]["relationship"] == "war"


def test_mobile_fixture_uses_a_real_narrow_embedded_viewport() -> None:
    page = MODULE.MOBILE_QA_PAGE

    assert 'width: 390px' in page
    assert 'height: 844px' in page
    assert 'id="mobile-map"' in page


def test_every_fixture_layer_has_a_map_control_or_an_explicit_parent() -> None:
    script = (Path(__file__).resolve().parents[1] / "python" / "moosebridge" / "map_ui" / "map.js").read_text(
        encoding="utf-8"
    )
    configured = set(re.findall(r'key: "([a-z_]+)", label:', script.split("const layerSections", 1)[0]))
    fixture_layers = {
        feature["properties"]["layer"] for feature in MODULE.build_fixture_picture()["features"]
    }

    assert fixture_layers - {"mission_links"} <= configured
    assert 'mapLayerIds.get("missions").push("mission-links-line")' in script
    assert 'layers: ["legions", "strategic_objectives", "missions"]' in script
