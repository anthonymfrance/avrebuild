"""Build a seeded, immutable PT corner assignment key."""

import csv
import math
from pathlib import Path

from config import (
    CORNERS,
    FAVORED_CORNER,
    TARGET_SPATIAL_BIAS,
    TRIAL_NPT_RANGE,
    TRIAL_PT_RANGE,
)
from stimulus_split import pt_sequence, write_stimulus_assignment


BASE_FIELDS = [
    'block',
    'trial',
    'active_pt',
    'npt_item',
    'role',
    'slot_number',
    'trial_pt_count',
    'trial_npt_count',
    'corner',
    'event_id',
    'pt_total_appearances',
    'npt_total_appearances',
]
CORNER_COUNT_FIELDS = [f'corner_count_{corner}' for corner in CORNERS]
FIELDNAMES = BASE_FIELDS + CORNER_COUNT_FIELDS


def corner_pile(total, rng):
    """Make and shuffle one PT's per-block corner assignments."""
    favored_count = math.floor(total * TARGET_SPATIAL_BIAS + 0.5)
    other_count = total - favored_count
    other_corners = [corner for corner in CORNERS if corner != FAVORED_CORNER]

    per_corner, remainder = divmod(other_count, len(other_corners))
    counts = {corner: per_corner for corner in other_corners}
    for corner in rng.sample(other_corners, remainder):
        counts[corner] += 1
    counts[FAVORED_CORNER] = favored_count

    pile = [
        corner
        for corner in CORNERS
        for _ in range(counts[corner])
    ]
    rng.shuffle(pile)
    if len(pile) != total:
        raise AssertionError('Corner pile size does not match PT appearance count.')
    return pile, counts


def build_slotting_key(
    rng, stimulus_assignment, pt_count_range=TRIAL_PT_RANGE,
    npt_count_range=TRIAL_NPT_RANGE,
):
    """Build PT/NPT rows; slot_number is an identity label, not temporal order."""
    if len(CORNERS) < 2 or len(set(CORNERS)) != len(CORNERS):
        raise ValueError('CORNERS must contain at least two unique corner names.')
    if FAVORED_CORNER not in CORNERS:
        raise ValueError('FAVORED_CORNER must be listed in CORNERS.')
    if not 0 <= TARGET_SPATIAL_BIAS <= 1:
        raise ValueError('TARGET_SPATIAL_BIAS must be between 0 and 1.')
    if pt_count_range[0] < 0 or pt_count_range[0] > pt_count_range[1]:
        raise ValueError('TRIAL_PT_RANGE must be a valid nonnegative range.')
    if npt_count_range[0] < 0 or npt_count_range[0] > npt_count_range[1]:
        raise ValueError('TRIAL_NPT_RANGE must be a valid nonnegative range.')

    pt_rows = []
    npt_rows = []
    for block, roles in stimulus_assignment.items():
        active_pts = pt_sequence(roles['PT'], rng)
        trial_counts = [
            rng.randint(*pt_count_range)
            for _ in active_pts
        ]
        block_pt_rows = []
        block_npt_rows = []

        for pt in roles['PT']:
            pt_trials = [
                (trial, count)
                for trial, (active_pt, count) in enumerate(
                    zip(active_pts, trial_counts), start=1
                )
                if active_pt == pt
            ]
            total = sum(count for _, count in pt_trials)
            pile, corner_counts = corner_pile(total, rng)
            pile_index = 0

            for trial, count in pt_trials:
                for slot_number in range(1, count + 1):
                    corner = pile[pile_index]
                    pile_index += 1
                    row = {
                        'block': block,
                        'trial': trial,
                        'active_pt': pt,
                        'npt_item': '',
                        'role': 'PT',
                        'slot_number': slot_number,
                        'trial_pt_count': count,
                        'trial_npt_count': '',
                        'corner': corner,
                        'event_id': f'{block}_trial_{trial}_PT_{slot_number}',
                        'pt_total_appearances': total,
                        'npt_total_appearances': '',
                    }
                    row.update({
                        f'corner_count_{name}': corner_counts[name]
                        for name in CORNERS
                    })
                    block_pt_rows.append(row)

            if pile_index != len(pile):
                raise AssertionError('Not every corner assignment was used.')

        # NPTs are sampled across each trial using the configured range. Sampling
        # with replacement allows a trial count larger than the NPT pool.
        npt_trial_items = {
            trial: rng.choices(
                roles['NPT'],
                k=rng.randint(*npt_count_range),
            )
            for trial in range(1, len(active_pts) + 1)
        }
        for npt in roles['NPT']:
            appearances = [
                (trial, slot_number)
                for trial, items in npt_trial_items.items()
                for slot_number, item in enumerate(items, start=1)
                if item == npt
            ]
            total = len(appearances)
            pile, corner_counts = corner_pile(total, rng)
            for (trial, slot_number), corner in zip(appearances, pile):
                row = {
                    'block': block,
                    'trial': trial,
                    'active_pt': '',
                    'npt_item': npt,
                    'role': 'NPT',
                    'slot_number': slot_number,
                    'trial_pt_count': '',
                    'trial_npt_count': len(npt_trial_items[trial]),
                    'corner': corner,
                    'event_id': f'{block}_trial_{trial}_NPT_{slot_number}_{npt}',
                    'pt_total_appearances': '',
                    'npt_total_appearances': total,
                }
                row.update({
                    f'corner_count_{name}': corner_counts[name]
                    for name in CORNERS
                })
                block_npt_rows.append(row)

        # CSV row order is for readability; slot_number is an identity label, not time.
        block_pt_rows.sort(key=lambda row: (row['trial'], row['slot_number']))
        block_npt_rows.sort(key=lambda row: (row['trial'], row['slot_number'], row['npt_item']))
        pt_rows.extend(block_pt_rows)
        npt_rows.extend(block_npt_rows)
    return pt_rows + npt_rows


def write_slotting_key(pid, seed, rows, stimulus_assignment, data_dir):
    """Write the key and seed without overwriting an existing participant key."""
    if not pid or Path(pid).name != pid or pid in {'.', '..'}:
        raise ValueError('PID must be a single folder name.')

    output_dir = Path(data_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    key_path = output_dir / 'slotting_key.csv'
    seed_path = output_dir / 'seed.txt'
    assignment_path = output_dir / 'stimulus_assignment.csv'

    if key_path.exists() or seed_path.exists() or assignment_path.exists():
        raise FileExistsError(f'Key, seed, or stimulus assignment already exists in {output_dir}')

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
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise

    return key_path
