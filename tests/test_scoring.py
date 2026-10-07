from scoring import (
    classify_press, finalize_targets, inter_trial_row, session_false_alarms,
    trial_feedback, trial_summary,
)

WINDOW = 1.5


def target(event_id, corner, onset, status='pending'):
    return {
        'event_id': event_id, 'corner': corner, '_actual_onset': onset,
        '_planned_runtime': onset, 'response_status': status, 'timing_flags': '',
    }


def test_hit_inside_window_matching_corner():
    row, chosen = classify_press('num_5', 'top_right', 10.4, [target('a', 'top_right', 10.0)], WINDOW)
    assert chosen['event_id'] == 'a'
    assert row['classification'] == 'hit' and row['correct'] is True
    assert abs(row['rt_from_actual_onset'] - 0.4) < 1e-9


def test_wrong_corner_is_false_alarm():
    row, chosen = classify_press('num_4', 'top_left', 10.4, [target('a', 'top_right', 10.0)], WINDOW)
    assert chosen is None and row['classification'] == 'false_alarm'
    assert row['matched_event_ids'] == 'a' and row['target_matches'] == ''


def test_duplicate_press_after_hit_is_false_alarm():
    row, chosen = classify_press('num_5', 'top_right', 10.6, [target('a', 'top_right', 10.0, 'hit')], WINDOW)
    assert chosen is None and row['classification'] == 'false_alarm'


def test_no_active_target_is_false_alarm():
    targets = [target('a', 'top_right', 10.0), target('b', 'top_right', None)]
    row, chosen = classify_press('num_5', 'top_right', 11.6, targets, WINDOW)
    assert chosen is None and row['classification'] == 'false_alarm' and row['matched_event_ids'] == ''


def test_non_response_key_matches_nothing():
    row, chosen = classify_press('space', None, 10.2, [target('a', 'top_right', 10.0)], WINDOW)
    assert chosen is None and row['classification'] == 'false_alarm' and row['matched_event_ids'] == ''


def test_overlap_chooses_earliest_pending():
    targets = [target('late', 'top_right', 10.5), target('early', 'top_right', 10.0)]
    row, chosen = classify_press('num_5', 'top_right', 10.8, targets, WINDOW)
    assert chosen['event_id'] == 'early' and row['response_window_overlap'] is True


def test_inter_trial_press_keeps_trial_and_is_not_a_false_alarm():
    row = inter_trial_row('num_5', 'top_right', 30.0, 'animate', 3)
    assert row['classification'] == 'inter_trial' and (row['block'], row['trial']) == ('animate', 3)
    assert session_false_alarms([row]) == 0


def test_aborted_trial_targets_are_incomplete_not_miss():
    targets = [target('shown', 'top_right', 10.0), target('unshown', 'top_left', None),
               target('missed', 'bottom_left', 5.0, 'miss')]
    finalize_targets(targets, complete=False)
    assert [t['response_status'] for t in targets] == ['incomplete', 'not_presented', 'miss']


def test_completed_trial_pending_target_becomes_miss():
    targets = [target('shown', 'top_right', 10.0)]
    finalize_targets(targets, complete=True)
    assert targets[0]['response_status'] == 'miss'


def test_summaries_exclude_incomplete_trials():
    trials = [{'miss_count': 2, 'frame_count': 10, 'trial_complete': True},
              {'miss_count': 5, 'frame_count': 4, 'trial_complete': False}]
    assert trial_summary(trials) == {
        'trial_count': 1, 'miss_count': 2, 'long_frame_count': 0, 'frame_count': 10,
        'audio_requested_only_count': 0,
    }
    keys = [{'classification': 'false_alarm', 'trial_complete': True},
            {'classification': 'false_alarm', 'trial_complete': False}]
    assert session_false_alarms(keys) == 1


def test_trial_feedback_from_memory():
    targets = [target('a', 'top_right', 1.0, 'hit'), target('b', 'top_left', 2.0, 'miss')]
    keys = [{'classification': 'hit'}, {'classification': 'false_alarm'}, {'classification': 'abort'}]
    assert trial_feedback(targets, keys) == (1, 1)
