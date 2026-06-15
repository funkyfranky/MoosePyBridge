from __future__ import annotations

import asyncio

from moosebridge.server import MooseBridgeServer


async def main() -> None:
    server = MooseBridgeServer(host="127.0.0.1", port=50100, log_path=None)
    await server.start()
    print("Server started. Waiting for DCS bridge connection...")
    while not server.state.connected:
        await asyncio.sleep(0.5)
    print("DCS connected. Sending test message to blue coalition...")
    ack = await server.message_to_coalition("blue", "MOOSE Bridge connected", duration=10)
    print("ACK:", ack)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
