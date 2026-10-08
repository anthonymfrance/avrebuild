import config
from audio_ptb import assign_sound_slots
from participant_setup import build_plan

SEEDS = range(50)
MARGIN = 0.05


def plan_sounds(seed):
    _, _, timeline, _, _ = build_plan(seed, ['animate', 'inanimate'])
    return [row for row in timeline if row['event_type'] == 'sound']


PLANS = [plan_sounds(seed) for seed in SEEDS]


def restart_violations(sounds, slots):
    """Plays scheduled while the previous play on the same Sound object is still sounding."""
    last_end = {}
    violations = []
    for event in sorted(sounds, key=lambda row: row['global_onset']):
        key = (event['stimulus'], slots[event['event_id']])
        scheduled_at = event['global_onset'] - config.SOUND_SCHEDULE_LEAD
        if key in last_end and scheduled_at - last_end[key] < MARGIN:
            violations.append(event['event_id'])
        last_end[key] = event['global_onset'] + config.SOUND_DUR
    return violations


def test_pool_never_restarts_a_playing_sound():
    for sounds in PLANS:
        slots = assign_sound_slots(sounds, config.SOUND_POOL_SIZE)
        assert restart_violations(sounds, slots) == []


def test_single_sound_per_stimulus_restarts_on_some_plan():
    assert any(restart_violations(sounds, assign_sound_slots(sounds, 1)) for sounds in PLANS)


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
            restart_violations(sounds, mutated_assign(sounds, config.SOUND_POOL_SIZE, slot_of, order_key))
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
