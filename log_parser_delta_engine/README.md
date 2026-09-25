# log_parser_delta_engine

Rebuild a VEX **workspace** from a student's activity and render it as pseudo-code. Every
VEX log event carries the whole project, so the log parser rebuilds the workspace from
that snapshot on each event. Two renderers live here: compact (LLM) and readable (human).
Both split the code that can run from the code that can't (see
[What counts as live code](#what-counts-as-live-code)).

Stdlib only (`json`, `xml.etree`), nothing to install.

## Quick start

```python
from log_parser_delta_engine import (
    smart_delta_engine, generate_compact_prompt, generate_compact_prompt_from_content,
    generate_readable_text, generate_readable_lines,
)
```

**1. Compact prompt from workspace XML** (LLM). One-shot: pass the workspace XML
string, get back the prompt.

```python
prompt = generate_compact_prompt(xml_string)
# "[Active]\n events_when_started\n  drivetrain_drive_for (DIRECTION=fwd,UNITS=mm,AMOUNT=200)\n[Orphaned]\n (empty)"
# or None if the workspace has no blocks
```

**2. Compact prompt from a VEX log content dict** (LLM). Skips the manual XML
extraction.

```python
prompt = generate_compact_prompt_from_content(content)
# content is the parsed "content" field of a VEX log event
```

**3. Compact prompt from an event stream** (LLM). Feed events as they land; the engine
always reflects the latest event's project snapshot.

```python
engine = smart_delta_engine()
for log_event in events:              # each: {"content": <json str or dict>, ...}
    engine.process_log(log_event)
engine.get_runnable_block_count()     # int: blocks that can run (live, not disabled)
engine.get_total_blocks()             # int: all blocks on the canvas (shadows excluded)
engine.generate_compact_prompt()      # str: same [Active]/[Orphaned] pseudo-code
```

**4. Readable pseudo-code from workspace XML** (human). Full block names, infix
operators, inline values, live code first and orphans after.

```python
generate_readable_text(xml_string)    # str, one line per block
generate_readable_lines(xml_string)   # list[str], same content as a list
```

## API reference

| Symbol | Input | Output |
|---|---|---|
| `generate_compact_prompt(xml_string)` | workspace XML `str` (or `None`) | pseudo-code `str`, or `None` if empty/unparseable |
| `generate_compact_prompt_from_content(content)` | parsed VEX log content dict | pseudo-code `str`, or `None` if no workspace |
| `generate_compact_prompt_from_project(project)` | raw `content.project` value (dict or JSON `str`) | pseudo-code `str`, or `None` if empty/no blocks |
| `smart_delta_engine().process_log(log_event)` | dict with a `content` key (JSON str or dict) | `None` (rebuilds engine state from `content.project`) |
| `smart_delta_engine().get_runnable_block_count()` | none | `int` (blocks that can run: in a live stack and not disabled) |
| `smart_delta_engine().get_total_blocks()` | none | `int` (all blocks on the canvas, shadows excluded) |
| `smart_delta_engine().generate_compact_prompt()` | none | `str` (the compact pseudo-code listing) |
| `generate_readable_text(xml_string)` | workspace XML `str` | readable pseudo-code `str` (empty string if blank/broken) |
| `generate_readable_lines(xml_string)` | workspace XML `str` | `list[str]`, one line per stackable block, `""` between stacks (empty list if blank/broken) |
| `liveness.split_stacks(root)` | namespace-stripped workspace `Element` | `(active, orphaned)` lists of top-level `<block>` elements |

## What counts as live code

Both renderers use [`liveness.py`](liveness.py), and goal_strategy's parser applies the
same rules to its own IR (a test keeps the two in agreement):

- A top-level stack is **live** when its first block is an enabled hat: `when started`,
  `when I receive`, `when bumper`, `when timer`, or `when eye`. The list is explicit.
  `broadcast` and `broadcast and wait` sit in the events category too, but they are
  ordinary stack blocks, so a stack that starts with one never runs.
- A **My Block** definition is live when live code calls it, directly or through other
  called My Blocks. An uncalled definition is an orphan, and so is a second definition
  of the same name.
- Everything else at the top level is an **orphan**: it is on the canvas but can never
  run.
- A **disabled** block never runs, and neither does anything inside it, but the block
  after it still does. Disabled blocks stay where they are and are marked, so a reader
  sees them without mistaking them for live code. A disabled hat makes its whole stack
  an orphan.

Checked against the `hasOrphans` flag VEX puts on every log event: on 9,744 distinct
classroom workspaces, both renderers and goal_strategy agree with VEX on every one.

## Compact output format

The compact prompt has two sections, `[Active]` and `[Orphaned]`:

```
[Active]
 events_when_started
  drivetrain_drive_for (DIRECTION=fwd,UNITS=mm,AMOUNT=200)
  control_repeat (TIMES=3)
   control_if_then_else
    operator_comparison (COMPARISON=<,NUM2=100)
     sensing_distance_distance (DISTANCE=frontdistance)
    procedures_call (PROC=back off)
   else:
    drivetrain_drive_for (DIRECTION=fwd,UNITS=mm,AMOUNT=50)
  drivetrain_stop_driving [disabled]
 procedures_definition (PROC=back off)
  drivetrain_turn_for (TURNDIRECTION=right,ANGLE=90)
[Orphaned]
 events_broadcast (BROADCAST_OPTION=message1)
```

- **[Active]** is the live stacks, **[Orphaned]** the rest, each in document order.
  Either section shows ` (empty)` when it has nothing.
- Every stack opens at depth 1 and the rest of its sequence sits at depth 2, so each
  depth-1 line starts a new stack. The next block in a sequence stays at the same depth;
  loop and if bodies and value-slot reporters indent one level under their block. The
  second branch of an if/else is labeled `else:`.
- Each block prints its type (noisy VEX prefixes `pg_`/`aim_`/`mixed_` stripped to save
  tokens) and its `field=value` pairs. My Blocks carry their name as `PROC=`.
- Value-slot literals (drive distance, turn degrees, wait duration) fold into the parent
  block's fields, e.g. `AMOUNT=200` on a `drive_for` block. When a reporter is plugged
  in over a literal, the reporter is the input and the covered default is dropped.
- Disabled blocks end with `[disabled]`.

## Readable output format

The same workspace, for a person:

```
when started
drive for forward, mm, amount 200
repeat times 3
  if / else (object distance frontdistance < 100)
    call back off
  else:
    drive for forward, mm, amount 50
stop driving (disabled)

define back off
turn for right, angle 90

not connected (won't run):
  broadcast event message1
```

- One line per stackable block, indented to show loop and if nesting. Live stacks come
  first with a blank line between them (separate stacks run side by side, not one after
  the other). Orphan stacks follow under `not connected (won't run):`, indented.
- Block names come from `vex_blocks.json`. If a block type is not in the mapping, a name
  is derived from the type (`pg_drivetrain_go_to_object` reads `drivetrain go to
  object`), so a stale mapping never breaks the listing.
- Operators render infix (`A < B`, `A and B`), enums get tidied (`fwd` to `forward`), and
  value slots inline their literal or the reporter plugged into them.
- My Blocks read `define <name>` and `call <name>`, with arguments filled into the name.
- Disabled blocks end with `(disabled)`.

## Events handled

Every VEX log event (`blockCreated`, `blockMoved`, `blockChanged`, `blockDeleted`,
`runProject`, `menuSelect`, ...) carries the whole project, workspace XML included, in
`content.project`. `process_log` rebuilds the workspace from that snapshot on every event
that has one, whatever its `eventType`. An empty workspace clears the state. Events
without a `project`, and anything it can't parse, are ignored (no exceptions).

The event's `blockEventData` delta is not replayed. In real logs it is too thin to
rebuild from: a move names the new parent but not which slot the block went into,
shadow blocks (the inline number pickers) never get a create event, and a session
starts from a workspace nobody saw being built.

## Input shape

`process_log` wants a dict with a `content` key holding the VEX log content (a JSON string
or a dict) that carries a `project` (a JSON string or a dict with a `workspace` XML
string). All three standalone renderers (`generate_compact_prompt`,
`generate_readable_text`, `generate_readable_lines`) take a workspace XML string directly.

### What is the workspace XML?

A VEX log event carries a `content.project.workspace` field that holds the student's
block program as an XML string. That XML is what all three renderers accept:

```xml
<xml xmlns="https://developers.google.com/blockly/xml">
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

Each `<block>` is a VEX block with a `type`, optional `id`/`x`/`y`/`disabled` attributes,
`<field>` children for parameters (direction, units), `<value>` children for inline inputs
(numbers, sensor reads), and `<statement>`/`<next>` children for nested or chained blocks.
Shadow blocks inside `<value>` slots hold default literals (the `200` in "drive 200mm");
when a reporter is plugged into the slot, Blockly still writes the shadow first and the
reporter after it. Real VEX XML is namespaced as above; un-namespaced XML works too.
