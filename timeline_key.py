"""Build and validate a seeded timeline from a participant's slotting key."""

import csv
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

from config import (
    BETWEEN_PT_STIMULUS_GAP,
    CORNERS,
    FADE_IN_DUR,
    FADE_OUT_DUR,
    IMAGE_SIZE,
    MAX_BACKTRACK_ATTEMPTS,
    MAX_PLACEMENT_ATTEMPTS,
    MAX_TIMELINE_ATTEMPTS,
    MIN_AUDIO_GAP,
    MIN_SAME_ITEM_GAP,
    MIN_VISUAL_ONSET_GAP,
    PD_SOA_MAX,
    PD_SOA_MIN,
    PEAK_HOLD_DUR,
    PT_SOA_MAX,
    PT_SOA_MIN,
    RESPONSE_WINDOW,
    SOUND_DUR,
    TRIAL_BUFFER_DUR,
    TRIAL_CONTENT_DUR,
    TRIAL_NPD_RANGE,
    TRIAL_NPT_RANGE,
    TRIAL_PD_RANGE,
    TRIAL_PT_RANGE,
)
from stimulus_split import read_stimulus_assignment, validate_stimulus_assignment


FIELDS = [
    'block', 'trial', 'event_index', 'order_in_trial', 'event_id', 'source_event_id', 'role',
    'stimulus', 'slot_number', 'corner', 'x', 'y', 'onset', 'duration', 'event_type',
    'soa', 'response_window',
]
VISUAL_DURATION = FADE_IN_DUR + PEAK_HOLD_DUR + FADE_OUT_DUR
TRIAL_DURATION = 2 * TRIAL_BUFFER_DUR + TRIAL_CONTENT_DUR
ROLE_ORDER = ('PT', 'PD', 'NPT', 'NPD')
ROLE_PRIORITY = {role: index for index, role in enumerate(ROLE_ORDER)}
RANGES = {
    'PT': TRIAL_PT_RANGE,
    'NPT': TRIAL_NPT_RANGE,
    'PD': TRIAL_PD_RANGE,
    'NPD': TRIAL_NPD_RANGE,
}
CORNER_SIGNS = {
    'top_left': (-1, 1), 'top_right': (1, 1),
    'bottom_left': (-1, -1), 'bottom_right': (1, -1),
}


class PlacementFailure(RuntimeError):
    pass


def read_slotting_key(path):
    """Read PT/NPT assignments; slot_number is an identity label, not time order."""
    with Path(path).open(newline='', encoding='utf-8') as file:
        rows = list(csv.DictReader(file))
    required = {'block', 'trial', 'role', 'slot_number', 'event_id', 'corner'}
    if not rows or not required.issubset(rows[0]):
        raise ValueError(f'Slotting key must have rows and columns: {sorted(required)}')
    ids = [row['event_id'] for row in rows]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError('Slotting-key event_id values must be present and unique.')
    for row in rows:
        row['trial'] = int(row['trial'])
        row['slot_number'] = int(row['slot_number'])
        row['role'] = row['role'].strip()
        row['stimulus'] = (
            row.get('active_pt', '').strip() if row['role'] == 'PT'
            else row.get('npt_item', '').strip() if row['role'] == 'NPT'
            else ''
        )
        if row['role'] not in {'PT', 'NPT'} or not row['stimulus']:
            raise ValueError(f"Unsupported role or missing stimulus in {row['event_id']}.")
        if row['corner'] not in CORNERS:
            raise ValueError(f"Invalid corner in slotting event {row['event_id']}.")
    return rows


def _trial_start(block_index, trial, trial_count):
    return (block_index * trial_count + trial - 1) * TRIAL_DURATION


def _position_bounds(window_size, image_size):
    """Return legal absolute center-coordinate bounds for one quadrant."""
    if len(window_size) != 2 or len(image_size) != 2:
        raise ValueError('Window and image sizes must each contain width and height.')
    window_width, window_height = map(float, window_size)
    image_width, image_height = map(float, image_size)
    if not all(math.isfinite(value) and value > 0 for value in (
        window_width, window_height, image_width, image_height
    )):
        raise ValueError('Window and image dimensions must be positive finite numbers.')
    x_min, x_max = image_width / 2, window_width / 2 - image_width / 2
    y_min, y_max = image_height / 2, window_height / 2 - image_height / 2
    if x_max < x_min or y_max < y_min:
        raise ValueError(
            f'Image size {image_size} cannot fit within each quadrant of window {window_size}.'
        )
    return x_min, x_max, y_min, y_max


def _jitter_position(corner, window_size, rng, image_size=IMAGE_SIZE):
    """Sample an image center uniformly within its assigned screen quadrant."""
    if corner not in CORNER_SIGNS:
        raise ValueError(f'Unknown corner {corner!r}.')
    x_min, x_max, y_min, y_max = _position_bounds(window_size, image_size)
    x_sign, y_sign = CORNER_SIGNS[corner]
    return (
        x_sign * rng.uniform(x_min, x_max),
        y_sign * rng.uniform(y_min, y_max),
    )


def _event(block, trial, role, stimulus, slot, event_id, corner, soa=None):
    # slot_number identifies the source slot; it does not assign a temporal order.
    return {
        'block': block, 'trial': trial, 'role': role, 'stimulus': stimulus,
        'slot_number': slot, 'event_id': event_id, 'corner': corner, 'soa': soa,
    }


def _required_events(slotting_rows, stimulus_assignment, rng, pt_soa_by_block, trial_count):
    events = []
    counts = Counter((row['block'], row['trial'], row['role']) for row in slotting_rows)
    blocks = list(dict.fromkeys(row['block'] for row in slotting_rows))
    for block in blocks:
        for trial in range(1, trial_count + 1):
            for role in ('PT', 'NPT'):
                count = counts[(block, trial, role)]
                low, high = RANGES[role]
                if not low <= count <= high:
                    raise ValueError(f'{block} trial {trial}: {role} count {count} outside {low}..{high}.')
    for row in slotting_rows:
        if row['stimulus'] not in stimulus_assignment[row['block']][row['role']]:
            raise ValueError(
                f"{row['block']} trial {row['trial']} {row['event_id']}: "
                f"{row['stimulus']} is absent from the persisted {row['role']} pool."
            )
        events.append(_event(
            row['block'], row['trial'], row['role'], row['stimulus'],
            row['slot_number'], row['event_id'], row['corner'],
            pt_soa_by_block[row['block']] if row['role'] == 'PT' else None,
        ))

    trials = range(1, trial_count + 1)
    for block in blocks:
        pools = stimulus_assignment[block]
        for trial in trials:
            for role in ('PD', 'NPD'):
                low, high = RANGES[role]
                for slot in range(1, rng.randint(low, high) + 1):
                    item = rng.choice(pools[role])
                    corner = rng.choice(CORNERS)
                    soa = rng.uniform(PD_SOA_MIN, PD_SOA_MAX) if role == 'PD' else None
                    events.append(_event(
                        block, trial, role, item, slot,
                        f'{block}_trial_{trial}_{role}_{slot}', corner, soa,
                    ))
    return events


def _conflict(event, onset, placed, trial_end):
    content_start = event['trial_start'] + TRIAL_BUFFER_DUR
    if onset < content_start or onset + VISUAL_DURATION > trial_end:
        return 'trial content boundary'
    if event['role'] in {'PT', 'PD'}:
        audio_end = onset + event['soa'] + SOUND_DUR + RESPONSE_WINDOW
        if audio_end > trial_end:
            return 'sound or response window exceeds trial content'
    visuals = [row for row in placed if row['event_type'] == 'visual']
    for other in visuals:
        gap = abs(onset - other['onset'])
        if event['corner'] == other['corner'] and gap < VISUAL_DURATION:
            return 'same-corner overlap'
        if gap < MIN_VISUAL_ONSET_GAP:
            return 'minimum visual onset gap'
        if event['stimulus'] == other['stimulus'] and gap < MIN_SAME_ITEM_GAP:
            return 'minimum same-item gap'
        if event['role'] == other['role'] == 'PT' and gap < BETWEEN_PT_STIMULUS_GAP:
            return 'between-PT stimulus gap'
    if event['role'] in {'PT', 'PD'}:
        sound_onset = onset + event['soa']
        for other in placed:
            if other['event_type'] == 'sound' and abs(sound_onset - other['onset']) < SOUND_DUR + MIN_AUDIO_GAP:
                return 'sound overlap or minimum audio gap'
    return ''


def _solve_trial(events, trial_start, stats):
    stats['attempt_backtracks'] = 0
    trial_end = trial_start + TRIAL_BUFFER_DUR + TRIAL_CONTENT_DUR
    # Role and slot labels prioritize placement; slot_number does not assign time.
    ordered = sorted(events, key=lambda e: (ROLE_PRIORITY[e['role']], e['slot_number'], e['event_id']))
    placed = []

    def solve(index):
        if index == len(ordered):
            return True
        event = dict(ordered[index], trial_start=trial_start)
        last_conflict = 'no legal candidate found'
        attempts = 0
        for attempts in range(1, MAX_PLACEMENT_ATTEMPTS + 1):
            stats['placement_attempts'] += 1
            onset = stats['rng'].uniform(
                trial_start + TRIAL_BUFFER_DUR,
                trial_end - VISUAL_DURATION,
            )
            reason = _conflict(event, onset, placed, trial_end)
            if reason:
                last_conflict = reason
                continue
            visual = {
                'block': event['block'], 'trial': event['trial'],
                'event_id': event['event_id'], 'source_event_id': event['event_id'],
                'role': event['role'], 'stimulus': event['stimulus'],
                'slot_number': event['slot_number'], 'corner': event['corner'],
                'onset': onset, 'duration': VISUAL_DURATION,
                'event_type': 'visual', 'soa': '', 'response_window': '',
            }
            placed.append(visual)
            sound = None
            if event['role'] in {'PT', 'PD'}:
                sound = {
                    'block': event['block'], 'trial': event['trial'],
                    'event_id': f"{event['event_id']}_sound",
                    'source_event_id': event['event_id'], 'role': event['role'],
                    'stimulus': event['stimulus'], 'slot_number': event['slot_number'],
                    'corner': '', 'onset': onset + event['soa'], 'duration': SOUND_DUR,
                    'event_type': 'sound', 'soa': event['soa'],
                    'response_window': RESPONSE_WINDOW,
                }
                placed.append(sound)
            if solve(index + 1):
                return True
            if stats['attempt_backtracks'] >= MAX_BACKTRACK_ATTEMPTS:
                stats['max_trial_backtracks'] = max(
                    stats['max_trial_backtracks'], stats['attempt_backtracks']
                )
                corner_count = sum(
                    row['event_type'] == 'visual' and row['corner'] == event['corner']
                    for row in placed
                )
                placed.pop()
                if sound:
                    placed.pop()
                raise PlacementFailure(
                    f"{event['block']} trial {event['trial']} event {event['event_id']}: "
                    f"required={len(ordered)}, placed={sum(r['event_type'] == 'visual' for r in placed)}, "
                    f'corner={event["corner"]}, corner_events_placed={corner_count}, '
                    f'constraint={last_conflict}; backtrack limit={MAX_BACKTRACK_ATTEMPTS} reached.'
                )
            stats['backtracks'] += 1
            stats['attempt_backtracks'] += 1
            placed.pop()
            if sound:
                placed.pop()
        stats['last_failure'] = (
            f"{event['block']} trial {event['trial']} role {event['role']} "
            f"event {event['event_id']} item {event['stimulus']}: "
            f"required={len(ordered)}, placed={sum(r['event_type'] == 'visual' for r in placed)}, "
            f"corner={event['corner']}, corner_events_placed="
            f"{sum(r['event_type'] == 'visual' and r['corner'] == event['corner'] for r in placed)}, "
            f'constraint={last_conflict}, placement attempts={attempts}, '
            f'backtracks={stats["attempt_backtracks"]}.'
        )
        return False

    if not solve(0):
        stats['max_trial_backtracks'] = max(
            stats['max_trial_backtracks'], stats['attempt_backtracks']
        )
        raise PlacementFailure(stats['last_failure'])
    stats['max_trial_backtracks'] = max(
        stats['max_trial_backtracks'], stats['attempt_backtracks']
    )
    return placed


def validate_timeline(slotting_rows, required_events, timeline, stimulus_assignment, window_size):
    """Check exact per-trial counts, source preservation, and configured timing."""
    x_min, x_max, y_min, y_max = _position_bounds(window_size, IMAGE_SIZE)
    ids = [row['event_id'] for row in timeline]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate timeline event IDs.')
    if timeline != sorted(timeline, key=lambda row: row['onset']):
        raise ValueError('Timeline is not chronologically ordered.')
    visuals = [row for row in timeline if row['event_type'] == 'visual']
    sounds = [row for row in timeline if row['event_type'] == 'sound']
    visual_by_id = {row['event_id']: row for row in visuals}
    if set(visual_by_id) != {row['event_id'] for row in required_events}:
        raise ValueError('A required visual event is missing or an unexpected visual was added.')
    for source in slotting_rows:
        actual = visual_by_id[source['event_id']]
        expected = (source['block'], source['trial'], source['role'], source['stimulus'], source['slot_number'], source['corner'])
        got = (actual['block'], actual['trial'], actual['role'], actual['stimulus'], actual['slot_number'], actual['corner'])
        if got != expected:
            raise ValueError(f"Slotting assignment changed for {source['event_id']}.")
    expected_audio = {row['event_id'] for row in required_events if row['role'] in {'PT', 'PD'}}
    if {row['source_event_id'] for row in sounds} != expected_audio:
        raise ValueError('PT/PD audio pairing is incomplete or contains unexpected sounds.')

    required_counts = Counter((r['block'], r['trial'], r['role']) for r in required_events)
    placed_counts = Counter((r['block'], r['trial'], r['role']) for r in visuals)
    if placed_counts != required_counts:
        raise ValueError(f'Per-trial exact-count check failed: required={required_counts}, placed={placed_counts}.')
    for key, count in placed_counts.items():
        low, high = RANGES[key[2]]
        if not low <= count <= high:
            raise ValueError(f'{key[0]} trial {key[1]} {key[2]} count {count} outside {low}..{high}.')
    for event in required_events:
        if event['stimulus'] not in stimulus_assignment[event['block']][event['role']]:
            raise ValueError(
                f"{event['block']} trial {event['trial']} {event['event_id']}: "
                f"item is not in the persisted {event['role']} pool."
            )

    blocks = list(dict.fromkeys(row['block'] for row in slotting_rows))
    trial_count = max(row['trial'] for row in slotting_rows)
    for row in timeline:
        if row['event_type'] == 'sound':
            if row['x'] != '' or row['y'] != '':
                raise ValueError(f"{row['event_id']}: sound rows must have blank x and y.")
        else:
            x, y = row['x'], row['y']
            if not isinstance(x, (int, float)) or not isinstance(y, (int, float)) or not (
                math.isfinite(x) and math.isfinite(y)
            ):
                raise ValueError(f"{row['event_id']}: visual x and y must be finite numeric coordinates.")
            if row['corner'] not in CORNER_SIGNS:
                raise ValueError(f"{row['event_id']}: invalid corner {row['corner']!r}.")
            x_sign, y_sign = CORNER_SIGNS[row['corner']]
            if x_sign * x < x_min - 1e-9 or x_sign * x > x_max + 1e-9 or \
                    y_sign * y < y_min - 1e-9 or y_sign * y > y_max + 1e-9:
                raise ValueError(
                    f"{row['block']} trial {row['trial']} {row['event_id']}: "
                    f'position ({x}, {y}) is outside {row["corner"]} bounds '
                    f'for window {window_size} and image {IMAGE_SIZE}.'
                )
        start = _trial_start(blocks.index(row['block']), row['trial'], trial_count)
        lower = start + TRIAL_BUFFER_DUR
        upper = start + TRIAL_BUFFER_DUR + TRIAL_CONTENT_DUR
        end = row['onset'] + row['duration']
        if row['event_type'] == 'sound':
            end += row['response_window']
        if row['onset'] < lower or end > upper:
            raise ValueError(f"{row['block']} trial {row['trial']} {row['event_id']}: outside trial content window.")

    by_block = defaultdict(list)
    for row in timeline:
        by_block[row['block']].append(row)
    for block, rows in by_block.items():
        block_visuals = sorted((r for r in rows if r['event_type'] == 'visual'), key=lambda r: r['onset'])
        block_sounds = sorted((r for r in rows if r['event_type'] == 'sound'), key=lambda r: r['onset'])
        corner_groups = defaultdict(list)
        trial_visuals = defaultdict(list)
        for visual in block_visuals:
            corner_groups[(visual['trial'], visual['corner'])].append(visual)
            trial_visuals[visual['trial']].append(visual)
        for (trial, corner), corner_rows in corner_groups.items():
            corner_rows.sort(key=lambda r: r['onset'])
            for left, right in zip(corner_rows, corner_rows[1:]):
                if right['onset'] - left['onset'] + 1e-9 < VISUAL_DURATION:
                    raise ValueError(
                        f'{block} trial {trial} corner {corner}: same-corner overlap '
                        f'({len(corner_rows)} visual events in that corner).'
                    )
        for left, right in zip(block_visuals, block_visuals[1:]):
            if right['onset'] - left['onset'] < MIN_VISUAL_ONSET_GAP:
                raise ValueError(f'{block}: minimum visual onset gap violated.')
        for i, left in enumerate(block_visuals):
            for right in block_visuals[i + 1:]:
                if left['stimulus'] == right['stimulus'] and right['onset'] - left['onset'] < MIN_SAME_ITEM_GAP:
                    raise ValueError(f'{block}: minimum same-item gap violated.')
                if left['role'] == right['role'] == 'PT' and right['onset'] - left['onset'] < BETWEEN_PT_STIMULUS_GAP:
                    raise ValueError(f'{block}: between-PT gap violated.')
        if any(row['event_type'] == 'sound' and row['order_in_trial'] != '' for row in rows):
            raise ValueError(f'{block}: sound rows must have empty order_in_trial.')
        for trial, trial_rows in trial_visuals.items():
            trial_rows.sort(key=lambda r: r['onset'])
            if [row['order_in_trial'] for row in trial_rows] != list(range(1, len(trial_rows) + 1)):
                raise ValueError(f'{block} trial {trial}: order_in_trial does not match onset order.')
        for left, right in zip(block_sounds, block_sounds[1:]):
            if right['onset'] - left['onset'] < SOUND_DUR + MIN_AUDIO_GAP:
                raise ValueError(f'{block}: sound overlap or minimum audio gap violated.')
        sounds_by_source = {r['source_event_id']: r for r in block_sounds}
        for visual in block_visuals:
            if visual['role'] in {'PT', 'PD'}:
                sound = sounds_by_source[visual['event_id']]
                lower, upper = (PT_SOA_MIN, PT_SOA_MAX) if visual['role'] == 'PT' else (PD_SOA_MIN, PD_SOA_MAX)
                if not lower <= sound['soa'] <= upper or not math.isclose(sound['onset'] - visual['onset'], sound['soa']):
                    raise ValueError(f"{visual['block']} trial {visual['trial']} {visual['event_id']}: invalid SOA.")
                if visual['role'] == 'PT' and any(
                    other['role'] == 'PT' and other['block'] == visual['block']
                    and sounds_by_source[other['event_id']]['soa'] != sound['soa']
                    for other in block_visuals
                ):
                    raise ValueError(f"{block}: PT SOA is not fixed within the block.")
    return True


def build_timeline(slotting_rows, rng, stimulus_assignment, window_size):
    """Construct a complete deterministic timeline or fail without writing."""
    _position_bounds(window_size, IMAGE_SIZE)
    validate_stimulus_assignment(stimulus_assignment)
    blocks = list(dict.fromkeys(row['block'] for row in slotting_rows))
    if set(blocks) != set(stimulus_assignment):
        raise ValueError(
            f'Slotting blocks {sorted(blocks)} do not match stimulus assignment blocks '
            f'{sorted(stimulus_assignment)}.'
        )
    for block in blocks:
        if block not in stimulus_assignment or set(stimulus_assignment[block]) != {'PT', 'NPT', 'PD', 'NPD'}:
            raise ValueError(f'{block}: missing or incomplete persisted stimulus assignment.')
    trial_count = max(row['trial'] for row in slotting_rows)
    if trial_count < 1 or {row['trial'] for row in slotting_rows} != set(range(1, trial_count + 1)):
        raise ValueError('Slotting key trial numbers must be contiguous and start at 1.')
    grouped = defaultdict(list)
    for row in slotting_rows:
        grouped[(row['block'], row['trial'])].append(row)
    stats = {
        'rng': rng, 'placement_attempts': 0, 'backtracks': 0,
        'attempt_backtracks': 0, 'max_trial_backtracks': 0,
    }
    pt_soa_by_block = {block: rng.uniform(PT_SOA_MIN, PT_SOA_MAX) for block in blocks}
    required = _required_events(slotting_rows, stimulus_assignment, rng, pt_soa_by_block, trial_count)
    required_by_trial = defaultdict(list)
    for event in required:
        required_by_trial[(event['block'], event['trial'])].append(event)
    last_failure = None
    for _ in range(MAX_TIMELINE_ATTEMPTS):
        stats['max_trial_backtracks'] = 0
        stats['last_failure'] = ''
        timeline = []
        try:
            for block_index, block in enumerate(blocks):
                for trial in range(1, trial_count + 1):
                    events = required_by_trial[(block, trial)]
                    start = _trial_start(block_index, trial, trial_count)
                    timeline.extend(_solve_trial(events, start, stats))
            timeline.sort(key=lambda row: row['onset'])
            for index, row in enumerate(timeline, start=1):
                row['event_index'] = index
                row['order_in_trial'] = ''
            order_counts = Counter()
            for row in timeline:
                if row['event_type'] == 'visual':
                    key = (row['block'], row['trial'])
                    order_counts[key] += 1
                    row['order_in_trial'] = order_counts[key]
                    row['x'], row['y'] = _jitter_position(row['corner'], window_size, rng)
                else:
                    row['x'] = row['y'] = ''
            validate_timeline(slotting_rows, required, timeline, stimulus_assignment, window_size)
            return timeline, required, stats
        except PlacementFailure as exc:
            last_failure = exc
    raise PlacementFailure(
        f'Failed after {MAX_TIMELINE_ATTEMPTS} timeline attempts; '
        f'{last_failure}; total placements={stats["placement_attempts"]}, '
        f'backtracks={stats["backtracks"]}, max trial backtracks={stats["max_trial_backtracks"]}.'
    )


def validation_report(slotting_rows, required, timeline, stats):
    counts = Counter((row['block'], row['trial'], row['role']) for row in timeline if row['event_type'] == 'visual')
    totals = Counter(row['role'] for row in timeline if row['event_type'] == 'visual')
    trials = sorted({(row['block'], row['trial']) for row in required})
    print(f'Total events: {len(timeline)} (including {sum(r["event_type"] == "sound" for r in timeline)} sounds)')
    print('Visual counts: ' + ', '.join(f'{role}={totals[role]}' for role in ('PT', 'NPT', 'PD', 'NPD')))
    print('Per-trial counts (PT/NPT/PD/NPD):')
    for block, trial in trials:
        values = '/'.join(str(counts[(block, trial, role)]) for role in ROLE_ORDER)
        print(f'  {block} trial {trial}: {values}')
    print('Checks: exact counts PASS; slotting preservation PASS; role-pool membership PASS; timing constraints PASS; chronological order PASS.')
    print(f'Solver: {stats["placement_attempts"]} candidate attempts, {stats["backtracks"]} total backtracks, '
          f'max {stats["max_trial_backtracks"]} in one trial.')
    print('Final: PASS')


def write_timeline(path, timeline):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(timeline)
    return path


def main():
    if len(sys.argv) != 5:
        raise SystemExit('Usage: python timeline_key.py <PID> <seed> <window_width> <window_height>')
    pid = sys.argv[1]
    if not pid or Path(pid).name != pid or pid in {'.', '..'}:
        raise SystemExit('PID must be a single folder name.')
    try:
        seed = int(sys.argv[2])
    except ValueError:
        raise SystemExit('Seed must be an integer.')
    try:
        window_size = (int(sys.argv[3]), int(sys.argv[4]))
    except ValueError:
        raise SystemExit('Window width and height must be integers in pixels.')
    output_dir = Path(__file__).resolve().parent / 'data' / pid
    try:
        source_seed = int((output_dir / 'seed.txt').read_text(encoding='utf-8').strip())
    except (OSError, ValueError):
        raise SystemExit(f'Could not read a valid seed from {output_dir / "seed.txt"}')
    if source_seed != seed:
        raise SystemExit(f'Supplied seed {seed} does not match slotting-key seed {source_seed}.')

    try:
        slotting_rows = read_slotting_key(output_dir / 'slotting_key.csv')
        stimulus_assignment = read_stimulus_assignment(output_dir / 'stimulus_assignment.csv')
        rng = random.Random(seed)
        timeline, required, stats = build_timeline(slotting_rows, rng, stimulus_assignment, window_size)
        validation_report(slotting_rows, required, timeline, stats)
        path = write_timeline(output_dir / 'timeline_key.csv', timeline)
    except (OSError, ValueError, PlacementFailure) as exc:
        raise SystemExit(f'Participant {pid}: {exc}') from exc
    print(f'Wrote {len(timeline)} events to {path}.')


if __name__ == '__main__':
    main()
