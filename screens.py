"""Participant and operator screens. PsychoPy objects are passed in, never imported."""

from __future__ import annotations

import math

import config
from config import BLOCK_LABELS
from scoring import inter_trial_row

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
INSTRUCTIONS = (
    'Your goal is to press the numpad key for the corner containing your target image.\n'
    'When you see a target, respond within '
    f'{config.RESPONSE_WINDOW:g} seconds. Ignore other images.\n'
    'Please keep your eyes near the center fixation cross and shift your attention\n'
    'toward the corners as needed. You may notice patterns; keep following the task.\n\n'
    '                 TOP\n'
    '        4                 5\n'
    '     top left          top right\n\n'
    '        1                 2\n'
    '  bottom left      bottom right\n'
    '              BOTTOM\n\n'
    'Press SPACE to begin. Press ESCAPE to stop the study.'
)


def _text(window, visual, height=28, **kwargs):
    return visual.TextStim(
        window, text='', color='white', height=height,
        wrapWidth=window.size[0] * 0.8, units='pix', autoLog=False, **kwargs,
    )


def numpad_check(window, kb, visual):
    """Require each response key once; False if ESCAPE."""
    keys = ('num_4', 'num_5', 'num_1', 'num_2')
    names = {
        'num_4': 'top-left (4)', 'num_5': 'top-right (5)',
        'num_1': 'bottom-left (1)', 'num_2': 'bottom-right (2)',
    }
    text = _text(window, visual)
    seen = set()
    while len(seen) < len(keys):
        missing = [names[key] for key in keys if key not in seen]
        text.text = (
            'Numpad check\n\n'
            'Press each indicated key on the numeric keypad once.\n'
            f'Still to check: {", ".join(missing)}\n\n'
            'If a key does not register, turn Num Lock on and try again.\n'
            'Press ESCAPE to stop.'
        )
        text.draw()
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
        'Sound check\n\nA short tone will play. '
        'Press R to replay it, SPACE if you heard it, N if you did not, or ESCAPE to stop.'
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


def instructions(window, kb, visual):
    """Show the task instructions; False if ESCAPE."""
    text = _text(window, visual)
    text.text = INSTRUCTIONS
    window.flip()
    text.draw()
    window.flip()
    while True:
        text.draw()
        window.flip()
        presses = kb.getKeys(keyList=['space', 'escape'], waitRelease=False, clear=True)
        if any(key.name == 'escape' for key in presses):
            return False
        if any(key.name == 'space' for key in presses):
            return True


def continuation(window, kb, text, message, key_rows, block, trial):
    """Between-trial screen. Response keys are logged as inter_trial; False if ESCAPE."""
    text.text = message + '\n\nPress SPACE to continue. Press ESCAPE to stop.'
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


def rest_break(window, kb, visual, clock, duration_seconds=120):
    """Timed rest; SPACE continues only after it ends. False if ESCAPE."""
    text = _text(window, visual, height=30)
    rest_start = clock.getTime()
    while True:
        remaining = max(0, math.ceil(duration_seconds - (clock.getTime() - rest_start)))
        if remaining:
            text.text = (
                'You have a 2-minute rest break.\n\n'
                f'{remaining // 60}:{remaining % 60:02d} remaining.\n\n'
                'Press ESCAPE to stop.'
            )
        else:
            text.text = 'Rest break complete.\n\nPress SPACE to continue. Press ESCAPE to stop.'
        text.draw()
        window.flip()
        presses = kb.getKeys(keyList=['space', 'escape'], waitRelease=False, clear=True)
        if any(key.name == 'escape' for key in presses):
            return False
        if remaining == 0 and any(key.name == 'space' for key in presses):
            return True
