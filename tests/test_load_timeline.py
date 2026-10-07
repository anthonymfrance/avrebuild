import contextlib
import io
import json
from pathlib import Path

import pytest

import participant_setup
from session_io import load_timeline

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def plan(tmp_path, monkeypatch):
    monkeypatch.delenv('AV_STUDY_SERVER_ROOT', raising=False)
    monkeypatch.delenv('AV_STUDY_SERVER_DATA_PATH', raising=False)
    monkeypatch.setattr(participant_setup.secrets, 'randbits', lambda _: 4242)
    with contextlib.redirect_stdout(io.StringIO()):
        timeline_path, _ = participant_setup.create_participant_plan(tmp_path, 'participant_01')
    metadata = json.loads((timeline_path.parent / 'participant_metadata.json').read_text())
    return timeline_path, metadata


def test_loads_generated_plan(plan):
    timeline_path, metadata = plan
    rows, assets, block_order, trials_by_block = load_timeline(timeline_path, metadata, ROOT)
    assert block_order == metadata['block_order']
    assert all(isinstance(row['trial_onset'], float) for row in rows)
    assert assets['sounds'] and all(path.is_file() for path in assets['images'].values())
    assert trials_by_block[block_order[0]] == set(range(1, max(trials_by_block[block_order[0]]) + 1))


def test_rejects_modified_timeline(plan):
    timeline_path, metadata = plan
    timeline_path.write_text(timeline_path.read_text() + '\n')
    with pytest.raises(ValueError, match='sha256'):
        load_timeline(timeline_path, metadata, ROOT)


def test_rejects_config_that_differs_from_plan_snapshot(plan):
    timeline_path, metadata = plan
    metadata['config']['RESPONSE_WINDOW'] = 9.0
    with pytest.raises(ValueError, match='RESPONSE_WINDOW'):
        load_timeline(timeline_path, metadata, ROOT)
