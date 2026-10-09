import config
from audio_ptb import assign_sound_slots
from participant_setup import build_plan

SEEDS = range(50)


def plan_sounds(seed):
    _, _, timeline, _, _ = build_plan(seed, ['animate', 'inanimate'])
    return [row for row in timeline if row['event_type'] == 'sound']


PLANS = [plan_sounds(seed) for seed in SEEDS]


def late_request_violations(sounds, slots):
    """Plays whose play(when=...) request cannot keep the planned lead.

    The trial runner requests each play as early as its pooled Sound object is
    free: the previous play on that object must have ended plus
    config.SOUND_POOL_RESTART_MARGIN. The pool assignment must keep every
    request at least config.SOUND_REQUEST_LEAD ahead of its onset, so a frame
    stall cannot push it into audio_schedule_late territory.
    """
    free_at = {}
    violations = []
    for event in sorted(sounds, key=lambda row: row['global_onset']):
        key = (event['stimulus'], slots[event['event_id']])
        onset = float(event['global_onset'])
        if free_at.get(key, float('-inf')) + config.SOUND_REQUEST_LEAD > onset:
            violations.append(event['event_id'])
        free_at[key] = onset + config.SOUND_DUR + config.SOUND_POOL_RESTART_MARGIN
    return violations


def test_pool_keeps_every_request_ahead_of_its_onset():
    for sounds in PLANS:
        slots = assign_sound_slots(sounds, config.SOUND_POOL_SIZE)
        assert late_request_violations(sounds, slots) == []


def test_single_sound_per_stimulus_shrinks_the_lead_on_some_plan():
    assert any(
        late_request_violations(sounds, assign_sound_slots(sounds, 1))
        for sounds in PLANS
    )


def mutated_assign(sounds, pool_size, slot_of, order_key):
    plays, slots = {}, {}
    for event in sorted(sounds, key=order_key):
        count = plays.get(event['stimulus'], 0)
        slots[event['event_id']] = slot_of(count, pool_size)
        plays[event['stimulus']] = count + 1
    return slots


def test_round_robin_mutations_are_caught():
    by_onset = lambda row: row['global_onset']  # noqa: E731
    mutants = [
        (lambda count, size: count // size % size, by_onset),
        (lambda count, size: count % size, lambda row: row['event_id']),
    ]
    for slot_of, order_key in mutants:
        assert any(
            late_request_violations(
                sounds, mutated_assign(sounds, config.SOUND_POOL_SIZE, slot_of, order_key))
            for sounds in PLANS
        )


def test_assignment_alternates_per_stimulus_in_onset_order():
    sounds = [
        {'event_id': 'b2', 'stimulus': 'b', 'global_onset': 5.0},
        {'event_id': 'a1', 'stimulus': 'a', 'global_onset': 1.0},
        {'event_id': 'b1', 'stimulus': 'b', 'global_onset': 2.0},
        {'event_id': 'a2', 'stimulus': 'a', 'global_onset': 3.0},
        {'event_id': 'a3', 'stimulus': 'a', 'global_onset': 4.0},
    ]
    assert assign_sound_slots(sounds, 2) == {'a1': 0, 'b1': 0, 'a2': 1, 'a3': 0, 'b2': 1}
