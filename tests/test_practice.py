"""Practice script checks that do not require PsychoPy."""

import importlib
import itertools
import types
from types import SimpleNamespace

import pytest

import config
from scoring import classify_press, trial_recap_lines
from screens import RESPONSE_KEYS
import practice
import trial_runner


class FakeWindow:
    def __init__(self):
        self.size = (1920, 1080)

    def flip(self):
        pass


class FakeText:
    def __init__(self, window, **kwargs):
        self.text = ''

    def draw(self):
        pass


class FakeVisual:
    TextStim = FakeText


class FakeKeyboard:
    def __init__(self, keys):
        self.keys = keys

    def getKeys(self, **kwargs):
        return [SimpleNamespace(name=key) for key in self.keys]


def test_intro_space_starts_s_skips_escape_aborts():
    window, visual = FakeWindow(), FakeVisual()
    assert practice.intro(window, FakeKeyboard(['space']), visual) == 'start'
    assert practice.intro(window, FakeKeyboard(['s']), visual) == 'skipped'
    assert practice.intro(window, FakeKeyboard(['escape']), visual) == 'abort'


def test_easy_round_is_the_fixed_script_that_scores_like_the_task():
    assert [kind for _, kind, _ in practice.EASY] == [
        'target', 'distractor', 'target', 'distractor', 'target',
    ]
    assert [corner for _, _, corner in practice.EASY] == [
        'top_right', 'bottom_left', 'bottom_right', 'top_left', 'top_left',
    ]
    onsets = [onset for onset, _, _ in practice.EASY]
    gap = config.RESPONSE_WINDOW + config.LATE_WINDOW
    assert all(b - a > gap for a, b in zip(onsets, onsets[1:]))

    targets = practice.paced_targets(practice.EASY, 'easy')
    row, chosen = classify_press(
        'num_5', 'top_right', 0.9, targets,
        config.RESPONSE_WINDOW, config.LATE_WINDOW, targets,
    )
    assert row['classification'] == 'hit' and chosen['corner'] == 'top_right'

    targets = practice.paced_targets(practice.EASY, 'easy')
    late_at = 0.8 + config.RESPONSE_WINDOW + 0.1
    row, chosen = classify_press(
        'num_5', 'top_right', late_at, targets,
        config.RESPONSE_WINDOW, config.LATE_WINDOW, targets,
    )
    assert row['classification'] == 'late' and chosen is not None

    targets = practice.paced_targets(practice.EASY, 'easy')
    row, chosen = classify_press(
        'num_1', 'bottom_left', 2.5, targets,
        config.RESPONSE_WINDOW, config.LATE_WINDOW, targets,
    )
    assert row['classification'] == 'false_alarm' and chosen is None


def test_practice_is_the_same_script_for_every_participant():
    """Every participant sees one hardcoded script: no RNG, no per-session state."""
    modules = [
        value.__name__ for value in vars(practice).values()
        if isinstance(value, types.ModuleType)
    ]
    assert 'random' not in modules
    assert [tier['tier'] for tier in practice.TIERS] == ['easy', 'medium', 'hard']
    assert practice.TIERS[0]['events'] is practice.EASY
    assert practice.TIERS[1]['events'] is practice.MEDIUM
    assert practice.TIERS[2]['events'] is practice.HARD
    for tier in practice.TIERS:
        assert isinstance(tier['events'], tuple) and isinstance(tier['offsets'], tuple)

    reloaded = importlib.reload(practice)
    assert reloaded.EASY == practice.EASY
    assert reloaded.MEDIUM == practice.MEDIUM
    assert reloaded.HARD == practice.HARD


def _tier_violations(events):
    """The visual rules the real timeline enforces, applied to a practice script.

    Mirrors timeline_key's checks: the universal onset gap, a corner never
    double-booked, a target's corner left empty for TARGET_CORNER_HOLD, and
    target response windows that never overlap.
    """
    violations = []
    for earlier, later in itertools.combinations(events, 2):
        earlier_onset, earlier_kind, earlier_corner = earlier
        later_onset, later_kind, later_corner = later
        gap = later_onset - earlier_onset
        end_to_onset = later_onset - (earlier_onset + config.VISUAL_DURATION)
        if gap < config.MIN_VISUAL_ONSET_GAP:
            violations.append(('minimum_visual_onset_gap', earlier_onset, later_onset))
        if earlier_corner == later_corner and end_to_onset < 0:
            violations.append(('same_corner_overlap', earlier_onset, later_onset))
        if (earlier_corner == later_corner and earlier_kind == 'target'
                and gap < config.TARGET_CORNER_HOLD):
            violations.append(('same_corner_target_hold', earlier_onset, later_onset))
        if earlier_kind == 'target' and later_kind == 'target':
            if end_to_onset < config.MIN_TARGET_END_TO_ONSET_GAP:
                violations.append(('minimum_target_end_to_onset_gap', earlier_onset, later_onset))
            if gap < config.RESPONSE_WINDOW:
                violations.append(('target_response_windows_overlap', earlier_onset, later_onset))
    return violations


def test_tier_scripts_obey_the_real_timeline_rules():
    for tier in practice.TIERS:
        events = tier['events']
        onsets = [onset for onset, _, _ in events]
        assert onsets == sorted(onsets)
        assert _tier_violations(events) == [], tier['tier']


def _gaps(events):
    onsets = [onset for onset, _, _ in events]
    return [later - earlier for earlier, later in zip(onsets, onsets[1:])]


def _peak_on_screen(onsets):
    """Most shapes sharing the screen at one instant."""
    edges = sorted(
        [(onset, 1) for onset in onsets]
        + [(onset + config.VISUAL_DURATION, -1) for onset in onsets]
    )
    live = peak = 0
    for _, delta in edges:
        live += delta
        peak = max(peak, live)
    return peak


def _round_facts(tier):
    events = tier['events']
    onsets = [onset for onset, _, _ in events]
    span = practice.paced_end(events)
    return {
        'events': len(events),
        'targets': sum(kind == 'target' for _, kind, _ in events),
        'target_corners': {corner for _, kind, corner in events if kind == 'target'},
        'span': span,
        'density': len(events) / span,
        'peak_on_screen': _peak_on_screen(onsets),
        # Two shapes share the screen when the earlier one is still visible as
        # the later one appears. The tolerance matters: an exact
        # VISUAL_DURATION gap leaves a ~1e-16 alpha from float error.
        'co_present': [
            (first, second) for first, second in itertools.combinations(onsets, 2)
            if trial_runner.planned_image_alpha(second - first) > 1e-6
        ],
        'onsets_in_target_windows': [
            sum(1 for other in onsets if onset < other <= onset + config.RESPONSE_WINDOW)
            for onset, kind, _ in events if kind == 'target'
        ],
    }


def test_difficulty_rises_from_one_round_to_the_next():
    """The ladder is measurable: more pictures per second, more sharing the screen."""
    easy, medium, hard = (
        _round_facts(tier) for tier in practice.TIERS
    )
    assert easy['targets'] < hard['targets']
    assert easy['density'] < medium['density'] < hard['density']
    # Generated real trials run 1.4-2.2 items per second; hard is inside that band.
    assert 1.4 <= hard['density'] <= 2.2
    assert medium['density'] < 1.4

    # One picture at a time, then two, then the three-deep pile-up of a real
    # trial (the median real trial also peaks at three pictures on screen).
    assert [easy['peak_on_screen'], medium['peak_on_screen'], hard['peak_on_screen']] == [1, 2, 3]
    assert easy['co_present'] == []
    assert all(gap > config.VISUAL_DURATION + 1e-6 for gap in _gaps(practice.EASY))
    assert len(medium['co_present']) >= 3 and len(hard['co_present']) >= 5

    # A target's window is shared with no picture, then with pictures, and the
    # real stream's sharing (mean 1.16 later onsets per window over 88 trials)
    # is visible in hard.
    assert easy['onsets_in_target_windows'] == [0] * easy['targets']
    assert max(medium['onsets_in_target_windows']) == 1
    assert max(hard['onsets_in_target_windows']) >= 1
    assert 0.8 <= sum(hard['onsets_in_target_windows']) / hard['targets'] <= 4

    # Medium and hard train all four keys, which the real target bias (79% of
    # targets in the favoured corner) would otherwise leave mostly untrained.
    # Easy is the round that ran before this change, so it keeps its three.
    assert medium['target_corners'] == set(config.CORNERS)
    assert hard['target_corners'] == set(config.CORNERS)
    assert easy['target_corners'] == set(config.CORNERS) - {'bottom_left'}


def test_every_round_uses_the_config_stimulus_appearance():
    """No tier carries its own size or fade: the look comes from config alone."""
    for tier in practice.TIERS:
        assert set(tier) == {'tier', 'events', 'offsets', 'caption', 'hold_text'}
        assert practice.paced_targets(tier['events'], tier['tier'])

    recorded = {}

    class RecordingShape:
        def __init__(self, window, **kwargs):
            self.kwargs = kwargs
            self.pos = (0, 0)
            self.opacity = 1.0
            recorded[type(self).__name__ + str(len(recorded))] = kwargs

        def draw(self):
            pass

    class RecordingVisual(FakeVisual):
        Circle = RecordingShape
        Rect = RecordingShape

    stims = practice._make_shapes(FakeWindow(), RecordingVisual)
    assert stims['target'].kwargs['radius'] == config.IMAGE_SIZE[0] / 2
    assert stims['distractor'].kwargs['width'] == config.IMAGE_SIZE[0]
    assert stims['distractor'].kwargs['height'] == config.IMAGE_SIZE[1]
    # Grey, because a solid white shape on the dark noise field reads far
    # heavier than a grayscale photo. Not the colour name 'gray': PsychoPy
    # resolves that to rgb 0.0039, which is essentially black.
    for kwargs in recorded.values():
        assert kwargs['fillColor'] == practice.SHAPE_COLOR
        assert kwargs['lineColor'] == practice.SHAPE_COLOR
    assert practice.SHAPE_COLOR.startswith('#')
    assert practice.SHAPE_COLOR.lower() not in ('#ffffff', 'gray', 'grey', 'white')
    # The practice ramp is the real trial ramp, not a copy of it.
    assert practice.planned_image_alpha is trial_runner.planned_image_alpha


def test_practice_draws_the_real_background_noise():
    """Practice carries the same noise field the trials draw, rotated the same way."""
    assert practice._background_frame([], 0.0) is None
    frames = [CountingShape(), CountingShape(), CountingShape()]
    assert practice._background_frame(frames, 0.0) is frames[0]
    assert practice._background_frame(frames, config.BG_UPDATE_RATE) is frames[1]
    assert practice._background_frame(frames, 3 * config.BG_UPDATE_RATE) is frames[0]

    clock = AdvancingClock()
    window = AdvancingWindow(clock)
    background = CountingShape()
    rows = []
    outcome, targets, false_alarms = practice._paced(
        window, ScheduledKeyboard(clock, []), clock, FakeFixation(),
        practice._text(window, FakeShapeVisual),
        practice._make_shapes(window, FakeShapeVisual), rows, practice.TIERS[-1],
        [background],
    )
    assert outcome == 'ok'
    assert false_alarms == 0
    assert background.draws > 10, 'the background is drawn on every frame of a round'
    assert [target['response_status'] for target in targets] == ['miss'] * len(targets)


class AdvancingClock:
    def __init__(self, step=0.01):
        self.now = 0.0
        self.step = step

    def getTime(self):
        return self.now


class AdvancingWindow(FakeWindow):
    def __init__(self, clock):
        super().__init__()
        self.clock = clock

    def flip(self):
        self.clock.now += self.clock.step


class ScheduledKeyboard:
    """Returns each scheduled press once the clock reaches its time."""

    def __init__(self, clock, schedule):
        self.clock = clock
        self.schedule = sorted(schedule)
        self.calls = 0

    def clearEvents(self):
        pass

    def getKeys(self, **kwargs):
        self.calls += 1
        due = [entry for entry in self.schedule if entry[0] <= self.clock.now]
        self.schedule = [entry for entry in self.schedule if entry[0] > self.clock.now]
        return [SimpleNamespace(name=name, rt=time) for time, name in due]


class FakeShape:
    def __init__(self, window, **kwargs):
        self.pos = (0, 0)
        self.opacity = 1.0

    def draw(self):
        pass


class FakeFixation:
    lineColor = None

    def draw(self):
        pass


class CountingShape(FakeShape):
    """A background frame that records how often it is drawn."""

    def __init__(self, window=None, **kwargs):
        self.draws = 0

    def draw(self):
        self.draws += 1


class FakeShapeVisual(FakeVisual):
    Circle = FakeShape
    Rect = FakeShape


def test_practice_intro_does_not_advertise_the_operator_skip_key():
    drawn = []

    class CapturingText(FakeText):
        def __init__(self, window, **kwargs):
            super().__init__(window, **kwargs)
            drawn.append(self)

    class CapturingVisual(FakeVisual):
        TextStim = CapturingText

    clock = AdvancingClock()
    # 's' still skips: the operator keeps the key, participants just don't see it.
    assert practice.intro(AdvancingWindow(clock), ScheduledKeyboard(clock, [(0.0, 's')]),
                          CapturingVisual) == 'skipped'
    message = drawn[-1].text
    assert 'Press SPACE to start.' in message
    assert 'skip' not in message.lower() and 'operator' not in message.lower()


def test_skipped_practice_is_reported_with_a_row():
    clock = AdvancingClock()
    window = AdvancingWindow(clock)
    keyboard = ScheduledKeyboard(clock, [(0.0, 's')])
    result = practice.run(
        window, keyboard, FakeVisual(), SimpleNamespace(lineColor=None), clock, [],
    )
    assert result['status'] == 'skipped'
    assert result['summary']['status'] == 'skipped'
    assert [row['classification'] for row in result['rows']] == ['skipped']
    assert result['rows'][0]['outcome'] == 'practice_not_run'


def test_paced_round_records_hits_late_misses_and_false_alarms():
    clock = AdvancingClock()
    window = AdvancingWindow(clock)
    keyboard = ScheduledKeyboard(clock, [
        (1.3, 'num_5'),   # hit: top-right target at 0.8 s
        (2.8, 'num_1'),   # false alarm: distractor in that corner
        (3.0, 'space'),   # ignored key, not a false alarm
        (5.1, 'num_2'),   # late: bottom-right target at 4.0 s
        # top-left target at 7.2 s is never pressed: miss
    ])
    fixation = FakeFixation()
    stims = practice._make_shapes(window, FakeShapeVisual)
    rows = []
    tier = practice.TIERS[0]
    outcome, targets, false_alarms = practice._paced(
        window, keyboard, clock, fixation, practice._text(window, FakeShapeVisual),
        stims, rows, tier, [],
    )
    assert outcome == 'ok'
    assert [target['response_status'] for target in targets] == ['hit', 'late', 'miss']
    assert false_alarms == 1
    classes = [row['classification'] for row in rows]
    assert classes.count('ignored_key') == 1 and 'ignored_key' not in [
        row['classification'] for row in rows if row['corner']
    ]
    assert {row['tier'] for row in rows} == {'easy'}
    target_rows = {row['event_id']: row for row in rows if row['event_id']}
    assert set(target_rows) == {'easy-0', 'easy-2', 'easy-4'}
    assert target_rows['easy-0']['classification'] == 'hit'
    assert target_rows['easy-0']['rt_seconds'] == 0.5
    assert target_rows['easy-2']['classification'] == 'late'
    assert target_rows['easy-4']['classification'] == 'miss'
    assert target_rows['easy-4']['key'] == ''


@pytest.mark.parametrize('tier', practice.TIERS, ids=lambda tier: tier['tier'])
def test_every_round_scores_a_hit_for_the_key_of_the_open_target(tier):
    clock = AdvancingClock()
    window = AdvancingWindow(clock)
    keyboard = ScheduledKeyboard(clock, [
        (onset + 0.2, RESPONSE_KEYS[corner][0])
        for onset, kind, corner in tier['events'] if kind == 'target'
    ])
    rows = []
    outcome, targets, false_alarms = practice._paced(
        window, keyboard, clock, FakeFixation(),
        practice._text(window, FakeShapeVisual),
        practice._make_shapes(window, FakeShapeVisual), rows, tier, [],
    )
    assert outcome == 'ok'
    assert [target['response_status'] for target in targets] == ['hit'] * len(targets)
    assert false_alarms == 0
    expected_ids = [
        f"{tier['tier']}-{index}" for index, (_, kind, _) in enumerate(tier['events'])
        if kind == 'target'
    ]
    assert [target['event_id'] for target in targets] == expected_ids
    assert len(set(expected_ids)) == len(expected_ids)
    assert {row['tier'] for row in rows if row['phase'] == 'paced'} == {tier['tier']}


TEXT_REGISTRY = []


class ScreenText(FakeText):
    """A TextStim that keeps every instance so a fake participant can read it."""

    def __init__(self, window, **kwargs):
        super().__init__(window, **kwargs)
        TEXT_REGISTRY.append(self)


class ScriptedShapeVisual(FakeShapeVisual):
    TextStim = ScreenText


class ScriptedParticipant:
    """A fake participant: reads each screen, then answers each open target.

    Pre-round screens are answered from the drawn text (SPACE to continue, the
    number key a coached step names). In the paced rounds the press follows the
    round script: the target currently in its response window gets its key,
    except for `miss` entries, which are left unanswered, and `false_alarms`
    entries, which get the wrong key. `skip_rounds` presses the operator's 's'
    on that round's hold screen.
    """

    def __init__(self, clock, miss=(), false_alarms=(), skip_rounds=()):
        self.clock = clock
        self.miss = set(miss)
        self.false_alarms = dict(false_alarms)
        self.skip_rounds = set(skip_rounds)
        self.clears = 0
        self.round_index = -1
        self.round_start = None
        self.answered = set()
        self.log = []

    def clearEvents(self):
        # practice.run clears once before the coached steps; every paced round
        # clears again at its own start, which is that round's zero.
        self.clears += 1
        if self.clears > 1:
            self.round_index += 1
            self.round_start = self.clock.now

    def getKeys(self, **kwargs):
        if self.round_index < 0:
            return self._read_screen()
        return self._answer_round() or self._read_screen()

    def _press(self, name):
        self.log.append((self.clock.now, name))
        return [SimpleNamespace(name=name, rt=self.clock.now)]

    def _read_screen(self):
        text = next((stim.text for stim in reversed(TEXT_REGISTRY) if stim.text), '')
        for tier in practice.TIERS:
            if text == tier['hold_text'] and tier['tier'] in self.skip_rounds:
                return self._press('s')
        if 'SPACE' in text.upper():
            return self._press('space')
        for digit in '1245':
            if f'Press {digit}' in text:
                return self._press(f'num_{digit}')
        return []

    def _answer_round(self):
        tier = practice.TIERS[self.round_index]
        elapsed = self.clock.now - self.round_start
        for index, (onset, kind, corner) in enumerate(tier['events']):
            key = (tier['tier'], index)
            if key in self.answered or key in self.miss:
                continue
            if not onset <= elapsed <= onset + config.RESPONSE_WINDOW:
                continue
            if key in self.false_alarms:
                self.answered.add(key)
                return self._press(self.false_alarms[key])
            if kind != 'target':
                continue
            self.answered.add(key)
            return self._press(RESPONSE_KEYS[corner][0])
        return []


def test_full_practice_run_walks_the_three_rounds():
    TEXT_REGISTRY.clear()
    clock = AdvancingClock()
    participant = ScriptedParticipant(
        clock,
        miss={('easy', 4), ('medium', 8), ('hard', 13)},
        false_alarms={('easy', 1): 'num_2'},
    )
    fixation = FakeFixation()
    background = CountingShape()
    result = practice.run(
        AdvancingWindow(clock), participant, ScriptedShapeVisual, fixation, clock,
        [background],
    )
    assert background.draws > 0, 'practice must draw the real background noise'

    assert result['status'] == 'completed'
    summary = result['summary']
    assert summary['status'] == 'completed'
    assert summary['skipped_at_tier'] == ''
    assert summary['coached_corrections'] == 0
    assert [tier['tier'] for tier in summary['tiers']] == ['easy', 'medium', 'hard']
    assert [tier['events'] for tier in summary['tiers']] == [5, 12, 20]
    assert [tier['outcome'] for tier in summary['tiers']] == ['completed'] * 3
    assert [tier['hits'] for tier in summary['tiers']] == [2, 3, 3]
    assert [tier['misses'] for tier in summary['tiers']] == [1, 1, 1]
    assert [tier['false_alarms'] for tier in summary['tiers']] == [1, 0, 0]
    assert summary['paced_hits'] == sum(tier['hits'] for tier in summary['tiers']) == 8
    assert summary['paced_misses'] == 3
    assert summary['paced_late'] == 0
    assert summary['paced_false_alarms'] == 1
    assert summary['duration_seconds'] == pytest.approx(clock.now)

    # One row per target, 11 in total (3 easy + 4 medium + 4 hard), each id unique.
    event_ids = [row['event_id'] for row in result['rows'] if row['event_id']]
    assert len(event_ids) == len(set(event_ids)) == 11
    assert {row['tier'] for row in result['rows'] if row['phase'] == 'paced'} == {
        'easy', 'medium', 'hard',
    }
    assert all(row['tier'] == 'coached' for row in result['rows'] if row['phase'] == 'coached')
    assert fixation.lineColor == config.FIXATION_COLOR
    # A scripted participant never wanders: the whole run stays well inside a minute.
    assert clock.now < 60


def test_skipping_at_a_round_change_keeps_the_rows_and_ends_practice():
    TEXT_REGISTRY.clear()
    clock = AdvancingClock()
    participant = ScriptedParticipant(clock, skip_rounds={'easy'})
    result = practice.run(
        AdvancingWindow(clock), participant, ScriptedShapeVisual, FakeFixation(), clock, [],
    )

    assert result['status'] == 'skipped'
    assert result['summary']['status'] == 'skipped'
    assert result['summary']['skipped_at_tier'] == 'easy'
    assert result['summary']['tiers'] == []
    assert result['rows'][-1]['classification'] == 'skipped'
    assert result['rows'][-1]['tier'] == 'easy'
    assert any(row['phase'] == 'coached' for row in result['rows'])


def test_practice_summary_uses_the_same_recap_lines_as_the_real_trials():
    drawn = []

    class CapturingText(FakeText):
        def draw(self):
            drawn.append(self.text)

    class CapturingVisual(FakeVisual):
        TextStim = CapturingText

    # Totals match the four recap statements asserted below; one tier per round.
    summary = {
        'paced_hits': 2, 'paced_late': 1, 'paced_misses': 1, 'paced_false_alarms': 2,
        'tiers': [
            {'tier': 'easy', 'hits': 1, 'late': 0, 'misses': 0, 'false_alarms': 1},
            {'tier': 'medium', 'hits': 1, 'late': 0, 'misses': 1, 'false_alarms': 1},
            {'tier': 'hard', 'hits': 0, 'late': 1, 'misses': 0, 'false_alarms': 0},
        ],
    }
    outcome = practice._summary(
        FakeWindow(), FakeKeyboard(['space']), CapturingVisual, summary,
    )
    assert outcome == 'ok'
    message = drawn[-1]
    assert 'Practice complete.' in message
    for line in trial_recap_lines(2, 4, 1, 1, 2):
        assert line in message
    assert 'Round 1 of 3 (easy): hits 1, late 0, misses 0, false alarms 1' in message
    assert 'Remember to respond to all targets quickly and accurately!' in message
    assert 'The real task is the same' in message
    assert 'Press SPACE to begin the study.' in message


def test_corner_xy_is_the_same_place_inside_its_quadrant():
    assert practice.corner_xy(1920, 1080, 'top_right') == practice.corner_xy(1920, 1080, 'top_right')
    half = config.IMAGE_SIZE[0] / 2
    for corner in config.CORNERS:
        x, y = practice.corner_xy(1920, 1080, corner)
        assert abs(x) + half < 960
        assert abs(y) + half < 540
        sx, sy = config.CORNER_SIGNS[corner]
        assert x * sx > half and y * sy > half


def test_practice_shapes_jitter_within_their_corners():
    half = config.IMAGE_SIZE[0] / 2
    for tier in practice.TIERS:
        assert len(tier['offsets']) == len(tier['events'])
        by_corner = {}
        for (_, _, corner), offset in zip(tier['events'], tier['offsets']):
            assert offset != (0, 0)
            x, y = practice.corner_xy(1920, 1080, corner, offset)
            assert abs(x) + half < 960
            assert abs(y) + half < 540
            sx, sy = config.CORNER_SIGNS[corner]
            assert x * sx > half and y * sy > half
            by_corner.setdefault(corner, []).append((x, y))
        for corner, positions in by_corner.items():
            assert len(set(positions)) == len(positions), (tier['tier'], corner)
    for step in practice.COACHED:
        assert all(offset != (0, 0) for _, _, offset in step['shapes'])
