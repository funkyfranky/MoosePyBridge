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
    msg = BridgeMessage(type="heartbeat", source="dcs")
    data = msg.to_dict()

    assert data["type"] == "heartbeat"
    assert "mission_time" not in data
    assert "correlation_id" not in data
