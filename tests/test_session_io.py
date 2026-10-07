import json

from session_io import copy_participant_tree


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
