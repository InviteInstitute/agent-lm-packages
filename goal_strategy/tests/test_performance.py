"""profile() must stay viable in an online request path: median < 50ms (spec §9)."""
import statistics
import time

from goal_strategy import profile


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
