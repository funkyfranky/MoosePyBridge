# Navigation Client Workflow

## Normal use

1. Start the normal MoosePyBridge daemon once. It owns the DCS connection on
   port 42000 and the local control API on port 42001.
2. Run `examples/sdk/run_navigation_menu.py` with **Run Python File** in VS Code
   once. It can also be started before the daemon or before DCS.
3. Start a mission with the bridge loaded and started. The client waits for
   readiness, checks navigation Lua compatibility and the navaid cache, then
   enables the group menus for occupied and future player slots.
   Each new group menu initializes all navaid type lists and the Airfields / ATC
   list from one current aircraft-position snapshot. Wait for the initialization
   messages in the console, then open either submenu directly. **Refresh nearby**
   updates its ordering later.
   The same activation adds the **Copilot** submenu. When speech is enabled it
   also configures HoundTTS/MSRS and adds **Radio diagnostics** below Copilot.
   No additional Python process is required.
4. End/start missions without restarting the Python client. Each activation
   starts with route and navaid map display off. Copilot monitoring, text output
   and radio output start on. No prior route progress, station selection or
   Copilot evaluator state is restored.
5. Stop the navigation script with Ctrl+C. The daemon keeps running.

No additional launcher or server process is needed. The client does not launch
DCS, start the daemon, import beacon data, copy Lua or modify mission files.
FLIGHTGROUP creation remains mission-owned and is needed for route navigation,
not for Flight status, Navaids or Airfields / ATC. The existing 0.5 s slot-entry
delay remains.

**Flight status** shows a grouped 15-second readout of optional FLIGHTGROUP FSM,
altitude/vertical speed, temperature/pressure (hPa/inHg), GS/TAS, Mach, CAS-based estimated
IAS, and MAG/TRUE heading/track. It remains on
demand, with no polling or cockpit changes. The airspeed fields require the
new POSITIONABLE methods and their UTILS helpers to be loaded in the mission;
missing optional values appear as N/A. Restart the mission after MOOSE changes.

**Copilot** samples the same aircraft every `navigation.sample_interval_seconds`
and compares it with the active Mission Editor route leg. The target waypoint's
route speed is compared with GS. Altitude is linearly interpolated only when both
leg endpoints use the same supported reference: BARO is evaluated against MSL,
RADIO against terrain AGL. Takeoff and landing legs are excluded. Defaults require
a deviation to persist for 10 seconds and use separate warning/recovery bands:
300/150 ft, 20/10 kt and 0.50/0.25 NM XTE. Active deviations repeat no sooner
than every 60 seconds; returning inside the recovery band produces a short
recovery advisory. Missing/ambiguous data suppresses that metric instead of
guessing. Monitoring retries if the player FLIGHTGROUP is not yet available.

**Copilot radio** uses HoundTTS 0.2.5, MOOSE MSRS, the bridge's per-sender
outboxes and synthetic radio-network arbiter with the local SRS
server. The initial profile is Piper `en_US-lessac-low`, `305.000 MHz AM`, port
5002 and label `COPILOT`. The Hornet radio and SRS client must be tuned to that
frequency. **SRS test tone** bypasses Piper; **Radio check** validates one TTS
transmission; **Queue test** enqueues two messages from one sender/radio that
should play in order. The default `disciplined` policy also coordinates other
synthetic senders on that network. Human SRS PTT is not observable and may overlap.
The configured SRS path is retained for MSRS compatibility, but Hound transmits
directly and does not launch `DCS-SR-ExternalAudio.exe`.

## Shared configuration

Both the navigation client and `examples/navigation/import_dcs_beacons.py`
read `config/navigation.json`, then merge the optional, Git-ignored sibling
`config/navigation.local.json`. Settings are loaded once per script invocation.
Restart the script after changing settings; unknown/malformed keys fail early.
Paths are relative to the configuration directory, not the terminal's cwd.

Local example (replace the installation path for your machine):

```json
{
  "navaids": {
    "dcs_directory": "G:/Games/DCS World Testing"
  }
}
```

The shared defaults contain no machine-specific DCS directory. Without a local
path, other navigation actions still work; Navaids reports how to configure it.
The default cache path `../tmp/navaids` resolves to the repository's ignored
cache directory. Use `navaids.enabled: false` to disable navaid access explicitly.

The `speech` section validates the SRS path/host/port, frequency, modulation,
provider, voice, label, volume, speed, guard interval, profile/network IDs,
arbitration mode, backoff, collision probability and emergency policy. Its host must match
`HoundTTS.SRS_HOST`; secrets remain in Hound configuration and never enter this
project file. Set `speech.enabled: false` to disable radio service and omit only
the **Radio diagnostics** submenu; text Copilot controls remain available.
Hound itself must use `DEFAULT_TRANSMITTER = "srs"`; `piper` belongs in
`DEFAULT_PROVIDER`. The Lua preflight rejects this common configuration mix-up
instead of accepting messages that cannot reach the SRS transmitter.

The `copilot` section controls automatic start, default output channels, warning
and recovery thresholds, persistence and reminder cooldown. Other settings cover
the control host/port, command timeout, retry interval, event-wait timeout,
sample interval, initial waypoint and capture radius.
`control.port` is the daemon's **control** port, not its DCS-facing port. This
file does not change daemon command-line settings or the mission bridge address.

## Mission Lua: choose one loading path

With the development MOOSE branch `FF/PyBridge`, `Moose/Modules.lua` already
includes the bridge JSON, core and extension files. Do not additionally dofile
those files from another directory. After MOOSE is loaded, the mission needs
one bridge instance:

```lua
Bridge = MOOSE_BRIDGE:New("127.0.0.1", 42000)
Bridge:Start()
```

For MOOSE distributions without that integration, load the JSON helper, bridge
core and required extensions before creating the instance. The general
`MooseBridgeMissionExample.lua` is for this separate-loading setup; it is not an
additional loader to use on top of the integrated development configuration.
Navigation requires the DCS-events extension. The socket-tuning extension is
recommended for low-impact retries while the daemon is absent.

Edit runtime Lua in this project's `lua` directory first, then synchronize it
to the configured MOOSE `Moose/Python` directory. Restart the mission to load
changes. Do not hot-reload bridge extensions into a running mission. Repeated
loads of the DCS-events extension are ignored, not treated as a live update.

## Startup checks and recovery

The read-only `player.menu.navigation.status` command reports navigation API
version 1, required capabilities, MOOSE readiness, terrain, bridge-instance
identity and current menu ownership. A missing/incompatible Lua implementation
keeps the client waiting with an actionable message; it does not build menus.
Required capabilities include batch navaid initialization and its
`player.menu.created` notification. The client captures its event cursor before
enabling menus, so existing occupants' creation events are not missed.
Enable/disable commands from this client also check the expected Lua instance.

Before each activation, source and artifact hashes of the current navigation-data cache
are checked outside the client's asyncio event loop. The active terrain is
selected by its exact DCS ID. Missing/stale/unreadable data produces a startup
warning while leaving the other navigation actions available. Flight status
and route navigation remain available.
No automatic import or stale-cache fallback occurs. Run the importer explicitly;
the next Navaids or Airfields refresh checks the repaired cache again, and a
client restart also performs the check.
Successful catalogs remain pinned until that activation ends. This validates
the local installation, not a remote server's terrain build or radio reception.

An independent watcher checks daemon identity, mission generation, connection,
Lua instance and ownership even while an action or event wait is pending. A
boundary cancels pending work and guidance and releases the old controller.
Recovery creates a new controller and menu owner ID, so stale callbacks cannot
address replacement slots. Recovery also deliberately resets navigation when
reconnecting to the same mission; display state is reset and Copilot defaults are reapplied.

Starting a second navigation client intentionally replaces the earlier run.
The old client detects that ownership changed and **stops**, instead of stealing
the menus back. The same applies if the diagnostic menu tool takes ownership.
Cleanup is owner/instance-scoped. If DCS is unavailable, cleanup cannot be
guaranteed immediately; Lua removes menus/overlays on last slot leave or mission
end, and the next successful activation replaces abandoned menus.

## When a restart is needed

- Navigation Python/configuration changes: restart the navigation script.
- Runtime Lua changes: synchronize the files and restart the mission. The
  persistent client notices the new mission and reactivates automatically.
- Daemon implementation changes: restart the daemon; the navigation client
  waits and reconnects. Other applications retain their own recovery policies.
- Updated DCS beacon sources: rerun the offline importer; use the new snapshot
  on the next navigation activation. No mid-activation data replacement occurs.

## Verification

Automated tests cover startup before server/mission, mission-end delivery and
missed end events, same-generation daemon restart, Lua-instance replacement,
disconnect/reconnect, failed preflight, missing caches, lost enable ACKs,
interrupted actions, Ctrl+C-equivalent cancellation, takeover and shared config.
Navaid tests also cover one-snapshot initialization of every type, empty lists,
creation before the enable acknowledgement, later slot entry, duplicate events,
manual-refresh races and recovery after initialization failure.
Speech tests cover guarded menu actions, multiple-profile validation,
owner/session isolation, trusted profile boundaries, sender serialization,
priority, TTL, deduplication, idempotent retries, Emergency Break-in, all four
network modes, test-tone dispatch and the nine-entry menu limit. See the
[general radio service](../RADIO_SPEECH.md).
Copilot tests cover altitude-reference interpolation, takeoff/landing exclusion,
sustained deviations, hysteresis, cooldowns, recovery calls, waypoint priority,
independent output controls and end-to-end text/radio dispatch.

Live DCS validation of automatic list initialization and this persistent
workflow is pending. Check TACAN/NDB without first selecting Refresh nearby,
both when already in the cockpit at script start and when entering later.
Start the client
before the mission, use a menu action, then end/start the mission while leaving
the script running. Check that menus return, old drawings are gone and Copilot
defaults are reapplied. Also restart the daemon once and check recovery. None of these
checks require flying. The earlier station-menu PASS does not certify these
new lifecycle changes or the still-pending navaid F10 drawing test.
Initial live speech validation: **PASS** on 2026-09-01. With the Hornet/SRS
client tuned to 305.000 AM, the Hound test tone, Piper radio check and both
queue-test messages were audible; the two queued messages played completely
and without overlap. A successful command acknowledgement alone still proves
only that Lua accepted a future request, so audible SRS behavior remains part of
live regression testing. The test was repeated successfully after deployment of
the general sender/network arbiter. A reported queue depth of one during the
two-message test is expected: the first message is already active and the second
is the only pending sender-queue item.

## Deferred consolidation

- Extract the growing menu/telemetry implementation from the DCS-events module
  while preserving public commands and MOOSE integration.
- Bound/rotate raw protocol logs separately from the semantic audit store.
- Improve per-group scheduling/transport efficiency as multiplayer use grows.

No log files were removed or rotated as part of this workflow change.
