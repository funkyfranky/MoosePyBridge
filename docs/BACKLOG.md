# MoosePyBridge Backlog

This file tracks concrete work that is not yet complete. `ROADMAP.md` describes
the architectural direction and completed foundations; this backlog is the
shorter working list for upcoming implementation.

Priorities:

- **P1**: Important for the next usable conflict-simulation increment.
- **P2**: Valuable after the current decision and execution loop is stable.
- **P3**: Longer-term hardening or extension.

## Theater portability

- [ ] **Validate the profile-driven workflow on a second DCS theater.** Create
  an isolated profile and pilot coverage area, then compare roads, connected
  surfaces, settlements, transport, railway, and representative infrastructure
  against DCS before building the full map.
- [ ] **Expose the active DCS theater ID through the bridge.** Use it to warn
  when the running mission does not match the selected theater-data profile.

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
  overbooking across candidate plans. Shared objectives now also produce
  coalition-private CAPTURE/DEFEND/DESTROY goals through one relationship-aware,
  scope-aware SDK derivation used by the conflict controller. Neutral targets
  remain protected and duplicate open goals are suppressed. Threat, cost,
  uncertainty, and richer objective relationship scoring remain to be added.
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

- [x] **Normalize cities and towns for strategic context.** City and town
  anchors now retain OSM population evidence and dates, receive transparent
  size and importance classes, and use bounded urban-landuse footprints. The
  SDK artifact and browser layer remain context until scenario policy promotes
  a settlement to a strategic objective.
- [x] **Refine settlement boundaries where conurbations matter.** Modern OSM
  administrative boundaries are retained as provenance while connected,
  hole-free urban cores provide the operational geometry. Hamburg and smaller
  towns were visually checked; internal water and parks deliberately remain
  inside instead of fragmenting a city into many pieces.
- [ ] **Add historical settlement evidence.** Compare dated population sources,
  GHSL 1990 built-up areas, and DCS scenery for selected GermanyCW cities. Keep
  present-day OSM population dates visible and never infer an exact historical
  population without a source.

- [x] **Inventory current infrastructure candidates and DCS representation.**
  The initial inventory is documented in `INFRASTRUCTURE_CANDIDATES.md`. It
  separates raw OSM features, normalized operational sites, bounded DCS
  scenery verification, and admitted strategic objectives. Power
  generation is the recommended first site category.
- [x] **Normalize energy infrastructure.** Cluster same-site generation
  components non-transitively, retain only documented grid nodes at 110 kV or
  above plus converter stations, and record role, source, output, voltage,
  footprint, scale, importance, and strategic-candidate status. GermanyCW
  continues to exclude modern wind, solar, biogas, and battery candidates.
- [ ] **Cache targeted infrastructure PBF extraction.** Persist the raw bounded
  energy and maritime results per regional source shard so category rebuilds
  do not rescan every Geofabrik PBF. The combined reader already extracts both
  categories in one pass; the remaining work is durable, invalidation-aware caching.
- [ ] **Validate representative GermanyCW energy sites.** Compare thermal and
  nuclear generation, 110/220/380 kV substations, and converter stations with
  DCS scenery. Record category-specific confidence; OSM evidence alone does
  not authorize a strategic target.
- [x] **Normalize the selected infrastructure type set.** Energy, fuel and
  storage, military, industrial, maritime, road, railway, and settlement data
  are converted into stable typed objects with provenance, geometry, source
  identifiers, member evidence, and reproducible versioned artifacts. Keep the
  taxonomy theater-aware: the first `EnergySite` model and GermanyCW policy
  exclude modern wind, solar, biogas, and battery sites without imposing that
  choice on other maps. `MilitarySite` is a separate type on the shared site
  base. The normalized caches, public SDK representations, browser layers, and
  bounded DCS scenery-survey examples are implemented.
  Fuel/storage uses explicit commodity evidence and category-specific,
  non-transitive clustering so raw tanks do not become independent strategic
  objects. Military candidates use typed roles, preserve multi-role sites,
  exclude AIRBASE-owned airfields and weak standalone bunker evidence, and keep
  training/range context non-targetable by default. Industrial sites retain
  typed production roles, products, footprint and scale, exclude generic
  estates, and distinguish ordinary locations from strategic candidates.
  Maritime sites aggregate civilian ports, terminal roles, cargo evidence,
  piers, quays, docks, harbour basins, berths, and shipyards while excluding
  marinas and keeping naval bases military. Keep the model extensible, but do
  not retain every available OSM tag in the operational model.
- [x] **Cluster infrastructure features into meaningful sites.** Energy,
  fuel/storage, military, industrial, maritime, railway, road-transport, and
  settlement aggregation use category-specific rules and preserve membership
  for diagnostics. A refinery, power station, port, rail yard, bridge, or
  junction is therefore represented as an operational location instead of
  hundreds of independent source markers.
- [ ] **Defer additional infrastructure categories.** Do not add more types to
  the current implementation increment. Preserve communications and radar
  sites, water and wastewater utilities, dams and flood-control works,
  pipelines and pumping stations, civil-government facilities, emergency
  services, and other specialist landmarks as future candidates. Add one only
  when it supports a concrete strategic decision and DCS can represent or
  scenario-author its operational effect.
- [x] **Normalize operational railway locations.** Aggregate stations, freight
  terminals, rail yards, depots, mainline junctions, and railway bridges
  into stable typed objects while keeping ordinary track as topographic and
  routing context. Targeted PBF reads are resumable through a per-source cache,
  and the browser exposes one grouped railway-infrastructure layer.
- [x] **Establish railway validation and network-analysis tooling.** Bounded
  scenery surveys and F10 overlays support DCS comparison. A compact routing
  graph measures bridge and junction loss as disconnection or detour, bridge
  clustering cannot form kilometer-long chains, and the map detail panel shows
  the resulting network impact. Remaining railway work is deferred below.
- [ ] **Add category-specific importance and dependency analysis.** Rank sites
  with transparent evidence appropriate to their role: capacity and network
  position for energy, storage and distribution role for fuel, production and
  facility extent for industry, connected transport modes for ports, and graph
  centrality or detour impact for rail facilities. Record uncertainty and the
  reason for every tier; avoid applying the road-junction score unchanged to
  unrelated infrastructure.
- [ ] **Bring the selected categories to a common maturity level.** Every
  selected type now has typed source data and a browser representation, but
  validation and operational behavior are uneven. Persist representative DCS
  verification for settlements, energy, fuel/storage, military, industrial,
  maritime, road, and railway sites; add comparable importance diagnostics;
  and expose a consistent SDK query surface before treating the categories as
  equally trustworthy planning inputs.
- [ ] **Validate maritime sites and add intermodal dependencies.** Compare a
  representative cargo port, ferry terminal, fishing port, and shipyard with
  GermanyCW DCS scenery and F10 geography. Then connect admitted ports to the
  normalized road and railway networks and record whether loss of a bridge,
  rail junction, fuel terminal, or access corridor materially isolates the
  site. Keep throughput unknown unless an explicit source provides it.
- [x] **Expose typed infrastructure through the SDK and browser map.** Each
  selected category has a public typed representation, bounded map layer,
  useful detail panel, importance-based styling, and zoom-dependent density.
  Large raw source layers remain optional topographic context; normalized
  infrastructure layers contain operational sites rather than raw components.
- [ ] **Add consistent infrastructure query and filtering ergonomics.** Provide
  SDK helpers for spatial, kind, role, strategic-candidate, verification, and
  importance queries. Add independent critical/high/medium/low browser filters
  where dense layers need them, without loading raw source data into the live
  picture.
- [ ] **Validate infrastructure against the GermanyCW DCS theater.** Compare
  high-value candidates with the DCS F10 map, Mission Editor, local scenery,
  and available historical sources. Record the simplified `unverified`,
  `represented`, or `not_represented` result plus notes and provenance instead
  of silently treating modern OSM as authoritative for the DCS era.
- [x] **Derive strategic objectives only after infrastructure normalization.**
  A versioned, theater-specific verification registry now selects
  `represented` sites with weighted fixed DCS SCENERY target components.
  Geographic candidates without such a mapping remain excluded; discovering
  an OSM facility never creates an attack goal automatically.
- [x] **Derive physical infrastructure state from immutable DCS baselines.**
  The verification registry retains every observed in-footprint DCS object
  separately from the small target subset. Mission-scoped destruction events
  and an explicit bounded follow-up survey now derive `operational`, `damaged`,
  `disabled`, `destroyed`, or uncertainty-bounded `unknown` state. Partial
  baselines cannot claim definitive site destruction, and routine verification
  does not overwrite an established baseline.
- [ ] **Add infrastructure recovery, control, and operational effects.** Model
  attacked/repaired history and coalition capture separately from physical
  health, then connect disabled facilities to supply, movement, production, or
  objective effects without rewriting the immutable geographic source site.

## P2 - Deferred railway infrastructure

- [ ] **Finish representative GermanyCW validation.** Complete and record the
  F10/scenery comparison for a major station, freight terminal or rail yard,
  junction, and the mainland-Rugen railway bridge. Persist the simplified
  representation state, object evidence, and reviewer notes instead of keeping
  test conclusions only in example output.
- [ ] **Calibrate railway classification and importance.** Refine station
  importance with station category, service, passenger or freight role, and
  measured network impact. Review rail-yard and bridge aggregation thresholds,
  unusually long single OSM bridge objects, and the critical/high/medium tier
  boundaries against representative GermanyCW locations.
- [ ] **Validate and extend railway criticality.** Check graph topology and
  portal selection against known corridors, calibrate bridge and junction
  blocking radii, and evaluate whether medium-tier structures also need bounded
  analysis. Retain explicit evidence for no-route, disconnection, and detour
  results, including uncertainty near theater and data-source boundaries.
- [ ] **Expose railway routing as a stable SDK service.** Add bounded route and
  disruption queries with cache identity, provenance, diagnostics, and
  predictable failure results. Keep the expensive theater graph offline or
  cached so map refresh and tactical DCS processing are unaffected.
- [ ] **Model runtime railway disruption and restoration.** Associate selected
  railway locations with scenario-defined DCS scenery, statics, zones, or
  events; track intact, damaged, blocked, destroyed, and repaired state; and
  invalidate affected cached routes only when an explicit association changes.
- [ ] **Use railway effects in strategic reasoning.** Let Python evaluate
  protection, interdiction, repair, rerouting, and supply-corridor consequences.
  Promote only validated or scenario-approved locations to strategic objectives;
  OSM importance or graph criticality alone must never create an attack goal.
- [ ] **Finish railway map ergonomics.** Add independent importance filters and
  optional network-impact filtering while retaining the grouped station,
  terminal, yard, depot, junction, and bridge controls and zoom-dependent
  density.

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
  memory and import time of sources such as Czechia, Turkey, and Ukraine
  without changing the resulting graph. The first coverage-filtered Caucasus
  rebuild still spent about 23 minutes decoding and compiling the twelve road
  sources before writing the bounded graph.
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

- [x] Theater coverage now controls data content rather than only documenting
  intended resolution. Exclusive `All` areas contain connected land/water and
  coastline only; `Low` adds generalized strategic roads, railways, cities,
  and major infrastructure; `High` adds bounded local detail without importing
  residential/service roads, paths, individual buildings, or minor POIs.
  Import geometries are clipped to inherited coverage masks, and road,
  railway, settlement, infrastructure, and maritime derivations observe the
  same policy.
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
- [x] Connected GermanyCW land and water regions use prepared OSMCoastline sea
  polygons with detailed OSM inland water. This removes distant nearest-coast
  artifacts while retaining the 500 m strategic grid.
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
- [x] Strategic mission scope is derived from red, blue, and neutral TERRITORY
  geometry. Red/blue ownership overrides neutral coverage, everything outside
  their union is out of scope, and red/blue overlap is an explicit validation
  error unless the scenario opts into contested areas.
- [x] Automatic strategic-objective generation now applies the TERRITORY scope
  centrally to live Airbases/OPSZONEs and normalized settlement, transport,
  railway, energy, fuel, military, industrial, and maritime candidates.
  Out-of-scope and below-threshold candidates remain visible in bounded
  diagnostics; manual objectives are not replaced unless explicitly requested.
- [x] Automatic strategic-goal derivation applies the strategic mission scope
  and rejects out-of-scope objectives instead of inventing a fallback.
- [ ] Apply the strategic mission scope to frontline calculation bounds and
  diplomatic border classification. Each consumer should reject invalid
  overlap instead of inventing a fallback.
- [ ] Feed verified SCENERY baseline assessments into strategic component
  health before and after STRIKE execution. Exact SCENERY targets can now be
  tasked through their stored coordinates, but weighted DESTROY completion
  still needs automatic post-strike reassessment and evidence persistence.
