"""Screen text checks that do not require PsychoPy."""

from types import SimpleNamespace

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


class FakeVisual:
    TextStim = FakeText


class FakeKeyboard:
    def __init__(self, keys):
        self.keys = keys
        self.calls = 0

    def getKeys(self, **kwargs):
        self.calls += 1
        return [SimpleNamespace(name=key) for key in self.keys]


def test_rest_break_is_untimed_and_space_continues():
    FakeText.instances.clear()
    window = FakeWindow()
    keyboard = FakeKeyboard(['space'])
    assert screens.rest_break(window, keyboard, FakeVisual()) == 'completed'
    assert keyboard.calls == 1
    assert window.flips == 1
    message = FakeText.instances[-1].text
    assert "You can take a 30 second break here or continue if you'd like." in message
    assert '2-minute' not in message
    assert 'Time left' not in message


def test_rest_break_escape_aborts():
    FakeText.instances.clear()
    window = FakeWindow()
    keyboard = FakeKeyboard(['escape'])
    assert screens.rest_break(window, keyboard, FakeVisual()) == 'aborted'
    assert keyboard.calls == 1
    assert window.flips == 1
