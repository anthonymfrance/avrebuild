"""
Stimulus logic for the study: (1) split the 20-item pool into four roles per
block, then (2) decide which PT is active on each trial.

Roles (per block):
    PT   privileged target         - in-category, one active per trial
    NPT  non-privileged target     - in-category, the leftovers
    PD   privileged distractor     - other category
    NPD  non-privileged distractor - other category, the leftovers
"""

import csv
from pathlib import Path
from types import MappingProxyType

from config import PD_COUNT_PER_BLOCK, PT_COUNT_PER_BLOCK, TRIALS_PER_PT

ANIMATE = ['cat', 'frog', 'duck', 'cow', 'rooster', 'dog', 'horse', 'lion', 'pig', 'elephant']
INANIMATE = ['camera', 'door', 'phone', 'toilet', 'clock', 'car', 'wineglass', 'helicopter', 'motorcycle', 'ship']


def split_group(items, rng):
    """Shuffle one group once, then divide it into PT, PD, and remaining items."""
    items = rng.sample(items, len(items))
    pd_end = PT_COUNT_PER_BLOCK + PD_COUNT_PER_BLOCK 
    return {
        'PT': items[:PT_COUNT_PER_BLOCK],
        'PD': items[PT_COUNT_PER_BLOCK:pd_end],
        'rest': items[pd_end:],
    }


def block_roles(own, other):
    """Assemble the four roles for a block from its target and distractor groups."""
    return {
        'PT': own['PT'],
        'NPT': own['rest'],
        'PD': other['PD'],
        'NPD': other['rest'],
    }


def split_pool(rng):
    """Create one immutable stimulus assignment for both blocks."""
    animate = split_group(ANIMATE, rng)
    inanimate = split_group(INANIMATE, rng)
    assignment = {
        'animate': block_roles(animate, inanimate),
        'inanimate': block_roles(inanimate, animate),
    }
    return MappingProxyType({
        block: MappingProxyType({role: tuple(items) for role, items in roles.items()})
        for block, roles in assignment.items()
    })


ASSIGNMENT_FIELDS = ('block', 'role', 'item', 'item_index')
ROLES = frozenset({'PT', 'NPT', 'PD', 'NPD'})


def validate_stimulus_assignment(assignment):
    """Require complete, non-overlapping immutable role pools per block."""
    if not assignment:
        raise ValueError('Stimulus assignment is empty.')
    for block, roles in assignment.items():
        if set(roles) != ROLES:
            raise ValueError(f'{block}: stimulus assignment must contain PT, NPT, PD, and NPD.')
        items = [item for pool in roles.values() for item in pool]
        if any(not item for item in items) or len(items) != len(set(items)):
            raise ValueError(f'{block}: each stimulus item must appear in exactly one nonempty role pool.')
    return True


def write_stimulus_assignment(path, assignment):
    """Persist the assignment once so later stages consume the same pools."""
    validate_stimulus_assignment(assignment)
    path = Path(path)
    created = False
    try:
        with path.open('x', newline='', encoding='utf-8') as file:
            created = True
            writer = csv.DictWriter(file, fieldnames=ASSIGNMENT_FIELDS)
            writer.writeheader()
            for block, roles in assignment.items():
                for role, items in roles.items():
                    for index, item in enumerate(items, start=1):
                        writer.writerow({
                            'block': block, 'role': role, 'item': item,
                            'item_index': index,
                        })
    except Exception:
        if created:
            path.unlink(missing_ok=True)
        raise
    return path


def read_stimulus_assignment(path):
    """Load the persisted assignment as immutable role pools."""
    with Path(path).open(newline='', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None or not set(ASSIGNMENT_FIELDS).issubset(reader.fieldnames):
            raise ValueError(f'Stimulus assignment must contain columns: {ASSIGNMENT_FIELDS}')
        rows = list(reader)
    assignment = {}
    for row in rows:
        block, role, item = row['block'], row['role'], row['item']
        if not block or role not in ROLES or not item:
            raise ValueError('Stimulus assignment contains an invalid block, role, or item.')
        index = int(row['item_index'])
        assignment.setdefault(block, {}).setdefault(role, []).append((index, item))
    if not assignment or any(set(roles) != ROLES for roles in assignment.values()):
        raise ValueError('Stimulus assignment must include PT, NPT, PD, and NPD pools for every block.')
    for roles in assignment.values():
        for role, indexed_items in roles.items():
            indexed_items.sort()
            indices = [index for index, _ in indexed_items]
            items = [item for _, item in indexed_items]
            if indices != list(range(1, len(items) + 1)):
                raise ValueError(f'{role} assignment indices must be consecutive and items unique.')
            roles[role] = tuple(items)
    assignment = MappingProxyType({
        block: MappingProxyType(dict(roles))
        for block, roles in assignment.items()
    })
    validate_stimulus_assignment(assignment)
    return assignment


def pt_sequence(pts, rng):
    """Shuffle an equal number of active trials for each PT."""
    sequence = [pt for pt in pts for _ in range(TRIALS_PER_PT)]
    rng.shuffle(sequence)
    return sequence
