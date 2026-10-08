import json

import session_io
from session_io import copy_participant_tree


def sync_with_remote_metadata(tmp_path, monkeypatch, remote_metadata):
    """Run sync_participant after a 'copied' result, with the given server session metadata."""
    session_dir = tmp_path / 'local' / 'participant_01' / 'session_01'
    remote_session = tmp_path / 'server' / 'participant_01' / 'session_01'
    session_dir.mkdir(parents=True)
    remote_session.mkdir(parents=True)
    (remote_session / 'session_metadata.json').write_text(json.dumps(remote_metadata))
    monkeypatch.setattr(session_io, 'copy_participant_data_to_server', lambda root, pid: {
        'status': 'copied', 'destination': str(remote_session.parent),
        'verified_files': [], 'failures': [],
    })
    metadata = {'started_utc': '2026-10-07T12:00:00+00:00', 'seed': 11}

    def save():
        (session_dir / 'session_metadata.json').write_text(json.dumps(metadata))

    session_io.sync_participant(tmp_path, 'participant_01', session_dir, metadata, save)
    return metadata, json.loads((remote_session / 'session_metadata.json').read_text())


def test_remote_metadata_of_another_session_is_preserved(tmp_path, monkeypatch):
    foreign = {'started_utc': '2026-10-01T09:00:00+00:00', 'seed': 11, 'note': 'other session'}
    metadata, remote = sync_with_remote_metadata(tmp_path, monkeypatch, foreign)
    assert remote == foreign
    assert metadata['server_sync']['status'] == 'collision'


def test_remote_metadata_with_other_seed_is_preserved(tmp_path, monkeypatch):
    foreign = {'started_utc': '2026-10-07T12:00:00+00:00', 'seed': 99}
    metadata, remote = sync_with_remote_metadata(tmp_path, monkeypatch, foreign)
    assert remote == foreign
    assert metadata['server_sync']['status'] == 'collision'


def test_remote_metadata_of_same_session_is_updated(tmp_path, monkeypatch):
    same = {'started_utc': '2026-10-07T12:00:00+00:00', 'seed': 11}
    metadata, remote = sync_with_remote_metadata(tmp_path, monkeypatch, same)
    assert metadata['server_sync']['status'] == 'copied'
    assert remote['server_sync']['status'] == 'copied'


def test_operator_warn_prints_and_appends(tmp_path, capsys):
    session_io.operator_warn(tmp_path, 'first warning')
    session_io.operator_warn(tmp_path, 'second warning')
    assert (tmp_path / 'operator_warnings.txt').read_text() == 'first warning\nsecond warning\n'
    assert capsys.readouterr().out == 'first warning\nsecond warning\n'


def test_local_only_sync_is_not_an_operator_warning(tmp_path, monkeypatch):
    monkeypatch.delenv('AV_STUDY_SERVER_ROOT', raising=False)
    monkeypatch.delenv('AV_STUDY_SERVER_DATA_PATH', raising=False)
    session_dir = tmp_path / 'data' / 'participant_01' / 'session_01'
    session_dir.mkdir(parents=True)
    metadata = {}
    session_io.sync_participant(tmp_path, 'participant_01', session_dir, metadata, lambda: None)
    assert metadata['server_sync']['status'] == 'local_only'
    assert not (tmp_path / 'data' / 'participant_01' / 'operator_warnings.txt').exists()


def test_collision_sync_is_an_operator_warning(tmp_path, monkeypatch):
    session_dir = tmp_path / 'data' / 'participant_01' / 'session_01'
    session_dir.mkdir(parents=True)
    monkeypatch.setattr(session_io, 'copy_participant_data_to_server', lambda root, pid: {
        'status': 'collision', 'destination': str(tmp_path / 'server'),
        'verified_files': [], 'failures': [],
    })
    metadata = {}
    session_io.sync_participant(tmp_path, 'participant_01', session_dir, metadata, lambda: None)
    warnings = (tmp_path / 'data' / 'participant_01' / 'operator_warnings.txt').read_text()
    assert 'collision' in warnings


def test_server_participant_collision_preserves_destination_and_local(tmp_path):
    local = tmp_path / 'local' / 'participant_01'
    server = tmp_path / 'server' / 'participant_01'
    local.mkdir(parents=True)
    server.mkdir(parents=True)
    (local / 'participant_metadata.json').write_text(json.dumps({'seed': 11}))
    (server / 'participant_metadata.json').write_text(json.dumps({'seed': 22}))
    (local / 'event_log.csv').write_text('local data')
    (server / 'event_log.csv').write_text('server data')

    result = copy_participant_tree(local, server)

    assert result['status'] == 'collision'
    assert (server / 'event_log.csv').read_text() == 'server data'
    assert (local / 'event_log.csv').read_text() == 'local data'
    assert 'event_log.csv' not in result['verified_files']


def test_same_participant_sync_copies_only_missing_or_matching_files(tmp_path):
    local = tmp_path / 'local' / 'participant_01'
    server = tmp_path / 'server' / 'participant_01'
    local.mkdir(parents=True)
    server.mkdir(parents=True)
    metadata = json.dumps({'seed': 11}, sort_keys=True)
    (local / 'participant_metadata.json').write_text(metadata)
    (server / 'participant_metadata.json').write_text(metadata)
    (local / 'existing.txt').write_text('same')
    (server / 'existing.txt').write_text('same')
    (local / 'new.txt').write_text('new data')

    result = copy_participant_tree(local, server)

    assert result['status'] == 'copied'
    assert (server / 'existing.txt').read_text() == 'same'
    assert (server / 'new.txt').read_text() == 'new data'
