"""Does a placer change the timing distribution? Compare it with today's sampler.

The reference is today's random-order sampler with a large budget: what the
current method would produce if it never gave up. Every placer gets the same
per-trial RNG seed, and metrics are computed on trials every placer solved.

    python3 tools/bias_check.py --json benchmarks/bias.json
"""

import argparse
import bisect
import json
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]

import config as c  # noqa: E402
import placement_experiments as px  # noqa: E402
from scheduler_bench import trial_load  # noqa: E402
from trial_corpus_bench import capture  # noqa: E402


def ks(a, b):
    """Two-sample Kolmogorov-Smirnov distance."""
    a, b = sorted(a), sorted(b)
    return max(abs(bisect.bisect_right(a, x) / len(a) - bisect.bisect_right(b, x) / len(b))
               for x in a + b) if a and b else None


def features(rows):
    vis = sorted((r for r in rows if r['event_type'] == 'visual'), key=lambda r: r['global_onset'])
    f = defaultdict(list)
    for i, r in enumerate(vis):
        f[f"onset_{r['role']}"].append(r['trial_onset'] - c.TRIAL_BUFFER_DUR)
        if r['role'] in c.TARGET_ROLES:
            f['target_rank'].append(i / (len(vis) - 1))
            if r['corner'] == c.FAVORED_CORNER:
                f['favored_target_onset'].append(r['trial_onset'] - c.TRIAL_BUFFER_DUR)
    gaps = [b['global_onset'] - a['global_onset'] for a, b in zip(vis, vis[1:])]
    f['gap'] = gaps
    f['gap_at_minimum'] = [g < c.MIN_VISUAL_ONSET_GAP + 1e-3 for g in gaps]
    f['span'] = [vis[-1]['global_onset'] + c.VISUAL_DURATION - vis[0]['global_onset']]
    return f


SEARCHES = {
    'critical_first': px.critical_first, 'repair': px.repair,
    'hybrid': px.hybrid, 'hybrid_critical': px.hybrid_critical,
}


def compare(trials, names, reference_budget):
    samples = {name: [] for name in ['reference'] + names}
    for seed, events, start in trials:
        key = f"{seed}:{events[0]['block']}:{events[0]['trial']}:bias"
        row = {}
        for name in samples:
            stats = {'rng': random.Random(key), 'placement_attempts': 0}
            if name == 'reference':
                row[name] = px.random_orders(events, start, stats, reference_budget)
            else:
                row[name] = SEARCHES[name](events, start, stats, px.BUDGET)
        for name, result in row.items():
            samples[name].append(result)
    common = [i for i in range(len(trials)) if all(samples[n][i] is not None for n in samples)]
    merged = {}
    for name, results in samples.items():
        f = defaultdict(list)
        for i in common:
            for k, v in features(results[i]).items():
                f[k].extend(v)
        merged[name] = f
    ref = merged['reference']
    out = {'trials': len(trials), 'common_solved': len(common),
           'solved': {n: sum(r is not None for r in v) for n, v in samples.items()},
           'identical_to_reference': {n: sum(samples[n][i] == samples['reference'][i] for i in common)
                                      for n in names}}
    for name, f in merged.items():
        out[name] = {
            'gap_at_minimum_pct': round(100 * statistics.fmean(f['gap_at_minimum']), 2),
            'mean_span_s': round(statistics.fmean(f['span']), 3),
            'mean_target_rank': round(statistics.fmean(f['target_rank']), 4),
            'mean_onset': {k[6:]: round(statistics.fmean(v), 3) for k, v in sorted(f.items()) if k.startswith('onset_')},
            'ks_vs_reference': {k: round(ks(v, ref[k]), 4) for k, v in sorted(f.items())
                                if k not in ('gap_at_minimum', 'span')},
        }
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--typical-plans', type=int, default=10)
    parser.add_argument('--hard-plans', type=int, default=40)
    parser.add_argument('--reference-budget', type=int, default=5000)
    parser.add_argument('--placers', default=','.join(SEARCHES))
    parser.add_argument('--json', type=Path)
    args = parser.parse_args()
    names = args.placers.split(',')
    feasible = lambda t: trial_load(t[1])['load'] <= 1 + 1e-9
    typical = [t for t in capture(args.typical_plans, 1, 25) if feasible(t)]
    hard = [t for t in capture(args.hard_plans, 1001, 25)
            if feasible(t) and trial_load(t[1])['load'] >= 0.85]
    report = {'args': {k: str(v) for k, v in vars(args).items()}}
    for label, trials in (('typical', typical), ('hard', hard)):
        report[label] = compare(trials, names, args.reference_budget)
        r = report[label]
        print(f"\n{label}: {r['trials']} trials, {r['common_solved']} solved by all; solved={r['solved']}")
        print('| placer | identical to ref | % gaps at 0.15 s | span s | target rank | max KS (metric) |')
        print('|---|---|---|---|---|---|')
        for name in ['reference'] + names:
            m = r[name]
            worst = max(m['ks_vs_reference'].items(), key=lambda kv: kv[1])
            print(f"| {name} | {r['identical_to_reference'].get(name, '-')} | {m['gap_at_minimum_pct']} | "
                  f"{m['mean_span_s']} | {m['mean_target_rank']} | {worst[1]} ({worst[0]}) |", flush=True)
    if args.json:
        args.json.write_text(json.dumps(report, indent=1) + '\n')


if __name__ == '__main__':
    main()
