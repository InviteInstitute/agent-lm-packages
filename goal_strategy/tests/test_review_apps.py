"""Public synthetic end-to-end checks for both optional review applications."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from goal_strategy.tests.synthetic_data import create_synthetic_data


@pytest.fixture
def review_data(tmp_path, monkeypatch):
    import streamlit as st
    st.cache_data.clear()
    st.cache_resource.clear()
    root = create_synthetic_data(tmp_path/'data')
    monkeypatch.setenv('GOAL_STRATEGY_DATA_DIR', str(root))
    yield root
    st.cache_data.clear()
    st.cache_resource.clear()


def app(name):
    return AppTest.from_file(str(Path(__file__).parents[1]/'viz'/f'{name}.py'), default_timeout=30).run()


def test_dev_review_pages_render_without_exceptions(review_data):
    ui = app('app')
    assert not ui.exception
    for page in ['Program summary', 'Cohort', 'Walkthrough']:
        ui.radio(key='view').set_value(page).run()
        assert not ui.exception, [e.message for e in ui.exception]


def test_longitudinal_run_and_rung_review(review_data):
    from goal_strategy.ccp_runs import load_ccp_runs
    from goal_strategy.dryrun import sweep as dry
    from goal_strategy.fidelity_sweep import sweep as fidelity
    from goal_strategy.rung_sweep import sweep as rung
    root = review_data/'ccp_run_dataset'
    dry(load_ccp_runs(), str(root/'stage1_dryrun.csv'))
    fidelity(str(root/'stage2_fidelity.csv'))
    rung(str(root/'stage2_rungs.csv'))
    ui = app('longitudinal')
    assert not ui.exception
    ui.toggle[0].set_value(True).run()
    assert not ui.exception
    ui.radio(key='view').set_value('rung review').run()
    assert not ui.exception, [e.message for e in ui.exception]


@pytest.mark.parametrize('name', ['app','longitudinal'])
def test_missing_data_displays_instructions(review_data, monkeypatch, name):
    monkeypatch.setenv('GOAL_STRATEGY_DATA_DIR', str(review_data/'absent'))
    ui = app(name)
    assert not ui.exception
    assert any('GOAL_STRATEGY_DATA_DIR' in element.value for element in ui.info)
