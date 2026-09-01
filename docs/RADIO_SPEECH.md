# Radio Speech Service

MoosePyBridge provides a mission-scoped synthetic radio service for player
copilots, instructors, AI aircraft, ground units, ships, airbases and other
trusted simulation producers. HoundTTS renders speech, MOOSE MSRS transmits it
through SRS, and the bridge controls ordering and synthetic channel occupancy.

The service cannot observe human SRS push-to-talk. A human transmission can
therefore overlap synthetic speech. This is an accepted external limitation;
all arbitration described below applies only to transmissions created by this
service.

## Model

| Object | Responsibility | Trust boundary |
| --- | --- | --- |
| `SpeechProfile` | SRS endpoint, frequency, modulation, provider, voice and network policy | Trusted application configuration only |
| `RadioSender` | Logical sender/radio and its live DCS transmission origin | Resolved and revalidated by Lua |
| `RadioIntent` | Text, priority, urgency, TTL and optional dedupe key | May be created by rules or an LLM-backed phraser |
| Sender queue | Prevents one logical sender/radio from talking over itself | Lua mission runtime |
| Network arbiter | Coordinates synthetic senders sharing a configured radio net | Lua mission runtime |

An intent names a configured `profile_id`; it cannot supply a frequency,
provider, voice, SRS path or coalition. This keeps future generated text from
changing trusted radio configuration.

Supported sender origins are:

- `player`: current group/session-guarded player aircraft;
- `unit`: live `UNIT:<name>` wrapper;
- `group`: live `GROUP:<name>` wrapper;
- `airbase`: live `AIRBASE:<name>` wrapper;
- `coordinate`: bounded explicit coordinate and coalition for a source that has
  no suitable live wrapper.

Object position and coalition are checked when the intent is accepted and again
when transmission starts. A stale player session, destroyed sender, missing
coordinate or changed coalition drops the pending intent instead of transmitting
from an invented location.

## Arbitration modes

Profiles sharing one `network_id` must use the same physical frequency,
modulation and policy. Conversely, profiles on the same frequency/modulation
must share one network ID so trusted configuration cannot accidentally bypass
arbitration. Red, blue and neutral coalitions receive separate network
instances even when the profile uses the same network ID.

| Mode | Synthetic network behavior |
| --- | --- |
| `strict` | One sender at a time, including the configured guard interval; no random backoff |
| `disciplined` | One sender at a time with deterministic bounded backoff after a busy channel; default |
| `congested` | Uses the disciplined rules but can deliberately admit configured synthetic collisions |
| `uncontrolled` | Every ready sender may start; only each sender's own queue remains serialized |

When a disciplined, congested or strict network becomes free, the highest
priority ready sender wins; equal priorities use enqueue order. A profile can
allow an `emergency` intent to break into a busy synthetic network. This overlap
is intentional and is controlled by application policy, not by generated text.

The bridge uses Hound's estimated speech duration plus `interval_s` as the
network guard boundary. Per-sender and per-network state is advanced by the
existing bridge 5 Hz scheduler; no scheduler or `MSRSQUEUE` instance is created
per sender. Independent networks and coalitions can transmit in parallel.

## Intent lifecycle

- `intent_id` makes a retry after a lost acknowledgement idempotent.
- `dedupe_key` replaces older pending reports from the same sender/radio, useful
  for rapidly changing status. It never interrupts an active transmission.
- `ttl_s` expires information that is no longer useful before it reaches the
  radio.
- Leaving a player menu session removes its pending player intents. Active audio
  already handed to Hound may finish.
- Mission end, bridge stop, owner release or reconfiguration clears all pending
  runtime state.
- Start, completion, expiry, cancellation and drop transitions are emitted as semantic bridge
  events for later diagnostics and integrations.

`speech.clear` clears pending messages globally for the owning client or for one
logical sender/radio. It does not claim that already submitted Hound audio was
cancelled.

## Python API

The navigation Copilot menu already uses the general API. Other applications can
configure several profiles and submit their own senders:

```python
from moosebridge.radio_rules import support_request
from moosebridge.speech import RadioSender, enqueue_speech

sender = RadioSender(
    sender_id="anvil-1",
    kind="group",
    radio_id="command",
    object_id="GROUP:Anvil 1",
)
intent = support_request(
    "ground_command",
    sender,
    callsign="Anvil One",
    addressee="Viper",
    request="immediate close air support",
    location="checkpoint Alpha",
    emergency=True,
)
await enqueue_speech(bridge, owner_id, intent)
```

One mission-scoped coordinator currently owns the configured profile set. Radio
producers intended to coexist should use that coordinator instance (or share its
owner context) rather than starting competing configuration scripts. A dedicated
multi-producer broker remains an integration task before navigation and the
conflict controller run as independent radio-owning processes.

`moosebridge.radio_rules` currently supplies deterministic builders for routine
status reports, support requests and threat warnings. A later LLM component may
rephrase the factual message, but the application must continue to assign the
profile, sender, priority, urgency, TTL and dedupe policy.

## Current Hornet profile

`config/navigation.json` defines `hornet_copilot` on synthetic network
`blue_305`: Piper `en_US-lessac-low`, 305.000 MHz AM, local SRS port 5002 and
`disciplined` arbitration. `navigation.local.json` supplies the machine-specific
SRS path. `HoundTTS.DEFAULT_TRANSMITTER` must be `srs`; Piper belongs in
`DEFAULT_PROVIDER`.

The current general arbiter passed its live DCS Copilot regression on
2026-09-01: the Hound/SRS test tone, Piper radio check and two sender-serialized
queue-test messages were audible on 305.000 MHz AM without unwanted overlap.
The queue-test acknowledgement reported a pending sender-queue depth of one,
which is expected after the first message has already moved into the active
transmission state. Automated Python and real Lua 5.1 coverage remains the
repeatable regression baseline.

## Known limitation and backlog

HoundTTS 0.2.5 can return a session ID and expose session progress. The current
arbiter intentionally uses the duration estimate because the session-aware path
has not yet been integrated. The backlog retains a bounded polling design that
will release a network from actual Hound completion while preserving estimated
duration as an ETA and failure fallback.
