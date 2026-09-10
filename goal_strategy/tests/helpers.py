"""Minimal corpus loaders for the test suite.

Stand-ins for the source project's ``io`` modules, which the task spec says to
leave behind. Deliberately quirk-free: ``program_id`` is the plain
``f"{student_study_id}_{derived_session_id}"`` join key into
``data/frozen_paths.parquet`` — if that ever diverges from the original
loader's edge handling, ``test_path_identity``'s program-set assertion fails.

Test-only; not shipped with the package.
"""
import json
from types import SimpleNamespace

import pandas as pd
import yaml


def load_playground_card(path):
    with open(path) as f:
        return yaml.safe_load(f)


def load_final_code_states(path):
    """The testing set: wrong-playground sessions (params lacking the card's
    corpus_filter.required_outcome_field — they were run on a different
    playground) are excluded per the reviewer decision of 2026-08-18."""
    from pathlib import Path
    card = load_playground_card(Path(__file__).resolve().parent.parent
                                / "configs" / "playgrounds" / "castle_crashers.yaml")
    required = (card.get("corpus_filter") or {}).get("required_outcome_field")
    programs = []
    for row in pd.read_parquet(path).to_dict("records"):
        xml = row.get("workspace_xml")
        params = row.get("playground_params")
        params = json.loads(params) if isinstance(params, str) and params else {}
        if required is not None and required not in params:
            continue   # wrong-playground session — not in the testing set
        programs.append(SimpleNamespace(
            program_id=f"{row['student_study_id']}_{row['derived_session_id']}",
            workspace_xml=xml if isinstance(xml, str) and xml.strip() else None,
            playground_params=params,
        ))
    return programs
