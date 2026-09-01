# DCS Navaid and Airfield Radio Import

The offline importer builds a local, versioned view of installed terrain
`Beacons.lua` and `radio.lua` files. It does not change DCS, execute Lua,
connect to the bridge, tune a radio, or establish that a frequency is usable by
an aircraft.

## Run in VS Code

Open `examples/navigation/import_dcs_beacons.py` and use **Run Python File**.
It uses the same settings as the connected navigation client:

- `config/navigation.json`: shared defaults.
- `config/navigation.local.json`: optional, Git-ignored overrides. Set
  `navaids.dcs_directory` to the selected DCS installation.
- `navaids.cache_directory`: defaults to `../tmp/navaids`, relative to the
  configuration directory. See [Navigation Client Workflow](WORKFLOW.md).

Neither the normal bridge server nor a DCS mission is required. This is an
offline exception to the usual connected SDK example workflow.

Alternatively, with the package installed:

```powershell
python -m moosebridge.navaids --dcs-root "G:\Games\DCS World Testing" --output "D:\Coden\Python\PyDCS\MoosePyBridge\tmp\navaids"
```

The console prints counts, issue totals and the report's absolute path. Exit
code 0 means the import completed, **not** that every record is valid. Exit code
2 means an import/source/output failure. Review the English report before using
the data in any later navigation feature.

## Sources and parser boundary

Discovery covers immediate terrain directories with case-insensitive
`Beacons.lua` and `radio.lua` filenames. Supported table formats are Beacon 2
and radio 3. Literal empty tables are valid; missing/malformed tables are not
treated as empty.

The importer reads:

- Terrain Beacon tables, preserving symbolic types, record source lines, raw
  fields, unmodified record text and unknown additional data fields.
- Terrain radio tables, preserving `radioId`, roles, callsign variants,
  frequency bands/modulations, source lines and raw records. Frequencies remain
  shared ATC alternatives; the source does not assign one frequency to each role.
- Terrain `entry.lua` metadata for the actual `theatre.id`. For example,
  `GermanyColdWar` is the folder but `GermanyCW` is the terrain ID. Missing or
  unreadable metadata produces a warning and a null ID, not a guessed ID.
- `BeaconTypes.lua`: integer type/state declarations and the ILS channel-pair
  table. Legacy conversion functions are not executed.
- `BeaconSites.lua`: system names, default/child mappings and system/device
  tables. Signal declarations distinguish, for example, VOR/DME from VORTAC.
- `FrequencyBands.lua` and `ModulationTypes.lua`: symbolic radio declarations.
  Legacy Windows-1251 terrain files are decoded explicitly and reported.
- `wsTypes.lua`, when present, is retained and hashed as an imported dependency;
  it is not evaluated or used to resolve additional beacon types in this MVP.

The restricted reader supports data tables, literal values, symbolic references,
translation string wrappers and preserved arithmetic expressions. It is not a
general Lua interpreter: `dofile`, `require`, constructors and arbitrary function
calls are never run. Duplicate table keys, unsupported calls inside data,
unknown formats, non-finite literals and code after the Beacon table fail the
file import explicitly. Numeric expressions are retained, not silently evaluated.
Source files are bounded to 8 MiB and table nesting to 40 levels.

Airfield `radioId` values matching `airfield<UID>_<index>` retain the numeric
UID for live resolution. Nonstandard IDs remain unresolved and visible; the
importer never guesses an AIRBASE from a callsign or display name.

## Validation and meaning

Each record retains raw data alongside normalized fields, issues and a
`validation_status` (`no_issues`, `review`, or `invalid`). None of these states
means live-verified or suitable for a particular aircraft. `live_verified` is
always false in this offline importer.

Checks currently include:

- Unknown types, missing IDs/names/callsigns, duplicate IDs within a map.
- Missing or invalid numeric tuning data, channel bounds, unclassified
  frequencies, frequency/channel conflicts, and declared-mode conflicts.
- Explicit frequency roles: homing tuning, VHF paired tuning, ILS localizer
  tuning, actual paired glideslope carrier, or UHF DME/TACAN frequency.
- Valid finite local/geographic positions. No terrain-height fallback, chart
  offset or grid/TRUE/magnetic conversion is applied.
- Non-ASCII callsigns and a limited set of visually confusable Latin/Cyrillic
  identifiers. These checks never merge or rewrite source identifiers.
- Unequal ILS localizer/glideslope counts per airfield ID. This is only a
  structural warning, not automatic runway pairing or proof of a broken ILS.

An omitted frequency can be legitimate when a channel is provided. An unused
zero channel does not by itself invalidate an NDB. A VHF frequency in a TACAN
or DME record is not automatically interpreted as its UHF carrier. Channel modes
from complete default signal declarations are explicitly labeled
`default_system_declaration`; explicit source modes remain `explicit`.

No-issue records may still be inaccurate. Warnings may be legitimate source
conventions, and receiver behavior ultimately requires a DCS test. No standard
service volume, signal range, tuned cockpit state or navigation clearance is
inferred from antenna/power declarations.

## Snapshot/cache policy

The selected installation remains the source; generated data lives outside it.
Output paths inside DCS are rejected. Nothing is copied into MOOSE.

Each snapshot contains:

- `manifest.json`: installation, schema/importer versions, SHA-256 source and
  artifact hashes, terrain inventory, map file references and issue totals.
- `definitions.json`: parsed common declarations and declared signal metadata.
- `maps/NNN.json`: one catalog per terrain, including raw records and issues.
- `sources/NNN.lua`: exact local source bytes for provenance and reproducibility.
- `report.md`: readable English inventory and all validation findings.

The numeric filenames are mapped back to original paths by the manifest. These
are private generated caches, ignored by Git; do not commit installed DCS source
files as project fixtures. Automated tests use small synthetic examples.

On each invocation the importer hashes the discovered source set. Matching
schema/importer/source hashes and intact artifact hashes permit cache reuse.
Otherwise it builds a new snapshot. This MVP rebuilds the small whole inventory
when any dependency changes. Timestamps or a map version such as `EA` are not
used as evidence of unchanged content. Recheck source hashes before publication
to catch a DCS update during import.

New files are staged before the snapshot directory is published.
`current.json` is replaced atomically only after all map tables have been read
successfully. Record-level errors do not discard other records: a completed
snapshot can contain invalid records that must be filtered by future consumers.
File/common-definition parse failures produce a failed report and leave the
previous pointer intact. Early I/O/discovery failures are reported in the console
and also leave it intact. There is **no silent fallback** to old data.

Historical snapshots are retained, including failed and damaged snapshots; no
automatic pruning is performed. Corrupt artifacts are rebuilt into a separate
snapshot. The importer does not edit a prior snapshot in place.

## Installation audit

The initial full audit of the user's installation on 2026-08-31 imported 14 maps
and 1,253 entries, including valid empty tables for Normandy, TheChannel and
MarianasWWII. Known source findings were retained, including Nordholz's undefined
`BEACON_TYPE_AIRPORT_TACAN`, suspicious tuning values, unequal ILS component
counts at Banak/Ramon and the distinct `RC` / `RС` spellings on Sinai.
These observations describe that snapshot, not every DCS release.

## In-game Navaids menu

Run `examples/sdk/run_navigation_menu.py` once in VS Code. It waits for the
normal daemon and mission, checks Lua and the cache before activation, and
stays running across mission changes. Restart the mission after a Lua update.
No separate server or script is needed for Navaids. The menu is available for
occupied groups and later slot entries:

- **Radio menu > F10 Other > Navigation > Navaids**
- Types: **TACAN**, **VOR**, **DME**, **VOR/DME**, **VORTAC**, **NDB**, **ILS**.
- **More types**: **RSBN**, **PRMG**, **ICLS**, **Other / unknown**.
- **Selected station**: explicit F10 display actions for the last successfully
  inspected station. This ninth top-level entry still reserves DCS Back.

All type lists are initialized once when a new group menu is created, using one
shared snapshot of the current aircraft position. This works both for an
already occupied slot when the script starts and for a later slot entry.
Wait for `Navaids initialized` in the Python console, then open a type directly;
if it was already open, reopen it to see the new entries. No initial refresh is
needed. Use **Refresh nearby** inside a type to update its ordering later.
Each page contains at most six stations, **Refresh nearby**,
and applicable **Previous page / Next page** commands. All menus stay at nine
custom entries or fewer, reserving a tenth position for DCS Back. This applies
to the type list as well as station pages; no entries are silently discarded.
Empty types retain Refresh nearby and report zero entries.

Initialization sends one batch for all eleven types and logs a console summary,
without eleven cockpit messages, station selection, map drawing or periodic
polling. A type already refreshed manually is not overwritten by a delayed
initialization. Duplicate creation events do not resample; a new menu session
after re-entry or recovery initializes again. If the reference position is not
ready or is ambiguous, initialization logs a warning and manual Refresh nearby
remains available once the problem is resolved. Missing caches follow the
activation-level rules below.

The shared configuration selects the importer cache and DCS installation.
Before each activation the client verifies snapshot artifact hashes and source
hashes against that local installation, then pins the catalogs in memory for
that activation. Missing or outdated caches disable Navaids with a startup
warning, without blocking other navigation actions. Terrain selection uses
the active mission's exact `theatre.id`, not a folder-name guess. Missing,
ambiguous or stale catalogs produce an English error with no stale fallback.
Run the importer after a DCS update; the next activation or a script restart
checks the cache again. Refresh
nearby updates aircraft-relative ordering, **not** the pinned source snapshot.
Agreement with a local installation does not verify a remote server's map build.

Ordering uses horizontal distance from the sole occupied player aircraft in
the group. Multiple crew seats in that aircraft are supported; multiple player
aircraft in one group are rejected as ambiguous. No FLIGHTGROUP is required.
Order and menu-label distances stay fixed until Refresh nearby, so movement
does not reshuffle stations while paging. Selecting a station samples position
again and sends source identity/type, channel/frequency when present, current
horizontal distance in NM and TRUE bearing to the group and Python console.
Cockpit tuning and waypoints are unchanged; no periodic polling is started.

## In-game Airfields / ATC menu

**Radio menu > F10 Other > Navigation > Airfields / ATC** is initialized when a
new player-group menu is created. Python supplies the imported `radio.lua` UIDs;
Lua iterates the active mission's MOOSE `AIRBASE` objects and compares each
`AIRBASE:GetID()` value. The matching live object supplies the authoritative
name and coordinates. No name-based fallback is used.

Airfields are ordered by horizontal distance from the player aircraft. Each
page has at most six airfields plus **Refresh nearby** and applicable
**Previous page / Next page** commands. Selecting an airfield reports:

- live AIRBASE name, numeric ID, distance and TRUE bearing;
- source callsign variants and the shared Ground/Tower/Approach roles;
- available HF, VHF Low, VHF and UHF frequencies with modulation;
- catalog/review status and unresolved-source limitations.

The action is read-only and does not tune either Hornet radio. Empty frequency
tables are shown as unavailable rather than filled from external data. `[!]`
marks source issues. A DCS update can change both `radio.lua` and AIRBASE UIDs;
rerun the importer after an update. A live DCS menu test remains pending.

### Explicit F10 station display

A station click still only displays information and remembers the station for
subsequent map actions. It neither creates nor moves a marker, enables guidance,
nor selects a cockpit waypoint. Under **Navaids > Selected station**:

- **Show on F10**: display a read-only labeled marker and amber position symbol
  for the selected station. The label includes identity, source type,
  channel/frequency when available, group name and any source-review flag.
- **Show with bearing line**: display the same marker with an amber line from
  the live aircraft position at execution time. This is a static snapshot, not
  a moving line or Direct-to guidance. Repeat the action to update its origin.
- **Hide from F10**: remove this session's navaid marker/symbol/line, leaving its
  selection and Mission Editor route display untouched. Hiding is idempotent.

Both displays are visible to the group's coalition, not only to the group.
The 100 m position symbol is a visual locator, **not a signal coverage radius**.
Station browsing, paging and Refresh nearby do not change an existing display.
Another explicit Show replaces the previous navaid display; Show without a line
also removes a previously displayed bearing line. There is one navaid display
per group-menu session, owned separately from the cyan route overlay.

Lua checks selection acknowledgement, current reference aircraft, terrain and
session again before drawing. Late actions cannot draw another selection or
address a replacement slot session. Last occupant leave, mission end, script
shutdown or replacement removes this session's navaid display as well as its
route overlay, without removing other groups' or scripts' drawings.

Live F10 display test is **pending**:

1. Restart the mission and navigation script after the Lua update; keep the
   normal daemon running. Select TACAN or NDB station details.
2. Check that merely inspecting the station does not create a marker. Choose
   Selected station > Show on F10; inspect the source-position symbol and label.
3. Choose Show with bearing line. Check its origin against the aircraft's
   position at the time of the click; no flight is needed for this check.
4. Inspect another station. The displayed station must remain unchanged until
   another Show action. Check that paging does not change the display either.
5. Show the route and hide the navaid display; the cyan route must remain.
   Repeat Hide, then Show without a line and check that no old line remains.
6. Leave/re-enter the slot and stop the script. Check cleanup and that a new
   session requires a fresh station selection. Test other-group isolation when
   a second occupied group is available.

Automated tests cover selection/show separation, menu limits, stale responses,
reference changes, label-failure cleanup and independent overlay ownership.

### Data quality and initial menu validation

Records without usable local/geographic coordinates are omitted from the list
and counted. **[!]** marks record or catalog validation issues. Records with
questionable tuning values can still be inspected, with explicit warnings;
they are not tuning recommendations. Undefined types stay under Other / unknown
instead of being guessed. ILS/PRMG/ICLS LOC and GS are separate components, not
automatically paired approaches. Channel modes from common default-system
declarations are labeled as such. Nearby does not guarantee reception, coverage,
working in-game implementation or compatibility with the F/A-18C.

Lua owns menu lifetimes and checks group/session ownership, occupied reference
aircraft, terrain, page revision and superseded page requests before updates.
Old callbacks cannot act on replacement pages or slot sessions. Leaving the last
occupied aircraft, stopping the script, mission end or replacing the script run
removes its menu; per-session Python lists are discarded with that session.

Initial DCS menu test: **PASS**, confirmed by the user on 2026-08-31 with
`GROUP:Test Hornet` / `Test Hornet 1-1` on Caucasus, snapshot `65adf65cfd17`.

- TACAN Refresh nearby returned six entries on one page, with no entries
  omitted for missing coordinates.
- Station details reached both the cockpit and Python console: TACAN
  `BTM | Batumi` (source channel 16X) and NDB `LU | Batumi` (430 kHz), including
  aircraft-relative horizontal distance and TRUE bearing.
- Next page and Previous page worked for the NDB list.

This confirms menu interaction and message delivery, not actual signal
reception or agreement with tuned cockpit instruments. Additional live checks
remain open: automatic population on script start and later slot entry,
More types, empty lists, refresh after aircraft movement,
leave/re-entry cleanup, and isolation between multiple player groups. Automated
Python and Lua tests cover pagination, stale callbacks, data selection and
lifecycle guards.

## Deferred integration

- Add explicit Direct-to guidance for a selected station, independently of
  the Mission Editor route and without changing cockpit waypoints. Browsing
  stations must not silently change the active navigation target.
- Provide an explicit offline/stale-cache mode; current source verification
  requires the configured local installation. The importer runs explicitly,
  not as a background update watcher.
- Add version-scoped, reviewed correction overrides without altering sources.
- Compare snapshots and reconcile renamed/reindexed beacons using more than ID.
- Match Navigraph data without overwriting the DCS catalog or licensing boundaries.
- Add mission-created/mobile beacons and live receiver/aircraft compatibility checks.
