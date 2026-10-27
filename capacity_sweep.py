"""Feasibility sweep: can the timeline generator place harder trials?

Each scenario overrides a few config constants and then runs the real
generation path (participant_setup.build_plan -> timeline_key.build_timeline ->
validate_timeline) inside a separate interpreter, because timeline_key binds
config values at import time. Nothing is written outside the scratch directory.

The number that matters is `generation_success_5_attempts`: create_participant_plan
draws a new seed and retries after a PlacementFailure, up to 5 times, so a
per-seed rate p still produces a participant plan with probability 1-(1-p)^5.

Usage:
    python capacity_sweep.py --n 100
    python capacity_sweep.py --n 100 --scenario baseline window_0.3s
    python capacity_sweep.py --n 100 --list
    python capacity_sweep.py --n 100 --json-report sweep.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import config

MAX_WORKERS = 4

# Bootstrap runs in a fresh interpreter: patch config first (timeline_key,
# slotting_key and stimulus_split read these at import time), re-derive the
# dependent constants, then run the sweep and write the summary JSON.
BOOTSTRAP = r'''
import json, sys
import config

patch = json.loads(sys.argv[1])
for name, value in patch.items():
    setattr(config, name, tuple(value) if isinstance(value, list) else value)
config.VISUAL_DURATION = config.FADE_IN_DUR + config.PEAK_HOLD_DUR + config.FADE_OUT_DUR
config.TRIAL_DURATION = 2 * config.TRIAL_BUFFER_DUR + config.TRIAL_CONTENT_DUR
config.TARGET_CORNER_HOLD = config.RESPONSE_WINDOW + config.LATE_WINDOW

from monte_carlo import run_monte_carlo

summary = run_monte_carlo(int(sys.argv[2]), start_seed=int(sys.argv[3]))
with open(sys.argv[4], 'w', encoding='utf-8') as output:
    json.dump(summary, output)
'''

# Every scenario states the whole relevant config so a row can be read on its own.
BASE = {
    'FADE_IN_DUR': config.FADE_IN_DUR,
    'FADE_OUT_DUR': config.FADE_OUT_DUR,
    'IMAGE_SIZE': list(config.IMAGE_SIZE),
    'TRIAL_CONTENT_DUR': config.TRIAL_CONTENT_DUR,
    'TRIAL_PT_RANGE': list(config.TRIAL_PT_RANGE),
    'TRIAL_NPT_RANGE': list(config.TRIAL_NPT_RANGE),
    'TRIAL_PD_RANGE': list(config.TRIAL_PD_RANGE),
    'TRIAL_NPD_RANGE': list(config.TRIAL_NPD_RANGE),
    'TRIALS_PER_PT': config.TRIALS_PER_PT,
}

# The exposure levers the professor proposed: 0.15 s fade in and out, 100 px images.
HARDER = {'FADE_IN_DUR': 0.15, 'FADE_OUT_DUR': 0.15, 'IMAGE_SIZE': [100, 100]}
# 45 minutes needs this many trials per PT once the content window is 30 s
# (see session_timing.py: 34 trials per block, 2 PTs per block).
FORTY_FIVE_MINUTE_TRIALS_PER_PT = 17


def scenario(name, why, **overrides):
    return {'name': name, 'why': why, 'patch': {**BASE, **overrides}}


SCENARIOS = {
    item['name']: item
    for item in (
        scenario(
            'baseline', 'control: the pilot configuration',
        ),
        scenario(
            'window_0.3s', 'prof idea 1 alone: 0.3 s exposure instead of 0.6 s',
            FADE_IN_DUR=0.15, FADE_OUT_DUR=0.15,
        ),
        scenario(
            'size_100px', 'prof idea 2 alone: 100 px images instead of 150 px',
            IMAGE_SIZE=[100, 100],
        ),
        scenario(
            'window_0.3s_size_100px', 'both exposure levers, current target counts',
            FADE_IN_DUR=0.15, FADE_OUT_DUR=0.15, IMAGE_SIZE=[100, 100],
        ),
        scenario(
            'targets_11_13', 'exposure levers + 11-13 targets per trial',
            **HARDER, TRIAL_PT_RANGE=[2, 3], TRIAL_NPT_RANGE=[9, 10],
        ),
        scenario(
            'targets_12_14', 'exposure levers + 12-14 targets per trial',
            **HARDER, TRIAL_PT_RANGE=[3, 4], TRIAL_NPT_RANGE=[9, 10],
        ),
        scenario(
            'targets_14_16', 'exposure levers + 14-16 targets per trial',
            **HARDER, TRIAL_PT_RANGE=[3, 4], TRIAL_NPT_RANGE=[11, 12],
        ),
        scenario(
            'targets_16_18', 'probe: where placement stops being reliable',
            **HARDER, TRIAL_PT_RANGE=[4, 4], TRIAL_NPT_RANGE=[12, 14],
        ),
        scenario(
            'content_30s_targets_12_14', 'longer content window + 12-14 targets',
            **HARDER, TRIAL_CONTENT_DUR=30.0,
            TRIAL_PT_RANGE=[3, 4], TRIAL_NPT_RANGE=[9, 10],
        ),
        scenario(
            'content_30s_targets_14_16', 'longer content window + 14-16 targets',
            **HARDER, TRIAL_CONTENT_DUR=30.0,
            TRIAL_PT_RANGE=[3, 4], TRIAL_NPT_RANGE=[11, 12],
        ),
        scenario(
            'content_30s_targets_16_18', 'longer content window + 16-18 targets',
            **HARDER, TRIAL_CONTENT_DUR=30.0,
            TRIAL_PT_RANGE=[4, 4], TRIAL_NPT_RANGE=[12, 14],
        ),
        scenario(
            'content_30s_targets_18_20', 'longer content window + 18-20 targets',
            **HARDER, TRIAL_CONTENT_DUR=30.0,
            TRIAL_PT_RANGE=[4, 5], TRIAL_NPT_RANGE=[14, 15],
        ),
        scenario(
            'content_30s_targets_12_14_dense',
            'prevalence-matched: 12-14 targets with the distractor count scaled to '
            'hold target prevalence near the pilot 22%',
            **HARDER, TRIAL_CONTENT_DUR=30.0,
            TRIAL_PT_RANGE=[3, 4], TRIAL_NPT_RANGE=[9, 10], TRIAL_NPD_RANGE=[38, 45],
        ),
        # 20 s content window with the distractor count left at today's (20, 28):
        # how the target total and the PT/NPT split each drive placement.
        scenario(
            'w20_pt3_5_npt9_10',
            '20 s window, PT max 5, 12-15 targets (same NPT as the 12-14 control)',
            **HARDER, TRIAL_PT_RANGE=[3, 5], TRIAL_NPT_RANGE=[9, 10],
        ),
        scenario(
            'w20_pt3_6_npt9_10',
            '20 s window, PT max 6, 12-16 targets',
            **HARDER, TRIAL_PT_RANGE=[3, 6], TRIAL_NPT_RANGE=[9, 10],
        ),
        scenario(
            'w20_pt3_5_npt7_8',
            '20 s window, PT max 5 but only 10-13 targets: isolates PT count from target load',
            **HARDER, TRIAL_PT_RANGE=[3, 5], TRIAL_NPT_RANGE=[7, 8],
        ),
        scenario(
            'w20_pt4_5_npt7_8',
            '20 s window, PT 4-5 repeats, 11-13 targets',
            **HARDER, TRIAL_PT_RANGE=[4, 5], TRIAL_NPT_RANGE=[7, 8],
        ),
        # 20 s window, targets pinned at 11-14 (PT 3-5, NPT 8-9), distractors
        # pushed up to find where the prevalence the study wants stops placing.
        scenario(
            'w20_npd28_34',
            '11-14 targets with more distractors: NPD 28-34, prevalence ~27%',
            **HARDER, TRIAL_NPD_RANGE=[28, 34],
            TRIAL_PT_RANGE=[3, 5], TRIAL_NPT_RANGE=[8, 9],
        ),
        scenario(
            'w20_npd34_40',
            '11-14 targets: NPD 34-40, prevalence ~24%',
            **HARDER, TRIAL_NPD_RANGE=[34, 40],
            TRIAL_PT_RANGE=[3, 5], TRIAL_NPT_RANGE=[8, 9],
        ),
        scenario(
            'w20_npd40_46',
            '11-14 targets: NPD 40-46, prevalence ~22% (matches the pilot)',
            **HARDER, TRIAL_NPD_RANGE=[40, 46],
            TRIAL_PT_RANGE=[3, 5], TRIAL_NPT_RANGE=[8, 9],
        ),
        scenario(
            'w20_pd5_7_npd34_40',
            '11-14 targets with PD raised to 5-7: 23% prevalence but 10 sounds/trial',
            **HARDER, TRIAL_PD_RANGE=[5, 7], TRIAL_NPD_RANGE=[34, 40],
            TRIAL_PT_RANGE=[3, 5], TRIAL_NPT_RANGE=[8, 9],
        ),
        scenario(
            'w20_12_14_full',
            'the professor-asked range at full length: 12-14 targets, 100 trials, NPD 20-28',
            **HARDER, TRIAL_PT_RANGE=[3, 4], TRIAL_NPT_RANGE=[9, 10],
            TRIALS_PER_PT=25,
        ),
        scenario(
            'w20_pt4_5_npt8_9_full',
            '12-14 targets with PT 4-5, 100 trials, NPD 20-28',
            **HARDER, TRIAL_PT_RANGE=[4, 5], TRIAL_NPT_RANGE=[8, 9],
            TRIALS_PER_PT=25,
        ),
        scenario(
            'w20_12_14_low_npd_full',
            '12-14 targets with NPD lowered to 14-20 to buy placement room, 100 trials',
            **HARDER, TRIAL_PT_RANGE=[3, 4], TRIAL_NPT_RANGE=[9, 10], TRIAL_NPD_RANGE=[14, 20],
            TRIALS_PER_PT=25,
        ),
        scenario(
            'w20_11_13_full',
            '20 s option B with fewer targets: 11-13 targets, 100 trials, NPD 20-28',
            **HARDER, TRIAL_PT_RANGE=[2, 3], TRIAL_NPT_RANGE=[9, 10],
            TRIALS_PER_PT=25,
        ),
        scenario(
            'w20_more_npd_22_30_full',
            'halfway to the failing NPD: 11-13 targets with NPD 22-30, 100 trials',
            **HARDER, TRIAL_PT_RANGE=[2, 3], TRIAL_NPT_RANGE=[9, 10], TRIAL_NPD_RANGE=[22, 30],
            TRIALS_PER_PT=25,
        ),
        scenario(
            'w20_more_npd_24_32_full',
            'the recommendation with more distractors: 11-13 targets, NPD 24-32, 100 trials',
            **HARDER, TRIAL_PT_RANGE=[2, 3], TRIAL_NPT_RANGE=[9, 10], TRIAL_NPD_RANGE=[24, 32],
            TRIALS_PER_PT=25,
        ),
        scenario(
            'w20_more_npd_28_34_full',
            'the recommendation with NPD 28-34 (prevalence down to ~26%), 100 trials',
            **HARDER, TRIAL_PT_RANGE=[2, 3], TRIAL_NPT_RANGE=[9, 10], TRIAL_NPD_RANGE=[28, 34],
            TRIALS_PER_PT=25,
        ),
        scenario(
            'w20_more_pd_5_7_full',
            'the recommendation with PD raised to 5-7 (more sound events), 11-13 targets, 100 trials',
            **HARDER, TRIAL_PT_RANGE=[2, 3], TRIAL_NPT_RANGE=[9, 10], TRIAL_PD_RANGE=[5, 7],
            TRIALS_PER_PT=25,
        ),
        scenario(
            'w20_pt_heavy_11_13_full',
            '11-13 targets but PT-heavy: PT 4-5 with NPT 7-8, 100 trials, NPD 20-28',
            **HARDER, TRIAL_PT_RANGE=[4, 5], TRIAL_NPT_RANGE=[7, 8], TRIALS_PER_PT=25,
        ),
        scenario(
            'w20_10_13_full',
            '20 s option B with PT 5: 10-13 targets, 100 trials, NPD 20-28',
            **HARDER, TRIAL_PT_RANGE=[3, 5], TRIAL_NPT_RANGE=[7, 8],
            TRIALS_PER_PT=25,
        ),
        scenario(
            'w20_pt3_5_npt8_9_full',
            'the whole 20 s option B plan: 11-14 targets, 100 trials, NPD 20-28',
            **HARDER, TRIAL_PT_RANGE=[3, 5], TRIAL_NPT_RANGE=[8, 9],
            TRIALS_PER_PT=25,
        ),
        scenario(
            'w20_pt3_5_npt8_9',
            '20 s window, PT max 5, 11-14 targets: the floor stays at the requested 11',
            **HARDER, TRIAL_PT_RANGE=[3, 5], TRIAL_NPT_RANGE=[8, 9],
        ),
        scenario(
            'w20_pt4_5_npt8_9',
            '20 s window, PT 4-5 repeats, 12-14 targets: matches the (3,4) target total',
            **HARDER, TRIAL_PT_RANGE=[4, 5], TRIAL_NPT_RANGE=[8, 9],
        ),
        scenario(
            'pt_3_5_content_30s',
            'wider PT range in the 30 s window: 3-5 PT repeats + 9-10 NPT = 12-15 targets',
            **HARDER, TRIAL_CONTENT_DUR=30.0,
            TRIAL_PT_RANGE=[3, 5], TRIAL_NPT_RANGE=[9, 10], TRIAL_NPD_RANGE=[38, 45],
        ),
        scenario(
            'pt_3_5_content_20s',
            'the same 12-15 targets in the current 20 s window',
            **HARDER,
            TRIAL_PT_RANGE=[3, 5], TRIAL_NPT_RANGE=[9, 10], TRIAL_NPD_RANGE=[38, 45],
        ),
        scenario(
            'pt_3_6_content_30s',
            'probe: 3-6 PT repeats + 9-10 NPT = 12-16 targets in the 30 s window',
            **HARDER, TRIAL_CONTENT_DUR=30.0,
            TRIAL_PT_RANGE=[3, 6], TRIAL_NPT_RANGE=[9, 10], TRIAL_NPD_RANGE=[38, 45],
        ),
        scenario(
            'a30_pt3_5_full',
            'option A with PT widened to 3-5, at the real 68-trial length',
            **HARDER, TRIAL_CONTENT_DUR=30.0,
            TRIAL_PT_RANGE=[3, 5], TRIAL_NPT_RANGE=[9, 10], TRIAL_NPD_RANGE=[38, 45],
            TRIALS_PER_PT=FORTY_FIVE_MINUTE_TRIALS_PER_PT,
        ),
        scenario(
            'a30_pt3_6_full',
            'option A with PT widened to 3-6, at the real 68-trial length',
            **HARDER, TRIAL_CONTENT_DUR=30.0,
            TRIAL_PT_RANGE=[3, 6], TRIAL_NPT_RANGE=[9, 10], TRIAL_NPD_RANGE=[38, 45],
            TRIALS_PER_PT=FORTY_FIVE_MINUTE_TRIALS_PER_PT,
        ),
        scenario(
            'pilot_45min_recommended',
            'the recommended plan: exposure levers, 30 s content, 12-14 targets, '
            'prevalence-matched distractors, 68 trials',
            **HARDER, TRIAL_CONTENT_DUR=30.0,
            TRIAL_PT_RANGE=[3, 4], TRIAL_NPT_RANGE=[9, 10], TRIAL_NPD_RANGE=[38, 45],
            TRIALS_PER_PT=FORTY_FIVE_MINUTE_TRIALS_PER_PT,
        ),
        scenario(
            'pilot_45min_candidate',
            'the whole proposed 45-minute plan: exposure levers, 30 s content, '
            '12-14 targets, 68 trials',
            **HARDER, TRIAL_CONTENT_DUR=30.0,
            TRIAL_PT_RANGE=[3, 4], TRIAL_NPT_RANGE=[9, 10],
            TRIALS_PER_PT=FORTY_FIVE_MINUTE_TRIALS_PER_PT,
        ),
    )
}


def _target_counts(patch):
    pt, npt = patch['TRIAL_PT_RANGE'], patch['TRIAL_NPT_RANGE']
    return pt[0] + npt[0], pt[1] + npt[1]


def _visual_duration(patch):
    return patch['FADE_IN_DUR'] + patch['FADE_OUT_DUR']


def npd_for_prevalence(targets, prevalence, pd_distractors):
    """NPD count per trial that puts target prevalence at `prevalence`.

    Prevalence is targets / (targets + PD + NPD), so holding it fixed while the
    target count rises forces NPD up by a multiple of the targets, not by the
    same amount. This is the arithmetic behind the splitting problem: at 22%
    prevalence every extra target needs ~3.5 extra NPD, and NPD is therefore
    always the largest role by count.
    """
    if not 0 < prevalence < 1:
        raise ValueError('prevalence must be between 0 and 1 exclusive.')
    if targets < 0 or pd_distractors < 0:
        raise ValueError('targets and pd_distractors must be nonnegative.')
    return targets * (1 - prevalence) / prevalence - pd_distractors


def _mean(bounds):
    return (bounds[0] + bounds[1]) / 2


def _target_prevalence(patch):
    """Share of presented images that are targets, over the configured ranges.

    Raising the target count without raising the distractor count also raises
    prevalence, which on its own tends to reduce misses (Wolfe et al. 2007), so
    this number has to be held roughly constant or reported as a manipulation.
    """
    targets = _mean(patch['TRIAL_PT_RANGE']) + _mean(patch['TRIAL_NPT_RANGE'])
    distractors = _mean(patch['TRIAL_PD_RANGE']) + _mean(patch['TRIAL_NPD_RANGE'])
    return targets / (targets + distractors)


def run_scenario(item, seeds, start_seed, scratch: Path) -> dict:
    """Run one scenario in its own interpreter and reduce its summary."""
    output = scratch / f"{item['name']}.json"
    started = time.monotonic()
    completed = subprocess.run(
        [sys.executable, '-c', BOOTSTRAP, json.dumps(item['patch']),
         str(seeds), str(start_seed), str(output)],
        cwd=Path(__file__).resolve().parent,
        capture_output=True, text=True, timeout=3600,
    )
    elapsed = time.monotonic() - started
    if completed.returncode != 0 or not output.is_file():
        return {
            'name': item['name'], 'why': item['why'], 'patch': item['patch'],
            'status': 'scenario_error', 'elapsed_seconds': elapsed,
            'stderr': completed.stderr[-2000:], 'stdout': completed.stdout[-2000:],
        }
    summary = json.loads(output.read_text(encoding='utf-8'))
    success = summary['successful_timelines'] / seeds if seeds else 0.0
    low, high = _target_counts(item['patch'])
    gaps = summary['variability_analysis']['target_end_to_onset_gaps']
    visual_gaps = summary['variability_analysis']['visual_gaps']
    onsets = [
        summary['variability_analysis']['visual_onset_by_position'][str(position)]['trial_onset']
        for position in range(1, high + 1)
        if str(position) in summary['variability_analysis']['visual_onset_by_position']
    ]
    return {
        'name': item['name'],
        'why': item['why'],
        'status': 'ok',
        'patch': item['patch'],
        'targets_per_trial': [low, high],
        'target_prevalence': _target_prevalence(item['patch']),
        'visual_seconds': _visual_duration(item['patch']),
        'image_px': item['patch']['IMAGE_SIZE'][0],
        'content_seconds': item['patch']['TRIAL_CONTENT_DUR'],
        'seeds': seeds,
        'successful_timelines': summary['successful_timelines'],
        'success_rate': success,
        'generation_success_5_attempts': 1 - (1 - success) ** 5,
        'first_attempt_success_rate': summary['first_attempt_success_rate'],
        'failure_counts_by_reason': summary['failure_counts_by_reason'],
        'trials_observed': summary['trials_observed'],
        'trials_per_plan': (
            summary['trials_observed'] // seeds if seeds else None
        ),
        'maximum_visual_events_observed': summary['maximum_visual_events_observed'],
        'placement_attempts_per_timeline': (
            summary['variability_analysis']['placement_behavior']
            ['placement_attempts_per_successful_timeline']['mean']
        ),
        'target_minimum_gap_share': (
            gaps['at_minimum_count'] / gaps['count'] if gaps['count'] else None
        ),
        'target_gap_mean_seconds': gaps['mean'],
        'target_gap_min_seconds': gaps['minimum'],
        'visual_gap_mean_seconds': visual_gaps['mean'],
        'last_visual_onset_mean_seconds': (
            onsets[-1]['mean'] if onsets else None
        ),
        'elapsed_seconds': elapsed,
    }


def sweep(names, seeds, start_seed, workers=MAX_WORKERS) -> list[dict]:
    items = [SCENARIOS[name] for name in names]
    with tempfile.TemporaryDirectory(prefix='capacity-sweep-') as scratch:
        scratch = Path(scratch)
        with ThreadPoolExecutor(max_workers=min(workers, len(items))) as pool:
            results = list(pool.map(
                lambda item: run_scenario(item, seeds, start_seed, scratch), items,
            ))
    return results


def _number(value, format_spec='.2f', absent='  n/a'):
    return absent if value is None else format(value, format_spec)


def _format_row(result):
    if result['status'] != 'ok':
        return f"{result['name']:26s} SCENARIO ERROR: {result['stderr'].strip().splitlines()[-1:]}"
    low, high = result['targets_per_trial']
    return (
        f"{result['name']:26s} {result['visual_seconds']:.2f}s "
        f"{result['image_px']:>3d}px targets {low:2d}-{high:2d} "
        f"content {result['content_seconds']:>2.0f}s "
        f"trials {result['trials_per_plan'] or 0:2d} "
        f"prev {100 * result['target_prevalence']:.0f}% | "
        f"fail {100 * (1 - result['success_rate']):5.1f}% "
        f"first-try {100 * result['first_attempt_success_rate']:5.1f}% "
        f"5-attempt {100 * result['generation_success_5_attempts']:5.1f}% "
        f"attempts/plan {_number(result['placement_attempts_per_timeline'], '6.1f', '   n/a')} "
        f"| visuals {result['maximum_visual_events_observed']:3d} "
        f"target gap min {_number(result['target_gap_min_seconds'])}s "
        f"mean {_number(result['target_gap_mean_seconds'])}s "
        f"last onset {_number(result['last_visual_onset_mean_seconds'], '.1f', 'n/a')}s "
        f"| {result['elapsed_seconds']:.0f}s"
    )


def _print_report(results, seeds):
    print('TASK-DIFFICULTY FEASIBILITY SWEEP')
    print('=' * 118)
    print(f'{seeds} seeds per scenario; success = a whole participant plan was generated and validated.')
    print('5-attempt = chance the runner produces a plan within its 5-seed retry budget.')
    print()
    for result in results:
        print(_format_row(result))
    print()
    print('Failure reasons:')
    for result in results:
        if result['status'] != 'ok':
            continue
        reasons = result['failure_counts_by_reason'] or {'none': 0}
        print(f"  {result['name']:26s} {reasons}")
    usable = [
        result for result in results
        if result['status'] == 'ok' and result['generation_success_5_attempts'] >= 0.999
    ]
    print()
    print('Scenarios a pilot could run (>= 99.9% plan generation within 5 seeds):')
    for result in usable:
        low, high = result['targets_per_trial']
        print(f"  {result['name']:26s} targets {low}-{high}, "
              f"{result['trials_per_plan']} trials, "
              f"first-try {100 * result['first_attempt_success_rate']:.1f}%, "
              f"{result['placement_attempts_per_timeline']:.0f} placement orders/plan")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--n', type=int, default=100, help='seeds per scenario (default: 100)')
    parser.add_argument('--start-seed', type=int, default=1)
    parser.add_argument('--scenario', nargs='+', choices=sorted(SCENARIOS),
                        help='scenarios to run (default: all)')
    parser.add_argument('--workers', type=int, default=MAX_WORKERS)
    parser.add_argument('--list', action='store_true', help='list scenarios and exit')
    parser.add_argument('--json-report', type=Path)
    args = parser.parse_args()

    if args.list:
        for name, item in SCENARIOS.items():
            low, high = _target_counts(item['patch'])
            print(f'{name:26s} targets {low}-{high}, '
                  f'{_visual_duration(item["patch"]):.2f}s visual, '
                  f'{item["patch"]["IMAGE_SIZE"][0]}px, '
                  f'{100 * _target_prevalence(item["patch"]):.0f}% prevalence  | {item["why"]}')
        return

    names = args.scenario or list(SCENARIOS)
    results = sweep(names, args.n, args.start_seed, args.workers)
    _print_report(results, args.n)
    if args.json_report:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(
            json.dumps({'seeds': args.n, 'start_seed': args.start_seed, 'results': results},
                       indent=2) + '\n',
            encoding='utf-8',
        )
        print(f'\nJSON report: {args.json_report}')


if __name__ == '__main__':
    main()
