"""Participant ID allocation and reproducible per-participant plan generation."""

from __future__ import annotations

import json
import os
import random
import re
import secrets
import shutil
import socket
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType

import config
from session_io import config_snapshot, json_default, server_data_directory, sha256_file
from slotting_key import build_slotting_key, write_slotting_key
from stimulus_split import split_pool
from timeline_key import (
    PlacementFailure,
    build_timeline,
    prepare_slotting_rows,
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


def build_plan(seed, block_order, count_ranges=None, diagnostics=None):
    """Generate split -> slotting key -> timeline in memory from one master seed.

    Returns (assignment, slotting_rows, timeline, required, stats). Raises
    PlacementFailure when the timeline cannot be placed.
    """
    slotting_rng = derive_rng(seed, 'split_slotting')
    split = split_pool(slotting_rng)
    assignment = MappingProxyType({block: split[block] for block in block_order})
    ranges = dict(count_ranges or {})
    slotting_rows = prepare_slotting_rows(build_slotting_key(
        slotting_rng, assignment,
        pt_count_range=ranges.get('PT', config.TRIAL_PT_RANGE),
        npt_count_range=ranges.get('NPT', config.TRIAL_NPT_RANGE),
    ))
    timeline, required, stats = build_timeline(
        slotting_rows, derive_rng(seed, 'timeline'), assignment, config.WINDOW_SIZE,
        diagnostics=diagnostics, count_ranges=count_ranges,
    )
    return assignment, slotting_rows, timeline, required, stats


CLAIM_DIR_NAME = '.claims'
CLAIM_SUFFIX = '.lock'
CLAIM_WRITE_GRACE_SECONDS = 60


def data_directories(data_dir):
    """Return local and configured server data roots, without duplicates."""
    local = Path(data_dir).resolve()
    data_dirs = [local]
    server_data = server_data_directory()
    if server_data is not None:
        server_data = Path(server_data).resolve()
        if server_data != local:
            data_dirs.append(server_data)
    return data_dirs


def _claim_filename(participant_id):
    return f'{participant_id}{CLAIM_SUFFIX}'


def _claim_number(path):
    match = PARTICIPANT_PATTERN.fullmatch(Path(path).stem)
    return int(match.group(1)) if match else None


def _read_claim(path):
    try:
        claim = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return claim if isinstance(claim, dict) else None


def _claim_is_expired(claim, path):
    """Expired or abandoned claims may be reclaimed; a fresh partial write is not."""
    if not claim or not claim.get('started_utc'):
        try:
            age = datetime.now(timezone.utc).timestamp() - Path(path).stat().st_mtime
        except OSError:
            return False
        return age > CLAIM_WRITE_GRACE_SECONDS
    try:
        started_at = datetime.fromisoformat(str(claim['started_utc']))
    except ValueError:
        return True
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - started_at > timedelta(
        hours=config.PARTICIPANT_CLAIM_TTL_HOURS
    )


def _occupied_participant_numbers(data_dirs):
    """Participant folders plus live claims in every visible data root."""
    numbers = set()
    for root in map(Path, data_dirs):
        if root.is_dir():
            for entry in root.iterdir():
                match = PARTICIPANT_PATTERN.fullmatch(entry.name)
                if match:
                    numbers.add(int(match.group(1)))
        claim_dir = root / CLAIM_DIR_NAME
        if not claim_dir.is_dir():
            continue
        for claim_path in claim_dir.glob(f'participant_*{CLAIM_SUFFIX}'):
            number = _claim_number(claim_path)
            if number is None:
                continue
            if _claim_is_expired(_read_claim(claim_path), claim_path):
                try:
                    claim_path.unlink()
                except OSError:
                    numbers.add(number)
                continue
            numbers.add(number)
    return numbers


def next_participant_id(data_dir: Path) -> str:
    """Return the lowest participant number not used locally, on the server, or claimed."""
    numbers = _occupied_participant_numbers(data_directories(data_dir))
    number = 1
    while number in numbers:
        number += 1
    return f'participant_{number:02d}'


def _shared_claim_root(data_dir, data_dirs):
    """Reserve on the lab share when it is available, otherwise locally."""
    server_data = server_data_directory()
    if server_data is not None:
        server_data = Path(server_data).resolve()
        if server_data in data_dirs:
            return server_data
    return Path(data_dir).resolve()


def claim_next_participant_id(data_dir: Path) -> dict:
    """Atomically reserve the lowest free participant ID on the shared data root.

    The claim file is created with O_EXCL, so two devices starting at the same
    time cannot both reserve the same participant number. The claim records the
    participant ID, the allocating process, the host, and the UTC start time.
    """
    data_dir = Path(data_dir).resolve()
    data_dirs = data_directories(data_dir)
    claim_root = _shared_claim_root(data_dir, data_dirs)
    claim_dir = claim_root / CLAIM_DIR_NAME
    claim_dir.mkdir(parents=True, exist_ok=True)
    number = participant_number(next_participant_id(data_dir))
    while True:
        participant_id = f'participant_{number:02d}'
        if any((Path(root) / participant_id).exists() for root in data_dirs):
            number += 1
            continue
        token = secrets.token_hex(16)
        claim_path = claim_dir / _claim_filename(participant_id)
        payload = {
            'participant_id': participant_id,
            'pid': os.getpid(),
            'host': socket.gethostname(),
            'started_utc': datetime.now(timezone.utc).isoformat(),
            'token': token,
        }
        try:
            descriptor = os.open(
                claim_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644
            )
        except FileExistsError:
            number += 1
            continue
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
                json.dump(payload, output, sort_keys=True)
                output.write('\n')
                output.flush()
                os.fsync(output.fileno())
        except Exception:
            claim_path.unlink(missing_ok=True)
            raise
        return {
            'participant_id': participant_id,
            'path': str(claim_path),
            'token': token,
        }


def verify_participant_claim(claim_path, participant_id, token):
    """Return the claim payload, or raise when it is missing, stale, or foreign."""
    path = Path(claim_path)
    claim = _read_claim(path)
    if claim is None:
        raise ValueError(f'Participant claim is missing or unreadable: {path}')
    if claim.get('participant_id') != participant_id:
        raise ValueError(
            f'Participant claim is for {claim.get("participant_id")!r}, not {participant_id!r}.'
        )
    if not token or claim.get('token') != token:
        raise ValueError(f'Participant claim token does not match for {participant_id}.')
    if _claim_is_expired(claim, path):
        raise ValueError(f'Participant claim for {participant_id} expired; run preflight again.')
    return claim


def release_participant_claim(claim_path, token):
    """Remove a claim only when the caller owns it."""
    path = Path(claim_path)
    claim = _read_claim(path)
    if claim is None or claim.get('token') != token:
        return False
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    try:
        path.parent.rmdir()
    except OSError:
        pass  # Another claim is still present; keep the directory.
    return True


def release_participant_claim_if_unused(data_dir, claim_path, token, participant_id):
    """Release a preflight claim when no participant folder was ever created."""
    data_dirs = data_directories(data_dir)
    if any((Path(root) / participant_id).exists() for root in data_dirs):
        return False
    return release_participant_claim(claim_path, token)


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


def create_participant_plan(data_dir: Path, participant_id: str, claim=None) -> tuple[Path, dict]:
    """Reserve the participant folder and create all immutable session plans."""
    data_dir = Path(data_dir).resolve()
    data_dirs = data_directories(data_dir)
    number = participant_number(participant_id)
    if claim is not None:
        verify_participant_claim(claim['path'], participant_id, claim['token'])
        existing = [str(Path(root) / participant_id) for root in data_dirs
                    if (Path(root) / participant_id).exists()]
        if existing:
            raise FileExistsError(
                f'{participant_id} already exists at {", ".join(existing)}; '
                'participant data is never overwritten.'
            )
    else:
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
            try:
                assignment, slotting_rows, timeline, required, stats = build_plan(seed, block_order)
            except PlacementFailure as exc:
                failed_seeds.append(seed)
                if attempt == 5:
                    failed = ', '.join(map(str, failed_seeds))
                    raise PlanGenerationError(
                        f'Timeline placement failed after 5 attempts; failed seeds: {failed}.'
                    ) from exc
                continue
            write_slotting_key(participant_id, seed, slotting_rows, assignment, data_dir=temp_dir)
            validation_report(slotting_rows, required, timeline, stats)
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
            'config': config_snapshot(),
            'artifacts': {
                'stimulus_assignment': 'stimulus_assignment.csv',
                'slotting_key': 'slotting_key.csv',
                'timeline': 'timeline_key.csv',
                'seed': 'seed.txt',
            },
        }
        (temp_dir / 'participant_metadata.json').write_text(
            json.dumps(snapshot, indent=2, sort_keys=True, default=json_default), encoding='utf-8',
        )
        os.rename(temp_dir, participant_dir)
        return participant_dir / 'timeline_key.csv', snapshot
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
