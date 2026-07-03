from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "python"))

from moosebridge import Auftrag_BAI
from moosebridge.control import MooseBridgeControlClient
from moosebridge.control_sdk import sdk_from_control_client


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = 51001
COMMAND_TIMEOUT = 10.0


async def main() -> int:
    control = MooseBridgeControlClient(CONTROL_HOST, CONTROL_PORT)

    status = await control.status(timeout=COMMAND_TIMEOUT)
    if not status.get("connected"):
        print("DCS ist nicht verbunden.")
        return 1

    bridge = sdk_from_control_client(control, timeout=COMMAND_TIMEOUT)

    auftrag_bai = Auftrag_BAI(target="UNIT:Ground-1-1", altitude_ft=15000)

    ack = await bridge.add_auftrag(auftrag=auftrag_bai, legion="LEGION:Wing Parchim")


    print("AUFTRAG erstellt:", ack.get("result", {}).get("auftrag_id"))

    summary = await bridge.get_auftrag_summary(auftrag_bai, on_status=print)

    if summary.success is True:
        print("BAI erfolgreich")
    else:
        print("BAI nicht erfolgreich")

    print(summary.to_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))