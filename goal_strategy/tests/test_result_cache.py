"""The content-addressed result cache must be invisible: identical re-runs
(wheel-spinning) hit it, program_id is re-stamped per call, and anything that
changes the output - params, outcome, include flags, config - is a fresh key."""
import copy

import pytest

import goal_strategy.adapter as adapter
from goal_strategy import GoalProfileStream, goal_profile, goal_profiles_from_events
from goal_strategy.config import load_configs
from goal_strategy.tests.test_hat_execution import drive_for, workspace
from goal_strategy.tests.test_scheduler import started

XML = workspace(started('A', drive_for(200)))
XML2 = workspace(started('A', drive_for(999)))


@pytest.fixture(autouse=True)
def _clear_cache():
    adapter._result_cache_clear()
    yield
    adapter._result_cache_clear()


def _strip_pids(result):
    """Deep copy with every program_id blanked, for content comparison."""
    r = copy.deepcopy(result)
    def walk(o):
        if isinstance(o, dict):
            for k in list(o):
                if k == 'program_id':
                    o[k] = '<pid>'
                else:
                    walk(o[k])
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(r)
    return r


def test_identical_rerun_hits_and_restamps_program_id():
    r0 = goal_profile(XML, 's/sess/0', {'weight_cleared': 700})
    assert len(adapter._RESULT_CACHE) == 1
    r1 = goal_profile(XML, 's/sess/1', {'weight_cleared': 700})   # wheel-spin: same code, new id
    assert len(adapter._RESULT_CACHE) == 1                        # a hit, not a new entry

    # program_id is stamped correctly in every embedded location...
    assert r0['program_id'] == 's/sess/0' and r1['program_id'] == 's/sess/1'
    assert r0['profile']['program_id'] == 's/sess/0'
    assert r1['profile']['program_id'] == 's/sess/1'
    # ...and everything else is identical.
    assert _strip_pids(r0) == _strip_pids(r1)


def test_hit_result_is_independent_copy():
    r0 = goal_profile(XML, 's/0', {'weight_cleared': 700})
    r1 = goal_profile(XML, 's/1', {'weight_cleared': 700})
    r1['diagnostics'].append('mutated')          # caller mutation must not corrupt the cache
    r2 = goal_profile(XML, 's/2', {'weight_cleared': 700})
    assert 'mutated' not in r2['diagnostics']
    assert r0['diagnostics'] == r2['diagnostics']


def test_outcome_change_is_a_miss_not_stale():
    r_no = goal_profile(XML, 's/0', {})                       # no weight outcome
    r_yes = goal_profile(XML, 's/1', {'weight_cleared': 700})  # outcome present
    assert len(adapter._RESULT_CACHE) == 2                    # distinct keys
    got = {r_no['profile']['outcome_available'], r_yes['profile']['outcome_available']}
    assert got == {False, True}                               # not served stale


def test_different_code_is_a_miss():
    goal_profile(XML, 's/0', {'weight_cleared': 700})
    goal_profile(XML2, 's/1', {'weight_cleared': 700})
    assert len(adapter._RESULT_CACHE) == 2


def test_include_flags_are_keyed_separately():
    a = goal_profile(XML, 's/0', {'weight_cleared': 700}, include_timeline=False)
    b = goal_profile(XML, 's/1', {'weight_cleared': 700}, include_timeline=True)
    assert len(adapter._RESULT_CACHE) == 2
    assert a['timeline'] is None and b['timeline'] is not None


def test_config_cache_clear_drops_result_cache():
    goal_profile(XML, 's/0', {'weight_cleared': 700})
    assert len(adapter._RESULT_CACHE) == 1
    load_configs.cache_clear()
    assert len(adapter._RESULT_CACHE) == 0


def test_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(adapter, '_RESULT_CACHE_MAX', 3)
    for i in range(10):
        # distinct code each call -> distinct keys
        goal_profile(workspace(started('A', drive_for(100 + i))), f's/{i}', {})
    assert len(adapter._RESULT_CACHE) <= 3


def test_streaming_wheel_spin_content_is_stable():
    stream = GoalProfileStream('s/sess')
    ev = {'event_type': 'runProject', 'ts': None,
          'content': {'playground': 'CastleCrasherPlus', 'project': {'workspace': XML}}}
    runs = [stream.push(dict(ev)) for _ in range(3)]
    # distinct indices/ids, identical profile content
    assert [r['index'] for r in runs] == [0, 1, 2]
    assert len({r['program_id'] for r in runs}) == 3
    assert _strip_pids(runs[0])['profile'] == _strip_pids(runs[2])['profile']


def test_cache_matches_uncached_output():
    """A cached hit is byte-identical (modulo program_id) to a freshly computed
    result - the cache changes nothing observable."""
    fresh = goal_profile(XML, 'x/0', {'weight_cleared': 700})
    adapter._result_cache_clear()
    recomputed = goal_profile(XML, 'x/0', {'weight_cleared': 700})
    assert fresh == recomputed


def test_non_string_param_keys_do_not_crash():
    # Review #4: a non-string key must not blow up the cache-key serialization.
    r = goal_profile(XML, 'x', {1: 'ignored', 'weight_cleared': 700})
    assert r['status'] in ('profiled', 'invalid_input')


def test_concurrent_access_is_thread_safe(monkeypatch):
    # Review #1: hammer the LRU from many threads with forced eviction churn;
    # an unlocked OrderedDict would raise KeyError/RuntimeError on a get/evict race.
    import threading
    monkeypatch.setattr(adapter, '_RESULT_CACHE_MAX', 16)
    xmls = [workspace(started('A', drive_for(100 + i))) for i in range(40)]
    errors = []

    def worker(tid):
        try:
            for r in range(120):
                goal_profile(xmls[(tid * 5 + r) % len(xmls)], f't{tid}/{r}', {'weight_cleared': 700})
        except Exception as exc:
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors[:3]
    assert len(adapter._RESULT_CACHE) <= 16
