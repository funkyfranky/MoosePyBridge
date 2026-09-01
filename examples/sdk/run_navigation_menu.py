"""Run in VS Code once; wait for the normal daemon and survive mission changes."""

from example_support import REPO_ROOT, run_example

from moosebridge.navigation_app import NavigationApplication
from moosebridge.navigation_config import load_navigation_config


CONFIG_FILE = REPO_ROOT / "config" / "navigation.json"


async def run() -> int:
    config = load_navigation_config(CONFIG_FILE)
    print(f"Navigation configuration: {CONFIG_FILE} (optional navigation.local.json overrides).", flush=True)
    return await NavigationApplication(config).run()


if __name__ == "__main__":
    raise SystemExit(run_example(run))
