"""Participant ID allocation and reproducible per-participant plan generation."""

from __future__ import annotations

import json
import random
import re
import secrets
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import config
from slotting_key import build_slotting_key, write_slotting_key
from stimulus_split import read_stimulus_assignment, split_pool
from timeline_key import (
    build_timeline,
    read_slotting_key,
    validation_report,
    write_timeline,
)


PARTICIPANT_PATTERN = re.compile(r"^(?:participant_)?(\d+)$")


def derive_rng(seed: int, label: str) -> random.Random:
    """Create a deterministic RNG stream isolated by a descriptive label."""
    if not label:
        raise ValueError('RNG stream label must not be empty.')
    return random.Random(f'{seed}:{label}')


def next_participant_id(data_dir: Path) -> str:
    """Return the lowest unused participant number, formatted with at least 2 digits."""
    data_dir = Path(data_dir)
    numbers = set()
    if data_dir.is_dir():
        for entry in data_dir.iterdir():
            if not entry.is_dir():
                continue
            match = PARTICIPANT_PATTERN.fullmatch(entry.name)
            if match:
                sessions = [
                    child for child in entry.iterdir()
                    if child.is_dir() and child.name.startswith('session_')
                ]
                # Every existing plan or session reserves its participant number.
                # Restarting an incomplete participant is an explicit reuse of that ID,
                # separate from allocating the next participant.
                has_plan = any((
                    (entry / 'seed.txt').is_file(),
                    (entry / 'slotting_key.csv').is_file(),
                    (entry / 'stimulus_assignment.csv').is_file(),
                    (entry / 'timeline_key.csv').is_file(),
                ))
                if not has_plan and not sessions:
                    continue
                numbers.add(int(match.group(1)))
    number = 1
    while number in numbers:
        number += 1
    return f'participant_{number:02d}'


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
        sessions = [
            child for child in participant_dir.iterdir()
            if child.is_dir() and child.name.startswith('session_')
        ]
        reusable_files = (
            participant_dir / 'seed.txt',
            participant_dir / 'slotting_key.csv',
            participant_dir / 'stimulus_assignment.csv',
            participant_dir / 'timeline_key.csv',
        )
        metadata_exists = any((
            (participant_dir / 'participant_metadata.json').is_file(),
            (participant_dir / 'session_config_snapshot.json').is_file(),
        ))
        if not all(path.is_file() for path in reusable_files) or not metadata_exists:
            raise FileExistsError(
                f'{participant_dir} exists but is not a complete, resumable setup. '
                'Preserve its contents and inspect it before continuing.'
            )
        snapshot_path = participant_dir / 'participant_metadata.json'
        if not snapshot_path.is_file():
            # Continue an already generated plan using its legacy snapshot name.
            snapshot_path = participant_dir / 'session_config_snapshot.json'
        snapshot = json.loads(snapshot_path.read_text(encoding='utf-8'))
        if snapshot.get('participant_id') != participant_id:
            raise ValueError(f'Config snapshot participant ID does not match {participant_id}.')
        for session in sessions:
            metadata_file = session / 'session_metadata.json'
            session_metadata = (
                json.loads(metadata_file.read_text(encoding='utf-8'))
                if metadata_file.is_file() else {}
            )
            if session_metadata.get('completion_status') == 'completed':
                raise FileExistsError(f'Completed session already exists: {session}')
            shutil.rmtree(session)
        return participant_dir / 'timeline_key.csv', snapshot

    participant_dir.mkdir(parents=True, exist_ok=False)
    used_seeds = set()
    if data_dir.is_dir():
        for entry in data_dir.iterdir():
            seed_file = entry / 'seed.txt'
            if seed_file.is_file():
                try:
                    used_seeds.add(int(seed_file.read_text(encoding='utf-8').strip()))
                except ValueError:
                    pass
    seed = secrets.randbits(64)
    while seed in used_seeds:
        seed = secrets.randbits(64)
    block_order = ['animate', 'inanimate'] if number % 2 else ['inanimate', 'animate']

    # Keep the assignment and all generated timelines in the same parity-based order.
    slotting_rng = derive_rng(seed, 'split_slotting')
    # The split itself consumes the same deterministic stream used by the key builder.
    assignment = split_pool(slotting_rng)
    assignment = {block: assignment[block] for block in block_order}
    slotting_rows = build_slotting_key(slotting_rng, assignment)
    write_slotting_key(participant_id, seed, slotting_rows, assignment)

    saved_assignment = read_stimulus_assignment(participant_dir / 'stimulus_assignment.csv')
    saved_slotting = read_slotting_key(participant_dir / 'slotting_key.csv')
    timeline, required, stats = build_timeline(
        saved_slotting, derive_rng(seed, 'timeline'), saved_assignment, config.WINDOW_SIZE,
    )
    validation_report(saved_slotting, required, timeline, stats)
    timeline_path = write_timeline(participant_dir / 'timeline_key.csv', timeline)

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
    (participant_dir / 'participant_metadata.json').write_text(
        json.dumps(snapshot, indent=2, sort_keys=True), encoding='utf-8',
    )
    return timeline_path, snapshot
