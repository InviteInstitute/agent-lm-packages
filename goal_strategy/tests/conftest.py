"""Goal test fixtures and explicit private-corpus requirements."""
from goal_strategy.paths import data_path
import pytest

from goal_strategy.tests.test_timeline import toy  # noqa: F401 (shared fixture)


@pytest.fixture(scope="session")
def corpus():
    from goal_strategy.tests.helpers import load_final_code_states
    return load_final_code_states(str(data_path() / "final_code_states.parquet"))


@pytest.fixture(scope="session")
def profiles_truncated(corpus):
    from goal_strategy import profile
    return [profile(p.workspace_xml or "", p.program_id, p.playground_params)
            for p in corpus]


@pytest.fixture(scope="session")
def profiles_full(corpus):
    from goal_strategy.profile import _profile
    return [_profile(p.workspace_xml or "", p.program_id, p.playground_params,
                     truncate=False)
            for p in corpus]


def pytest_collection_modifyitems(config, items):
    if config.getoption("--require-goal-data"):
        paths = ["final_code_states.parquet", "frozen_paths.parquet",
                 "ccp_run_dataset/ccp_runs.parquet", "ccp_run_dataset/stage2_rungs.csv",
                 "ccp_run_dataset/stage2_fidelity.csv"]
        missing = [str(data_path(p)) for p in paths if not data_path(p).is_file()]
        if missing:
            raise pytest.UsageError("Missing required goal data: " + ", ".join(missing))


def pytest_runtest_setup(item):
    if item.get_closest_marker("corpus") and not item.config.getoption("--require-goal-data"):
        paths = ["final_code_states.parquet", "ccp_run_dataset/ccp_runs.parquet"]
        if "frozen" in item.fixturenames:
            paths.append("frozen_paths.parquet")
        missing = [str(data_path(p)) for p in paths if not data_path(p).is_file()]
        if missing:
            pytest.skip("Private goal data unavailable: " + ", ".join(missing))
