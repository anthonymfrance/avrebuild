"""Filesystem persistence helpers that do not depend on PsychoPy."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import shutil
import wave
from pathlib import Path

import config
from stimulus_split import ANIMATE, INANIMATE
from timeline_key import FIELDS


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
