"""Run a participant from an immutable timeline_key.csv plan."""

from __future__ import annotations

import argparse
import inspect
import json
import math
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import config
from config import BLOCK_LABELS, TARGET_ROLES
from participant_setup import create_participant_plan, derive_rng
import screens
from session_io import load_timeline, operator_warn, save_session, sha256_file, sync_participant
from audio_ptb import (
    AUDIO_START_SOURCE, assign_sound_slots, backend_start_time, open_ptb_speaker, ptb_to_session, resolve_trial_audio,
)
from scoring import finalize_targets, session_false_alarms, trial_feedback
from trial_runner import run_trial


ROOT = Path(os.environ.get('AV_STUDY_DIR', Path(__file__).resolve().parent)).resolve()


def _finite_number(value, label):
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{label} must be numeric, got {value!r}.') from exc
    if not math.isfinite(number):
        raise ValueError(f'{label} must be finite.')
    return number


def make_backgrounds(window, visual, np, Image, rng):
    """Build cached Fourier phase-randomized backgrounds before the task."""
    source_path = ROOT / config.BG_SOURCE_FILE
    image = np.asarray(Image.open(source_path).convert('L'), dtype=np.float32)
    spectrum = np.fft.fftshift(np.fft.fft2(image))
    magnitude = np.abs(spectrum)
    backgrounds = []
    for _ in range(20):
        phase = rng.uniform(-np.pi, np.pi, spectrum.shape)
        frame = np.real(np.fft.ifft2(np.fft.ifftshift(magnitude * np.exp(1j * phase))))
        low, high = float(frame.min()), float(frame.max())
        normalized = np.zeros_like(frame) if high <= low else (frame - low) / (high - low)
        backgrounds.append(visual.ImageStim(
            window, image=normalized * 2.0 - 1.0, size=window.size,
            units='pix', opacity=config.BG_NOISE_OPACITY, autoLog=False,
        ))
    return backgrounds


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


def run(args):
    pid_dir = ROOT / 'data' / args.pid
    report_source = os.environ.get('AV_STUDY_PREFLIGHT_REPORT')
    if not report_source or not Path(report_source).is_file():
        raise FileNotFoundError('Preflight report is missing. Start the experiment from preflight.sh.')
    report_text = Path(report_source).read_text(encoding='utf-8')
    preflight_report = _parse_preflight_report(report_text)
    if preflight_report.get('participant_id') != args.pid:
        raise ValueError('Preflight report participant ID does not match the requested participant.')
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
    clock_offset = float(
        ptb_to_session(ptb.GetSecs(), session_clock.getLastResetTime()) - session_clock.getTime()
    )
    if abs(clock_offset) > 0.005:
        raise RuntimeError(
            f'PsychoPy Clock and PTB GetSecs do not share a time base (offset {clock_offset:.6f} s); '
            'audio timestamps cannot be converted to session time.'
        )
    shared_speaker, speaker_profile = open_ptb_speaker(ptb_audio, SpeakerDevice)

    window = None
    session_dir = None
    kb = None
    all_events = []
    key_rows = []
    trial_rows = []
    current_trial_events = None
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
        'display_refresh_hz_xrandr': display_refresh_hz,
        'audio_onset_flag_threshold_seconds': config.AUDIO_ONSET_FLAG_THRESHOLD,
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
        window_size = tuple(int(value) for value in window.size)
        if window_size != tuple(config.WINDOW_SIZE):
            raise RuntimeError(
                f'Window opened at {window_size}, but config.WINDOW_SIZE is {tuple(config.WINDOW_SIZE)}. '
                'Set the experiment display to that resolution.'
            )
        measured_refresh_hz = window.getActualFrameRate(
            nIdentical=20, nMaxFrames=60, nWarmUpFrames=10, threshold=1,
        )
        if not measured_refresh_hz:
            raise RuntimeError('Could not measure a stable display refresh rate with getActualFrameRate().')
        measured_refresh_hz = float(measured_refresh_hz)
        frame_period = 1.0 / measured_refresh_hz
        metadata.update({
            'window_size': list(window_size),
            'display_refresh_hz': measured_refresh_hz,
            'display_refresh_rate_source': 'window.getActualFrameRate (~0.5 s of flips)',
            'visual_onset_flag_threshold_seconds': float(config.VISUAL_ONSET_FLAG_FRAMES * frame_period),
            'long_frame_threshold_seconds': float(1.2 * frame_period),
            'display_refresh_differs_from_xrandr': bool(
                abs(measured_refresh_hz - display_refresh_hz) > 1.0
            ),
        })
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
        kb = keyboard.Keyboard(clock=session_clock)
        kb.clearEvents()

        if not screens.numpad_check(window, kb, visual):
            return

        if not screens.sound_check(window, kb, visual, test_tone):
            return
        metadata['sound_check'] = {
            'status': 'confirmed', 'participant_response': 'heard',
            'tone_hz': 440, 'tone_duration_seconds': 0.8,
        }
        test_tone_start = backend_start_time(test_tone, requested_ptb=0.0)
        metadata['sound_check']['backend_start_ptb_time'] = test_tone_start

        # The participant ID and plan are consumed only after both hardware checks pass.
        timeline_path, plan_snapshot = create_participant_plan(ROOT / 'data', args.pid)
        # Earlier warnings wait until here: creating pid_dir sooner would consume the ID.
        if metadata['display_refresh_differs_from_xrandr']:
            operator_warn(pid_dir, f'⚠️ Measured refresh {measured_refresh_hz:.2f} Hz differs from xrandr '
                          f'{display_refresh_hz:.2f} Hz by more than 1 Hz.')
        if test_tone_start is None:
            operator_warn(pid_dir, f'⚠️ PTB reported no audio start time ({AUDIO_START_SOURCE}) for the sound check; '
                          "audio timing will fall back to requested times (audio_timing_source='requested_only').")
        shutil.copyfile(report_source, pid_dir / 'preflight_report.txt')
        Path(report_source).unlink(missing_ok=True)
        participant_metadata_path = pid_dir / 'participant_metadata.json'
        participant_metadata = json.loads(participant_metadata_path.read_text(encoding='utf-8'))
        rows, assets, block_order, trials_by_block = load_timeline(
            timeline_path, participant_metadata, ROOT,
        )
        metadata.update({
            'timeline_path': str(timeline_path),
            'timeline_sha256': sha256_file(timeline_path),
            'timeline_sha256_at_generation': participant_metadata['timeline_sha256'],
            'timeline_sha256_verified': True,
            'config_matches_plan_snapshot': True,
            'timeline_order': block_order,
            'seed': plan_snapshot['seed'],
            'participant_metadata_file': participant_metadata_path.name,
            'participant_metadata_sha256': sha256_file(participant_metadata_path),
            'preflight_report_file': 'preflight_report.txt',
            'background_rng': f"numpy default_rng({config.BG_SEED})",
        })
        backgrounds = make_backgrounds(
            window, visual, np, Image,
            np.random.default_rng(config.BG_SEED),
        )
        image_cache = {
            stimulus: visual.ImageStim(
                window, image=str(path), size=config.IMAGE_SIZE,
                units='pix', autoLog=False,
            )
            for stimulus, path in assets['images'].items()
        }
        sound_pool = {
            stimulus: [
                sound.Sound(
                    str(path), speaker=shared_speaker,
                    stereo=True, preBuffer=-1, autoLog=False,
                )
                for _ in range(config.SOUND_POOL_SIZE)
            ]
            for stimulus, path in assets['sounds'].items()
        }
        if not sound_pool:
            raise RuntimeError('Timeline has no sounds.')
        sound_rows = [row for row in rows if row['event_type'] == 'sound']
        slots = assign_sound_slots(sound_rows, config.SOUND_POOL_SIZE)
        for row in sound_rows:
            row['sound_slot'] = slots[row['event_id']]

        debug_lines, pt_soa_by_block = screens.plan_summary(args.pid, rows, block_order, trials_by_block)
        debug_overlay_enabled = os.environ.get('AV_STUDY_DEBUG_OVERLAY', 'false').lower() == 'true'
        if debug_overlay_enabled and not screens.operator_screen(window, kb, visual, debug_lines):
            return
        if not screens.instructions(window, kb, visual):
            return

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
            return screens.continuation(window, kb, window_text, message, key_rows, last_block, last_trial)

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
                trial_keys = []
                current_trial_events = trial_events
                trial_events, trial_keys, trial_row, aborted = run_trial(
                    window=window, kb=kb, session_clock=session_clock, logging=logging,
                    block=block, trial=trial, trial_events=trial_events, trial_keys=trial_keys,
                    sound_pool=sound_pool, image_cache=image_cache, backgrounds=backgrounds,
                    fixation=fixation, frame_period=frame_period, metadata=metadata,
                    overlay=(debug_overlay, (
                        f'{args.pid} | {BLOCK_LABELS[block]} | trial {trial}\n'
                        f'PT SOA: {pt_soa_by_block[block]}'
                    )) if debug_overlay_enabled else None,
                )
                trial_complete = trial_row['trial_complete']
                trial_targets = [
                    row for row in trial_events
                    if row['event_type'] == 'visual' and row['role'] in TARGET_ROLES
                ]
                trial_rows.append(trial_row)
                for row in trial_events:
                    row['trial_complete'] = trial_complete
                for key_row in trial_keys:
                    key_row['trial_complete'] = trial_complete
                key_rows.extend(trial_keys)
                all_events.extend(trial_events)
                current_trial_events = None
                last_block, last_trial = block, trial
                save_session(session_dir, all_events, key_rows, trial_rows, metadata)
                trial_hits, trial_false_alarms = trial_feedback(trial_targets, trial_keys)
                if aborted or not continuation(
                    f'{BLOCK_LABELS[block]} — Trial {trial} complete.\n'
                    f'Correct hits: {trial_hits}\n'
                    f'Misses: {trial_row["miss_count"]}\n'
                    f'False alarms: {trial_false_alarms} (please minimize these).'
                ):
                    aborted = True
                    break
            if not aborted and block_index < len(block_order) - 1:
                rest_start_time = session_clock.getTime()
                break_skipped = screens.rest_break(window, kb, visual, session_clock)
                break_duration = session_clock.getTime() - rest_start_time
                metadata['break_skip_info'] = {
                    'break_number': block_index + 1,
                    'break_duration_seconds': break_duration,
                    'break_was_skipped': break_skipped,
                    'break_duration_seconds_full': 120,  # 2 minutes = 120 seconds
                }
                if not break_skipped:
                    aborted = not break_skipped
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
                        f'Misses: {sum(event["response_status"] == "miss" for event in target_events)}\n'
                        f'False alarms: {false_alarms}\n\n'
                        f'Data saved in:\n{session_dir}\n\n'
                        'Please inform the experiment lead that you have finished.'
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
            sync_participant(
                ROOT, args.pid, session_dir, metadata,
                lambda: save_session(session_dir, all_events, key_rows, trial_rows, metadata),
            )
    finally:
        if session_dir is not None and current_trial_events is not None:
            # An error interrupted a trial: keep its rows marked trial_complete=False
            # (pending targets become 'incomplete') so they never count as misses.
            finalize_targets(
                [row for row in current_trial_events
                 if row['event_type'] == 'visual' and row['role'] in TARGET_ROLES],
                complete=False,
            )
            resolve_trial_audio(current_trial_events, config.FADE_IN_DUR, complete=False)
            for row in current_trial_events + trial_keys:
                row['trial_complete'] = False
            key_rows.extend(trial_keys)
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
        sounds_to_close = [
            sound_obj for pool in locals().get('sound_pool', {}).values() for sound_obj in pool
        ]
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
