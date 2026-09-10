"""Goal test fixtures and explicit private-corpus requirements."""
from goal_strategy.paths import data_path
import pytest


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


# These cases read private files directly instead of using the shared fixtures.
_DIRECT_CORPUS = {
    "test_real_registry_covers_every_observed_type", "test_dev_corpus_carries_no_unmodeled_flag",
    "test_procedures_call_run_is_no_longer_flagged", "test_cli_writes_flat_csv",
    "test_outline_rows_render_a_real_ccp_run", "test_brightness_is_foreign_not_unmodeled",
    "test_cohort_table_shape",
}


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "goal_strategy/tests/" not in item.nodeid:
            continue
        if (_DIRECT_CORPUS & {item.originalname} or
            {"corpus", "corpus_map", "runs", "dev_corpus", "frozen", "replayed"} & set(item.fixturenames)
            or (item.path.name == "test_rung_sweep.py" and "rows" in item.fixturenames)):
            item.add_marker(pytest.mark.corpus)
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
