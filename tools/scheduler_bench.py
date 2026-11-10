"""Benchmark participant-plan generation across session lengths; writes no plan files.

Runs the real participant_setup.build_plan path for a fixed seed range, sets the
session length through stimulus_split.TRIALS_PER_PT (trials per block =
PT_COUNT_PER_BLOCK * TRIALS_PER_PT), and checks every plan with plan_validator.

    python3 tools/scheduler_bench.py --lengths 8,100 --seeds 100 --placer baseline \
        --json benchmarks/baseline.json
    python3 tools/scheduler_bench.py --set FADE_IN_DUR=0.15 --set FADE_OUT_DUR=0.15 ...

--set overrides are applied to config before any study module is imported,
because timeline_key binds config values at import time.
"""

import argparse
import hashlib
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]


def apply_overrides(pairs):
    import config
    for pair in pairs:
        name, value = pair.split('=', 1)
        setattr(config, name, eval(value, {}))  # trusted CLI input: numbers and tuples
    config.VISUAL_DURATION = config.FADE_IN_DUR + config.PEAK_HOLD_DUR + config.FADE_OUT_DUR
    config.TARGET_CORNER_HOLD = config.RESPONSE_WINDOW + config.LATE_WINDOW
    config.TRIAL_DURATION = 2 * config.TRIAL_BUFFER_DUR + config.TRIAL_CONTENT_DUR


def trial_load(events):
    """Order-independent lower bounds on the time each constraint family needs."""
    import config as c
    from timeline_key import _lower_bounds
    targets = [e for e in events if e['role'] in c.TARGET_ROLES]
    audio = sum(e['role'] in c.AUDIO_ROLES for e in events)
    bounds = _lower_bounds(events)
    binding = max(bounds, key=bounds.get)
    corner_counts = Counter(e['corner'] for e in targets)
    return {'visuals': len(events), 'targets': len(targets), 'audio': audio,
            'max_target_corner_share': (
                round(max(corner_counts.values()) / len(targets), 3) if targets else None),
            'binding': binding, 'load': bounds[binding] / c.TRIAL_CONTENT_DUR,
            **{f'lb_{k}': round(v, 3) for k, v in bounds.items()}}


def plan_hash(slotting_rows, timeline):
    blob = json.dumps([slotting_rows, timeline], sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def dist(values):
    if not values:
        return None
    q = statistics.quantiles(values, n=4) if len(values) > 1 else [values[0]] * 3
    return {'n': len(values), 'mean': round(statistics.fmean(values), 4),
            'sd': round(statistics.pstdev(values), 4), 'q1': round(q[0], 4),
            'median': round(q[1], 4), 'q3': round(q[2], 4)}


def timing_profile(timelines):
    """Distributions that a placement change could bias."""
    import config as c
    onsets = defaultdict(list)
    gaps, packed, spans, first_target_pos = [], 0, [], []
    visuals_per_trial, targets_per_trial = [], []
    crowding, prevalence = [], []
    for timeline in timelines:
        by_trial = defaultdict(list)
        for r in timeline:
            if r['event_type'] == 'visual':
                by_trial[(r['block'], r['trial'])].append(r)
                onsets[r['role']].append(r['trial_onset'] - c.TRIAL_BUFFER_DUR)
        for rows in by_trial.values():
            rows.sort(key=lambda r: r['global_onset'])
            g = [b['global_onset'] - a['global_onset'] for a, b in zip(rows, rows[1:])]
            gaps.extend(g)
            packed += sum(x < c.MIN_VISUAL_ONSET_GAP + 1e-3 for x in g)
            spans.append(rows[-1]['global_onset'] + c.VISUAL_DURATION - rows[0]['global_onset'])
            first_target_pos.extend(i / (len(rows) - 1) for i, r in enumerate(rows)
                                    if r['role'] in c.TARGET_ROLES)
            targets = [r for r in rows if r['role'] in c.TARGET_ROLES]
            visuals_per_trial.append(len(rows))
            targets_per_trial.append(len(targets))
            if rows:
                prevalence.append(len(targets) / len(rows))
            # Pictures that appear inside each target's response window: the
            # crowding a heavier load setting is meant to raise, and the load
            # the pilot data could not judge because hits were at ceiling.
            for target in targets:
                start = target['global_onset']
                end = start + c.RESPONSE_WINDOW
                crowding.append(sum(
                    other is not target and start <= other['global_onset'] < end
                    for other in rows
                ))
    return {
        'content_onset_by_role': {role: dist(v) for role, v in sorted(onsets.items())},
        'adjacent_visual_gap': dist(gaps),
        'gaps_at_minimum_onset_gap_pct': round(100 * packed / len(gaps), 2) if gaps else None,
        'trial_span_seconds': dist(spans),
        'target_rank_in_trial_0_to_1': dist(first_target_pos),
        'visuals_per_trial': dist(visuals_per_trial),
        'targets_per_trial': dist(targets_per_trial),
        'target_prevalence': dist(prevalence),
        'other_onsets_in_target_window': dist(crowding),
    }


def run_length(trials_per_block, seeds, placer_name, repro, count_ranges):
    import config
    import stimulus_split
    import timeline_key
    from participant_setup import build_plan
    from plan_validator import validate_plan
    from timeline_key import PlacementFailure

    if trials_per_block % config.PT_COUNT_PER_BLOCK:
        raise SystemExit(f'{trials_per_block} trials per block is not a multiple of '
                         f'PT_COUNT_PER_BLOCK={config.PT_COUNT_PER_BLOCK}.')
    trials_per_pt = trials_per_block // config.PT_COUNT_PER_BLOCK
    stimulus_split.TRIALS_PER_PT = config.TRIALS_PER_PT = trials_per_pt

    if placer_name != 'current':
        import placement_experiments
        placement_experiments.install(placer_name)
    placer = timeline_key._construct_trial_schedule
    trial_calls = []

    def instrumented(events, trial_start, stats, **kwargs):
        before = stats['placement_attempts']
        record = trial_load(events)
        record['repair'] = kwargs.get('repair', False)
        try:
            result = placer(events, trial_start, stats, **kwargs)
            record['ok'] = True
            return result
        except PlacementFailure:
            record['ok'] = False
            raise
        finally:
            record['orders'] = stats['placement_attempts'] - before
            trial_calls.append(record)

    timeline_key._construct_trial_schedule = instrumented
    records, timelines, hashes = [], [], {}
    try:
        for seed in seeds:
            trial_calls.clear()
            diagnostics = {}
            started = time.perf_counter()
            rec = {'seed': seed}
            try:
                assignment, slotting, timeline, _, stats = build_plan(
                    seed, ['animate', 'inanimate'], count_ranges, diagnostics=diagnostics)
                rec['seconds'] = time.perf_counter() - started
                rec['ok'] = True
                errors = validate_plan(assignment, slotting, timeline, trials_per_pt, count_ranges)
                rec['validator_errors'] = errors[:5]
                rec['valid'] = not errors
                hashes[seed] = rec['plan_sha256'] = plan_hash(slotting, timeline)
                rec['repaired_trials'] = len(stats.get('repaired_trials', []))
                if len(timelines) < 30:
                    timelines.append(timeline)
                rec['targets_per_trial'] = statistics.fmean(c['targets'] for c in trial_calls[-2 * trials_per_block:])
            except PlacementFailure as exc:
                rec['seconds'] = time.perf_counter() - started
                rec['ok'] = rec['valid'] = False
                rec['failure_stage'] = diagnostics.get('stage')
                rec['failure'] = str(exc)[:160]
                failing = [c for c in trial_calls if not c['ok']]
                rec['failing_trial_loads'] = failing[-3:]
            rec['timeline_attempts'] = diagnostics.get('timeline_attempts')
            rec['placement_orders'] = diagnostics.get('placement_stats', {}).get('placement_attempts')
            rec['trial_placements'] = len(trial_calls)
            rec['trial_calls'] = [dict(c) for c in trial_calls]
            records.append(rec)
        repro_checked = repro_mismatch = 0
        for seed in [s for s in seeds if s in hashes][:repro]:
            _, slotting, timeline, _, _ = build_plan(seed, ['animate', 'inanimate'], count_ranges)
            repro_checked += 1
            repro_mismatch += plan_hash(slotting, timeline) != hashes[seed]
    finally:
        timeline_key._construct_trial_schedule = placer

    ok = [r for r in records if r['ok']]
    calls = [c for r in records for c in r['trial_calls']]
    by_load = defaultdict(lambda: [0, 0])
    for c in calls:
        bucket = f"{min(c['load'], 1.2) // 0.05 * 0.05:.2f}"
        by_load[bucket][0] += 1
        by_load[bucket][1] += not c['ok']
    binding_fail = Counter(c['binding'] for c in calls if not c['ok'])
    for r in records:
        r.pop('trial_calls')
    return {
        'trials_per_block': trials_per_block, 'total_trials': 2 * trials_per_block,
        'trials_per_pt': trials_per_pt, 'placer': placer_name,
        'seeds': [seeds[0], seeds[-1]], 'n': len(seeds),
        'successes': len(ok), 'success_rate': len(ok) / len(seeds),
        'valid_successes': sum(r['valid'] for r in ok),
        'first_attempt_successes': sum(r['timeline_attempts'] == 1 for r in ok),
        'failure_stages': dict(Counter(r.get('failure_stage') for r in records if not r['ok'])),
        'seconds_per_plan_success': dist([r['seconds'] for r in ok]),
        'seconds_per_plan_all': dist([r['seconds'] for r in records]),
        'placement_orders_per_plan': dist([r['placement_orders'] for r in records]),
        'trial_placements_per_plan': dist([r['trial_placements'] for r in records]),
        'trial_placement_calls': len(calls),
        'trial_placement_failures': sum(not c['ok'] for c in calls),
        'orders_per_successful_trial': dist([c['orders'] for c in calls if c['ok']]),
        'trial_failure_by_load_bucket': {k: {'trials': v[0], 'failed': v[1]}
                                         for k, v in sorted(by_load.items())},
        'binding_bound_of_failed_trials': dict(binding_fail),
        'targets_per_trial_in_successful_plans': dist([r['targets_per_trial'] for r in ok]),
        'reproducibility': {'checked': repro_checked, 'mismatches': repro_mismatch},
        'timing_profile': timing_profile(timelines),
        'records': records,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--lengths', default='8,20,40,60,80,100', help='total trials, comma separated')
    parser.add_argument('--seeds', type=int, default=100)
    parser.add_argument('--start-seed', type=int, default=1)
    parser.add_argument('--placer', default='current',
                        help="'current' = timeline_key as checked out; else a placement_experiments name")
    parser.add_argument('--repro', type=int, default=10, help='successful seeds to rebuild and compare')
    parser.add_argument('--set', action='append', default=[], metavar='NAME=VALUE')
    parser.add_argument('--ranges', default=None, help='JSON count ranges, e.g. {"PT": [3, 4]}')
    parser.add_argument('--json', type=Path)
    args = parser.parse_args()
    apply_overrides(args.set)
    ranges = {k: tuple(v) for k, v in json.loads(args.ranges).items()} if args.ranges else None
    seeds = list(range(args.start_seed, args.start_seed + args.seeds))
    results = []
    print('| total trials | placer | success | valid | 1st attempt | s/plan median (max) | orders/plan median | failed trials / placements |')
    print('|---|---|---|---|---|---|---|---|')
    for total in map(int, args.lengths.split(',')):
        if total % 2:
            raise SystemExit(f'{total} trials cannot split into two equal blocks.')
        res = run_length(total // 2, seeds, args.placer, args.repro, ranges)
        res['overrides'] = args.set
        res['count_ranges'] = ranges
        results.append(res)
        sp = res['seconds_per_plan_all']
        print(f"| {total} | {args.placer} | {res['successes']}/{res['n']} | {res['valid_successes']} | "
              f"{res['first_attempt_successes']} | {sp['median']:.2f} ({max(r['seconds'] for r in res['records']):.2f}) | "
              f"{res['placement_orders_per_plan']['median']:.0f} | "
              f"{res['trial_placement_failures']}/{res['trial_placement_calls']} |", flush=True)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({'overrides': args.set, 'results': results}, indent=1) + '\n')


if __name__ == '__main__':
    main()
