"""Battery-side rubric evidence (B-2 layers 2+3, 2026-08-31).

Per-scenario indicator extraction over the artifacts `run_battery`
already preserves (the B-1(c) constraint: re-read, never re-run).
Thresholds come from the card's `episode_rules` block — card-declared,
environment-derived (reviewer ruling 2026-08-31) — never from constants
here.

v1 segmentation is EVENT-ANCHORED rather than a full span classifier:
onsets from `world_event_log` / piece materialization, engagement from
`object_contacts`, clears from `pieces_cleared`, band entry/retreat from
path distance to the placed (or card) boundary edges. The four episode
indicators read those seams. An abstained scenario yields an abstained
evidence record — no extracts (the ruled U semantics).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from goal_strategy.detector.simulation.simulate_path import _point_segment_dist

from .rubric_evidence import CodeEvidence, code_evidence


@dataclass(frozen=True)
class ScenarioEvidence:
    scenario_id: str
    family: str
    construct: str
    abstained: bool = False
    abstain_reason: str | None = None
    onset_step: int | None = None
    # OI-37 (2026-09-11): the failure step — first densified sample
    # outside the island beyond grace. Responsiveness evidence below is
    # scored only BEFORE this step. None = never failed.
    scenario_exit_step: int | None = None
    # EF / Recovery: travel from onset to first >divergence_mm departure
    # from the scenario baseline (None = never diverged)
    response_latency_mm: float | None = None
    # EF / TSR: travel from onset to first movable contact
    engagement_latency_mm: float | None = None
    # TSR (T3's disappearance cue): travel from a piece clearing to the
    # next behaviour change (heading change > turn_change_deg or reversal)
    post_clear_action_latency_mm: float | None = None
    # EF-2 / TSR-2 / Recovery-2: band entries separated by full retreats
    boundary_band_entries: int = 0
    # Recovery-1: after the first band entry, did the robot retreat?
    corrective_response_present: bool | None = None
    # TSR: ordered seams (step, kind) and the count of kind CHANGES
    behavioral_seams: tuple = ()
    behavioral_transition_count: int = 0
    # ---- task-semantic layer (construct-separability build 2026-09-05) ----
    # transitions whose seam is a TASK event (acquire/engage/clear/loss/
    # recovery) — TSR's primary variable; geometric boundary/retreat
    # seams excluded.
    task_state_triggered_transition_count: int = 0
    # engage/acquire seam AFTER a boundary+retreat pair (resolution ->
    # resumed pursuit)
    task_phase_return_count: int = 0
    # post-clear behaviour change within the card's post_clear_bar_mm
    completion_triggered_transition: bool | None = None
    # any engage after any full retreat (generalizes T6's gate)
    reengagement_after_resolution: bool = False
    # deviation -> correction -> reassessment -> further correction or
    # task seam (Recovery-2's primary variable, previously proxied)
    correction_reassessment_cycles: int = 0
    # trace re-read on the SCENARIO sim (same extractor as production)
    code: CodeEvidence | None = None


def _edges(sim, ctx):
    """The boundary edges the run was tested against: placed edges when
    world events fired, else the card polygon's own edges."""
    placed = [(e[2], e[3]) for e in (sim.world_event_log or [])
              if e[2] is not None]
    if placed:
        return placed
    verts = list(ctx.field_hex_vertices or [])
    return [(verts[i], verts[(i + 1) % len(verts)])
            for i in range(len(verts))] if verts else []


def _d_edge(x, y, edges):
    return min((_point_segment_dist(x, y, a[0], a[1], b[0], b[1])
                for a, b in edges), default=float("inf"))


def edge_encounter_episodes(path, edges, polygon, band_mm: float,
                            retreat_mm: float, grace_mm: float,
                            origin: tuple | None = None):
    """Edge ENCOUNTERS (reviewer ruling 2026-09-01): episodes where the
    robot enters the ring band (within band_mm of an edge), separated by
    full retreats (>= retreat_mm). An episode is SURVIVED unless the
    robot's centre goes OUTSIDE the polygon by more than grace_mm during
    it — the depth grace reuses the production card's physical
    half-diagonal (on_island_xy_mm), so the permissible extension is
    literally the same number in both instruments. Returns a list of
    (entry_step, max_overshoot_mm, survived)."""
    from goal_strategy.detector.simulation.simulate_path import (
        _point_in_convex_polygon,
    )
    # SEGMENT-DENSIFIED walk (2026-09-01, the t6b probe): path points are
    # block ENDPOINTS, so a band crossed mid-drive_for — including the
    # assured-detection start pose, whose first block is the retreat
    # itself — never appears as a point. Interpolate each segment at
    # <= 25mm so nothing crossed mid-block is missed. `origin` (when
    # given) seeds the walk with the pre-first-block pose.
    def _samples():
        pts = []
        if origin is not None:
            pts.append((origin[0], origin[1], int(path[0].step) if path else 0))
        for p in path:
            pts.append((p.x, p.y, int(p.step)))
        for (x0, y0, s0), (x1, y1, s1) in zip(pts, pts[1:]):
            seg = math.hypot(x1 - x0, y1 - y0)
            n = max(1, int(seg // 25))
            for i in range(n):
                t = i / n
                yield (x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, s0)
        if pts:
            yield pts[-1]
    episodes = []
    in_episode, retreated = False, True
    entry_step, max_over = None, 0.0
    for sx, sy, sstep in _samples():
        d = _d_edge(sx, sy, edges)
        inside = (_point_in_convex_polygon(sx, sy, polygon)
                  if polygon else True)
        over = 0.0 if inside else d
        if not in_episode and d <= band_mm and retreated:
            in_episode, retreated = True, False
            entry_step, max_over = sstep, 0.0
        if in_episode:
            max_over = max(max_over, over)
            if inside and d >= retreat_mm:
                episodes.append((entry_step, max_over,
                                 max_over <= grace_mm))
                in_episode = False
                retreated = True
    if in_episode:
        episodes.append((entry_step, max_over, max_over <= grace_mm))
    return episodes


def _dense_samples(path, origin=None):
    """Segment-densified (x, y, step) walk (<=25mm sampling) — the same
    pattern edge_encounter_episodes uses: path points are block
    ENDPOINTS, so anything crossed mid-block never appears as a point.
    `step` is the SEGMENT-START step (conservative attribution)."""
    pts = []
    if origin is not None:
        pts.append((origin[0], origin[1], int(path[0].step) if path else 0))
    for p in path:
        pts.append((p.x, p.y, int(p.step)))
    for (x0, y0, s0), (x1, y1, s1) in zip(pts, pts[1:]):
        seg = math.hypot(x1 - x0, y1 - y0)
        n = max(1, int(seg // 25))
        for i in range(n):
            t = i / n
            yield (x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, s0)
    if pts:
        yield pts[-1]


def _scenario_exit_step(path, polygon, grace_mm: float,
                        origin=None):
    """The FAILURE step (OI-37 ruling 2026-09-11): the first densified
    sample whose centre is outside the island polygon by more than
    grace_mm. None = never failed. Responsiveness evidence is scored
    only BEFORE this step; post-failure behavior can never evidence
    responsiveness."""
    if not polygon or not path:
        return None
    from goal_strategy.detector.simulation.simulate_path import (
        _point_in_convex_polygon,
    )
    pedges = list(zip(polygon, polygon[1:] + polygon[:1]))
    for sx, sy, sstep in _dense_samples(path, origin):
        if not _point_in_convex_polygon(sx, sy, polygon):
            over = min(_point_segment_dist(sx, sy, a[0], a[1], b[0], b[1])
                       for a, b in pedges)
            if over > grace_mm:
                return int(sstep)
    return None


def _cumulative(path):
    out, total = [0.0], 0.0
    for p, q in zip(path, path[1:]):
        total += math.hypot(q.x - p.x, q.y - p.y)
        out.append(total)
    return out


def _idx_at_step(path, step):
    for i, p in enumerate(path):
        if p.step >= step:
            return i
    return None


def scenario_evidence(program, result, artifact, card) -> ScenarioEvidence:
    ident = dict(scenario_id=result.scenario_id, family=result.family,
                 construct=result.construct)
    if result.checks and all(c.abstained for c in result.checks):
        return ScenarioEvidence(**ident, abstained=True,
                                abstain_reason=result.checks[0].abstain_reason)
    rules = dict(card.get("episode_rules") or {})
    # Same encounter definition as the check rule (2026-09-03, closing a
    # gap from the 2026-09-01 eye-reach ruling): an ENCOUNTER = the
    # down-eye entered the ring, so the band reaches band_mm + the eye's
    # forward offset. Without it, boundary-RESPECTING programs (reverse
    # at red, centre ~120mm out) under-counted band entries.
    band = float(rules.get("band_mm") or 0.0) + \
        float(rules.get("eye_reach_mm") or 0.0)
    retreat = float(rules.get("retreat_mm") or 0.0)
    diverge = float(rules.get("divergence_mm") or 100.0)
    turn_deg = float(rules.get("turn_change_deg") or 15.0)

    sim, base, ctx = artifact.sim, artifact.baseline, artifact.context
    path = list(sim.path or [])
    if not path:
        return ScenarioEvidence(**ident)
    travel = _cumulative(path)
    edges = _edges(sim, ctx)

    # OI-37 failure-scoped window (reviewer-ruled 2026-09-11): every
    # responsiveness scan below runs only over pre-failure behavior.
    origin = (sim.origin_x, sim.origin_y)
    grace = float(rules.get("exit_grace_mm") or 0.0)
    exit_step = _scenario_exit_step(path, ctx.field_hex_vertices,
                                    grace, origin)
    wend = len(path)                # first path index PAST the window
    if exit_step is not None:
        wend = next((i for i, p in enumerate(path)
                     if int(p.step) > exit_step), len(path))
        wend = max(wend, 1)

    def _in_window(step) -> bool:
        return exit_step is None or int(step) <= exit_step

    # onset: first fired world event, else first piece materialization
    if sim.world_event_log:
        onset = int(sim.world_event_log[0][0])
    elif sim.piece_position_trace:
        onset = int(min(t[0] for t in sim.piece_position_trace))
    else:
        onset = 0
    oi = _idx_at_step(path, onset) or 0

    # response latency vs baseline (index-aligned, v1; pre-failure only)
    bpath = list(base.path or [])
    resp = None
    for i in range(oi, min(wend, len(bpath))):
        if math.hypot(path[i].x - bpath[i].x,
                      path[i].y - bpath[i].y) > diverge:
            resp = travel[i] - travel[oi]
            break

    # engagement latency: first contact at/after onset (pre-failure)
    eng = None
    contact_steps = sorted(s for s in (sim.object_contacts or {}).values()
                           if s >= onset and _in_window(s))
    if contact_steps:
        ci = _idx_at_step(path, contact_steps[0])
        if ci is not None:
            eng = max(0.0, travel[ci] - travel[oi])

    # post-clear action latency (first pre-failure clear)
    post_clear = None
    clears = sorted(s for s in (sim.pieces_cleared or {}).values()
                    if _in_window(s))
    if clears:
        ki = _idx_at_step(path, clears[0])
        if ki is not None:
            for i in range(max(ki, 1), wend):
                dh = abs((path[i].heading - path[i - 1].heading + 180) % 360 - 180)
                vx1 = path[i].x - path[i - 1].x
                vy1 = path[i].y - path[i - 1].y
                rev = False
                if i + 1 < len(path):
                    vx2 = path[i + 1].x - path[i].x
                    vy2 = path[i + 1].y - path[i].y
                    rev = (vx1 * vx2 + vy1 * vy2) < 0
                if dh > turn_deg or rev:
                    post_clear = max(0.0, travel[i] - travel[ki])
                    break

    # band entries separated by retreats + corrective response.
    # OI-36/OI-37 rebuild (2026-09-11): SEGMENT-DENSIFIED (a band
    # crossed mid-drive_for now counts — chunk drivers become
    # opportunity-verified), SIGNED (a retreat counts only while ON
    # the island: an outbound crossing is the failure, never the
    # response), and FAILURE-SCOPED (the scan ends at exit_step).
    entries, corrective = 0, None
    if edges and band > 0:
        from goal_strategy.detector.simulation.simulate_path import (
            _point_in_convex_polygon,
        )
        poly = ctx.field_hex_vertices
        in_band, retreated = False, True
        for sx, sy, sstep in _dense_samples(path, origin):
            if sstep < onset or not _in_window(sstep):
                if not _in_window(sstep):
                    break
                continue
            d = _d_edge(sx, sy, edges)
            inside = (_point_in_convex_polygon(sx, sy, poly)
                      if poly else True)
            if not in_band and d <= band and retreated:
                entries += 1
                in_band, retreated = True, False
            elif in_band and d > band:
                in_band = False
            if not in_band and entries and d >= retreat and inside:
                retreated = True
                if corrective is None:
                    corrective = True
        if entries and corrective is None:
            corrective = False

    # behavioural seams: ordered state-qualified events; transitions =
    # kind CHANGES (repeats of the same kind are not transitions).
    # Six kinds since the separability build (2026-09-05): the four
    # originals plus ACQUIRE (first true movable-target sensing — the
    # sim's first_target_detect field) and LOSS (a piece vanishing while
    # it was the most recent contact, or a loses-hat firing).
    # (OI-37: all seam sources are FAILURE-SCOPED — post-exit events
    # are not creditable behavior.)
    seams = []
    for pid, s in sorted((getattr(sim, "first_target_detect", None) or {}).items(),
                         key=lambda kv: kv[1]):
        if s >= onset and _in_window(s):
            seams.append((int(s), "acquire"))
    for pid, s in sorted((sim.object_contacts or {}).items(), key=lambda kv: kv[1]):
        if s >= onset and _in_window(s):
            seams.append((int(s), "engage"))
    last_contact = max((sim.object_contacts or {}).items(),
                       key=lambda kv: kv[1], default=(None, None))
    for pid, s in sorted((sim.pieces_cleared or {}).items(), key=lambda kv: kv[1]):
        if not _in_window(s):
            continue
        seams.append((int(s), "clear"))
        if pid in (sim.object_contacts or {}):
            seams.append((int(s), "loss"))       # engaged target vanished
    # (loses-variant hats also mark loss, but hat KIND is not
    # distinguishable from the sim result alone — the cleared-while-
    # contacted rule above covers the population case; revisit with the
    # program if the 46-run loses cohort ever needs finer seams.)
    for rec in (sim.world_event_log or []):
        # recovery markers: fired events with no placed edge (T6's
        # recovery_1 rows: (step, id, None, None))
        if len(rec) >= 3 and rec[2] is None and "recovery" in str(rec[1]) \
                and _in_window(rec[0]):
            seams.append((int(rec[0]), "recovery"))
    if edges and band > 0:
        # OI-36/OI-37: densified, signed, failure-scoped (mirrors the
        # entries scan — a mid-drive crossing produces the boundary
        # seam; a retreat seam requires being ON the island).
        from goal_strategy.detector.simulation.simulate_path import (
            _point_in_convex_polygon,
        )
        poly = ctx.field_hex_vertices
        in_band = False
        for sx, sy, sstep in _dense_samples(path, origin):
            if sstep < onset:
                continue
            if not _in_window(sstep):
                break
            d = _d_edge(sx, sy, edges)
            inside = (_point_in_convex_polygon(sx, sy, poly)
                      if poly else True)
            if not in_band and d <= band:
                seams.append((int(sstep), "boundary"))
                in_band = True
            elif in_band and d >= retreat and inside:
                seams.append((int(sstep), "retreat"))
                in_band = False
    seams.sort()
    kinds = [k for _, k in seams]
    transitions = sum(1 for a, b in zip(kinds, kinds[1:]) if a != b)

    # ---- task-semantic variables (2026-09-05) ----
    TASK_KINDS = {"acquire", "engage", "clear", "loss", "recovery"}
    task_transitions = sum(
        1 for (sa, a), (sb, b) in zip(seams, seams[1:])
        if a != b and b in TASK_KINDS)
    # resolution -> resumed pursuit: engage/acquire after a
    # boundary...retreat pair
    task_returns = 0
    reengaged = False
    pending_resolution = False
    seen_boundary = False
    for _s, k in seams:
        if k == "boundary":
            seen_boundary = True
            pending_resolution = False
        elif k == "retreat" and seen_boundary:
            pending_resolution = True
        elif k in ("engage", "acquire") and pending_resolution:
            task_returns += 1
            reengaged = True
            pending_resolution = False
    # completion cue: post-clear behaviour change within the card bar
    bar = float(rules.get("post_clear_bar_mm") or 0.0)
    completion = None
    if post_clear is not None and bar > 0:
        completion = post_clear <= bar
    # correction -> reassessment -> further correction / task seam
    cycles = 0
    state = 0   # 0 idle, 1 corrected (awaiting reassessment evidence)
    for _s, k in seams:
        if k == "retreat":
            if state == 1:
                cycles += 1          # correction followed correction
            state = 1
        elif state == 1 and k in ("acquire", "engage", "clear", "boundary"):
            # a NEW state read/interaction after the correction =
            # reassessment; task seams close the cycle productively
            cycles += 1
            state = 0

    return ScenarioEvidence(
        **ident,
        onset_step=onset,
        scenario_exit_step=exit_step,
        response_latency_mm=resp,
        engagement_latency_mm=eng,
        post_clear_action_latency_mm=post_clear,
        boundary_band_entries=entries,
        corrective_response_present=corrective,
        behavioral_seams=tuple(seams),
        behavioral_transition_count=transitions,
        task_state_triggered_transition_count=task_transitions,
        task_phase_return_count=task_returns,
        completion_triggered_transition=completion,
        reengagement_after_resolution=reengaged,
        correction_reassessment_cycles=cycles,
        code=code_evidence(program, sim),
    )


def battery_evidence(workspace_xml: str, program_id: str,
                     playground: str = "castle_crashers",
                     configs_dir: str | None = None) -> list[ScenarioEvidence]:
    """Convenience wrapper: run the battery once with artifacts and
    extract evidence for every scenario."""
    from goal_strategy.detector.parsing.parse_blocks import parse_workspace
    from .testcases import load_scenarios, run_battery
    report = run_battery(workspace_xml, program_id, playground=playground,
                         configs_dir=configs_dir, collect_sims=True)
    if not report.eligible:
        return []
    cards = {c["scenario_id"]: c
             for c in load_scenarios(playground, configs_dir)}
    program = parse_workspace(workspace_xml, program_id)
    arts = {(a.scenario_id, a.construct): a for a in report.artifacts}
    out = []
    for res in report.scenarios:
        art = arts.get((res.scenario_id, res.construct))
        if art is None:
            out.append(ScenarioEvidence(
                scenario_id=res.scenario_id, family=res.family,
                construct=res.construct, abstained=True,
                abstain_reason=(res.checks[0].abstain_reason
                                if res.checks and res.checks[0].abstained
                                else None)))
            continue
        out.append(scenario_evidence(program, res, art,
                                     cards.get(res.scenario_id, {})))
    return out


@dataclass(frozen=True)
class FamilyEvidence:
    """Cross-variant aggregation (B-2 layer 4): the two family-level
    indicators. `outcome_profile` keeps RAW per-variant check outcomes
    (status, or the measured value) — level reading belongs to the
    combination mechanism, never here."""
    family: str
    variants: tuple
    abstained_variants: tuple
    # check name -> {scenario_id: status-or-value}
    outcome_profile: dict = field(default_factory=dict)
    # structure exercised in EVERY non-abstained variant (loop/branch ids)
    shared_structure: tuple = ()
    # structure exercised in at least one variant
    structure_union: tuple = ()


def family_evidence(report, evidences) -> list:
    """Aggregate a battery report's scenarios by family. `evidences` is
    the scenario_evidence list (for abstention status); artifacts supply
    the exercised-structure sets."""
    by_fam: dict[str, list] = {}
    for res in report.scenarios:
        by_fam.setdefault(res.family, []).append(res)
    ev_by_id = {e.scenario_id: e for e in evidences}
    arts = {(a.scenario_id, a.construct): a for a in report.artifacts}
    out = []
    for fam, results in sorted(by_fam.items()):
        if len(results) < 2:
            continue          # a family is cross-variant by definition
        abstained = tuple(r.scenario_id for r in results
                          if ev_by_id.get(r.scenario_id) is not None
                          and ev_by_id[r.scenario_id].abstained)
        live = [r for r in results if r.scenario_id not in abstained]
        profile: dict = {}
        for r in results:
            for c in r.checks:
                cell = ("abstained:" + (c.abstain_reason or "")) if c.abstained \
                    else (c.value if c.value is not None else c.status)
                profile.setdefault(c.name, {})[r.scenario_id] = cell
        struct_sets = []
        for r in live:
            art = arts.get((r.scenario_id, r.construct))
            if art is None:
                continue
            sim = art.sim
            struct_sets.append(set((sim.loops_exercised or {}).keys())
                               | set((sim.branches_exercised or {}).keys()))
        shared = set.intersection(*struct_sets) if struct_sets else set()
        union = set.union(*struct_sets) if struct_sets else set()
        out.append(FamilyEvidence(
            family=fam,
            variants=tuple(r.scenario_id for r in results),
            abstained_variants=abstained,
            outcome_profile=profile,
            shared_structure=tuple(sorted(shared)),
            structure_union=tuple(sorted(union))))
    return out


def load_evidence_registry(playground: str = "castle_crashers",
                           configs_dir: str | None = None) -> dict:
    from pathlib import Path

    import yaml

    from .config import _DEFAULT_CONFIGS_DIR
    path = (Path(configs_dir or _DEFAULT_CONFIGS_DIR) / "testcases"
            / playground / "_evidence.yaml")
    card = yaml.safe_load(path.read_text()) if path.exists() else None
    return card if isinstance(card, dict) else {}


def dimension_u_map(evidences, registry: dict) -> dict:
    """Per-dimension U surfacing (reviewer-ruled 2026-08-31): a scenario
    that abstained is U for every dimension its variables feed. Returns
    {dimension: {"abstained": [(scenario, reason)...],
                 "informative": [scenario...]}} — the joint model reads
    `informative` as the scenarios contributing variables and
    `abstained` as the map's U cells that actually occurred."""
    fam_dims: dict[str, dict] = {}
    for var in (registry.get("variables") or {}).values():
        # registry v2 (2026-09-05): primary/supporting/role replace the
        # flat `informs`; v1 registries still read (informs -> supporting)
        prim = set(var.get("primary") or [])
        supp = set(var.get("supporting") or var.get("informs") or [])
        role = var.get("role") or "indicator"
        for fam in var.get("families") or []:
            slot = fam_dims.setdefault(fam, {"primary": set(),
                                             "supporting": set(),
                                             "validation": set()})
            if role == "validation":
                slot["validation"] |= prim | supp
            else:
                slot["primary"] |= prim
                slot["supporting"] |= supp
    out: dict = {d: {"abstained": [], "informative": [],
                     "informative_primary": [], "informative_supporting": [],
                     "informative_validation": []}
                 for d in registry.get("dimensions") or []}
    for e in evidences:
        slot = fam_dims.get(e.family)
        if not slot:
            continue
        touched = slot["primary"] | slot["supporting"] | slot["validation"]
        for dim in touched:
            if dim not in out:
                continue
            if e.abstained:
                out[dim]["abstained"].append((e.scenario_id, e.abstain_reason))
            else:
                out[dim]["informative"].append(e.scenario_id)
                if dim in slot["primary"]:
                    out[dim]["informative_primary"].append(e.scenario_id)
                elif dim in slot["supporting"]:
                    out[dim]["informative_supporting"].append(e.scenario_id)
                else:
                    out[dim]["informative_validation"].append(e.scenario_id)
    return out
