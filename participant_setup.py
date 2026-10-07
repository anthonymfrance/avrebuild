"""Participant ID allocation and reproducible per-participant plan generation."""

from __future__ import annotations

import json
import os
import random
import re
import secrets
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import config
from session_io import sha256_file
from slotting_key import build_slotting_key, write_slotting_key
from stimulus_split import read_stimulus_assignment, split_pool
from timeline_key import (
    PlacementFailure,
    build_timeline,
    read_slotting_key,
    validation_report,
    write_timeline,
)


PARTICIPANT_PATTERN = re.compile(r"^(?:participant_)?(\d+)$")


class PlanGenerationError(RuntimeError):
    """Raised when all secret-seed plan placement attempts fail."""


def derive_rng(seed: int, label: str) -> random.Random:
    """Create a deterministic RNG stream isolated by a descriptive label."""
    if not label:
        raise ValueError('RNG stream label must not be empty.')
    return random.Random(f'{seed}:{label}')


def next_participant_id(data_dir: Path) -> str:
    """Return the lowest unused participant number, formatted with at least 2 digits."""
    data_dirs = data_directories(data_dir)
    numbers = set()
    for root in data_dirs:
        if root.is_dir():
            for entry in root.iterdir():
                match = PARTICIPANT_PATTERN.fullmatch(entry.name)
                if match:
                    numbers.add(int(match.group(1)))
    number = 1
    while number in numbers:
        number += 1
    return f'participant_{number:02d}'


def data_directories(data_dir):
    """Return local and configured server data roots, without duplicates."""
    data_dirs = [Path(data_dir)]
    server_data = os.environ.get('AV_STUDY_SERVER_DATA_PATH')
    server_root = os.environ.get('AV_STUDY_SERVER_ROOT')
    if server_data:
        data_dirs.append(Path(server_data))
    elif server_root:
        data_dirs.append(Path(server_root) / 'data')
    unique = []
    for root in data_dirs:
        if root not in unique:
            unique.append(root)
    return unique


def planned_block_order(data_dirs):
    """Counterbalance blocks by completed sessions across local and server data."""
    completed = set()
    for root in map(Path, data_dirs):
        if not root.is_dir():
            continue
        for participant in root.iterdir():
            if not participant.is_dir() or not PARTICIPANT_PATTERN.fullmatch(participant.name):
                continue
            for session in participant.glob('session_*'):
                meta = session / 'session_metadata.json'
                if meta.is_file():
                    try:
                        if json.loads(meta.read_text(encoding='utf-8')).get('completion_status') == 'completed':
                            completed.add((participant.name, session.name))
                    except (OSError, ValueError):
                        continue
    count = len(completed)
    order = ['animate', 'inanimate'] if count % 2 == 0 else ['inanimate', 'animate']
    return order, count


def participant_number(participant_id: str) -> int:
    match = re.fullmatch(r'participant_(\d+)', participant_id)
    if not match:
        raise ValueError('Participant ID must use the form participant_01.')
    return int(match.group(1))


def create_participant_plan(data_dir: Path, participant_id: str) -> tuple[Path, dict]:
    """Reserve the participant folder and create all immutable session plans."""
    data_dir = Path(data_dir).resolve()
    number = participant_number(participant_id)
    expected_id = next_participant_id(data_dir)
    if participant_id != expected_id:
        raise FileExistsError(
            f'Next available participant is {expected_id}; requested {participant_id}. '
            'Run preflight again to refresh the participant ID.'
        )

    participant_dir = data_dir / participant_id
    if participant_dir.exists():
        raise FileExistsError(f'{participant_dir} already exists; participant data is never overwritten.')
    temp_dir = data_dir / f'.{participant_id}.tmp'
    if temp_dir.exists():
        raise FileExistsError(f'{temp_dir} already exists; preserve it and inspect before continuing.')
    data_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir()
    data_dirs = data_directories(data_dir)
    block_order, completed_count = planned_block_order(data_dirs)
    used_seeds = set()
    for root in data_dirs:
        for entry in root.iterdir() if root.is_dir() else ():
            seed_file = entry / 'seed.txt'
            if seed_file.is_file():
                try:
                    used_seeds.add(int(seed_file.read_text(encoding='utf-8').strip()))
                except ValueError:
                    pass
    failed_seeds = []
    try:
        for attempt in range(1, 6):
            seed = secrets.randbits(64)
            while seed in used_seeds:
                seed = secrets.randbits(64)
            used_seeds.add(seed)
            slotting_rng = derive_rng(seed, 'split_slotting')
            assignment = split_pool(slotting_rng)
            assignment = {block: assignment[block] for block in block_order}
            slotting_rows = build_slotting_key(slotting_rng, assignment)
            write_slotting_key(participant_id, seed, slotting_rows, assignment, data_dir=temp_dir)
            saved_assignment = read_stimulus_assignment(temp_dir / 'stimulus_assignment.csv')
            saved_slotting = read_slotting_key(temp_dir / 'slotting_key.csv')
            try:
                timeline, required, stats = build_timeline(
                    saved_slotting, derive_rng(seed, 'timeline'), saved_assignment, config.WINDOW_SIZE,
                )
            except PlacementFailure as exc:
                failed_seeds.append(seed)
                for path in temp_dir.iterdir():
                    path.unlink()
                if attempt == 5:
                    failed = ', '.join(map(str, failed_seeds))
                    raise PlanGenerationError(
                        f'Timeline placement failed after 5 attempts; failed seeds: {failed}.'
                    ) from exc
                continue
            validation_report(saved_slotting, required, timeline, stats)
            write_timeline(temp_dir / 'timeline_key.csv', timeline)
            break
        try:
            git_commit = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=Path(__file__).resolve().parent,
            text=True, stderr=subprocess.DEVNULL,
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            git_commit = None
        snapshot = {
            'participant_id': participant_id,
            'participant_number': number,
            'seed': seed,
            'seed_bits': 64,
            'rng_strategy': 'Independent Python random.Random streams derived from the master seed using labels split_slotting and timeline.',
            'block_order': block_order,
            'block_order_rule': 'completed session count: even animate,inanimate; odd inanimate,animate',
            'completed_session_count_at_allocation': completed_count,
            'plan_attempts': len(failed_seeds) + 1,
            'failed_plan_seeds': failed_seeds,
            'timeline_sha256': sha256_file(temp_dir / 'timeline_key.csv'),
            'generated_utc': datetime.now(timezone.utc).isoformat(),
            'git_commit': git_commit,
            'config': {
                name: value for name, value in vars(config).items()
                if name.isupper() and not name.startswith('_')
            },
            'artifacts': {
                'stimulus_assignment': 'stimulus_assignment.csv',
                'slotting_key': 'slotting_key.csv',
                'timeline': 'timeline_key.csv',
                'seed': 'seed.txt',
            },
        }
        (temp_dir / 'participant_metadata.json').write_text(
            json.dumps(snapshot, indent=2, sort_keys=True), encoding='utf-8',
        )
        os.rename(temp_dir, participant_dir)
        return participant_dir / 'timeline_key.csv', snapshot
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
