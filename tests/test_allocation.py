import json

import pytest

import participant_setup
from session_io import sha256_file
from participant_setup import PlanGenerationError, next_participant_id, planned_block_order
from timeline_key import PlacementFailure


def test_empty_participant_folder_is_occupied(tmp_path):
    (tmp_path / 'participant_01').mkdir()
    assert next_participant_id(tmp_path) == 'participant_02'


def test_incomplete_plan_folder_is_occupied(tmp_path):
    folder = tmp_path / 'participant_01'
    folder.mkdir()
    (folder / 'seed.txt').write_text('1')
    assert next_participant_id(tmp_path) == 'participant_02'


def test_block_order_counts_completed_sessions(tmp_path):
    participant = tmp_path / 'participant_09' / 'session_01'
    participant.mkdir(parents=True)
    (participant / 'session_metadata.json').write_text(json.dumps({'completion_status': 'completed'}))
    order, count = planned_block_order([tmp_path])
    assert count == 1
    assert order == ['inanimate', 'animate']


def test_build_plan_follows_block_order():
    assignment, slotting_rows, timeline, _, _ = participant_setup.build_plan(7, ['inanimate', 'animate'])
    assert list(assignment) == ['inanimate', 'animate']
    assert list(dict.fromkeys(row['block'] for row in timeline)) == ['inanimate', 'animate']
    assert slotting_rows[0]['block'] == 'inanimate'


def test_five_failed_seeds_leave_no_folder_and_do_not_consume_id(tmp_path, monkeypatch):
    seeds = iter(range(100, 105))
    monkeypatch.setattr(participant_setup.secrets, 'randbits', lambda _: next(seeds))

    def fail(*args, **kwargs):
        raise PlacementFailure('simulated failure')

    monkeypatch.setattr(participant_setup, 'build_timeline', fail)
    with pytest.raises(PlanGenerationError, match='failed after 5 attempts') as error:
        participant_setup.create_participant_plan(tmp_path, 'participant_01')
    assert all(str(seed) in str(error.value) for seed in range(100, 105))
    assert not (tmp_path / 'participant_01').exists()
    assert not (tmp_path / '.participant_01.tmp').exists()
    assert next_participant_id(tmp_path) == 'participant_01'


def test_failure_retries_with_new_seed_and_records_failed_seed(tmp_path, monkeypatch):
    seeds = iter((100, 100, 200))
    monkeypatch.setattr(participant_setup.secrets, 'randbits', lambda _: next(seeds))
    real_build = participant_setup.build_plan
    attempts = []

    def fail_then_succeed(seed, *args, **kwargs):
        attempts.append(seed)
        assert not any((tmp_path / '.participant_01.tmp').iterdir())
        if len(attempts) == 1:
            raise PlacementFailure('simulated first-attempt failure')
        return real_build(seed, *args, **kwargs)

    monkeypatch.setattr(participant_setup, 'build_plan', fail_then_succeed)
    timeline_path, metadata = participant_setup.create_participant_plan(tmp_path, 'participant_01')
    participant_dir = timeline_path.parent
    assert attempts == [100, 200]
    assert metadata['plan_attempts'] == 2
    assert metadata['failed_plan_seeds'] == [100]
    assert int((participant_dir / 'seed.txt').read_text()) == 200
    assert {path.name for path in participant_dir.iterdir()} == {
        'seed.txt', 'slotting_key.csv', 'stimulus_assignment.csv',
        'timeline_key.csv', 'participant_metadata.json',
    }
    stored = json.loads((participant_dir / 'participant_metadata.json').read_text())
    assert stored['plan_attempts'] == 2
    assert stored['failed_plan_seeds'] == [100]
    assert stored['timeline_sha256'] == sha256_file(timeline_path)
