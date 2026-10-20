"""Pure response scoring shared by the runner and unit tests (no PsychoPy).

Targets are runtime visual rows with at least event_id, corner, _actual_onset
(None until drawn) and response_status ('pending' until scored).

Each target ends as one of:
  hit   first press in its corner within RESPONSE_WINDOW of its onset
  late  first press in its corner during the LATE_WINDOW after that
  miss  no press in its corner by the end of the late window
Each in-trial keypress is one of:
  hit / late   the press that decided a target's outcome
  repeat       another press in the same corner after the target was already
               answered, before its late window ends (a double tap or finger
               slip); logged only, never counted as a false alarm
  false_alarm  wrong corner, a press during a distractor, a press with no
               target on screen, or a same-corner press after the late window
  ignored_key  a key that is not a response key (for example SPACE); logged
               only, never scored, so a resting hand is not an error
A target's windows end early if the next image in its corner actually appears
first (only after a frame stall; the timeline keeps the corner empty), so a
press is always scored against what was on screen.
"""

from __future__ import annotations


def response_deadline(target, visuals, response_window, late_window):
    """End of a target's late window, or the next same-corner onset if earlier."""
    onset = target['_actual_onset']
    later_onsets = [
        visual['_actual_onset'] for visual in visuals
        if visual['corner'] == target['corner'] and visual['_actual_onset'] is not None
        and visual['_actual_onset'] > onset
    ]
    return min([onset + response_window + late_window, *later_onsets])


def classify_press(key_name, corner, key_time, targets, response_window, late_window=0.0, visuals=None):
    """Score one in-trial keypress; return (key_row_fields, chosen_target_or_None).

    chosen is the pending target this press decides (hit or late); repeats and
    false alarms return None. visuals (default: targets) are all drawn images,
    used to end a target's windows when the next image in its corner appears.
    Targets are not modified; the caller applies the result.
    """
    if not corner:
        # A key with no response corner (SPACE, letters, modifiers) is not a
        # response and must not be scored as a false alarm.
        return {
            'session_time': key_time, 'key': key_name, 'corner': '',
            'classification': 'ignored_key',
            'matched_event_ids': '', 'target_matches': '', 'correct': False,
            'response_window_overlap': False, 'associated_event_id': '',
            'rt_from_actual_onset': '', 'rt_from_planned_onset': '',
        }, None
    visuals = targets if visuals is None else visuals
    active = [
        target for target in targets
        if corner and target['_actual_onset'] is not None
        and target['_actual_onset'] <= key_time <= target['_actual_onset'] + response_window
    ]
    in_corner = [
        target for target in targets
        if corner and target['corner'] == corner and target['_actual_onset'] is not None
        and target['_actual_onset'] <= key_time
        <= response_deadline(target, visuals, response_window, late_window)
    ]
    pending = [target for target in in_corner if target['response_status'] == 'pending']
    matching = [t for t in pending if key_time <= t['_actual_onset'] + response_window]
    late = [t for t in pending if key_time > t['_actual_onset'] + response_window]
    repeats = [t for t in in_corner if t['response_status'] in ('hit', 'late')]
    by_onset = lambda target: target['_actual_onset']
    chosen = min(matching or late, key=by_onset, default=None)
    classification = (
        'hit' if matching else 'late' if late else 'repeat' if repeats else 'false_alarm'
    )
    associated = chosen or min(repeats, key=by_onset, default=None)
    row = {
        'session_time': key_time, 'key': key_name, 'corner': corner or '',
        'classification': classification,
        'matched_event_ids': '|'.join(target['event_id'] for target in active),
        'target_matches': '|'.join(target['event_id'] for target in matching),
        'correct': classification == 'hit',
        'response_window_overlap': bool(len(active) > 1),
        'associated_event_id': associated['event_id'] if associated else '',
        'rt_from_actual_onset': float(key_time - associated['_actual_onset']) if associated else '',
        'rt_from_planned_onset': float(key_time - associated['_planned_runtime']) if associated else '',
    }
    return row, chosen


def inter_trial_row(key_name, corner, key_time, block, trial):
    """A response key pressed on a between-trial or instruction screen."""
    return {
        'session_time': key_time, 'key': key_name, 'corner': corner or '',
        'classification': 'inter_trial', 'matched_event_ids': '',
        'target_matches': '', 'correct': '', 'response_window_overlap': False,
        'block': block, 'trial': trial,
    }


def finalize_targets(targets, complete):
    """Resolve still-pending targets in place once a trial ends or is aborted."""
    for target in targets:
        if target['response_status'] != 'pending':
            continue
        if target['_actual_onset'] is None:
            target['response_status'] = 'not_presented'
            flag = 'trial_ended_before_visual_onset' if complete else 'trial_aborted_before_visual_onset'
            target['timing_flags'] = ';'.join(filter(None, [target['timing_flags'], flag]))
        elif complete:
            target['response_status'] = 'miss'
            target['response_correct'] = False
        else:
            target['response_status'] = 'incomplete'


def trial_feedback(trial_targets, trial_keys):
    """Return (hits, false_alarms) for one trial from in-memory rows."""
    hits = sum(target['response_status'] == 'hit' for target in trial_targets)
    false_alarms = sum(key['classification'] == 'false_alarm' for key in trial_keys)
    return hits, false_alarms


def session_false_alarms(keys):
    """False alarms in completed trials; inter-trial presses are not counted."""
    return sum(
        key['classification'] == 'false_alarm' and key.get('trial_complete') is not False
        for key in keys
    )


def trial_summary(trials):
    """Session totals over completed trials only."""
    complete = [row for row in trials if row.get('trial_complete', True) is not False]
    return {
        'trial_count': len(complete),
        'miss_count': sum(int(row.get('miss_count', 0) or 0) for row in complete),
        'late_count': sum(int(row.get('late_count', 0) or 0) for row in complete),
        'long_frame_count': sum(int(row.get('long_frame_count', 0) or 0) for row in complete),
        'frame_count': sum(int(row.get('frame_count', 0) or 0) for row in complete),
        'audio_requested_only_count': sum(
            int(row.get('audio_requested_only_count', 0) or 0) for row in complete
        ),
    }
