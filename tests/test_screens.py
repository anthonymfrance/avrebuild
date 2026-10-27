"""Screen text checks that do not require PsychoPy."""

from types import SimpleNamespace

import pytest

import config
from scoring import trial_recap_lines
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
        self.kwargs = kwargs
        self.pos = kwargs.get('pos', (0, 0))
        self.text = ''
        FakeText.instances.append(self)

    def draw(self):
        pass


IMAGE_SIZES = {
    screens.NUMPAD_IMAGE_NAME: (1082, 605),
    screens.FINGERS_IMAGE_NAME: (1728, 2304),
    screens.HAND_PHOTO_NAME: (3377, 1535),
}

# A page is one look's worth of text; the instructions and scoring rules are
# split across pages so no screen is a wall.
PAGE_WORD_BUDGET = 70

# Every string actually drawn, one entry per draw, not per TextStim: a paged
# screen reuses one TextStim and rewrites its text.
_DRAWN = []


def drawn_texts():
    return [text for text, _ in _DRAWN]


def oneline(text):
    """Phrases are asserted across the source's line breaks."""
    return ' '.join(text.split())


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


class CapturingText(FakeText):
    def draw(self):
        _DRAWN.append((self.text, self))


class CapturingVisual(FakeVisual):
    TextStim = CapturingText


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


class FakeMark:
    """Any of the centre-mark primitives; records what it was built with."""

    instances = []

    def __init__(self, window, **kwargs):
        self.window = window
        self.kwargs = kwargs
        self.pos = kwargs.get('pos', (0, 0))
        self.lineColor = kwargs.get('lineColor')
        type(self).instances.append(self)


class FakeMarkShape(FakeMark):
    instances = []


class FakeMarkRect(FakeMark):
    instances = []


class FakeMarkCircle(FakeMark):
    instances = []


class MarkVisual:
    """A visual module exposing only the mark primitives, so the options stay
    distinguishable from one another."""

    ShapeStim = FakeMarkShape
    Rect = FakeMarkRect
    Circle = FakeMarkCircle


MARK_STIM = {'cross': FakeMarkShape, 'circle': FakeMarkCircle, 'border': FakeMarkRect}


def test_center_mark_draws_each_option_as_an_unfilled_stim_at_the_centre(monkeypatch):
    for shape, stim_class in MARK_STIM.items():
        for fake in (FakeMarkShape, FakeMarkRect, FakeMarkCircle):
            fake.instances.clear()
        monkeypatch.setattr(config, 'FIXATION_SHAPE', shape)
        mark = screens.center_mark(FakeWindow(), MarkVisual)
        assert type(mark) is stim_class
        assert mark.lineColor == config.FIXATION_COLOR
        assert mark.pos == (0, 0)
        # Unfilled: the hit flash is a lineColor change, which is why
        # trial_runner and practice need no per-mark case.
        assert mark.kwargs.get('fillColor', None) is None


def test_border_frame_is_inset_so_the_whole_stroke_stays_on_screen(monkeypatch):
    monkeypatch.setattr(config, 'FIXATION_SHAPE', 'border')
    mark = screens.center_mark(FakeWindow(), MarkVisual)
    width = config.FIXATION_BORDER_WIDTH
    # A stroked Rect straddles its path, so the frame is inset by one stroke
    # width and its visible outer edge lands on the window edge.
    assert mark.kwargs['lineWidth'] == width
    assert mark.kwargs['size'] == (1920 - width, 1080 - width)
    assert width > config.FIXATION_LINE_WIDTH


def test_mark_wording_follows_the_configured_shape(monkeypatch):
    assert set(screens.MARK_NAMES) == {'cross', 'circle', 'border'}
    for shape, name in screens.MARK_NAMES.items():
        monkeypatch.setattr(config, 'FIXATION_SHAPE', shape)
        assert screens.mark_shape() == shape
        assert screens.mark_flash_phrase() == f'the {name} flashes green'


def test_instruction_and_scoring_pages_name_the_configured_mark():
    """The pages read the mark from config instead of a hardcoded word."""
    phrase = screens.mark_flash_phrase()
    for pages in (screens.INSTRUCTION_PAGES, screens.SCORING_PAGES):
        text = oneline('\n'.join(pages))
        assert phrase in text
        for other in set(screens.MARK_NAMES) - {config.FIXATION_SHAPE}:
            assert f'the {screens.MARK_NAMES[other]} flashes green' not in text


def test_an_unknown_mark_shape_is_rejected(monkeypatch):
    monkeypatch.setattr(config, 'FIXATION_SHAPE', 'triangle')
    with pytest.raises(ValueError, match='FIXATION_SHAPE'):
        screens.mark_shape()
    with pytest.raises(ValueError, match='FIXATION_SHAPE'):
        screens.center_mark(FakeWindow(), MarkVisual)


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


def test_scoring_rules_screen_defines_every_outcome_across_pages():
    _DRAWN.clear()
    FakeText.instances.clear()
    FakeImageStim.instances.clear()
    window = FakeWindow()
    keyboard = FakeKeyboard(['space'])
    assert screens.scoring_rules(window, keyboard, CapturingVisual) is True
    assert keyboard.calls == len(screens.SCORING_PAGES) > 1
    assert FakeImageStim.instances == []
    pages = drawn_texts()
    message = '\n'.join(pages)
    for word in ('Hit:', 'Late:', 'Miss:', 'False alarm:'):
        assert word in message
    assert f'{config.RESPONSE_WINDOW:g} seconds' in message
    assert f'{config.TARGET_CORNER_HOLD:g} seconds' in message
    assert 'Press SPACE to start the practice.' in pages[-1]
    assert all(len(page.split()) <= PAGE_WORD_BUDGET for page in pages)


def test_every_instruction_and_scoring_page_waits_for_space():
    for pages in (screens.INSTRUCTION_PAGES, screens.SCORING_PAGES):
        assert all('Press SPACE' in page for page in pages)
        assert all(len(page.split()) <= PAGE_WORD_BUDGET for page in pages)


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


def test_instructions_are_split_across_pages_and_do_not_repeat_the_numpad_guide():
    _DRAWN.clear()
    FakeText.instances.clear()
    FakeImageStim.instances.clear()
    window = FakeWindow()
    keyboard = FakeKeyboard(['space'])
    assert screens.instructions(window, keyboard, CapturingVisual) is True
    assert keyboard.calls == len(screens.INSTRUCTION_PAGES) > 1
    assert FakeImageStim.instances == []
    pages = drawn_texts()
    assert len(pages) == len(screens.INSTRUCTION_PAGES)
    assert all(len(page.split()) <= PAGE_WORD_BUDGET for page in pages)
    message = oneline('\n'.join(pages))
    # The split must not lose the instructions the participant needs.
    assert 'an animals part and an objects part' in message
    assert 'all animals are your targets' in message
    assert 'all objects are your targets' in message
    assert 'press the number key for the corner where it appeared' in message
    assert 'not your targets' in message
    assert (
        f'You will have {config.RESPONSE_WINDOW:g} seconds to get points for '
        'reacting after the target first appears.' in message
    )
    assert 'false alarm' in message.lower()
    assert 'green' in message.lower()


def test_trial_recap_pages_report_the_trial_in_two_halves():
    pages = screens.trial_recap_messages('inanimate', 3, 5, 7, 1, 1, 2)
    assert len(pages) == 2
    assert pages[0].startswith('OBJECTS — Trial 3 complete.')
    recap = trial_recap_lines(5, 7, 1, 1, 2)
    for line in recap[:2]:
        assert line in pages[0] and line not in pages[1]
    for line in recap[2:]:
        assert line in pages[1] and line not in pages[0]
    assert pages[1].endswith('Remember to respond to all targets quickly and accurately!')
    assert all(len(page.split()) <= PAGE_WORD_BUDGET for page in pages)


def test_instructions_escape_aborts_on_any_page():
    window = FakeWindow()
    assert screens.instructions(window, FakeKeyboard(['escape']), FakeVisual()) is False


def test_finger_placement_shows_photo_under_text_and_diagram_beside_it():
    FakeText.instances.clear()
    FakeImageStim.instances.clear()
    window = FakeWindow()
    keyboard = FakeKeyboard(['space'])
    assert screens.finger_placement(window, keyboard, FakeVisual()) is True
    assert keyboard.calls == 1
    message = oneline(FakeText.instances[-1].text)
    line_count = len(FakeText.instances[-1].text.splitlines())
    assert 'index finger between 4 and 1' in message
    assert 'middle finger between 5 and 2' in message
    assert 'one finger on the space bar and two on the number pad' in message
    assert 'dominant hand on the number pad' in message
    photo = next(
        image for image in FakeImageStim.instances
        if image.image.endswith(screens.HAND_PHOTO_NAME)
    )
    diagram = next(
        image for image in FakeImageStim.instances
        if image.image.endswith(screens.FINGERS_IMAGE_NAME)
    )
    # The photo sits in the left column below the text; the tall diagram keeps
    # the right column, where it fits without being squashed.
    assert photo.pos[0] < 0 and photo.pos[1] < 0
    assert photo.size[0] <= 1920 * 0.46 + 1
    assert photo.size[1] <= 1080 * 0.38 + 1
    assert photo.size[0] / photo.size[1] > 2.0  # landscape, not cropped
    # The left column stacks text above photo: they must not overlap, and the
    # gap has to survive a font whose line height differs from this estimate.
    assert FakeText.instances[-1].kwargs['anchorVert'] == 'top'
    text_bottom = 1080 / 2 - FakeText.instances[-1].pos[1] + line_count * 36
    photo_top = 1080 / 2 - (photo.pos[1] + photo.size[1] / 2)
    assert photo_top - text_bottom > 30, (photo_top, text_bottom)
    assert diagram.pos[0] > 0
    assert diagram.size[0] <= 1920 * 0.30 + 1
    assert diagram.size[1] <= 1080 * 0.74 + 1


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
