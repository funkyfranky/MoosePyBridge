from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "python"))

from moosebridge import Auftrag_BAI, Auftrag_ORBIT, Auftrag_CAP
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

    #auftrag = Auftrag_BAI(target="UNIT:Ground-1-1", altitude_ft=15000)
    #auftrag = Auftrag_ORBIT(target="ZONE:Town Fight",altitude_ft=15000, speed_kts=300, heading_deg=90, leg_nm=20)
    auftrag = Auftrag_CAP(zone="ZONE:Town Fight", altitude_ft=15000, speed_kts=300, heading_deg=0, leg_nm=20, target_types=["Air"])

    ack = await bridge.add_auftrag(auftrag=auftrag, legion="LEGION:Wing Laage")

    print("ACK:")
    print(ack)
    print()
    result= ack.get("result", {})
    print("AUFTRAG erstellt:", result.get("auftrag_id"), result.get("legion_id"))
    print()

    summary = await bridge.get_auftrag_summary(auftrag, on_status=print)

    if summary.success is True:
        print("BAI erfolgreich")
    else:
        print("BAI nicht erfolgreich")

    print(summary.to_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))