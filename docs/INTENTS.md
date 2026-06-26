# Intent and Recommendation Model

MoosePyBridge separates tactical intent from executable bridge commands.

This gives operator tools and agents a stable shape for proposals:

1. what should be achieved
2. why it is useful
3. what command would execute it
4. what risks or assumptions apply
5. whether approval is required

The model is deliberately semantic. Agents should continue to command through
MOOSE/OPS surfaces such as AUFTRAG rather than direct low-level DCS scripting.

## Core Types

### `TacticalIntent`

An intent describes the desired battlefield effect.

Current intent types:

- `attack_target`
- `defend_zone`
- `patrol_zone`
- `move_to_zone`
- `observe`

Example:

```python
intent = TacticalIntent.attack_target(
    "GROUP:Enemy Armor",
    coalition="blue",
    priority=80,
)
```

Serialized shape:

```json
{
  "intent_type": "attack_target",
  "objective": "Attack GROUP:Enemy Armor",
  "target_id": "GROUP:Enemy Armor",
  "zone_id": null,
  "coalition": "blue",
  "priority": 80,
  "params": {}
}
```

### `CommandPayload`

A command payload describes the semantic bridge command that can execute the
intent.

```json
{
  "action": "auftrag.create_bai",
  "params": {
    "legion_id": "LEGION:Blue Air Wing",
    "cohort_id": "COHORT:F-18",
    "target": "GROUP:Enemy Armor",
    "altitude_ft": 12000
  },
  "mode": "execute"
}
```

The command is still subject to the normal bridge path, DCS ACK handling, and
future policy checks.

### `TacticalRecommendation`

A recommendation combines intent, command, rationale, risks, confidence, and
approval mode.

```json
{
  "intent": {},
  "command": {},
  "rationale": [
    "Selected cohort COHORT:F-18",
    "Distance to target is 42.0 NM"
  ],
  "risks": [],
  "confidence": 0.75,
  "approval_mode": "approval_required",
  "source": "auftrag_advisory",
  "evidence": {},
  "executable": true
}
```

Approval modes:

- `observe`: not executable
- `recommend`: proposal only
- `approval_required`: executable command exists but needs human approval
- `autonomous`: policy allows execution without a human approval step

## AUFTRAG Adapter

The existing AUFTRAG advisory layer can be converted to a generic tactical
recommendation:

```python
from moosebridge import evaluate_auftrag_request, recommend_auftrag
from moosebridge.intents import tactical_recommendation_from_auftrag

result = evaluate_auftrag_request(state, "BAI", {"target": "GROUP:Enemy"}, coalition="blue")
auftrag_recommendation = recommend_auftrag(result)
tactical_recommendation = tactical_recommendation_from_auftrag(auftrag_recommendation)
```

The adapter maps:

- mission type to broad intent type
- AUFTRAG recommendation fields to `CommandPayload`
- score inputs and original recommendation to `evidence`
- range and selected asset details to `rationale`
- missing payload certainty to `risks`

This is the first bridge between today's AUFTRAG advisory helpers and the future
agent-facing recommendation stream.
