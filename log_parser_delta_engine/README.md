# log_parser_delta_engine

This package rebuilds a VEX **workspace** from the activity of a student and renders it as
pseudo-code. Every VEX log event has the whole project, so the log parser rebuilds the workspace
from that snapshot on each event. The package has two renderers: compact (LLM) and readable
(human). Both renderers separate the code that can run from the code that cannot run. See
[What counts as live code](#what-counts-as-live-code).

The package uses only the stdlib (`json`, `xml.etree`). You do not need to install anything.

## Quick start

```python
from log_parser_delta_engine import (
    smart_delta_engine, generate_compact_prompt, generate_compact_prompt_from_content,
    generate_readable_text, generate_readable_lines,
)
```

**1. Compact prompt from workspace XML** (LLM). This is a one-shot call. Pass the workspace XML
string and get the prompt.

```python
prompt = generate_compact_prompt(xml_string)
# "[Active]\n events_when_started\n  drivetrain_drive_for (DIRECTION=fwd,UNITS=mm,AMOUNT=200)\n[Orphaned]\n (empty)"
# or None if the workspace has no blocks
```

**2. Compact prompt from a VEX log content dict** (LLM). This call skips the manual XML extraction.

```python
prompt = generate_compact_prompt_from_content(content)
# content is the parsed "content" field of a VEX log event
```

**3. Compact prompt from an event stream** (LLM). Feed events as they arrive. The engine always
shows the project snapshot of the latest event.

```python
engine = smart_delta_engine()
for log_event in events:              # each: {"content": <json str or dict>, ...}
    engine.process_log(log_event)
engine.get_runnable_block_count()     # int: blocks that can run (live, not disabled)
engine.get_total_blocks()             # int: all blocks on the canvas (shadows excluded)
engine.generate_compact_prompt()      # str: same [Active]/[Orphaned] pseudo-code
```

**4. Readable pseudo-code from workspace XML** (human). This output has full block names, infix
operators and inline values, with live code first and orphans after it.

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

Both renderers use [`liveness.py`](liveness.py). The goal_strategy parser applies the same rules to
its own IR, and a test keeps the two in agreement.

- A top-level stack is **live** when its first block is an enabled hat: `when started`,
  `when I receive`, `when bumper`, `when timer`, or `when eye`. The list is explicit. `broadcast`
  and `broadcast and wait` are also in the events category, but they are ordinary stack blocks. A
  stack that starts with one of them thus never runs.
- A **My Block** definition is live when live code calls it, directly or through other called My
  Blocks. An uncalled definition is an orphan. A second definition of the same name is also an
  orphan.
- Everything else at the top level is an **orphan**. It is on the canvas but can never run.
- A **disabled** block never runs, and nothing inside it runs. The block after it still runs.
  Disabled blocks stay where they are and have a mark, so a reader sees them and does not mistake
  them for live code. A disabled hat makes its whole stack an orphan.

We checked these rules against the `hasOrphans` flag that VEX puts on every log event. On 9,744
distinct classroom workspaces, both renderers and goal_strategy agree with VEX on every one.

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

- **[Active]** has the live stacks, and **[Orphaned]** has the rest, each in document order. A
  section with nothing in it shows ` (empty)`.
- Every stack starts at depth 1, and the rest of its sequence is at depth 2. Each depth-1 line thus
  starts a new stack. The next block in a sequence stays at the same depth. Loop bodies, if bodies
  and value-slot reporters indent one level under their block. The second branch of an if/else has
  the label `else:`.
- Each block prints its type and its `field=value` pairs. The output removes the noisy VEX prefixes
  `pg_`/`aim_`/`mixed_` to save tokens. My Blocks show their name as `PROC=`.
- Value-slot literals (drive distance, turn degrees, wait duration) fold into the fields of the
  parent block, for example `AMOUNT=200` on a `drive_for` block. When a reporter is plugged in over
  a literal, the reporter is the input and the output drops the covered default.
- Disabled blocks end with `[disabled]`.

## Readable output format

This is the same workspace, for a person:

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

- The output has one line for each stackable block, indented to show loop and if nesting. Live
  stacks come first, with a blank line between them. (Separate stacks run side by side, not one
  after the other.) Orphan stacks come next under `not connected (won't run):`, indented.
- Block names come from `vex_blocks.json`. If the mapping does not have a block type, the renderer
  derives a name from the type (`pg_drivetrain_go_to_object` reads `drivetrain go to object`). A
  stale mapping thus never breaks the listing.
- Operators render infix (`A < B`, `A and B`), and the renderer tidies enums (`fwd` to `forward`). Value
  slots show their literal or the reporter plugged into them.
- My Blocks read `define <name>` and `call <name>`, with arguments filled into the name.
- Disabled blocks end with `(disabled)`.

## Events handled

Every VEX log event (`blockCreated`, `blockMoved`, `blockChanged`, `blockDeleted`, `runProject`,
`menuSelect`, ...) has the whole project, workspace XML included, in `content.project`.
`process_log` rebuilds the workspace from that snapshot on every event that has one, whatever its
`eventType`. An empty workspace clears the state. The engine ignores events without a `project`,
and anything that it cannot parse, with no exceptions. An event whose workspace string is the same
as the last one (most `menuSelect`, `runProject` and UI events) skips the rebuild.

The engine does not replay the `blockEventData` delta of the event. In real logs, this delta has
too little data for a rebuild:

- A move names the new parent but not the slot that the block went into.
- Shadow blocks (the inline number pickers) never get a create event.
- A session starts from a workspace that nobody saw being built.

## Input shape

`process_log` needs a dict with a `content` key. This key holds the VEX log content (a JSON string
or a dict) with a `project` (a JSON string or a dict with a `workspace` XML string). All three
standalone renderers (`generate_compact_prompt`, `generate_readable_text`,
`generate_readable_lines`) take a workspace XML string directly.

### What is the workspace XML?

A VEX log event has a `content.project.workspace` field. This field holds the block program of the
student as an XML string. All three renderers accept that XML:

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

Each `<block>` is a VEX block with a `type`. It has these optional parts:

- `id`, `x`, `y` and `disabled` attributes
- `<field>` children for parameters (direction, units)
- `<value>` children for inline inputs (numbers, sensor reads)
- `<statement>` and `<next>` children for nested or chained blocks

Shadow blocks inside `<value>` slots hold default literals (the `200` in "drive 200mm"). When a
reporter is plugged into the slot, Blockly still writes the shadow first and the reporter after it.
Real VEX XML has the namespace shown above. XML with no namespace also works.
