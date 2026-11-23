"""Compare per-trial placers on the same hard trials drawn from real 100-trial plans.

Trials come from build_plan for seeds START..START+N-1 at 50 trials per block,
captured just before placement, so event sets (counts, corners, items, SOAs)
are exactly what production would have to place. Each placer gets the same
per-trial RNG seed. 'reference' is today's sampler with a 20,000-order budget:
the distribution a perfect-but-slow version of today's method would produce.

    python3 tools/trial_corpus_bench.py --plans 100 --min-load 0.85 --json benchmarks/corpus.json
"""

import argparse
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]

from scheduler_bench import apply_overrides, dist, timing_profile, trial_load  # noqa: E402

if __name__ == '__main__':  # --set must reach config before timeline_key binds its values
    apply_overrides([sys.argv[i + 1] for i, a in enumerate(sys.argv[:-1]) if a == '--set'])

import stimulus_split  # noqa: E402
import timeline_key as tk  # noqa: E402
import placement_experiments as px  # noqa: E402
from participant_setup import build_plan  # noqa: E402


def capture(plans, start, trials_per_pt, count_ranges=None):
    trials = []
    real, real_check = tk._construct_trial_schedule, tk._infeasibility
    stimulus_split.TRIALS_PER_PT = trials_per_pt
    tk._infeasibility = lambda events: ''  # capture every trial, including ones it would reject
    for seed in range(start, start + plans):
        n0 = len(trials)
        tk._construct_trial_schedule = lambda e, s, st, **_: (trials.append((e, s)), [])[1]
        try:
            build_plan(seed, ['animate', 'inanimate'], count_ranges)
        except Exception:
            pass  # the empty schedules fail validation; only the captured events matter
        for i in range(n0, len(trials)):
            trials[i] = (seed,) + trials[i]
    tk._construct_trial_schedule, tk._infeasibility = real, real_check
    return trials


SEARCHES = {
    'baseline_750': (px.random_orders, px.BUDGET),
    'reference_20000': (px.random_orders, 20_000),
    'repair': (px.repair, px.BUDGET),
    'critical_first': (px.critical_first, px.BUDGET),
    'hybrid': (px.hybrid, px.BUDGET),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--plans', type=int, default=100)
    parser.add_argument('--start-seed', type=int, default=1)
    parser.add_argument('--trials-per-pt', type=int, default=25)
    parser.add_argument('--min-load', type=float, default=0.85)
    parser.add_argument('--placers', default=','.join(SEARCHES))
    parser.add_argument('--set', action='append', default=[])
    parser.add_argument('--ranges', default=None)
    parser.add_argument('--json', type=Path)
    args = parser.parse_args()
    ranges = {k: tuple(v) for k, v in json.loads(args.ranges).items()} if args.ranges else None
    corpus = capture(args.plans, args.start_seed, args.trials_per_pt, ranges)
    loads = [trial_load(events) for _, events, _ in corpus]
    rejected = [bool(tk._infeasibility(events)) for _, events, _ in corpus]
    infeasible = sum(l['load'] > 1 + 1e-9 for l in loads)
    rejected_plans = len({seed for (seed, _, _), r in zip(corpus, rejected) if r})
    hard = [(c, l) for c, l in zip(corpus, loads) if args.min_load <= l['load'] <= 1 + 1e-9]
    targets = sum(l['targets'] for l in loads) / len(loads)
    print(f'{len(corpus)} trials; {infeasible} provably infeasible; {sum(rejected)} rejected by lower bound '
          f'(incl. zero slack); plans with a rejected trial: {rejected_plans}/{args.plans}; '
          f'targets/trial {targets:.2f}; target prevalence {targets / (sum(l["visuals"] for l in loads) / len(loads)):.1%}; '
          f'{len(hard)} feasible with load >= {args.min_load}')
    if not args.placers:
        return
    results = {}
    print('| placer | solved | seconds total | s/trial max | orders/trial mean |')
    print('|---|---|---|---|---|')
    for name in args.placers.split(','):
        search, budget = SEARCHES[name]
        solved, times, orders, placed = [], [], [], []
        for (seed, events, start), load in hard:
            stats = {'rng': random.Random(f'{seed}:{events[0]["block"]}:{events[0]["trial"]}:corpus'),
                     'placement_attempts': 0}
            t0 = time.perf_counter()
            result = search(events, start, stats, budget)
            times.append(time.perf_counter() - t0)
            orders.append(stats['placement_attempts'])
            solved.append(result is not None)
            if result is not None:
                placed.append([dict(r, global_onset=r['global_onset']) for r in result])
        by_bucket = {}
        for ok, (_, load) in zip(solved, hard):
            b = f"{int(load['load'] * 20) / 20:.2f}"
            by_bucket.setdefault(b, [0, 0])
            by_bucket[b][0] += 1
            by_bucket[b][1] += ok
        results[name] = {
            'solved': sum(solved), 'of': len(hard), 'solved_mask': solved,
            'seconds': dist(times), 'seconds_total': sum(times), 'orders': dist(orders),
            'solved_by_load_bucket': by_bucket, 'timing_profile': timing_profile([sum(placed, [])]),
        }
        print(f"| {name} | {sum(solved)}/{len(hard)} | {sum(times):.1f} | {max(times):.2f} | "
              f"{sum(orders) / len(orders):.1f} |", flush=True)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({'args': vars(args) | {'json': str(args.json)},
                                         'trials': len(corpus), 'provably_infeasible': infeasible,
                                         'hard_feasible': len(hard), 'results': results},
                                        indent=1, default=str) + '\n')


if __name__ == '__main__':
    main()
