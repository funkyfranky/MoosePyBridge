# Theater Data Workflow

Theater datasets are configured through one JSON profile. The profile is the
single source for the DCS theater identity, historical reference years,
external sources, policy exclusions, storage root, and generated artifact
names. Runtime code consumes generated artifacts and does not need to know how
they were built.

The released Germany Cold War profile is:

```text
python/moosebridge/data/GermanyCW_topography.json
```

Every theater uses an isolated `tmp/theaters/{theater_id}` root. Generated data
is separated by lifecycle:

```text
tmp/theaters/<theater-id>/
  sources/       downloaded external inputs
  cache/         reproducible build intermediates
  runtime/       products consumed by planning and the map server
  verification/  DCS coverage and manually reviewed evidence
```

The browser consumes only the indexed topography below `cache/viewport`; a
multi-gigabyte merged topography GeoJSON is neither generated nor loaded.

Artifacts used by the map server must cover the complete theater. Regional
pilot or validation artifacts may be retained for diagnostics, but must not be
configured as the runtime transport, settlement, or infrastructure dataset.

## Inspect a Theater

```powershell
python tools/theater_workflow.py --profile python/moosebridge/data/GermanyCW_topography.json status
python tools/theater_workflow.py --profile python/moosebridge/data/GermanyCW_topography.json plan
```

`status` validates the profile, reports all map artifacts, and verifies the
theater ID in the viewport manifest. `plan` prints the complete reproducible
build order with resolved paths.

## Build Stages

The stages are ordered as follows:

1. `coverage`: capture mission-editor `Topography All`, `Topography Low ...`,
   and `Topography High ...` zones from DCS.
2. `import`: download and normalize configured Geofabrik PBF extracts into
   reusable per-source shards.
3. `viewport`: build the browser-map spatial index.
4. `surfaces`: build connected land and water regions.
5. `road-routing`: build the unrestricted military road graph.
6. `ground-mobility`: build the coarse strategic mobility graph.
7. `transport`: aggregate bridges and strategic road junctions.
8. `settlements`: normalize cities and towns.
9. `railway`: aggregate railway facilities and routing data.
10. `infrastructure`: normalize energy, fuel, military, industrial, and
    maritime candidates according to the profile's historical policy.
11. `maritime`: refresh maritime logistics candidates.

Run a single stage or inspect its exact command first:

```powershell
python tools/theater_workflow.py --profile <profile.json> build --stage coverage
python tools/theater_workflow.py --profile <profile.json> build --stage import --dry-run
python tools/theater_workflow.py --profile <profile.json> build --stage viewport
```

Running `build` without `--stage` executes the complete workflow. This is
expensive and intentionally never happens implicitly.

## Start the Map

```powershell
.\run_map.ps1 --theater-profile python/moosebridge/data/GermanyCW_topography.json
```

Individual artifact switches remain available as explicit overrides. The map
server rejects loaded artifacts whose embedded theater ID differs from the
profile, preventing accidental mixtures of data from different DCS maps.

## Adding Another DCS Map

1. Copy the GermanyCW profile and assign the exact DCS theater ID.
2. Use a separate `data_root`, normally `tmp/theaters/{theater_id}`.
3. Set the mission and infrastructure reference years.
4. Configure only Geofabrik extracts intersecting the DCS map.
5. Configure historical exclusions such as modern wind or solar generation.
6. Create broad coverage zones in a small DCS verification mission.
7. Run `coverage`, then `status` and `plan`, before downloading data.
8. Build one representative high-detail area first and compare roads, surfaces,
   settlements, and infrastructure against the DCS F10 map.
9. Expand to complete-theater coverage only after that pilot validation.

OSM data is an external baseline. Coastlines, passability, roads, scenery, and
strategic target components still require representative DCS validation because
DCS maps model different eras and simplify real-world geography.
