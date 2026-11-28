"""profile() must stay viable in an online request path: median < 50ms (spec §9)."""
import statistics
import time

import pytest

from goal_strategy import profile
from goal_strategy.tests.test_hat_execution import drive_for, turn_for, workspace
from goal_strategy.tests.test_scheduler import started


def test_median_profile_latency_on_synthetic_programs():
    """The same 50ms gate on public programs, so it runs without the private data."""
    loop = ('<block type="pg_control_repeat" id="r"><value name="TIMES"><shadow '
            'type="math_number"><field name="NUM">{n}</field></shadow></value>'
            '<statement name="SUBSTACK">{body}</statement></block>')
    programs = [workspace(started("A", drive_for(100 * k, nxt=f"<next>{turn_for(15 * k)}</next>")))
                for k in range(1, 11)]
    programs += [workspace(started("A", loop.format(n=k, body=drive_for(300))))
                 for k in range(1, 11)]
    profile("", "warmup")
    times = []
    for i, xml in enumerate(programs):
        start = time.perf_counter()
        profile(xml, f"synthetic/{i}", {"weight_cleared": 700})
        times.append(time.perf_counter() - start)
    assert statistics.median(times) * 1000 < 50


@pytest.mark.corpus
def test_median_profile_latency_under_50ms(corpus):
    profile("", "warmup")  # load + cache configs outside the timed region
    times = []
    for prog in corpus:
        start = time.perf_counter()
        profile(prog.workspace_xml or "", prog.program_id, prog.playground_params)
        times.append(time.perf_counter() - start)
    median_ms = statistics.median(times) * 1000
    print(f"\nprofile() median over {len(times)} programs: {median_ms:.2f}ms")
    assert median_ms < 50, f"median {median_ms:.2f}ms exceeds the 50ms target"


def test_core_package_does_not_import_pandas():
    import subprocess
    import sys
    code = "import sys; sys.modules['pandas'] = None; import goal_strategy; goal_strategy.profile('', 'x')"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
