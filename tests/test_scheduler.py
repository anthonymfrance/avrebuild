import copy
import hashlib
import json

import pytest

import config
import participant_setup
import stimulus_split
import timeline_key
from plan_validator import validate_plan
from timeline_key import PlacementFailure

ORDER = ['animate', 'inanimate']


def plan_digest(slotting_rows, timeline):
    return hashlib.sha256(json.dumps([slotting_rows, timeline], sort_keys=True, default=str).encode()).hexdigest()


@pytest.fixture
def trials_per_pt(monkeypatch):
    def set_length(value):
        monkeypatch.setattr(stimulus_split, 'TRIALS_PER_PT', value)
        monkeypatch.setattr(config, 'TRIALS_PER_PT', value)
    return set_length


@pytest.fixture(scope='module')
def plan_100():
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(stimulus_split, 'TRIALS_PER_PT', 25)
        mp.setattr(config, 'TRIALS_PER_PT', 25)
        return participant_setup.build_plan(7, ORDER)


def test_eight_trial_plan_is_unchanged_from_before_the_scheduler_rework():
    # Plans the old scheduler placed in its first timeline attempt are byte-identical.
    _, slotting, timeline, _, _ = participant_setup.build_plan(7, ORDER)
    assert plan_digest(slotting, timeline) == '1908019b49c9f8512cffd7d05d84028ba65b4d447694df5ec7ef09903db033e6'


def test_hundred_trial_plan_is_complete_and_valid(plan_100):
    assignment, slotting, timeline, _, _ = plan_100
    assert validate_plan(assignment, slotting, timeline, trials_per_pt=25) == []
    visuals = [r for r in timeline if r['event_type'] == 'visual']
    for block, category in (('animate', stimulus_split.ANIMATE), ('inanimate', stimulus_split.INANIMATE)):
        trials = {r['trial'] for r in visuals if r['block'] == block}
        assert trials == set(range(1, 51))
        assert {r['stimulus'] for r in visuals if r['block'] == block and r['role'] in ('PT', 'NPT')} <= set(category)


def test_same_seed_reproduces_the_same_hundred_trial_plan(plan_100, trials_per_pt):
    trials_per_pt(25)
    _, slotting, timeline, _, _ = participant_setup.build_plan(7, ORDER)
    assert plan_digest(slotting, timeline) == plan_digest(plan_100[1], plan_100[2])


def test_validator_rejects_a_plan_checked_against_the_wrong_length(plan_100):
    assignment, slotting, timeline, _, _ = plan_100
    assert any('expected 1..48' in e for e in validate_plan(assignment, slotting, timeline, trials_per_pt=24))


def test_zero_trials_per_pt_cannot_build_a_plan(trials_per_pt):
    trials_per_pt(0)
    with pytest.raises(ValueError):
        participant_setup.build_plan(7, ORDER)


def test_validator_rejects_a_trial_moved_to_the_other_pt(plan_100):
    assignment = plan_100[0]
    slotting, timeline = copy.deepcopy(plan_100[1:3])
    first_pt, other_pt = assignment['animate']['PT']
    trial = next(r['trial'] for r in slotting if r['block'] == 'animate' and r['active_pt'] == first_pt)
    for rows in (slotting, timeline):
        for r in rows:
            if r['block'] == 'animate' and r['trial'] == trial and r['role'] == 'PT':
                r['active_pt' if rows is slotting else 'stimulus'] = other_pt
    errors = validate_plan(assignment, slotting, timeline, trials_per_pt=25)
    assert any('PT active-trial counts' in e for e in errors)


def test_validator_rejects_broken_corner_balance_and_spacing(plan_100):
    assignment = plan_100[0]
    slotting, timeline = copy.deepcopy(plan_100[1:3])
    target = next(r for r in timeline if r['event_type'] == 'visual' and r['role'] == 'PT')
    corner = next(k for k in config.CORNERS if k != target['corner'])
    target['corner'] = corner
    target['x'], target['y'] = (s * 300 for s in config.CORNER_SIGNS[corner])
    next(r for r in slotting if r['event_id'] == target['event_id'])['corner'] = corner
    assert any('corner counts' in e for e in validate_plan(assignment, slotting, timeline, trials_per_pt=25))

    assignment = plan_100[0]
    slotting, timeline = copy.deepcopy(plan_100[1:3])
    visuals = [r for r in timeline if r['event_type'] == 'visual' and r['trial'] == 1 and r['block'] == 'animate']
    visuals[1]['global_onset'] = visuals[0]['global_onset'] + 0.01
    visuals[1]['trial_onset'] = visuals[0]['trial_onset'] + 0.01
    assert validate_plan(assignment, slotting, timeline, trials_per_pt=25)


def test_build_plan_refuses_a_plan_the_validator_rejects(monkeypatch):
    monkeypatch.setattr(participant_setup, 'validate_plan', lambda *a, **k: ['broken'])
    with pytest.raises(participant_setup.PlanValidationError, match='broken'):
        participant_setup.build_plan(7, ORDER)


def _events(corner_roles):
    return [{'role': role, 'corner': corner, 'stimulus': f'item{i}', 'soa': 1.0}
            for i, (corner, role) in enumerate(corner_roles)]


def test_overloaded_corner_is_reported_as_provably_infeasible():
    # 15 targets holding one corner need 14 * 1.4 + 0.6 = 20.2 s of a 20 s window.
    assert 'corner lower bound' in timeline_key._infeasibility(_events([('top_right', 'NPT')] * 15))
    assert timeline_key._infeasibility(_events([('top_right', 'NPT')] * 14)) == ''


def test_provably_infeasible_trial_fails_before_any_placement(monkeypatch):
    monkeypatch.setattr(timeline_key, '_infeasibility', lambda events: 'corner lower bound 21s')
    diagnostics = {}
    with pytest.raises(PlacementFailure, match='provably infeasible'):
        participant_setup.build_plan(7, ORDER, diagnostics=diagnostics)
    assert diagnostics['stage'] == 'capacity_check'
    assert diagnostics['placement_stats']['placement_attempts'] == 0


def test_a_failed_trial_is_retried_alone_and_placed_trials_are_kept(monkeypatch):
    real = timeline_key._construct_trial_schedule
    calls = []

    def flaky(events, trial_start, stats, repair=False):
        key = (events[0]['block'], events[0]['trial'])
        calls.append((key, repair))
        if key == ('animate', 3) and not repair:
            raise PlacementFailure('forced')
        return real(events, trial_start, stats, repair=repair)

    monkeypatch.setattr(timeline_key, '_construct_trial_schedule', flaky)
    diagnostics = {}
    assignment, slotting, timeline, _, stats = participant_setup.build_plan(7, ORDER, diagnostics=diagnostics)
    assert calls.count((('animate', 3), True)) == 1
    assert len(calls) == 9  # 8 first-pass placements plus one retry, nothing re-placed
    assert stats['repaired_trials'] == ['animate trial 3']
    assert diagnostics['timeline_attempts'] == 2
    assert validate_plan(assignment, slotting, timeline) == []


def test_unplaceable_trial_fails_after_the_configured_passes(monkeypatch):
    def never(events, trial_start, stats, repair=False):
        raise PlacementFailure('forced')

    monkeypatch.setattr(timeline_key, '_construct_trial_schedule', never)
    diagnostics = {}
    with pytest.raises(PlacementFailure, match=f'unplaced after {config.MAX_TIMELINE_ATTEMPTS} passes'):
        participant_setup.build_plan(7, ORDER, diagnostics=diagnostics)
    assert diagnostics['timeline_attempts'] == config.MAX_TIMELINE_ATTEMPTS
