# LogParserDeltaEngine

Rebuild a VEX Blockly **workspace** from a student's activity and render it as compact,
LLM-ready pseudo-code. It's both the log parser (folds log events into state) and the
delta engine (replays the create/move/delete/change deltas).

Stdlib only (`json`, `xml.etree`), nothing to install.

> This is the **compact** renderer, built for LLM prompts. For a human-readable rendering
> with full block names and infix operators, use
> `LearnerModels.generate_readable_text`.

## Quick start

```python
from LogParserDeltaEngine import SmartDeltaEngine, generate_compact_prompt_from_project
```

**1. One shot from a project blob** — the common case: you've got a student's latest
`project` field off a VEX log.

```python
prompt = generate_compact_prompt_from_project(project_json_str)
# "[Active]\n whenStarted\n  drive(DIRECTION=fwd,UNITS=mm)\n[Orphaned]\n turn(...)"
# or None if the project has no blocks
```

**2. Incrementally from an event stream** — replay the deltas as they land.

```python
engine = SmartDeltaEngine()
for log_event in events:              # each: {"content": <json str or dict>, ...}
    engine.process_log(log_event)
engine.get_runnable_block_count()     # int: blocks reachable from a hat block
engine.get_total_blocks()             # int: all blocks tracked
engine.generate_compact_prompt()      # str: same [Active]/[Orphaned] pseudo-code
```

## API reference

| Symbol | Input | Output |
|---|---|---|
| `generate_compact_prompt_from_project(project_json_str)` | `project` field as a JSON string (or `None`) | pseudo-code `str`, or `None` if empty/unparseable |
| `SmartDeltaEngine().process_log(log_event)` | dict with a `content` key (JSON str or dict) | `None` (mutates engine state) |
| `SmartDeltaEngine().get_runnable_block_count()` | — | `int` (blocks reachable from a hat) |
| `SmartDeltaEngine().get_total_blocks()` | — | `int` (all tracked blocks) |
| `SmartDeltaEngine().generate_compact_prompt()` | — | `str` (the pseudo-code listing) |

## Output format

The prompt has two sections:

```
[Active]
 <block_type>(<field>=<val>,...)
  <child_block_type>(...)
[Orphaned]
 <block_type>(...)
```

- **[Active]** — blocks reachable from a "hat" block (`events_*`, `procedures_definition`),
  i.e. code that actually runs. **[Orphaned]** — loose blocks not wired to a hat. Either
  section shows ` (empty)` when it has nothing.
- Each block prints its type (noisy VEX prefixes `pg_`/`aim_`/`mixed_` stripped to save
  tokens) and its `field=value` pairs, indented by nesting depth.

## Events handled

| `eventType` | Effect |
|---|---|
| `loadProject`, `newProject` | Wipe state and rebuild from the project's workspace XML |
| `blockEventData` → `create` | Add a block (shadows skipped) |
| `blockEventData` → `move` | Reparent a block, or set its x/y if it's floating |
| `blockEventData` → `delete` | Remove a block and its descendants |
| `blockEventData` → `change` | Update one field value on a block |

Anything it can't parse is dropped quietly (no exceptions).

## Input shape

`process_log` wants a dict with a `content` key holding the VEX log content (a JSON string
or a dict) that carries `eventType` and either `blockEventData` (for deltas) or `project`
(for load/new). `generate_compact_prompt_from_project` takes the `project` field straight,
as a JSON string.
