"""Monte Carlo diagnostics for seeded timeline generation; writes no trial CSVs."""

import argparse
import json
import random
import time
from collections import Counter
from pathlib import Path

from config import WINDOW_SIZE
from slotting_key import build_slotting_key
from stimulus_split import split_pool
from timeline_key import PlacementFailure, _maximum_visual_events, build_timeline


MAX_EXAMPLE_FAILURES = 20


def _seed_inputs(seed):
    """Recreate the persisted slotting inputs using the production seed flow."""
    key_rng = random.Random(seed)
    assignment = split_pool(key_rng)
    source_rows = build_slotting_key(key_rng, assignment)

    # Match read_slotting_key's in-memory normalization of the CSV rows.
    slotting_rows = []
    for source in source_rows:
        row = dict(source)
        row['trial'] = int(row['trial'])
        row['slot_number'] = int(row['slot_number'])
        row['role'] = row['role'].strip()
        row['stimulus'] = (
            row.get('active_pt', '').strip() if row['role'] == 'PT'
            else row.get('npt_item', '').strip() if row['role'] == 'NPT'
            else ''
        )
        slotting_rows.append(row)
    return slotting_rows, assignment


def _run_seed(seed, diagnostics=None):
    slotting_rows, assignment = _seed_inputs(seed)
    timeline_rng = random.Random(seed)
    timeline, required, stats = build_timeline(
        slotting_rows, timeline_rng, assignment, WINDOW_SIZE,
        diagnostics=diagnostics,
    )
    return timeline, required, stats, diagnostics


def _classify_failure(exc, diagnostics):
    stage = diagnostics.get('stage', 'unknown')
    counts = diagnostics.get('trial_visual_counts', [])
    over_capacity = [
        item for item in counts if item['count'] > _maximum_visual_events()
    ]
    if stage == 'capacity_check' and over_capacity:
        return 'over_capacity'
    if isinstance(exc, PlacementFailure) and stage == 'placement':
        return 'placement_failure_within_capacity'
    if stage == 'validation':
        return 'validation_failure'
    return 'unexpected_internal_error'


def run_monte_carlo(n, start_seed=1, progress_every=0):
    count_distribution = Counter()
    reason_counts = Counter()
    failure_records = []
    trial_count = 0
    over_capacity_trials = 0
    max_visual_events = 0
    successful = 0
    placement_attempts = 0
    timeline_attempts = 0
    backtracks = 0
    max_trial_backtracks = 0
    started = time.monotonic()

    for index, seed in enumerate(range(start_seed, start_seed + n), start=1):
        pid = f'MC_{seed:06d}'
        diagnostics = {}
        try:
            _, _, stats, _ = _run_seed(seed, diagnostics)
            successful += 1
        except Exception as exc:  # Preserve all failure details and seed context.
            category = _classify_failure(exc, diagnostics)
            counts = diagnostics.get('trial_visual_counts', [])
            over_capacity = [
                item for item in counts if item['count'] > _maximum_visual_events()
            ]
            reason = str(exc).split(';', 1)[0]
            reason_key = category
            if category == 'over_capacity' and over_capacity:
                observed = max(item['count'] for item in over_capacity)
                reason_key = f'over_capacity_{observed}'
            reason_counts[reason_key] += 1
            failure_records.append({
                'seed': seed,
                'pid': pid,
                'category': category,
                'exception_type': type(exc).__name__,
                'message': str(exc),
                'stage': diagnostics.get('stage', 'unknown'),
                'reason': reason,
            })
            stats = diagnostics.get('placement_stats', {})

        counts = diagnostics.get('trial_visual_counts', [])
        trial_count += len(counts)
        for item in counts:
            event_count = item['count']
            count_distribution[event_count] += 1
            max_visual_events = max(max_visual_events, event_count)
            over_capacity_trials += event_count > _maximum_visual_events()
        placement_attempts += stats.get('placement_attempts', 0)
        timeline_attempts += diagnostics.get('timeline_attempts', stats.get('timeline_attempts', 0))
        backtracks += stats.get('backtracks', 0)
        max_trial_backtracks = max(
            max_trial_backtracks, stats.get('max_trial_backtracks', 0)
        )
        if progress_every and index % progress_every == 0:
            print(
                f'Progress: {index}/{n} seeds; successes={successful}, failures={len(failure_records)}',
                flush=True,
            )

    failed = len(failure_records)
    return {
        'seeds_tested': n,
        'start_seed': start_seed,
        'successful_timelines': successful,
        'failed_timelines': failed,
        'failure_rate': failed / n if n else 0.0,
        'failure_counts_by_reason': dict(sorted(reason_counts.items())),
        'visual_event_count_distribution': {
            str(event_count): {
                'count': count_distribution[event_count],
                'percentage': 100 * count_distribution[event_count] / trial_count if trial_count else 0.0,
            }
            for event_count in sorted(count_distribution)
        },
        'trials_observed': trial_count,
        'maximum_visual_events_observed': max_visual_events,
        'trials_with_27_visual_events': count_distribution[27],
        'percentage_of_trials_with_27_visual_events': (
            100 * count_distribution[27] / trial_count if trial_count else 0.0
        ),
        'over_capacity_trials': over_capacity_trials,
        'timelines_failed_over_capacity': sum(
            record['category'] == 'over_capacity' for record in failure_records
        ),
        'placement_failures_within_capacity': reason_counts['placement_failure_within_capacity'],
        'validation_failures': reason_counts['validation_failure'],
        'unexpected_internal_errors': reason_counts['unexpected_internal_error'],
        'placement_attempts': placement_attempts,
        'timeline_attempts': timeline_attempts,
        'backtracks': backtracks,
        'maximum_trial_backtracks': max_trial_backtracks,
        'elapsed_seconds': time.monotonic() - started,
        'failed_seeds': [record['seed'] for record in failure_records],
        'failures': failure_records,
    }


def _print_summary(summary):
    print('Monte Carlo timeline validation')
    print(f"Seeds tested: {summary['seeds_tested']}")
    print(f"Successful: {summary['successful_timelines']}")
    print(f"Failed: {summary['failed_timelines']}")
    print(f"Failure rate: {summary['failure_rate']:.2%}")
    print('\nFailure counts by reason:')
    if summary['failure_counts_by_reason']:
        for reason, count in summary['failure_counts_by_reason'].items():
            print(f'  {reason}: {count}')
    else:
        print('  none')
    print('\nVisual event count distribution (count, percentage of trials):')
    for event_count, values in summary['visual_event_count_distribution'].items():
        print(f"  {event_count}: {values['count']} ({values['percentage']:.2f}%)")
    print(f"Trials observed: {summary['trials_observed']}")
    print(f"Maximum visual events observed: {summary['maximum_visual_events_observed']}")
    print(
        f"Trials with 27 visual events: {summary['trials_with_27_visual_events']} "
        f"({summary['percentage_of_trials_with_27_visual_events']:.2f}%)"
    )
    print(f"Over-capacity trials: {summary['over_capacity_trials']}")
    print(f"Timelines failed over capacity: {summary['timelines_failed_over_capacity']}")
    print(f"Placement failures within capacity: {summary['placement_failures_within_capacity']}")
    print(f"Validation failures: {summary['validation_failures']}")
    print(f"Unexpected/internal errors: {summary['unexpected_internal_errors']}")
    print(
        f"Placement layouts/retries: {summary['placement_attempts']} / "
        f"{summary['timeline_attempts']}; backtracks: {summary['backtracks']} "
        f"(max in one trial: {summary['maximum_trial_backtracks']})"
    )
    print(f"Elapsed: {summary['elapsed_seconds']:.2f}s")
    print(f"\nExample failed seeds (first {MAX_EXAMPLE_FAILURES}):")
    for seed in summary['failed_seeds'][:MAX_EXAMPLE_FAILURES]:
        print(f'  {seed}')
    if not summary['failed_seeds']:
        print('  none')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--n', type=int, default=10_000, help='number of seeds to simulate (default: 10000)')
    parser.add_argument('--start-seed', type=int, default=1, help='first seed to simulate (default: 1)')
    parser.add_argument(
        '--progress-every', type=int, default=1000,
        help='print a progress line every N seeds (default: 1000; 0 disables)',
    )
    parser.add_argument(
        '--json-report', type=Path,
        help='optional path for one machine-readable summary including all failed seeds',
    )
    args = parser.parse_args()
    if args.n < 1 or args.progress_every < 0:
        parser.error('--n must be positive and --progress-every must be nonnegative')

    summary = run_monte_carlo(args.n, args.start_seed, args.progress_every)
    _print_summary(summary)
    if args.json_report:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
        print(f'\nJSON report: {args.json_report}')


if __name__ == '__main__':
    main()
