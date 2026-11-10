"""Compare candidate difficulty settings on the plan generator.

config values are bound at import time by timeline_key, so each variant runs
tools/scheduler_bench.py in its own subprocess and the JSON summaries are
compared here. This measures placement only: perceptually harder settings such
as BG_NOISE_OPACITY never reach the planner and cannot be compared this way, so
they are left out rather than shown as identical rows.

    python3 tools/difficulty_sweep.py --seeds 50 --lengths 8,100 \
        --json benchmarks/difficulty.json
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Smallest change first: raising the NPD count adds pictures around each target
# without moving the answer, while the response window is the speed arm the
# pilot already sat at ceiling on (hit RT 90th percentile 0.71 s of 0.9 s).
VARIANTS = (
    ('baseline', ()),
    ('NPD 40-48', ('TRIAL_NPD_RANGE=(40, 48)',)),
    ('NPD 44-52', ('TRIAL_NPD_RANGE=(44, 52)',)),
    ('window 0.8', ('RESPONSE_WINDOW=0.8',)),
)


def run_variant(overrides, args):
    """One scheduler_bench run, in its own process so config binds fresh."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / 'bench.json'
        command = [
            sys.executable, str(ROOT / 'tools' / 'scheduler_bench.py'),
            '--lengths', args.lengths, '--seeds', str(args.seeds),
            '--repro', str(args.repro), '--json', str(out),
        ]
        for override in overrides:
            command += ['--set', override]
        if args.ranges:
            command += ['--ranges', args.ranges]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            raise SystemExit(
                f'scheduler_bench failed for {overrides or "baseline"}:\n'
                f'{result.stdout}\n{result.stderr}'
            )
        return json.loads(out.read_text())


def mean(profile, key):
    entry = profile.get(key)
    return entry['mean'] if entry else None


def summarise(name, bench):
    rows = []
    for result in bench['results']:
        profile = result['timing_profile']
        rows.append({
            'variant': name,
            'overrides': list(result.get('overrides', ())),
            'total_trials': result['total_trials'],
            'success_rate': round(result['success_rate'], 3),
            'first_attempt_rate': round(result['first_attempt_successes'] / result['n'], 3),
            'visuals_per_trial': round(mean(profile, 'visuals_per_trial') or 0.0, 2),
            'targets_per_trial': round(mean(profile, 'targets_per_trial') or 0.0, 2),
            'target_prevalence': round(mean(profile, 'target_prevalence') or 0.0, 3),
            'other_onsets_in_target_window': round(
                mean(profile, 'other_onsets_in_target_window') or 0.0, 2),
            'median_orders_per_plan': result['placement_orders_per_plan']['median'],
            'failed_trial_placements': result['trial_placement_failures'],
            'trial_placements': result['trial_placement_calls'],
        })
    return rows


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--seeds', type=int, default=50)
    parser.add_argument('--lengths', default='8,100', help='total trials per block pair')
    parser.add_argument('--repro', type=int, default=0)
    parser.add_argument('--ranges', default=None,
                        help='JSON count ranges, passed through to scheduler_bench')
    parser.add_argument('--json', type=Path)
    args = parser.parse_args()

    rows = []
    for name, overrides in VARIANTS:
        rows.extend(summarise(name, run_variant(overrides, args)))

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps({'variants': [list(variant) for variant in VARIANTS], 'rows': rows},
                       indent=1) + '\n'
        )

    print('| variant | total trials | success | 1st attempt | visuals/trial | targets/trial '
          '| target prevalence | other onsets in window | median orders/plan '
          '| failed trial placements |')
    print('|---|---|---|---|---|---|---|---|---|---|')
    for row in rows:
        print(
            f"| {row['variant']} | {row['total_trials']} | {row['success_rate']:.3f} "
            f"| {row['first_attempt_rate']:.3f} | {row['visuals_per_trial']:.2f} "
            f"| {row['targets_per_trial']:.2f} | {row['target_prevalence']:.3f} "
            f"| {row['other_onsets_in_target_window']:.2f} "
            f"| {row['median_orders_per_plan']:.0f} "
            f"| {row['failed_trial_placements']}/{row['trial_placements']} |"
        )


if __name__ == '__main__':
    main()
