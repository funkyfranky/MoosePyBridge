# DCS Navigation Project

Status: Concept, preparation, and navigation prototype

Updated: August 30, 2026

## Purpose of this document

This document collects findings, architecture ideas, decisions, risks, and next
steps for a new Python-based navigation project for DCS World and MOOSE.

The final product scope has not been fixed. The recommended starting point is a
deterministic navigation and flight-planning core. An AI copilot and AI ATC can
later build on the same core.

## Product vision

A Python-based navigation and flight-planning platform for DCS World that
connects current navigation data with the actual DCS mission state and provides
structured navigation services to pilots, cockpit systems, MOOSE-controlled AI
flights, and eventually voice assistants.

An initial end-to-end use case would be:

> The user selects departure, destination, and aircraft. The system generates a
> flyable route with runway, departure, enroute segment, arrival, and approach,
> then assists the pilot throughout the flight.

## Project principles

- All project-facing text is in English unless explicitly requested otherwise.
  This includes menus, messages, logs, errors, documentation, and code comments.
  Conversation with the user may remain in German.
- Navigation, routing, and validation are deterministic core functions. A
  language model may operate and explain them, but must not replace them with
  unconstrained decisions.
- The internal flight plan remains independent of Navigraph, DCS, MOOSE, and
  any particular aircraft module.
- Navigraph, DCS/MOOSE, DTC, and cockpit modules connect through adapters.
- DCS remains authoritative for the live simulation state.
- Navigraph data may only be used for flight simulation and in accordance with
  Navigraph's license terms.
- Automatic actions require typed requests, validation, and explicit
  confirmation for high-risk actions. MoosePyBridge's activation model is a
  suitable reference.
- Secrets such as the Navigraph Client Secret, Access Token, and Refresh Token
  must never appear in Git, logs, or DTC files.

## Planned development stages

### 1. Navigation and flight-planning core

Possible inputs include:

- Departure and destination airport
- Aircraft type and navigation equipment
- IFR/VFR or tactical mission type
- Departure time
- DCS weather and wind
- Desired cruise altitude or optimization objective
- Airspace and threat areas to avoid

Possible outputs include:

- Departure and landing runway
- SID or suitable departure route
- Enroute waypoints and airways
- Cruise altitude
- STAR or arrival transition
- Instrument approach and missed approach
- Optional holds
- Courses, distances, altitudes, speed constraints, and ETA
- A structured waypoint list for different output formats

Holds are not added to every route by default. They arise from a procedure, an
ATC instruction, a holding requirement, or a dynamic traffic situation.

### 2. DTC and cockpit integration

The generated flight plan should be translated into a suitable Data Transfer
Cartridge format for supported DCS modules. This can substantially simplify or
replace manual cockpit entry.

Additional outputs may include:

- MOOSE/DCS routes for AI aircraft
- Kneeboards or mission cards
- F10 markers
- Machine-readable JSON
- Step-by-step entry instructions for the copilot

### 3. AI copilot

The copilot can be expanded gradually:

1. **Advisory:** Explain the flight plan, frequencies, courses, checklists, and
   cockpit inputs.
2. **Assisted:** Prepare typed inputs and wait for confirmation.
3. **Automatic:** Operate explicitly supported cockpit systems through
   module-specific adapters.

Possible tasks:

- Explain the flight plan and justify changes
- Prepare waypoint and radio data
- Guide the pilot through checklists
- Monitor navigation and cross-track error
- Announce upcoming actions, altitudes, and frequencies
- Monitor fuel, ETA, and diversion options
- Prepare radio calls
- Generate a new DTC or input sequence when replanning

DCS has no universal cockpit-control interface. F-16C, F/A-18C, A-10C, AH-64D,
and other modules each need their own adapters, potentially through DCS-BIOS,
Export Lua, or module-specific cockpit commands.

### 4. Flight Instructor

The Flight Instructor is a separate role from the copilot. The copilot assists
with execution; the instructor observes, evaluates, explains, and provides
targeted training.

Planned modes:

- **Briefing:** Explain the route, procedures, learning objectives, and likely
  sources of error
- **Silent:** Help only when asked
- **Training:** Provide contextual guidance for relevant deviations
- **Strict:** Closely monitor procedures and tolerances
- **Exam:** Remain silent during the flight and evaluate afterward
- **Debriefing:** Produce an error timeline, assessment, and exercise suggestions

Possible monitoring areas:

- Target versus actual altitude, speed, and course
- Cross-track error, climb/descent rate, and ETA
- Flight phase and correct aircraft configuration
- Approach profile, localizer, glideslope, and angle of attack
- Landing gear, flaps, airbrake, fuel, and bingo
- Checklists and procedure steps
- Sensor, radar, defensive-system, and weapon-system states
- Prerequisites and simulated parameters for weapon employment

Deviations are detected deterministically from DCS telemetry, the flight plan,
flight phase, and an aircraft-specific training profile. A language model only
handles clear explanations, dialogue, and the timing of noncritical assistance.
Tolerances, priorities, hysteresis, and duplicate suppression prevent unnecessary
or constant prompts.

The **DCS: F/A-18C Hornet** is the first reference and test aircraft. The initial
instructor prototype should monitor IFR navigation, flight phases,
altitude/speed guidance, and a stabilized approach. Sensor and weapon-system
courses can be added as separate modules later.

### 5. ATIS and AI ATC

Full AI ATC is a substantial, long-term project in its own right. It should build
on the navigation core in small stages:

1. ATIS/AWOS
2. Advisory traffic information
3. Tower for one airport
4. Approach control with sequencing, vectors, and holds
5. Regional ATC with sectors, handoffs, and separation
6. Military additions such as formation flights, GCI, marshal, carrier
   operations, and tactical airspace

Separation, runway occupancy, conflict detection, and clearance state must be
computed deterministically. A language model only handles dialogue,
interpretation, and natural-language phrasing.

## Navigraph findings

These notes retain the research findings from August 29, 2026. API access and
license conditions still need confirmation for the intended application.

### Access

- The Navigraph developer-access request was emailed on August 29, 2026.
- Requested or recommended capabilities:

  - Navigation Data API
  - DFD v2 in SQLite format
  - Device Authorization Flow with PKCE
  - A local Python application for DCS World

- A personal Navigraph subscription grants the account access to subscribed
  data, but does not replace developer approval.
- The API requires an application-specific `Client ID` and `Client Secret`.
- Each end user authenticates with their own Navigraph account.

### Navigation Data API

This is not a search API for individual waypoints. It provides complete,
AIRAC-based data packages. The relevant entry point is:

```http
GET https://api.navigraph.com/v1/navdata/packages
Authorization: Bearer <access-token>
```

Package descriptions include:

- AIRAC cycle and revision
- Package status: `outdated`, `current`, or `future`
- Format
- Files
- SHA-256 checksums
- Short-lived download URLs

The application downloads the appropriate package and performs searches, graph
preparation, and route calculation locally. On startup, it checks the cycle,
revision, and hash, updating only packages that have changed.

### Authentication

Device Authorization Flow with PKCE is planned for the local desktop/simulator
application. Typical scopes are:

```text
openid offline_access fmsdata
```

The user authorizes the application through a browser, code, or QR code. The
Access Token is valid for approximately one hour. The longer-lived Refresh Token
is replaced on refresh and must be stored securely and atomically.

### DFD v2

DFD v2 follows ARINC 424 concepts and can be supplied as SQLite or text data.
Relevant data types include:

- Airports, runways, and gates
- VHF navaids, DME, ILS, and GLS
- Enroute and terminal NDBs
- Enroute and terminal waypoints
- Airways and airway restrictions
- Holds
- SIDs, STARs, and instrument approaches
- Airport and enroute communications
- MSA and Grid MORA
- Controlled and restricted airspace
- FIR/UIR
- Procedure path points

Procedure data contains ARINC-style legs and constraints. The planner must
convert these into connected, flyable segments.

Official development samples are available as geographically limited, older
DFD v1/v2 datasets. They may be used for development and evaluation, not
redistribution.

### Charts API

The Charts API provides high-resolution day/night airport-chart PNGs and enroute
maps as Web Mercator tiles. Airport charts may include metadata, procedure and
runway associations, and georeferencing.

The Charts API is not needed initially. Important restrictions recorded during
the research:

- Charts must not be stored or cached offline.
- A conventional standalone desktop charts application is generally not
  approved.
- Virtual EFBs within the simulator are typically allowed. Local supplementary
  displays closely tied to an active simulation require Navigraph review.
- FMS navigation data must not be used to create map-like substitutes for
  Navigraph products.

Any later map view must therefore be clearly distinguished from a Navigraph
charts product, both technically and under the license, and approved in advance
where necessary.

### SimBrief

SimBrief can be an optional flight-plan provider or import source. A user's
latest OFP can be retrieved as XML or JSON. Creating flight plans through a
custom integration requires a separately requested SimBrief API key.

SimBrief is useful for civil flight planning, but does not replace a dedicated
planner for military DCS aircraft, tactical routes, or threat avoidance.

## DCS and MOOSE findings

DCS provides or controls:

- Live mission state
- Player and AI positions
- Weather and wind
- DCS airports and actually implemented radio navaids
- Terrain and theater coordinates
- Mission-specific beacons, carriers, and TACAN stations
- Threats, coalitions, and the tactical mission situation

MoosePyBridge monitors the player-slot lifecycle through MOOSE
`PlayerEnterAircraft` and DCS `PlayerLeaveUnit`. The normalized events
`player.aircraft.entered` and `player.aircraft.left` include the player, unit,
group, and, where available, the associated `FLIGHTGROUP` through its inherited
`OPSGROUP` identity. Navigation, copilot, and instructor sessions can start on
entry and end on departure. Lua caches entry data because leave events do not
always retain all player and wrapper fields. DCS can emit `PlayerLeaveUnit`
twice within milliseconds. The bridge suppresses duplicate leave events for the
same player or unit within one second; re-entry immediately resets this window.

The bridge also delays processing `PlayerEnterAircraft` by 0.5 seconds. Mission
scripts handling the same event can create the `FLIGHTGROUP` first; the bridge
then resolves the `OPSGROUP`. If the player leaves earlier, the pending entry is
processed before the leave, preventing a delayed active session from remaining.

MOOSE provides semantic mission objects, AI groups, and routes. It is not a
universal interface for operating player-aircraft avionics.

### First DCS test path: Mission Editor route

Before Navigraph routing and DTC generation are available, a route created in
the DCS Mission Editor serves as the first executable flight plan. MOOSE adopts
the existing group as a `FLIGHTGROUP`. The inheritance relationship is explicit:

```text
FLIGHTGROUP -> OPSGROUP
```

Navigation can use general state and functions from the `OPSGROUP` base and
supplement them with flight-specific information from `FLIGHTGROUP`. This test
path enables the following experiments without external navigation data:

- Read Mission Editor waypoints and investigate current-waypoint state
- Compare the planned route with position, course, altitude, and speed
- Test flight phases and cross-track deviations
- Test copilot and instructor guidance
- Start player sessions on slot entry and stop them on departure
- Later compare the same neutral route with Navigraph and DTC adapters

Implemented initial route retrieval:

- Lua command `flightgroup.route.get`, Python SDK
  `get_flightgroup_route(opsgroup_id, route_source="mission_editor")`.
- The full Mission Editor route comes from the inherited `waypoints0` list.
  `GetWaypoints()` returns the processed current route instead; MOOSE may remove
  the landing point from it. That source is available separately through
  `route_source="current"`.
- DCS waypoint `x/y` values are horizontal coordinates, treated as world
  `x/z`. The `alt` (meters), `alt_type` (BARO/RADIO), and `speed` (m/s)
  values are preserved. F10 display uses only the horizontal projection.
- `examples/sdk/monitor_player_aircraft.py` retrieves the route after entry and
  draws consecutive points as a cyan line for the player's coalition. The
  display supports two to 501 points. Only this overlay is removed on slot
  departure or script exit.
- The display changes neither the route nor avionics. It connects waypoints
  with straight lines, without modeling turns, holds, or instrument procedures.

Live route tracking in the same Python script:

- Query the specific player `UNIT` every two seconds through the existing
  `object.coords` API; no additional Lua timer.
- Distance to the next waypoint in NM and bearing referenced to true north.
  This is not a magnetic steering heading and does not include wind correction.
- Cross-track error (XTE) in meters relative to the active straight segment:
  positive right, negative left. Calculated in DCS `x/z` to match the F10 line,
  not as a 3D slant distance. Before/after the segment, XTE refers to its extended
  line rather than distance to the endpoint.
- Independent deterministic progress tracking starts at WP 1 -> WP 2,
  configurable through `INITIAL_TARGET_WAYPOINT`. It does not read the active
  avionics waypoint.
- Advance within a 500 m capture radius. A crossing between two samples also
  counts if lateral proximity is sufficient and the sample gap is at most ten
  seconds. The first position sample does not automatically skip a distant
  waypoint already behind the aircraft.
- Reaching the target means horizontal proximity only, not a successful landing
  or compliance with altitude and speed constraints.
- Position polling stops on slot departure, mission end, and script exit.

Navigraph mainly represents current real-world civil navigation. DCS has its own,
sometimes historical, theater data. Explicit reconciliation is therefore needed:
matching ICAO codes do not guarantee matching runways, frequencies, procedures,
or coordinates.

### In-game menu: initial functional test

- MOOSE foundation: `MENU_GROUP:New(group, text)` creates the submenu;
  `MENU_GROUP_COMMAND:New(group, text, parent, callback)` binds actions.
- Test script: `examples/sdk/monitor_player_menu.py`, run directly in VS Code
  while the normal Python daemon and DCS mission are running. Restart the mission
  after a Lua update. The project Lua file is also synchronized to the MOOSE
  directory on branch `FF/PyBridge`.
- Radio menu -> F10 Other -> **MoosePyBridge Test**, not the F10 map.
  **Show message** calls `MESSAGE:ToGroup` directly in Lua;
  **Python console** sends `player.menu.selected` for output in the test script.
- Menus are off by default. The script enables them through
  `player.menu.test.configure` for already occupied and subsequently entered
  groups. Neither a `FLIGHTGROUP` nor flight is required.
- Important limitation: group visibility, not individual permissions.
  DCS supplies no clicking-player name. `group_sessions` identifies current
  group occupants, not the actual person who clicked.
- One menu instance per group, removed only when the last occupant leaves.
  Duplicate leave events remain suppressed. Re-entry handles changed DCS group
  IDs. Removed callbacks become inert.
- Ctrl+C removes the current run's menus. Mission end also cleans up and ends the
  script. A forced process kill can leave menus behind; a new run takes ownership.
  A run ID prevents an older run from removing the new run's menus.
- Automated verification uses a Lua lifecycle harness with simulated DCS/MOOSE
  boundaries and Python tests for event reception, filters, cursors, and cleanup.
  Set `MOOSEBRIDGE_TEST_LUA` to a local Lua interpreter to run the Lua harness.
  The user confirmed both actions in DCS: cockpit message and `MENU CLICK` for
  `GROUP:Test Hornet` / `funkyfranky`: PASS.

### Installed DCS navaids

The read-only offline importer in `examples/navigation/import_dcs_beacons.py`
reads all installed terrain Beacon and airfield radio tables plus their common
definitions.
Run it directly in VS Code without a bridge server or DCS mission. It creates
local JSON snapshots, preserves raw data, and writes an English validation
report. Matching source/artifact hashes reuse the cache; failed file imports do
not replace the previous current snapshot. Record issues remain visible rather
than being silently corrected.

See [DCS Navaid Import and Validation](NAVAIDS.md) for source interpretation,
cache semantics, the type-based radio menu, limitations, and remaining TODOs.

### Navigation through the radio menu

- Normal entry point: `examples/sdk/run_navigation_menu.py` in VS Code. Start it
  once; it waits for the normal daemon and mission and survives mission changes.
  Restart the mission after a Lua update. Stop old diagnostic menu scripts first.
  Shared configuration and loading/recovery rules: [Navigation Client Workflow](WORKFLOW.md).
- Radio menu -> F10 Other -> **Navigation**, with eight top-level items:
  **Show route**, **Hide route**, **Navigation status**, **Flight status**, **Enable hints**,
  **Disable hints**, **Navaids**, and **Airfields / ATC**.
- **Navaids** groups imported stations by type. New group menus initialize all
  type lists once from one current aircraft-position snapshot. **Refresh nearby**
  updates a type's list later; select a station for source data, horizontal
  distance and TRUE bearing. Six stations per page plus refresh/previous/next
  stay within nine custom entries, reserving a tenth position for DCS Back.
  **More types** keeps the type list within the same limit. No FLIGHTGROUP is
  needed. Before each activation the snapshot is checked against the local
  installation and pinned; source warnings remain visible. Nearby does not
  imply receivable or aircraft-compatible. See [the detailed guide](NAVAIDS.md#in-game-navaids-menu).
- **Navaids > Selected station** offers **Show on F10**, **Show with bearing line**
  and **Hide from F10**. Inspecting a station alone does not draw or move it.
  The explicit display uses a labeled amber position symbol and optional static
  aircraft-to-station line, visible to the group's coalition. It is independent
  of the cyan route, respects session cleanup, and does not start Direct-to
  guidance or change cockpit settings. The type root remains at nine entries.
- **Airfields / ATC** joins imported `radioId` UIDs to live MOOSE AIRBASE objects
  by `AIRBASE:GetID()`, never by name. Six-airfield pages provide callsign,
  shared ATC roles, source frequencies, live distance and TRUE bearing. Empty or
  nonstandard source records remain visible in the issue/unresolved counts.
- Route display and hints start off. The display uses the preserved Mission
  Editor route and a cyan F10 line for the group's coalition, not exclusively
  for the group. Hiding the line does not affect hints.
- Status shows the reference aircraft, active leg and target, distance in NM,
  TRUE bearing, and spelled-out cross-track error through `MESSAGE:ToGroup`:

  ```text
  Navigation status | Reference: Hornet-1
  Leg: WP 1 -> WP 2 | Target: WP 2
  Distance: 12.10 NM | Bearing: 093.3 deg TRUE
  Cross-track error: 15 m left
  ```

  Hints sample every two seconds by default and display approximately every ten
  seconds and on waypoint capture.
- The existing `RouteNavigator` is reused per group-menu session. Progress
  survives showing/hiding the line and disabling hints. There is no periodic
  aircraft-position polling while hints are off. The application still checks
  connection/mission health. Cockpit waypoint selection is neither read nor
  changed; target capture does not prove a landing.
- Navigation status/hints require exactly one player aircraft per group and its FLIGHTGROUP.
  Multiple crew seats in the same UNIT count as one aircraft. Multiple player
  aircraft produce an error message instead of an arbitrary reference choice.
- Lua validates owner ID, menu-session ID, DCS group ID, and occupancy for
  context, message, and overlay calls. Delayed work from an old session is
  rejected. When the last occupant leaves, `player.menu.closed` stops Python
  hints and the session's line is removed.
- Lua removes its line even without a reachable Python client. Ctrl+C, mission
  end, or a new menu run removes the menu and its line; unrelated overlays remain.
  The client waits for the next mission and creates fresh state. It also recovers
  from server/connection changes; hints and selections are never restored.
- Ground checks: show/hide the line, request status, enable hints for at least
  ten seconds, disable hints, leave/re-enter the slot, and stop with Ctrl+C.
  Automated tests cover Lua lifecycle/write guards and Python actions/task
  cancellation. The user confirmed the navigation-menu ground test.

**Flight status** is a separate on-demand action. It reads the occupied UNIT's
live DCS position/orientation and velocity without requiring a FLIGHTGROUP. If
the group has a FLIGHTGROUP, its current FSM state is included; otherwise that
optional field is N/A. It
also reads the UNIT's POSITIONABLE methods: `GetGroundSpeed`, `GetAirspeedTrue`,
`GetMachNumber`, and `GetAirspeedIndicatedEstimated`. Python formats one
15-second group message and the same console report: MSL/AGL in feet, local
temperature in Celsius and pressure in hPa/inHg, IAS/TAS/GS in knots,
Mach, MAG/TRUE heading and track, and vertical speed in ft/min
with climb/descent/level labels.
The layout separates altitude, speeds, and direction:

```text
Flight status | Reference: Hornet-1
FLIGHTGROUP FSM: Airborne
Altitude: 10,000 ft MSL | 9,000 ft AGL
Vertical speed: +1,000 ft/min (climb)
Temperature: 15.0 C | Pressure: 1013.2 hPa / 29.92 inHg

IAS: 240.0 kt | TAS: 270.0 kt
GS: 250.0 kt | Mach: 0.420

Heading: 084.0 deg MAG | 090.0 deg TRUE
Track: 084.0 deg MAG | 090.0 deg TRUE
```

This is an illustrative layout, not a recorded DCS sample. The bridge transports
speeds in m/s; Python only converts display units and does not duplicate the
MOOSE airspeed calculation. Air data uses wind without turbulence. There is no
fallback to the legacy `GetAirspeedIndicated(OATCorrection)` approximation.
If a speed method is missing, fails or returns invalid data, that optional
value is unavailable. GS can still fall back to the horizontal DCS velocity;
TAS, estimated IAS and Mach are never substituted with GS or a previous sample.
Velocity and wind availability are checked before reading airspeed methods
that otherwise return fallback zeros. Temperature, local static pressure and
magnetic declination come from the current MOOSE COORDINATE. MOOSE resolves
declination for the coordinate when its optional `magvar` dependency is available
and otherwise uses its terrain-wide constant. Magnetic directions are computed
as `TRUE - declination`, normalized to 0..360 degrees. Geographic north comes
from a local DCS coordinate-conversion
tangent, not uncorrected grid north. Track is unavailable below 1 m/s GS.
Unavailable optional telemetry is N/A; missing position or an ambiguous/dead
reference aircraft rejects the report. Lua validates the reference again before
returning telemetry and before delivering the group message. Multiple seats in
one aircraft remain supported. Reports containing N/A include a short legend.

These are world-state quantities, not cockpit instrument readings: geometric
MSL is not pressure/QNH altitude, terrain AGL is not radar altitude or carrier
deck clearance, and displayed MAG/TRUE references are intentionally distinct.
The action leaves route progress,
hints, and cockpit systems unchanged and starts no timer. Instructor warnings,
target-altitude/speed comparisons, and cockpit IAS are outside this first step.
The IAS value is calculated CAS, not a cockpit reading or an aircraft-specific
instrument/position-error correction. Restart the mission after installing the
POSITIONABLE methods and their UTILS dependencies or updating the bridge Lua.
Automated telemetry/conversion tests are included; live parked and airborne
Flight status checks remain pending.

### Initial airborne test

The user supplied a test log for `GROUP:Test Hornet Air`:

- The first run could not resolve a FLIGHTGROUP at the time of the status query.
  The second run resolved it and provided guidance.
- Distance to WP 2 decreased from 12.10 NM to 0.59 NM in the displayed samples.
- The navigator then advanced from WP 1 -> WP 2 to WP 2 -> WP 3.
- XTE changed during flight, including left/right indications on the new leg.
- Tracking continued after the route-display command.
- The script stopped at mission end/reset.

This confirms initial live tracking and waypoint sequencing. Deliberate left/right
maneuvers to validate XTE sign against the flown path remain a separate test.

## DTC findings

### General suitability

DCS can create, save, import, and export DTCs in the Mission Editor and in-game.
DTCs can be:

- Stored in a `.miz` file
- Assigned to individual player/client aircraft or flights
- Exported as `.dtc` files and imported later
- Selected before mission start
- Managed on the ground at a friendly airport through the ground-crew menu
- Loaded by partition in the cockpit

DTCs are intended for player/client aircraft. AI aircraft still need DCS or MOOSE
routes.

### Functionality recorded during research

DTC support began with F-16C and F/A-18C and was extended to MiG-29A. AH-64D was
well advanced and A-10C II planned at the time of research. Features and memory
partitions are aircraft-specific.

Relevant F-16C capabilities include:

- Navigation steerpoints and routes
- VIP/VRP and offset aimpoints
- TACAN, ILS, and bingo
- Geo lines, steerpoints 31 through 55
- Threat points, steerpoints 56 through 70
- Destination points, steerpoints 81 through 99

For the F/A-18C, relevant data includes navigation points and SA data such as CAP
points, corridors, FAOR/FLOT, and missile engagement zones.

### Limitations and risks

- No stable public DTC API or binding cross-module file specification is known
  from the research so far.
- ED and third-party modules can use different data models and interfaces.
- The format and DTC features are evolving rapidly.
- Importing a DTC can overwrite existing waypoint slots; generic merge behavior
  must not be assumed.
- Forum reports indicate that dynamic-spawn workflows are not consistently
  reliable yet.
- Dynamic replanning during flight is not available for every module or start
  type.

DTC is therefore an output adapter, explicitly not the internal flight-plan
model.

### Planned format experiment

When time permits, export at least these test files from DCS:

- `empty.dtc`: default DTC without custom navigation points
- `one-point.dtc`: one uniquely named waypoint
- `changed-point.dtc`: the same point with changed coordinates and altitude

Then inspect file type, serialization, coordinates, partitions, IDs, checksums,
and version dependencies. Perform the experiment with the F/A-18C first and
optionally repeat it with the F-16C.

## Proposed architecture

```text
Navigraph DFD ---------+
                       |
DCS/MOOSE Live State --+--> Normalization --> Navigation Core
                       |                         |
Aircraft Profiles -----+                         +--> Route/Procedure Planner
                                                 +--> Guidance/Monitoring
                                                 +--> Conflict Validation
                                                 |
                                                 +--> Per-module DTC Adapter
                                                 +--> MOOSE/DCS AI Route
                                                 +--> Copilot Tools
                                                 +--> Instructor/Evaluator
                                                 +--> Kneeboard/Mission Card
                                                 +--> Future ATC Services
```

### Potential core models

- `Airport`
- `Runway`
- `Navaid`
- `Waypoint`
- `AirwaySegment`
- `Airspace`
- `Procedure`
- `ProcedureLeg`
- `AltitudeConstraint`
- `SpeedConstraint`
- `Holding`
- `AircraftNavigationProfile`
- `FlightPlan`
- `RouteLeg`
- `NavigationSolution`
- `DcsMissionContext`
- `ThreatArea`
- `DtcCartridge`
- `DtcPartition`
- `FlightPhase`
- `AircraftTrainingProfile`
- `TrainingEvent`
- `TrainingSession`
- `DebriefingReport`

### Adapter boundaries

- `NavigraphRepository`: DFD import and local queries
- `DcsStateAdapter`: weather, airports, beacons, and live state
- `MooseRouteAdapter`: semantic AI routes and mission commands
- `AircraftProfileRepository`: performance and avionics limitations
- `DtcExporter`: module-specific cartridge generation
- `CockpitAdapter`: optional direct avionics operation
- `FlightTelemetryAdapter`: flight state and available cockpit parameters
- `TrainingEvaluator`: deterministic rules, tolerances, and assessments
- `SimBriefAdapter`: optional OFP import

## Preliminary MVP

The first MVP should work without AI, voice, or direct cockpit control. The
F/A-18C Hornet is the first reference aircraft for the aircraft profile, DTC
adapter, telemetry, and later instructor features.

### Scope

1. Open a DFD v2 SQLite database and validate its metadata.
2. Search airports, runways, navaids, and waypoints.
3. Resolve ambiguous identifiers geographically.
4. Match departure and destination to a DCS theater.
5. Calculate an enroute connection through the airway network.
6. Identify suitable SID, STAR, and approach candidates.
7. Convert procedure legs and constraints into a neutral flight plan.
8. Calculate distances, courses, and a basic ETA.
9. Export the plan as JSON and readable text.
10. Provide tests using known routes and edge cases.

### Outside the first MVP

- Full aircraft-performance optimization
- Weather- and NOTAM-aware routing
- Comprehensive terrain-clearance validation
- Tactical threat avoidance
- Charts API
- Automatic cockpit entry
- AI copilot with write access
- ATC

## Decisions

- The navigation core is deterministic and independent of an LLM.
- The project is developed as a separate Python subproject, while reusing
  suitable MoosePyBridge transport, coordinate, theater, and state components.
- Navigraph is a data source, not the domain model.
- DTC is treated as an aircraft-specific output format.
- The F/A-18C Hornet is the first test and reference aircraft.
- Player sessions start with `PlayerEnterAircraft` and end with
  `PlayerLeaveUnit`; `FLIGHTGROUP` is a specialization of its inherited
  `OPSGROUP` base.
- MOOSE remains the preferred semantic execution path for AI units.
- DTC and, later, module-specific cockpit adapters will be investigated for
  player aircraft.
- Flight Instructor and copilot remain separate roles. The instructor uses a
  deterministic evaluator; the language model only explains and converses.
- AI ATC, if pursued, begins with ATIS and advisory services rather than full
  separation responsibility.
- English is the default language for project artifacts and output; other
  languages require an explicit request.

## Open questions

- Should the subproject remain in the existing repository or eventually use its
  own repository?
- Which DCS map should be paired with the F/A-18C for the first vertical
  prototype?
- Should routing start with civil IFR planning or tactical threat avoidance?
- Which DCS data sources reliably expose weather, runways, and radio navaids?
- How should real-world Navigraph airports and DCS airfields be versioned and
  reconciled?
- Which aircraft-performance data may be used and distributed?
- Should the first broader interface be a CLI, browser map, or in-game overlay?
- Which parts of a route may change automatically after pilot confirmation?
- What exact license restrictions apply to the intended route display?
- Is the exported `.dtc` format stable and reproducible without an internal DCS
  checksum?
- How do DTC import and slot merging behave for each aircraft module?

## Task list

### Possible now

- [ ] Download official DFD v2 sample data and document its license notice.
- [ ] Inventory the DFD v2 SQLite schema against the documentation.
- [ ] Build a small Python airport, navaid, and waypoint search experiment.
- [ ] Draft neutral `FlightPlan` and `RouteLeg` models.
- [x] Select the F/A-18C Hornet as the first test and reference aircraft.
- [ ] Select the first DCS theater for the MVP.
- [ ] Review existing MoosePyBridge components for reuse.
- [x] Connect `PlayerEnterAircraft` and `PlayerLeaveUnit` to MoosePyBridge and
      mirror active player-aircraft sessions in Python.
- [x] Read a F/A-18C FLIGHTGROUP's Mission Editor waypoints as the initial route
      through the inherited OPSGROUP base.
- [x] Implement read-only route retrieval and F10 line display in the Python test.
- [x] Validate the F10 line, including departure/landing points, against the
      Mission Editor route in DCS.
- [x] Implement live distance, true bearing, and XTE with independent sequencing.
- [x] Observe automatic WP 2 -> WP 3 sequencing in an airborne test.
- [ ] Validate XTE signs with deliberate left/right maneuvers in flight.
- [x] Implement an opt-in group menu with cockpit and Python-console test actions.
- [x] Confirm both simple menu actions in DCS.
- [x] Connect route display, status, and switchable hints to the navigation menu.
- [x] Confirm the navigation-menu ground test.
- [x] Add on-demand, read-only Flight status to the navigation menu, with explicit
      altitude, speed, and direction references and no FLIGHTGROUP dependency.
- [ ] Validate Flight status in DCS while parked and from the air-start slot.
- [x] Add POSITIONABLE GS/TAS, Mach and CAS-based estimated IAS to Flight status,
      with grouped English output, N/A handling and a 15-second display.
- [x] Add optional FLIGHTGROUP FSM state, COORDINATE temperature/pressure and
      coordinate magnetic declination to Flight status; simplify altitude labels.
- [ ] Compare the extended readout with parked/airborne Hornet observations;
      keep CAS-based estimates distinct from cockpit IAS.
- [x] Standardize project-facing text and documentation on English.
- [x] Implement a non-executing, read-only terrain Beacon importer and English
      validation report, preserving raw records and unknown types.
- [x] Validate 14 installed maps and 1,253 entries; test versioned snapshots,
      source-hash invalidation, corrupt caches and failed-import preservation.
- [x] Import each terrain radio.lua with preserved callsigns, ATC roles,
      frequency bands/modulation, raw records, encoding and validation issues.
- [x] Join standard radioId UIDs exclusively to live MOOSE AIRBASE:GetID()
      values and add a paged Airfields / ATC menu with read-only details.
- [ ] Validate Airfields / ATC in DCS on Caucasus and Sinai, including automatic
      initialization, nearby ordering, paging, source callsigns and frequencies.
- [x] Add a type-based Navaids menu with six-station pages, guarded group messages,
      nearest ordering and a source-validated snapshot pinned per activation.
- [x] Confirm the initial Navaids menu test in DCS: TACAN/NDB station selection,
      Refresh nearby, previous/next pages, and cockpit/Python messages (2026-08-31).
- [x] Initialize all navaid type lists once per new group menu from one position
      snapshot, retaining manual refresh and six-station pagination.
- [ ] Confirm automatic population in DCS for already occupied and later-entered
      slots, re-entry, and mission/terrain changes; no initial refresh required.
- [x] Add explicit F10 display/hide for an inspected navaid, a labeled position
      marker and optional static bearing line, separate from the route overlay.
- [ ] Validate navaid F10 display in DCS, including labels, static line origin,
      explicit replacement, independent route visibility and lifecycle cleanup.
- [ ] Add opt-in navaid Direct-to guidance without changing cockpit waypoints;
      browsing stations must not change the active navigation target.
- [ ] Validate remaining Navaids live cases: More types, empty lists, refresh
      after movement, leave/re-entry cleanup, and isolation between player groups.
- [x] Add a persistent navigation client, shared local configuration, Lua API
      preflight and non-blocking navaid cache validation before activation.
- [x] Test reconnect/reset, idle and busy mission boundaries, lost enable ACKs,
      incompatible Lua, unavailable caches and competing menu ownership.
- [ ] Validate the persistent workflow in DCS without flying: start before the
      mission, end/start another mission, restart the daemon, and check cleanup.
- [ ] Extract menu/telemetry modules and standardize internal test-era names.
- [ ] Add bounded raw-log rotation separately from semantic audit persistence.
- [ ] Add reviewed navaid overrides, explicit stale-cache use and live availability.
- [ ] Define tests for duplicate fix identifiers and DCS/Navigraph discrepancies.

### After Navigraph approval

- [ ] Configure Client ID and Client Secret locally only.
- [ ] Implement Device Authorization Flow with PKCE.
- [ ] Implement a secure, atomic token store.
- [ ] Connect the `packages` endpoint.
- [ ] Implement cycle, revision, and SHA-256 validation.
- [ ] Provide clear subscription and error handling.
- [ ] Load a current DFD v2 dataset and compare it with the sample.

### After generating DTC test files

- [ ] Determine the `.dtc` file type and structure.
- [ ] Produce controlled diffs of the three F/A-18C files.
- [ ] Identify coordinate, altitude, name, and slot encodings.
- [ ] Validate import of an externally reproduced test file in DCS.
- [ ] Optionally repeat the experiment with F-16C.
- [ ] Record format version and DCS build in test fixtures.
- [ ] Decide whether the first DTC adapter should be read-only or write-capable.

### Later

- [ ] **Connect the conflict simulation to optional player missions.** Derive
      mission offers from the player's coalition objectives and operational
      plans, using only information available to that coalition. Offer an English
      briefing and navigation route through the in-game menu, with explicit
      player acceptance or rejection. Define coordination with AI assignments
      and mission-result feedback to avoid duplicate tasking. This is a deferred
      integration idea, not the next implementation step or a current milestone
      requirement; see the [project backlog](../BACKLOG.md#p3---deferred-player-missions).
- [ ] Develop an airway router and procedure resolver.
- [ ] Integrate live DCS weather and runway selection.
- [ ] Define aircraft navigation profiles.
- [ ] Develop a F/A-18C DTC exporter.
- [ ] Develop a MOOSE route exporter.
- [ ] Develop a guidance and monitoring service.
- [ ] Integrate an advisory copilot as a tool consumer.
- [ ] Develop a F/A-18C training profile and flight-phase detection.
- [ ] Develop a rule-based instructor evaluator with tolerances and hysteresis.
- [ ] Start with opt-in target-altitude monitoring using an explicit altitude
      reference, sustained-deviation threshold and reminder cooldown.
- [ ] Prototype an IFR/approach instructor and debriefing report.
- [ ] Add modular sensor and weapon-system courses.
- [ ] Evaluate an ATIS prototype.
- [ ] Evaluate tower/approach ATC only afterward.

## References

- [Navigraph Developer Portal](https://developers.navigraph.com/docs/general/introduction)
- [Navigraph API Access Request](https://developers.navigraph.com/docs/request-access)
- [Navigraph Navigation Data API](https://developers.navigraph.com/docs/navigation-data/api-overview)
- [Navigraph DFD v2 Specification](https://developers.navigraph.com/docs/navigation-data/dfd-data-format-v2)
- [Navigraph Sample Data](https://developers.navigraph.com/docs/navigation-data/sample-data)
- [Navigraph Device Authorization Flow](https://developers.navigraph.com/docs/authentication/device-authorization)
- [Navigraph Restrictions](https://developers.navigraph.com/docs/general/restrictions)
- [DCS DTC Forum](https://forum.dcs.world/forum/1329-dtc-data-transfer-cartridge/)
- [DCS DTC Quick Start Guide](https://forum.dcs.world/topic/371995-quick-start-guide-data-transfer-cartridge-dtc/)
- [DCS 2026 Roadmap](https://www.digitalcombatsimulator.com/en/news/2026-01-09/)
- [DCS AH-64D DTC Development Report](https://www.digitalcombatsimulator.com/en/news/2026-08-07/)
