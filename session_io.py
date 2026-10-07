"""Filesystem persistence helpers that do not depend on PsychoPy."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _participant_identity(folder: Path):
    metadata_path = folder / 'participant_metadata.json'
    metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    return metadata.get('seed'), sha256_file(metadata_path)


def copy_participant_tree(local_dir: Path, destination: Path) -> dict:
    """Copy missing files only; refuse conflicting participant identities or files."""
    local_dir, destination = Path(local_dir), Path(destination)
    copied, verified, failures = [], [], []
    if destination.exists():
        try:
            if _participant_identity(local_dir) != _participant_identity(destination):
                return {
                    'status': 'collision', 'destination': str(destination),
                    'reason': 'Existing server participant metadata has a different seed or sha256.',
                    'verified_files': [], 'failures': [],
                }
        except (OSError, ValueError, KeyError) as exc:
            return {
                'status': 'collision', 'destination': str(destination),
                'reason': f'Could not verify existing server participant identity: {exc}',
                'verified_files': [], 'failures': [],
            }

    try:
        for source_dir, _, filenames in os.walk(local_dir):
            relative = Path(source_dir).relative_to(local_dir)
            target_dir = destination / relative
            target_dir.mkdir(parents=True, exist_ok=True)
            for filename in filenames:
                source = Path(source_dir) / filename
                target = target_dir / filename
                relative_name = str(target.relative_to(destination))
                try:
                    if target.exists():
                        if sha256_file(source) != sha256_file(target):
                            failures.append(f'{relative_name}: destination checksum differs; preserved')
                        else:
                            verified.append(relative_name)
                        continue
                    try:
                        with source.open('rb') as src, target.open('xb') as dst:
                            shutil.copyfileobj(src, dst)
                    except FileExistsError:
                        if sha256_file(source) == sha256_file(target):
                            verified.append(relative_name)
                        else:
                            failures.append(f'{relative_name}: destination appeared with different content')
                        continue
                    if sha256_file(source) == sha256_file(target):
                        copied.append(relative_name)
                    else:
                        failures.append(f'{relative_name}: checksum mismatch after copy')
                except OSError as exc:
                    failures.append(f'{relative_name}: {type(exc).__name__}: {exc}')
        if any('checksum differs' in failure or 'different content' in failure for failure in failures):
            status = 'collision'
        else:
            status = 'copied' if not failures else 'partial'
        return {
            'status': status, 'destination': str(destination),
            'verified_files': copied + verified, 'failures': failures,
        }
    except OSError as exc:
        return {
            'status': 'failed', 'destination': str(destination),
            'reason': f'{type(exc).__name__}: {exc}',
            'verified_files': copied + verified, 'failures': failures,
        }
