"""Load and validate the playground and goal cards into runtime objects.

All validation happens at load time; profile() never sees a malformed card.
Adding a playground or goals must require YAML only (spec §5) — the configs
directory is parameterisable precisely so that holds in tests.
"""
from __future__ import annotations

import functools
import copy
import math
from importlib.resources import files
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

from goal_strategy.detector.simulation.simulate_path import PlaygroundContext

from .indicators import REGISTRY, resolve_reference

_DEFAULT_CONFIGS_DIR = files("goal_strategy").joinpath("configs")

_BINDING_ENTITY_KEYS = ("object", "region", "block_family")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class RungSpec:
    kind: str                       # "numeric" | "categorical"
    labels: tuple[str, ...]         # positional over ascending-value bins (numeric)
    direction: Optional[str] = None  # numeric only: lower_is_better | higher_is_better
    edges: tuple[float, ...] = ()   # resolved, ascending; () for categorical
    reference: Optional[str] = None  # echoed for auditability when edges came from one
    absent_label: Optional[str] = None
    provenance: Optional[str] = None  # card-authored edge-provenance note (inert; OI-9 review)

    def evaluate(self, raw: Any) -> Optional[str]:
        if self.kind == "categorical":
            if raw is None:
                return self.labels[0]
            values = {raw} if isinstance(raw, str) else set(raw)
            matched = None
            for label in self.labels[2:]:
                if label in values:
                    matched = label  # last-listed match wins
            return matched if matched is not None else self.labels[1]
        if raw is None:
            return self.absent_label
        value = float(raw)
        if not math.isfinite(value):
            return self.absent_label
        # The shared edge goes to the better bin: <= for lower_is_better, < for higher.
        for i, edge in enumerate(self.edges):
            if (value <= edge) if self.direction == "lower_is_better" else (value < edge):
                return self.labels[i]
        return self.labels[-1]


@dataclass(frozen=True)
class IndicatorSpec:
    name: str
    indicator: str
    binding: dict
    rungs: Optional[RungSpec]
    flag_rules: tuple[dict, ...] = ()


@dataclass(frozen=True)
class GoalSpec:
    id: str
    label: str
    intent: tuple[IndicatorSpec, ...]
    attainment: tuple[IndicatorSpec, ...]  # may be empty — a modelling statement, not a gap


@dataclass(frozen=True)
class LoadedConfig:
    playground: str
    card: dict
    context: PlaygroundContext
    block_families: dict[str, frozenset[str]]
    goals: tuple[GoalSpec, ...]
    config_version: str
    robot: dict = None  # shared robot hardware card (configs/robot/); {} if absent
    capabilities: dict = None  # simulation-capability registry (D2 layer 1); {} if absent


def _parse_rungs(node: dict, binding: dict, card: dict, where: str) -> RungSpec:
    labels = node.get("labels")
    if not labels or not isinstance(labels, list):
        raise ConfigError(f"{where}: rungs must declare a labels list")
    labels = tuple(str(l) for l in labels)
    has_edges = "edges" in node or "edges_as_multiples" in node

    if not has_edges:
        if "direction" in node:
            raise ConfigError(f"{where}: direction is meaningless on a categorical rung spec")
        if len(labels) < 2:
            raise ConfigError(f"{where}: categorical rungs need at least [absent, present] labels")
        return RungSpec(kind="categorical", labels=labels,
                        provenance=node.get("provenance"))

    direction = node.get("direction")
    if direction not in ("lower_is_better", "higher_is_better"):
        raise ConfigError(f"{where}: numeric rungs require direction "
                          "(lower_is_better | higher_is_better)")
    reference = node.get("reference")
    if "edges_as_multiples" in node:
        if reference is None:
            raise ConfigError(f"{where}: edges_as_multiples requires a reference")
        try:
            base = float(resolve_reference(reference, binding, card))
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigError(f"{where}: cannot resolve reference {reference!r}: {exc}") from exc
        edges = tuple(base * float(m) for m in node["edges_as_multiples"])
    else:
        edges = tuple(float(e) for e in node["edges"])
    if not all(math.isfinite(e) for e in edges):
        raise ConfigError(f"{where}: edges must be finite")
    if list(edges) != sorted(edges):
        raise ConfigError(f"{where}: edges must be ascending, got {edges}")
    if len(labels) != len(edges) + 1:
        raise ConfigError(f"{where}: {len(edges)} edges need {len(edges) + 1} labels, "
                          f"got {len(labels)}")
    return RungSpec(kind="numeric", labels=labels, direction=direction, edges=edges,
                    reference=reference, absent_label=node.get("absent_label"),
                    provenance=node.get("provenance"))


def _parse_indicator(node: dict, card: dict, block_families: dict, where: str) -> IndicatorSpec:
    for key in ("name", "indicator"):
        if key not in node:
            raise ConfigError(f"{where}: indicator entry missing {key!r}")
    where = f"{where}.{node['name']}"
    if node["indicator"] not in REGISTRY:
        raise ConfigError(f"{where}: unknown indicator {node['indicator']!r}")
    binding = dict(node.get("binding") or {})
    for key in _BINDING_ENTITY_KEYS:
        if key not in binding:
            continue
        pool = block_families if key == "block_family" else card.get(f"{key}s", {})
        if binding[key] not in pool:
            raise ConfigError(f"{where}: binding {key} {binding[key]!r} not in playground card")
    if "zones_ref" in binding:
        try:
            zones = resolve_reference(binding["zones_ref"], binding, card)
        except (KeyError, TypeError) as exc:
            raise ConfigError(f"{where}: cannot resolve zones_ref "
                              f"{binding['zones_ref']!r}: {exc}") from exc
        if not isinstance(zones, dict):
            raise ConfigError(f"{where}: zones_ref must resolve to a mapping of zones")
    rungs = _parse_rungs(node["rungs"], binding, card, where) if "rungs" in node else None
    flag_rules = tuple(dict(r) for r in node.get("flag_rules") or ())
    for rule in flag_rules:
        for key in ("flag", "when_rung_in", "other_indicator", "other_rung_in"):
            if key not in rule:
                raise ConfigError(f"{where}: flag_rule missing {key!r}")
    return IndicatorSpec(name=str(node["name"]), indicator=node["indicator"],
                         binding=binding, rungs=rungs, flag_rules=flag_rules)


def _config_version(playground_card: dict, goals_card: dict, robot_card: dict,
                    capabilities: dict | None = None) -> str:
    canonical = json.dumps([playground_card, goals_card, robot_card,
                            capabilities or {}], sort_keys=True,
                           separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]


def resolve_capability(block_type: str, capabilities: dict) -> dict:
    """D2 layer-1 lookup: explicit entry > longest family prefix > unknown
    default. Returns the entry dict ({class, flag?, ...}); the unknown
    default guarantees a named flag for anything unrecognized — never a
    crash, never silence."""
    entry = (capabilities.get("blocks") or {}).get(block_type)
    if entry:
        return entry
    fams = capabilities.get("families") or {}
    best = None
    for prefix, fam_entry in fams.items():
        if block_type.startswith(prefix) and (best is None or len(prefix) > best[0]):
            best = (len(prefix), fam_entry)
    if best:
        return best[1]
    return dict(capabilities.get("unknown_default")
                or {"class": "unsimulable", "flag": "unmodeled_blocks"})


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"missing config card: {path}")
    with path.open("r", encoding="utf-8") as f:
        card = yaml.safe_load(f)
    if not isinstance(card, dict):
        raise ConfigError(f"{path} is not a YAML mapping")
    return card


def configs_root(configs_dir=None):
    value = configs_dir or os.environ.get("GOAL_STRATEGY_CONFIG_DIR") or os.environ.get("VEX_GOAL_PROFILES_CONFIG_DIR")
    return Path(value).expanduser().resolve() if value else _DEFAULT_CONFIGS_DIR


def load_configs(playground: str, configs_dir: str | None = None) -> LoadedConfig:
    # Copy cached cards/context so callers and scenarios cannot mutate other runs.
    return copy.deepcopy(_load_configs(playground, configs_root(configs_dir)))


@functools.lru_cache(maxsize=32)
def _load_configs(playground, base):
    card = _load_yaml(base / "playgrounds" / f"{playground}.yaml")
    goals_card = _load_yaml(base / "goals" / f"{playground}.yaml")
    # Shared robot hardware card (reviewer ruling 2026-08-19: sensor hardware
    # is a robot property, not a playground property). Optional so synthetic
    # test playgrounds without a robot/ directory keep working.
    robot_path = base / "robot" / f"{card.get('robot_ref', 'vr_robot')}.yaml"
    robot_card = _load_yaml(robot_path) if robot_path.exists() else {}
    # Simulation-capability registry (D2 layer 1, ruled 2026-08-21):
    # transferable across playgrounds, so it lives at the configs root.
    # Optional so synthetic test config dirs keep working.
    cap_path = base / "capabilities.yaml"
    capabilities = _load_yaml(cap_path) if cap_path.exists() else {}

    if card.get("playground_id") != playground:
        raise ConfigError(f"playground card id {card.get('playground_id')!r} != {playground!r}")
    if goals_card.get("playground") != playground:
        raise ConfigError(f"goals card is for {goals_card.get('playground')!r}, "
                          f"not {playground!r}")

    families = {str(fam): frozenset(types)
                for fam, types in (card.get("block_families") or {}).items()}

    goals = []
    for goal_node in goals_card.get("goals") or []:
        if "id" not in goal_node:
            raise ConfigError("goal entry missing 'id'")
        where = f"goal {goal_node['id']}"
        goals.append(GoalSpec(
            id=str(goal_node["id"]),
            label=str(goal_node.get("label", goal_node["id"])),
            intent=tuple(_parse_indicator(n, card, families, f"{where}.intent")
                         for n in goal_node.get("intent") or []),
            attainment=tuple(_parse_indicator(n, card, families, f"{where}.attainment")
                             for n in goal_node.get("attainment") or []),
        ))

    return LoadedConfig(
        playground=playground,
        card=card,
        context=PlaygroundContext.from_playground_card(card, robot_card),
        block_families=families,
        goals=tuple(goals),
        config_version=_config_version(card, goals_card, robot_card, capabilities),
        robot=robot_card,
        capabilities=capabilities,
    )

# Keep the established explicit invalidation API. Derived caches that read the
# same card contents (e.g. the adapter's alias->canonical map) register here so
# one cache_clear() call stays coherent after external cards are edited.
_CACHE_CLEARERS = [_load_configs.cache_clear]


def _clear_config_caches():
    for clear in _CACHE_CLEARERS:
        clear()


def register_config_cache_clearer(clear):
    """Register a derived-cache invalidator so load_configs.cache_clear() drops
    it too. Called at import time by caches keyed on card contents."""
    _CACHE_CLEARERS.append(clear)


load_configs.cache_clear = _clear_config_caches
