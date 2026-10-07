"""Pure response scoring shared by the runner and unit tests (no PsychoPy).

Targets are runtime visual rows with at least event_id, corner, _actual_onset
(None until drawn) and response_status ('pending' until scored).
"""

from __future__ import annotations


def classify_press(key_name, corner, key_time, targets, response_window):
    """Score one in-trial keypress; return (key_row_fields, chosen_target_or_None).

    A press is a hit only for a pending target in the pressed corner whose
    response window contains the press. Wrong corner, a repeat press on an
    already-hit target, a press with no active target, and non-numpad keys are
    false alarms. Targets are not modified; the caller applies the hit.
    """
    active = [
        target for target in targets
        if corner and target['_actual_onset'] is not None
        and target['_actual_onset'] <= key_time <= target['_actual_onset'] + response_window
    ]
    matching = [
        target for target in active
        if target['corner'] == corner and target['response_status'] == 'pending'
    ]
    chosen = min(matching, key=lambda target: target['_actual_onset']) if matching else None
    row = {
        'session_time': key_time, 'key': key_name, 'corner': corner or '',
        'classification': 'hit' if chosen else 'false_alarm',
        'matched_event_ids': '|'.join(target['event_id'] for target in active),
        'target_matches': '|'.join(target['event_id'] for target in matching),
        'correct': chosen is not None,
        'response_window_overlap': len(active) > 1,
        'associated_event_id': chosen['event_id'] if chosen else '',
        'rt_from_actual_onset': key_time - chosen['_actual_onset'] if chosen else '',
        'rt_from_planned_onset': key_time - chosen['_planned_runtime'] if chosen else '',
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
        'long_frame_count': sum(int(row.get('long_frame_count', 0) or 0) for row in complete),
        'frame_count': sum(int(row.get('frame_count', 0) or 0) for row in complete),
    }
