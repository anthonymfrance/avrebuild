"""Hardcoded practice: coached steps, then three paced rounds that get harder.

The script is fixed for every participant (no RNG), so practice is identical
across sessions and subjects. Everything with a config equivalent -- shape size,
fade profile, response window, corner signs -- is read from config, so practice
cannot drift from the real task. Only the content is hardcoded: which corner,
target or distractor, and how densely the shapes appear.

Difficulty is item density, never the response window: RESPONSE_WINDOW is the
same in all three rounds and in the real task.

Rows are returned to the caller so practice can be saved even when it is
skipped or aborted; nothing here writes files.

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
# every participant. Values stay well inside each quadrant, and two shapes in
# the same corner never share an offset.
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

# Round 1: one shape at a time, nothing else on screen while a target's window
# is open. 5 items, 1.6 s apart.
EASY = (
    (0.8, 'target', 'top_right'),
    (2.4, 'distractor', 'bottom_left'),
    (4.0, 'target', 'bottom_right'),
    (5.6, 'distractor', 'top_left'),
    (7.2, 'target', 'top_left'),
)
EASY_OFFSETS = (
    (25, 20),
    (-30, -25),
    (35, -30),
    (-40, 25),
    (20, -35),
)

# Round 2: more pictures, closer together, but still only one on screen at a
# time (gaps stay above VISUAL_DURATION). 9 items, 0.7-0.9 s apart.
MEDIUM = (
    (0.60, 'target', 'top_right'),
    (1.30, 'distractor', 'bottom_left'),
    (2.10, 'target', 'top_left'),
    (3.00, 'distractor', 'bottom_right'),
    (3.90, 'distractor', 'top_right'),
    (4.80, 'distractor', 'bottom_left'),
    (5.70, 'target', 'bottom_right'),
    (6.60, 'distractor', 'top_left'),
    (7.40, 'target', 'top_right'),
)
MEDIUM_OFFSETS = (
    (30, -25),
    (-35, 30),
    (-25, -35),
    (40, 25),
    (25, 30),
    (-30, 20),
    (35, -30),
    (-40, 25),
    (20, -35),
)

# Round 3: the real item density from a generated trial (1.4-2.2 items/s), so
# the next shape is already fading in while the previous one fades out and each
# target's window spans two later onsets. The gaps still respect every rule the
# timeline enforces: MIN_VISUAL_ONSET_GAP, target onsets at least RESPONSE_WINDOW
# apart, and a target's corner empty for TARGET_CORNER_HOLD.
HARD = (
    (0.50, 'target', 'top_right'),
    (0.95, 'distractor', 'bottom_left'),
    (1.35, 'distractor', 'bottom_right'),
    (1.75, 'distractor', 'top_left'),
    (2.10, 'target', 'bottom_left'),
    (2.55, 'distractor', 'bottom_right'),
    (2.95, 'distractor', 'top_left'),
    (3.55, 'distractor', 'bottom_left'),
    (3.95, 'distractor', 'top_right'),
    (4.35, 'target', 'bottom_right'),
    (4.75, 'distractor', 'top_left'),
    (5.15, 'distractor', 'bottom_left'),
    (5.55, 'distractor', 'top_right'),
    (5.95, 'distractor', 'bottom_right'),
    (6.35, 'target', 'top_left'),
    (6.75, 'distractor', 'bottom_right'),
    (7.15, 'distractor', 'bottom_left'),
    (7.55, 'distractor', 'top_right'),
)
HARD_OFFSETS = (
    (30, -25),
    (-35, 25),
    (40, 20),
    (-25, -35),
    (-25, 35),
    (35, -30),
    (-40, 25),
    (25, 20),
    (25, 30),
    (-20, -35),
    (30, 20),
    (-20, -40),
    (-20, -30),
    (30, 35),
    (20, -25),
    (-35, 20),
    (30, -25),
    (35, -30),
)

# The order participants see, and the words they read between rounds.
TIERS = (
    {
        'tier': 'easy',
        'events': EASY,
        'offsets': EASY_OFFSETS,
        'caption': 'Circles only.',
        'hold_text': (
            'Round 1 of 3: at an easy pace.\n'
            'One picture at a time.\n'
            'Press the number key for the corner with the circle.\n\n'
            'Press SPACE to start.'
        ),
    },
    {
        'tier': 'medium',
        'events': MEDIUM,
        'offsets': MEDIUM_OFFSETS,
        'caption': 'Circles only.',
        'hold_text': (
            'Round 2 of 3: a bit faster.\n'
            'More pictures, one after another. Still one at a time.\n\n'
            'Press SPACE to start.'
        ),
    },
    {
        'tier': 'hard',
        'events': HARD,
        'offsets': HARD_OFFSETS,
        'caption': 'Circles only.',
        'hold_text': (
            'Round 3 of 3: the real speed.\n'
            f'Circles only. You have {config.RESPONSE_WINDOW:g} seconds.\n'
            'The cross flashes green when you are correct.\n\n'
            'Press SPACE to start.'
        ),
    },
)


def corner_xy(width, height, corner, offset=(0, 0)):
    """Fixed center of a practice shape, moved by a fixed per-event offset."""
    sx, sy = config.CORNER_SIGNS[corner]
    dx, dy = offset
    return (sx * width * 0.32 + dx, sy * height * 0.28 + dy)


def paced_targets(events, prefix):
    """Target rows in the shape classify_press already scores."""
    targets = []
    for index, (onset, kind, corner) in enumerate(events):
        if kind != 'target':
            continue
        targets.append({
            'event_id': f'{prefix}-{index}',
            'corner': corner,
            '_actual_onset': onset,
            '_planned_runtime': onset,
            'response_status': 'pending',
            'timing_flags': '',
        })
    return targets


def paced_end(events):
    last = max(onset for onset, _, _ in events)
    return last + config.RESPONSE_WINDOW + config.LATE_WINDOW + 0.3


def _row(phase, step='', event_id='', time_seconds='', key='', corner='',
         expected_corner='', classification='', rt_seconds='', outcome='', tier=''):
    """One practice_log.csv row; blank fields stay blank."""
    return {
        'tier': tier, 'phase': phase, 'step': step, 'event_id': event_id,
        'time_seconds': time_seconds, 'key': key, 'corner': corner,
        'expected_corner': expected_corner, 'classification': classification,
        'rt_seconds': rt_seconds, 'outcome': outcome,
    }


def intro(window, kb, visual):
    """'start', 'skipped', or 'abort'."""
    text = _text(window, visual)
    text.text = (
        'Practice\n\n'
        'Circles are targets. Squares are not.\n'
        'Everyone sees this same practice. It is not part of your score.\n\n'
        f'There are {len(TIERS)} short rounds. Each one is a little faster.\n\n'
        'Press SPACE to start.'
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
    """Run practice and return {'status', 'rows', 'summary'}.

    status is 'completed', 'skipped', or 'abort'. rows are practice_log.csv
    rows, collected even when the participant skips or aborts, so the caller can
    still save what happened. summary['tiers'] holds one entry per round, in the
    order they were run.
    """
    started = float(clock.getTime())
    rows = []
    summary = {
        'status': 'completed',
        'duration_seconds': 0.0,
        'coached_steps': len(COACHED),
        'coached_corrections': 0,
        'paced_hits': 0,
        'paced_late': 0,
        'paced_misses': 0,
        'paced_false_alarms': 0,
        'skipped_at_tier': '',
        'tiers': [],
    }

    def finish(status):
        summary['status'] = status
        summary['duration_seconds'] = float(clock.getTime()) - started
        return {'status': status, 'rows': rows, 'summary': summary}

    try:
        decision = intro(window, kb, visual)
        if decision != 'start':
            rows.append(_row(
                'intro', classification=decision, outcome='practice_not_run',
            ))
            return finish('abort' if decision == 'abort' else 'skipped')
        stims = _make_shapes(window, visual)
        text = _text(window, visual)
        kb.clearEvents()
        for step_number, step in enumerate(COACHED, start=1):
            outcome = _coached(
                window, kb, clock, fixation, text, stims, step, step_number, rows,
            )
            if outcome == 'abort':
                return finish('abort')
            if outcome == 'corrected':
                summary['coached_corrections'] += 1
        for tier in TIERS:
            decision = _hold(window, kb, text, tier['hold_text'], allow_skip=True)
            if decision == 'abort':
                return finish('abort')
            if decision == 'skip':
                # The operator may end practice at any round change; the rows
                # collected so far are kept and the status is 'skipped'.
                rows.append(_row(
                    'intro', classification='skipped',
                    outcome='practice_not_run', tier=tier['tier'],
                ))
                summary['skipped_at_tier'] = tier['tier']
                return finish('skipped')
            tier_started = float(clock.getTime())
            outcome, targets, false_alarms = _paced(
                window, kb, clock, fixation, text, stims, rows, tier,
            )
            hits = sum(target['response_status'] == 'hit' for target in targets)
            late = sum(target['response_status'] == 'late' for target in targets)
            misses = sum(target['response_status'] == 'miss' for target in targets)
            summary['paced_hits'] += hits
            summary['paced_late'] += late
            summary['paced_misses'] += misses
            summary['paced_false_alarms'] += false_alarms
            summary['tiers'].append({
                'tier': tier['tier'],
                'events': len(tier['events']),
                'duration_seconds': float(clock.getTime()) - tier_started,
                'hits': hits, 'late': late, 'misses': misses,
                'false_alarms': false_alarms,
                'outcome': 'abort' if outcome == 'abort' else 'completed',
            })
            if outcome == 'abort':
                return finish('abort')
        if _summary(window, kb, visual, summary) == 'abort':
            return finish('abort')
        return finish('completed')
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


def _coached(window, kb, clock, fixation, text, stims, step, step_number, rows):
    """One coached step. Returns 'ok', 'corrected', or 'abort'."""
    width, height = window.size
    placed = [
        (stims[kind], corner_xy(width, height, corner, offset))
        for kind, corner, offset in step['shapes']
    ]
    notice = ''
    expect = step['expect']
    corrected = False
    while True:
        caption = step['prompt'] if not notice else f"{step['prompt']}\n\n{notice}"
        _frame(
            window, fixation, text,
            [(stim, pos, 1.0) for stim, pos in placed], caption, False,
        )
        presses = kb.getKeys(keyList=ALL_KEYS, waitRelease=False, clear=True)
        if any(key.name == 'escape' for key in presses):
            return 'abort'
        number_presses = [press for press in presses if press.name in KEY_TO_CORNER]
        if expect is None:
            for press in number_presses:
                corrected = True
                rows.append(_row(
                    'coached', step_number, '', float(press.rt), press.name,
                    KEY_TO_CORNER[press.name], '', 'false_alarm', '',
                    tier='coached',
                ))
                notice = 'That would be a false alarm. Squares are not targets.'
            if any(key.name == 'space' for key in presses):
                rows.append(_row(
                    'coached', step_number, classification='step_result',
                    outcome='false_alarm_prompted' if corrected else 'no_false_alarm',
                    tier='coached',
                ))
                return 'corrected' if corrected else 'ok'
            continue
        for press in number_presses:
            corner = KEY_TO_CORNER[press.name]
            if corner == expect:
                rows.append(_row(
                    'coached', step_number, '', float(press.rt), press.name,
                    corner, expect, 'correct', '', tier='coached',
                ))
                rows.append(_row(
                    'coached', step_number, classification='step_result',
                    outcome='corrected' if corrected else 'first_try',
                    tier='coached',
                ))
                if _acknowledge(window, kb, clock, fixation, text, placed) == 'abort':
                    return 'abort'
                return 'corrected' if corrected else 'ok'
            corrected = True
            rows.append(_row(
                'coached', step_number, '', float(press.rt), press.name,
                corner, expect, 'wrong_corner', '', tier='coached',
            ))
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


def _hold(window, kb, text, message, allow_skip=False):
    """Wait for SPACE. Returns 'ok', 'skip' (operator ending practice), or 'abort'."""
    text.text = message
    key_list = ['space', 'escape'] + (['s'] if allow_skip else [])
    while True:
        text.draw()
        window.flip()
        presses = kb.getKeys(keyList=key_list, waitRelease=False, clear=True)
        if any(key.name == 'escape' for key in presses):
            return 'abort'
        if allow_skip and any(key.name == 's' for key in presses):
            return 'skip'
        if any(key.name == 'space' for key in presses):
            return 'ok'


def _paced(window, kb, clock, fixation, text, stims, rows, tier):
    """One paced round. Returns ('ok'|'abort', targets, false_alarms)."""
    width, height = window.size
    events = tier['events']
    offsets = tier['offsets']
    targets = paced_targets(events, tier['tier'])
    t0 = float(clock.getTime())
    green_until = -1.0
    false_alarms = 0
    kb.clearEvents()
    aborted = False
    while float(clock.getTime()) - t0 < paced_end(events):
        now = float(clock.getTime()) - t0
        drawn = []
        for index, (onset, kind, corner) in enumerate(events):
            age = now - onset
            if 0 <= age < VISUAL_DURATION:
                drawn.append((
                    stims[kind], corner_xy(width, height, corner, offsets[index]),
                    planned_image_alpha(age),
                ))
        _frame(
            window, fixation, text, drawn, tier['caption'],
            float(clock.getTime()) < green_until,
        )
        for press in kb.getKeys(keyList=ALL_KEYS, waitRelease=False, clear=True):
            if press.name == 'escape':
                aborted = True
                break
            corner = KEY_TO_CORNER.get(press.name)
            if corner is None:
                rows.append(_row(
                    'paced', '', '', float(press.rt) - t0, press.name, '',
                    '', 'ignored_key', '', tier=tier['tier'],
                ))
                continue
            row, chosen = classify_press(
                press.name, corner, float(press.rt) - t0,
                targets, config.RESPONSE_WINDOW, config.LATE_WINDOW, targets,
            )
            if chosen is not None:
                chosen['response_status'] = row['classification']
                chosen['response_key'] = press.name
                chosen['rt_from_actual_onset'] = row['rt_from_actual_onset']
            rows.append(_row(
                'paced', '', '', float(press.rt) - t0, press.name, corner, '',
                row['classification'], row['rt_from_actual_onset'],
                tier=tier['tier'],
            ))
            if row['classification'] == 'hit':
                green_until = float(press.rt) + config.FIXATION_FLASH_DUR
            elif row['classification'] == 'false_alarm':
                false_alarms += 1
        if aborted:
            break
    finalize_targets(targets, not aborted)
    for target in targets:
        rows.append(_row(
            'paced', '', target['event_id'], target['_actual_onset'],
            target.get('response_key', ''), target['corner'], target['corner'],
            target['response_status'], target.get('rt_from_actual_onset', ''),
            tier=tier['tier'],
        ))
    return ('abort' if aborted else 'ok'), targets, false_alarms


def _summary(window, kb, visual, summary):
    rounds = '\n'.join(
        f'Round {index} of {len(TIERS)} ({tier["tier"]}):   hits {tier["hits"]}, '
        f'late {tier["late"]}, misses {tier["misses"]}, '
        f'false alarms {tier["false_alarms"]}'
        for index, tier in enumerate(summary['tiers'], start=1)
    )
    text = _text(window, visual)
    text.text = (
        'Practice complete.\n\n'
        f'{rounds}\n\n'
        f'Total: hits {summary["paced_hits"]}, late {summary["paced_late"]}, '
        f'misses {summary["paced_misses"]}, '
        f'false alarms {summary["paced_false_alarms"]}.\n\n'
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
