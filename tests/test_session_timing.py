import json

import pytest

import config

# session_timing.py and capacity_sweep.py are analysis-only tools. They ship on the
# feat/trial-timing-harder branch and are deliberately not in this tree, so skip this
# module rather than fail collection when they are absent.
session_timing = pytest.importorskip(
    'session_timing', reason='analysis-only module, kept on feat/trial-timing-harder'
)
capacity_sweep = pytest.importorskip(
    'capacity_sweep', reason='analysis-only module, kept on feat/trial-timing-harder'
)
BASE = capacity_sweep.BASE
SCENARIOS = capacity_sweep.SCENARIOS
_target_counts = capacity_sweep._target_counts
_target_prevalence = capacity_sweep._target_prevalence
_visual_duration = capacity_sweep._visual_duration
npd_for_prevalence = capacity_sweep.npd_for_prevalence


def test_trials_per_block_matches_the_generator():
    # slotting_key builds one trial list of PT_COUNT_PER_BLOCK x TRIALS_PER_PT entries.
    assert session_timing.trials_per_block() == (
        config.PT_COUNT_PER_BLOCK * config.TRIALS_PER_PT
    )


def test_block_count_is_one_per_category():
    assert session_timing.block_count() == len(config.BLOCK_LABELS) == 2


def test_breakdown_is_the_sum_of_its_components():
    seconds = {
        'pre_task_seconds': 60.0, 'practice_seconds': 30.0,
        'continuation_seconds': 2.0, 'break_seconds': 30.0, 'completion_seconds': 20.0,
    }
    breakdown = session_timing.duration_breakdown(
        trials_per_block_count=4, **seconds,
    )
    trials = session_timing.trials_per_block() * 2
    # 8 trials today: trials, screens after every trial plus one per block, one break.
    assert trials == 8
    expected = 60 + 30 + trials * config.TRIAL_DURATION + (trials + 2) * 2.0 + 30 + 20
    assert session_timing.session_duration(breakdown) == pytest.approx(expected)
    assert sum(1 for label, _ in breakdown if 'Feedback screens' in label) == 1
    assert sum(1 for label, _ in breakdown if 'Breaks' in label) == 1


def test_break_count_defaults_to_one_between_blocks():
    assert session_timing.break_count(8, 2) == 1
    assert session_timing.break_count(100, 2, break_every_trials=None) == 1


def test_break_count_inside_the_trial_loop_never_ends_on_the_last_trial():
    # 16 trials with a break every 8: one at 8, none after the final trial.
    assert session_timing.break_count(16, 2, break_every_trials=8) == 1
    assert session_timing.break_count(32, 2, break_every_trials=8) == 3
    assert session_timing.break_count(9, 2, break_every_trials=4) == 2


def test_continuation_screens_cover_every_trial_and_every_block():
    assert session_timing.continuation_screens(8, 2) == 10
    assert session_timing.continuation_screens(100, 2) == 102


def test_trial_seconds_uses_two_buffers_around_the_content_window():
    assert session_timing.trial_seconds() == config.TRIAL_DURATION
    assert session_timing.trial_seconds(20.0) == 2 * config.TRIAL_BUFFER_DUR + 20.0


def test_trials_for_duration_lands_within_half_a_quantization_step():
    # Trials per block moves in steps of PT_COUNT_PER_BLOCK, so reachable session
    # lengths are quantized; the closest candidate is never more than half a step off.
    solution = session_timing.trials_for_duration(2700.0)
    chosen = session_timing.closest_candidate(solution)
    assert abs(chosen['difference_seconds']) <= solution['step_seconds'] / 2
    assert solution['step_seconds'] == pytest.approx(
        config.PT_COUNT_PER_BLOCK * 2 * (config.TRIAL_DURATION + 2.0)
    )
    assert chosen['trials_total'] == chosen['trials_per_block'] * 2


def test_solved_trial_counts_are_multiples_of_pt_count_per_block():
    solution = session_timing.trials_for_duration(2700.0)
    assert solution['granularity'] == config.PT_COUNT_PER_BLOCK
    for candidate in solution['candidates']:
        assert candidate['trials_per_block'] % config.PT_COUNT_PER_BLOCK == 0
        assert candidate['trials_per_pt'] == (
            candidate['trials_per_block'] // config.PT_COUNT_PER_BLOCK
        )


def test_longer_targets_reduce_the_trial_count():
    short = session_timing.closest_candidate(session_timing.trials_for_duration(2700.0))
    long = session_timing.closest_candidate(
        session_timing.trials_for_duration(2700.0, content_seconds=30.0)
    )
    assert long['trials_per_block'] < short['trials_per_block']


def test_a_45_minute_target_needs_far_more_than_the_pilot_trial_count():
    report = session_timing.summary(2700.0)
    assert report['config_trials_per_block'] == 4
    assert report['config_minutes'] < 10.0
    assert report['chosen']['trials_per_block'] > 40


def test_target_cadence_sets_content_and_trial_length():
    rows = session_timing.cadence_table(
        target_seconds=2700.0, targets_options=[12], cadences=[2.5],
    )
    assert len(rows) == 1
    row = rows[0]
    assert row['content_seconds'] == 30.0
    assert row['trial_seconds'] == 2 * config.TRIAL_BUFFER_DUR + 30.0
    assert row['targets_total_mean'] == 12 * row['trials_total']


def test_trial_content_stats_uses_the_configured_ranges():
    stats = session_timing.trial_content_stats(
        100, pt_range=(3, 4), npt_range=(9, 10),
        pd_range=(3, 5), npd_range=(20, 28), content_seconds=20.0,
    )
    assert stats['targets_per_trial_min'] == 12
    assert stats['targets_per_trial_max'] == 14
    assert stats['targets_total_mean'] == pytest.approx(13 * 100)
    # 13 targets in a 20 s window is one every 20/13 s.
    assert stats['mean_target_interval_seconds'] == pytest.approx(20 / 13)


def test_unsupported_granularity_is_rejected():
    with pytest.raises(ValueError, match='step must be a positive'):
        session_timing.trials_for_duration(2700.0, step=0)


def test_calibration_reads_measured_screen_times(tmp_path):
    participant = tmp_path / 'participant_01'
    session = participant / 'session_01'
    session.mkdir(parents=True)
    (participant / 'preflight_report.txt').write_text(
        'measured_at=2026-10-26T20:00:00+00:00\nparticipant_id=participant_01\n'
    )
    (session / 'session_metadata.json').write_text(json.dumps({
        'started_utc': '2026-10-26T20:02:00+00:00',
        'completion_status': 'completed',
        'practice': {'duration_seconds': 20.0},
        'breaks': [{'elapsed_seconds': 5.0}],
    }))
    session.joinpath('trial_log.csv').write_text(
        'block,trial,trial_complete,trial_start_session_time,trial_end_session_time\n'
        'animate,1,True,0.0,24.0\n'
        'animate,2,True,26.0,50.0\n'
        'inanimate,1,True,80.0,104.0\n'
    )
    report = session_timing.calibrate(tmp_path)
    assert report['sessions'] == 1
    detail = report['sessions_detail'][0]
    # 2 minutes of pre-task screens minus the 20 s practice round.
    assert detail['pre_task_seconds'] == pytest.approx(100.0)
    # Gaps between blocks are excluded from the within-block trial gaps.
    assert detail['trial_gaps_seconds'] == [pytest.approx(2.0)]
    assert report['medians']['continuation_seconds'] == pytest.approx(2.0)
    assert report['within_block_trial_gaps']['maximum_seconds'] == pytest.approx(2.0)


def test_calibration_ignores_folders_without_metadata(tmp_path):
    (tmp_path / 'participant_01').mkdir()
    assert session_timing.calibrate(tmp_path)['sessions'] == 0


def test_every_scenario_states_the_full_config_it_tests():
    # A row is only readable on its own if the patch carries every lever, so a
    # scenario can never silently inherit a value from another scenario.
    for name, item in SCENARIOS.items():
        assert set(BASE) <= set(item['patch']), name
        assert item['why'], name
        low, high = _target_counts(item['patch'])
        assert 0 < low <= high, name
        assert _visual_duration(item['patch']) > 0, name


def test_target_prevalence_matches_the_pilot_ratio():
    assert _target_prevalence(BASE) == pytest.approx(8.0 / 36.0)


def test_npd_for_prevalence_reproduces_the_shipped_ranges():
    # Today's config: 8 targets among 36 images = 22%, with PD averaging 4.
    assert npd_for_prevalence(8, 0.222, 4) == pytest.approx(24, abs=0.5)
    # Holding 22% while targets rise to 13 needs NPD ~41, far above the shipped 24.
    assert npd_for_prevalence(13, 0.222, 4) == pytest.approx(41.5, abs=0.5)


def test_npd_for_prevalence_needs_about_three_and_a_half_times_the_targets():
    # At a fixed 22% prevalence, each extra target costs ~3.5 extra distractors.
    per_target = (
        npd_for_prevalence(14, 0.222, 4) - npd_for_prevalence(13, 0.222, 4)
    )
    assert per_target == pytest.approx((1 - 0.222) / 0.222, abs=0.01)
    assert per_target > 3


def test_npd_for_prevalence_rejects_impossible_inputs():
    for bad in (0.0, 1.0, -0.1, 1.5):
        with pytest.raises(ValueError, match='prevalence'):
            npd_for_prevalence(10, bad, 4)
    with pytest.raises(ValueError, match='nonnegative'):
        npd_for_prevalence(-1, 0.22, 4)


def test_harder_target_scenarios_raise_prevalence_unless_distractors_scale():
    # More targets with an unchanged distractor count also makes targets more
    # frequent, which on its own tends to reduce misses; only the "dense"
    # scenario holds prevalence near the pilot value.
    assert _target_prevalence(SCENARIOS['targets_12_14']['patch']) > _target_prevalence(BASE)
    dense = _target_prevalence(SCENARIOS['content_30s_targets_12_14_dense']['patch'])
    assert dense == pytest.approx(_target_prevalence(BASE), abs=0.02)


def test_probed_scenarios_span_the_target_counts_the_professor_asked_for():
    counts = {name: _target_counts(item['patch']) for name, item in SCENARIOS.items()}
    assert counts['baseline'] == (
        config.TRIAL_PT_RANGE[0] + config.TRIAL_NPT_RANGE[0],
        config.TRIAL_PT_RANGE[1] + config.TRIAL_NPT_RANGE[1],
    )
    assert any(low >= 11 for low, _ in counts.values())
    assert max(high for _, high in counts.values()) >= 16
