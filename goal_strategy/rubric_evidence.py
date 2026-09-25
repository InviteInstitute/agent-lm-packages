"""Code/full-program rubric evidence (B-2 layer 1, researcher-agreed
2026-08-31 — RUBRIC_SCORING.md "The code/full-program extraction layer").

Extracts the code-side half of the rubric indicator set from the parsed
program plus the PRODUCTION SimulationResult the profile already
computes. Nothing re-runs; nothing here is a level — these are evidence
variables for the joint model, kept separate from GoalProfile.

Sensing here INCLUDES down-eye color: the red line is environment.
(Battery ELIGIBILITY excludes it because the sim models it faithfully —
different question, different set.)

v1 operationalizations (documented per extract; refine with the
reviewer):
- a wait_until "release" is approximated as its `.next` block appearing
  later in the path than the wait's first appearance;
- a procedures_call inside an exercised loop/conditional body is counted
  as exercised (calls emit no trace event of their own);
- a called My Block body is executable code: its blocks join the census, and
  their loop / conditional ancestry continues through each live call site
  (the body runs where it is called);
- state-gated motion counts a CONTINUOUS drive/turn whose immediate
  next block is a sensing wait_until.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .detector.parsing.block_program import procedure_name

_SENSING_PREFIXES = ("pg_sensing_",)
_SENSING_HATS = ("pg_events_optical_detect_object", "pg_events_when_bumper")
_LOOP_TYPES = ("pg_control_forever", "pg_control_repeat",
               "pg_control_repeat_until", "pg_control_while")
_CONDITIONAL_TYPES = ("pg_control_if_then", "pg_control_if_then_else",
                      "pg_control_if_elseif_else")
_MOTION_PREFIX = "pg_drivetrain_"
_CONTINUOUS_MOTION = ("pg_drivetrain_drive", "pg_drivetrain_turn")
_MOTION_PARAM_BLOCKS = ("pg_drivetrain_drive_for", "pg_drivetrain_turn_for",
                        "pg_drivetrain_turn_to_heading")
# literal value shadows (mirrors the simulator's literal set)
_LITERAL_TYPES = ("math_number", "math_positive_number", "math_whole_number",
                  "math_number_string", "math_positive_number_only")


@dataclass(frozen=True)
class CodeEvidence:
    """One record per run; evidence_source is `rules` for census fields,
    `simulated` for trace/path-derived fields."""
    program_id: str
    # census (rules)
    sensing_in_executable: bool
    sensing_in_recurrent: bool
    has_loops: bool
    has_conditionals: bool
    has_procedures: bool
    has_variables: bool
    # per-dimension maximum levels from the census ceilings (None = the
    # dimension's own top — no cap)
    ceilings: dict = field(default_factory=dict)
    # trace/path-derived (simulated)
    condition_arm_alternations: dict = field(default_factory=dict)
    max_arm_alternations: int = 0
    wait_release_counts: dict = field(default_factory=dict)
    construct_coordination_relations: int = 0
    coordination_detail: tuple = ()
    state_terminated_motion_fraction: float | None = None
    # ---- construct-separability build (reviewer-ruled 2026-09-05) ----
    # Control Structure (architecture set — census/trace):
    exercised_loops_fixed: int = 0        # repeat(count) that ran
    exercised_loops_state: int = 0        # repeat_until/while that ran
    exercised_loops_forever: int = 0
    exercised_conditional_count: int = 0  # branch ids seen in BRANCH_ARM
    max_nesting_depth: int = 0            # deepest loop/conditional chain
    state_controlled_termination: bool = False
    # Spatial/Motion (state-derived set — primary L2 evidence):
    state_gated_drivetrain_count: int = 0   # motion blocks under EVALUATED
                                            # sensing conditionals (the
                                            # architecture count — diagnostic
                                            # since the OI-33 ruling)
    # OI-33 ruling (2026-09-10, "attempts are flawed"): the SCORING
    # variant — gated motion blocks that actually EXECUTED in the
    # production run. An evaluated-but-never-taken motion arm is an
    # attempt, not demonstrated state-derived motion.
    state_gated_drivetrain_executed: int = 0
    gated_sensor_fields: tuple = ()         # diagnostic: sensor[field] set on
                                            # motion-gating conditionals (the
                                            # mis-wired-sensor surfacing)
    computed_motion_param_count: int = 0    # non-literal AMOUNT expressions
    # Representation & Abstraction (code-representation set):
    procedure_metrics: dict = field(default_factory=dict)
    variable_metrics: dict = field(default_factory=dict)
    duplicated_sequence_count: int = 0
    # SMC-1 parameter audit (2026-09-09, parse-only): motion literals
    # within the claims card's calibration_tolerance_pct of a
    # card-geometry distance (spawn->piece, spawn->zone centroid,
    # island half-extents). Presence >=1 = the Calibrated inference.
    calibrated_param_matches: int = 0
    motion_literal_count: int = 0


def _is_sensing(bt: str) -> bool:
    return bt.startswith(_SENSING_PREFIXES) or bt in _SENSING_HATS


def _walk(node):
    """Pre-order: a block, its statement bodies, its value inputs, then the next
    block. Iterative, so neither a long sequence nor deep nesting costs stack."""
    pending = [node]
    while pending:
        cur = pending.pop()
        if cur is None:
            continue
        yield cur
        pending.append(cur.next)
        pending.extend(reversed(cur.values))
        pending.extend(reversed(cur.children))


def _subtree_has_sensing(node) -> bool:
    return any(_is_sensing(b.block_type) for b in _walk_values_only(node))


def _walk_values_only(node):
    """The node and its VALUE subtree (a condition expression), not its
    statement bodies or siblings."""
    yield node
    for value in node.values:
        yield from _walk_values_only(value)


def _call_sites(program, blocks) -> dict:
    """id(node) -> the procedures_call nodes that run it, for every
    chain-level node of a called My Block definition (the definition and its
    body's top-level next-chain). Deeper body nodes reach one of these by
    following .parent. Only calls among `blocks` (live, not statically dead)
    count."""
    calls: dict = {}
    for b in blocks:
        if b.block_type == "procedures_call":
            calls.setdefault(procedure_name(b), []).append(b)
    sites: dict = {}
    for definition in program.procedure_stacks:
        callers = calls.get(procedure_name(definition), [])
        node = definition
        while node is not None:
            sites[id(node)] = callers
            node = node.next
    return sites


class _Ancestry:
    """Ancestor queries that look through My Block call sites: inside a called
    My Block body, a block's ancestors continue from each call that runs the
    body, so a body block called from inside a loop has that loop as an
    ancestor. Recursive calls are cut (a call already being followed is not
    followed again).

    Each call site's answer is computed once and reused by every block under
    it, so a query costs the walk up the block's own body plus cached lookups.
    Enumerating every ancestor path instead costs the product of the call-site
    counts at each My Block level, which is exponential in how deeply My Blocks
    call each other."""

    _PENDING = object()

    def __init__(self, sites):
        self._sites = sites or {}
        self._first = {}   # (predicate, id(call)) -> nearest match via that call
        self._depth = {}   # (predicate, id(call)) -> max matches via that call

    def _chain(self, node):
        """The node's ancestors inside its own body (nearest first) and the
        topmost one, whose call sites continue the chain."""
        chain, top, p = [], node, node.parent
        while p is not None:
            chain.append(p)
            top = p
            p = p.parent
        return chain, top

    def first(self, node, pred):
        """The nearest ancestor matching pred: first up the node's own body,
        then through each call site in order."""
        chain, top = self._chain(node)
        for p in chain:
            if pred(p):
                return p
        for call in self._sites.get(id(top), ()):
            key = (pred, id(call))
            found = self._first.get(key)
            if found is self._PENDING:
                continue
            if key not in self._first:
                self._first[key] = self._PENDING
                found = call if pred(call) else self.first(call, pred)
                self._first[key] = found
            if found is not None:
                return found
        return None

    def depth(self, node, pred):
        """The most ancestors matching pred along any chain of call sites."""
        chain, top = self._chain(node)
        best = 0
        for call in self._sites.get(id(top), ()):
            key = (pred, id(call))
            got = self._depth.get(key)
            if got is self._PENDING:
                continue
            if got is None:
                self._depth[key] = self._PENDING
                got = int(pred(call)) + self.depth(call, pred)
                self._depth[key] = got
            best = max(best, got)
        return sum(1 for p in chain if pred(p)) + best


def _is_loop(node) -> bool:
    return node.block_type in _LOOP_TYPES


def _is_body(node) -> bool:
    return node.block_type in _LOOP_TYPES or node.block_type in _CONDITIONAL_TYPES


def _loop_ancestor(node, ancestry):
    return ancestry.first(node, _is_loop)


def _body_ancestor(node, ancestry):
    """Nearest loop OR conditional ancestor (for procedure-call coordination)."""
    return ancestry.first(node, _is_body)


def calibration_audit(program, geometry_mm: "list[float]",
                      tolerance_pct: float = 10.0,
                      dead: set | None = None) -> tuple:
    """SMC-1 parameter audit (parse-only, 2026-09-09): (matches, total)
    over drive_for/turn-distance literals — a literal within
    tolerance_pct of ANY card-geometry distance counts as calibrated.
    Geometry targets are card-derived by the caller (YAML-only:
    tolerance from _claims.yaml). Statically-dead blocks excluded
    (OI-33 liveness ruling 2026-09-10)."""
    if dead is None:
        dead = statically_dead_ids(program)
    lits = []
    for root in program.live_stacks:
        for b in _walk(root):
            if b.block_type in _MOTION_PARAM_BLOCKS[:2]:   # drive_for/turn_for? distances only
                if b.block_type != "pg_drivetrain_drive_for":
                    continue
                if b.block_id in dead:
                    continue
                slot = (getattr(b, "value_slots", None) or {}).get("AMOUNT")
                cand = slot if slot is not None else (b.values[0] if b.values else None)
                if cand is not None and cand.block_type in _LITERAL_TYPES:
                    v = cand.get_field("NUM")
                    try:
                        lits.append(abs(float(v)))
                    except (TypeError, ValueError):
                        pass
    matches = 0
    for lit in lits:
        for g in geometry_mm:
            if g > 0 and abs(lit - g) / g * 100.0 <= tolerance_pct:
                matches += 1
                break
    return matches, len(lits)


def card_geometry_targets(playground_card: dict) -> "list[float]":
    """Distances a calibrated dead-reckoner would encode: spawn->piece
    centres, spawn->zone centroid, island half-extents."""
    import math
    out = []
    spawns = playground_card.get("spawn_points") or {}
    if isinstance(spawns, dict):
        sp = next(iter(spawns.values()), {}) if spawns else {}
    else:
        sp = spawns[0] if spawns else {}
    sx, sy = float(sp.get("x", 0) or 0), float(sp.get("y", 0) or 0)
    for name, obj in (playground_card.get("objects") or {}).items():
        try:
            out.append(math.hypot(float(obj["x"]) - sx, float(obj["y"]) - sy))
        except (KeyError, TypeError, ValueError):
            pass
    poly = ((playground_card.get("field_boundary") or {}).get("polygon_mm")
            or [])
    if poly:
        xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
        out += [(max(xs) - min(xs)) / 2.0, (max(ys) - min(ys)) / 2.0]
    for rid, reg in (playground_card.get("regions") or {}).items():
        rp = reg.get("polygon_mm") or []
        if rp:
            cx = sum(p[0] for p in rp) / len(rp)
            cy = sum(p[1] for p in rp) / len(rp)
            import math as _m
            out.append(_m.hypot(cx - sx, cy - sy))
    return [g for g in out if g > 50]


def statically_dead_ids(program) -> set:
    """Block ids that can NEVER execute: everything following a
    `forever` loop in the same next-chain (descendants included).
    OI-33 liveness ruling (2026-09-10): parse-only evidence walks only
    code that could execute in the playground — reachable-but-untaken
    branches stay in (they could run); post-forever chains cannot.
    Detached stacks and uncalled My Blocks are already excluded upstream
    (orphan_stacks); called My Block bodies are swept like any live stack."""
    dead: set = set()

    def _sub(n):
        yield n
        for c in n.children:
            yield from _sub(c)
        for v in n.values:
            yield from _sub(v)

    def _sweep(chain_head, dead_mode):
        cur = chain_head
        while cur is not None:
            if dead_mode:
                for x in _sub(cur):
                    dead.add(x.block_id)
            for ch in cur.children:
                _sweep(ch, dead_mode)
            if cur.block_type == "pg_control_forever" and not dead_mode:
                _sweep(cur.next, True)
                return
            cur = cur.next

    for root in program.live_stacks:
        _sweep(root, False)
    return dead


def fixed_motion_vocabulary(program, dead: set | None = None) -> dict:
    """SMC lower-scale restructure (reviewer-ruled 2026-09-09,
    parse-only): the run's fixed-motion literal vocabulary —
    drive_for / turn_for literal AMOUNTs. These lists plus the
    diagnostics computed from them are INGREDIENTS for the one ordinal
    indicator (fixed_motion_specificity), never separate scoring
    variables. Statically-dead blocks (post-forever) are excluded —
    OI-33 liveness ruling 2026-09-10; pass a precomputed `dead` set
    or let it compute one."""
    if dead is None:
        dead = statically_dead_ids(program)
    drives, turns = [], []
    for root in program.live_stacks:
        for b in _walk(root):
            if b.block_type not in ("pg_drivetrain_drive_for",
                                    "pg_drivetrain_turn_for"):
                continue
            if b.block_id in dead:
                continue
            slot = (getattr(b, "value_slots", None) or {}).get("AMOUNT")
            cand = slot if slot is not None else (b.values[0] if b.values
                                                  else None)
            if cand is not None and cand.block_type in _LITERAL_TYPES:
                import math
                try:
                    v = abs(float(cand.get_field("NUM")))
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(v):
                    # a literal parsing to inf/nan (seen once in the
                    # full corpus) is not a usable motion parameter —
                    # skipped like an unparseable one
                    continue
                (drives if b.block_type == "pg_drivetrain_drive_for"
                 else turns).append(v)
    return {"drives": drives, "turns": turns}


def _value_clusters(vals: "list[float]", merge_pct: float) -> int:
    """Count of meaningfully-distinct values: sorted values within
    merge_pct of the cluster anchor merge (the 'meaningfully distinct'
    read — 1497 and 1500 are one value, 200 and 800 are two)."""
    n, anchor = 0, None
    for v in sorted(set(vals)):
        if anchor is None or (anchor > 0
                              and (v - anchor) / anchor * 100 > merge_pct):
            n, anchor = n + 1, v
    return n


def _is_multiple(v: float, m: float) -> bool:
    return m > 0 and abs(v / m - round(v / m)) < 1e-9


def fixed_motion_diagnostics(vocab: dict, palette: dict) -> dict:
    """The audit ingredients under the claims card's smc_vocabulary
    palette (corpus-derived 2026-09-09). Emitted as diagnostics —
    they explain why the specificity indicator fired, never score."""
    drives, turns = vocab["drives"], vocab["turns"]
    canon_d = set(float(x) for x in palette.get("canonical_drive_values")
                  or [])
    canon_t = set(float(x) for x in palette.get("canonical_turn_values")
                  or [])
    round_d = float(palette.get("round_drive_multiple_mm") or 0)
    card_t = float(palette.get("cardinal_turn_multiple_deg") or 0)
    merge = float(palette.get("cluster_merge_pct") or 5)
    fine_m = float(palette.get("fine_grain_multiple") or 5)
    is_canon_d = lambda v: v in canon_d or _is_multiple(v, round_d)
    is_canon_t = lambda v: v in canon_t or _is_multiple(v, card_t)
    n_canon = (sum(1 for v in drives if is_canon_d(v))
               + sum(1 for v in turns if is_canon_t(v)))
    total = len(drives) + len(turns)
    return {
        "distinct_drive_clusters": _value_clusters(drives, merge),
        "distinct_turn_clusters": _value_clusters(turns, merge),
        "canonical_prop": (n_canon / total) if total else None,
        "fine_value_count": sum(1 for v in drives + turns
                                if not _is_multiple(v, fine_m)),
        "literal_total": total,
    }


def fixed_motion_specificity(diag: dict, rule: dict):
    """The ONE new ordinal indicator (reviewer-ruled 2026-09-09):
    0 = coarse/default (predominantly palette parameters), 1 =
    differentiated (credible fitted-to-problem residue), None =
    insufficient fixed motion to characterize. All thresholds live in
    the claims card (smc_specificity) with their D-d inference labels;
    the rule is deliberately a disjunction of differentiation signals
    measured in the 2026-09-09 corpus audit."""
    if diag["literal_total"] < int(rule.get("min_literals") or 1):
        return None
    if diag["distinct_drive_clusters"] >= int(
            rule.get("distinct_drive_clusters_min") or 3):
        return 1
    if diag["fine_value_count"] >= int(rule.get("fine_values_min") or 1):
        return 1
    prop = diag["canonical_prop"]
    if (prop is not None
            and diag["literal_total"] >= int(
                rule.get("canonical_prop_min_literals") or 4)
            and prop <= float(rule.get("canonical_prop_max") or 0.5)):
        return 1
    return 0


def canonical_ambiguous_matches(program, geometry_mm: "list[float]",
                                tolerance_pct: float,
                                palette: dict) -> int:
    """Contamination diagnostic (audit finding 2026-09-09): geometry
    matches whose literal is ALSO a NAMED top-palette value (752~800,
    988~1000, 1972~2000 on this card) — the match may be a popular
    number, not calibration. Deliberately restricted to the explicit
    canonical list (NOT every round multiple — students type round
    numbers when calibrating too, and the probe showed the broad rule
    flags every match). Annotates route-A awards for review; whether
    to discount them is a reviewer call, never made here."""
    canon_d = set(float(x) for x in palette.get("canonical_drive_values")
                  or [])
    vocab = fixed_motion_vocabulary(program)
    n = 0
    for lit in vocab["drives"]:
        if lit not in canon_d:
            continue
        if any(g > 0 and abs(lit - g) / g * 100.0 <= tolerance_pct
               for g in geometry_mm):
            n += 1
    return n


def smc_lower_columns(program, geometry_mm: "list[float]",
                      tolerance_pct: float, palette: dict,
                      rule: dict) -> list:
    """The six SMC lower-scale CSV values in CE_HEADER order —
    shared by rung_sweep (native emission) and the committed backfill
    script so the two paths can never diverge:
    [fixed_motion_specificity ('' = None), distinct_drive_clusters,
     distinct_turn_clusters, canonical_prop ('' = None, 3dp),
     fine_value_count, canonical_ambiguous_matches]."""
    vocab = fixed_motion_vocabulary(program)
    diag = fixed_motion_diagnostics(vocab, palette)
    spec = fixed_motion_specificity(diag, rule)
    return [
        "" if spec is None else spec,
        diag["distinct_drive_clusters"], diag["distinct_turn_clusters"],
        ("" if diag["canonical_prop"] is None
         else round(diag["canonical_prop"], 3)),
        diag["fine_value_count"],
        canonical_ambiguous_matches(program, geometry_mm,
                                    tolerance_pct, palette),
    ]


def code_evidence(program, sim) -> CodeEvidence:
    executable = list(program.live_stacks)
    # OI-33 liveness ruling (2026-09-10): the census and every
    # parse-side count walk only code that could execute — post-forever
    # chains are out (trace-derived facts are unaffected: dead blocks
    # never appear in a trace anyway).
    _dead = statically_dead_ids(program)
    blocks = [b for root in executable for b in _walk(root)
              if b.block_id not in _dead]
    by_id = {b.block_id: b for b in blocks}
    ancestry = _Ancestry(_call_sites(program, blocks))

    sensing_blocks = [b for b in blocks if _is_sensing(b.block_type)]
    sensing_in_executable = bool(sensing_blocks)
    # hats are recurrent by semantics (edge-triggered re-arming); reporters
    # are recurrent when a loop encloses them
    sensing_in_recurrent = any(
        b.block_type in _SENSING_HATS or _loop_ancestor(b, ancestry) is not None
        for b in sensing_blocks)

    has_loops = any(b.block_type in _LOOP_TYPES for b in blocks)
    has_conditionals = any(b.block_type in _CONDITIONAL_TYPES for b in blocks)
    has_procedures = any(b.block_type == "procedures_call" for b in blocks)
    has_variables = any(b.block_type.startswith("pg_variables_") for b in blocks)

    # ---- census ceilings (the economy rule, computable) ----
    ceilings: dict = {}
    if not sensing_in_executable:
        ceilings.update(environmental_feedback=0, task_state_regulation=0,
                        recovery=0, spatial_motion=1)
    elif not sensing_in_recurrent:
        ceilings.update(environmental_feedback=1, task_state_regulation=1,
                        recovery=1)
    if not (has_loops or has_conditionals):
        ceilings["control_structure"] = 0
    elif not has_loops:
        ceilings["control_structure"] = 2   # state-dependent possible; no
        # structured repetition and no loop-coordinated integration
    if not (has_loops or has_procedures or has_variables):
        ceilings["representation"] = 0

    # ---- condition_arm_alternations (trace) ----
    arm_seqs: dict[str, list] = {}
    for _th, evt, blk, detail in (sim.structure_trace or []):
        if evt == "BRANCH_ARM":
            arm_seqs.setdefault(blk, []).append(detail)
    alternations = {}
    for blk, seq in arm_seqs.items():
        node = by_id.get(blk)
        if node is None or not _subtree_has_sensing(node):
            continue      # only sensor-fed conditions carry EF meaning
        alternations[blk] = sum(1 for a, b in zip(seq, seq[1:]) if a != b)
    max_alt = max(alternations.values(), default=0)

    # ---- wait_until releases (path, v1 approximation) ----
    path_ids = [p.block_id for p in (sim.path or [])]
    # Where each block sits on the path, built once: the executed path can run
    # to the simulator's 50k-block budget, so per-block rescans of it add up.
    positions: dict[str, list[int]] = {}
    for i, bid in enumerate(path_ids):
        positions.setdefault(bid, []).append(i)
    first_at = {bid: at[0] for bid, at in positions.items()}

    def _count(bid):
        return len(positions.get(bid, ()))
    wait_releases: dict[str, int] = {}
    for b in blocks:
        if b.block_type != "pg_control_wait_until":
            continue
        if not _subtree_has_sensing(b):
            continue
        nxt = b.next
        if b.block_id in first_at and nxt is not None \
                and nxt.block_id in positions \
                and positions[nxt.block_id][-1] > first_at[b.block_id]:
            wait_releases[b.block_id] = min(
                _count(b.block_id), _count(nxt.block_id))

    # ---- construct_coordination_relations ----
    loops_run = set((sim.loops_exercised or {}).keys())
    relations: list[str] = []
    # Separability ruling (2026-09-05): coordination is ARCHITECTURE, not
    # environment response — an EXERCISED sensing conditional inside an
    # exercised loop is a relation regardless of whether its arms ever
    # alternated. Alternation stays EF evidence only.
    for blk in arm_seqs:
        node = by_id.get(blk)
        if node is None or not _subtree_has_sensing(node):
            continue
        loop = _loop_ancestor(node, ancestry)
        if loop is not None and loop.block_id in loops_run:
            relations.append(f"live_conditional_in_loop:{blk}")
    for b in blocks:
        if b.block_type in ("pg_control_repeat_until", "pg_control_while") \
                and b.block_id in loops_run and _subtree_has_sensing(b):
            nxt = b.next
            if nxt is not None and nxt.block_id in first_at:
                relations.append(f"sensing_terminated_loop:{b.block_id}")
    for blk, n in wait_releases.items():
        node = by_id[blk]
        loop = _loop_ancestor(node, ancestry)
        if n >= 1 and loop is not None and loop.block_id in loops_run:
            relations.append(f"sensing_wait_in_loop:{blk}")
    for b in blocks:
        if b.block_type == "procedures_call":
            anc = _body_ancestor(b, ancestry)
            if anc is not None and (anc.block_id in loops_run
                                    or anc.block_id in arm_seqs):
                relations.append(f"procedure_in_construct:{b.block_id}")

    # ---- state_terminated_motion_fraction (BROADENED 2026-09-05) ----
    # The v1 rule credited only the literal `drive; wait_until` adjacency
    # and read 0.0 for 99% of the population (measured — it missed the
    # dominant conditional-redirect idiom). A motion segment now counts
    # as state-terminated when a drivetrain state change coincides with
    # a STATE EVENT:
    #   (a) a sensing wait_until release with a drivetrain block among
    #       the next 3 executed path rows (or gating a continuous drive);
    #   (b) a sensing-predicated loop exit whose successor executed;
    #   (c) a sensing conditional ARM CHANGE where some arm contains an
    #       executed drivetrain block (the redirect idiom);
    #   (d) a sensor-hat firing whose stack contains executed drivetrain.
    motion_execs = [bid for bid in path_ids
                    if by_id.get(bid) is not None
                    and by_id[bid].block_type.startswith(_MOTION_PREFIX)]
    motion_ids = set(motion_execs)

    def _stmt_walk(node):
        """The node's statement bodies, recursively (not values/siblings
        of the node itself)."""
        for child in node.children:
            yield from _walk(child)

    state_events = 0
    # (a) wait releases followed by motion
    for b in blocks:
        if b.block_type != "pg_control_wait_until" or not _subtree_has_sensing(b):
            continue
        if b.next is not None and b.next.block_type in _CONTINUOUS_MOTION:
            state_events += _count(b.block_id)
            continue
        for i in positions.get(b.block_id, ()):
            look = path_ids[i + 1:i + 4]
            if any(l in motion_ids for l in look):
                state_events += 1
    # (b) sensing-loop exits followed by anything (the exit IS the
    # state-driven motion boundary; successor execution proves the exit)
    for b in blocks:
        if b.block_type in ("pg_control_repeat_until", "pg_control_while") \
                and b.block_id in loops_run and _subtree_has_sensing(b):
            nxt = b.next
            if nxt is not None and nxt.block_id in first_at:
                state_events += _count(nxt.block_id)
    # (c) arm changes on sensing conditionals whose arms drive
    for blk, alts in alternations.items():
        if alts < 1:
            continue
        node = by_id[blk]
        if any(x.block_id in motion_ids or
               x.block_type.startswith(_MOTION_PREFIX)
               for x in _stmt_walk(node)):
            state_events += alts
    # (d) hat firings whose stack drives
    hats_fired = getattr(sim, "sensor_hats_fired", None) or {}
    for hat_id, steps in hats_fired.items():
        root = by_id.get(hat_id)
        if root is not None and any(
                x.block_type.startswith(_MOTION_PREFIX) for x in _walk(root)):
            state_events += len(steps) if hasattr(steps, "__len__") else int(steps)
    total = len(motion_execs) + state_events
    fraction = (state_events / total) if total else None

    # ---- Control Structure architecture set (2026-09-05) ----
    ex_fixed = ex_state = ex_forever = 0
    for lid in loops_run:
        node = by_id.get(lid)
        if node is None:
            continue
        if node.block_type == "pg_control_repeat":
            ex_fixed += 1
        elif node.block_type in ("pg_control_repeat_until", "pg_control_while"):
            ex_state += 1
        elif node.block_type == "pg_control_forever":
            ex_forever += 1
    exercised_conditionals = len(arm_seqs)

    max_depth = max((int(_is_body(b)) + ancestry.depth(b, _is_body) for b in blocks),
                    default=0)

    state_termination = bool(wait_releases) or any(
        r.startswith("sensing_terminated_loop") for r in relations)

    # ---- Spatial/Motion state-derived set (2026-09-05) ----
    # OI-33 ruling (2026-09-10): the count splits — `state_gated_motion`
    # is the ARCHITECTURE count (motion under an EVALUATED sensing
    # conditional; diagnostic), `state_gated_executed` requires the
    # gated motion block to have actually RUN (the scoring variant:
    # an evaluated-but-never-taken motion arm is an attempt, not
    # demonstrated state-derived motion). `gated_sensor_fields`
    # surfaces WHICH sensor gates motion — the mis-wired-sensor
    # diagnostic (front-eye edge checks etc.).
    state_gated_motion = 0
    state_gated_executed = 0
    gated_sensors: set = set()
    for b in blocks:
        if not b.block_type.startswith(_MOTION_PREFIX):
            continue
        anc = _body_ancestor(b, ancestry)
        # Walking up through call sites of recursive My Blocks comes back
        # around to ancestors already checked; stop there instead of looping.
        checked: set = set()
        while anc is not None and id(anc) not in checked:
            checked.add(id(anc))
            if anc.block_type in _CONDITIONAL_TYPES \
                    and _subtree_has_sensing(anc) \
                    and anc.block_id in arm_seqs:
                state_gated_motion += 1
                if b.block_id in positions:
                    state_gated_executed += 1
                for s in _walk_values_only(anc):
                    if _is_sensing(s.block_type):
                        f = (s.get_field("OPTICAL")
                             or s.get_field("DISTANCE")
                             or s.get_field("BUMPER") or "")
                        gated_sensors.add(f"{s.block_type}[{f}]")
                break
            anc = _body_ancestor(anc, ancestry)
    computed_params = 0
    for b in blocks:
        if b.block_type in _MOTION_PARAM_BLOCKS:
            slot = (getattr(b, "value_slots", None) or {}).get("AMOUNT")
            cand = slot if slot is not None else (b.values[0] if b.values else None)
            if cand is not None and cand.block_type not in _LITERAL_TYPES:
                computed_params += 1

    # ---- Representation & Abstraction code set (2026-09-05) ----
    proc_calls: dict[str, int] = {}
    parameterized = 0
    for b in blocks:
        mut = getattr(b, "mutation", None) or {}
        if b.block_type == "procedures_call":
            code = mut.get("proccode", "?")
            proc_calls[code] = proc_calls.get(code, 0) + 1
            if (mut.get("argumentnames") or "[]") not in ("", "[]"):
                parameterized += 1
    procedure_metrics = {
        "calls": sum(proc_calls.values()),
        "distinct": len(proc_calls),
        "reused": sum(1 for n in proc_calls.values() if n >= 2),
        "parameterized_calls": parameterized,
    }
    var_set = var_read = 0
    set_names: set = set()
    read_names: set = set()
    for b in blocks:
        bt = b.block_type
        if bt.startswith("pg_variables_set") or bt.startswith("pg_variables_change") \
                or bt in ("variables_set", "variables_change", "math_change"):
            var_set += 1
            n = b.get_field("VARIABLE")
            if n:
                set_names.add(n)
        elif bt in ("pg_variables_variable", "pg_variables_boolean_variable"):
            var_read += 1
            n = b.get_field("VARIABLE")
            if n:
                read_names.add(n)
    variable_metrics = {"sets": var_set, "reads": var_read,
                        "names_reused": len(set_names & read_names)}
    # duplicated linear sequences (v1: distinct 3-grams of block types
    # appearing >= 2 times across next-chains — duplication signals
    # concrete representation; factoring removes it)
    chains: list[list] = []
    def _chains_from(node):
        chain = []
        cur = node
        while cur is not None:
            chain.append(cur.block_type)
            for child in cur.children:
                _chains_from(child)
            cur = cur.next
        if len(chain) >= 3:
            chains.append(chain)
    for root in executable:
        _chains_from(root)
    grams: dict[tuple, int] = {}
    for chain in chains:
        for i in range(len(chain) - 2):
            g = tuple(chain[i:i + 3])
            grams[g] = grams.get(g, 0) + 1
    dup_sequences = sum(1 for g, n in grams.items() if n >= 2)

    return CodeEvidence(
        program_id=getattr(program, "program_id", ""),
        sensing_in_executable=sensing_in_executable,
        sensing_in_recurrent=sensing_in_recurrent,
        has_loops=has_loops, has_conditionals=has_conditionals,
        has_procedures=has_procedures, has_variables=has_variables,
        ceilings=ceilings,
        condition_arm_alternations=alternations,
        max_arm_alternations=max_alt,
        wait_release_counts=wait_releases,
        construct_coordination_relations=len(relations),
        coordination_detail=tuple(relations),
        state_terminated_motion_fraction=fraction,
        exercised_loops_fixed=ex_fixed,
        exercised_loops_state=ex_state,
        exercised_loops_forever=ex_forever,
        exercised_conditional_count=exercised_conditionals,
        max_nesting_depth=max_depth,
        state_controlled_termination=state_termination,
        state_gated_drivetrain_count=state_gated_motion,
        state_gated_drivetrain_executed=state_gated_executed,
        gated_sensor_fields=tuple(sorted(gated_sensors)),
        computed_motion_param_count=computed_params,
        procedure_metrics=procedure_metrics,
        variable_metrics=variable_metrics,
        duplicated_sequence_count=dup_sequences,
    )
