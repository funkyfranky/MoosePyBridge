"""Explicitly start the current DCS mission in a state of war."""

from __future__ import annotations

from example_support import open_example_session, run_example

from moosebridge import RelationshipState, format_relationship
from moosebridge.control import DEFAULT_CONTROL_PORT


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
DECLARING_COALITION = "blue"
DECLARATION_REASON = "Start the autonomous conflict simulation"


async def run() -> int:
    session = await open_example_session(
        CONTROL_HOST,
        CONTROL_PORT,
        10.0,
        client_id="war-declaration-example",
        display_name="War Declaration Example",
    )
    bridge = session.bridge
    await bridge.refresh_diplomacy_state()
    if bridge.relationship.state is RelationshipState.WAR:
        print("The coalitions are already at war.")
    else:
        incident = bridge.declare_war(
            DECLARING_COALITION,
            reason=DECLARATION_REASON,
        )
        await bridge.persist_diplomacy_state()
        print(
            f"{incident.actor_coalition} declared war on "
            f"{incident.target_coalition}: {DECLARATION_REASON}"
        )
    print()
    print(format_relationship(bridge.relationship))
    return 0


def main() -> int:
    return run_example(run)


if __name__ == "__main__":
    raise SystemExit(main())
