"""Render the study's text screens to HTML with fake PsychoPy objects.

Lets you review wording and layout off the lab machine: no display, no audio and
no PsychoPy needed. Every position, image size and page break comes from the real
screen code, and one HTML stage is emitted per frame the screen actually drew, so
a paged screen appears as the sequence of pages a participant presses through.

    python3 tools/render_screen_mock.py [output_dir]   # default build/screen_mock

Writes a contact sheet, `screens.html`, plus the images it references. Serve the
directory and open it:

    python3 -m http.server 8791 --directory build/screen_mock

The block intro and the between-trial recap are composed in experiment.py from
live trial rows, so they are not in this sheet; see PARTICIPANT_TEXT_AUDIT.md.
"""

from __future__ import annotations

import html
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402  (import after sys.path fix)
import practice  # noqa: E402
import screens  # noqa: E402

WINDOW_SIZE = tuple(config.WINDOW_SIZE)
MAX_FRAMES_PER_SCREEN = 8


class FrameRecorder:
    """The frames drawn so far; each `flip()` starts a new one."""

    def __init__(self):
        self.frames = [[]]
        self.flips = 0

    def flip(self):
        self.flips += 1
        self.frames.append([])

    def record(self, element):
        self.frames[-1].append(element)

    def screens(self):
        """Distinct consecutive frames, in order, without the repeats."""
        distinct = []
        for frame in self.frames:
            if not frame:
                continue
            if distinct and _same_frame(distinct[-1], frame):
                continue
            distinct.append(frame)
        return distinct[:MAX_FRAMES_PER_SCREEN]

    @property
    def truncated(self):
        return len(self.frames) > MAX_FRAMES_PER_SCREEN


def _same_frame(first, second):
    keys = ('type', 'text', 'src', 'pos', 'size', 'width', 'height', 'anchor')
    return [{key: element.get(key) for key in keys} for element in first] == [
        {key: element.get(key) for key in keys} for element in second
    ]


RECORDER = FrameRecorder()


class FakeWindow:
    def __init__(self):
        self.size = WINDOW_SIZE

    def flip(self):
        RECORDER.flip()


class FakeTextStim:
    def __init__(self, window, **kwargs):
        self.text = ''
        self.width = kwargs.get('wrapWidth', WINDOW_SIZE[0] * 0.8)
        self.height = kwargs.get('height', 22)
        self.pos = kwargs.get('pos', (0, 0))
        self.anchor = kwargs.get('anchorVert', 'center')

    def draw(self):
        RECORDER.record({
            'type': 'text', 'text': self.text, 'pos': self.pos,
            'width': self.width, 'height': self.height, 'anchor': self.anchor,
        })


class FakeImageStim:
    def __init__(self, window, image, **kwargs):
        from PIL import Image
        self.image = Path(image)
        self.size = tuple(Image.open(image).size)
        self.pos = (0, 0)

    def draw(self):
        RECORDER.record({
            'type': 'image', 'src': self.image.name, 'pos': self.pos, 'size': self.size,
        })


class FakeShapeStim:
    """Practice shapes; only their corner position matters for a text review."""

    def __init__(self, window, **kwargs):
        self.pos = (0, 0)
        self.size = tuple(config.IMAGE_SIZE)

    def draw(self):
        RECORDER.record({
            'type': 'image', 'src': '(shape)', 'pos': self.pos, 'size': self.size,
        })


class FakeVisual:
    TextStim = FakeTextStim
    ImageStim = FakeImageStim
    Circle = FakeShapeStim
    Rect = FakeShapeStim
    ShapeStim = FakeShapeStim


class FakeKeyboard:
    """Answers the given keys once, then SPACE forever, so pages advance."""

    def __init__(self, first=()):
        self.pending = list(first)

    def getKeys(self, **kwargs):
        from types import SimpleNamespace
        keys = self.pending or ['space']
        self.pending = []
        return [SimpleNamespace(name=key, rt=0.0) for key in keys]


class FakeClock:
    def __init__(self, advance=0.0):
        self.now = 0.0
        self.advance = advance

    def getTime(self):
        self.now += self.advance
        return self.now


class SimpleSound:
    def play(self):
        pass

    def stop(self):
        pass


def _css_box(pos, size):
    return (f'left:{WINDOW_SIZE[0] / 2 + pos[0] - size[0] / 2:.0f}px;'
            f'top:{WINDOW_SIZE[1] / 2 - (pos[1] + size[1] / 2):.0f}px;'
            f'width:{size[0]:.0f}px;height:{size[1]:.0f}px')


def _element_html(element):
    if element['type'] == 'image':
        return f'<img src="{html.escape(element["src"])}" style="{_css_box(element["pos"], element["size"])}">'
    lines = max(1, len(element['text'].splitlines()))
    block_height = lines * element['height'] * 1.35
    if element['anchor'] == 'top':
        top = WINDOW_SIZE[1] / 2 - element['pos'][1]
    else:
        top = WINDOW_SIZE[1] / 2 - element['pos'][1] - block_height / 2
    return (
        f'<div class="txt" style="left:{WINDOW_SIZE[0] / 2 + element["pos"][0] - element["width"] / 2:.0f}px;'
        f'top:{top:.0f}px;width:{element["width"]:.0f}px;font-size:{element["height"]:.0f}px;'
        f'line-height:{element["height"] * 1.35:.0f}px">{html.escape(element["text"])}</div>'
    )


def _practice_summary():
    """A pretend three-round practice result, for the summary screen."""
    tiers = [
        {'tier': 'easy', 'hits': 2, 'late': 0, 'misses': 1, 'false_alarms': 1},
        {'tier': 'medium', 'hits': 3, 'late': 0, 'misses': 1, 'false_alarms': 1},
        {'tier': 'hard', 'hits': 3, 'late': 0, 'misses': 1, 'false_alarms': 0},
    ]
    return {
        'tiers': tiers,
        'paced_hits': sum(tier['hits'] for tier in tiers),
        'paced_late': sum(tier['late'] for tier in tiers),
        'paced_misses': sum(tier['misses'] for tier in tiers),
        'paced_false_alarms': sum(tier['false_alarms'] for tier in tiers),
    }


def render(name, run, images):
    """Run one screen with fakes; return its title, frames and referenced images."""
    RECORDER.frames = [[]]
    try:
        run(FakeVisual)
    except Exception as exc:  # a screen needing live input still gets a slot
        return name, [[{'type': 'text', 'text': f'not rendered: {exc}', 'pos': (0, 0),
                        'width': 900, 'height': 24, 'anchor': 'center'}]], []
    for frame in RECORDER.frames:
        for element in frame:
            if element['type'] == 'image' and element['src'] != '(shape)':
                images.add(element['src'])
    return name, RECORDER.screens(), RECORDER.frames


def main():
    output_dir = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / 'build' / 'screen_mock')
    output_dir.mkdir(parents=True, exist_ok=True)
    images = set()
    sheets = []

    def sheet(name, run):
        title, frames, _ = render(name, run, images)
        sheets.append((title, frames))

    sheet('Hand Placement', lambda visual: screens.finger_placement(
        FakeWindow(), FakeKeyboard(), visual))
    sheet('Number Key Check', lambda visual: screens.numpad_check(
        FakeWindow(), FakeKeyboard(['num_4', 'num_5', 'num_1', 'num_2']), visual))
    sheet('Sound Check', lambda visual: screens.sound_check(
        FakeWindow(), FakeKeyboard(), visual, SimpleSound()))
    sheet('Instructions', lambda visual: screens.instructions(
        FakeWindow(), FakeKeyboard(), visual))
    sheet('How your responses are scored', lambda visual: screens.scoring_rules(
        FakeWindow(), FakeKeyboard(), visual))
    sheet('Practice intro', lambda visual: practice.intro(
        FakeWindow(), FakeKeyboard(), visual))
    sheet('Practice summary', lambda visual: practice._summary(
        FakeWindow(), FakeKeyboard(), visual, _practice_summary()))
    for index, tier in enumerate(practice.TIERS, start=1):
        sheet(
            f'Practice round {index} hold ({tier["tier"]})',
            lambda visual, tier=tier: practice._hold(
                FakeWindow(), FakeKeyboard(),
                practice._text(FakeWindow(), visual), tier['hold_text']),
        )
    sheet('Break', lambda visual: screens.rest_break(
        FakeWindow(), FakeKeyboard(), visual, FakeClock(advance=1.0)))

    for name in images:
        shutil.copy(screens._image_path(name), output_dir / name)

    cards = []
    for title, frames in sheets:
        stages = []
        for index, frame in enumerate(frames, start=1):
            label = f'{title} — page {index} of {len(frames)}' if len(frames) > 1 else title
            stages.append(
                f'<h2>{html.escape(label)}</h2>'
                f'<div class="stage">{"".join(_element_html(el) for el in frame)}</div>'
            )
        cards.append(f'<section>{"".join(stages)}</section>')

    page = f'''<!doctype html><meta charset="utf-8">
<title>Participant screens</title>
<style>
 body{{margin:0;background:#111;color:#ddd;font-family:DejaVu Sans,Arial,sans-serif}}
 h1{{font-size:20px;margin:24px 40px 0}}
 section{{margin:40px auto;width:{WINDOW_SIZE[0]}px}}
 h2{{font-size:16px;font-weight:normal;color:#8cf;margin:16px 0 8px}}
 .stage{{position:relative;width:{WINDOW_SIZE[0]}px;height:{WINDOW_SIZE[1]}px;
        background:#000;overflow:hidden;border:1px solid #333}}
 .txt{{position:absolute;color:#fff;text-align:center;white-space:pre-wrap}}
 img{{position:absolute;object-fit:fill}}
</style>
<h1>Participant screens — {WINDOW_SIZE[0]}×{WINDOW_SIZE[1]}, rendered from screens.py and practice.py</h1>
{''.join(cards)}'''
    (output_dir / 'screens.html').write_text(page)
    print(f'{sum(len(frames) for _, frames in sheets)} stages -> {output_dir / "screens.html"}')
    for title, frames in sheets:
        print(f'  {title}: {len(frames)} stage(s)')


if __name__ == '__main__':
    main()
