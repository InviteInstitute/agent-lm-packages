"""Minimal corpus loaders for the test suite.

``program_id`` is the plain ``f"{student_study_id}_{derived_session_id}"`` join
key into ``data/frozen_paths.parquet``. If that ever diverges from the original
loader's edge handling, ``test_path_identity``'s program-set assertion fails.

Test-only; not shipped with the package.
"""
from types import SimpleNamespace

import yaml


def load_playground_card(path):
    with open(path) as f:
        return yaml.safe_load(f)


def load_final_code_states(path):
    """The testing set, loaded the way the CLI loads it (wrong-playground
    sessions excluded by the card's corpus_filter)."""
    from goal_strategy.cli import _load_programs
    return [SimpleNamespace(program_id=pid, workspace_xml=xml if xml.strip() else None,
                            playground_params=params)
            for pid, xml, params in _load_programs(path)]
