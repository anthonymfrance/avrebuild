"""Hardcoded practice. Same shapes for every participant. Nothing is logged.

PsychoPy objects are passed in; this module never imports PsychoPy.
"""

from __future__ import annotations

import config
from config import VISUAL_DURATION
from scoring import classify_press, finalize_targets
from screens import ALL_KEYS, KEY_TO_CORNER
from trial_runner import planned_image_alpha

KEY_NUMBER = {
    'top_left': '4',
    'top_right': '5',
    'bottom_left': '1',
    'bottom_right': '2',
}

# Circles are targets, squares are distractors. Onsets are seconds from the
# paced-round start. Gaps stay wider than the hit window plus the late window.
# Small fixed offsets from the quadrant center, in pixels. They keep the shapes
# from always appearing in exactly the same spot while staying identical for
# every participant. Values stay well inside each quadrant.
COACHED = (
    {
        'prompt': 'A circle is a target.\nThis one is in the top-right. Press 5.',
        'shapes': (('target', 'top_right', (30, -25)),),
        'expect': 'top_right',
    },
    {
        'prompt': (
            'A square is not a target.\n'
            'Do not press a number key.\n'
            'Press SPACE to continue.'
        ),
        'shapes': (('distractor', 'bottom_left', (-35, 30)),),
        'expect': None,
    },
    {
        'prompt': 'Press only for the circle.\nThe circle is in the top-left. Press 4.',
        'shapes': (
            ('target', 'top_left', (-25, -35)),
            ('distractor', 'bottom_right', (40, 25)),
        ),
        'expect': 'top_left',
    },
)
PACED = (
    (0.8, 'target', 'top_right'),
    (2.4, 'distractor', 'bottom_left'),
    (4.0, 'target', 'bottom_right'),
    (5.6, 'distractor', 'top_left'),
    (7.2, 'target', 'top_left'),
)
PACED_OFFSETS = (
    (25, 20),
    (-30, -25),
    (35, -30),
    (-40, 25),
    (20, -35),
)


def corner_xy(width, height, corner, offset=(0, 0)):
    """Fixed center of a practice shape, moved by a fixed per-event offset."""
    sx, sy = config.CORNER_SIGNS[corner]
    dx, dy = offset
    return (sx * width * 0.32 + dx, sy * height * 0.28 + dy)


def paced_targets(events=PACED):
    """Target rows in the shape classify_press already scores."""
    targets = []
    for index, (onset, kind, corner) in enumerate(events):
        if kind != 'target':
            continue
        targets.append({
            'event_id': f'practice-{index}',
            'corner': corner,
            '_actual_onset': onset,
            '_planned_runtime': onset,
            'response_status': 'pending',
            'timing_flags': '',
        })
    return targets


def paced_end(events=PACED):
    last = max(onset for onset, _, _ in events)
    return last + config.RESPONSE_WINDOW + config.LATE_WINDOW + 0.3


def intro(window, kb, visual):
    """'start', 'skipped', or 'abort'."""
    text = _text(window, visual)
    text.text = (
        'Practice\n\n'
        'Circles are targets. Squares are not.\n'
        'Everyone sees this same practice. It is not part of your score.\n\n'
        'Press SPACE to start.\n'
        'Operator: press S to skip.'
    )
    while True:
        text.draw()
        window.flip()
        presses = kb.getKeys(keyList=['space', 's', 'escape'], waitRelease=False, clear=True)
        if any(key.name == 'escape' for key in presses):
            return 'abort'
        if any(key.name == 's' for key in presses):
            return 'skipped'
        if any(key.name == 'space' for key in presses):
            return 'start'


def run(window, kb, visual, fixation, clock):
    """'completed', 'skipped', or 'abort'. Draws nothing into the trial logs."""
    try:
        decision = intro(window, kb, visual)
        if decision != 'start':
            return decision
        stims = _make_shapes(window, visual)
        text = _text(window, visual)
        kb.clearEvents()
        for step in COACHED:
            if _coached(window, kb, clock, fixation, text, stims, step) == 'abort':
                return 'abort'
        if _hold(
            window, kb, text,
            'Now at the real speed.\n'
            f'Circles only. You have {config.RESPONSE_WINDOW:g} seconds.\n'
            'The cross flashes green when you are correct.\n\n'
            'Press SPACE to start.',
        ) == 'abort':
            return 'abort'
        outcome, targets, false_alarms = _paced(window, kb, clock, fixation, text, stims)
        if outcome == 'abort':
            return 'abort'
        if _summary(window, kb, visual, targets, false_alarms) == 'abort':
            return 'abort'
        return 'completed'
    finally:
        fixation.lineColor = config.FIXATION_COLOR


def _make_shapes(window, visual):
    common = dict(fillColor='white', lineColor='white', units='pix', autoLog=False)
    return {
        'target': visual.Circle(window, radius=config.IMAGE_SIZE[0] / 2, **common),
        'distractor': visual.Rect(
            window, width=config.IMAGE_SIZE[0], height=config.IMAGE_SIZE[1], **common,
        ),
    }


def _text(window, visual, height=26):
    win_h = window.size[1]
    return visual.TextStim(
        window, text='', color='white', height=height,
        wrapWidth=window.size[0] * 0.75, units='pix', autoLog=False,
        pos=(0, win_h * 0.5 - 36), anchorVert='top',
    )


def _frame(window, fixation, text, shapes, caption, green):
    fixation.lineColor = config.FIXATION_HIT_COLOR if green else config.FIXATION_COLOR
    fixation.draw()
    for stim, pos, opacity in shapes:
        stim.pos = pos
        stim.opacity = opacity
        stim.draw()
    text.text = caption
    text.draw()
    window.flip()


def _coached(window, kb, clock, fixation, text, stims, step):
    width, height = window.size
    placed = [
        (stims[kind], corner_xy(width, height, corner, offset))
        for kind, corner, offset in step['shapes']
    ]
    notice = ''
    expect = step['expect']
    while True:
        caption = step['prompt'] if not notice else f"{step['prompt']}\n\n{notice}"
        _frame(
            window, fixation, text,
            [(stim, pos, 1.0) for stim, pos in placed], caption, False,
        )
        presses = kb.getKeys(keyList=ALL_KEYS, waitRelease=False, clear=True)
        if any(key.name == 'escape' for key in presses):
            return 'abort'
        if expect is None:
            if any(key.name in KEY_TO_CORNER for key in presses):
                notice = 'That would be a false alarm. Squares are not targets.'
            elif any(key.name == 'space' for key in presses):
                return 'ok'
            continue
        for press in presses:
            corner = KEY_TO_CORNER.get(press.name)
            if corner is None:
                continue
            if corner == expect:
                return _acknowledge(window, kb, clock, fixation, text, placed)
            notice = _miss_notice(corner, expect, step['shapes'])


def _miss_notice(pressed, expect, shapes):
    if any(kind == 'distractor' and corner == pressed for kind, corner, _ in shapes):
        return 'That corner has a square. Squares are not targets.'
    label = expect.replace('_', '-')
    return (
        f'That key is a different corner. '
        f'This circle is the {label} ({KEY_NUMBER[expect]}).'
    )


def _acknowledge(window, kb, clock, fixation, text, placed):
    until_green = clock.getTime() + config.FIXATION_FLASH_DUR
    until_done = clock.getTime() + 0.8
    while clock.getTime() < until_done:
        _frame(
            window, fixation, text,
            [(stim, pos, 1.0) for stim, pos in placed], 'Correct.',
            clock.getTime() < until_green,
        )
        presses = kb.getKeys(keyList=ALL_KEYS, waitRelease=False, clear=True)
        if any(key.name == 'escape' for key in presses):
            return 'abort'
    return 'ok'


def _hold(window, kb, text, message):
    text.text = message
    while True:
        text.draw()
        window.flip()
        presses = kb.getKeys(keyList=['space', 'escape'], waitRelease=False, clear=True)
        if any(key.name == 'escape' for key in presses):
            return 'abort'
        if any(key.name == 'space' for key in presses):
            return 'ok'


def _paced(window, kb, clock, fixation, text, stims):
    width, height = window.size
    targets = paced_targets()
    t0 = float(clock.getTime())
    green_until = -1.0
    false_alarms = 0
    kb.clearEvents()
    while float(clock.getTime()) - t0 < paced_end():
        now = float(clock.getTime()) - t0
        drawn = []
        for index, (onset, kind, corner) in enumerate(PACED):
            age = now - onset
            if 0 <= age < VISUAL_DURATION:
                drawn.append((
                    stims[kind], corner_xy(width, height, corner, PACED_OFFSETS[index]),
                    planned_image_alpha(age),
                ))
        _frame(
            window, fixation, text, drawn, 'Circles only.',
            float(clock.getTime()) < green_until,
        )
        for press in kb.getKeys(keyList=ALL_KEYS, waitRelease=False, clear=True):
            if press.name == 'escape':
                return 'abort', targets, false_alarms
            corner = KEY_TO_CORNER.get(press.name)
            if corner is None:
                continue
            row, chosen = classify_press(
                press.name, corner, float(press.rt) - t0,
                targets, config.RESPONSE_WINDOW, config.LATE_WINDOW, targets,
            )
            if chosen is not None:
                chosen['response_status'] = row['classification']
            if row['classification'] == 'hit':
                green_until = float(press.rt) + config.FIXATION_FLASH_DUR
            elif row['classification'] == 'false_alarm':
                false_alarms += 1
    finalize_targets(targets, True)
    return 'ok', targets, false_alarms


def _summary(window, kb, visual, targets, false_alarms):
    hits = sum(row['response_status'] == 'hit' for row in targets)
    late = sum(row['response_status'] == 'late' for row in targets)
    misses = sum(row['response_status'] == 'miss' for row in targets)
    text = _text(window, visual)
    text.text = (
        'Practice complete.\n\n'
        f'Correct hits: {hits}\n'
        f'Late responses: {late}\n'
        f'Misses: {misses}\n'
        f'False alarms: {false_alarms}\n\n'
        'The real task is the same, with animal photos and object photos\n'
        'instead of circles and squares. Some pictures play a sound.\n'
        'You still respond only to the target pictures.\n\n'
        'Press SPACE to begin the study.'
    )
    while True:
        text.draw()
        window.flip()
        presses = kb.getKeys(keyList=['space', 'escape'], waitRelease=False, clear=True)
        if any(key.name == 'escape' for key in presses):
            return 'abort'
        if any(key.name == 'space' for key in presses):
            return 'ok'
