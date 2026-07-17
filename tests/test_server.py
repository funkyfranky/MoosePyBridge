from __future__ import annotations

import asyncio

from moosebridge.protocol import BridgeCommand
from moosebridge.server import DcsBridgeConnectionError, MooseBridgeServer


def _bridge_port(server: MooseBridgeServer) -> int:
    assert server._server is not None
    sockets = server._server.sockets
    assert sockets
    return int(sockets[0].getsockname()[1])


def test_point_commands_use_at_point_actions() -> None:
    server = MooseBridgeServer()
    sent: list[BridgeCommand] = []

    async def fake_send_command(command: BridgeCommand, timeout: float = 10.0) -> dict[str, object]:
        sent.append(command)
        return {"ok": True}

    server.send_command = fake_send_command  # type: ignore[method-assign]

    asyncio.run(server.smoke_at_point(1, 2, "red", y=3))
    asyncio.run(server.mark_at_point(4, 5, "mark", y=6))

    assert [command.action for command in sent] == ["smoke.at_point", "mark.at_point"]
    assert sent[0].params == {"x": 1, "y": 3, "z": 2, "color": "red"}
    assert sent[1].params == {"x": 4, "y": 6, "z": 5, "text": "mark"}


def test_new_snapshot_helpers_use_registered_lua_actions() -> None:
    server = MooseBridgeServer()
    sent: list[BridgeCommand] = []

    async def fake_send_command(command: BridgeCommand, timeout: float = 10.0) -> dict[str, object]:
        sent.append(command)
        return {"ok": True}

    server.send_command = fake_send_command  # type: ignore[method-assign]

    asyncio.run(server.snapshot_cohorts())
    asyncio.run(server.snapshot_legions())

    assert [command.action for command in sent] == ["snapshot.cohorts", "snapshot.legions"]


def test_dcs_connection_reset_during_close_is_handled() -> None:
    class EmptyReader:
        async def readline(self) -> bytes:
            return b""

    class ResettingWriter:
        closed = False

        def get_extra_info(self, name: str) -> object:
            return ("127.0.0.1", 42000) if name == "peername" else None

        def close(self) -> None:
            self.closed = True

        async def wait_closed(self) -> None:
            raise ConnectionResetError(64, "The specified network name is no longer available")

    async def scenario() -> None:
        server = MooseBridgeServer()
        reader = EmptyReader()
        writer = ResettingWriter()

        await server._handle_dcs_client(reader, writer)  # type: ignore[arg-type]

        assert writer.closed is True
        assert server._writer is None
        assert server.state.connected is False

    asyncio.run(scenario())


def test_pending_command_fails_when_dcs_disconnects() -> None:
    async def scenario() -> None:
        server = MooseBridgeServer(host="127.0.0.1", port=0)
        await server.start()
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", _bridge_port(server))
            try:
                while server._writer is None:
                    await asyncio.sleep(0.01)

                task = asyncio.create_task(server.send_command(BridgeCommand(action="message.to_all", params={"text": "hello"}), timeout=5.0))
                while not server._pending:
                    await asyncio.sleep(0.01)

                writer.close()
                await writer.wait_closed()

                try:
                    await task
                except DcsBridgeConnectionError as exc:
                    assert "disconnected" in str(exc)
                else:
                    raise AssertionError("pending command did not fail after DCS disconnect")
            finally:
                writer.close()
        finally:
            await server.stop()

    asyncio.run(scenario())


def test_replaced_connection_cannot_mark_new_connection_disconnected() -> None:
    async def scenario() -> None:
        server = MooseBridgeServer(host="127.0.0.1", port=0)
        await server.start()
        first_writer = None
        second_writer = None
        try:
            _, first_writer = await asyncio.open_connection("127.0.0.1", _bridge_port(server))
            first_port = first_writer.get_extra_info("sockname")[1]
            while server._writer is None or server._writer.get_extra_info("peername")[1] != first_port:
                await asyncio.sleep(0.01)

            _, second_writer = await asyncio.open_connection("127.0.0.1", _bridge_port(server))
            second_port = second_writer.get_extra_info("sockname")[1]
            while server._writer is None or server._writer.get_extra_info("peername")[1] != second_port:
                await asyncio.sleep(0.01)

            await asyncio.sleep(0.05)
            assert server.state.connected is True
            assert server._writer is not None
            assert server._writer.get_extra_info("peername")[1] == second_port
        finally:
            if first_writer is not None:
                first_writer.close()
            if second_writer is not None:
                second_writer.close()
                await second_writer.wait_closed()
            await server.stop()

    asyncio.run(scenario())


def test_wait_for_event_resolves_from_dcs_event() -> None:
    async def scenario() -> None:
        server = MooseBridgeServer()
        waiter = asyncio.create_task(server.wait_for_event("auftrag.evaluated", filters={"auftrag_id": "AUFTRAG:1"}, timeout=1.0))
        await asyncio.sleep(0)

        await server._handle_line(
            '{"type":"event","event":"auftrag.evaluated","payload":{"auftrag_id":"AUFTRAG:1","summary":{"success":true}}}'
        )

        event = await waiter
        assert event["event"] == "auftrag.evaluated"
        assert event["payload"]["auftrag_id"] == "AUFTRAG:1"

    asyncio.run(scenario())


def test_wait_for_event_after_unknown_id_does_not_replay_history() -> None:
    async def scenario() -> None:
        server = MooseBridgeServer()
        await server._handle_line(
            '{"type":"event","id":"event-queued","event":"auftrag.status","payload":{"auftrag_id":"AUFTRAG:1","fsm_event":"Queued"}}'
        )

        waiter = asyncio.create_task(
            server.wait_for_event("auftrag.*", filters={"auftrag_id": "AUFTRAG:1"}, timeout=1.0, after_id="event-missing")
        )
        await asyncio.sleep(0)
        assert not waiter.done()

        await server._handle_line(
            '{"type":"event","id":"event-started","event":"auftrag.status","payload":{"auftrag_id":"AUFTRAG:1","fsm_event":"Started"}}'
        )
        event = await waiter
        assert event["id"] == "event-started"

    asyncio.run(scenario())
