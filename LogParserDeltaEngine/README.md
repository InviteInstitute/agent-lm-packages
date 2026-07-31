# LogParserDeltaEngine

Rebuild a VEX Blockly **workspace** from a student's activity and render it as compact,
LLM-ready pseudo-code. It's both the log parser (it folds log events into state) and the
delta engine (it replays the create/move/delete/change deltas).

Stdlib only (`json`, `xml.etree`), nothing to install.

## Two ways to build state

```python
from LogParserDeltaEngine import SmartDeltaEngine, generate_llm_prompt_from_project
```

**1. One shot from a project blob.** The common case: you've got a student's latest
`project` field off a VEX log.

```python
prompt = generate_llm_prompt_from_project(project_json_str)
# "[Active]\n whenStarted\n  drive(...)\n[Orphaned]\n turn(...)"  (or None if empty)
```

**2. Incrementally from an event stream.** Replay the deltas as they land.

```python
engine = SmartDeltaEngine()
for log_event in events:              # each: {"content": <json str or dict>, ...}
    engine.process_log(log_event)
engine.get_runnable_block_count()     # blocks reachable from a hat block
engine.get_total_blocks()
engine.generate_llm_prompt()          # same [Active]/[Orphaned] pseudo-code
```

## What the output means

- **[Active]** is the blocks reachable from a "hat" block (`events_*`,
  `procedures_definition`), i.e. code that actually runs. **[Orphaned]** is the loose
  blocks that aren't wired to a hat.
- Each block prints its type (the noisy VEX prefixes like `pg_`/`aim_` get stripped to
  save tokens) and its fields, indented by how deep it nests.
- A `loadProject`/`newProject` event rebuilds state from the project XML; block-level
  events just mutate it. Anything it can't parse is dropped quietly.

## Input shape

`process_log` wants a dict with a `content` key holding the VEX log content (a JSON
string or a dict) that carries `eventType` and either `blockEventData` (for deltas) or
`project` (for load/new). `generate_llm_prompt_from_project` takes the `project` field
straight, as a JSON string.
