"""Build and validate a seeded timeline from a participant's slotting key."""

import csv
import math
from collections import Counter, defaultdict
from pathlib import Path

from config import (
    AUDIO_ROLES,
    BETWEEN_PT_STIMULUS_GAP,
    CORNER_SIGNS,
    CORNERS,
    FADE_IN_DUR,
    IMAGE_SIZE,
    MAX_PLACEMENT_ATTEMPTS,
    MAX_TIMELINE_ATTEMPTS,
    MIN_AUDIO_GAP,
    MIN_SAME_ITEM_GAP,
    MIN_TARGET_END_TO_ONSET_GAP,
    MIN_VISUAL_ONSET_GAP,
    PD_SOA_MAX,
    PD_SOA_MIN,
    PT_SOA_MAX,
    PT_SOA_MIN,
    RESPONSE_WINDOW,
    SOUND_DUR,
    TRIAL_BUFFER_DUR,
    TRIAL_CONTENT_DUR,
    TRIAL_NPD_RANGE,
    TRIAL_NPT_RANGE,
    TRIAL_PD_RANGE,
    TRIAL_DURATION,
    TRIAL_PT_RANGE,
    TARGET_ROLES,
    VISUAL_DURATION,
    VISUAL_ROLES,
)
from stimulus_split import validate_stimulus_assignment


# global_onset is PLANNED time on one continuous clock assuming no pauses. It
# is used for timeline planning and validation, not runtime scheduling; participant
# breaks can occur between trials or blocks.
FIELDS = [
    'block', 'trial', 'event_index', 'order_in_trial', 'event_id', 'source_event_id', 'role',
    'stimulus', 'slot_number', 'corner', 'x', 'y', 'global_onset', 'trial_onset', 'duration', 'event_type',
    'soa', 'response_window',
]
ROLE_ORDER = ('PT', 'PD', 'NPT', 'NPD')
RANGES = {
    'PT': TRIAL_PT_RANGE,
    'NPT': TRIAL_NPT_RANGE,
    'PD': TRIAL_PD_RANGE,
    'NPD': TRIAL_NPD_RANGE,
}


class PlacementFailure(RuntimeError):
    pass


def prepare_slotting_rows(rows):
    """Normalize slotting rows in place (typed trial/slot, stimulus field) and check them."""
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
        if row['role'] not in TARGET_ROLES or not row['stimulus']:
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


def _required_events(
    slotting_rows, stimulus_assignment, rng, pt_soa_by_identity, trial_count, ranges,
):
    events = []
    counts = Counter((row['block'], row['trial'], row['role']) for row in slotting_rows)
    blocks = list(dict.fromkeys(row['block'] for row in slotting_rows))
    for block in blocks:
        for trial in range(1, trial_count + 1):
            for role in ('PT', 'NPT'):
                count = counts[(block, trial, role)]
                low, high = ranges[role]
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
            pt_soa_by_identity[(row['block'], row['stimulus'])] if row['role'] == 'PT' else None,
        ))

    trials = range(1, trial_count + 1)
    for block in blocks:
        pools = stimulus_assignment[block]
        for trial in trials:
            for role in ('PD', 'NPD'):
                low, high = ranges[role]
                for slot in range(1, rng.randint(low, high) + 1):
                    item = rng.choice(pools[role])
                    corner = rng.choice(CORNERS)
                    soa = rng.uniform(PD_SOA_MIN, PD_SOA_MAX) if role == 'PD' else None
                    events.append(_event(
                        block, trial, role, item, slot,
                        f'{block}_trial_{trial}_{role}_{slot}', corner, soa,
                    ))
    return events


def _conflict(event, onset, placed):
    content_start = event['trial_start'] + TRIAL_BUFFER_DUR
    content_end = content_start + TRIAL_CONTENT_DUR
    trial_end = event['trial_start'] + TRIAL_DURATION
    hold_start = onset + FADE_IN_DUR
    sound_onset = hold_start - event['soa'] if event['role'] in AUDIO_ROLES else None
    if onset < content_start or onset + VISUAL_DURATION > content_end:
        return 'trial content boundary'
    if event['role'] in AUDIO_ROLES:
        if sound_onset < content_start or sound_onset + SOUND_DUR > content_end:
            return 'sound exceeds trial content'
    if event['role'] in TARGET_ROLES and onset + RESPONSE_WINDOW > trial_end:
        return 'target response window exceeds trial'
    visuals = [row for row in placed if row['event_type'] == 'visual']
    for other in visuals:
        onset_difference = abs(onset - other['global_onset'])
        earlier_onset = min(onset, other['global_onset'])
        later_onset = max(onset, other['global_onset'])
        end_to_onset_gap = later_onset - (earlier_onset + VISUAL_DURATION)
        if onset_difference < MIN_VISUAL_ONSET_GAP:
            return 'minimum visual onset gap'
        if event['corner'] == other['corner'] and end_to_onset_gap < 0:
            return 'same-corner overlap'
        if event['role'] in TARGET_ROLES and other['role'] in TARGET_ROLES:
            if end_to_onset_gap < MIN_TARGET_END_TO_ONSET_GAP:
                return 'minimum target end-to-onset gap'
            if onset_difference < RESPONSE_WINDOW:
                return 'target response windows overlap'
        if event['stimulus'] == other['stimulus'] and end_to_onset_gap < MIN_SAME_ITEM_GAP:
            return 'minimum same-item gap'
        if event['role'] == other['role'] == 'PT' and end_to_onset_gap < BETWEEN_PT_STIMULUS_GAP:
            return 'between-PT stimulus gap'
    if event['role'] in AUDIO_ROLES:
        for other in placed:
            if other['event_type'] == 'sound' and abs(sound_onset - other['global_onset']) < SOUND_DUR + MIN_AUDIO_GAP:
                return 'sound overlap or minimum audio gap'
    return ''


def _maximum_visual_events():
    """Return the loose capacity imposed by the universal onset gap alone."""
    if VISUAL_DURATION > TRIAL_CONTENT_DUR:
        return 0
    return math.floor((TRIAL_CONTENT_DUR - VISUAL_DURATION) / MIN_VISUAL_ONSET_GAP) + 1


def _construct_trial_schedule(events, trial_start, stats):
    """Place a randomized event order while checking every pair of constraints."""
    count = len(events)
    content_start = trial_start + TRIAL_BUFFER_DUR
    content_end = content_start + TRIAL_CONTENT_DUR
    trial_end = trial_start + TRIAL_DURATION
    rng = stats['rng']
    def random_order():
        remaining = list(events)
        rng.shuffle(remaining)
        sequence = []
        while remaining:
            previous = sequence[-1]['stimulus'] if sequence else None
            eligible = [
                index for index, event in enumerate(remaining)
                if event['stimulus'] != previous
            ]
            # Prefer not to repeat the preceding identity, but allow it when
            # necessary; the configured same-item interval remains enforced.
            index = rng.choice(eligible or range(len(remaining)))
            sequence.append(remaining.pop(index))
        return sequence

    def pair_separation(previous, current):
        separation = MIN_VISUAL_ONSET_GAP
        if previous['corner'] == current['corner']:
            separation = max(separation, VISUAL_DURATION)
        if previous['stimulus'] == current['stimulus']:
            separation = max(separation, VISUAL_DURATION + MIN_SAME_ITEM_GAP)
        if previous['role'] == current['role'] == 'PT':
            separation = max(separation, VISUAL_DURATION + BETWEEN_PT_STIMULUS_GAP)
        if previous['role'] in TARGET_ROLES and current['role'] in TARGET_ROLES:
            separation = max(
                separation,
                VISUAL_DURATION + MIN_TARGET_END_TO_ONSET_GAP,
                RESPONSE_WINDOW,
            )
        if previous['role'] in AUDIO_ROLES and current['role'] in AUDIO_ROLES:
            separation = max(
                separation,
                SOUND_DUR + MIN_AUDIO_GAP + current['soa'] - previous['soa'],
            )
        return separation

    def schedule(layout):
        minimum_offsets = [0.0]
        for index, event in enumerate(layout[1:], start=1):
            minimum_onset = max(
                minimum_offsets[previous_index]
                + pair_separation(previous, event)
                for previous_index, previous in enumerate(layout[:index])
            )
            minimum_offsets.append(minimum_onset)

        available_slack = max(
            0.0, TRIAL_CONTENT_DUR - VISUAL_DURATION - minimum_offsets[-1]
        )
        for attempt in range(9):
            extra_total = 0.0 if attempt == 8 else rng.uniform(0.0, available_slack)
            weights = [rng.random() for _ in range(max(0, count - 1))]
            weight_total = sum(weights)
            extras = (
                [extra_total * weight / weight_total for weight in weights]
                if weight_total and extra_total else [0.0] * len(weights)
            )
            offsets = [0.0]
            for index, event in enumerate(layout[1:], start=1):
                minimum_onset = max(
                    offsets[previous_index]
                    + pair_separation(previous, event)
                    for previous_index, previous in enumerate(layout[:index])
                )
                offsets.append(minimum_onset + extras[index - 1])

            lower = content_start
            upper = content_end - VISUAL_DURATION - offsets[-1]
            for index, event in enumerate(layout):
                if event['role'] in AUDIO_ROLES:
                    lower = max(
                        lower,
                        content_start - FADE_IN_DUR + event['soa'] - offsets[index],
                    )
                    upper = min(
                        upper,
                        content_end - SOUND_DUR - FADE_IN_DUR
                        + event['soa'] - offsets[index],
                    )
                if event['role'] in TARGET_ROLES:
                    upper = min(upper, trial_end - RESPONSE_WINDOW - offsets[index])
            if lower > upper + 1e-9:
                continue

            base = rng.uniform(lower, max(lower, upper))
            placed = []
            for index, event in enumerate(layout):
                picture_onset = base + offsets[index]
                visual = {
                    'block': event['block'], 'trial': event['trial'],
                    'event_id': event['event_id'], 'source_event_id': event['event_id'],
                    'role': event['role'], 'stimulus': event['stimulus'],
                    'slot_number': event['slot_number'], 'corner': event['corner'],
                    'global_onset': picture_onset, 'trial_onset': picture_onset - trial_start,
                    'duration': VISUAL_DURATION, 'event_type': 'visual',
                    'soa': '',
                    'response_window': RESPONSE_WINDOW if event['role'] in TARGET_ROLES else '',
                }
                placed.append(visual)
                if event['role'] in AUDIO_ROLES:
                    sound_onset = picture_onset + FADE_IN_DUR - event['soa']
                    placed.append({
                        'block': event['block'], 'trial': event['trial'],
                        'event_id': f"{event['event_id']}_sound",
                        'source_event_id': event['event_id'], 'role': event['role'],
                        'stimulus': event['stimulus'], 'slot_number': event['slot_number'],
                        'corner': '', 'global_onset': sound_onset,
                        'trial_onset': sound_onset - trial_start, 'duration': SOUND_DUR,
                        'event_type': 'sound', 'soa': event['soa'], 'response_window': '',
                    })
            checked = []
            for index, event in enumerate(layout):
                reason = _conflict(
                    dict(event, trial_start=trial_start),
                    base + offsets[index], checked,
                )
                if reason:
                    break
                visual_id = event['event_id']
                checked.append(next(row for row in placed if row['event_id'] == visual_id))
                checked.extend(
                    row for row in placed
                    if row['event_type'] == 'sound' and row['source_event_id'] == visual_id
                )
            else:
                return placed
        return None

    for _ in range(MAX_PLACEMENT_ATTEMPTS):
        layout = random_order()
        result = schedule(layout)
        stats['placement_attempts'] += 1
        if result is not None:
            return result
    minimum_space = VISUAL_DURATION + (count - 1) * MIN_VISUAL_ONSET_GAP
    raise PlacementFailure(
        f'Could not construct a trial schedule: required_visual_events={count}, '
        f'content_window={TRIAL_CONTENT_DUR:.3f}s, visual_duration={VISUAL_DURATION:.3f}s, '
        f'minimum_onset_gap={MIN_VISUAL_ONSET_GAP:.3f}s, '
        f'minimum_visual_space={minimum_space:.3f}s, '
        f'theoretical_visual_capacity={_maximum_visual_events()}, '
        f'paired_sound_events={sum(event["role"] in {"PT", "PD"} for event in events)}; '
        f'after {MAX_PLACEMENT_ATTEMPTS} randomized orders, pairing, same-item, target, '
        f'corner, or audio constraints prevented placement.'
    )


def validate_timeline(
    slotting_rows, required_events, timeline, stimulus_assignment, window_size,
    count_ranges=None,
):
    """Check exact per-trial counts, source preservation, and configured timing."""
    x_min, x_max, y_min, y_max = _position_bounds(window_size, IMAGE_SIZE)
    ids = [row['event_id'] for row in timeline]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate timeline event IDs.')
    if timeline != sorted(timeline, key=lambda row: row['global_onset']):
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
    expected_audio = {row['event_id'] for row in required_events if row['role'] in AUDIO_ROLES}
    if {row['source_event_id'] for row in sounds} != expected_audio:
        raise ValueError('PT/PD audio pairing is incomplete or contains unexpected sounds.')

    required_counts = Counter((r['block'], r['trial'], r['role']) for r in required_events)
    placed_counts = Counter((r['block'], r['trial'], r['role']) for r in visuals)
    if placed_counts != required_counts:
        raise ValueError(f'Per-trial exact-count check failed: required={required_counts}, placed={placed_counts}.')
    ranges = dict(RANGES)
    if count_ranges:
        ranges.update(count_ranges)
    for key, count in placed_counts.items():
        low, high = ranges[key[2]]
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
        if not math.isclose(row['trial_onset'], row['global_onset'] - start):
            raise ValueError(f"{row['block']} trial {row['trial']} {row['event_id']}: global/local timing mismatch.")
        if row['trial_onset'] < 0:
            raise ValueError(f"{row['block']} trial {row['trial']} {row['event_id']}: invalid local trial timing.")
        end = row['global_onset'] + row['duration']
        if row['event_type'] == 'sound':
            if row['response_window'] != '':
                raise ValueError(f"{row['event_id']}: sounds must not have response windows.")
            if row['global_onset'] < lower or end > upper:
                raise ValueError(f"{row['block']} trial {row['trial']} {row['event_id']}: sound outside content window.")
        else:
            if row['global_onset'] < lower or end > upper:
                raise ValueError(f"{row['block']} trial {row['trial']} {row['event_id']}: visual outside content window.")
            expected_window = RESPONSE_WINDOW if row['role'] in TARGET_ROLES else ''
            if row['response_window'] != expected_window:
                raise ValueError(f"{row['event_id']}: response window does not match target role.")
            if expected_window and end - row['duration'] + row['response_window'] > start + TRIAL_DURATION:
                raise ValueError(f"{row['event_id']}: response window exceeds trial end.")

    by_block = defaultdict(list)
    for row in timeline:
        by_block[row['block']].append(row)
    for block, rows in by_block.items():
        block_visuals = sorted((r for r in rows if r['event_type'] == 'visual'), key=lambda r: r['global_onset'])
        block_sounds = sorted((r for r in rows if r['event_type'] == 'sound'), key=lambda r: r['global_onset'])
        corner_groups = defaultdict(list)
        trial_visuals = defaultdict(list)
        for visual in block_visuals:
            corner_groups[(visual['trial'], visual['corner'])].append(visual)
            trial_visuals[visual['trial']].append(visual)
        for (trial, corner), corner_rows in corner_groups.items():
            corner_rows.sort(key=lambda r: r['global_onset'])
            for left, right in zip(corner_rows, corner_rows[1:]):
                if right['global_onset'] - (left['global_onset'] + VISUAL_DURATION) + 1e-9 < 0:
                    raise ValueError(
                        f'{block} trial {trial} corner {corner}: same-corner overlap '
                        f'({len(corner_rows)} visual events in that corner).'
                    )
        for left, right in zip(block_visuals, block_visuals[1:]):
            if right['global_onset'] - left['global_onset'] < MIN_VISUAL_ONSET_GAP:
                raise ValueError(f'{block}: minimum visual onset gap violated.')
        for i, left in enumerate(block_visuals):
            for right in block_visuals[i + 1:]:
                gap = right['global_onset'] - (left['global_onset'] + VISUAL_DURATION)
                if left['stimulus'] == right['stimulus'] and gap < MIN_SAME_ITEM_GAP:
                    raise ValueError(f'{block}: minimum same-item gap violated.')
                if left['role'] == right['role'] == 'PT' and gap < BETWEEN_PT_STIMULUS_GAP:
                    raise ValueError(f'{block}: between-PT gap violated.')
                if left['role'] in TARGET_ROLES and right['role'] in TARGET_ROLES:
                    if gap < MIN_TARGET_END_TO_ONSET_GAP:
                        raise ValueError(f'{block}: minimum target end-to-onset gap violated.')
                    if right['global_onset'] - left['global_onset'] < RESPONSE_WINDOW:
                        raise ValueError(f'{block}: target response windows overlap.')
        if any(row['event_type'] == 'sound' and row['order_in_trial'] != '' for row in rows):
            raise ValueError(f'{block}: sound rows must have empty order_in_trial.')
        for trial, trial_rows in trial_visuals.items():
            trial_rows.sort(key=lambda r: r['global_onset'])
            if [row['order_in_trial'] for row in trial_rows] != list(range(1, len(trial_rows) + 1)):
                raise ValueError(f'{block} trial {trial}: order_in_trial does not match onset order.')
        for left, right in zip(block_sounds, block_sounds[1:]):
            if right['global_onset'] - left['global_onset'] < SOUND_DUR + MIN_AUDIO_GAP:
                raise ValueError(f'{block}: sound overlap or minimum audio gap violated.')
        sounds_by_source = {r['source_event_id']: r for r in block_sounds}
        for visual in block_visuals:
            if visual['role'] in AUDIO_ROLES:
                sound = sounds_by_source[visual['event_id']]
                lower, upper = (PT_SOA_MIN, PT_SOA_MAX) if visual['role'] == 'PT' else (PD_SOA_MIN, PD_SOA_MAX)
                hold_start = visual['global_onset'] + FADE_IN_DUR
                if not lower <= sound['soa'] <= upper or not math.isclose(
                    hold_start - sound['global_onset'], sound['soa']
                ):
                    raise ValueError(f"{visual['block']} trial {visual['trial']} {visual['event_id']}: invalid SOA.")
    pt_soa_by_identity = {}
    for visual in visuals:
        if visual['role'] != 'PT':
            continue
        sound = next(row for row in sounds if row['source_event_id'] == visual['event_id'])
        identity = (visual['block'], visual['stimulus'])
        if identity in pt_soa_by_identity and not math.isclose(
            pt_soa_by_identity[identity], sound['soa']
        ):
            raise ValueError(
                f"{visual['block']} trial {visual['trial']} {visual['event_id']}: "
                f'PT SOA changed for identity {visual["stimulus"]!r}.'
            )
        pt_soa_by_identity[identity] = sound['soa']
    return True


def build_timeline(
    slotting_rows, rng, stimulus_assignment, window_size, diagnostics=None,
    count_ranges=None,
):
    """Construct a complete deterministic timeline or fail without writing."""
    _position_bounds(window_size, IMAGE_SIZE)
    validate_stimulus_assignment(stimulus_assignment)
    ranges = dict(RANGES)
    if count_ranges:
        ranges.update(count_ranges)
    for role, bounds in ranges.items():
        if len(bounds) != 2 or bounds[0] < 0 or bounds[0] > bounds[1]:
            raise ValueError(f'{role} count range must be a valid nonnegative (min, max) pair.')
    blocks = list(dict.fromkeys(row['block'] for row in slotting_rows))
    if set(blocks) != set(stimulus_assignment):
        raise ValueError(
            f'Slotting blocks {sorted(blocks)} do not match stimulus assignment blocks '
            f'{sorted(stimulus_assignment)}.'
        )
    for block in blocks:
        if block not in stimulus_assignment or set(stimulus_assignment[block]) != VISUAL_ROLES:
            raise ValueError(f'{block}: missing or incomplete persisted stimulus assignment.')
    trial_count = max(row['trial'] for row in slotting_rows)
    if trial_count < 1 or {row['trial'] for row in slotting_rows} != set(range(1, trial_count + 1)):
        raise ValueError('Slotting key trial numbers must be contiguous and start at 1.')
    grouped = defaultdict(list)
    for row in slotting_rows:
        grouped[(row['block'], row['trial'])].append(row)
    stats = {
        'rng': rng, 'placement_attempts': 0,
    }
    timeline_attempt_count = 0

    def publish_diagnostics(stage):
        if diagnostics is not None:
            diagnostics['stage'] = stage
            diagnostics['timeline_attempts'] = timeline_attempt_count
            diagnostics['placement_stats'] = {
                key: value for key, value in stats.items() if key != 'rng'
            }

    publish_diagnostics('event_generation')
    # Freeze one PT SOA for each (block, stimulus identity) before generating
    # PD instances and before any placement attempt or retry.
    pt_identities = list(dict.fromkeys(
        (row['block'], row['stimulus']) for row in slotting_rows if row['role'] == 'PT'
    ))
    pt_soa_by_identity = {
        identity: rng.uniform(PT_SOA_MIN, PT_SOA_MAX) for identity in pt_identities
    }
    # _required_events assigns each PD instance its own SOA once; the resulting
    # required-event list is reused unchanged across all placement retries.
    required = _required_events(
        slotting_rows, stimulus_assignment, rng, pt_soa_by_identity, trial_count, ranges,
    )
    required_by_trial = defaultdict(list)
    for event in required:
        required_by_trial[(event['block'], event['trial'])].append(event)
    if diagnostics is not None:
        diagnostics['trial_visual_counts'] = [
            {'block': block, 'trial': trial, 'count': len(events)}
            for (block, trial), events in required_by_trial.items()
        ]
    publish_diagnostics('capacity_check')
    capacity = _maximum_visual_events()
    for (block, trial), events in required_by_trial.items():
        if len(events) > capacity:
            minimum_space = VISUAL_DURATION + (len(events) - 1) * MIN_VISUAL_ONSET_GAP
            raise PlacementFailure(
                f'{block} trial {trial}: required_visual_events={len(events)}, '
                f'content_window={TRIAL_CONTENT_DUR:.3f}s, '
                f'visual_duration={VISUAL_DURATION:.3f}s, '
                f'minimum_onset_gap={MIN_VISUAL_ONSET_GAP:.3f}s, '
                f'minimum_visual_space={minimum_space:.3f}s, '
                f'theoretical_onset_capacity={capacity}. Other corner, target, identity, '
                f'SOA, and audio constraints may further limit placement.'
            )
    last_failure = None
    for _ in range(MAX_TIMELINE_ATTEMPTS):
        timeline_attempt_count += 1
        publish_diagnostics('placement')
        timeline = []
        try:
            for block_index, block in enumerate(blocks):
                for trial in range(1, trial_count + 1):
                    events = required_by_trial[(block, trial)]
                    start = _trial_start(block_index, trial, trial_count)
                    try:
                        timeline.extend(_construct_trial_schedule(events, start, stats))
                    except PlacementFailure as exc:
                        raise PlacementFailure(f'{block} trial {trial}: {exc}') from exc
            timeline.sort(key=lambda row: row['global_onset'])
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
            publish_diagnostics('validation')
            validate_timeline(
                slotting_rows, required, timeline, stimulus_assignment, window_size,
                count_ranges=ranges,
            )
            publish_diagnostics('complete')
            return timeline, required, stats
        except PlacementFailure as exc:
            last_failure = exc
            publish_diagnostics('placement')
    raise PlacementFailure(
        f'Failed after {MAX_TIMELINE_ATTEMPTS} timeline attempts; '
        f'{last_failure}; total placement orders={stats["placement_attempts"]}.'
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
    print(f'Solver: {stats["placement_attempts"]} randomized placement orders.')
    print('Final: PASS')


def write_timeline(path, timeline):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(timeline)
    return path
