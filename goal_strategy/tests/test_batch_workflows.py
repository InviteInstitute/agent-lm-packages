"""Exercise the shipped CLI interfaces against public synthetic parquet data."""
import csv
import os
import signal
import subprocess
import sys

from goal_strategy.artifacts import validate_artifact
from goal_strategy.tests.synthetic_data import create_synthetic_data


def test_all_five_cli_workflows(tmp_path):
    root = create_synthetic_data(tmp_path/'data')
    env = dict(os.environ, GOAL_STRATEGY_DATA_DIR=str(root))
    outputs = {'cli': root/'profiles.csv', 'dryrun': root/'ccp_run_dataset/stage1_dryrun.csv',
               'rung_sweep': root/'ccp_run_dataset/stage2_rungs.csv',
               'fidelity_sweep': root/'ccp_run_dataset/stage2_fidelity.csv',
               'testcases': root/'battery.csv'}
    for module, path in outputs.items():
        proc = subprocess.run([sys.executable, '-m', f'goal_strategy.{module}', '--out', str(path)],
                              env=env, capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        rows = list(csv.DictReader(path.open()))
        assert rows, module
        if module != 'testcases':
            validate_artifact(rows)
    dry = list(csv.DictReader(outputs['dryrun'].open()))
    assert {r['classification'] for r in dry} <= {'profiled_clean', 'profiled_with_abstentions', 'parse_failed'}
    assert sum(r['classification'] == 'parse_failed' for r in dry) == 2
    fidelity = list(csv.DictReader(outputs['fidelity_sweep'].open()))
    assert len(fidelity) == 12


def test_dryrun_restores_signal_handler_on_success_and_error(tmp_path):
    from goal_strategy.dryrun import sweep
    previous = signal.getsignal(signal.SIGALRM)
    assert sweep([], str(tmp_path/'empty.csv'))['crashed'] == 0
    assert signal.getsignal(signal.SIGALRM) is previous
    import pytest
    with pytest.raises(Exception):
        sweep([], str(tmp_path/'bad.csv'), configs_dir=str(tmp_path/'missing'))
    assert signal.getsignal(signal.SIGALRM) is previous


def test_stale_artifacts_are_rejected():
    import pytest
    with pytest.raises(ValueError, match='Regenerate'):
        validate_artifact([{'run_id': 'old'}])
