"""Filesystem persistence helpers that do not depend on PsychoPy."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import shutil
import tempfile
import wave
from datetime import datetime, timezone
from pathlib import Path

import config
from stimulus_split import ANIMATE, INANIMATE
from scoring import trial_summary
from timeline_key import FIELDS


def operator_warn(pid_dir, message):
    """Print an operator warning and append it to <pid_dir>/operator_warnings.txt for preflight.sh."""
    print(message)
    try:
        with (Path(pid_dir) / 'operator_warnings.txt').open('a', encoding='utf-8') as output:
            output.write(message + '\n')
    except OSError as exc:
        print(f'⚠️ Could not record operator warning in {pid_dir}: {exc}')


def json_default(obj):
    """Convert NumPy bool_/integer/floating and ndarray; reject anything else."""
    try:
        import numpy as np
    except ImportError:
        np = None
    if np is not None:
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
    raise TypeError(f'Object of type {type(obj).__name__} is not JSON serializable')


def _python_scalar(value):
    """NumPy scalars become Python values so CSV cells are not NumPy reprs."""
    if type(value).__module__ == 'numpy':
        return value.tolist()
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def config_snapshot():
    """JSON-normalized uppercase config values (tuples become lists, sets sorted lists)."""
    values = {name: value for name, value in vars(config).items()
              if name.isupper() and not name.startswith('_')}
    return json.loads(json.dumps(values, default=sorted))


def stimulus_paths(root, block, role, stimulus):
    """Resolve a timeline item through the study's canonical numbered pools."""
    if block not in {'animate', 'inanimate'} or role not in config.VISUAL_ROLES:
        raise ValueError(f'Unsupported block or role: {block!r}, {role!r}.')
    category = block if role in config.TARGET_ROLES else (
        'inanimate' if block == 'animate' else 'animate'
    )
    names = ANIMATE if category == 'animate' else INANIMATE
    try:
        number = names.index(stimulus) + 1
    except ValueError as exc:
        raise ValueError(f'{stimulus!r} is not in the {category} stimulus pool.') from exc
    root = Path(root)
    image = root / '20_stimuli' / category / 'objects_numbered' / '_normalized' / f'obj_{number}_bw.png'
    sound = root / '20_stimuli' / category / 'obj_snds' / '_cleaned' / f'snd_{number}.wav'
    return image, sound


def _number(row, field):
    try:
        value = float(row[field])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{row['event_id']} {field} must be numeric, got {row[field]!r}.") from exc
    if not math.isfinite(value):
        raise ValueError(f"{row['event_id']} {field} must be finite.")
    return value


def load_timeline(path, participant_metadata, root):
    """Load a saved timeline_key.csv for the runtime.

    Full rule checks ran once at generation (timeline_key.validate_timeline).
    This only checks integrity (sha256 and config snapshot from
    participant_metadata.json), schema/types, assets, and WAV durations.
    Returns (rows, assets, block_order, trials_by_block).
    """
    path, root = Path(path), Path(root)
    expected_sha = participant_metadata.get('timeline_sha256')
    actual_sha = sha256_file(path)
    if actual_sha != expected_sha:
        raise ValueError(
            f'{path} sha256 {actual_sha} does not match participant_metadata.json '
            f'({expected_sha}); the plan changed after generation.'
        )
    current = config_snapshot()
    stored = participant_metadata.get('config', {})
    changed = sorted(name for name in set(current) | set(stored) if current.get(name) != stored.get(name))
    if changed:
        raise ValueError(
            'config.py differs from the config snapshot saved with this plan; '
            f'changed values: {", ".join(changed)}. Restore those values to run this plan.'
        )

    with path.open(newline='', encoding='utf-8') as source:
        reader = csv.DictReader(source)
        missing = sorted(set(FIELDS) - set(reader.fieldnames or []))
        if missing:
            raise ValueError(f'Timeline is missing required columns: {missing}')
        rows = list(reader)
    if not rows:
        raise ValueError('Timeline has no events.')
    ids = [row['event_id'] for row in rows]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError('Timeline event_id values must be present and unique.')
    visual_ids = {row['event_id'] for row in rows if row['event_type'] == 'visual'}

    assets = {'images': {}, 'sounds': {}}
    sound_durations = {}
    trials_by_block = {}
    for row in rows:
        if row['block'] not in {'animate', 'inanimate'}:
            raise ValueError(f"{row['event_id']} has invalid block {row['block']!r}.")
        try:
            row['trial'] = int(row['trial'])
            row['event_index'] = int(row['event_index'])
        except ValueError as exc:
            raise ValueError(f"{row['event_id']} has a non-integer trial or event_index.") from exc
        if row['trial'] < 1:
            raise ValueError(f"{row['event_id']} has invalid trial {row['trial']}.")
        for field in ('global_onset', 'trial_onset', 'duration'):
            row[field] = _number(row, field)
        image_path, sound_path = stimulus_paths(root, row['block'], row['role'], row['stimulus'])
        if row['event_type'] == 'visual':
            if row['corner'] not in config.CORNER_SIGNS:
                raise ValueError(f"{row['event_id']} has invalid corner {row['corner']!r}.")
            row['x'], row['y'] = _number(row, 'x'), _number(row, 'y')
            if row['role'] in config.TARGET_ROLES:
                row['response_window'] = _number(row, 'response_window')
            assets['images'][row['stimulus']] = image_path
        elif row['event_type'] == 'sound':
            if row['role'] not in config.AUDIO_ROLES or row['source_event_id'] not in visual_ids:
                raise ValueError(f"Sound {row['event_id']} has an invalid role or source visual.")
            row['soa'] = _number(row, 'soa')
            assets['sounds'][row['stimulus']] = sound_path
            sound_durations[row['stimulus']] = row['duration']
        else:
            raise ValueError(f"{row['event_id']} has unknown event_type {row['event_type']!r}.")
        trials_by_block.setdefault(row['block'], set()).add(row['trial'])
    block_order = list(dict.fromkeys(row['block'] for row in rows))

    missing = [str(p) for group in assets.values() for p in group.values() if not p.is_file()]
    if not (root / config.BG_SOURCE_FILE).is_file():
        missing.append(str(root / config.BG_SOURCE_FILE))
    if missing:
        raise FileNotFoundError('Required experiment assets are missing:\n  ' + '\n  '.join(missing))
    for stimulus, wav_path in assets['sounds'].items():
        try:
            with wave.open(str(wav_path), 'rb') as audio_file:
                if audio_file.getnchannels() not in {1, 2} or audio_file.getnframes() < 1:
                    raise ValueError('audio must contain samples in one or two channels')
                actual = audio_file.getnframes() / audio_file.getframerate()
        except (wave.Error, OSError, ValueError) as exc:
            raise ValueError(f'Invalid WAV for {stimulus}: {wav_path}: {exc}') from exc
        if not math.isclose(actual, sound_durations[stimulus], abs_tol=0.002):
            raise ValueError(
                f'WAV for {stimulus} lasts {actual:.4f}s but the plan schedules '
                f'{sound_durations[stimulus]:.4f}s: {wav_path}'
            )
    return rows, assets, block_order, trials_by_block


def _participant_identity(folder: Path):
    metadata_path = folder / 'participant_metadata.json'
    metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    return metadata.get('seed'), sha256_file(metadata_path)


def copy_participant_tree(local_dir: Path, destination: Path) -> dict:
    """Copy missing files only; refuse conflicting participant identities or files."""
    local_dir, destination = Path(local_dir), Path(destination)
    copied, verified, failures = [], [], []
    if destination.exists():
        try:
            if _participant_identity(local_dir) != _participant_identity(destination):
                return {
                    'status': 'collision', 'destination': str(destination),
                    'reason': 'Existing server participant metadata has a different seed or sha256.',
                    'verified_files': [], 'failures': [],
                }
        except (OSError, ValueError, KeyError) as exc:
            return {
                'status': 'collision', 'destination': str(destination),
                'reason': f'Could not verify existing server participant identity: {exc}',
                'verified_files': [], 'failures': [],
            }

    try:
        for source_dir, _, filenames in os.walk(local_dir):
            relative = Path(source_dir).relative_to(local_dir)
            target_dir = destination / relative
            target_dir.mkdir(parents=True, exist_ok=True)
            for filename in filenames:
                source = Path(source_dir) / filename
                target = target_dir / filename
                relative_name = str(target.relative_to(destination))
                try:
                    if target.exists():
                        if sha256_file(source) != sha256_file(target):
                            failures.append(f'{relative_name}: destination checksum differs; preserved')
                        else:
                            verified.append(relative_name)
                        continue
                    try:
                        with source.open('rb') as src, target.open('xb') as dst:
                            shutil.copyfileobj(src, dst)
                    except FileExistsError:
                        if sha256_file(source) == sha256_file(target):
                            verified.append(relative_name)
                        else:
                            failures.append(f'{relative_name}: destination appeared with different content')
                        continue
                    if sha256_file(source) == sha256_file(target):
                        copied.append(relative_name)
                    else:
                        failures.append(f'{relative_name}: checksum mismatch after copy')
                except OSError as exc:
                    failures.append(f'{relative_name}: {type(exc).__name__}: {exc}')
        if any('checksum differs' in failure or 'different content' in failure for failure in failures):
            status = 'collision'
        else:
            status = 'copied' if not failures else 'partial'
        return {
            'status': status, 'destination': str(destination),
            'verified_files': copied + verified, 'failures': failures,
        }
    except OSError as exc:
        return {
            'status': 'failed', 'destination': str(destination),
            'reason': f'{type(exc).__name__}: {exc}',
            'verified_files': copied + verified, 'failures': failures,
        }


def _atomic_csv(path, fieldnames, rows):
    path = Path(path)
    fd, temp_name = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', newline='', encoding='utf-8') as output:
            writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(
                {column: _python_scalar(value) for column, value in row.items()}
                for row in rows
            )
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp_name, path)
    except Exception:
        Path(temp_name).unlink(missing_ok=True)
        raise


def save_session(session_dir, events, keys, trials, metadata):
    event_fields = list(FIELDS) + [
        'session_time_seconds', 'planned_session_time_seconds',
        'actual_session_time_seconds',
        'actual_minus_planned_seconds',
        'audio_requested_session_time', 'audio_requested_ptb_time', 'audio_backend_start_ptb_time',
        'audio_backend_start_session_time', 'audio_timing_source', 'sound_slot',
        'realized_soa_seconds', 'soa_error_seconds',
        'response_status', 'response_correct', 'response_key', 'response_session_time',
        'rt_from_actual_onset', 'rt_from_planned_onset', 'timing_flags',
        'key', 'classification', 'associated_event_id', 'matched_event_ids',
        'target_matches', 'correct', 'response_window_overlap', 'trial_complete',
    ]
    log_rows = []
    for event in events:
        row = dict(event)
        actual_time = event.get('actual_onset')
        row['session_time_seconds'] = actual_time if actual_time not in ('', None) else ''
        row['planned_session_time_seconds'] = event.get('runtime_planned_onset', '')
        row['actual_session_time_seconds'] = actual_time if actual_time not in (None, '') else ''
        row['actual_minus_planned_seconds'] = event.get('onset_deviation', '')
        row['classification'] = event.get('response_status', '')
        row['response_correct'] = event.get('response_correct', '')
        row['key'] = event.get('response_key', '')
        log_rows.append(row)
    for index, key in enumerate(keys, start=1):
        row = {
            'event_id': key.get('event_id', f"keypress_{index:06d}"),
            'event_type': 'keypress', 'block': key.get('block', ''),
            'trial': key.get('trial', ''),
            'session_time_seconds': key.get('session_time', ''),
            'actual_session_time_seconds': key.get('session_time', ''),
            'key': key.get('key', ''), 'corner': key.get('corner', ''),
            'classification': key.get('classification', ''),
            'associated_event_id': key.get('associated_event_id', ''),
            'matched_event_ids': key.get('matched_event_ids', ''),
            'target_matches': key.get('target_matches', ''),
            'correct': key.get('correct', ''),
            'response_window_overlap': key.get('response_window_overlap', ''),
            'rt_from_actual_onset': key.get('rt_from_actual_onset', ''),
            'rt_from_planned_onset': key.get('rt_from_planned_onset', ''),
            'trial_complete': key.get('trial_complete', ''),
        }
        log_rows.append(row)
    log_rows.sort(key=lambda row: (
        float(row['session_time_seconds']) if row.get('session_time_seconds') not in ('', None)
        else float(row['audio_requested_session_time'])
        if row.get('audio_requested_session_time') not in ('', None)
        else float(row['planned_session_time_seconds'])
        if row.get('planned_session_time_seconds') not in ('', None)
        else math.inf,
        0 if row.get('event_type') != 'keypress' else 1,
    ))
    _atomic_csv(session_dir / 'event_log.csv', event_fields, log_rows)
    metadata['trial_summary'] = trial_summary(trials)
    metadata['last_saved_utc'] = datetime.now(timezone.utc).isoformat()
    temp_path = session_dir / '.session_metadata.json.tmp'
    temp_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True, default=json_default),
        encoding='utf-8',
    )
    os.replace(temp_path, session_dir / 'session_metadata.json')


def copy_participant_data_to_server(root, participant_id):
    """Copy the local participant folder to the configured share and verify files."""
    server_root = os.environ.get('AV_STUDY_SERVER_ROOT')
    data_path = os.environ.get('AV_STUDY_SERVER_DATA_PATH')
    if not server_root or not data_path:
        return {'status': 'local_only', 'reason': 'server was not mounted at preflight'}

    local_participant_dir = Path(root) / 'data' / participant_id
    destination = Path(server_root) / data_path / participant_id
    result = copy_participant_tree(local_participant_dir, destination)
    if result['status'] == 'collision':
        operator_warn(local_participant_dir, f"🚨 SERVER DATA COLLISION for {participant_id}: {result.get('reason', result.get('failures'))}")
    return result


def _foreign_session_reason(remote_metadata: Path, metadata):
    """Why the server session_metadata.json is not this session's, or '' if it is (or is absent)."""
    if not remote_metadata.exists():
        return ''
    try:
        remote = json.loads(remote_metadata.read_text(encoding='utf-8'))
        identity = (remote['started_utc'], remote['seed'])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return f'Could not verify server session_metadata.json: {exc}; preserved.'
    if identity != (metadata.get('started_utc'), metadata.get('seed')):
        return 'Server session_metadata.json has a different started_utc or seed; preserved.'
    return ''


def sync_participant(root, participant_id, session_dir, metadata, save):
    """Push the participant folder, then re-copy the final session metadata."""
    pid_dir = Path(root) / 'data' / participant_id
    sync_result = copy_participant_data_to_server(root, participant_id)
    metadata['server_sync'] = sync_result
    save()
    if sync_result['status'] == 'copied':
        remote_metadata = Path(sync_result['destination']) / session_dir.name / 'session_metadata.json'
        local_metadata = session_dir / 'session_metadata.json'
        foreign = _foreign_session_reason(remote_metadata, metadata)
        if foreign:
            sync_result.update({'status': 'collision', 'reason': foreign})
            save()
            operator_warn(pid_dir, f'🚨 SERVER DATA COLLISION for {participant_id}: {foreign}')
        else:
            try:
                shutil.copyfile(local_metadata, remote_metadata)
                if hashlib.sha256(local_metadata.read_bytes()).hexdigest() != hashlib.sha256(remote_metadata.read_bytes()).hexdigest():
                    raise OSError('session metadata checksum mismatch')
            except OSError as exc:
                metadata['server_sync']['status'] = 'partial'
                metadata['server_sync']['failures'].append(f'session_metadata.json: {exc}')
                save()
                operator_warn(pid_dir, f'⚠️ Server copy completed, but final metadata update failed: {exc}')
    if sync_result['status'] == 'copied':
        print(f"✅ Full participant folder copied and verified on server: {sync_result['destination']}")
    elif sync_result['status'] == 'local_only':
        print(f"Participant data remains local at {session_dir}; no server was mounted at preflight.")
    else:
        operator_warn(pid_dir, f"⚠️ Server copy {sync_result['status']}; local data remains at {session_dir}.")
