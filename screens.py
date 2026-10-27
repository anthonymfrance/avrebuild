"""Participant and operator screens. PsychoPy objects are passed in, never imported."""

from __future__ import annotations

import math
from pathlib import Path

import config
from config import BLOCK_LABELS
from scoring import inter_trial_row, trial_recap_lines

# Resolve the study root from this file's location, matching experiment.py's ROOT.
_ROOT = Path(__file__).resolve().parent
NUMPAD_IMAGE_NAME = '4-Corner Numpad Screen Visual.png'
FINGERS_IMAGE_NAME = 'Finger Placement Screen Visual.png'
HAND_PHOTO_NAME = 'Example Hand Placement Photo.jpg'


def _image_path(name):
    """Study root first, then the directory holding the configured background image."""
    candidates = (
        _ROOT / name,
        (_ROOT / config.BG_SOURCE_FILE).parent / name,
    )
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(
        f'Instruction visual {name!r} not found; looked in: '
        + ', '.join(str(path) for path in candidates)
    )


RESPONSE_KEYS = {
    'top_left': ('num_4', 'KP_Left'),
    'top_right': ('num_5', 'KP_Begin'),
    'bottom_left': ('num_1', 'KP_End'),
    'bottom_right': ('num_2', 'KP_Down'),
}
KEY_TO_CORNER = {
    key: corner for corner, keys in RESPONSE_KEYS.items() for key in keys
}
ALL_KEYS = list(KEY_TO_CORNER) + ['space', 'escape']
# "any animal" / "any object": the singular of the block label, so the block
# intro cannot drift from the block name. It lives here rather than in config
# because every config value is part of the snapshot that existing participant
# plans are validated against, and this is wording, not a study parameter.
BLOCK_TARGET_PHRASE = {
    block: f'any {label.lower().rstrip("s")}' for block, label in BLOCK_LABELS.items()
}
# The instructions and the scoring rules are shown one page at a time: each page
# is short enough to read in one look and waits for SPACE, so the participant
# never faces a full wall of text. Every page carries its own advance line.
INSTRUCTION_PAGES = (
    'The experiment has two parts: an animals part and an objects part.\n'
    'You will be told which part comes first for you.\n\n'
    'During the animals part, all animals are your targets.\n'
    'During the objects part, all objects are your targets.\n\n'
    'Press SPACE to continue.',

    'When a target appears, press the number key for the corner where it appeared.\n\n'
    'Do not press for pictures that are not your targets. In the animals part, for\n'
    'example, do not react to pictures of objects.\n\n'
    f'You will have {config.RESPONSE_WINDOW:g} seconds to get points for reacting\n'
    'after the target first appears.\n\n'
    'Press SPACE to continue.',

    'React correctly and the cross flashes green: that is a hit. Aim to get as many\n'
    'hits as you can.\n\n'
    'If you do not react in time you gain a miss or a late response; the next screen\n'
    'explains the difference.\n\n'
    'If you react to the wrong corner or to the wrong type of picture you gain a\n'
    'false alarm. Aim to keep these low.\n\n'
    'Press SPACE to continue.',
)

# The four outcomes the scorer actually produces, in the participant's words.
# Keep the numbers derived from config so the screen cannot drift from scoring.
SCORING_PAGES = (
    'How your responses are scored\n\n'
    f'Hit: the right number key within {config.RESPONSE_WINDOW:g} seconds of the target\n'
    'appearing. The cross flashes green.\n\n'
    f'Late: the right number key, but after {config.RESPONSE_WINDOW:g} seconds and within\n'
    f'{config.TARGET_CORNER_HOLD:g} seconds. A late response is not a miss.\n\n'
    'Press SPACE to continue.',

    f'Miss: no key in the target\'s corner within {config.TARGET_CORNER_HOLD:g} seconds.\n\n'
    'False alarm: a key in the wrong corner, a key for a picture that is not your\n'
    'target, or a key when no target is on screen.\n\n'
    'Press SPACE to continue.',

    'Only 1, 2, 4 and 5 count as responses. Any other key is ignored.\n\n'
    # "3 short rounds" mirrors practice.TIERS: screens.py cannot import practice
    # (practice imports screens), and a config value would be frozen into the
    # participant-plan snapshot.
    'Press SPACE to start the practice. There are 3 short rounds.',
)


def _text(window, visual, height=22, **kwargs):
    return visual.TextStim(
        window, text='', color='white', height=height,
        wrapWidth=window.size[0] * 0.8, units='pix', autoLog=False, **kwargs,
    )


def _fit_image(window, visual, path, max_fraction_w, max_fraction_h):
    """Build an ImageStim scaled to fit the given fractions of the window."""
    image = visual.ImageStim(window, image=str(path), units='pix', autoLog=False)
    img_w, img_h = image.size
    scale = min(
        (window.size[0] * max_fraction_w) / img_w,
        (window.size[1] * max_fraction_h) / img_h,
        1.0,
    )
    image.size = (img_w * scale, img_h * scale)
    return image


def finger_placement(window, kb, visual):
    """Show where to rest the fingers before the key check; False if ESCAPE."""
    win_w, win_h = window.size
    text = _text(
        window, visual, height=26,
        pos=(-win_w * 0.26, win_h * 0.38), anchorVert='top',
    )
    text.text = (
        'Hand Placement\n\n'
        'Here is an example hand position: one finger on the\n'
        'space bar and two on the number pad. Please use your\n'
        'dominant hand on the number pad.\n\n'
        'Rest your index finger between 4 and 1, and your\n'
        'middle finger between 5 and 2.\n'
        'Keep your fingers on the number pad between responses.\n\n'
        'Press SPACE when your hand is in place.'
    )
    text.wrapWidth = win_w * 0.46
    # The photo shows a real hand; the taller diagram stays beside it as the
    # labelled reference for which key each finger rests on.
    photo = _fit_image(window, visual, _image_path(HAND_PHOTO_NAME), 0.46, 0.38)
    photo.pos = (-win_w * 0.26, -win_h * 0.22)
    diagram = _fit_image(window, visual, _image_path(FINGERS_IMAGE_NAME), 0.30, 0.74)
    diagram.pos = (win_w * 0.30, 0)
    while True:
        text.draw()
        photo.draw()
        diagram.draw()
        window.flip()
        presses = kb.getKeys(keyList=['space', 'escape'], waitRelease=False, clear=True)
        if any(key.name == 'escape' for key in presses):
            return False
        if any(key.name == 'space' for key in presses):
            return True


def numpad_check(window, kb, visual):
    """Require each response key once; False if ESCAPE."""
    keys = ('num_4', 'num_5', 'num_1', 'num_2')
    names = {
        'num_4': 'top-left (4)', 'num_5': 'top-right (5)',
        'num_1': 'bottom-left (1)', 'num_2': 'bottom-right (2)',
    }
    win_w, win_h = window.size
    text = _text(window, visual, height=26, pos=(-win_w * 0.25, 0))
    text.wrapWidth = win_w * 0.44
    numpad = _fit_image(window, visual, _image_path(NUMPAD_IMAGE_NAME), 0.48, 0.62)
    numpad.pos = (win_w * 0.25, 0)
    seen = set()
    while len(seen) < len(keys):
        missing = [names[key] for key in keys if key not in seen]
        text.text = (
            'Number Key Check\n\n'
            'Press each of the four number keys shown here once.\n\n'
            f'Still to check: {", ".join(missing)}\n\n'
            'If a key does not work, turn Num Lock on and try again.'
        )
        text.draw()
        numpad.draw()
        window.flip()
        presses = kb.getKeys(keyList=list(keys) + ['escape'], waitRelease=False, clear=True)
        if any(key.name == 'escape' for key in presses):
            return False
        seen.update(key.name for key in presses)
    return True


def sound_check(window, kb, visual, test_tone):
    """Play the tone (R replays); True only when the participant reports hearing it."""
    text = _text(window, visual)
    text.text = (
        'Sound Check\n\n'
        'Listen for a short sound.\n\n'
        'Press R to hear it again.\n'
        'Press SPACE if you heard it.\n'
        'Press N if you did not hear it.'
    )
    test_tone.play()
    while True:
        text.draw()
        window.flip()
        presses = kb.getKeys(keyList=['space', 'r', 'n', 'escape'], waitRelease=False, clear=True)
        if any(key.name == 'escape' for key in presses):
            return False
        if any(key.name == 'r' for key in presses):
            test_tone.stop()
            test_tone.play()
        if any(key.name == 'space' for key in presses):
            return True
        if any(key.name == 'n' for key in presses):
            return False


def plan_summary(participant_id, rows, block_order, trials_by_block):
    """Operator debug-screen lines and the PT SOA per block (operator-only)."""
    pt_soa_by_block = {}
    for block in block_order:
        pt_soa_by_block[block] = {}
        for row in rows:
            if row['block'] == block and row['event_type'] == 'sound' and row['role'] == 'PT':
                pt_soa_by_block[block][row['stimulus']] = float(row['soa'])
    lines = [
        'STUDY SETUP — STIMULUS ASSIGNMENTS',
        f"Participant: {participant_id}    Block order: {' → '.join(BLOCK_LABELS[b] for b in block_order)}",
        f'Target response window: {config.RESPONSE_WINDOW:.1f} seconds',
        'PT SOA is fixed for each PT in this participant plan:',
        f'PD sound lead: {config.PD_SOA_MIN:.2f}–{config.PD_SOA_MAX:.2f} seconds',
        '',
    ]
    for block in block_order:
        block_rows = [row for row in rows if row['block'] == block]
        pt_counts = sum(row['event_type'] == 'visual' and row['role'] == 'PT' for row in block_rows)
        pd_counts = sum(row['event_type'] == 'visual' and row['role'] == 'PD' for row in block_rows)
        npd_counts = sum(row['event_type'] == 'visual' and row['role'] == 'NPD' for row in block_rows)
        lines.append(f"{BLOCK_LABELS[block]} BLOCK — target group: {BLOCK_LABELS[block]}")
        lines.append(
            '  PT SOA by target: ' + ', '.join(
                f'{name} = {soa:.1f}s' for name, soa in sorted(pt_soa_by_block[block].items())
            )
        )
        lines.append(f'  Events per block — PT: {pt_counts}, PD: {pd_counts}, NPD: {npd_counts}')
        for role, description in (
            ('PT', 'Targets with sound (PT)'),
            ('NPT', 'Targets without sound (NPT)'),
            ('PD', 'Distractors with sound (PD)'),
            ('NPD', 'Distractors without sound (NPD)'),
        ):
            names = sorted({row['stimulus'] for row in block_rows
                            if row['event_type'] == 'visual' and row['role'] == role})
            lines.append(f"  {description}: {', '.join(names) if names else 'none'}")
        lines.append(
            f"  Trials: {len(trials_by_block[block])}; visual events: "
            f"{sum(row['event_type'] == 'visual' for row in block_rows)}"
        )
        lines.append('')
    lines.append('Operator review: press SPACE to continue to the instructions.')
    return lines, pt_soa_by_block


def operator_screen(window, kb, visual, lines):
    """Show the operator debug screen; False if ESCAPE."""
    text = visual.TextStim(
        window, text='\n'.join(lines), color='white', height=20,
        wrapWidth=window.size[0] * 0.88, units='pix', autoLog=False,
    )
    while True:
        text.draw()
        window.flip()
        presses = kb.getKeys(keyList=['space', 'escape'], waitRelease=False, clear=True)
        if any(key.name == 'escape' for key in presses):
            return False
        if any(key.name == 'space' for key in presses):
            return True


def block_intro_message(block_index, block_count, block):
    """The page shown before each block. Targets are named as a group."""
    return (
        f'Block {block_index + 1} of {block_count}: {BLOCK_LABELS[block]}\n'
        f'Your target group is {BLOCK_LABELS[block].lower()}. Press the matching '
        f'numpad key when you see {BLOCK_TARGET_PHRASE[block]}.'
    )


def recap_pages(headline, hits, total_targets, late, misses, false_alarms):
    """The recap split over two pages, so neither page is a wall of text.

    The practice summary uses this too, so the two recaps cannot drift apart.
    The caller supplies the headline and adds its own SPACE line to each page.
    """
    lines = trial_recap_lines(hits, total_targets, late, misses, false_alarms)
    return (
        f'{headline}\n\n'
        + '\n'.join(lines[:2]),
        '\n'.join(lines[2:])
        + '\n\nRemember to respond to all targets quickly and accurately!',
    )


def trial_recap_messages(block, trial, hits, total_targets, late, misses, false_alarms):
    """The two pages shown after every trial, in the participant's words."""
    return recap_pages(
        f'{BLOCK_LABELS[block]} — Trial {trial} complete.',
        hits, total_targets, late, misses, false_alarms,
    )


def _pages(window, kb, visual, pages, height=24):
    """Show each page in turn, waiting for SPACE after every one; False if ESCAPE."""
    text = _text(window, visual, height=height)
    for page in pages:
        text.text = page
        while True:
            text.draw()
            window.flip()
            presses = kb.getKeys(keyList=['space', 'escape'], waitRelease=False, clear=True)
            if any(key.name == 'escape' for key in presses):
                return False
            if any(key.name == 'space' for key in presses):
                break
    return True


def instructions(window, kb, visual):
    """Show the task instructions, one page per SPACE; False if ESCAPE."""
    return _pages(window, kb, visual, INSTRUCTION_PAGES, height=26)


def scoring_rules(window, kb, visual):
    """Explain the four scored outcomes before practice; False if ESCAPE."""
    return _pages(window, kb, visual, SCORING_PAGES, height=26)


def continuation(window, kb, text, message, key_rows, block, trial):
    """Between-trial screen. Response keys are logged as inter_trial; False if ESCAPE."""
    text.text = message + '\n\nPress SPACE to continue.'
    while True:
        text.draw()
        window.flip()
        presses = kb.getKeys(keyList=ALL_KEYS, waitRelease=False, clear=True)
        for key in presses:
            if key.name in KEY_TO_CORNER:
                key_rows.append(inter_trial_row(
                    key.name, KEY_TO_CORNER[key.name], float(key.rt), block, trial,
                ))
        if any(key.name == 'escape' for key in presses):
            key = next(key for key in presses if key.name == 'escape')
            key_rows.append({
                'session_time': float(key.rt), 'key': key.name, 'corner': '',
                'classification': 'abort', 'matched_event_ids': '',
                'target_matches': '', 'correct': '',
                'response_window_overlap': False,
                'block': block, 'trial': trial,
            })
            return False
        if any(key.name == 'space' for key in presses):
            return True


def rest_break(window, kb, visual, clock, duration=config.BREAK_OFFER_SECONDS):
    """Count down a break; returns ('completed'|'aborted', seconds actually taken).

    The break ends at zero, so a participant who does not press anything still
    continues on their own. SPACE ends it early and ESCAPE aborts.
    """
    text = _text(window, visual, height=30)
    start = float(clock.getTime())
    while True:
        elapsed = float(clock.getTime()) - start
        remaining = max(0.0, duration - elapsed)
        text.text = (
            f'Break — the study continues on its own in {math.ceil(remaining)} seconds.\n\n'
            'Rest your eyes and hands, then carry on when you are ready.\n\n'
            'Press SPACE to continue now.'
        )
        text.draw()
        window.flip()
        presses = kb.getKeys(keyList=['space', 'escape'], waitRelease=False, clear=True)
        if any(key.name == 'escape' for key in presses):
            return 'aborted', elapsed
        if any(key.name == 'space' for key in presses):
            return 'completed', elapsed
        if remaining <= 0:
            return 'completed', float(clock.getTime()) - start
