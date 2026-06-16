# AUFTRAG Target Semantics

This document defines how MoosePyBridge represents AUFTRAG targets in Python.

## Source of truth

The source of truth for an AUFTRAG target is:

```lua
AUFTRAG.engageTarget
```

`engageTarget` is expected to be either `nil` or a MOOSE `TARGET` object.

MoosePyBridge must not infer, reinterpret, or remap the target to a different semantic object type unless MOOSE explicitly exposes that object type in the TARGET data.

For example, if a patrol assignment was created from an OPSZONE but the resulting TARGET object contains a target object of type `Zone`, Python must represent it as:

```text
ZONE:<name>
```

not as:

```text
OPSZONE:<name>
```

## Snapshot shape

An AUFTRAG snapshot may contain a `target` section:

```json
{
  "object_id": "AUFTRAG:1",
  "target": {
    "object_id": "TARGET:1",
    "name": "Town Fight",
    "state": "Alive",
    "category": "Zone",
    "x": -33711.171875,
    "y": 0,
    "z": -510211.0,
    "life": 1,
    "life0": 1,
    "damage": 0,
    "threat_level_max": 0,
    "objects": [
      {
        "id": 1,
        "type": "Zone",
        "name": "Town Fight",
        "object_id": "ZONE:Town Fight",
        "status": "Alive",
        "x": -33711.171875,
        "y": 0,
        "z": -510211.0,
        "life": 1,
        "life0": 1
      }
    ]
  }
}
```

## Target object ID mapping

Target object IDs are derived directly from `TARGET.Object.Type` and `TARGET.Object.Name`.

| TARGET object type | MoosePyBridge object id |
| --- | --- |
| `Group` | `GROUP:<Name>` |
| `Unit` | `UNIT:<Name>` |
| `Static` | `STATIC:<Name>` |
| `Scenery` | `SCENERY:<Name>` |
| `Airbase` | `AIRBASE:<Name>` |
| `Zone` | `ZONE:<Name>` |
| `OpsZone` | `OPSZONE:<Name>` |
| `Coordinate` | no object id, use coordinates |

No cross-type name matching is performed.

## Aggregate target versus target objects

`target` describes the aggregate MOOSE TARGET object.

`target.objects` describes the concrete target objects contained in the TARGET.

The aggregate `target.x`, `target.y`, and `target.z` are the primary coordinate returned by the TARGET object. For set targets or multi-object targets, consumers should inspect `target.objects`.

## Python model

Python represents this as:

```python
auftrag.target                       # TargetSnapshot | None
auftrag.target.objects               # list[TargetObjectSnapshot]
auftrag.target.objects[0].object_id  # e.g. "ZONE:Town Fight"
```

The Python model should stay a mirror of the MOOSE TARGET structure. Tactical reasoning layers may interpret this data, but the state mirror should not rewrite target identity.

## Current policy

- Do not resolve `ZONE:<name>` to `OPSZONE:<name>` automatically.
- Do not collapse multi-object targets to a single inferred object.
- Do not infer a target type from AUFTRAG type.
- Prefer `AUFTRAG.engageTarget` over AUFTRAG-type-specific fields.
- Preserve raw target payloads for debugging and future migration.
