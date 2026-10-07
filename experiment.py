"""Run a participant from an immutable timeline_key.csv plan."""

from __future__ import annotations

import argparse
import csv
import hashlib
import inspect
import json
import math
import os
import platform
import statistics
import shutil
import subprocess
import sys
import tempfile
import wave
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import config
from stimulus_split import ANIMATE, INANIMATE
from timeline_key import FIELDS as TIMELINE_FIELDS
from participant_setup import create_participant_plan
from session_io import copy_participant_tree
from audio_timing import AUDIO_START_SOURCE, backend_start_time, ptb_to_session, resolve_trial_audio
from scoring import (
    classify_press, finalize_targets, inter_trial_row, session_false_alarms,
    trial_feedback, trial_summary,
)


ROOT = Path(os.environ.get('AV_STUDY_DIR', Path(__file__).resolve().parent)).resolve()
RESPONSE_KEYS = {
    'top_left': ('num_4', 'KP_Left'),
    'top_right': ('num_5', 'KP_Begin'),
    'bottom_left': ('num_1', 'KP_End'),
    'bottom_right': ('num_2', 'KP_Down'),
}
KEY_TO_CORNER = {
    key: corner for corner, keys in RESPONSE_KEYS.items() for key in keys
}
VISUAL_ROLES = {'PT', 'NPT', 'PD', 'NPD'}
TARGET_ROLES = {'PT', 'NPT'}
AUDIO_ROLES = {'PT', 'PD'}
TRIAL_DURATION = 2 * config.TRIAL_BUFFER_DUR + config.TRIAL_CONTENT_DUR
VISUAL_DURATION = config.FADE_IN_DUR + config.PEAK_HOLD_DUR + config.FADE_OUT_DUR
ALL_KEYS = list(KEY_TO_CORNER) + ['space', 'escape']
BLOCK_LABELS = {'animate': 'ANIMALS', 'inanimate': 'OBJECTS'}


def stimulus_paths(block, role, stimulus):
    """Resolve a timeline item through the study's canonical numbered pools."""
    if block not in {'animate', 'inanimate'} or role not in VISUAL_ROLES:
        raise ValueError(f'Unsupported block or role: {block!r}, {role!r}.')
    category = block if role in TARGET_ROLES else (
        'inanimate' if block == 'animate' else 'animate'
    )
    names = ANIMATE if category == 'animate' else INANIMATE
    try:
        number = names.index(stimulus) + 1
    except ValueError as exc:
        raise ValueError(f'{stimulus!r} is not in the {category} stimulus pool.') from exc
    image = (
        ROOT / '20_stimuli' / category / 'objects_numbered' / '_normalized'
        / f'obj_{number}_bw.png'
    )
    sound = (
        ROOT / '20_stimuli' / category / 'obj_snds' / '_cleaned'
        / f'snd_{number}.wav'
    )
    return image, sound


def _patch_ptb_output_channels(ptb_audio, target_channels=2):
    """Limit virtual PortAudio device profiles to the study's stereo output."""
    original_get_devices = ptb_audio.get_devices
    if getattr(original_get_devices, '_av_study_patched', False):
        return

    def get_devices_with_stereo_limit(*args, **kwargs):
        profiles = original_get_devices(*args, **kwargs)
        for profile in profiles:
            try:
                output_channels = int(profile.get('NrOutputChannels', 0))
            except (TypeError, ValueError):
                continue
            if output_channels > target_channels:
                profile['NrOutputChannels'] = float(target_channels)
        return profiles

    get_devices_with_stereo_limit._av_study_patched = True
    ptb_audio.get_devices = get_devices_with_stereo_limit


def _patch_ptb_scalar_latency_argument(ptb_audio):
    """Adapt PsychoPy's one-item latency list to this PTB binding's scalar API."""
    original_stream = ptb_audio.Stream
    if getattr(original_stream, '_av_study_scalar_latency', False):
        return

    def stream_with_scalar_latency(*args, **kwargs):
        if 'latency_class' in kwargs:
            latency = kwargs['latency_class']
            if isinstance(latency, (list, tuple)) and len(latency) == 1:
                kwargs['latency_class'] = latency[0]
        elif len(args) >= 3:
            latency = args[2]
            if isinstance(latency, (list, tuple)) and len(latency) == 1:
                args = (*args[:2], latency[0], *args[3:])
        return original_stream(*args, **kwargs)

    stream_with_scalar_latency._av_study_scalar_latency = True
    ptb_audio.Stream = stream_with_scalar_latency


def _open_ptb_speaker(ptb_audio, speaker_device_class):
    """Open one explicit stereo-capable PTB speaker for the full session."""
    _patch_ptb_output_channels(ptb_audio)
    _patch_ptb_scalar_latency_argument(ptb_audio)
    profiles = ptb_audio.get_devices()
    outputs = [
        profile for profile in profiles
        if int(profile.get('NrOutputChannels', 0)) >= 2
    ]
    if not outputs:
        raise RuntimeError(
            'PTB found no stereo output devices. Device profiles: '
            f'{profiles!r}. Check the Linux audio server and output device.'
        )

    requested = config.AUDIO_SPEAKER
    if requested in {'', 'default', 'None'} and config.AUDIO_DEVICE not in {'', 'default', 'None'}:
        requested = config.AUDIO_DEVICE
    if requested in {'', 'default', 'None'}:
        def default_route_rank(profile):
            name = str(profile.get('DeviceName', '')).lower()
            host_api = str(profile.get('HostAudioAPIName', '')).lower()
            if 'jack' in host_api:
                if 'built-in audio analog stereo' in name:
                    return 0
                if 'built-in audio' in name:
                    return 1
                return 2
            if 'pipewire' in name:
                return 3
            if 'pulse' in name:
                return 4
            if name in {'default', 'sysdefault'}:
                return 5 if name == 'default' else 6
            return 7

        chosen = min(outputs, key=default_route_rank)
    else:
        chosen = next(
            (profile for profile in outputs if profile.get('DeviceName') == requested),
            None,
        )
        if chosen is None:
            available = [profile.get('DeviceName') for profile in outputs]
            raise RuntimeError(
                f'Configured PTB speaker {requested!r} is unavailable. '
                f'Stereo output devices: {available!r}.'
            )

    try:
        speaker = speaker_device_class(
            index=int(chosen['DeviceIndex']), latencyClass=config.AUDIO_LATENCY_MODE,
        )
    except Exception as exc:
        raise RuntimeError(
            f"PTB could not open '{chosen.get('DeviceName')}' "
            f"(index {chosen.get('DeviceIndex')}, channels "
            f"{chosen.get('NrOutputChannels')}, host API "
            f"{chosen.get('HostAudioAPIName')}, rate "
            f"{chosen.get('DefaultSampleRate')} Hz): {type(exc).__name__}: {exc}. "
            f'Available output profiles: {outputs!r}'
        ) from exc
    return speaker, chosen


def _finite_number(value, label):
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{label} must be numeric, got {value!r}.') from exc
    if not math.isfinite(number):
        raise ValueError(f'{label} must be finite.')
    return number


def read_and_validate_timeline(path):
    """Validate the complete planned session and every asset before the task."""
    path = Path(path).resolve()
    with path.open(newline='', encoding='utf-8') as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None or not set(TIMELINE_FIELDS).issubset(reader.fieldnames):
            missing = sorted(set(TIMELINE_FIELDS) - set(reader.fieldnames or []))
            raise ValueError(f'Timeline is missing required columns: {missing}')
        rows = list(reader)
    if not rows:
        raise ValueError('Timeline has no events.')

    ids = [row['event_id'] for row in rows]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError('Timeline event_id values must be present and unique.')
    first_order = list(dict.fromkeys(row['block'] for row in rows))
    if any(block not in {'animate', 'inanimate'} for block in first_order):
        raise ValueError('Timeline block values must be animate or inanimate.')
    if set(first_order) != {'animate', 'inanimate'}:
        raise ValueError('Timeline must contain both animate and inanimate blocks.')

    trials_by_block = {}
    rows_by_trial = defaultdict(list)
    visual_by_id = {}
    expected_sounds = set()
    previous_global = -math.inf
    assets = {'images': {}, 'sounds': {}}
    for row in rows:
        try:
            row['trial'] = int(row['trial'])
            row['event_index'] = int(row['event_index'])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid trial or event_index in {row['event_id']}.") from exc
        if row['trial'] < 1:
            raise ValueError(f"Invalid trial number in {row['event_id']}.")
        row['global_onset'] = _finite_number(row['global_onset'], f"{row['event_id']} global_onset")
        row['trial_onset'] = _finite_number(row['trial_onset'], f"{row['event_id']} trial_onset")
        row['duration'] = _finite_number(row['duration'], f"{row['event_id']} duration")
        if row['global_onset'] < previous_global:
            raise ValueError('Timeline rows are not ordered by global_onset.')
        previous_global = row['global_onset']
        if row['trial_onset'] < 0 or row['trial_onset'] >= TRIAL_DURATION:
            raise ValueError(f"{row['event_id']} trial_onset is outside the configured trial.")
        if row['trial_onset'] + row['duration'] > TRIAL_DURATION + 1e-9:
            raise ValueError(f"{row['event_id']} extends beyond its configured trial.")
        rows_by_trial[(row['block'], row['trial'])].append(row)
        trials_by_block.setdefault(row['block'], set()).add(row['trial'])

        if row['event_type'] == 'visual':
            if row['role'] not in VISUAL_ROLES:
                raise ValueError(f"Unsupported visual role in {row['event_id']}.")
            if row['corner'] not in RESPONSE_KEYS:
                raise ValueError(f"Invalid visual corner in {row['event_id']}.")
            x = _finite_number(row['x'], f"{row['event_id']} x")
            y = _finite_number(row['y'], f"{row['event_id']} y")
            x_sign, y_sign = {
                'top_left': (-1, 1), 'top_right': (1, 1),
                'bottom_left': (-1, -1), 'bottom_right': (1, -1),
            }[row['corner']]
            x_low, x_high = config.IMAGE_SIZE[0] / 2, config.WINDOW_SIZE[0] / 2 - config.IMAGE_SIZE[0] / 2
            y_low, y_high = config.IMAGE_SIZE[1] / 2, config.WINDOW_SIZE[1] / 2 - config.IMAGE_SIZE[1] / 2
            if not (x_low <= x_sign * x <= x_high and y_low <= y_sign * y <= y_high):
                raise ValueError(f"{row['event_id']} position is outside its configured corner.")
            if not math.isclose(row['duration'], VISUAL_DURATION, abs_tol=1e-6):
                raise ValueError(f"{row['event_id']} duration differs from configured visual duration.")
            if (row['trial_onset'] < config.TRIAL_BUFFER_DUR - 1e-9
                    or row['trial_onset'] + row['duration']
                    > config.TRIAL_BUFFER_DUR + config.TRIAL_CONTENT_DUR + 1e-9):
                raise ValueError(f"{row['event_id']} visual is outside the content window.")
            target_window = row['role'] in TARGET_ROLES
            if target_window:
                row['response_window'] = _finite_number(
                    row['response_window'], f"{row['event_id']} response_window"
                )
                if not math.isclose(row['response_window'], config.RESPONSE_WINDOW, abs_tol=1e-6):
                    raise ValueError(f"{row['event_id']} response window differs from config.")
                if row['trial_onset'] + row['response_window'] > TRIAL_DURATION + 1e-9:
                    raise ValueError(f"{row['event_id']} response window extends beyond its trial.")
            elif row['response_window'] != '':
                raise ValueError(f"Distractor {row['event_id']} has a response window.")
            image_path, sound_path = stimulus_paths(row['block'], row['role'], row['stimulus'])
            assets['images'][row['stimulus']] = image_path
            visual_by_id[row['event_id']] = row
            if row['role'] in AUDIO_ROLES:
                expected_sounds.add((row['event_id'], row['stimulus'], sound_path))
        elif row['event_type'] == 'sound':
            if row['role'] not in AUDIO_ROLES or row['corner'] or row['x'] or row['y']:
                raise ValueError(f"Invalid sound row {row['event_id']}.")
            if row['response_window'] != '':
                raise ValueError(f"Sound {row['event_id']} has a response window.")
            if (row['trial_onset'] < config.TRIAL_BUFFER_DUR - 1e-9
                    or row['trial_onset'] + row['duration']
                    > config.TRIAL_BUFFER_DUR + config.TRIAL_CONTENT_DUR + 1e-9):
                raise ValueError(f"{row['event_id']} sound is outside the content window.")
            if not math.isclose(row['duration'], config.SOUND_DUR, abs_tol=1e-6):
                raise ValueError(f"{row['event_id']} duration differs from configured sound duration.")
        else:
            raise ValueError(f"Unknown event_type in {row['event_id']}.")

    for block in first_order:
        block_trials = trials_by_block[block]
        if block_trials != set(range(1, max(block_trials) + 1)):
            raise ValueError(f'{block} trial numbers must be contiguous starting at 1.')
    expected_trial_keys = {
        (block, trial) for block in first_order for trial in trials_by_block[block]
    }
    if set(rows_by_trial) != expected_trial_keys:
        raise ValueError('Timeline contains an inconsistent block/trial grouping.')
    offsets_by_trial = {}
    for key, group in rows_by_trial.items():
        offsets = {round(row['global_onset'] - row['trial_onset'], 6) for row in group}
        if len(offsets) != 1:
            raise ValueError(f'{key[0]} trial {key[1]} has inconsistent global/local onset offsets.')
        offsets_by_trial[key] = offsets.pop()
        visuals = sorted(
            (row for row in group if row['event_type'] == 'visual'),
            key=lambda row: row['global_onset'],
        )
        try:
            visual_order = [int(row['order_in_trial']) for row in visuals]
        except (TypeError, ValueError) as exc:
            raise ValueError(f'{key[0]} trial {key[1]} has invalid visual order labels.') from exc
        if visual_order != list(range(1, len(visuals) + 1)):
            raise ValueError(f'{key[0]} trial {key[1]} visual order labels do not match onset order.')
        targets = [row for row in visuals if row['role'] in TARGET_ROLES]
        for left, right in zip(visuals, visuals[1:]):
            if right['global_onset'] - left['global_onset'] + 1e-9 < config.MIN_VISUAL_ONSET_GAP:
                raise ValueError(f'{key[0]} trial {key[1]} violates the visual onset gap.')
        for left, right in zip(targets, targets[1:]):
            if right['global_onset'] - left['global_onset'] + 1e-9 < config.RESPONSE_WINDOW:
                raise ValueError(f'{key[0]} trial {key[1]} has overlapping planned target windows.')
            target_gap = right['global_onset'] - (left['global_onset'] + VISUAL_DURATION)
            if target_gap + 1e-9 < config.MIN_TARGET_END_TO_ONSET_GAP:
                raise ValueError(f'{key[0]} trial {key[1]} violates target end-to-onset gap.')

    for block in first_order:
        block_trials = sorted(trials_by_block[block])
        for left_trial, right_trial in zip(block_trials, block_trials[1:]):
            left_offset = offsets_by_trial[(block, left_trial)]
            right_offset = offsets_by_trial[(block, right_trial)]
            if not math.isclose(right_offset - left_offset, TRIAL_DURATION, abs_tol=1e-4):
                raise ValueError(f'{block} planned trial spacing differs from configured trial duration.')
    block_trial_counts = {len(trials_by_block[block]) for block in first_order}
    if len(block_trial_counts) != 1:
        raise ValueError('Blocks must contain the same number of trials for the planned global clock.')
    trial_count = block_trial_counts.pop()
    for block_index, block in enumerate(first_order):
        for trial in trials_by_block[block]:
            expected_offset = (block_index * trial_count + trial - 1) * TRIAL_DURATION
            if not math.isclose(
                offsets_by_trial[(block, trial)], expected_offset, abs_tol=1e-4
            ):
                raise ValueError(f'{block} trial {trial} global_onset does not match the no-break plan.')

    sounds_by_id = [row for row in rows if row['event_type'] == 'sound']
    sound_sources = [row['source_event_id'] for row in sounds_by_id]
    expected_by_id = {event_id for event_id, _, _ in expected_sounds}
    if len(sound_sources) != len(set(sound_sources)) or set(sound_sources) != expected_by_id:
        raise ValueError('Timeline sound rows do not pair one-to-one with PT and PD visuals.')
    for row in sounds_by_id:
        source = visual_by_id.get(row['source_event_id'])
        if source is None or source['stimulus'] != row['stimulus'] or source['role'] != row['role']:
            raise ValueError(f"Sound {row['event_id']} does not match its source visual.")
        if row['block'] != source['block'] or row['trial'] != source['trial']:
            raise ValueError(f"Sound {row['event_id']} is assigned to the wrong trial.")
        if row['event_id'] != f"{source['event_id']}_sound":
            raise ValueError(f"Sound {row['event_id']} has an unexpected event identifier.")
        if row['duration'] <= 0:
            raise ValueError(f"Sound {row['event_id']} has invalid duration.")
        row['soa'] = _finite_number(row['soa'], f"{row['event_id']} soa")
        soa_min, soa_max = (
            (config.PT_SOA_MIN, config.PT_SOA_MAX)
            if row['role'] == 'PT' else (config.PD_SOA_MIN, config.PD_SOA_MAX)
        )
        if not soa_min <= row['soa'] <= soa_max:
            raise ValueError(f"{row['event_id']} SOA is outside configured bounds.")
        if not math.isclose(
            row['trial_onset'],
            source['trial_onset'] + config.FADE_IN_DUR - row['soa'],
            abs_tol=1e-5,
        ):
            raise ValueError(f"{row['event_id']} does not match its visual SOA.")
        assets['sounds'][row['stimulus']] = stimulus_paths(
            row['block'], row['role'], row['stimulus']
        )[1]

    for block in first_order:
        block_visuals = sorted(
            (row for row in rows if row['block'] == block and row['event_type'] == 'visual'),
            key=lambda row: row['global_onset'],
        )
        block_sounds = sorted(
            (row for row in rows if row['block'] == block and row['event_type'] == 'sound'),
            key=lambda row: row['global_onset'],
        )
        by_corner = defaultdict(list)
        for visual_row in block_visuals:
            by_corner[visual_row['corner']].append(visual_row)
        for corner_rows in by_corner.values():
            for left, right in zip(corner_rows, corner_rows[1:]):
                if right['global_onset'] - left['global_onset'] + 1e-9 < VISUAL_DURATION:
                    raise ValueError(f'{block} contains overlapping visuals in one corner.')
        for index, left in enumerate(block_visuals):
            for right in block_visuals[index + 1:]:
                gap = right['global_onset'] - (left['global_onset'] + VISUAL_DURATION)
                if left['stimulus'] == right['stimulus'] and gap + 1e-9 < config.MIN_SAME_ITEM_GAP:
                    raise ValueError(f'{block} violates the minimum same-item gap.')
                if left['role'] == right['role'] == 'PT' and gap + 1e-9 < config.BETWEEN_PT_STIMULUS_GAP:
                    raise ValueError(f'{block} violates the between-PT gap.')
        for left, right in zip(block_sounds, block_sounds[1:]):
            if right['global_onset'] - left['global_onset'] + 1e-9 < config.SOUND_DUR + config.MIN_AUDIO_GAP:
                raise ValueError(f'{block} violates the minimum audio gap.')

    missing = [str(path) for group in assets.values() for path in group.values() if not path.is_file()]
    if not (ROOT / config.BG_SOURCE_FILE).is_file():
        missing.append(str(ROOT / config.BG_SOURCE_FILE))
    if missing:
        raise FileNotFoundError('Required experiment assets are missing:\n  ' + '\n  '.join(missing))
    for stimulus, path in assets['sounds'].items():
        try:
            with wave.open(str(path), 'rb') as audio_file:
                if audio_file.getnchannels() not in {1, 2} or audio_file.getnframes() < 1:
                    raise ValueError('audio must contain samples in one or two channels')
                actual_duration = audio_file.getnframes() / audio_file.getframerate()
                if not math.isclose(actual_duration, config.SOUND_DUR, abs_tol=0.002):
                    raise ValueError(
                        f'audio duration {actual_duration:.4f}s differs from configured '
                        f'{config.SOUND_DUR:.4f}s'
                    )
        except (wave.Error, OSError, ValueError) as exc:
            raise ValueError(f'Invalid WAV for {stimulus}: {path}: {exc}') from exc

    indices = [row['event_index'] for row in rows]
    if indices != list(range(1, len(rows) + 1)):
        raise ValueError('Timeline event_index values must be consecutive in CSV order.')
    return path, rows, assets, first_order, trials_by_block


def make_backgrounds(window, visual, np, Image):
    """Build cached Fourier phase-randomized backgrounds before the task."""
    source_path = ROOT / config.BG_SOURCE_FILE
    image = np.asarray(Image.open(source_path).convert('L'), dtype=np.float32)
    spectrum = np.fft.fftshift(np.fft.fft2(image))
    magnitude = np.abs(spectrum)
    backgrounds = []
    for _ in range(20):
        phase = np.random.uniform(-np.pi, np.pi, spectrum.shape)
        frame = np.real(np.fft.ifft2(np.fft.ifftshift(magnitude * np.exp(1j * phase))))
        low, high = float(frame.min()), float(frame.max())
        normalized = np.zeros_like(frame) if high <= low else (frame - low) / (high - low)
        backgrounds.append(visual.ImageStim(
            window, image=normalized * 2.0 - 1.0, size=window.size,
            units='pix', opacity=config.BG_NOISE_OPACITY, autoLog=False,
        ))
    return backgrounds


def planned_image_alpha(time_to_onset):
    elapsed = max(0.0, time_to_onset)
    if elapsed < config.FADE_IN_DUR:
        return max(0.02, min(1.0, elapsed / config.FADE_IN_DUR))
    elapsed -= config.FADE_IN_DUR
    if elapsed < config.PEAK_HOLD_DUR:
        return 1.0
    elapsed -= config.PEAK_HOLD_DUR
    return max(0.0, min(1.0, 1.0 - elapsed / config.FADE_OUT_DUR))


def convert_default_clock(clock, default_time, logging):
    """Convert Window.flip's defaultClock time into the session clock domain."""
    return (
        default_time + logging.defaultClock.getLastResetTime()
        - clock.getLastResetTime()
    )


def _atomic_csv(path, fieldnames, rows):
    path = Path(path)
    fd, temp_name = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', newline='', encoding='utf-8') as output:
            writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp_name, path)
    except Exception:
        Path(temp_name).unlink(missing_ok=True)
        raise


def _parse_preflight_report(report_text):
    report = {}
    display_modes = []
    in_display_modes = False
    for line in report_text.splitlines():
        if line == 'Connected display modes:':
            in_display_modes = True
            continue
        if in_display_modes:
            if line.strip():
                display_modes.append(line.strip())
        elif '=' in line:
            key, value = line.split('=', 1)
            report[key] = value
    if display_modes:
        report['connected_display_modes'] = display_modes
    return report


def save_session(session_dir, events, keys, trials, metadata):
    event_fields = list(TIMELINE_FIELDS) + [
        'session_time_seconds', 'planned_session_time_seconds',
        'actual_session_time_seconds',
        'actual_minus_planned_seconds',
        'audio_requested_session_time', 'audio_requested_ptb_time', 'audio_backend_start_ptb_time',
        'audio_backend_start_session_time', 'audio_timing_source',
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
    temp_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding='utf-8')
    os.replace(temp_path, session_dir / 'session_metadata.json')


def copy_participant_data_to_server(participant_id):
    """Copy the local participant folder to the configured share and verify files."""
    server_root = os.environ.get('AV_STUDY_SERVER_ROOT')
    data_path = os.environ.get('AV_STUDY_SERVER_DATA_PATH')
    if not server_root or not data_path:
        return {'status': 'local_only', 'reason': 'server was not mounted at preflight'}

    local_participant_dir = ROOT / 'data' / participant_id
    destination = Path(server_root) / data_path / participant_id
    result = copy_participant_tree(local_participant_dir, destination)
    if result['status'] == 'collision':
        print(f"🚨 SERVER DATA COLLISION for {participant_id}: {result.get('reason', result.get('failures'))}")
    return result


def run(args):
    pid_dir = ROOT / 'data' / args.pid
    report_source = os.environ.get('AV_STUDY_PREFLIGHT_REPORT')
    if not report_source or not Path(report_source).is_file():
        raise FileNotFoundError('Preflight report is missing. Start the experiment from preflight.sh.')
    report_text = Path(report_source).read_text(encoding='utf-8')
    if f'participant_id={args.pid}' not in report_text:
        raise ValueError('Preflight report participant ID does not match the requested participant.')
    preflight_report = _parse_preflight_report(report_text)
    if 'display_refresh_hz' not in preflight_report:
        raise ValueError('Preflight report does not contain the xrandr display refresh rate.')
    display_refresh_hz = _finite_number(
        preflight_report['display_refresh_hz'], 'preflight display_refresh_hz'
    )
    if display_refresh_hz <= 0:
        raise ValueError('Preflight xrandr refresh rate must be positive.')

    try:
        import numpy as np
        from PIL import Image
        from psychopy import prefs
        prefs.hardware['audioLib'] = [config.AUDIO_BACKEND]
        prefs.hardware['audioLatencyMode'] = [config.AUDIO_LATENCY_MODE]
        prefs.hardware['audioDevice'] = [config.AUDIO_DEVICE]
        prefs.hardware['audioSpeaker'] = [config.AUDIO_SPEAKER]
        from psychopy import core, logging, sound, visual
        from psychopy.hardware import keyboard
        from psychopy.hardware.speaker import SpeakerDevice
        import psychopy
        import psychtoolbox as ptb
        import psychtoolbox.audio as ptb_audio
    except ImportError as exc:
        raise RuntimeError(
            'PsychoPy with its PTB audio backend, NumPy, Pillow, and psychtoolbox are required.'
        ) from exc

    session_clock = core.Clock()
    clock_offset = (
        ptb_to_session(ptb.GetSecs(), session_clock.getLastResetTime()) - session_clock.getTime()
    )
    if abs(clock_offset) > 0.005:
        raise RuntimeError(
            f'PsychoPy Clock and PTB GetSecs do not share a time base (offset {clock_offset:.6f} s); '
            'audio timestamps cannot be converted to session time.'
        )
    shared_speaker, speaker_profile = _open_ptb_speaker(ptb_audio, SpeakerDevice)

    window = None
    session_dir = None
    kb = None
    all_events = []
    key_rows = []
    trial_rows = []
    current_trial_events = None
    current_trial_row = None
    metadata = {
        'participant_id': args.pid,
        'started_utc': None,
        'psychopy_version': psychopy.__version__,
        'python_version': sys.version,
        'platform': platform.platform(),
        'audio_backend_requested': config.AUDIO_BACKEND,
        'audio_latency_mode': config.AUDIO_LATENCY_MODE,
        'audio_device_profile': speaker_profile,
        'audio_timing_note': 'PTB software-reported playback timing; no physical loopback measurement.',
        'audio_start_source': None,
        'audio_clock_conversion': 'session_time = PTB time - session_clock.getLastResetTime()',
        'audio_clock_offset_check_seconds': clock_offset,
        'preflight': preflight_report,
        'display_refresh_hz': display_refresh_hz,
        'display_refresh_rate_source': 'xrandr active mode',
        'background_source': str(ROOT / config.BG_SOURCE_FILE),
        'background_variants': 20,
        'seed': None,
        'sound_check': {'status': 'pending'},
        'clock_strategy': 'session core.Clock; Keyboard on session clock; flip timestamps converted from PsychoPy defaultClock; PTB targets converted from a paired future-flip time.',
    }

    try:
        # The window is initialized before the participant sees the start screen.
        window = visual.Window(
            size=config.WINDOW_SIZE, fullscr=True, screen=0,
            units='pix', color=[0, 0, 0], checkTiming=True, waitBlanking=True,
        )
        test_tone = sound.Sound(
            440, secs=0.8, stereo=True, speaker=shared_speaker, autoLog=False,
        )
        sound_class = type(test_tone)
        play_signature = inspect.signature(test_tone.play)
        if config.AUDIO_BACKEND != 'ptb':
            raise RuntimeError('Only the PTB audio backend is supported for this experiment.')
        if ('backend_ptb' not in sound_class.__module__
                and not sound_class.__module__.endswith('.SoundPTB')):
            raise RuntimeError(
                f'PTB was requested, but PsychoPy created {sound_class.__module__}.{sound_class.__name__}.'
            )
        if 'when' not in play_signature.parameters and not any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in play_signature.parameters.values()
        ):
            raise RuntimeError('The active PTB Sound.play() does not support scheduled when= playback.')
        metadata['audio_backend_class'] = f'{sound_class.__module__}.{sound_class.__name__}'
        metadata['audio_channels_requested'] = 2
        metadata['audio_volume'] = 1.0
        metadata['audio_speaker'] = shared_speaker.name
        try:
            from importlib.metadata import version
            metadata['psychtoolbox_version'] = version('psychtoolbox')
        except Exception:
            metadata['psychtoolbox_version'] = None

        fix_half = config.FIXATION_SIZE / 2
        fixation = visual.ShapeStim(
            window,
            vertices=((0, -fix_half), (0, fix_half), (0, 0), (-fix_half, 0), (fix_half, 0)),
            closeShape=False, lineColor=config.FIXATION_COLOR,
            lineWidth=config.FIXATION_LINE_WIDTH, pos=(0, 0), autoLog=False,
        )
        instruction = visual.TextStim(
            window, text='', color='white', height=28, wrapWidth=window.size[0] * 0.8,
            units='pix', autoLog=False,
        )
        instruction.text = (
            'Your goal is to press the numpad key for the corner containing your target image.\n'
            'When you see a target, respond within '
            f'{config.RESPONSE_WINDOW:g} seconds. Ignore other images.\n'
            'Please keep your eyes near the center fixation cross and shift your attention\n'
            'toward the corners as needed. You may notice patterns; keep following the task.\n\n'
            '                 TOP\n'
            '        4                 5\n'
            '     top left          top right\n\n'
            '        1                 2\n'
            '  bottom left      bottom right\n'
            '              BOTTOM\n\n'
            'Press SPACE to begin. Press ESCAPE to stop the study.'
        )
        kb = keyboard.Keyboard(clock=session_clock)
        kb.clearEvents()

        numpad_test_keys = ('num_4', 'num_5', 'num_1', 'num_2')
        numpad_test_names = {
            'num_4': 'top-left (4)', 'num_5': 'top-right (5)',
            'num_1': 'bottom-left (1)', 'num_2': 'bottom-right (2)',
        }
        numpad_test_text = visual.TextStim(
            window, text='', color='white', height=28,
            wrapWidth=window.size[0] * 0.8, units='pix', autoLog=False,
        )
        numpad_test_seen = set()
        while len(numpad_test_seen) < len(numpad_test_keys):
            missing = [numpad_test_names[key] for key in numpad_test_keys
                       if key not in numpad_test_seen]
            numpad_test_text.text = (
                'Numpad check\n\n'
                'Press each indicated key on the numeric keypad once.\n'
                f'Still to check: {", ".join(missing)}\n\n'
                'If a key does not register, turn Num Lock on and try again.\n'
                'Press ESCAPE to stop.'
            )
            numpad_test_text.draw()
            window.flip()
            presses = kb.getKeys(keyList=list(numpad_test_keys) + ['escape'],
                                 waitRelease=False, clear=True)
            if any(key.name == 'escape' for key in presses):
                return
            numpad_test_seen.update(key.name for key in presses)

        sound_check_text = visual.TextStim(
            window, text='', color='white', height=28,
            wrapWidth=window.size[0] * 0.8, units='pix', autoLog=False,
        )
        sound_check_text.text = (
            'Sound check\n\nA short tone will play. '
            'Press R to replay it, SPACE if you heard it, N if you did not, or ESCAPE to stop.'
        )
        test_tone.play()
        while True:
            sound_check_text.draw()
            window.flip()
            presses = kb.getKeys(keyList=['space', 'r', 'n', 'escape'], waitRelease=False, clear=True)
            if any(key.name == 'escape' for key in presses):
                return
            if any(key.name == 'r' for key in presses):
                test_tone.stop()
                test_tone.play()
            if any(key.name == 'space' for key in presses):
                metadata['sound_check'] = {
                    'status': 'confirmed', 'participant_response': 'heard',
                    'tone_hz': 440, 'tone_duration_seconds': 0.8,
                }
                break
        test_tone_start = backend_start_time(test_tone, requested_ptb=0.0)
        metadata['sound_check']['backend_start_ptb_time'] = test_tone_start
        if test_tone_start is None:
            print(f'⚠️ PTB reported no audio start time ({AUDIO_START_SOURCE}) for the sound check; '
                  "audio timing will fall back to requested times (audio_timing_source='requested_only').")
            if any(key.name == 'n' for key in presses):
                return

        # The participant ID and plan are consumed only after both hardware checks pass.
        timeline_path, plan_snapshot = create_participant_plan(ROOT / 'data', args.pid)
        Path(report_source).unlink(missing_ok=True)
        participant_metadata_path = pid_dir / 'participant_metadata.json'
        timeline_path, rows, assets, block_order, trials_by_block = read_and_validate_timeline(timeline_path)
        metadata.update({
            'timeline_path': str(timeline_path),
            'timeline_sha256': hashlib.sha256(timeline_path.read_bytes()).hexdigest(),
            'timeline_order': block_order,
            'timeline_used_unchanged': True,
            'seed': plan_snapshot['seed'],
            'participant_metadata_file': participant_metadata_path.name,
            'participant_metadata_sha256': hashlib.sha256(
                participant_metadata_path.read_bytes()
            ).hexdigest(),
        })
        backgrounds = make_backgrounds(window, visual, np, Image)
        image_cache = {
            stimulus: visual.ImageStim(
                window, image=str(path), size=config.IMAGE_SIZE,
                units='pix', autoLog=False,
            )
            for stimulus, path in assets['images'].items()
        }
        sound_cache = {
            stimulus: sound.Sound(
                str(path), speaker=shared_speaker,
                stereo=True, preBuffer=-1, autoLog=False,
            )
            for stimulus, path in assets['sounds'].items()
        }
        if not sound_cache:
            raise RuntimeError('Timeline has no sounds.')

        # Operator-facing summary of this participant's immutable timeline plan.
        pt_soa_by_block = {}
        for block in block_order:
            pt_soa_by_block[block] = {}
            for row in rows:
                if row['block'] == block and row['event_type'] == 'sound' and row['role'] == 'PT':
                    pt_soa_by_block[block][row['stimulus']] = float(row['soa'])
        debug_lines = [
            'STUDY SETUP — STIMULUS ASSIGNMENTS',
            f"Participant: {args.pid}    Block order: {' → '.join(BLOCK_LABELS[b] for b in block_order)}",
            f'Target response window: {config.RESPONSE_WINDOW:.1f} seconds',
            'PT SOA is fixed for each PT in this participant plan:',
            f'PD sound lead: {config.PD_SOA_MIN:.2f}–{config.PD_SOA_MAX:.2f} seconds',
            '',
        ]
        for block in block_order:
            block_rows = [row for row in rows if row['block'] == block]
            pt_counts = sum(row['event_type'] == 'visual' and row['role'] == 'PT' for row in block_rows)
            pd_counts = sum(row['event_type'] == 'visual' and row['role'] == 'PD' for row in block_rows)
            npd_counts = sum(row['event_type'] == 'visual' and row['role'] == 'NPD' for row in block_rows)
            debug_lines.append(f"{BLOCK_LABELS[block]} BLOCK — target group: {BLOCK_LABELS[block]}")
            debug_lines.append(
                '  PT SOA by target: ' + ', '.join(
                    f'{name} = {soa:.1f}s' for name, soa in sorted(pt_soa_by_block[block].items())
                )
            )
            debug_lines.append(f'  Events per block — PT: {pt_counts}, PD: {pd_counts}, NPD: {npd_counts}')
            for role, description in (
                ('PT', 'Targets with sound (PT)'),
                ('NPT', 'Targets without sound (NPT)'),
                ('PD', 'Distractors with sound (PD)'),
                ('NPD', 'Distractors without sound (NPD)'),
            ):
                names = sorted({row['stimulus'] for row in block_rows
                                if row['event_type'] == 'visual' and row['role'] == role})
                debug_lines.append(f"  {description}: {', '.join(names) if names else 'none'}")
            debug_lines.append(
                f"  Trials: {len(trials_by_block[block])}; visual events: "
                f"{sum(row['event_type'] == 'visual' for row in block_rows)}"
            )
            debug_lines.append('')
        debug_lines.append('Operator review: press SPACE to continue to the instructions.')
        debug_text = visual.TextStim(
            window, text='\n'.join(debug_lines), color='white', height=20,
            wrapWidth=window.size[0] * 0.88, units='pix', autoLog=False,
        )
        debug_overlay_enabled = os.environ.get('AV_STUDY_DEBUG_OVERLAY', 'false').lower() == 'true'
        if debug_overlay_enabled:
            while True:
                debug_text.draw()
                window.flip()
                presses = kb.getKeys(keyList=['space', 'escape'], waitRelease=False, clear=True)
                if any(key.name == 'escape' for key in presses):
                    return
                if any(key.name == 'space' for key in presses):
                    break

        window.flip()
        instruction.draw()
        window.flip()
        while True:
            instruction.draw()
            window.flip()
            presses = kb.getKeys(keyList=['space', 'escape'], waitRelease=False, clear=True)
            if any(key.name == 'escape' for key in presses):
                return
            if any(key.name == 'space' for key in presses):
                break

        session_clock.reset()
        kb.clearEvents()
        metadata['started_utc'] = datetime.now(timezone.utc).isoformat()
        session_number = 1
        while (pid_dir / f'session_{session_number:02d}').exists():
            session_number += 1
        session_name = f'session_{session_number:02d}'
        session_dir = pid_dir / session_name
        session_dir.mkdir(parents=True, exist_ok=False)
        try:
            metadata['git_commit'] = subprocess.check_output(
                ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            metadata['git_commit'] = None
        metadata['session_dir'] = str(session_dir)

        window_text = visual.TextStim(
            window, text='', color='white', height=28,
            wrapWidth=window.size[0] * 0.8, units='pix', autoLog=False,
        )
        debug_overlay = visual.TextStim(
            window, text='', color='yellow', height=18,
            pos=(-window.size[0] * 0.42, window.size[1] * 0.43),
            alignText='left', anchorHoriz='left', anchorVert='top',
            units='pix', autoLog=False,
        )

        last_block, last_trial = '', ''

        def continuation(message):
            window_text.text = message + '\n\nPress SPACE to continue. Press ESCAPE to stop.'
            while True:
                window_text.draw()
                window.flip()
                presses = kb.getKeys(keyList=ALL_KEYS, waitRelease=False, clear=True)
                for key in presses:
                    if key.name in KEY_TO_CORNER:
                        key_rows.append(inter_trial_row(
                            key.name, KEY_TO_CORNER[key.name], float(key.rt), last_block, last_trial,
                        ))
                if any(key.name == 'escape' for key in presses):
                    key = next(key for key in presses if key.name == 'escape')
                    key_rows.append({
                        'session_time': float(key.rt), 'key': key.name, 'corner': '',
                        'classification': 'abort', 'matched_event_ids': '',
                        'target_matches': '', 'correct': '',
                        'response_window_overlap': False,
                        'block': last_block, 'trial': last_trial,
                    })
                    return False
                if any(key.name == 'space' for key in presses):
                    return True

        def rest_break(duration_seconds=120):
            rest_text = visual.TextStim(
                window, text='', color='white', height=30,
                wrapWidth=window.size[0] * 0.8, units='pix', autoLog=False,
            )
            rest_start = session_clock.getTime()
            while True:
                remaining = max(0, math.ceil(duration_seconds - (session_clock.getTime() - rest_start)))
                if remaining:
                    rest_text.text = (
                        'You have a 2-minute rest break.\n\n'
                        f'{remaining // 60}:{remaining % 60:02d} remaining.\n\n'
                        'Press ESCAPE to stop.'
                    )
                else:
                    rest_text.text = 'Rest break complete.\n\nPress SPACE to continue. Press ESCAPE to stop.'
                rest_text.draw()
                window.flip()
                presses = kb.getKeys(keyList=['space', 'escape'], waitRelease=False, clear=True)
                if any(key.name == 'escape' for key in presses):
                    return False
                if remaining == 0 and any(key.name == 'space' for key in presses):
                    return True

        aborted = False
        for block_index, block in enumerate(block_order):
            if not continuation(
                f"Block {block_index + 1} of {len(block_order)}: {BLOCK_LABELS[block]}\n"
                f'Your target group is {BLOCK_LABELS[block].lower()}. Press the matching '
                'numpad key when you see one.'
            ):
                aborted = True
                break
            for trial in sorted(trials_by_block[block]):
                trial_events = [
                    dict(row) for row in rows
                    if row['block'] == block and row['trial'] == trial
                ]
                trial_key_start = len(key_rows)
                current_trial_events = trial_events
                trial_start = session_clock.getTime()
                trial_visuals = [row for row in trial_events if row['event_type'] == 'visual']
                trial_targets = [row for row in trial_visuals if row['role'] in TARGET_ROLES]
                for row in trial_events:
                    row.update({
                        'runtime_planned_onset': trial_start + row['trial_onset'],
                        'actual_onset': '', 'onset_deviation': '',
                        'audio_requested_session_time': '',
                        'audio_requested_ptb_time': '', 'audio_backend_start_ptb_time': '',
                        'audio_backend_start_session_time': '', 'audio_timing_source': '',
                        'realized_soa_seconds': '', 'soa_error_seconds': '',
                        'response_status': 'pending' if row['role'] in TARGET_ROLES and row['event_type'] == 'visual' else '',
                        'response_correct': '',
                        'response_key': '', 'response_session_time': '',
                        'rt_from_actual_onset': '', 'rt_from_planned_onset': '',
                        'timing_flags': '', '_actual_onset': None,
                        '_planned_runtime': trial_start + row['trial_onset'],
                        '_audio_scheduled': False, '_audio_obj': None,
                    })
                    if row['event_type'] == 'sound':
                        row['_audio_obj'] = sound_cache[row['stimulus']]
                frame_intervals = []
                last_flip = None
                fixation_green_until = -1.0
                frame_count = 0
                trial_end_target = trial_start + TRIAL_DURATION

                while True:
                    response_end = max(
                        (event['_actual_onset'] + config.RESPONSE_WINDOW
                         for event in trial_visuals
                         if event['role'] in TARGET_ROLES and event['_actual_onset'] is not None),
                        default=trial_end_target,
                    )
                    if session_clock.getTime() >= max(trial_end_target, response_end):
                        break
                    now = session_clock.getTime()
                    next_flip_session = window.getFutureFlipTime(clock=session_clock)
                    next_flip_ptb = window.getFutureFlipTime(clock='ptb')

                    backgrounds[int(max(0.0, now - trial_start) / config.BG_UPDATE_RATE) % len(backgrounds)].draw()
                    fixation.lineColor = (
                        config.FIXATION_HIT_COLOR
                        if now < fixation_green_until else config.FIXATION_COLOR
                    )
                    fixation.draw()
                    if debug_overlay_enabled:
                        debug_overlay.text = (
                            f'{args.pid} | {BLOCK_LABELS[block]} | trial {trial}\n'
                            f'PT SOA: {pt_soa_by_block[block]}'
                        )
                        debug_overlay.draw()

                    visual_onsets_this_flip = []
                    for row in trial_events:
                        if row['event_type'] == 'sound' and not row['_audio_scheduled']:
                            sound_target = row['_planned_runtime']
                            lead = sound_target - next_flip_session
                            if lead <= 0.5:
                                # If a late frame consumed the requested lead, schedule
                                # at the next available PTB time and retain the deviation.
                                actual_request_session = max(sound_target, next_flip_session + 0.03)
                                requested_ptb = next_flip_ptb + (actual_request_session - next_flip_session)
                                row['_audio_obj'].play(when=requested_ptb)
                                row['_audio_scheduled'] = True
                                row['audio_requested_session_time'] = actual_request_session
                                row['audio_requested_ptb_time'] = requested_ptb
                                row['audio_timing_source'] = 'PTB scheduled playback'
                                if actual_request_session > sound_target + 1e-6:
                                    row['timing_flags'] = 'audio_schedule_late'

                        if row['event_type'] != 'visual':
                            continue
                        onset = row['_actual_onset']
                        planned = row['_planned_runtime']
                        if onset is None and next_flip_session >= planned:
                            time_from_onset = max(0.0, next_flip_session - planned)
                            visual_onsets_this_flip.append(row)
                        elif onset is not None:
                            time_from_onset = next_flip_session - onset
                        else:
                            continue
                        if 0 <= time_from_onset < VISUAL_DURATION:
                            stim = image_cache[row['stimulus']]
                            stim.pos = (float(row['x']), float(row['y']))
                            stim.opacity = (
                                0.02 if onset is None else planned_image_alpha(time_from_onset)
                            )
                            stim.draw()

                    flip_default = window.flip()
                    flip_session = (
                        convert_default_clock(session_clock, flip_default, logging)
                        if flip_default is not None else session_clock.getTime()
                    )
                    if last_flip is not None:
                        interval = flip_session - last_flip
                        frame_intervals.append(interval)
                    last_flip = flip_session
                    frame_count += 1
                    for row in visual_onsets_this_flip:
                        if row['_actual_onset'] is None:
                            row['_actual_onset'] = flip_session
                            row['actual_onset'] = flip_session
                            row['onset_deviation'] = flip_session - row['_planned_runtime']
                            if abs(row['onset_deviation']) > 1e-9:
                                row['timing_flags'] = 'visual_onset_deviation'
                            if row['role'] in TARGET_ROLES:
                                for other in trial_visuals:
                                    if (other is row or other['role'] not in TARGET_ROLES
                                            or other['_actual_onset'] is None):
                                        continue
                                    overlap_start = max(row['_actual_onset'], other['_actual_onset'])
                                    overlap_end = min(
                                        row['_actual_onset'] + config.RESPONSE_WINDOW,
                                        other['_actual_onset'] + config.RESPONSE_WINDOW,
                                    )
                                    if overlap_start < overlap_end:
                                        for target in (row, other):
                                            target['timing_flags'] = ';'.join(filter(None, [
                                                target['timing_flags'],
                                                'actual_response_windows_overlap',
                                            ]))

                    for row in trial_events:
                        if row['event_type'] == 'sound' and row['_audio_scheduled'] and not row['audio_backend_start_ptb_time']:
                            reported_ptb = backend_start_time(
                                row['_audio_obj'], float(row['audio_requested_ptb_time']),
                            )
                            if reported_ptb is not None:
                                metadata['audio_start_source'] = AUDIO_START_SOURCE
                                row['audio_backend_start_ptb_time'] = reported_ptb
                                row['audio_backend_start_session_time'] = ptb_to_session(
                                    reported_ptb, session_clock.getLastResetTime(),
                                )
                                row['actual_onset'] = row['audio_backend_start_session_time']
                                row['onset_deviation'] = (
                                    row['audio_backend_start_session_time'] - row['_planned_runtime']
                                )
                                if abs(row['onset_deviation']) > 1e-6:
                                    row['timing_flags'] = ';'.join(filter(None, [
                                        row['timing_flags'], 'audio_playback_deviation',
                                    ]))
                                row['audio_timing_source'] = 'PTB backend-reported startTime'

                    presses = kb.getKeys(waitRelease=False, clear=True)
                    for press in presses:
                        if press.name == 'escape':
                            key_rows.append({
                                'session_time': float(press.rt), 'key': press.name,
                                'corner': '', 'classification': 'abort',
                                'matched_event_ids': '', 'target_matches': '',
                                'correct': '', 'response_window_overlap': False,
                                'block': block, 'trial': trial,
                            })
                            aborted = True
                            break
                        key_time = float(press.rt)
                        key_row, chosen = classify_press(
                            press.name, KEY_TO_CORNER.get(press.name), key_time,
                            trial_targets, config.RESPONSE_WINDOW,
                        )
                        key_row.update({'block': block, 'trial': trial})
                        key_rows.append(key_row)
                        if key_row['response_window_overlap']:
                            for event in trial_targets:
                                if event['event_id'] in key_row['matched_event_ids'].split('|'):
                                    event['timing_flags'] = ';'.join(filter(None, [
                                        event['timing_flags'], 'actual_response_windows_overlap',
                                    ]))
                        if chosen is not None:
                            chosen['response_status'] = 'hit'
                            chosen['response_correct'] = True
                            chosen['response_key'] = press.name
                            chosen['response_session_time'] = key_time
                            chosen['rt_from_actual_onset'] = key_row['rt_from_actual_onset']
                            chosen['rt_from_planned_onset'] = key_row['rt_from_planned_onset']
                            fixation_green_until = key_time + config.FIXATION_FLASH_DUR
                    if aborted:
                        break

                    for event in trial_targets:
                        if (event['response_status'] == 'pending'
                                and event['_actual_onset'] is not None
                                and session_clock.getTime() > event['_actual_onset'] + config.RESPONSE_WINDOW):
                            event['response_status'] = 'miss'
                            event['response_correct'] = False
                trial_complete = not aborted
                finalize_targets(trial_targets, trial_complete)
                audio_requested_only = resolve_trial_audio(trial_events, config.FADE_IN_DUR)
                trial_end = session_clock.getTime()
                long_frames = [
                    interval for interval in frame_intervals
                    if interval > (1.2 / display_refresh_hz)
                ]
                current_trial_row = {
                    'block': block, 'trial': trial,
                    'trial_start_session_time': trial_start,
                    'trial_end_session_time': trial_end,
                    'frame_count': frame_count,
                    'long_frame_count': len(long_frames),
                    'mean_frame_interval': statistics.fmean(frame_intervals) if frame_intervals else '',
                    'median_frame_interval': statistics.median(frame_intervals) if frame_intervals else '',
                    'max_frame_interval': max(frame_intervals, default=''),
                    'miss_count': sum(event['response_status'] == 'miss' for event in trial_targets),
                    'trial_complete': trial_complete,
                    'audio_requested_only_count': audio_requested_only,
                }
                trial_rows.append(current_trial_row)
                for row in trial_events:
                    row['trial_complete'] = trial_complete
                trial_keys = key_rows[trial_key_start:]
                for key_row in trial_keys:
                    key_row['trial_complete'] = trial_complete
                all_events.extend(trial_events)
                current_trial_events = None
                last_block, last_trial = block, trial
                save_session(session_dir, all_events, key_rows, trial_rows, metadata)
                trial_hits, trial_false_alarms = trial_feedback(trial_targets, trial_keys)
                if aborted or not continuation(
                    f'{BLOCK_LABELS[block]} — Trial {trial} complete.\n'
                    f'Correct hits: {trial_hits}\nFalse alarms: {trial_false_alarms} '
                    '(please minimize these).'
                ):
                    aborted = True
                    break
            if not aborted and block_index < len(block_order) - 1:
                aborted = not rest_break()
            if aborted:
                break

        metadata['completion_status'] = 'aborted' if aborted else 'completed'
        metadata['ended_utc'] = datetime.now(timezone.utc).isoformat()
        if session_dir is not None:
            metadata['server_sync'] = {'status': 'pending'}
            save_session(session_dir, all_events, key_rows, trial_rows, metadata)
            if not aborted:
                target_events = [
                    event for event in all_events
                    if event['event_type'] == 'visual' and event['role'] in TARGET_ROLES
                ]
                valid_hits = sum(event['response_status'] == 'hit' for event in target_events)
                false_alarms = session_false_alarms(key_rows)
                completion_text = visual.TextStim(
                    window, text=(
                        'Study complete — thank you!\n\n'
                        f'Participant: {args.pid}\n'
                        f'Target appearances: {len(target_events)}\n'
                        f'Valid hits: {valid_hits}\n'
                        f'False alarms: {false_alarms}\n\n'
                        f'Data saved in:\n{session_dir}\n\n'
                        'Press SPACE to finish.'
                    ), color='white', height=26,
                    wrapWidth=window.size[0] * 0.8, units='pix', autoLog=False,
                )
                while True:
                    completion_text.draw()
                    window.flip()
                    presses = kb.getKeys(keyList=['space'], waitRelease=False, clear=True)
                    if presses:
                        break
            # The participant has acknowledged the final screen; now push the
            # complete participant folder and verify its files on the lab share.
            sync_result = copy_participant_data_to_server(args.pid)
            metadata['server_sync'] = sync_result
            save_session(session_dir, all_events, key_rows, trial_rows, metadata)
            if sync_result['status'] == 'copied':
                remote_metadata = Path(sync_result['destination']) / session_dir.name / 'session_metadata.json'
                local_metadata = session_dir / 'session_metadata.json'
                try:
                    shutil.copyfile(local_metadata, remote_metadata)
                    if hashlib.sha256(local_metadata.read_bytes()).hexdigest() != hashlib.sha256(remote_metadata.read_bytes()).hexdigest():
                        raise OSError('session metadata checksum mismatch')
                except OSError as exc:
                    metadata['server_sync']['status'] = 'partial'
                    metadata['server_sync']['failures'].append(f'session_metadata.json: {exc}')
                    save_session(session_dir, all_events, key_rows, trial_rows, metadata)
                    print(f'⚠️ Server copy completed, but final metadata update failed: {exc}')
            if sync_result['status'] == 'copied':
                print(f"✅ Full participant folder copied and verified on server: {sync_result['destination']}")
            elif sync_result['status'] == 'local_only':
                print(f"⚠️ Participant data remains local at {session_dir}; no server was mounted at preflight.")
            else:
                print(f"⚠️ Server copy {sync_result['status']}; local data remains at {session_dir}.")
    finally:
        if session_dir is not None and current_trial_events is not None:
            # An error interrupted a trial: keep its rows marked trial_complete=False
            # (pending targets become 'incomplete') so they never count as misses.
            finalize_targets(
                [row for row in current_trial_events
                 if row['event_type'] == 'visual' and row['role'] in TARGET_ROLES],
                complete=False,
            )
            resolve_trial_audio(current_trial_events, config.FADE_IN_DUR)
            for row in current_trial_events + key_rows[trial_key_start:]:
                row['trial_complete'] = False
            all_events.extend(current_trial_events)
            trial_rows.append({
                'block': current_trial_events[0]['block'],
                'trial': current_trial_events[0]['trial'],
                'trial_complete': False,
            })
            current_trial_events = None
            metadata.setdefault('completion_status', 'aborted_or_error')
            metadata['ended_utc'] = datetime.now(timezone.utc).isoformat()
            save_session(session_dir, all_events, key_rows, trial_rows, metadata)
        Path(report_source).unlink(missing_ok=True)
        if window is not None:
            window.close()
        sounds_to_close = list(locals().get('sound_cache', {}).values())
        if locals().get('test_tone') is not None:
            sounds_to_close.append(test_tone)
        for sound_obj in sounds_to_close:
            try:
                sound_obj.stop()
                track = sound_obj.track
                if track is not None:
                    track.close()
            except Exception:
                pass
        try:
            shared_speaker.close()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description='Set up and run the AV attention experiment.')
    parser.add_argument('pid', help='Reserved participant ID, for example participant_01.')
    args = parser.parse_args()
    if (not args.pid.startswith('participant_') or Path(args.pid).name != args.pid
            or args.pid in {'.', '..'}):
        parser.error('PID must use the form participant_01.')
    try:
        run(args)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f'Experiment could not start or finish: {exc}\n')


if __name__ == '__main__':
    main()
