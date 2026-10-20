import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys

import pytest

import config
import participant_setup
from session_io import sha256_file
from participant_setup import (
    PlanGenerationError,
    claim_next_participant_id,
    next_participant_id,
    planned_block_order,
    verify_participant_claim,
)
from timeline_key import PlacementFailure


@pytest.mark.parametrize('path_kind', ['relative', 'absolute', 'default'])
def test_server_only_id_and_completion_use_backup_root(tmp_path, monkeypatch, path_kind):
    import session_io

    local = tmp_path / 'local' / 'data'
    server = tmp_path / 'share'
    monkeypatch.setenv('AV_STUDY_SERVER_ROOT', str(server))
    if path_kind == 'default':
        monkeypatch.delenv('AV_STUDY_SERVER_DATA_PATH', raising=False)
        destination = server / 'data'
    else:
        destination = server / 'Experiments' / 'study' / 'data'
        monkeypatch.setenv('AV_STUDY_SERVER_DATA_PATH',
                           'Experiments/study/data' if path_kind == 'relative' else str(destination))
    session = destination / 'participant_01' / 'session_01'
    session.mkdir(parents=True)
    (session / 'session_metadata.json').write_text(json.dumps({'completion_status': 'completed'}))
    assert next_participant_id(local) == 'participant_02'
    assert planned_block_order(participant_setup.data_directories(local)) == (['inanimate', 'animate'], 1)
    assert session_io.server_data_directory() == destination

    participant = local / 'participant_02'
    participant.mkdir(parents=True)
    (participant / 'participant_metadata.json').write_text(json.dumps({'seed': 123}))
    result = session_io.copy_participant_data_to_server(local.parent, 'participant_02')
    assert result['status'] == 'copied'
    assert result['destination'] == str(destination / 'participant_02')
    assert (destination / 'participant_02' / 'participant_metadata.json').read_bytes() == (
        participant / 'participant_metadata.json').read_bytes()


def test_absolute_server_data_path_without_mount_root(tmp_path, monkeypatch):
    monkeypatch.delenv('AV_STUDY_SERVER_ROOT', raising=False)
    monkeypatch.setenv('AV_STUDY_SERVER_DATA_PATH', str(tmp_path / 'server'))
    (tmp_path / 'server' / 'participant_01').mkdir(parents=True)
    assert next_participant_id(tmp_path / 'local') == 'participant_02'


def test_relative_server_path_without_mount_root_is_not_a_local_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('AV_STUDY_SERVER_ROOT', raising=False)
    monkeypatch.setenv('AV_STUDY_SERVER_DATA_PATH', 'Experiments/study/data')
    (tmp_path / 'Experiments/study/data/participant_01').mkdir(parents=True)
    assert participant_setup.data_directories(tmp_path / 'local') == [tmp_path / 'local']
    assert next_participant_id(tmp_path / 'local') == 'participant_01'


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


@pytest.mark.parametrize('size', [50, 100, 200])
def test_supported_image_sizes_generate_valid_plans(size):
    # Set config before imports, just as editing config before launch does.
    result = subprocess.run(
        [sys.executable, '-c', f'''
import config
config.IMAGE_SIZE = ({size}, {size})
from participant_setup import build_plan
from timeline_key import _position_bounds
_, _, timeline, _, _ = build_plan(7, ['animate', 'inanimate'])
x_min, x_max, y_min, y_max = _position_bounds(config.WINDOW_SIZE, config.IMAGE_SIZE)
visuals = [row for row in timeline if row['event_type'] == 'visual']
assert visuals
for row in visuals:
    assert x_min <= abs(row['x']) <= x_max
    assert y_min <= abs(row['y']) <= y_max
'''],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_build_plan_follows_block_order():
    assignment, slotting_rows, timeline, _, _ = participant_setup.build_plan(7, ['inanimate', 'animate'])
    assert list(assignment) == ['inanimate', 'animate']
    assert list(dict.fromkeys(row['block'] for row in timeline)) == ['inanimate', 'animate']
    assert slotting_rows[0]['block'] == 'inanimate'


def test_target_corner_stays_empty_through_late_window():
    from config import TARGET_CORNER_HOLD, TARGET_ROLES
    timeline = participant_setup.build_plan(7, ['animate', 'inanimate'])[2]
    visuals = [row for row in timeline if row['event_type'] == 'visual']
    for target in (row for row in visuals if row['role'] in TARGET_ROLES):
        for other in visuals:
            if other is not target and other['corner'] == target['corner'] and other['block'] == target['block']:
                assert not 0 <= other['global_onset'] - target['global_onset'] < TARGET_CORNER_HOLD


def test_pt_sound_never_starts_before_previous_pt_response_window_ends():
    from config import RESPONSE_WINDOW, WINDOW_SIZE
    from timeline_key import validate_timeline
    # Include seed 11356349656583725014, where a later PT's sound used to start
    # during the earlier PT's visual/response window.
    for seed in (7, 11, 11356349656583725014):
        assignment, slotting_rows, timeline, required, _ = participant_setup.build_plan(
            seed, ['animate', 'inanimate'],
        )
        sounds_by_source = {
            row['source_event_id']: row for row in timeline if row['event_type'] == 'sound'
        }
        for block in ('animate', 'inanimate'):
            pts = sorted(
                (row for row in timeline
                 if row['block'] == block and row['event_type'] == 'visual' and row['role'] == 'PT'),
                key=lambda row: row['global_onset'],
            )
            for earlier, later in zip(pts, pts[1:]):
                later_sound = sounds_by_source[later['event_id']]
                assert later_sound['global_onset'] >= earlier['global_onset'] + RESPONSE_WINDOW - 1e-9

    # Also verify validate_timeline rejects a timeline where a PT's sound starts
    # before the previous PT's response window ends. The violating timeline is
    # built here rather than read from a saved participant folder, which changes
    # with every session and would make this check depend on leftover data.
    from config import FADE_IN_DUR
    assignment, slotting_rows, timeline, required, _ = participant_setup.build_plan(
        7, ['animate', 'inanimate'],
    )
    sounds_by_source = {
        row['source_event_id']: row for row in timeline if row['event_type'] == 'sound'
    }
    pts_by_trial = {}
    for row in timeline:
        if row['event_type'] == 'visual' and row['role'] == 'PT':
            pts_by_trial.setdefault((row['block'], row['trial']), []).append(row)
    same_trial_pairs = [
        pair
        for pts in pts_by_trial.values()
        for pair in zip(sorted(pts, key=lambda r: r['global_onset']),
                        sorted(pts, key=lambda r: r['global_onset'])[1:])
    ]
    assert same_trial_pairs, 'seed 7 should place two PTs in at least one trial'
    for earlier, later in same_trial_pairs:
        sound = sounds_by_source[later['event_id']]
        trial_start = sound['global_onset'] - sound['trial_onset']
        moved = dict(sound)
        moved['global_onset'] = earlier['global_onset'] + RESPONSE_WINDOW - 0.001
        moved['trial_onset'] = moved['global_onset'] - trial_start
        moved['soa'] = (later['global_onset'] + FADE_IN_DUR) - moved['global_onset']
        mutated = [row for row in timeline if row['event_id'] != moved['event_id']] + [moved]
        mutated.sort(key=lambda row: row['global_onset'])
        with pytest.raises(ValueError, match='PT sound starts before previous PT response window ends'):
            validate_timeline(slotting_rows, required, mutated, assignment, WINDOW_SIZE)


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


def test_claims_reserve_ids_in_order_and_skip_active_claims(tmp_path, monkeypatch):
    monkeypatch.delenv('AV_STUDY_SERVER_ROOT', raising=False)
    monkeypatch.delenv('AV_STUDY_SERVER_DATA_PATH', raising=False)
    first = claim_next_participant_id(tmp_path)
    second = claim_next_participant_id(tmp_path)
    assert first['participant_id'] == 'participant_01'
    assert second['participant_id'] == 'participant_02'
    assert next_participant_id(tmp_path) == 'participant_03'
    claim_path = tmp_path / '.claims' / 'participant_01.lock'
    assert claim_path.is_file()
    payload = json.loads(claim_path.read_text())
    assert payload['participant_id'] == 'participant_01'
    assert isinstance(payload['pid'], int)
    assert payload['token'] == first['token']
    assert payload['host']
    assert payload['started_utc']


def test_claim_prefers_shared_server_root(tmp_path, monkeypatch):
    local = tmp_path / 'local' / 'data'
    server = tmp_path / 'server_data'
    server.mkdir()
    monkeypatch.setenv('AV_STUDY_SERVER_ROOT', str(tmp_path / 'share'))
    monkeypatch.setenv('AV_STUDY_SERVER_DATA_PATH', str(server))
    claim = claim_next_participant_id(local)
    assert claim['path'] == str(server / '.claims' / 'participant_01.lock')
    assert Path(claim['path']).is_file()
    assert not (local / '.claims').exists()


def test_expired_claim_is_reclaimed_without_skipping_numbers(tmp_path, monkeypatch):
    monkeypatch.delenv('AV_STUDY_SERVER_ROOT', raising=False)
    monkeypatch.delenv('AV_STUDY_SERVER_DATA_PATH', raising=False)
    claim_dir = tmp_path / '.claims'
    claim_dir.mkdir()
    stale = datetime.now(timezone.utc) - timedelta(
        hours=config.PARTICIPANT_CLAIM_TTL_HOURS + 1
    )
    (claim_dir / 'participant_01.lock').write_text(json.dumps({
        'participant_id': 'participant_01', 'pid': 1, 'host': 'old-machine',
        'started_utc': stale.isoformat(), 'token': 'old',
    }))
    assert next_participant_id(tmp_path) == 'participant_01'
    assert not (claim_dir / 'participant_01.lock').exists()


def test_claim_refuses_participant_folder_already_on_server(tmp_path, monkeypatch):
    local = tmp_path / 'local' / 'data'
    server = tmp_path / 'server_data'
    server.mkdir()
    monkeypatch.setenv('AV_STUDY_SERVER_ROOT', str(tmp_path / 'share'))
    monkeypatch.setenv('AV_STUDY_SERVER_DATA_PATH', str(server))
    claim = claim_next_participant_id(local)
    (server / claim['participant_id']).mkdir()
    with pytest.raises(FileExistsError, match='never overwritten'):
        participant_setup.create_participant_plan(
            local, claim['participant_id'], claim=claim
        )


def test_claim_token_and_existing_folder_are_enforced(tmp_path, monkeypatch):
    monkeypatch.delenv('AV_STUDY_SERVER_ROOT', raising=False)
    monkeypatch.delenv('AV_STUDY_SERVER_DATA_PATH', raising=False)
    claim = claim_next_participant_id(tmp_path)
    with pytest.raises(ValueError, match='token'):
        verify_participant_claim(claim['path'], claim['participant_id'], 'wrong-token')
    with pytest.raises(ValueError, match='token'):
        participant_setup.create_participant_plan(
            tmp_path, claim['participant_id'], claim={**claim, 'token': 'wrong-token'}
        )
    (tmp_path / claim['participant_id']).mkdir()
    with pytest.raises(FileExistsError, match='never overwritten'):
        participant_setup.create_participant_plan(tmp_path, claim['participant_id'], claim=claim)
    (tmp_path / claim['participant_id']).rmdir()
    timeline_path, _ = participant_setup.create_participant_plan(
        tmp_path, claim['participant_id'], claim=claim
    )
    assert timeline_path.is_file()
    assert participant_setup.release_participant_claim_if_unused(
        tmp_path, claim['path'], claim['token'], claim['participant_id']
    ) is False
    assert Path(claim['path']).is_file()


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
