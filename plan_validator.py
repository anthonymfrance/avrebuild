"""Independent check of a finished participant plan.

Re-derives every rule from config and the stimulus lists instead of trusting
the generator: it shares no checking code with slotting_key or timeline_key, so
a bug in placement cannot also hide in its own validation. Returns a list of
problems; an empty list means the plan is valid.
"""

import math
from collections import Counter, defaultdict

import config as c
from stimulus_split import ANIMATE, INANIMATE

EPS = 1e-9
CATEGORY = {'animate': set(ANIMATE), 'inanimate': set(INANIMATE)}
OTHER = {'animate': 'inanimate', 'inanimate': 'animate'}


def expected_trials_per_block(trials_per_pt=None):
    return c.PT_COUNT_PER_BLOCK * (c.TRIALS_PER_PT if trials_per_pt is None else trials_per_pt)


def _corner_rule_errors(label, corners, favored, bias):
    """The item's own corner gets round(n * bias); the others split the rest within one."""
    counts = Counter(corners)
    total = len(corners)
    if favored not in c.CORNERS:
        return [f'{label}: favoured corner {favored!r} is not one of {c.CORNERS}.']
    favored_count = math.floor(total * bias + 0.5)
    others = [counts[k] for k in c.CORNERS if k != favored]
    if counts[favored] != favored_count or sum(others) != total - favored_count \
            or max(others) - min(others) > 1:
        return [f'{label}: corner counts {dict(counts)} break the {bias:.0%} '
                f'{favored} rule for {total} appearances.']
    return []


def _even_rule_errors(label, corners):
    """Non-privileged roles spread their appearances over all four corners."""
    counts = Counter(corners)
    values = [counts[k] for k in c.CORNERS]
    if max(values) - min(values) > 1:
        return [f'{label}: corner counts {dict(counts)} are not split evenly.']
    return []


def validate_plan(assignment, slotting_rows, timeline, trials_per_pt=None, count_ranges=None):
    errors = []
    err = errors.append
    ranges = {'PT': c.TRIAL_PT_RANGE, 'NPT': c.TRIAL_NPT_RANGE,
              'PD': c.TRIAL_PD_RANGE, 'NPD': c.TRIAL_NPD_RANGE, **(count_ranges or {})}
    n_trials = expected_trials_per_block(trials_per_pt)
    per_pt = n_trials // c.PT_COUNT_PER_BLOCK
    blocks = list(assignment)

    # --- Stimulus assignment: categories, pool sizes, cross-block complement ---
    if sorted(blocks) != ['animate', 'inanimate']:
        return [f'Blocks {blocks} are not exactly animate and inanimate.']
    for block in blocks:
        roles = assignment[block]
        own, other = CATEGORY[block], CATEGORY[OTHER[block]]
        if len(roles['PT']) != c.PT_COUNT_PER_BLOCK or len(roles['PD']) != c.PD_COUNT_PER_BLOCK:
            err(f'{block}: {len(roles["PT"])} PTs / {len(roles["PD"])} PDs, expected '
                f'{c.PT_COUNT_PER_BLOCK} / {c.PD_COUNT_PER_BLOCK}.')
        lent = set(assignment[OTHER[block]]['PD'])
        if set(roles['PT']) | set(roles['NPT']) | lent != own or \
                len(roles['PT']) + len(roles['NPT']) + len(lent) != len(own):
            err(f'{block}: PT, NPT and the other block\'s PDs must partition the {block} items.')
        if set(roles['PD']) & set(roles['NPD']) or not set(roles['PD']) | set(roles['NPD']) <= other:
            err(f'{block}: PD and NPD must be disjoint {OTHER[block]} items.')
        if set(roles['PD']) | set(roles['NPD']) != other - set(assignment[OTHER[block]]['PT']):
            err(f'{block}: distractors must be every {OTHER[block]} item except that block\'s PTs.')

    # --- Slotting key: trial count, one active PT and PD per trial, balanced use ---
    for block in blocks:
        rows = [r for r in slotting_rows if r['block'] == block]
        trials = {int(r['trial']) for r in rows}
        if trials != set(range(1, n_trials + 1)):
            err(f'{block}: slotting trials {sorted(trials)[:3]}..., expected 1..{n_trials}.')
        for role in ('PT', 'PD'):
            active = {}
            for r in rows:
                if r['role'] == role:
                    active.setdefault(int(r['trial']), set()).add(r['item'])
            if any(len(v) != 1 for v in active.values()) or set(active) != trials:
                err(f'{block}: every trial needs exactly one active {role}.')
            uses = Counter(next(iter(v)) for v in active.values() if len(v) == 1)
            if set(uses) != set(assignment[block][role]) or set(uses.values()) != {per_pt}:
                err(f'{block}: {role} active-trial counts {dict(uses)}, expected {per_pt} each.')

    # --- Timeline rows: counts, sources, timing, audio ---
    visuals = [r for r in timeline if r['event_type'] == 'visual']
    sounds = [r for r in timeline if r['event_type'] == 'sound']
    if len({r['event_id'] for r in timeline}) != len(timeline):
        err('Duplicate event IDs.')
    if any(b['global_onset'] < a['global_onset'] for a, b in zip(timeline, timeline[1:])):
        err('Timeline is not in onset order.')
    if [r['event_index'] for r in timeline] != list(range(1, len(timeline) + 1)):
        err('event_index is not 1..N in row order.')
    if {(r['block'], r['trial']) for r in visuals} != {(b, t) for b in blocks for t in range(1, n_trials + 1)}:
        err(f'Timeline does not contain exactly {len(blocks) * n_trials} trials.')

    slot_by_id = {r['event_id']: r for r in slotting_rows}
    visuals_by_id = {r['event_id']: r for r in visuals}
    if set(slot_by_id) - set(visuals_by_id):
        err('A slotting row has no matching timeline visual.')
    for event_id, s in slot_by_id.items():
        r = visuals_by_id.get(event_id)
        if r is None:
            continue
        if (r['block'], r['trial'], r['role'], r['corner'], r['stimulus'],
                r.get('favored_corner', '')) != (
                s['block'], int(s['trial']), s['role'], s['corner'], s['item'],
                s.get('favored_corner', '')):
            err(f'{event_id}: differs from its slotting row.')

    role_counts = Counter((r['block'], r['trial'], r['role']) for r in visuals)
    for block in blocks:
        for trial in range(1, n_trials + 1):
            for role, (low, high) in ranges.items():
                if not low <= role_counts[(block, trial, role)] <= high:
                    err(f'{block} trial {trial}: {role_counts[(block, trial, role)]} {role} '
                        f'outside {low}..{high}.')
    for r in visuals:
        if r['stimulus'] not in assignment[r['block']][r['role']]:
            err(f'{r["event_id"]}: {r["stimulus"]} is not in the {r["block"]} {r["role"]} pool.')

    # Corner balance per identity is checked on the timeline itself.
    favored = defaultdict(dict)
    for row in slotting_rows:
        if row.get('favored_corner'):
            favored[row['block']][row['item']] = row['favored_corner']
    by_identity = defaultdict(list)
    for r in visuals_by_id.values():
        by_identity[(r['block'], r['role'], r['stimulus'])].append(r['corner'])
    for block in blocks:
        privileged = {
            row['item']: row['favored_corner'] for row in slotting_rows
            if row['block'] == block and row['role'] in ('PT', 'PD')
        }
        if len(privileged) != len(c.CORNERS) or set(privileged.values()) != set(c.CORNERS):
            err(f'{block}: privileged favoured corners {privileged} are not one per corner.')
    bias = {'PT': c.TARGET_SPATIAL_BIAS, 'PD': c.DISTRACTOR_SPATIAL_BIAS}
    for (block, role, item), corners in by_identity.items():
        if role in bias:
            errors.extend(_corner_rule_errors(
                f'{block} {role} {item}', corners, favored[block].get(item, ''), bias[role]))
        else:
            errors.extend(_even_rule_errors(f'{block} {role} {item}', corners))

    x_lo, y_lo = c.IMAGE_SIZE[0] / 2, c.IMAGE_SIZE[1] / 2
    x_hi, y_hi = c.WINDOW_SIZE[0] / 2 - x_lo, c.WINDOW_SIZE[1] / 2 - y_lo
    sound_by_source = {}
    for s in sounds:
        if s['source_event_id'] in sound_by_source:
            err(f'{s["source_event_id"]}: more than one sound.')
        sound_by_source[s['source_event_id']] = s
    soa_by_identity = {}
    for r in timeline:
        start = (blocks.index(r['block']) * n_trials + r['trial'] - 1) * c.TRIAL_DURATION
        content_start = start + c.TRIAL_BUFFER_DUR
        content_end = content_start + c.TRIAL_CONTENT_DUR
        if abs(r['trial_onset'] - (r['global_onset'] - start)) > 1e-6:
            err(f'{r["event_id"]}: trial_onset disagrees with global_onset.')
        expected_duration = c.VISUAL_DURATION if r['event_type'] == 'visual' else c.SOUND_DUR
        if abs(r['duration'] - expected_duration) > EPS:
            err(f'{r["event_id"]}: duration {r["duration"]}, expected {expected_duration}.')
        if r['global_onset'] < content_start - EPS or r['global_onset'] + r['duration'] > content_end + EPS:
            err(f'{r["event_id"]}: outside its trial content window.')
        if r['event_type'] == 'sound':
            continue
        sx, sy = c.CORNER_SIGNS[r['corner']]
        if not (x_lo - EPS <= sx * r['x'] <= x_hi + EPS and y_lo - EPS <= sy * r['y'] <= y_hi + EPS):
            err(f'{r["event_id"]}: position outside the {r["corner"]} quadrant.')
        is_target = r['role'] in c.TARGET_ROLES
        if r['response_window'] != (c.RESPONSE_WINDOW if is_target else ''):
            err(f'{r["event_id"]}: wrong response_window.')
        if is_target and r['global_onset'] + c.TARGET_CORNER_HOLD > start + c.TRIAL_DURATION + EPS:
            err(f'{r["event_id"]}: response plus late window runs past the trial.')
        sound = sound_by_source.get(r['event_id'])
        if (r['role'] in c.AUDIO_ROLES) != (sound is not None):
            err(f'{r["event_id"]}: {r["role"]} must{"" if r["role"] in c.AUDIO_ROLES else " not"} have a sound.')
        if sound is None:
            continue
        soa = r['global_onset'] + c.FADE_IN_DUR - sound['global_onset']
        low, high = (c.PT_SOA_MIN, c.PT_SOA_MAX) if r['role'] == 'PT' else (c.PD_SOA_MIN, c.PD_SOA_MAX)
        if not low - EPS <= soa <= high + EPS or abs(soa - sound['soa']) > 1e-6:
            err(f'{r["event_id"]}: SOA {soa:.4f} invalid.')
        if r['role'] in c.AUDIO_ROLES and abs(
                soa_by_identity.setdefault(
                    (r['role'], r['block'], r['stimulus']), soa) - soa) > 1e-6:
            err(f'{r["event_id"]}: {r["role"]} SOA differs from the identity\'s first SOA.')
    if len(sound_by_source) != len(sounds) or set(sound_by_source) - {r['event_id'] for r in visuals}:
        err('A sound has no matching PT/PD visual.')

    # --- Pairwise spacing, every pair within reach in each block ---
    max_soa = max([c.PT_SOA_MAX, c.PD_SOA_MAX] + [s['soa'] for s in sounds])
    vd = c.VISUAL_DURATION
    reach = max(c.MIN_VISUAL_ONSET_GAP, c.TARGET_CORNER_HOLD, vd + c.MIN_SAME_ITEM_GAP,
                vd + c.BETWEEN_PT_STIMULUS_GAP, vd + c.MIN_TARGET_END_TO_ONSET_GAP,
                c.RESPONSE_WINDOW, c.RESPONSE_WINDOW + max_soa - c.FADE_IN_DUR) + 1e-6
    for block in blocks:
        rows = sorted((r for r in visuals if r['block'] == block), key=lambda r: r['global_onset'])
        for i, a in enumerate(rows):
            for b in rows[i + 1:]:
                d = b['global_onset'] - a['global_onset']
                if d >= reach:
                    break
                gap = d - vd
                name = f'{block} {a["event_id"]} -> {b["event_id"]}'
                if d < c.MIN_VISUAL_ONSET_GAP - EPS:
                    err(f'{name}: onsets {d:.3f}s apart.')
                if a['corner'] == b['corner'] and (gap < -EPS or (
                        a['role'] in c.TARGET_ROLES and d < c.TARGET_CORNER_HOLD - EPS)):
                    err(f'{name}: same corner too soon.')
                if a['stimulus'] == b['stimulus'] and gap < c.MIN_SAME_ITEM_GAP - EPS:
                    err(f'{name}: same item too soon.')
                if a['role'] in c.TARGET_ROLES and b['role'] in c.TARGET_ROLES and (
                        gap < c.MIN_TARGET_END_TO_ONSET_GAP - EPS or d < c.RESPONSE_WINDOW - EPS):
                    err(f'{name}: targets too close.')
                if a['role'] == b['role'] == 'PT':
                    later_sound = sound_by_source.get(b['event_id'])
                    if gap < c.BETWEEN_PT_STIMULUS_GAP - EPS or (later_sound and later_sound[
                            'global_onset'] < a['global_onset'] + c.RESPONSE_WINDOW - EPS):
                        err(f'{name}: PT spacing or PT sound inside the previous response window.')
        block_sounds = sorted((s for s in sounds if s['block'] == block), key=lambda s: s['global_onset'])
        for a, b in zip(block_sounds, block_sounds[1:]):
            if b['global_onset'] - a['global_onset'] < c.SOUND_DUR + c.MIN_AUDIO_GAP - EPS:
                err(f'{block} {a["event_id"]} -> {b["event_id"]}: sounds too close.')
        sounds_by_item = defaultdict(list)
        for sound in block_sounds:
            sounds_by_item[sound['stimulus']].append(sound)
        for item_sounds in sounds_by_item.values():
            for a, b in zip(item_sounds, item_sounds[1:]):
                if b['global_onset'] - a['global_onset'] < c.SOUND_DUR + c.MIN_SAME_SOUND_GAP - EPS:
                    err(f'{block} {a["event_id"]} -> {b["event_id"]}: same sound too close.')
    return errors
