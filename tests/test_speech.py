from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from moosebridge.speech import (
    RadioIntent,
    RadioSender,
    SpeechProfile,
    configure_speech,
    enqueue_speech,
    test_tone as request_test_tone,
)


def profile(profile_id="copilot", network_id="blue_305", frequency=305.0):
    return SpeechProfile(
        srs_path=r"D:\DCS\_SRS", srs_host="127.0.0.1", srs_port=5002,
        frequency_mhz=frequency, modulation="AM", provider="piper",
        voice="en_US-lessac-low", label="COPILOT", volume=1.0, speed=1.0,
        interval_s=0.5, profile_id=profile_id, network_id=network_id,
        arbitration="disciplined", backoff_min_s=0.25, backoff_max_s=0.75,
        collision_probability=0.1, emergency_break_in=True,
    )


def bridge(result=None):
    server = SimpleNamespace(send_command=AsyncMock(return_value={"ok": True, "result": result or {}}))
    return SimpleNamespace(server=server), server


def test_configure_supports_multiple_trusted_profiles():
    async def scenario():
        client, server = bridge({"enabled": True, "profile_count": 2})
        result = await configure_speech(
            client, "radio-service", [profile(), profile("guard", "blue_243", 243.0)], enabled=True,
        )
        command = server.send_command.await_args.args[0]
        assert result["profile_count"] == 2
        assert command.action == "speech.configure"
        assert [item["profile_id"] for item in command.params["profiles"]] == ["copilot", "guard"]
        assert command.params["profiles"][0]["arbitration"] == "disciplined"
    asyncio.run(scenario())


def test_radio_intent_keeps_sender_and_untrusted_content_separate_from_profile():
    async def scenario():
        client, server = bridge({"queued": True, "sender_queue_depth": 1})
        sender = RadioSender(
            sender_id="armor-platoon-1", kind="group", radio_id="command",
            object_id="GROUP:Armor Platoon 1",
        )
        intent = RadioIntent(
            intent_id="request-1", profile_id="ground_command", sender=sender,
            text="Viper, this is Anvil. Request immediate support at checkpoint Alpha.",
            priority=80, urgency="urgent", ttl_s=12, dedupe_key="anvil-support",
        )
        await enqueue_speech(client, "radio-service", intent)
        params = server.send_command.await_args.args[0].params
        assert params["sender"] == {
            "sender_id": "armor-platoon-1", "kind": "group", "radio_id": "command",
            "object_id": "GROUP:Armor Platoon 1",
        }
        assert params["profile_id"] == "ground_command"
        assert "frequency_mhz" not in params and params["urgency"] == "urgent"
    asyncio.run(scenario())


def test_player_tone_is_bound_to_current_group_session():
    async def scenario():
        client, server = bridge({"requested": True})
        sender = RadioSender.player("GROUP:Hornet", "session-7", radio_id="copilot")
        await request_test_tone(client, "radio-service", "copilot", sender)
        params = server.send_command.await_args.args[0].params
        assert params["sender"]["group_id"] == "GROUP:Hornet"
        assert params["sender"]["session_id"] == "session-7"
    asyncio.run(scenario())


@pytest.mark.parametrize("kwargs", [
    {"priority": 101}, {"urgency": "panic"}, {"ttl_s": 0}, {"text": "line\nbreak"},
])
def test_invalid_intents_fail_before_a_bridge_write(kwargs):
    values = {"profile_id": "copilot", "sender": RadioSender.player("GROUP:Hornet", "s1"),
              "text": "Radio check."}
    values.update(kwargs)
    with pytest.raises(ValueError):
        RadioIntent(**values)


def test_sender_object_prefix_must_match_kind():
    with pytest.raises(ValueError, match="GROUP"):
        RadioSender(sender_id="wrong", kind="group", object_id="UNIT:Wrong")
