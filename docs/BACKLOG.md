# MoosePyBridge Backlog

This file tracks concrete work that is not yet complete. `ROADMAP.md` describes
the architectural direction and completed foundations; this backlog is the
shorter working list for upcoming implementation.

Priorities:

- **P1**: Important for the next usable conflict-simulation increment.
- **P2**: Valuable after the current decision and execution loop is stable.
- **P3**: Longer-term hardening or extension.

## P1 - Decision and execution

- [x] **Add a minimal autonomous conflict controller.** Run one bounded Python
  decision loop per coalition: refresh the appropriate global or INTEL picture,
  generate CAPTURE/DEFEND/DESTROY candidates, apply relationship and doctrine
  constraints, select a capacity-feasible portfolio, submit approved plans
  through COMMANDER, and reassess on relevant events. Limit concurrency and
  decision frequency so the first scenario remains understandable and
  auditable rather than becoming a full campaign engine. The first controller
  supports one coalition, one selected goal per cycle, explicit scenario
  objectives, automatic war initialization, and CAPTURE/DEFEND/DESTROY through
  the existing portfolio, approval, COMMANDER execution, and audit paths.
- [x] **Apply relationship constraints and doctrine to goal selection.** Block
  offensive goals that are politically invalid in peace or a ceasefire, bound
  limited-conflict goals to their authorized area/effects, and use doctrine
  biases when ranking otherwise valid concurrent goals. Relationship remains a
  hard policy boundary; doctrine is only a preference.
- [ ] **Broaden operational planning beyond CAPTURE, DEFEND, DESTROY, and runway denial.** Generate
  and execute plans for remaining DISABLE effects, PROTECT, and INTERDICT while
  preserving the existing validation, approval, audit, and replanning path.
- [ ] **Add strategic goal selection and prioritization.** Let Python compare
  possible goals using strategic value, current control, visible threats,
  available capabilities, expected cost, and uncertainty. Start with a
  deterministic rule engine before adding an LLM decision layer. The first
  capacity-aware portfolio selector is complete: it permits multiple concurrent
  goals, applies explicit priority ordering, and prevents provisional COHORT
  overbooking across candidate plans. Threat, cost, uncertainty, and objective
  relationship scoring remain to be added.
- [x] **Close the deterministic strategic feedback loop.** Reassess active goals and plans
  after objective ownership changes, losses, INTEL changes, mission outcomes,
  and asset availability changes without duplicating MOOSE tactical behavior.
  The event monitor and policy now produce explicit keep, wait, replan, and
  abort decisions. Temporary shortages preserve active MOOSE missions;
  persistent shortages use DCS mission time and request an approved replan.
  Only terminal goals and unsafe friendly targets trigger automatic aborts.
- [ ] **Relate INTEL changes to goals before proposing replans.** New, lost, or
  reacquired contacts currently remain planning context because a global INTEL
  event does not prove relevance to every active plan. Add spatial, target, and
  information-requirement matching before emitting plan-specific follow-up or
  replan proposals; never replace running AUFTRAGs directly.

## P1 - Intelligence and RECON

- [ ] **Optional satellite picture.** Provide an explicit omniscient INTEL
  source that can add all relevant groups as known contacts independently of
  normal DCS detection. The Lua integration should use
  `INTEL:KnowObject(Positionable, RecceName, Tdetected)` and clearly identify
  the synthetic recce source, for example `Satellite`. This mode must remain
  opt-in and separate from the normal coalition-private, sensor-derived
  tactical picture.
- [ ] **Define satellite refresh semantics.** Decide whether satellite data is
  a one-time pass, a periodic pass, or operator-triggered; define coalition
  scope, refresh interval, and how `Tdetected` and stale/lost contacts behave.

## P2 - Forces and sustainment

- [ ] **Track remaining unit strength inside spawned asset groups.** Planning
  now derives the initial unit count automatically for homogeneous COHORT
  templates and respects `COHORT:SetGrouping()`. Extend the runtime force model
  so casualties within a surviving group reduce its effective strength and can
  trigger reinforcement, defense, and replanning decisions without treating
  every surviving asset group as fully effective.
- [ ] **Extend ammunition/range-aware ranking beyond artillery.** ARTY now uses
  weapon classification, DCS weapon flags, current ammunition, firing position,
  and min/max task ranges for feasibility. Apply current losses, readiness, and
  ammunition evidence to other combat missions where it changes a real
  operational decision.
- [ ] **Expand logistics planning.** Model ammunition supply, rearming, force
  sustainment, and transport as operational dependencies rather than only
  optional support missions. Fuel remains irrelevant for DCS ground and naval
  units unless a later simulation layer adds it deliberately.
- [ ] **Improve force-effectiveness estimates.** Combine unit role, DCS
  attributes, life, active state, ammunition availability, weapon reach, and a
  small logistics contribution for territorial control and planning.

## P2 - Strategic infrastructure

- [x] **Inventory current infrastructure candidates and DCS representation.**
  The initial inventory is documented in `INFRASTRUCTURE_CANDIDATES.md`. It
  separates raw OSM features, normalized operational sites, bounded DCS
  scenery verification, and scenario-approved strategic objectives. Power
  generation is the recommended first site category.
- [ ] **Bring the remaining infrastructure candidates to the transport-cache
  standard.** Define a small, typed taxonomy for energy, fuel and storage,
  industrial sites, ports and harbours, rail facilities, communications, and
  other operationally relevant infrastructure. Convert raw OSM features into
  stable point or site objects with source identifiers, provenance, geometry,
  member counts, and reproducible versioned artifacts. Keep the taxonomy
  theater-aware: the first `EnergySite` model and GermanyCW policy exclude
  modern wind, solar, biogas, and battery sites without imposing that choice
  on other maps. `MilitarySite` is a separate type on the shared site base.
  The normalized energy cache, SDK representation, browser markers, and
  bounded DCS scenery-survey example are implemented. Fuel/storage,
  industrial, port, rail, and communications site builders, clustering, and
  persisted DCS verification remain open. Keep the model extensible, but do
  not retain every available OSM tag in the operational model.
- [ ] **Cluster infrastructure features into meaningful sites.** Group related
  buildings, tanks, yards, platforms, terminals, and equipment into one
  operational location where they represent the same real facility. Use
  category-specific clustering and preserve membership for diagnostics so a
  refinery, power station, port, or rail yard is not represented by hundreds of
  independent target markers.
- [ ] **Add category-specific importance and dependency analysis.** Rank sites
  with transparent evidence appropriate to their role: capacity and network
  position for energy, storage and distribution role for fuel, production and
  facility extent for industry, connected transport modes for ports, and graph
  centrality or detour impact for rail facilities. Record uncertainty and the
  reason for every tier; avoid applying the road-junction score unchanged to
  unrelated infrastructure.
- [ ] **Expose typed infrastructure through the SDK and browser map.** Give each
  category a bounded map representation, useful detail panel, importance-based
  styling, zoom-dependent density, and filters for category and
  critical/high/medium/low importance. Large raw source layers remain optional
  topographic context; the strategic infrastructure layer contains only
  normalized sites.
- [ ] **Validate infrastructure against the GermanyCW DCS theater.** Compare
  high-value candidates with the DCS F10 map, Mission Editor, local scenery,
  and available historical sources. Retain `confirmed`, `approximate`,
  `historically_uncertain`, and `not_represented_in_dcs` evidence instead of
  silently treating modern OSM as authoritative for the DCS era.
- [ ] **Derive strategic objectives only after infrastructure normalization.**
  Add an explicit policy that selects confirmed or scenario-approved sites and
  converts them into multi-component `StrategicObjective` objects. Objective
  value, ownership, desired effect, targetability, and component weights must
  remain scenario/Python decisions; discovering an OSM facility must never
  create an attack goal automatically.
- [ ] **Model infrastructure state and effects separately from geography.**
  Associate known DCS statics, map objects, airbases, zones, or scenario
  components with a normalized site and derive operational, damaged, disabled,
  destroyed, repaired, or captured state from events and snapshots. Keep the
  immutable source site intact so damage and coalition control do not rewrite
  the geographic cache.

## P2 - Deferred transport infrastructure

- [ ] **Add importance filters for bridges and transport junctions.** Allow
  critical, high, medium, and low locations to be shown independently without
  changing their current zoom-dependent level of detail.
- [ ] **Validate strategic bridge and junction locations against DCS.** Sample
  representative motorway interchanges, urban junction complexes, water
  crossings, and the mainland-Rugen corridor. Store bounded theater corrections
  where DCS road topology materially differs from OSM rather than increasing
  global clustering radii.
- [ ] **Connect transport locations to runtime disruption state.** Associate a
  bridge or junction with scenario-defined DCS objects or destruction zones,
  retain intact/damaged/blocked/repaired state, and invalidate affected cached
  routes when that state changes. OSM geometry remains immutable and a DCS
  object loss must not imply a blocked corridor without explicit association.
- [ ] **Use transport criticality in later strategic reasoning.** Let Python
  propose protection, interdiction, repair, or rerouting decisions from route
  dependency and current state. Keep importance as planning evidence rather
  than automatically turning every high-tier bridge or junction into a goal.

## P2 - Deferred COHORT ranking

- [ ] **Calibrate COHORT score assumptions with live DCS scenarios.** Validate
  the current 50% mission-performance, 30% skill, and 20% response weighting,
  the neutral values for unknown inputs, and the 900-second response reference.
  Introduce mission- or domain-specific values only when observed behavior
  demonstrates a real need.
- [ ] **Replace timing fallbacks with measured capability where available.** Use
  reliable COHORT, template, or spawned OPSGROUP preparation and movement data
  instead of fixed air, ground, naval, and artillery speeds without adding
  periodic polling solely for ranking.
- [ ] **Decide whether force size belongs in the score.** Asset availability is
  currently a hard capacity constraint and unit/group count is deliberately not
  a score component. Revisit combat mass, losses, and remaining unit count only
  with a model that does not reward oversized formations indiscriminately.
- [ ] **Make ranking diagnostics reflect the two-stage decision.** Show only
  COHORT alternatives for the selected AUFTRAG type under `cohort_options`, and
  list lower-priority mission types separately as doctrinal fallbacks. Retain
  the complete raw assignment metadata for audit and debugging.
- [ ] **Verify and expose actual MOOSE recruitment.** Compare Python's predicted
  capacity allocation with the COHORTs and assets recruited by COMMANDER, then
  retain the actual selection in events, execution diagnostics, and audit data.
  Do not assume that repeated `AssignCohort` calls imply score-order preference.
- [ ] **Broaden safe ARTY fallback recruitment.** Synchronize the selected
  weapon range for every otherwise qualified fallback COHORT before submission.
  Until then, only the selected ARTY COHORT and already synchronized alternatives
  with the same weapon flag may enter the COMMANDER recruitment pool.
- [ ] **Validate COHORT skill semantics.** Confirm all values used by the MOOSE
  branch and DCS templates, including `Random` and numeric forms, then replace
  neutral mappings only where the runtime meaning is unambiguous.

## P2 - Tactical picture

- [ ] **Profile and optionally pre-generate vector tiles for concurrent users.**
  Dynamic per-layer MVT generation and in-memory/browser caching are now in
  place. Measure multiple concurrent viewers and dense high-detail areas before
  adding persistent tiles or an MBTiles build step.

- [ ] **Verify the GermanyCW topography baseline against DCS.** The first
  versioned OSM import and browser layers cover water, major roads, railways,
  settlements, and infrastructure candidates. Add adaptive DCS surface,
  seabed, road-route, and local scenery checks; retain corrections in the
  theater cache instead of polling the complete terrain during missions.
- [ ] **Add historical topography enrichment.** Evaluate GHSL 1990 settlement
  footprints, OpenHistoricalMap, and dated Wikidata landmarks for GermanyCW.
  Preserve provenance and uncertainty, and require explicit confirmation
  before external infrastructure becomes a strategic objective.
- [ ] **Expose goals and operational plans on the browser map.** Show objective
  status, coalition intent, active plan phase, assigned missions, warnings, and
  blocked reasons with coalition-appropriate visibility.
- [ ] **Add historical analysis controls.** Allow inspection of losses, INTEL
  changes, frontline movement, objective ownership, and mission activity over
  a selected DCS-time window.

## P2 - Deferred diplomacy

- [ ] **Complete optional escalation sources.** Add weapon-fire,
  strategic-object-attack, and ceasefire-violation incidents only where a
  reliable DCS or MOOSE event provides attribution. Keep the current
  event-driven design and deduplication; do not introduce polling solely for
  diplomacy.
- [ ] **Validate Kill-event reliability in live DCS missions.** Confirm that
  `EVENTS.Kill` consistently supplies killer and target coalition/object data
  for relevant air, ground, and naval kills. Only if live evidence shows gaps,
  add a bounded last-Hit cache correlated with UnitLost/Dead and mark it as
  lower-confidence evidence.
- [ ] **Complete ceasefire and de-escalation policy.** Define how a ceasefire is
  negotiated or imposed, how long it lasts, which violations terminate it, and
  under which explicit conditions escalation can decrease. Avoid automatic
  score decay until its strategic meaning is clear.
- [ ] **Validate limited-conflict authorization in DCS.** Exercise geographic
  and effect restrictions with simultaneous goals and confirm that Python
  blocks out-of-scope offensive action while permitting defense.

## P3 - Platform hardening

- [ ] **Add authenticated remote clients.** Build authentication and
  authorization on top of the existing declared client identity and audit
  envelope before exposing the control service beyond trusted networks.
- [ ] **Continue protocol and snapshot hardening.** Expand typed snapshots and
  schemas only where required by operational features, with replay and
  compatibility tests for state-changing events.
- [ ] **Add long-running DCS integration scenarios.** Exercise reconnects,
  mission restarts, multiple clients, audit restore, event ordering, and map
  updates over extended missions.
- [ ] **Build platform-specific mobility graphs from surface regions.** Keep
  physical components immutable, connect ground regions through verified road
  bridges, and constrain naval regions by vessel class, water width, depth
  evidence, and bridge clearance where such evidence exists. MOOSE/DCS remains
  responsible for the final tactical route.
- [ ] **Prebuild detailed road-graph tiles for interactive continental
  routing.** The hierarchical router already filters regional shards to occupied
  corridor cells, but cold queries must still decompress their source shards.
  Persisting independently loadable 25-km graph tiles should reduce both cold
  assembly and warm A* time for long routes.
- [ ] **Scale transport criticality to the complete theater through routing
  shards.** Regional graphs now calculate bounded bridge/junction detours and
  transparent importance scores, but the 94-second MV run must not be applied
  naively to the 32-million-node graph. Analyze occupied routing corridors or
  prebuilt graph tiles and distinguish "no route inside the analysis limit"
  from proven graph disconnection.
- [ ] **Pre-clip large PBF sources before Pyrosm network extraction.** Worker
  isolation prevents cumulative memory growth, but Pyrosm still decodes each
  complete source; an osmium/GDAL clipping stage should reduce the high peak
  memory of sources such as Czechia without changing the resulting graph.
- [ ] **Calibrate Python road speeds and connector handling against DCS.** Use
  representative wheeled, tracked, and logistics movements; keep all roads
  bidirectional and unrestricted, with bridges retained as metadata only.
- [ ] **Quantify coastline displacement against DCS.** Sample transects across
  OSM shorelines and compare the DCS `land.getSurfaceType()` transition while
  retaining uncertainty near complex harbour and shallow-water geometry.
- [ ] **Refine accepted 500 m shoreline artifacts only where operationally
  relevant.** Narrow channels, tiny islands, and historical DCS/modern OSM
  differences are tolerated for strategic planning unless they create a false
  ground or naval connection.
## Recently completed

- [x] Detailed road graphs now produce a versioned strategic transport cache.
  Connected and nearby OSM bridge structures are grouped into stable point-like
  `TransportBridge` locations with source IDs, approaches, and road classes,
  while degree-filtered motorway through
  secondary-road nodes become typed `TransportJunction` objects. Both are
  exposed through the SDK, a reproducible builder, a dedicated map endpoint,
  and independent browser layers. OSM topology is retained separately from
  future DCS damage state and military bridge-capacity assumptions.
- [x] Regional transport caches can now be enriched with bounded route-impact
  analysis. Blocking each abstract location yields road-hierarchy importance,
  alternative distance, added detour, ratio, and a transparent four-tier score;
  the map visualizes high and critical infrastructure distinctly.
- [x] Hierarchical road routing now combines the coarse ground-mobility graph,
  a 25-km occupied-cell shard index, configurable corridor filtering, and an
  in-memory detailed-graph cache. A 50-km corridor reproduced all four
  full-graph validation distances while reducing Laage-Gross Mohrdorf to about
  348,000 detailed nodes (2.7 seconds cold, 0.4 seconds warm).
- [x] The complete GermanyCW road graph now merges 29 non-empty Geofabrik
  regions through global OSM node IDs. Per-PBF worker isolation bounds retained
  memory, resumable caches record both populated and empty sources, and the
  resulting 1.48-GiB artifact contains 32,019,466 nodes and 34,235,737 edges.
  Validation found connected routes within MV and across Hamburg-Berlin,
  Frankfurt-Berlin, and Amsterdam-Berlin.
- [x] A compact Pyrosm-derived Python road router now complements native DCS
  routing. Its NumPy/CSR graph uses unrestricted bidirectional military access,
  A* travel-time routing, typed vehicle profiles, persistent NPZ artifacts, and
  side-by-side DCS/Python timing and F10 diagnostics. The initial MV artifact
  contains 562,053 nodes and 580,866 edges in 25.7 MiB.
- [x] A versioned 5 km GermanyCW ground-mobility graph combines connected land
  regions, four strategic OSM road classes, and explicit bridge-head links.
  A* routing supports conservative wheeled and tracked speed profiles while
  keeping tactical path generation in MOOSE/DCS. Selected connected corridors
  can be refined through a bounded native `land.findPathOnRoads` SDK request;
  only that native road path is drawn as the F10 diagnostic. The reproducible
  `tools/validate_ground_mobility_theater.py` check connects mainland routes
  and Rugen by bridge while correctly leaving Bornholm disconnected. The same
  Python strategic route distance and ETA now feed ground-COHORT feasibility
  and response scoring; native DCS routing remains outside candidate ranking.
- [x] OSMCoastline is the default 500 m GermanyCW land/sea baseline. The
  full-theater builder classifies directly from prepared sea polygons, skips
  unused directed-coast distance arrays, uses broadcast grid coordinates, and
  rasterizes each inland-water polygon only inside its local grid window. The
  complete 18,561-region artifact builds in bounded memory in about 140 seconds.
- [x] Prepared official OSMCoastline sea polygons can now replace the Natural
  Earth baseline in the shared surface-region builder. A downloader, bounded
  regional build mode, and independent comparison GeoJSON support reproducible
  A/B tests; the first north-Germany/western-Baltic run agreed at 99.67% of
  6,055 sampled points.
- [x] Connected GermanyCW land and water regions now combine a globally
  consistent Natural Earth 1:10m land baseline with local directed OSM
  coastline refinement and detailed OSM inland water. This removes distant
  nearest-coast Voronoi artifacts while retaining the 500 m strategic grid.
- [x] The complete GermanyCW topography is served through spatially indexed
  FlatGeobuf shards and dynamic per-layer Mapbox Vector Tiles. The browser loads
  only visible, enabled layers, applies `all`/`low`/`high` by zoom, caches tiles,
  and retains the bounded GeoJSON viewport endpoint for diagnostics.
- [x] The DCS-authored `Topography All`, `Topography Low`, and `Topography High`
  coverage was captured for GermanyCW. All 36 intersecting Geofabrik sources
  were downloaded and imported into a checkpointed 4.5-million-feature analysis
  cache. The complete 500 m surface build records one mainland, 854 islands,
  524 maritime components, and 17,512 inland-water components with complete
  source metadata.
- [x] Directed OSM coastline geometry and closed water polygons produce a
  versioned `TheaterSurfaceRegions` artifact. Four-neighbor components
  distinguish mainland, islands, maritime water, and inland water; source
  completeness and pending DCS verification remain explicit. The browser map
  exposes separate connected-land and connected-water layers.
- [x] A passive event-driven strategic feedback monitor reports goal status,
  plan feasibility, predicted allocation, INTEL context, objective changes, and
  mission outcomes. It emits `replanning_required` on real asset shortfalls and
  reports recovery without mutating plans or issuing DCS commands.
- [x] Cross-domain mission selection first fixes the first executable type in
  the doctrinal AUFTRAG order, then ranks only its COHORTs. Mission performance,
  skill, and response time produce auditable COHORT score components for air,
  ground, naval, and ARTY assignments. Distance and platform speed are combined
  in response time and unknown inputs receive explicit neutral defaults.
- [x] Generated mission requirements retain all qualified COHORTs in score
  order. Phase validation distributes capacity across that order and passes the
  same recruitment pool to MOOSE COMMANDER. ARTY alternatives remain constrained
  by weapon flag and synchronized weapon range.
- [x] Multiple feasible ARTY COHORTs are ranked by required relocation,
  COHORT-specific observed ammunition, remaining rounds, mission performance,
  range-source quality, synchronization state, and available assets. Qualified
  alternatives remain in resolution metadata for diagnostics. No unsupported
  shell-versus-rocket lethality or cost preference is inferred.
- [x] Automatic `ARTY` assignment is restricted to stationary ground or static
  targets and a concrete available COHORT with known deployment position,
  matching indirect-fire weapon flag, ammunition evidence, and a known COHORT
  `engageRange`. Mobile artillery may relocate within that range before firing.
  Missing or stale MOOSE `weaponData` is synchronized from the versioned Python
  datamine profile through `COHORT:AddWeaponRange` before COMMANDER submission.
  The complete decision and synchronization ACK are retained in plan metadata
  and audit diagnostics; execution applies the same flag through
  `AUFTRAG:SetWeaponType()`.
- [x] A central `StrategicMissionResolver` maps strategic effects and DCS/MOOSE
  target domains to prioritized AUFTRAG candidates. CAPTURE isolation, DEFEND
  counterattacks, DESTROY strikes, and runway denial use the same assignment
  path, with current COHORT support selecting the concrete mission type.
- [x] AIRBASE `DISABLE` goals default to `deny_runway`; planning accepts only
  MOOSE `Airdrome` objects and completion requires a successful object-targeted
  `BOMBRUNWAY` AUFTRAG. Unverified BOMBING/ARTY fallbacks are intentionally absent.
- [x] Weighted DESTROY goals create one task per alive, known, targetable
  component while retaining the damage threshold solely as the strategic
  completion condition. COMMANDER execution, component-state refresh,
  confirmation, audit, diagnostics, and the DCS example use the established path.
- [x] DESTROY events, pretty-print diagnostics, and audits distinguish MOOSE
  AUFTRAG outcomes from evidence-derived weighted strategic damage assessments.
- [x] Object-targeted AUFTRAG `Summary.damage` supplements snapshot component
  health cumulatively without double counting; source attribution survives audit.
- [x] DESTROY shortfalls can be replanned against already damaged components;
  the DCS example demonstrates bounded, separately approved strike rounds.
- [x] Rule-based DEFEND proposals and deadline-aware execution use the existing
  COMMANDER, validation, event, cleanup, audit, and replanning path.
- [x] Deadline-based DEFEND execution was validated in a live DCS mission with
  required ground defense and optional logistics tasking.
- [x] Browser-map layers are grouped into compact force, territorial-control,
  zone, intelligence, infrastructure, operations, and event sections.
- [x] Direct and operational RECON share route sampling and spatial coverage.
- [x] Direct `execute_recon()` results are persisted and displayed by the map.
- [x] INTEL contact acquisition is independent of AUFTRAG lifecycle and accepts
  observations from every coalition INTEL agent.
- [x] Information requirements track open, partial, satisfied, and lost states
  without cancelling a running RECON mission.
