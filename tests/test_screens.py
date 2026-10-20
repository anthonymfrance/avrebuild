"""Screen text checks that do not require PsychoPy."""

from types import SimpleNamespace

import config
import screens


class FakeWindow:
    def __init__(self):
        self.size = (1920, 1080)
        self.flips = 0

    def flip(self):
        self.flips += 1


class FakeText:
    instances = []

    def __init__(self, window, **kwargs):
        self.window = window
        self.text = ''
        FakeText.instances.append(self)

    def draw(self):
        pass


IMAGE_SIZES = {
    screens.NUMPAD_IMAGE_NAME: (1082, 605),
    screens.FINGERS_IMAGE_NAME: (1728, 2304),
}


class FakeImageStim:
    instances = []

    def __init__(self, window, image, **kwargs):
        self.window = window
        self.image = image
        self.size = next(
            (size for name, size in IMAGE_SIZES.items() if image.endswith(name)),
            (1000, 1000),
        )
        self.pos = (0, 0)
        FakeImageStim.instances.append(self)

    def draw(self):
        pass


class FakeVisual:
    TextStim = FakeText
    ImageStim = FakeImageStim


class FakeKeyboard:
    def __init__(self, keys):
        self.keys = keys
        self.calls = 0

    def getKeys(self, **kwargs):
        self.calls += 1
        return [SimpleNamespace(name=key) for key in self.keys]


class FakeClock:
    def __init__(self, advance=0.0):
        self.now = 0.0
        self.advance = advance

    def getTime(self):
        self.now += self.advance
        return self.now


def test_rest_break_counts_down_and_space_ends_it_early():
    FakeText.instances.clear()
    window = FakeWindow()
    keyboard = FakeKeyboard(['space'])
    outcome, elapsed = screens.rest_break(window, keyboard, FakeVisual(), FakeClock())
    assert outcome == 'completed' and elapsed == 0.0
    assert keyboard.calls == 1
    assert window.flips == 1
    message = FakeText.instances[-1].text
    assert 'the study continues on its own in 30 seconds' in message
    assert 'Press SPACE to continue now' in message
    assert '2-minute' not in message


def test_rest_break_continues_by_itself_when_the_countdown_ends():
    FakeText.instances.clear()
    window = FakeWindow()
    keyboard = FakeKeyboard([])
    clock = FakeClock(advance=1.0)
    outcome, elapsed = screens.rest_break(window, keyboard, FakeVisual(), clock)
    assert outcome == 'completed' and elapsed >= 30
    assert keyboard.calls > 1
    assert 'in 0 seconds' in FakeText.instances[-1].text


def test_scoring_rules_screen_defines_every_outcome():
    FakeText.instances.clear()
    FakeImageStim.instances.clear()
    window = FakeWindow()
    keyboard = FakeKeyboard(['space'])
    assert screens.scoring_rules(window, keyboard, FakeVisual()) is True
    assert keyboard.calls == 1
    assert FakeImageStim.instances == []
    message = FakeText.instances[-1].text
    for word in ('Hit:', 'Late:', 'Miss:', 'False alarm:'):
        assert word in message
    assert f'{config.RESPONSE_WINDOW:g} seconds' in message
    assert f'{config.TARGET_CORNER_HOLD:g} seconds' in message
    assert 'Press SPACE to start the practice.' in message


def test_numpad_check_shows_the_numpad_guide_and_checks_every_key():
    FakeText.instances.clear()
    FakeImageStim.instances.clear()
    window = FakeWindow()
    keyboard = FakeKeyboard(['num_4', 'num_5', 'num_1', 'num_2'])
    assert screens.numpad_check(window, keyboard, FakeVisual()) is True
    assert keyboard.calls == 1
    message = FakeText.instances[-1].text
    assert 'Number Key Check' in message
    assert 'Still to check:' in message
    image = FakeImageStim.instances[-1]
    assert image.image.endswith(screens.NUMPAD_IMAGE_NAME)
    assert image.pos[0] > 0
    assert image.size[0] > 1920 * 0.45
    assert image.size[0] <= 1920 * 0.48 + 1
    assert image.size[1] <= 1080 * 0.62 + 1


def test_numpad_check_escape_aborts():
    FakeText.instances.clear()
    FakeImageStim.instances.clear()
    window = FakeWindow()
    keyboard = FakeKeyboard(['escape'])
    assert screens.numpad_check(window, keyboard, FakeVisual()) is False
    assert keyboard.calls == 1


def test_instructions_does_not_repeat_the_numpad_guide():
    FakeText.instances.clear()
    FakeImageStim.instances.clear()
    window = FakeWindow()
    keyboard = FakeKeyboard(['space'])
    assert screens.instructions(window, keyboard, FakeVisual()) is True
    assert keyboard.calls == 1
    assert FakeImageStim.instances == []


def test_finger_placement_shows_hand_guide_and_space_continues():
    FakeText.instances.clear()
    FakeImageStim.instances.clear()
    window = FakeWindow()
    keyboard = FakeKeyboard(['space'])
    assert screens.finger_placement(window, keyboard, FakeVisual()) is True
    assert keyboard.calls == 1
    message = FakeText.instances[-1].text
    assert 'index finger between 4 and 1' in message
    assert 'middle finger between 5 and 2' in message
    image = FakeImageStim.instances[-1]
    assert image.image.endswith(screens.FINGERS_IMAGE_NAME)
    assert image.pos[0] > 0
    assert image.size[0] <= 1920 * 0.36 + 1
    assert image.size[1] <= 1080 * 0.78 + 1


def test_finger_placement_escape_aborts():
    FakeText.instances.clear()
    FakeImageStim.instances.clear()
    window = FakeWindow()
    keyboard = FakeKeyboard(['escape'])
    assert screens.finger_placement(window, keyboard, FakeVisual()) is False
    assert keyboard.calls == 1


def test_rest_break_escape_aborts():
    FakeText.instances.clear()
    window = FakeWindow()
    keyboard = FakeKeyboard(['escape'])
    outcome, _elapsed = screens.rest_break(window, keyboard, FakeVisual(), FakeClock())
    assert outcome == 'aborted'
    assert keyboard.calls == 1
    assert window.flips == 1
