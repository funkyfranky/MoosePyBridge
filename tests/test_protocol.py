from moosebridge.protocol import BridgeCommand, BridgeMessage


def test_command_to_dict_contains_required_fields():
    cmd = BridgeCommand(action="message.to_all", params={"text": "hello"})
    data = cmd.to_dict(sequence=1)

    assert data["version"] == 1
    assert data["type"] == "command"
    assert data["source"] == "python"
    assert data["sequence"] == 1
    assert data["action"] == "message.to_all"
    assert data["params"] == {"text": "hello"}


def test_message_to_dict_omits_none_values():
    msg = BridgeMessage(type="heartbeat", source="dcs", mission_time=10.5, dcs_time=43_210.5)
    data = msg.to_dict()

    assert data["type"] == "heartbeat"
    assert data["mission_time"] == 10.5
    assert data["dcs_time"] == 43_210.5
    assert "correlation_id" not in data
