from scoring import (
    classify_press, finalize_targets, inter_trial_row, response_deadline,
    session_false_alarms, trial_feedback, trial_summary,
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


def test_second_press_in_hit_window_is_repeat_not_false_alarm():
    row, chosen = classify_press('num_5', 'top_right', 10.6, [target('a', 'top_right', 10.0, 'hit')], WINDOW)
    assert chosen is None and row['classification'] == 'repeat' and row['associated_event_id'] == 'a'
    assert trial_feedback([], [row]) == (0, 0) and session_false_alarms([row]) == 0


def test_press_in_late_window_after_hit_or_late_is_repeat():
    for status in ('hit', 'late'):
        row, chosen = classify_press('num_5', 'top_right', 11.2, [target('a', 'top_right', 10.0, status)], 0.9, 0.5)
        assert chosen is None and row['classification'] == 'repeat'


def test_press_after_late_window_following_hit_is_false_alarm():
    row, _ = classify_press('num_5', 'top_right', 11.5, [target('a', 'top_right', 10.0, 'hit')], 0.9, 0.5)
    assert row['classification'] == 'false_alarm' and row['associated_event_id'] == ''


def test_next_same_corner_image_ends_stalled_targets_windows():
    stalled = target('a', 'top_right', 10.3)
    distractor = target('d', 'top_right', 11.4)
    visuals = [stalled, distractor]
    assert response_deadline(stalled, visuals, 0.9, 0.5) == 11.4
    assert classify_press('num_5', 'top_right', 11.3, [stalled], 0.9, 0.5, visuals)[0]['classification'] == 'late'
    row, chosen = classify_press('num_5', 'top_right', 11.6, [stalled], 0.9, 0.5, visuals)
    assert chosen is None and row['classification'] == 'false_alarm'
    stalled['response_status'] = 'hit'
    assert classify_press('num_5', 'top_right', 11.6, [stalled], 0.9, 0.5, visuals)[0]['classification'] == 'false_alarm'


def test_no_active_target_is_false_alarm():
    targets = [target('a', 'top_right', 10.0), target('b', 'top_right', None)]
    row, chosen = classify_press('num_5', 'top_right', 11.6, targets, WINDOW)
    assert chosen is None and row['classification'] == 'false_alarm' and row['matched_event_ids'] == ''


def test_press_in_late_window_is_late_not_hit():
    row, chosen = classify_press('num_5', 'top_right', 11.7, [target('a', 'top_right', 10.0)], WINDOW, 0.5)
    assert chosen['event_id'] == 'a' and row['classification'] == 'late' and row['correct'] is False
    assert abs(row['rt_from_actual_onset'] - 1.7) < 1e-9


def test_late_window_wrong_corner_and_after_late_window_are_false_alarms():
    targets = [target('a', 'top_right', 10.0)]
    assert classify_press('num_4', 'top_left', 11.7, targets, WINDOW, 0.5)[0]['classification'] == 'false_alarm'
    assert classify_press('num_5', 'top_right', 12.1, targets, WINDOW, 0.5)[0]['classification'] == 'false_alarm'


def test_non_response_key_is_ignored_not_a_false_alarm():
    row, chosen = classify_press('space', None, 10.2, [target('a', 'top_right', 10.0)], WINDOW)
    assert chosen is None and row['classification'] == 'ignored_key' and row['matched_event_ids'] == ''
    assert row['correct'] is False and row['associated_event_id'] == ''
    assert session_false_alarms([row]) == 0 and trial_feedback([], [row]) == (0, 0)


def test_overlapping_same_corner_targets_go_to_the_newer_one():
    targets = [target('second', 'top_right', 10.5), target('first', 'top_right', 10.0)]
    row, chosen = classify_press('num_5', 'top_right', 10.8, targets, WINDOW)
    assert chosen['event_id'] == 'second' and row['response_window_overlap'] is True


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
    trials = [{'miss_count': 2, 'late_count': 1, 'frame_count': 10, 'trial_complete': True},
              {'miss_count': 5, 'late_count': 3, 'frame_count': 4, 'trial_complete': False}]
    assert trial_summary(trials) == {
        'trial_count': 1, 'miss_count': 2, 'late_count': 1, 'long_frame_count': 0, 'frame_count': 10,
        'audio_requested_only_count': 0,
    }
    keys = [{'classification': 'false_alarm', 'trial_complete': True},
            {'classification': 'false_alarm', 'trial_complete': False}]
    assert session_false_alarms(keys) == 1


def test_trial_feedback_from_memory():
    targets = [target('a', 'top_right', 1.0, 'hit'), target('b', 'top_left', 2.0, 'miss')]
    keys = [{'classification': 'hit'}, {'classification': 'false_alarm'}, {'classification': 'abort'}]
    assert trial_feedback(targets, keys) == (1, 1)
