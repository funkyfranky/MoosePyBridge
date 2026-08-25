# SDK Example Catalog

These examples exercise the public Python SDK against the MoosePyBridge daemon
and a live DCS/MOOSE mission. Unless noted otherwise, start `run_server.ps1`,
start the DCS mission, and edit the constants near the top of the selected
script before running it.

```powershell
python examples/sdk/monitor_global_picture.py
```

## Safety Classes

| Class | Meaning |
|---|---|
| Read-only | Refreshes snapshots or reads retained events without changing DCS. |
| Overlay | Temporarily draws and removes F10 map diagnostics. |
| Mission-changing | Creates AUFTRAGs, changes ownership, or changes diplomacy. |
| Destructive | Deliberately damages or destroys a DCS object. |
| Offline/build | Generates or inspects local datasets; DCS may be optional. |

Stop periodic monitors with `Ctrl+C`. Examples use English output and the
default control endpoint `127.0.0.1:42001`.

## Start Here

| Example | Class | Purpose |
|---|---|---|
| `release_smoke_test.py` | Overlay | Validate the SDK, bridge, snapshots, map datasets, and one temporary F10 markup. |
| `check_conflict_readiness.py` | Read-only DCS | Validate the active theater, strategic scope, both coalition force structures, INTEL, capabilities, and admitted objectives before starting conflict control. |
| `recommend_bilateral_strategy.py` | Read-only DCS | Rank feasible blue and red strategic candidates, explain all decisions, and retain an audit without creating Goals, Plans, or AUFTRAGs. |
| `activate_bilateral_strategy.py` | DCS runtime state | Revalidate and atomically activate one selected decision per coalition as a Goal and validated Plan without creating AUFTRAGs. |
| `execute_bilateral_strategy.py` | DCS runtime state | Activate one bounded decision per coalition, then approve and execute both plans concurrently through their MOOSE COMMANDERs. |
| `run_bilateral_conflict.py` | Mission-changing | Run a finite recurring blue/red conflict with independent cadence, concurrent COMMANDER execution, cooldowns, and cycle audit. |
| `monitor_global_picture.py` | Read-only | Print and validate the complete global picture periodically. |
| `run_auftrag_lifecycle.py` | Mission-changing | Run the representative bounded ONGUARD lifecycle used by the release test. |
| `test_mission_reset.py` | Mission-changing | Verify mission-end/restart generations and mission-scoped state cleanup. |

`auftrag.py` remains as a compatibility entry point for
`run_auftrag_lifecycle.py`.

`example_support.py` provides shared repository bootstrap, daemon connection,
and error handling for executable examples. It contains no mission-specific
configuration and is not intended to be run directly.

## Monitoring

| Example | Class | Purpose |
|---|---|---|
| `monitor_commanders.py` | Read-only | Print COMMANDER, LEGION, asset, and mission status. |
| `monitor_legion.py` | Read-only | Print one LEGION or all LEGION objects periodically. |
| `monitor_intel.py` | Read-only | Print INTEL agents, contacts, and clusters. |
| `monitor_group_distance.py` | Read-only | Track the distance between configured groups. |
| `monitor_relationship.py` | Read-only | Print diplomacy state, escalation, incidents, and doctrine. |
| `monitor_airbase_capture.py` | Read-only | Observe airbase ownership and objective transitions. |
| `monitor_unit_lost.py` | Destructive | Trigger an explosion and verify the resulting destruction event and snapshots. |
| `territories.py` | Read-only by default | Inspect passive TERRITORY objects; optional owner changes are disabled by default. |

## Missions And Planning

| Example | Class | Purpose |
|---|---|---|
| `recon_intel_test.py` | Mission-changing | Assign RECON and assess detections attributed to its assets. |
| `test_arty_weapon_selection.py` | Mission-changing | Validate artillery ranges, weapon flags, synchronization, and execution. |
| `select_arty_cohort.py` | Mission-changing | Rank fire-support candidates and execute the selected option. |
| `plan_capture_goal.py` | Mission-changing | Build, approve, and execute a CAPTURE strategic plan. |
| `plan_defend_goal.py` | Mission-changing | Build, approve, and execute a DEFEND strategic plan. |
| `plan_destroy_goal.py` | Mission-changing | Execute DESTROY strike rounds until weighted damage is sufficient. |
| `attack_strategic_objective.py` | Destructive | Plan and optionally execute a verified SCENERY infrastructure attack. |
| `plan_deny_runway_goal.py` | Mission-changing | Plan and execute runway denial. |
| `run_blue_conflict_controller.py` | Mission-changing | Run one bounded rule-based strategic decision cycle. |
| `generate_strategic_objectives.py` | Offline/build and read-only DCS | Generate scoped objectives from territories and normalized infrastructure. |

## Diplomacy And Events

| Example | Class | Purpose |
|---|---|---|
| `declare_war.py` | Mission-changing | Explicitly transition the coalition relationship to war. |
| `test_border_violation.py` | Mission-changing | Validate tolerance timing, deduplication, and incursion escalation. |
| `test_opszone_relationship.py` | Mission-changing | Validate future OPSZONE capture events and diplomacy scoring. |
| `test_capture_reaction.py` | Mission-changing | Capture one configured OPSZONE, confirm its persistent combat patrol, and validate the opponent's selected recapture reaction. |

## Topography And Routing

| Example | Class | Purpose |
|---|---|---|
| `capture_topography_coverage.py` | Offline/build | Export mission-defined all/low/high topography coverage areas. |
| `verify_topography_overlay.py` | Overlay | Draw a bounded sample of normalized topography in DCS F10. |
| `verify_road_alignment.py` | Overlay | Compare OSM road samples with native DCS roads. |
| `verify_surface_alignment.py` | Overlay | Compare normalized land/water samples with DCS surface types. |
| `draw_coastline_overlay.py` | Overlay | Draw the normalized coastline in DCS F10. |
| `inspect_ground_route.py` | Overlay | Compare strategic Python routing with a native DCS road route. |
| `benchmark_road_routing.py` | Read-only | Benchmark Python A* and native DCS path calculation. |

## Infrastructure

| Example | Class | Purpose |
|---|---|---|
| `verify_scenery_representation.py` | Overlay/build | Verify any normalized infrastructure, railway, settlement, bridge, or junction feature against fixed DCS scenery. |
| `monitor_scenery_verification_markers.py` | Overlay/build | Continuously turn live F10 `verify OBJECT_ID` markers into reviewed scenery surveys. |
| `test_scenery_damage.py` | Destructive | Explode any confirmed fixed scenery target and assess its generic feature baseline. |

## Inspection

| Example | Class | Purpose |
|---|---|---|
| `inspect_ammunition.py` | Read-only | Print classified ammunition for configured groups. |

## Conventions

- Configuration belongs in named constants near the top of each script.
- Object IDs, zones, LEGIONs, and COMMANDERs must match the active mission.
- Read-only examples do not create AUFTRAGs or persist strategic state.
- Overlay examples remove their own F10 markups before exiting.
- Destructive examples require an explicit armed switch or a verified target.
- Compatibility entry points contain no independent workflow logic.
