"""Practice script checks that do not require PsychoPy."""

from types import SimpleNamespace

import config
from scoring import classify_press, trial_recap_lines
import practice


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


def test_paced_script_is_fixed_and_scores_like_the_task():
    assert [kind for _, kind, _ in practice.PACED] == [
        'target', 'distractor', 'target', 'distractor', 'target',
    ]
    assert [corner for _, _, corner in practice.PACED] == [
        'top_right', 'bottom_left', 'bottom_right', 'top_left', 'top_left',
    ]
    onsets = [onset for onset, _, _ in practice.PACED]
    gap = config.RESPONSE_WINDOW + config.LATE_WINDOW
    assert all(b - a > gap for a, b in zip(onsets, onsets[1:]))

    targets = practice.paced_targets()
    row, chosen = classify_press(
        'num_5', 'top_right', 0.9, targets,
        config.RESPONSE_WINDOW, config.LATE_WINDOW, targets,
    )
    assert row['classification'] == 'hit' and chosen['corner'] == 'top_right'

    targets = practice.paced_targets()
    late_at = 0.8 + config.RESPONSE_WINDOW + 0.1
    row, chosen = classify_press(
        'num_5', 'top_right', late_at, targets,
        config.RESPONSE_WINDOW, config.LATE_WINDOW, targets,
    )
    assert row['classification'] == 'late' and chosen is not None

    targets = practice.paced_targets()
    row, chosen = classify_press(
        'num_1', 'bottom_left', 2.5, targets,
        config.RESPONSE_WINDOW, config.LATE_WINDOW, targets,
    )
    assert row['classification'] == 'false_alarm' and chosen is None


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
    result = practice.run(window, keyboard, FakeVisual(), SimpleNamespace(lineColor=None), clock)
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
    outcome, targets, false_alarms = practice._paced(
        window, keyboard, clock, fixation, practice._text(window, FakeShapeVisual), stims, rows,
    )
    assert outcome == 'ok'
    assert [target['response_status'] for target in targets] == ['hit', 'late', 'miss']
    assert false_alarms == 1
    classes = [row['classification'] for row in rows]
    assert classes.count('ignored_key') == 1 and 'ignored_key' not in [
        row['classification'] for row in rows if row['corner']
    ]
    target_rows = {row['event_id']: row for row in rows if row['event_id']}
    assert target_rows['practice-0']['classification'] == 'hit'
    assert target_rows['practice-0']['rt_seconds'] == 0.5
    assert target_rows['practice-2']['classification'] == 'late'
    assert target_rows['practice-4']['classification'] == 'miss'
    assert target_rows['practice-4']['key'] == ''


def test_practice_summary_uses_the_same_recap_lines_as_the_real_trials():
    drawn = []

    class CapturingText(FakeText):
        def draw(self):
            drawn.append(self.text)

    class CapturingVisual(FakeVisual):
        TextStim = CapturingText

    targets = [
        {'response_status': 'hit'}, {'response_status': 'hit'},
        {'response_status': 'late'}, {'response_status': 'miss'},
    ]
    outcome = practice._summary(
        FakeWindow(), FakeKeyboard(['space']), CapturingVisual, targets, 2,
    )
    assert outcome == 'ok'
    message = drawn[-1]
    assert 'Practice complete.' in message
    for line in trial_recap_lines(2, len(targets), 1, 1, 2):
        assert line in message
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
    assert len(practice.PACED_OFFSETS) == len(practice.PACED)
    half = config.IMAGE_SIZE[0] / 2
    positions = []
    for index, (_, _, corner) in enumerate(practice.PACED):
        offset = practice.PACED_OFFSETS[index]
        assert offset != (0, 0)
        x, y = practice.corner_xy(1920, 1080, corner, offset)
        positions.append((corner, (x, y)))
        assert abs(x) + half < 960
        assert abs(y) + half < 540
        sx, sy = config.CORNER_SIGNS[corner]
        assert x * sx > half and y * sy > half
    top_left = [pos for corner, pos in positions if corner == 'top_left']
    assert len(set(top_left)) == len(top_left)
    for step in practice.COACHED:
        assert all(offset != (0, 0) for _, _, offset in step['shapes'])
