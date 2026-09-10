"""Shared descriptive fidelity policy for profiles and offline review."""
import math

from .indicators import _polyline_min_distance


def assess(config, program, sim, profile, params):
    result = dict(verdict='not_applicable', trajectory_mm=None, edge_zone=False)
    if sim is None:
        return result
    params = params or {}
    if params.get('project_stopped_by_user'):
        result['verdict'] = 'early_stop'
        return result
    spec = (config.card.get('outcome_metrics') or {}).get('final_gps_position') or {}
    try:
        gx, gy = float(params[spec['x_field']]), float(params[spec['y_field']])
    except (KeyError, TypeError, ValueError, OverflowError):
        return result
    if not all(math.isfinite(v) for v in (gx, gy)):
        return result
    thresholds = config.card.get('fidelity_thresholds') or {}
    points = [(sim.origin_x, sim.origin_y)] + [(p.x, p.y) for p in sim.path]
    trajectory = _polyline_min_distance(points, gx, gy)
    if not math.isfinite(trajectory):
        return result
    result['trajectory_mm'] = trajectory
    poly = (config.card.get('field_boundary') or {}).get('polygon_mm') or []
    zone = float(thresholds.get('edge_divergence_zone_mm') or 0)
    # Preserve the offline sweep's 50 mm sampling policy for edge annotations.
    if zone and poly:
        for a, b in zip(points, points[1:]):
            count = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) // 50))
            if any(_polyline_min_distance(poly + [poly[0]],
                   a[0] + (b[0] - a[0]) * k / count,
                   a[1] + (b[1] - a[1]) * k / count) < zone for k in range(count + 1)):
                result['edge_zone'] = True
                break
    flags = set(sim.execution_flags)
    hats = {h.block_id: h.block_type for h in program.event_handler_stacks}
    detected = any(hats.get(bid, '').endswith(('optical_detect_object', 'when_bumper'))
                   for bid in sim.sensor_hats_fired)
    detection_present = any(t.endswith(('optical_detect_object', 'when_bumper')) for t in hats.values())
    sensorish = bool({'sensor_reading_stale', 'timer_hat_unfired', 'wait_until_unmet'} & flags)
    sensorish |= detection_present and not detected or detected and bool(sim.object_contacts)
    if profile.off_island_agreement and (profile.gps_final_error_mm is None or
        profile.gps_final_error_mm <= float(thresholds.get('on_island_xy_mm', 0))):
        verdict = 'agree'
    elif profile.boundary_exit_overridden:
        verdict = 'override'
    elif sim.loop_was_capped or {'execution_budget_exhausted', 'hat_restart_capped'} & flags:
        verdict = 'capped'
    elif {'nonfinite_parameter_stall', 'invalid_expression'} & flags:
        verdict = 'stalled'
    elif profile.off_island_agreement is False and trajectory <= float(thresholds.get('off_island_edge_slip_mm') or 0):
        verdict = 'edge_slip'
    elif sensorish:
        verdict = 'sensor_uncertainty'
    elif result['edge_zone']:
        verdict = 'edge_zone_possible'
    else:
        verdict = 'UNATTRIBUTED'
    result['verdict'] = verdict
    return result
