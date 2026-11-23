"""Build the seeded, immutable per-participant slotting key.

The key decides the privileged pairing only: which PT and which PD are active on
each trial, how many instances each of those two gets, and which corner every one
of those appearances uses. Non-privileged items are sampled per trial when the
timeline is generated, so they stay out of this file; only their corner split is
controlled, and that happens where the events are created.

Roles here:
    PT  privileged target      one active per trial, 80/20 to its own corner
    PD  privileged distractor  one active per trial, 80/20 to its own corner

PTs and PDs are shuffled independently, so the pairing of a trial's PT with its
PD is random: the same PT can meet either PD across its trials.
"""

import csv
import math
from collections import defaultdict
from pathlib import Path

from config import (
    CORNERS,
    DISTRACTOR_SPATIAL_BIAS,
    TARGET_SPATIAL_BIAS,
    TRIAL_PD_RANGE,
    TRIAL_PT_RANGE,
)
from stimulus_split import active_sequence, write_stimulus_assignment


ROLE_ORDER = ('PT', 'PD')

BASE_FIELDS = [
    'block',
    'trial',
    'role',
    'item',
    'slot_number',
    'trial_role_count',
    'total_appearances',
    'corner',
    'favored_corner',
    'event_id',
]
CORNER_COUNT_FIELDS = [f'corner_count_{corner}' for corner in CORNERS]
FIELDNAMES = BASE_FIELDS + CORNER_COUNT_FIELDS
CORNER_PLAN_FIELDS = ('block', 'role', 'item', 'favored_corner')


def corner_pile(total, favored, rng, bias):
    """Privileged pile: `bias` of the appearances in the item's own corner.

    The remainder is spread as evenly as the other three corners allow, and any
    leftover goes to randomly chosen corners.
    """
    if favored not in CORNERS:
        raise ValueError(f'Favoured corner {favored!r} is not one of {CORNERS}.')
    if not 0 <= bias <= 1:
        raise ValueError('Spatial bias must be between 0 and 1.')
    favored_count = math.floor(total * bias + 0.5)
    other_corners = [corner for corner in CORNERS if corner != favored]
    per_corner, remainder = divmod(total - favored_count, len(other_corners))
    counts = {corner: per_corner for corner in other_corners}
    for corner in rng.sample(other_corners, remainder):
        counts[corner] += 1
    counts[favored] = favored_count

    pile = [corner for corner in CORNERS for _ in range(counts[corner])]
    rng.shuffle(pile)
    if len(pile) != total:
        raise AssertionError('Corner pile size does not match the appearance count.')
    return pile, counts


def even_pile(total, rng):
    """Even four-way pile for non-privileged items: counts differ by at most one.

    This is deliberately not `corner_pile` with a zero bias: that function always
    reserves the favoured corner first, which would leave one corner empty here.
    """
    per_corner, remainder = divmod(total, len(CORNERS))
    counts = {corner: per_corner for corner in CORNERS}
    for corner in rng.sample(list(CORNERS), remainder):
        counts[corner] += 1

    pile = [corner for corner in CORNERS for _ in range(counts[corner])]
    rng.shuffle(pile)
    if len(pile) != total:
        raise AssertionError('Corner pile size does not match the appearance count.')
    return pile, counts


def _rows(block, role, item, slots, pile, counts, favored, trial_counts):
    """One row per appearance, carrying the item's totals for auditing."""
    rows = []
    for (trial, slot), corner in zip(slots, pile):
        row = {
            'block': block,
            'trial': trial,
            'role': role,
            'item': item,
            'slot_number': slot,
            'trial_role_count': trial_counts[trial],
            'total_appearances': len(slots),
            'corner': corner,
            'favored_corner': favored,
            'event_id': f'{block}_trial_{trial}_{role}_{slot}',
        }
        row.update({f'corner_count_{name}': counts[name] for name in CORNERS})
        rows.append(row)
    return rows


def _privileged_rows(rng, block, role, items, actives, trial_counts, block_favored, bias):
    """One active item per trial, appearing `trial_counts[trial]` times in it."""
    rows = []
    counts_by_trial = dict(enumerate(trial_counts, start=1))
    for item in items:
        slots = [
            (trial, slot)
            for trial, (active, count) in enumerate(zip(actives, trial_counts), start=1)
            if active == item
            for slot in range(1, count + 1)
        ]
        if not slots:
            raise AssertionError(f'{role} {item} has no active trial.')
        favored_corner = block_favored[item]
        pile, corner_counts = corner_pile(len(slots), favored_corner, rng, bias)
        rows.extend(_rows(
            block, role, item, slots, pile, corner_counts, favored_corner, counts_by_trial,
        ))
    return rows


def build_slotting_key(
    rng, stimulus_assignment, favored,
    pt_count_range=TRIAL_PT_RANGE, pd_count_range=TRIAL_PD_RANGE,
):
    """Build the PT and PD slots; slot_number is an identity label, not time order."""
    if len(CORNERS) < 2 or len(set(CORNERS)) != len(CORNERS):
        raise ValueError('CORNERS must contain at least two unique corner names.')
    for role, bounds in (('PT', pt_count_range), ('PD', pd_count_range)):
        if bounds[0] < 0 or bounds[0] > bounds[1]:
            raise ValueError(f'{role} count range must be a valid nonnegative range.')

    rows = []
    for block, roles in stimulus_assignment.items():
        block_favored = favored[block]
        missing = [
            item for role in ROLE_ORDER for item in roles[role]
            if item not in block_favored
        ]
        if missing:
            raise ValueError(f'{block}: no favoured corner for {missing}.')

        pt_trials = active_sequence(roles['PT'], rng)
        pd_trials = active_sequence(roles['PD'], rng)
        if not pt_trials or not pd_trials:
            raise ValueError(f'{block}: every PT and PD needs at least one active trial.')
        pt_counts = [rng.randint(*pt_count_range) for _ in pt_trials]
        pd_counts = [rng.randint(*pd_count_range) for _ in pd_trials]

        block_rows = []
        block_rows.extend(_privileged_rows(
            rng, block, 'PT', roles['PT'], pt_trials, pt_counts, block_favored,
            TARGET_SPATIAL_BIAS,
        ))
        block_rows.extend(_privileged_rows(
            rng, block, 'PD', roles['PD'], pd_trials, pd_counts, block_favored,
            DISTRACTOR_SPATIAL_BIAS,
        ))

        ids = [row['event_id'] for row in block_rows]
        if len(ids) != len(set(ids)):
            raise AssertionError(f'{block}: duplicate slotting event ids.')
        block_rows.sort(key=lambda row: (
            row['trial'], ROLE_ORDER.index(row['role']), row['slot_number'], row['item'],
        ))
        rows.extend(block_rows)
    return rows


def favored_from_rows(rows):
    """Rebuild the per-block corner plan from the key's own favoured_corner column."""
    favored = defaultdict(dict)
    for row in rows:
        if row['role'] in ROLE_ORDER:
            favored[row['block']][row['item']] = row['favored_corner']
    return favored


def write_corner_plan(path, stimulus_assignment, favored):
    """Persist the four-way corner plan so it can be audited after the session."""
    path = Path(path)
    with path.open('x', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=CORNER_PLAN_FIELDS)
        writer.writeheader()
        for block, roles in stimulus_assignment.items():
            for role in ROLE_ORDER:
                for item in roles[role]:
                    writer.writerow({
                        'block': block, 'role': role, 'item': item,
                        'favored_corner': favored[block][item],
                    })
    return path


def write_slotting_key(pid, seed, rows, stimulus_assignment, data_dir):
    """Write the key, corner plan, and seed without overwriting an existing participant."""
    if not pid or Path(pid).name != pid or pid in {'.', '..'}:
        raise ValueError('PID must be a single folder name.')

    output_dir = Path(data_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    key_path = output_dir / 'slotting_key.csv'
    seed_path = output_dir / 'seed.txt'
    assignment_path = output_dir / 'stimulus_assignment.csv'
    corner_plan_path = output_dir / 'corner_plan.csv'

    if any(path.exists() for path in (key_path, seed_path, assignment_path, corner_plan_path)):
        raise FileExistsError(
            f'Key, seed, stimulus assignment, or corner plan already exists in {output_dir}'
        )

    created = []
    try:
        with key_path.open('x', newline='', encoding='utf-8') as file:
            created.append(key_path)
            writer = csv.DictWriter(file, fieldnames=FIELDNAMES, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)

        with seed_path.open('x', encoding='utf-8') as file:
            created.append(seed_path)
            file.write(f'{seed}\n')
        write_stimulus_assignment(assignment_path, stimulus_assignment)
        created.append(assignment_path)
        write_corner_plan(corner_plan_path, stimulus_assignment, favored_from_rows(rows))
        created.append(corner_plan_path)
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise

    return key_path
