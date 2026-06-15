from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from moosebridge.sdk import MooseBridgeClient, MooseBridgeCommandError, SMOKE_COLORS
from moosebridge.server import MooseBridgeServer


async def wait_for_dcs(server: MooseBridgeServer) -> None:
    """Wait until the DCS Lua bridge is connected.

    :param server: Running bridge server instance.
    """

    print("Server started. Waiting for DCS bridge connection...")
    while not server.state.connected:
        await asyncio.sleep(0.5)
    print("DCS connected.")


async def run(args: argparse.Namespace) -> None:
    """Run the tactical annotation example.

    :param args: Parsed command-line arguments.
    """

    server = MooseBridgeServer(host=args.host, port=args.port, log_path=Path(args.log) if args.log else None)
    await server.start()

    try:
        await wait_for_dcs(server)
        bridge = MooseBridgeClient(server)

        await bridge.message_all(args.message, duration=args.duration)
        print("Sent MESSAGE to all.")

        await bridge.smoke_object(args.object_id, color=args.color)
        print(f"Smoked {args.object_id} with {args.color} smoke.")

        await bridge.mark_object(args.object_id, text=args.mark_text)
        print(f"Marked {args.object_id}: {args.mark_text}")
    except MooseBridgeCommandError as exc:
        print("DCS rejected the command:", exc)
        print("ACK:", exc.ack)
        raise
    finally:
        await server.stop()


def main() -> None:
    """Parse command-line arguments and run the example."""

    parser = argparse.ArgumentParser(description="Annotate one DCS/MOOSE object with MESSAGE, SMOKE and MARK.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=50100)
    parser.add_argument("--log", default=None)
    parser.add_argument("--object-id", default="UNIT:Ground-1-1", help="Bridge object id, e.g. UNIT:Ground-1-1")
    parser.add_argument("--color", default="red", choices=sorted(SMOKE_COLORS))
    parser.add_argument("--message", default="MOOSE Bridge tactical annotation example", help="MESSAGE text sent to all players")
    parser.add_argument("--mark-text", default="Annotated by MoosePyBridge", help="Map mark text")
    parser.add_argument("--duration", type=int, default=10, help="MESSAGE duration in seconds")
    args = parser.parse_args()

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
