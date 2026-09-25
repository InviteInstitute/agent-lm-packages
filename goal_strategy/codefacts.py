"""Code-channel facts about the authored program, binned by card-declared block families.

No block type, family name, or field name appears here — families come from the
playground card's ``block_families`` map, and field values are read off the
authored blocks themselves.
"""
from __future__ import annotations

from dataclasses import dataclass

from goal_strategy.detector.parsing.block_program import BlockProgram


@dataclass(frozen=True)
class CodeFacts:
    family_counts: dict[str, int]
    family_field_values: dict[str, frozenset[str]]  # lowercased authored field values


def extract_code_facts(program: BlockProgram,
                       block_families: dict[str, frozenset[str]]) -> CodeFacts:
    counts = {fam: 0 for fam in block_families}
    values: dict[str, set[str]] = {fam: set() for fam in block_families}
    families_by_type: dict[str, list[str]] = {}
    for fam, types in block_families.items():
        for block_type in types:
            families_by_type.setdefault(block_type, []).append(fam)

    # Active (attached) blocks only: a detached block never executes, and the
    # corpus regression pins confirm the design analysis scoped it this way.
    # All field values on a block are collected (the registry's xml_fields
    # list is stale for some blocks — the corpus XML carries ACTION where the CSV
    # says STATE, and the simulator likewise reads both); the categorical rung
    # matcher picks out card-declared labels, so extra values are inert.
    for node in program.iter_all_blocks():
        for fam in families_by_type.get(node.block_type, ()):
            counts[fam] += 1
            for block_field in node.fields:
                if block_field.value:
                    values[fam].add(str(block_field.value).strip().lower())

    return CodeFacts(counts, {fam: frozenset(v) for fam, v in values.items()})
