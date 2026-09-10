"""D2 layer-1 registry: resolution semantics + the graceful-failure wiring
(Stage 1 of VALIDATION_PLAN.md, 2026-08-21)."""
from __future__ import annotations
from goal_strategy.paths import data_path

from goal_strategy.config import load_configs, resolve_capability


def test_resolution_precedence():
    caps = {
        "unknown_default": {"class": "unsimulable", "flag": "unmodeled_blocks"},
        "families": {"pg_control_": {"class": "simulates"},
                     "pg_": {"class": "testable"}},
        "blocks": {"pg_control_forever": {"class": "simulates_capped"}},
    }
    # explicit beats family
    assert resolve_capability("pg_control_forever", caps)["class"] == "simulates_capped"
    # longest family prefix wins
    assert resolve_capability("pg_control_wait", caps)["class"] == "simulates"
    assert resolve_capability("pg_sensing_new", caps)["class"] == "testable"
    # unknown default guarantees a named flag
    e = resolve_capability("totally_new_block", caps)
    assert e["class"] == "unsimulable" and e["flag"] == "unmodeled_blocks"


def test_real_registry_covers_every_observed_type():
    """Every block type observed in EITHER corpus resolves to a class other
    than the unknown default — the registry is complete for known data. A
    failure here means a new type arrived: classify it in
    configs/capabilities.yaml, don't widen a family blindly."""
    import re
    import pandas as pd
    from pathlib import Path
    caps = load_configs("castle_crashers").capabilities
    root = Path(__file__).resolve().parent.parent
    observed = set()
    for path in (data_path() / "final_code_states.parquet",
                 data_path() / "ccp_run_dataset" / "ccp_runs.parquet"):
        for xml in pd.read_parquet(path)["workspace_xml"]:
            observed |= set(re.findall(r'type="([^"]+)"', xml or ""))
    unknown = {t for t in observed
               if resolve_capability(t, caps) == resolve_capability("__nope__", caps)
               and t not in (caps.get("blocks") or {})}
    # resolve equality check is structural; be precise: a type is COVERED if
    # it has an explicit entry or matches a family prefix
    fams = tuple((caps.get("families") or {}).keys())
    uncovered = {t for t in observed
                 if t not in (caps.get("blocks") or {})
                 and not t.startswith(fams)}
    assert not uncovered, f"unclassified observed types: {sorted(uncovered)}"


def test_dev_corpus_carries_no_unmodeled_flag():
    """All dev-corpus block types are modeled — the registry wiring must not
    change dev profiles (the §6 regression base)."""
    from goal_strategy.profile import _profile
    from goal_strategy.tests.helpers import load_final_code_states
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    for p in load_final_code_states(str(data_path() / "final_code_states.parquet"))[:8]:
        prof = _profile(p.workspace_xml or "", p.program_id, p.playground_params)
        flags = {f for g in prof.goals for i in g.intent + g.attainment
                 for f in (i.flags or [])}
        assert "unmodeled_blocks" not in flags, p.program_id


def test_procedures_call_run_is_no_longer_flagged():
    """OI-23 build (2026-08-24): procedure calls are inline-expanded — the
    Stage-1 unmodeled flag is retired for them; the profile carries no
    unmodeled_blocks for a procedures-only exotic program."""
    from goal_strategy.ccp_runs import load_ccp_runs
    from goal_strategy.profile import _profile
    r = next(x for x in load_ccp_runs(tag_dev_overlap=False)
             if "procedures_call" in (x.workspace_xml or "")
             and "when_timer" not in (x.workspace_xml or ""))
    prof = _profile(r.workspace_xml, r.run_id, r.playground_params)
    flags = {f for g in prof.goals for i in g.intent + g.attainment
             for f in (i.flags or [])}
    assert "unmodeled_blocks" not in flags
