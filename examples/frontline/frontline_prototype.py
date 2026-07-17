"""Generate a synthetic operational frontline and open its diagnostic viewer."""

from __future__ import annotations

import json
import math
from pathlib import Path
import random
import sys
import webbrowser

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_PYTHON_DIR = REPO_ROOT / "python"
if LOCAL_PYTHON_DIR.exists():
    sys.path.insert(0, str(LOCAL_PYTHON_DIR))

from moosebridge.frontline_diagnostics import write_frontline_diagnostic_html
from moosebridge.frontlines import ForcePoint, FrontlineArea, FrontlineConfig, FrontlineEngine


RANDOM_SEED = 17
OPEN_BROWSER = True
OUTPUT_DIRECTORY = REPO_ROOT / "tmp"

GRID_SPACING_M = 1_500.0
INFLUENCE_SIGMA_M = 18_000.0
SIMPLIFY_TOLERANCE_M = 500.0


def synthetic_forces() -> list[ForcePoint]:
    """Create two opposing formations with one blue salient."""

    randomizer = random.Random(RANDOM_SEED)
    forces: list[ForcePoint] = []
    for coalition, side in (("blue", -1), ("red", 1)):
        for index in range(18):
            z = -72_000 + index * 8_500 + randomizer.uniform(-2_500, 2_500)
            curved_front = 11_000 * math.sin(z / 38_000)
            x = side * 31_000 + curved_front + randomizer.uniform(-5_000, 5_000)
            if coalition == "blue" and 8 <= index <= 11:
                x += 17_000
            forces.append(
                ForcePoint(
                    object_id=f"GROUP:{coalition.title()}-{index + 1}",
                    coalition=coalition,
                    x=x,
                    z=z,
                    weight=randomizer.uniform(0.7, 2.2),
                    label=f"{coalition.title()} {index + 1}",
                )
            )
    return forces


def main() -> int:
    """Run the isolated calculation and write its diagnostic artifacts."""

    area = FrontlineArea(
        "Synthetic Campaign Area",
        (
            (-105_000, -88_000),
            (88_000, -88_000),
            (112_000, -48_000),
            (102_000, 87_000),
            (-92_000, 92_000),
            (-116_000, 38_000),
        ),
    )
    config = FrontlineConfig(
        grid_spacing_m=GRID_SPACING_M,
        influence_sigma_m=INFLUENCE_SIGMA_M,
        simplify_tolerance_m=SIMPLIFY_TOLERANCE_M,
    )
    result = FrontlineEngine(config).calculate(synthetic_forces(), area=area)

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    geojson_path = (OUTPUT_DIRECTORY / "frontline_prototype.geojson").resolve()
    geojson_path.write_text(json.dumps(result.to_geojson(), indent=2), encoding="utf-8")
    html_path = write_frontline_diagnostic_html(
        result,
        OUTPUT_DIRECTORY / "frontline_prototype.html",
        title="Operational Frontline Prototype",
    )

    print(
        f"forces={result.diagnostics['included_force_count']} "
        f"segments={result.diagnostics['segment_count']} "
        f"length={result.diagnostics['frontline_length_m'] / 1000:.1f} km "
        f"runtime={result.elapsed_ms:.1f} ms"
    )
    print(f"GeoJSON: {geojson_path}")
    print(f"Viewer:  {html_path}")
    if OPEN_BROWSER:
        webbrowser.open(html_path.as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
