"""Compare the machines that ran the study: versions, display, audio, hardware.

Reads every session_metadata.json under the given data roots (by default the
local data/ directory plus the mounted lab server) and prints one row per
device. Values come from the preflight report each session stores, so a machine
that never passed preflight shows up as unknown instead of staying silent.

    python3 tools/device_report.py
    python3 tools/device_report.py --data /mnt/camp-lab-server/Anthony/data
    python3 tools/device_report.py --json

Differences between devices are listed under the table; the exit status is 0
even when they exist, so this can be run midway through a pilot.
"""

import argparse
import json
import os
import sys
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Field name in the preflight report -> column heading.
FIELDS = OrderedDict([
    ('machine_name', 'machine'),
    ('machine_uuid', 'uuid'),
    ('machine_model', 'model'),
    ('machine_serial', 'serial'),
    ('machine_mac', 'mac'),
    ('hardware_host', 'host'),
    ('hardware_cpu', 'cpu'),
    ('hardware_gpu', 'gpu'),
    ('hardware_kernel', 'kernel'),
    ('python_version', 'python'),
    ('psychopy_version', 'psychopy'),
    ('psychtoolbox_version', 'psychtoolbox'),
    ('numpy_version', 'numpy'),
    ('pillow_version', 'pillow'),
    ('display_output', 'output'),
    ('active_mode', 'mode'),
    ('display_refresh_hz', 'refresh'),
    ('audio_route_device', 'output device'),
    ('audio_chain', 'audio chain'),
    ('system_volume_percent', 'volume %'),
    ('git_branch', 'branch'),
    ('git_commit', 'commit'),
    ('git_dirty', 'dirty'),
])

# Columns that are expected to differ (a device name or id) and are never
# reported as a parity problem.
EXPECTED_DIFFERENCES = {
    'machine', 'uuid', 'model', 'serial', 'mac', 'host', 'commit', 'dirty',
}


def default_roots():
    """Local data directory, then the server data root when it is mounted."""
    roots = [ROOT / 'data']
    server_root = os.environ.get('AV_STUDY_SERVER_ROOT')
    server_path = os.environ.get('AV_STUDY_SERVER_DATA_PATH')
    if server_root:
        server = Path(server_root)
        if server_path:
            server = server / server_path if not Path(server_path).is_absolute() else Path(server_path)
        else:
            server = server / 'data'
        roots.append(server)
    return roots


def sessions_in(root):
    """Yield (participant_id, session_name, metadata) for one data root."""
    root = Path(root)
    if not root.is_dir():
        return
    for participant_dir in sorted(root.iterdir()):
        if not participant_dir.is_dir() or not participant_dir.name.startswith('participant_'):
            continue
        for session_dir in sorted(participant_dir.glob('session_*')):
            metadata_path = session_dir / 'session_metadata.json'
            if not metadata_path.is_file():
                continue
            try:
                metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            yield participant_dir.name, session_dir.name, metadata


def collect(roots):
    """One row per (device, participant, session), with server copies collapsed."""
    seen = set()
    devices = OrderedDict()
    duplicates = 0
    for root in roots:
        for participant_id, session_name, metadata in sessions_in(root):
            key = (participant_id, session_name, metadata.get('started_utc'))
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            preflight = metadata.get('preflight') or {}
            values = {name: str(preflight.get(name, '')) for name in FIELDS}
            if not values['hardware_host']:
                values['hardware_host'] = str(metadata.get('participant_claim', {}).get('host', 'unknown'))
            # The first eight characters identify an install without filling the table.
            values['machine_uuid'] = values['machine_uuid'][:8]
            device = values['machine_name'] or values['hardware_host'] or 'unknown'
            record = devices.setdefault(device, {'sessions': [], 'values': values})
            record['sessions'].append({
                'participant': participant_id,
                'session': session_name,
                'completed': metadata.get('completion_status', 'unknown'),
                'started_utc': metadata.get('started_utc', ''),
            })
            # Fill blanks in a device row from its other sessions.
            for name, value in values.items():
                record['values'][name] = record['values'].get(name) or value
    return devices, duplicates


def shorten(value, width=26):
    value = str(value)
    return value if len(value) <= width else value[:width - 1] + '…'


def differences(devices):
    """Per column, the distinct values and which devices carry each one."""
    report = []
    for name, heading in FIELDS.items():
        if heading in EXPECTED_DIFFERENCES:
            continue
        grouped = OrderedDict()
        for device, record in devices.items():
            grouped.setdefault(record['values'].get(name, ''), []).append(device)
        known = {value: hosts for value, hosts in grouped.items() if value not in ('', 'None')}
        if len(known) > 1 or (known and '' in grouped):
            report.append((heading, known, grouped.get('', [])))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--data', action='append', default=None,
                        help='data root to scan (repeatable); defaults to local data/ plus the lab server')
    parser.add_argument('--json', action='store_true', help='print the collected rows as JSON')
    args = parser.parse_args(argv)

    roots = [Path(path).expanduser() for path in args.data] if args.data else default_roots()
    devices, duplicates = collect(roots)

    if args.json:
        print(json.dumps({
            'roots': [str(root) for root in roots],
            'duplicate_sessions_skipped': duplicates,
            'devices': {
                device: {'sessions': record['sessions'], 'values': record['values']}
                for device, record in devices.items()
            },
        }, indent=2, sort_keys=True))
        return 0

    print('scanned: ' + ', '.join(str(root) for root in roots))
    if duplicates:
        print(f'{duplicates} duplicate session(s) skipped (same participant, session and start time)')
    if not devices:
        print('\nNo sessions with metadata found. Run preflight and a session first, or pass --data.')
        return 0

    columns = ['machine', 'sessions', 'participants'] + [
        name for name in FIELDS if name not in ('machine_name', 'hardware_host')
    ]
    widths = {column: len(column) for column in columns}
    table = []
    for device, record in devices.items():
        participants = sorted({session['participant'] for session in record['sessions']})
        cells = {
            'machine': device,
            'sessions': str(len(record['sessions'])),
            'participants': ','.join(
                participant.replace('participant_', '') for participant in participants
            ),
        }
        for name in columns[3:]:
            cells[name] = record['values'].get(name, '') or '—'
        table.append(cells)
        for column in columns:
            widths[column] = max(widths[column], len(shorten(cells[column])))

    print()
    print('  '.join(column.ljust(widths[column]) for column in columns))
    for cells in table:
        print('  '.join(shorten(cells[column]).ljust(widths[column]) for column in columns))

    mismatches = differences(devices)
    print()
    if not mismatches:
        print(f'✅ {len(devices)} device(s) agree on every recorded value.')
        return 0
    print(f'⚠️  {len(mismatches)} field(s) differ between devices:')
    for heading, known, unknown in mismatches:
        for value, hosts in known.items():
            print(f'   {heading}: {value or "(empty)"} — {", ".join(hosts)}')
        if unknown:
            print(f'   {heading}: not recorded — {", ".join(unknown)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
