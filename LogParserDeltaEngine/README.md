# LogParserDeltaEngine

Rebuild a VEX **workspace** from a student's activity and render it as pseudo-code. It's
both the log parser (folds log events into state) and the delta engine (replays the
create/move/delete/change deltas). Two renderers live here: compact (LLM) and readable
(human).

Stdlib only (`json`, `xml.etree`), nothing to install.

## Quick start

```python
from LogParserDeltaEngine import (
    smart_delta_engine, generate_compact_prompt, generate_compact_prompt_from_content,
    generate_readable_text, generate_readable_lines,
)
```

**1. Compact prompt from workspace XML** (LLM). One-shot: pass the workspace XML
string, get back the prompt.

```python
prompt = generate_compact_prompt(xml_string)
# "[Active]\n whenStarted\n  drive_for(DIRECTION=fwd,UNITS=mm,AMOUNT=200)\n[Orphaned]\n (empty)"
# or None if the workspace has no blocks
```

**2. Compact prompt from a VEX log content dict** (LLM). Skips the manual XML
extraction.

```python
prompt = generate_compact_prompt_from_content(content)
# content is the parsed "content" field of a VEX log event
```

**3. Compact prompt incrementally from an event stream** (LLM). Replay the deltas as
they land.

```python
engine = smart_delta_engine()
for log_event in events:              # each: {"content": <json str or dict>, ...}
    engine.process_log(log_event)
engine.get_runnable_block_count()     # int: blocks reachable from a hat block
engine.get_total_blocks()             # int: all non-shadow blocks tracked
engine.generate_compact_prompt()      # str: same [Active]/[Orphaned] pseudo-code
```

**4. Readable pseudo-code from workspace XML** (human). Full block names, infix
operators, inline values.

```python
generate_readable_text(xml_string)    # str, one line per block
generate_readable_lines(xml_string)   # list[str], same content as a list
```

## API reference

| Symbol | Input | Output |
|---|---|---|
| `generate_compact_prompt(xml_string)` | workspace XML `str` (or `None`) | pseudo-code `str`, or `None` if empty/unparseable |
| `generate_compact_prompt_from_content(content)` | parsed VEX log content dict | pseudo-code `str`, or `None` if no workspace |
| `smart_delta_engine().process_log(log_event)` | dict with a `content` key (JSON str or dict) | `None` (mutates engine state) |
| `smart_delta_engine().get_runnable_block_count()` | none | `int` (non-shadow blocks reachable from a hat) |
| `smart_delta_engine().get_total_blocks()` | none | `int` (all non-shadow blocks tracked) |
| `smart_delta_engine().generate_compact_prompt()` | none | `str` (the compact pseudo-code listing) |
| `generate_readable_text(xml_string)` | workspace XML `str` | readable pseudo-code `str` (empty string if blank/broken) |
| `generate_readable_lines(xml_string)` | workspace XML `str` | `list[str]`, one line per stackable block (empty list if blank/broken) |

## Compact output format

The compact prompt has two sections, `[Active]` and `[Orphaned]`:

```
[Active]
 events_when_started
  drivetrain_drive_for (DIRECTION=fwd,UNITS=mm,AMOUNT=200)
  drivetrain_turn_for (DIRECTION=right,UNITS=deg,AMOUNT=90)
  control_wait (UNITS=seconds,DURATION=1)
  control_repeat (TIMES=3)
   drivetrain_drive_for (DIRECTION=rev,UNITS=mm,AMOUNT=50)
  control_if_then
   operator_comparison (COMPARISON=<,NUM2=100)
    sensing_distance_distance (DISTANCE=frontdistance)
   drivetrain_stop_driving
[Orphaned]
 (empty)
```

- **[Active]** is blocks reachable from a "hat" block (`events_*`,
  `procedures_definition`), i.e. code that actually runs. **[Orphaned]** is loose blocks
  not wired to a hat. Either section shows ` (empty)` when it has nothing.
- Each block prints its type (noisy VEX prefixes `pg_`/`aim_`/`mixed_` stripped to save
  tokens) and its `field=value` pairs, indented by nesting depth.
- Value-slot literals (drive distance, turn degrees, wait duration) fold into the parent
  block's fields, e.g. `AMOUNT=200` on a `drive_for` block.
- Reporter blocks inside value slots (conditions, sensor reads) render as indented
  children, same as loop bodies and next-chain blocks.
- Shadow blocks (inline number pickers) are tracked internally for field propagation but
  excluded from the prompt and from block counts.

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
| `blockEventData` with `create` | Add a block (shadows tracked, initial fields captured) |
| `blockEventData` with `move` | Reparent a block (with edge type + slot), or set its x/y if floating |
| `blockEventData` with `delete` | Remove a block and its descendants |
| `blockEventData` with `change` | Update one field value on a block (propagates to parent if shadow) |

Orphan status is recomputed from scratch after every create/move/delete by walking down
from hat roots, so the active/orphan split stays correct without incremental cascade
logic.

Anything it can't parse is dropped quietly (no exceptions).

## Input shape

`process_log` wants a dict with a `content` key holding the VEX log content (a JSON string
or a dict) that carries `eventType` and either `blockEventData` (for deltas) or `project`
(for load/new). All three standalone renderers (`generate_compact_prompt`,
`generate_readable_text`, `generate_readable_lines`) take a workspace XML string directly.

### What is the workspace XML?

A VEX log event carries a `content.project.workspace` field that holds the student's
block program as an XML string. That XML is what all three renderers accept:

```xml
<xml>
  <block type="pg_events_when_started" id="hat">
    <next>
      <block type="pg_drivetrain_drive_for" id="drive">
        <field name="DIRECTION">fwd</field>
        <field name="UNITS">mm</field>
        <value name="AMOUNT">
          <shadow type="math_number"><field name="NUM">200</field></shadow>
        </value>
      </block>
    </next>
  </block>
</xml>
```

Each `<block>` is a VEX block with a `type`, optional `id`/`x`/`y` attributes, `<field>`
children for parameters (direction, units), `<value>` children for inline inputs (numbers,
sensor reads), and `<statement>`/`<next>` children for nested or chained blocks. Shadow
blocks inside `<value>` slots hold default literals (the `200` in "drive 200mm").

### `create` event payload

The `blockEventData` for a `create` event may carry initial field values:

```python
{"eventType": "create", "blockID": "b1", "blockType": "pg_drivetrain_drive_for",
 "fields": [{"name": "DIRECTION", "value": "fwd"}, {"name": "UNITS", "value": "mm"}]}
```

### `move` event payload

A `move` event reparents a block. The `newInfo` dict carries the parent, edge type, and
slot name:

```python
{"eventType": "move", "blockID": "s1",
 "newInfo": {"parent": "b1", "type": "value", "inputName": "AMOUNT"}}
```

`type` is `next` (sequential chain), `statement` (loop/if body), or `value` (inline
reporter slot). When a shadow block moves into a `value` slot, its field value folds into
the parent's fields under the slot name.
