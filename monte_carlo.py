"""Monte Carlo diagnostics for seeded timeline generation; writes no trial CSVs."""

import argparse
import json
import random
import statistics
import time
from collections import Counter
from pathlib import Path

from config import (
    AUDIO_ROLES, FADE_IN_DUR, MIN_TARGET_END_TO_ONSET_GAP, MIN_VISUAL_ONSET_GAP,
    TARGET_ROLES, VISUAL_DURATION,
    TRIAL_NPD_RANGE, TRIAL_NPT_RANGE, TRIAL_PD_RANGE, TRIAL_PT_RANGE,
    WINDOW_SIZE,
)
from participant_setup import build_plan
from timeline_key import PlacementFailure, _maximum_visual_events, validate_timeline


MAX_EXAMPLE_FAILURES = 20
MAX_LAYOUT_TIMELINES = 250
LAYOUT_SIMILARITY_SAMPLE_PAIRS = 50_000
NEAR_EXACT_ONSET_RESOLUTION = 0.001


def _distribution(values):
    if not values:
        return {'count': 0, 'mean': None, 'standard_deviation': None,
                'minimum': None, 'median': None, 'maximum': None}
    return {
        'count': len(values), 'mean': statistics.fmean(values),
        'standard_deviation': statistics.pstdev(values), 'minimum': min(values),
        'median': statistics.median(values), 'maximum': max(values),
    }


def _layout_analysis(timelines, placement_stats, start_seed, n):
    """Summarize successful timelines; all rows originate in build_timeline."""
    onset_by_position = {}
    gaps = []
    target_end_gaps = []
    role_orders = Counter()
    identity_orders = Counter()
    normalized_layouts = Counter()
    intended_soas = []
    actual_soas = []
    abs_soa_errors = []
    attempts_by_timeline = []
    trial_records = []

    for timeline, stats in zip(timelines, placement_stats):
        by_trial = {}
        visuals = [row for row in timeline if row['event_type'] == 'visual']
        sounds_by_source = {
            row['source_event_id']: row for row in timeline
            if row['event_type'] == 'sound'
        }
        for row in visuals:
            by_trial.setdefault((row['block'], row['trial']), []).append(row)
            if row['role'] in AUDIO_ROLES:
                sound = sounds_by_source.get(row['event_id'])
                if sound is not None:
                    intended = float(sound['soa'])
                    # Production SOA is hold-start minus sound onset.
                    actual = row['global_onset'] + FADE_IN_DUR - sound['global_onset']
                    intended_soas.append(intended)
                    actual_soas.append(actual)
                    abs_soa_errors.append(abs(actual - intended))

        for (block, trial), events in by_trial.items():
            events.sort(key=lambda row: row['global_onset'])
            order = tuple(row['role'] for row in events)
            identities = tuple(
                (row['role'], row.get('stimulus', ''), row.get('event_id', ''))
                for row in events
            )
            onsets = [row['global_onset'] for row in events]
            local_onsets = [row['trial_onset'] for row in events]
            for position, (global_onset, local_onset) in enumerate(zip(onsets, local_onsets), 1):
                onset_by_position.setdefault(position, {'global': [], 'trial': []})
                onset_by_position[position]['global'].append(global_onset)
                onset_by_position[position]['trial'].append(local_onset)
            trial_gaps = [
                right['global_onset'] - left['global_onset']
                for left, right in zip(events, events[1:])
            ]
            gaps.extend(trial_gaps)
            targets = [row for row in events if row['role'] in TARGET_ROLES]
            target_end_gaps.extend(
                right['global_onset'] - (left['global_onset'] + VISUAL_DURATION)
                for left, right in zip(targets, targets[1:])
            )
            normalized = tuple(
                round((onset - onsets[0]) / NEAR_EXACT_ONSET_RESOLUTION)
                * NEAR_EXACT_ONSET_RESOLUTION for onset in onsets
            )
            role_orders[order] += 1
            identity_orders[identities] += 1
            normalized_layouts[(order, normalized)] += 1
            trial_records.append({
                'event_count': len(events), 'normalized_onsets': normalized,
            })

        attempts_by_timeline.append(stats.get('placement_attempts', 0))

    # Sample with replacement from valid equal-event-count groups. The fixed
    # range-derived RNG makes the reported distance sample reproducible.
    pair_rng = random.Random((start_seed * 1_000_003 + n) & ((1 << 64) - 1))
    groups = {}
    for record in trial_records:
        groups.setdefault(record['event_count'], []).append(record['normalized_onsets'])
    pairable = [(count, values) for count, values in groups.items() if len(values) >= 2]
    pair_distances = []
    if pairable:
        weights = [len(values) * (len(values) - 1) // 2 for _, values in pairable]
        total_weight = sum(weights)
        for _ in range(LAYOUT_SIMILARITY_SAMPLE_PAIRS):
            pick = pair_rng.randrange(total_weight)
            for group_index, weight in enumerate(weights):
                pick -= weight
                if pick < 0:
                    break
            values = pairable[group_index][1]
            i = pair_rng.randrange(len(values))
            j = pair_rng.randrange(len(values) - 1)
            if j >= i:
                j += 1
            pair_distances.append(statistics.fmean(
                abs(a - b) for a, b in zip(values[i], values[j])
            ))

    def top_patterns(counter, limit=10):
        total = sum(counter.values())
        return [
            {'pattern': repr(pattern), 'count': count,
             'percentage': 100 * count / total if total else 0.0}
            for pattern, count in counter.most_common(limit)
        ]

    onset_stats = {
        str(position): {
            'global_onset': _distribution(values['global']),
            'trial_onset': _distribution(values['trial']),
        }
        for position, values in sorted(onset_by_position.items())
    }
    gap_stats = _distribution(gaps)
    gap_stats.update({
        'minimum_allowed_gap': MIN_VISUAL_ONSET_GAP,
        'at_minimum_count': sum(abs(gap - MIN_VISUAL_ONSET_GAP) <= 1e-9 for gap in gaps),
        'at_minimum_percentage': 100 * sum(
            abs(gap - MIN_VISUAL_ONSET_GAP) <= 1e-9 for gap in gaps
        ) / len(gaps) if gaps else 0.0,
        'above_minimum_count': sum(gap > MIN_VISUAL_ONSET_GAP + 1e-9 for gap in gaps),
        'above_minimum_percentage': 100 * sum(
            gap > MIN_VISUAL_ONSET_GAP + 1e-9 for gap in gaps
        ) / len(gaps) if gaps else 0.0,
    })
    target_gap_stats = _distribution(target_end_gaps)
    target_gap_stats.update({
        'minimum_allowed_gap': MIN_TARGET_END_TO_ONSET_GAP,
        'at_minimum_count': sum(
            abs(gap - MIN_TARGET_END_TO_ONSET_GAP) <= 1e-9 for gap in target_end_gaps
        ),
        'above_minimum_count': sum(
            gap > MIN_TARGET_END_TO_ONSET_GAP + 1e-9 for gap in target_end_gaps
        ),
    })
    order_total = sum(role_orders.values())
    most_common_order, most_common_count = role_orders.most_common(1)[0] if role_orders else ((), 0)
    normalized_total = sum(normalized_layouts.values())
    normalized_most_common, normalized_most_count = (
        normalized_layouts.most_common(1)[0] if normalized_layouts else (None, 0)
    )
    return {
        'successful_timelines_analyzed': len(timelines),
        'visual_onset_by_position': onset_stats,
        'visual_gaps': gap_stats,
        'target_end_to_onset_gaps': target_gap_stats,
        'visual_order_diversity': {
            'successful_trials_analyzed': order_total,
            'unique_role_order_patterns': len(role_orders),
            'most_common_role_pattern': repr(most_common_order),
            'most_common_role_pattern_count': most_common_count,
            'most_common_role_pattern_percentage': 100 * most_common_count / order_total if order_total else 0.0,
            'top_10_role_patterns': top_patterns(role_orders),
            'unique_full_identity_patterns': len(identity_orders),
            'top_10_full_identity_patterns': top_patterns(identity_orders),
        },
        'onset_layout_similarity': {
            'method': 'Mean absolute difference between first-onset-normalized onset vectors, sampled with replacement from equal event-count trial groups.',
            'comparable_trials': len(trial_records),
            'sampled_pairs': len(pair_distances),
            'distance_seconds': _distribution(pair_distances),
        },
        'pt_pd_timing': {
            'measurement': 'PT/PD visual-to-associated-sound SOA; production SOA is hold-start minus sound onset. PT-to-PD visual pairs are not represented by a dedicated pair field in the production timeline.',
            'intended_soa_seconds': _distribution(intended_soas),
            'actual_soa_seconds': _distribution(actual_soas),
            'mean_absolute_difference_seconds': statistics.fmean(abs_soa_errors) if abs_soa_errors else None,
        },
        'schedule_repetition': {
            'normalized_signature_definition': 'Role order plus first-onset-relative visual onset vector rounded to 1 ms.',
            'unique_normalized_layout_signatures': len(normalized_layouts),
            'successful_trials_analyzed': normalized_total,
            'most_repeated_signature_count': normalized_most_count,
            'most_repeated_signature_percentage': 100 * normalized_most_count / normalized_total if normalized_total else 0.0,
            'most_repeated_signature': repr(normalized_most_common),
        },
        'placement_behavior': {
            'placement_attempts_total': sum(attempts_by_timeline),
            'placement_attempts_per_successful_timeline': _distribution(attempts_by_timeline),
        },
        'sampling': {
            'layout_similarity_pairs': len(pair_distances),
            'similarity_sampling_seed': (start_seed * 1_000_003 + n) & ((1 << 64) - 1),
            'near_exact_signature_onset_resolution_seconds': NEAR_EXACT_ONSET_RESOLUTION,
            'note': 'No categorical high/moderate/low labels are assigned; inspect the reported measurements directly.',
        },
    }


def _audit_timeline(timeline, required, assignment, slotting_rows, count_ranges=None):
    """Re-run the single full rule check on the finished timeline."""
    validate_timeline(
        slotting_rows, required, timeline, assignment, WINDOW_SIZE, count_ranges=count_ranges,
    )


def _run_seed(seed, diagnostics=None, count_ranges=None):
    assignment, slotting_rows, timeline, required, stats = build_plan(
        seed, ['animate', 'inanimate'], count_ranges, diagnostics=diagnostics,
    )
    if diagnostics is not None:
        diagnostics['stage'] = 'monte_carlo_audit'
    _audit_timeline(timeline, required, assignment, slotting_rows, count_ranges)
    return timeline, required, stats, diagnostics


def _classify_failure(exc, diagnostics):
    stage = diagnostics.get('stage', 'unknown')
    if stage == 'monte_carlo_audit':
        return 'independent_validation_failure'
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


def run_monte_carlo(n, start_seed=1, progress_every=0, count_ranges=None):
    count_distribution = Counter()
    reason_counts = Counter()
    failure_records = []
    successful_layouts = []
    successful_placement_stats = []
    trial_count = 0
    over_capacity_trials = 0
    max_visual_events = 0
    successful = 0
    placement_attempts = 0
    timeline_attempts = 0
    first_attempt_successes = 0
    layout_rng = random.Random((start_seed * 2_000_033 + n) & ((1 << 64) - 1))
    started = time.monotonic()

    for index, seed in enumerate(range(start_seed, start_seed + n), start=1):
        pid = f'MC_{seed:06d}'
        diagnostics = {}
        try:
            timeline, _, stats, _ = _run_seed(seed, diagnostics, count_ranges)
            successful += 1
            if diagnostics.get('timeline_attempts') == 1:
                first_attempt_successes += 1
            if len(successful_layouts) < MAX_LAYOUT_TIMELINES:
                successful_layouts.append(timeline)
                successful_placement_stats.append(dict(stats))
            else:
                replacement = layout_rng.randrange(successful)
                if replacement < MAX_LAYOUT_TIMELINES:
                    successful_layouts[replacement] = timeline
                    successful_placement_stats[replacement] = dict(stats)
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
        if progress_every and index % progress_every == 0:
            print(
                f'Progress: {index:,}/{n:,} seeds; successes={successful:,}, failures={len(failure_records):,}',
                flush=True,
            )

    failed = len(failure_records)
    summary = {
        'seeds_tested': n,
        'start_seed': start_seed,
        'successful_timelines': successful,
        'first_attempt_successes': first_attempt_successes,
        'first_attempt_success_rate': first_attempt_successes / n if n else 0.0,
        'layout_analysis_sampled_timelines': len(successful_layouts),
        'count_ranges': {
            role: (count_ranges or {}).get(role, bounds)
            for role, bounds in {
                'PT': TRIAL_PT_RANGE, 'NPT': TRIAL_NPT_RANGE,
                'PD': TRIAL_PD_RANGE, 'NPD': TRIAL_NPD_RANGE,
            }.items()
        },
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
        'over_capacity_trials': over_capacity_trials,
        'timelines_failed_over_capacity': sum(
            record['category'] == 'over_capacity' for record in failure_records
        ),
        'placement_failures_within_capacity': reason_counts['placement_failure_within_capacity'],
        'validation_failures': reason_counts['validation_failure'],
        'unexpected_internal_errors': reason_counts['unexpected_internal_error'],
        'placement_attempts': placement_attempts,
        'timeline_attempts': timeline_attempts,
        'elapsed_seconds': time.monotonic() - started,
        'failed_seeds': [record['seed'] for record in failure_records],
        'failures': failure_records,
    }
    summary['variability_analysis'] = _layout_analysis(
        successful_layouts, successful_placement_stats, start_seed, n,
    )
    return summary


def _print_summary(summary):
    print('Monte Carlo timeline validation')
    print(f"Seeds tested: {summary['seeds_tested']:,}")
    print(f"Successful: {summary['successful_timelines']:,}")
    print(f"Failed: {summary['failed_timelines']:,}")
    print(f"Failure rate: {summary['failure_rate']:.2%}")
    print(f"First-attempt success rate: {summary['first_attempt_success_rate']:.2%}")
    print('\nFailure counts by reason:')
    if summary['failure_counts_by_reason']:
        for reason, count in summary['failure_counts_by_reason'].items():
            print(f'  {reason}: {count:,}')
    else:
        print('  none')
    print('\nVisual event count distribution (count, percentage of trials):')
    for event_count, values in summary['visual_event_count_distribution'].items():
        print(f"  {event_count}: {values['count']:,} ({values['percentage']:.2f}%)")
    print(f"Trials observed: {summary['trials_observed']:,}")
    print(f"Maximum visual events observed: {summary['maximum_visual_events_observed']:,}")
    print(f"Over-capacity trials: {summary['over_capacity_trials']:,}")
    print(f"Timelines failed over capacity: {summary['timelines_failed_over_capacity']:,}")
    print(f"Placement failures within capacity: {summary['placement_failures_within_capacity']:,}")
    print(f"Validation failures: {summary['validation_failures']:,}")
    print(f"Unexpected/internal errors: {summary['unexpected_internal_errors']:,}")
    print(
        f"Randomized placement orders: {summary['placement_attempts']:,}; "
        f"whole-timeline attempts: {summary['timeline_attempts']:,}"
    )
    print(f"Elapsed: {summary['elapsed_seconds']:.2f}s")
    print(f"\nExample failed seeds (first {MAX_EXAMPLE_FAILURES}):")
    for seed in summary['failed_seeds'][:MAX_EXAMPLE_FAILURES]:
        print(f'  {seed}')
    if not summary['failed_seeds']:
        print('  none')


def _print_distribution(label, values):
    if values['count']:
        print(
            f"  n={values['count']:,}; mean={values['mean']:.3f}s; "
            f"SD={values['standard_deviation']:.3f}s; min={values['minimum']:.3f}s; "
            f"median={values['median']:.3f}s; max={values['maximum']:.3f}s"
        )
    else:
        print('  no observations')


def _print_variability(analysis):
    print('\nVISUAL ONSET VARIABILITY')
    for position, values in analysis['visual_onset_by_position'].items():
        glob, local = values['global_onset'], values['trial_onset']
        print(f"Position {position} (global): mean={glob['mean']:.3f}s, SD={glob['standard_deviation']:.3f}s, min={glob['minimum']:.3f}s, max={glob['maximum']:.3f}s")
        print(f"             (within trial): mean={local['mean']:.3f}s, SD={local['standard_deviation']:.3f}s, min={local['minimum']:.3f}s, max={local['maximum']:.3f}s")

    gaps = analysis['visual_gaps']
    print('\nVISUAL GAP VARIABILITY')
    _print_distribution('gaps', gaps)
    print(f"  at minimum gap ({gaps['minimum_allowed_gap']:.3f}s): {gaps['at_minimum_percentage']:.2f}%")
    print(f"  above minimum gap: {gaps['above_minimum_percentage']:.2f}%")

    target_gaps = analysis['target_end_to_onset_gaps']
    print('\nTARGET FADE-END TO NEXT-TARGET GAPS')
    _print_distribution('target gaps', target_gaps)
    print(f"  at minimum gap ({target_gaps['minimum_allowed_gap']:.3f}s): {target_gaps['at_minimum_count']:,}")

    orders = analysis['visual_order_diversity']
    print('\nVISUAL ORDER DIVERSITY')
    print(f"  Successful trials analyzed: {orders['successful_trials_analyzed']:,}")
    print(f"  Unique role-order patterns: {orders['unique_role_order_patterns']:,}")
    print(f"  Most common role pattern: {orders['most_common_role_pattern']} — {orders['most_common_role_pattern_count']:,} ({orders['most_common_role_pattern_percentage']:.2f}%)")
    print('  Top role patterns:')
    for index, item in enumerate(orders['top_10_role_patterns'], 1):
        print(f"    {index}. {item['pattern']} — {item['count']:,} ({item['percentage']:.2f}%)")
    print(f"  Unique full identity patterns: {orders['unique_full_identity_patterns']:,}")

    similarity = analysis['onset_layout_similarity']
    print('\nONSET-LAYOUT SIMILARITY')
    print(f"  Comparable trials: {similarity['comparable_trials']:,}; sampled pairs: {similarity['sampled_pairs']:,}")
    _print_distribution('layout distance', similarity['distance_seconds'])

    timing = analysis['pt_pd_timing']
    print('\nPT/PD PAIRED AUDIOVISUAL SOA VARIABILITY')
    print('  Intended SOA:')
    _print_distribution('intended', timing['intended_soa_seconds'])
    print('  Actual SOA:')
    _print_distribution('actual', timing['actual_soa_seconds'])
    if timing['mean_absolute_difference_seconds'] is not None:
        print(f"  Mean absolute actual/intended difference: {timing['mean_absolute_difference_seconds']:.6f}s")
    print(f"  Note: {timing['measurement']}")

    repetition = analysis['schedule_repetition']
    print('\nEXACT/NEAR-EXACT SCHEDULE REPETITION')
    print(f"  Unique normalized layout signatures: {repetition['unique_normalized_layout_signatures']:,}")
    print(f"  Successful trials analyzed: {repetition['successful_trials_analyzed']:,}")
    print(f"  Most repeated signature: {repetition['most_repeated_signature_count']:,} ({repetition['most_repeated_signature_percentage']:.2f}%)")
    print(f"  Signature definition: {repetition['normalized_signature_definition']}")

    placement = analysis['placement_behavior']
    print('\nPLACEMENT ATTEMPT VARIABILITY')
    print(f"  Placement attempts total: {placement['placement_attempts_total']:,}")
    print(f"  Placement attempts per successful timeline: {placement['placement_attempts_per_successful_timeline']}")

    print('\n' + '=' * 60)
    print('SCHEDULE VARIABILITY ASSESSMENT')
    print('=' * 60)
    print('Insufficient evidence for categorical high/moderate/low labels; inspect the measured distributions above.')
    if similarity['distance_seconds']['count']:
        print(
            f"Interpretation: among {similarity['sampled_pairs']:,} reproducibly sampled equal-event-count trial pairs, "
            f"the mean normalized onset-layout distance was "
            f"{similarity['distance_seconds']['mean']:.3f}s (median "
            f"{similarity['distance_seconds']['median']:.3f}s). The most common "
            f"normalized signature occurred in {repetition['most_repeated_signature_percentage']:.2f}% "
            'of analyzed trials.'
        )


def _worst_case_ranges():
    return {
        'PT': (TRIAL_PT_RANGE[1], TRIAL_PT_RANGE[1]),
        'NPT': (TRIAL_NPT_RANGE[1], TRIAL_NPT_RANGE[1]),
        'PD': (TRIAL_PD_RANGE[1], TRIAL_PD_RANGE[1]),
        'NPD': (TRIAL_NPD_RANGE[1], TRIAL_NPD_RANGE[1]),
    }


def _sweep_ranges():
    """Sweep NPT/NPD upper bounds while keeping their configured minima fixed."""
    for npt_max in range(TRIAL_NPT_RANGE[0], TRIAL_NPT_RANGE[1] + 1):
        for npd_max in range(TRIAL_NPD_RANGE[0], TRIAL_NPD_RANGE[1] + 1):
            yield {
                'PT': TRIAL_PT_RANGE,
                'NPT': (TRIAL_NPT_RANGE[0], npt_max),
                'PD': TRIAL_PD_RANGE,
                'NPD': (TRIAL_NPD_RANGE[0], npd_max),
            }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--n', type=int, default=None,
        help='number of seeds to simulate (prompt interactively when omitted)',
    )
    parser.add_argument('--start-seed', type=int, default=1, help='first seed to simulate (default: 1)')
    parser.add_argument(
        '--progress-every', type=int, default=1000,
        help='print a progress line every N seeds (default: 1000; 0 disables)',
    )
    parser.add_argument(
        '--json-report', type=Path,
        help='optional path for one machine-readable summary including all failed seeds',
    )
    scenario_group = parser.add_mutually_exclusive_group()
    scenario_group.add_argument(
        '--worst-case', action='store_true',
        help='set PT, NPT, PD, and NPD counts to their configured maxima',
    )
    scenario_group.add_argument(
        '--sweep', action='store_true',
        help='sweep all NPT/NPD upper-bound combinations, keeping minima fixed',
    )
    args = parser.parse_args()
    if args.progress_every < 0:
        parser.error('--progress-every must be nonnegative')

    if args.n is None:
        print('=' * 60)
        print('MONTE CARLO TIMELINE VALIDATION')
        print('=' * 60)
        while True:
            try:
                response = input('\nHow many seeds would you like to test? ')
            except EOFError:
                parser.error('no seed count was provided')
            try:
                n = int(response)
                if n > 0:
                    break
            except ValueError:
                pass
            print('Please enter a positive whole number (for example, 10000).')
    else:
        n = args.n
        if n < 1:
            parser.error('--n must be positive')

    print(f'\nSeeds to test: {n:,}')
    print(f'Seed range: {args.start_seed:,}–{args.start_seed + n - 1:,}\n')

    try:
        if args.sweep:
            results = []
            scenarios = list(_sweep_ranges())
            for index, ranges in enumerate(scenarios, start=1):
                label = f"NPT={ranges['NPT']} NPD={ranges['NPD']}"
                print(f'\nSweep {index}/{len(scenarios)}: {label}')
                result = run_monte_carlo(
                    n, args.start_seed, args.progress_every, count_ranges=ranges,
                )
                results.append({'ranges': ranges, 'result': result})
                print(
                    f"  success={result['successful_timelines']}/{n}; "
                    f"first_attempt={result['first_attempt_success_rate']:.1%}; "
                    f"failures={result['failure_counts_by_reason']}"
                )
            summary = {
                'scenario': 'npt_npd_upper_bound_sweep',
                'seeds_per_scenario': n,
                'start_seed': args.start_seed,
                'scenarios': results,
            }
        else:
            ranges = _worst_case_ranges() if args.worst_case else None
            summary = run_monte_carlo(
                n, args.start_seed, args.progress_every, count_ranges=ranges,
            )
    except KeyboardInterrupt:
        print('\nMonte Carlo simulation interrupted.')
        return
    if args.sweep:
        print(f"\nCompleted {len(summary['scenarios'])} range-sweep scenarios.")
    else:
        _print_summary(summary)
        _print_variability(summary['variability_analysis'])
    if args.json_report:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
        print(f'\nJSON report: {args.json_report}')


if __name__ == '__main__':
    main()
