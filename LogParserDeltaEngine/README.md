# LogParserDeltaEngine

Rebuild a VEX **workspace** from a student's activity and render it as
pseudo-code. It's both the log parser (folds log events into state) and the delta engine
(replays the create/move/delete/change deltas). Two renderers live here, compact (LLM)
and readable (human).

Stdlib only (`json`, `xml.etree`), nothing to install.

## Quick start

```python
from LogParserDeltaEngine import (
    SmartDeltaEngine, generate_compact_prompt_from_project,
    generate_readable_text, generate_readable_lines,
)
```

**1. Compact prompt from a project blob** (LLM). The common case: you've got a student's
latest `project` field off a VEX log.

```python
prompt = generate_compact_prompt_from_project(project_json_str)
# "[Active]\n whenStarted\n  drive(DIRECTION=fwd,UNITS=mm)\n[Orphaned]\n turn(...)"
# or None if the project has no blocks
```

**2. Compact prompt incrementally from an event stream** (LLM). Replay the deltas as they
land.

```python
engine = SmartDeltaEngine()
for log_event in events:              # each: {"content": <json str or dict>, ...}
    engine.process_log(log_event)
engine.get_runnable_block_count()     # int: blocks reachable from a hat block
engine.get_total_blocks()             # int: all blocks tracked
engine.generate_compact_prompt()      # str: same [Active]/[Orphaned] pseudo-code
```

**3. Readable pseudo-code from workspace XML** (human). Full block names, infix
operators, inline values.

```python
generate_readable_text(xml_string)    # str, one line per block
generate_readable_lines(xml_string)   # list[str], same content as a list
```

## API reference

| Symbol | Input | Output |
|---|---|---|
| `generate_compact_prompt_from_project(project_json_str)` | `project` field as a JSON string (or `None`) | pseudo-code `str`, or `None` if empty/unparseable |
| `SmartDeltaEngine().process_log(log_event)` | dict with a `content` key (JSON str or dict) | `None` (mutates engine state) |
| `SmartDeltaEngine().get_runnable_block_count()` | none | `int` (blocks reachable from a hat) |
| `SmartDeltaEngine().get_total_blocks()` | none | `int` (all tracked blocks) |
| `SmartDeltaEngine().generate_compact_prompt()` | none | `str` (the compact pseudo-code listing) |
| `generate_readable_text(xml_string)` | workspace XML `str` | readable pseudo-code `str` (empty string if blank/broken) |
| `generate_readable_lines(xml_string)` | workspace XML `str` | `list[str]`, one line per stackable block (empty list if blank/broken) |

## Compact output format

The compact prompt has two sections:

```
[Active]
 <block_type>(<field>=<val>,...)
  <child_block_type>(...)
[Orphaned]
 <block_type>(...)
```

- **[Active]** is blocks reachable from a "hat" block (`events_*`,
  `procedures_definition`), i.e. code that actually runs. **[Orphaned]** is loose blocks
  not wired to a hat. Either section shows ` (empty)` when it has nothing.
- Each block prints its type (noisy VEX prefixes `pg_`/`aim_`/`mixed_` stripped to save
  tokens) and its `field=value` pairs, indented by nesting depth.

## Readable output format

The readable renderer prints one line per stackable block, indented to show loop and if
nesting. Block names come from `vex_blocks.json`. Operators render infix (`A < B`, `A and
B`), enums get tidied (`fwd` to `forward`), and reporter value slots inline their
literals. If a block type is not in the mapping, its raw type prints, so a stale mapping
never breaks the listing.

## Events handled

| `eventType` | Effect |
|---|---|
| `loadProject`, `newProject` | Wipe state and rebuild from the project's workspace XML |
| `blockEventData` with `create` | Add a block (shadows skipped) |
| `blockEventData` with `move` | Reparent a block, or set its x/y if it's floating |
| `blockEventData` with `delete` | Remove a block and its descendants |
| `blockEventData` with `change` | Update one field value on a block |

Anything it can't parse is dropped quietly (no exceptions).

## Input shape

`process_log` wants a dict with a `content` key holding the VEX log content (a JSON string
or a dict) that carries `eventType` and either `blockEventData` (for deltas) or `project`
(for load/new). `generate_compact_prompt_from_project` takes the `project` field straight,
as a JSON string. The readable renderers take a workspace XML string directly.
