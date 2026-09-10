"""Small public fixtures for CLI and browser qualification; no research records."""
import json
from pathlib import Path

from .test_hat_execution import drive_for, workspace
from .test_scheduler import started
from .test_testcases import RESPONSIVE_PUSHER


def create_synthetic_data(root):
    import pandas as pd
    root = Path(root)
    (root/'ccp_run_dataset').mkdir(parents=True, exist_ok=True)
    runs, final = [], []
    for student in range(2):
        session = f'SYNTHETIC-{student}-SESSION'
        for index in range(6):
            xml = workspace(started('start', drive_for(100 * (index + 1))))
            if index == 4:
                xml = RESPONSIVE_PUSHER
            if index == 5:
                xml = '<broken'
            params = {'weight_cleared': index * 350, 'gps_x_position': 1014 - 100 * (index + 1),
                      'gps_y_position': 50, 'project_stopped_by_user': False}
            runs.append(dict(run_id=f'{session}-R{index}', run_seq=index + 1,
                workspace_xml=xml, playground_params=json.dumps({'playground': 'CasteCrasherPlus', 'parameters': params}),
                student_study_id=f'SYNTHETIC-{student}', derived_session_id=session,
                derived_session_num=1, ccp_session_seq=1, school='SYNTHETIC', class_code='DEMO',
                date='2026-09-10', run_start_ts=1690000000 + index * 60, run_end_ts=1690000002 + index * 60,
                end_status='completed', run_duration_ms=2000, has_project_end=True,
                n_playground_data=1, playground='CastleCrasherPlus', starts_with_existing_code=False))
            final.append(dict(student_study_id=f'SYNTHETIC-{student}', derived_session_id=f'{session}-{index}',
                              workspace_xml=xml, playground_params=json.dumps(params)))
    pd.DataFrame(runs).to_parquet(root/'ccp_run_dataset/ccp_runs.parquet', index=False)
    pd.DataFrame(final).to_parquet(root/'final_code_states.parquet', index=False)
    return root
