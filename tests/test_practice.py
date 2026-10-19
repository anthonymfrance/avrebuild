"""Practice script checks that do not require PsychoPy."""

from types import SimpleNamespace

import config
from scoring import classify_press
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


def test_corner_xy_is_the_same_place_inside_its_quadrant():
    assert practice.corner_xy(1920, 1080, 'top_right') == practice.corner_xy(1920, 1080, 'top_right')
    half = config.IMAGE_SIZE[0] / 2
    for corner in config.CORNERS:
        x, y = practice.corner_xy(1920, 1080, corner)
        assert abs(x) + half < 960
        assert abs(y) + half < 540
        sx, sy = config.CORNER_SIGNS[corner]
        assert x * sx > half and y * sy > half
