"""Canonical, strict JSON data for typed goal results."""
from dataclasses import fields, is_dataclass
import math

PIPELINE_VERSION = "0.2.0"
SCHEMA_VERSION = 1


def to_dict(value):
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_dict(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, dict):
        return {str(k): to_dict(v) for k, v in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted((to_dict(v) for v in value), key=repr)
    if isinstance(value, (list, tuple)):
        return [to_dict(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Non-finite evidence must be validated before serialization")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported result type: {type(value).__name__}")


def profile_to_dict(profile):
    result = to_dict(profile)
    for goal in result['goals']:
        for indicator in goal['intent'] + goal['attainment']:
            indicator['flags'] = sorted(set(indicator['flags']))
    return result
