# Release Checklist

Use this checklist for named MoosePyBridge releases. A release may proceed only
when every applicable automated check passes and outstanding live-DCS checks are
recorded explicitly.

## Metadata

- [ ] Package version is consistent in `setup.cfg` and the SDK.
- [ ] `RELEASE_NOTES.md` describes the shipped scope and known limitations.
- [ ] The worktree contains only intentional release changes.
- [ ] Generated caches, logs, PBF extracts, and datamine repositories are not
      tracked.

## Automated Validation

- [ ] `python -m pytest -q`
- [ ] `python -m compileall -q python examples tools`
- [ ] A wheel can be built from the repository without network access.
- [ ] The built wheel reports the expected `moosebridge.__version__`.

## Live DCS Smoke Test

- [x] Run `python examples/sdk/release_smoke_test.py` with the bridge daemon,
      map server, and designated release mission active.
- [x] Bridge connects, reconnects, and reports DCS and mission time.
- [x] Global and coalition-specific pictures contain expected objects.
- [x] Mission end is forwarded and clears mission-scoped Python state.
- [x] A representative AUFTRAG reaches its expected lifecycle states.
- [x] INTEL agents and contacts update independently of AUFTRAG lifecycle.
- [x] The browser map loads all configured static and live layers with plausible
      feature counts.
- [x] DCS F10 debug overlays and object markers can be created and removed.
- [x] One verified infrastructure baseline can be assessed after controlled
      damage.

## Publication

- [ ] Commit the validated release state.
- [ ] Create an annotated tag named `v<version>`.
- [ ] Record any skipped live checks in the release description.
