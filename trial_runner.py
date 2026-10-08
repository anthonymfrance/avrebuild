"""One trial's frame loop: drawing, PTB audio scheduling, keypress scoring.

PsychoPy objects are passed in; this module never imports PsychoPy.
"""

from __future__ import annotations

import statistics

import config
from audio_ptb import AUDIO_START_SOURCE, backend_start_time, ptb_to_session, resolve_trial_audio
from config import TARGET_ROLES, TRIAL_DURATION, VISUAL_DURATION
from scoring import classify_press, finalize_targets
from screens import KEY_TO_CORNER


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


def run_trial(
    *, window, kb, session_clock, logging, block, trial, trial_events, trial_keys,
    sound_pool, image_cache, backgrounds, fixation, overlay, frame_period, metadata,
):
    """Run one trial on prepared copies of its timeline rows.

    trial_events and trial_keys are filled in place so an interrupted trial
    can still be saved by the caller. overlay is (TextStim, text) or None.
    Returns (trial_events, trial_keys, trial_row, aborted).
    """
    aborted = False
    trial_start = float(session_clock.getTime())
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
            row['_audio_obj'] = sound_pool[row['stimulus']][row['sound_slot']]
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
        if float(session_clock.getTime()) >= max(trial_end_target, response_end):
            break
        now = float(session_clock.getTime())
        next_flip_session = float(window.getFutureFlipTime(clock=session_clock))
        next_flip_ptb = float(window.getFutureFlipTime(clock='ptb'))

        backgrounds[int(max(0.0, now - trial_start) / config.BG_UPDATE_RATE) % len(backgrounds)].draw()
        fixation.lineColor = (
            config.FIXATION_HIT_COLOR
            if now < fixation_green_until else config.FIXATION_COLOR
        )
        fixation.draw()
        if overlay is not None:
            overlay[0].text = overlay[1]
            overlay[0].draw()

        visual_onsets_this_flip = []
        for row in trial_events:
            if row['event_type'] == 'sound' and not row['_audio_scheduled']:
                sound_target = row['_planned_runtime']
                lead = sound_target - next_flip_session
                if bool(lead <= config.SOUND_SCHEDULE_LEAD):
                    # If a late frame consumed the requested lead, schedule
                    # at the next available PTB time and retain the deviation.
                    actual_request_session = max(sound_target, next_flip_session + 0.03)
                    requested_ptb = next_flip_ptb + (actual_request_session - next_flip_session)
                    row['_audio_obj'].play(when=requested_ptb)
                    row['_audio_scheduled'] = True
                    row['audio_requested_session_time'] = actual_request_session
                    row['audio_requested_ptb_time'] = requested_ptb
                    row['audio_timing_source'] = 'PTB scheduled playback'
                    if bool(actual_request_session > sound_target + 1e-6):
                        row['timing_flags'] = 'audio_schedule_late'

            if row['event_type'] != 'visual' or row['response_status'] == 'not_presented':
                continue
            onset = row['_actual_onset']
            planned = row['_planned_runtime']
            if onset is None and bool(next_flip_session >= planned):
                time_from_onset = max(0.0, next_flip_session - planned)
                if bool(time_from_onset >= VISUAL_DURATION):
                    # A stall skipped this visual's entire display period.
                    row['response_status'] = 'not_presented'
                    row['timing_flags'] = ';'.join(filter(None, [
                        row['timing_flags'], 'visual_stalled',
                    ]))
                    continue
                visual_onsets_this_flip.append(row)
            elif onset is not None:
                time_from_onset = next_flip_session - onset
            else:
                continue
            if bool(0 <= time_from_onset < VISUAL_DURATION):
                stim = image_cache[row['stimulus']]
                stim.pos = (float(row['x']), float(row['y']))
                stim.opacity = (
                    0.02 if onset is None else planned_image_alpha(time_from_onset)
                )
                stim.draw()

        flip_default = window.flip()
        flip_session = float(
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
                row['onset_deviation'] = float(flip_session - row['_planned_runtime'])
                if bool(abs(row['onset_deviation']) > config.VISUAL_ONSET_FLAG_FRAMES * frame_period):
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
                        if bool(overlap_start < overlap_end):
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
                    row['onset_deviation'] = float(
                        row['audio_backend_start_session_time'] - row['_planned_runtime']
                    )
                    if bool(abs(row['onset_deviation']) > config.AUDIO_ONSET_FLAG_THRESHOLD):
                        row['timing_flags'] = ';'.join(filter(None, [
                            row['timing_flags'], 'audio_playback_deviation',
                        ]))
                    row['audio_timing_source'] = 'PTB backend-reported startTime'

        presses = kb.getKeys(waitRelease=False, clear=True)
        for press in presses:
            if press.name == 'escape':
                trial_keys.append({
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
            trial_keys.append(key_row)
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
                    and bool(float(session_clock.getTime()) > event['_actual_onset'] + config.RESPONSE_WINDOW)):
                event['response_status'] = 'miss'
                event['response_correct'] = False
    trial_complete = not aborted
    finalize_targets(trial_targets, trial_complete)
    audio_requested_only = resolve_trial_audio(trial_events, config.FADE_IN_DUR, trial_complete)
    trial_end = float(session_clock.getTime())
    long_frames = [
        interval for interval in frame_intervals
        if bool(interval > 1.2 * frame_period)
    ]
    trial_row = {
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
    return trial_events, trial_keys, trial_row, aborted
