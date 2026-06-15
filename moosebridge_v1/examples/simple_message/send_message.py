from __future__ import annotations

import asyncio

from moosebridge import MooseBridgeServer


async def main() -> None:
    server = MooseBridgeServer(host="127.0.0.1", port=50100, log_path=None)
    await server.start()
    while not server.state.connected:
        await asyncio.sleep(0.5)
    ack = await server.message_to_coalition("blue", "MOOSE Bridge connected", duration=10)
    print("ACK:", ack)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
