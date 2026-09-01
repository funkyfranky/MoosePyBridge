from moosebridge.radio_rules import status_report, support_request, threat_warning
from moosebridge.speech import RadioSender


SENDER = RadioSender(
    sender_id="anvil-1", kind="group", radio_id="command", object_id="GROUP:Anvil 1",
)


def test_rule_based_status_is_routine_and_replaceable():
    intent = status_report("ground_command", SENDER, callsign="Anvil One",
                           status="holding", location="checkpoint Alpha")
    assert intent.text == "Anvil One. holding. Position checkpoint Alpha."
    assert intent.priority == 35 and intent.urgency == "routine" and intent.ttl_s == 20
    assert intent.dedupe_key == "status:anvil-1"


def test_rule_based_emergency_request_controls_break_in_fields():
    intent = support_request(
        "ground_command", SENDER, callsign="Anvil One", addressee="Viper",
        request="immediate close air support", location="checkpoint Alpha", emergency=True,
    )
    assert intent.text.startswith("Viper, this is Anvil One.")
    assert intent.priority == 100 and intent.urgency == "emergency" and intent.ttl_s == 12


def test_rule_based_warning_is_short_lived():
    intent = threat_warning(
        "guard", SENDER, callsign="Colt One", threat="missile launch", location="bullseye 270 for 15",
    )
    assert intent.priority == 90 and intent.ttl_s == 8
    assert intent.dedupe_key == "warning:anvil-1:missile launch"
