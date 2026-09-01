"""Import terrain navaids and airfield radio data with Run Python File in VS Code.

Only the configured cache directory is written. DCS sources are never executed.
"""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "python"))

from moosebridge.navaids import main
from moosebridge.navigation_config import load_navigation_config


CONFIG_FILE = PROJECT_ROOT / "config" / "navigation.json"


def run() -> int:
    try:
        config = load_navigation_config(CONFIG_FILE)
        if config.dcs_directory is None:
            raise ValueError("Set navaids.dcs_directory in config/navigation.local.json before importing.")
    except ValueError as exc:
        print(f"Navigation-data import configuration error: {exc}")
        return 2
    return main(["--dcs-root", str(config.dcs_directory), "--output", str(config.cache_directory)])


if __name__ == "__main__":
    raise SystemExit(run())
