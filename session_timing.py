"""Expected session duration model, trial-count solver, and cadence tradeoff.

Pure arithmetic: no PsychoPy, no file writes, no RNG. Every structural number is
read from config.py so the model cannot drift from the runner. Participant-paced
screen times come from MEASURED_SCREEN_SECONDS, whose defaults are medians over
the pilot sessions under data/ (--calibrate recomputes them).

The session shape modelled here is exactly what experiment.py runs:

    finger placement -> numpad check -> sound check -> plan -> instructions
      -> scoring rules -> practice -> [per block: intro screen, then each trial
      followed by a feedback screen, then a break] -> completion screen

Two levers decide how long a session lasts:

  trial length   = 2 x TRIAL_BUFFER_DUR + content, fixed by config today
  trials         = how many of those trials fit in the target duration

Content length is what sets the target cadence (one target every N seconds), so
the cadence table answers "how long is a trial with 12 targets, and how many
trials then fit in 45 minutes?".

Usage:
    python session_timing.py --target-minutes 45
    python session_timing.py --target-minutes 45 --cadence-table
    python session_timing.py --trials-per-block 4 8 16 32 36 50
    python session_timing.py --calibrate /path/to/data
    python session_timing.py --break-every 8 --target-minutes 45
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from datetime import datetime
from pathlib import Path

import config

# --- Pilot calibration -------------------------------------------------------
# Medians over the pilot sessions in data/. These are participant-paced screens
# and are the noisiest part of the model, so every one is a CLI override.
MEASURED_SCREEN_SECONDS = {
    'pre_task_seconds': 65.0,      # window + checks + instructions + scoring rules
    'practice_seconds': 29.0,      # 3 coached steps + held screen + paced round + summary
    'continuation_seconds': 2.0,   # feedback screen between trials, ended with SPACE
    'completion_seconds': 20.0,    # final screen read + SPACE
}
MEASURED_SCREEN_SOURCE = (
    'median of the pilot sessions in data/ '
    '(preflight_report.txt measured_at, session_metadata.json, trial_log.csv)'
)


# --- Structure from config ---------------------------------------------------

def trials_per_block() -> int:
    """Trials in one block: one PT is active per trial and every PT is seen an
    equal number of times, so trials = PT_COUNT_PER_BLOCK x TRIALS_PER_PT."""
    return config.PT_COUNT_PER_BLOCK * config.TRIALS_PER_PT


def block_count() -> int:
    """One block per stimulus category (animate, inanimate)."""
    return len(config.BLOCK_LABELS)


def trial_seconds(content_seconds: float | None = None) -> float:
    """Scheduled trial duration: start buffer + content + end buffer."""
    if content_seconds is None:
        return config.TRIAL_DURATION
    return 2 * config.TRIAL_BUFFER_DUR + content_seconds


def break_count(trials: int, blocks: int, break_every_trials: int | None = None) -> int:
    """Breaks in a session.

    Default: one between blocks, which is all experiment.py offers today. With
    break_every_trials set (a proposed change: a break inside the trial loop)
    the count is one break per block of trials, less any break that would land
    after the final trial."""
    if break_every_trials is None:
        return blocks - 1
    return sum(
        1 for index in range(1, int(trials)) if index % break_every_trials == 0
    )


def continuation_screens(trials: int, blocks: int) -> int:
    """Feedback screens: one after every trial, plus one before every block."""
    return trials + blocks


def duration_breakdown(
    *,
    trials_per_block_count: int,
    blocks: int | None = None,
    content_seconds: float | None = None,
    trial_seconds_override: float | None = None,
    break_every_trials: int | None = None,
    pre_task_seconds: float | None = None,
    practice_seconds: float | None = None,
    continuation_seconds: float | None = None,
    break_seconds: float | None = None,
    completion_seconds: float | None = None,
) -> list[tuple[str, float]]:
    """Return [(label, seconds)] for every component of one session."""
    blocks = block_count() if blocks is None else blocks
    trial = trial_seconds_override if trial_seconds_override is not None else trial_seconds(content_seconds)
    pre_task = MEASURED_SCREEN_SECONDS['pre_task_seconds'] if pre_task_seconds is None else pre_task_seconds
    practice = MEASURED_SCREEN_SECONDS['practice_seconds'] if practice_seconds is None else practice_seconds
    cont = MEASURED_SCREEN_SECONDS['continuation_seconds'] if continuation_seconds is None else continuation_seconds
    break_len = float(config.BREAK_OFFER_SECONDS) if break_seconds is None else break_seconds
    completion = MEASURED_SCREEN_SECONDS['completion_seconds'] if completion_seconds is None else completion_seconds

    trials = trials_per_block_count * blocks
    breaks = break_count(trials, blocks, break_every_trials)
    screens = continuation_screens(trials, blocks)
    return [
        ('Pre-task screens (placement, key check, sound check, instructions, rules)', pre_task),
        ('Practice (coached steps + paced round + summary)', practice),
        (f'Main task: {trials} trials x {trial:.1f} s', trials * trial),
        (f'Feedback screens: {screens} x {cont:.1f} s', screens * cont),
        (f'Breaks: {breaks} x {break_len:.0f} s', breaks * break_len),
        ('Completion screen', completion),
    ]


def session_duration(breakdown: list[tuple[str, float]]) -> float:
    """Total seconds for a breakdown."""
    return sum(seconds for _, seconds in breakdown)


def _bisect_solve(target_seconds, fn, low, high):
    """Find x in [low, high] where the monotonic fn(x) == target_seconds."""
    if fn(low) > target_seconds:
        return low
    if fn(high) < target_seconds:
        return high
    for _ in range(80):
        mid = (low + high) / 2
        if fn(mid) < target_seconds:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def trials_for_duration(
    target_seconds: float,
    *,
    blocks: int | None = None,
    step: int | None = None,
    **duration_options,
) -> dict:
    """Solve trials per block for a target session duration.

    Trials per block is always a multiple of PT_COUNT_PER_BLOCK, because every PT
    must be the active PT the same number of times. `step` overrides that
    granularity (for example 2 gives only every other reachable count).
    """
    blocks = block_count() if blocks is None else blocks
    granularity = config.PT_COUNT_PER_BLOCK if step is None else step
    if granularity < 1:
        raise ValueError('step must be a positive number of trials per block.')

    def total(per_block: float) -> float:
        return session_duration(duration_breakdown(
            trials_per_block_count=per_block, blocks=blocks, **duration_options,
        ))

    ideal = _bisect_solve(target_seconds, total, 0.0, 10_000.0)
    # Reachable lengths are quantized: trials per block moves in whole steps so
    # every PT stays equally often the active PT.
    step_seconds = total(granularity) - total(0)
    if ideal <= granularity:
        return {
            'target_seconds': target_seconds, 'blocks': blocks,
            'granularity': granularity, 'ideal_trials_per_block': ideal,
            'step_seconds': step_seconds, 'candidates': [],
            'note': 'even zero trials overshoot the target once the fixed screens are counted',
        }
    steps = max(0, int(math.floor(ideal / granularity)))
    candidates = sorted({steps * granularity, (steps + 1) * granularity})
    return {
        'target_seconds': target_seconds,
        'blocks': blocks,
        'granularity': granularity,
        'step_seconds': step_seconds,
        'ideal_trials_per_block': ideal,
        'candidates': [
            {
                'trials_per_block': per_block,
                'trials_total': per_block * blocks,
                'trials_per_pt': per_block // config.PT_COUNT_PER_BLOCK,
                'seconds': total(per_block),
                'minutes': total(per_block) / 60.0,
                'difference_seconds': total(per_block) - target_seconds,
            }
            for per_block in candidates
        ],
    }


def closest_candidate(solution: dict) -> dict:
    """The solved trial count nearest the target duration."""
    if not solution['candidates']:
        raise ValueError('No reachable trial count solves this target duration.')
    return min(solution['candidates'], key=lambda item: abs(item['difference_seconds']))


def trial_content_stats(
    trials_total: int, *,
    pt_range=None, npt_range=None, pd_range=None, npd_range=None,
    content_seconds: float | None = None,
) -> dict:
    """Planned stimulus load for a whole session, from the configured ranges."""
    pt_range = config.TRIAL_PT_RANGE if pt_range is None else pt_range
    npt_range = config.TRIAL_NPT_RANGE if npt_range is None else npt_range
    pd_range = config.TRIAL_PD_RANGE if pd_range is None else pd_range
    npd_range = config.TRIAL_NPD_RANGE if npd_range is None else npd_range
    content = config.TRIAL_CONTENT_DUR if content_seconds is None else content_seconds
    mean = lambda bounds: (bounds[0] + bounds[1]) / 2

    targets_mean = mean(pt_range) + mean(npt_range)
    visuals_mean = targets_mean + mean(pd_range) + mean(npd_range)
    return {
        'trials': trials_total,
        'content_seconds': content,
        'targets_per_trial_min': pt_range[0] + npt_range[0],
        'targets_per_trial_max': pt_range[1] + npt_range[1],
        'targets_per_trial_mean': targets_mean,
        'visuals_per_trial_mean': visuals_mean,
        'targets_total_mean': targets_mean * trials_total,
        'visuals_total_mean': visuals_mean * trials_total,
        'sounds_total_mean': (mean(pt_range) + mean(pd_range)) * trials_total,
        'mean_target_interval_seconds': content / targets_mean if targets_mean else None,
        'responses_per_minute': 60.0 / (content / targets_mean) if targets_mean else None,
    }


# --- Reports -----------------------------------------------------------------

def summary(target_seconds: float, **duration_options) -> dict:
    """Solved trial counts, the chosen configuration, load, and the breakdown."""
    solution = trials_for_duration(target_seconds, **duration_options)
    chosen = closest_candidate(solution)
    breakdown = duration_breakdown(
        trials_per_block_count=chosen['trials_per_block'],
        blocks=solution['blocks'],
        **duration_options,
    )
    content = duration_options.get('content_seconds')
    return {
        'solution': solution,
        'chosen': chosen,
        'breakdown': breakdown,
        'load': trial_content_stats(chosen['trials_total'], content_seconds=content),
        'config_trials_per_block': trials_per_block(),
        'config_minutes': session_duration(duration_breakdown(
            trials_per_block_count=trials_per_block(),
        )) / 60.0,
        'calibration_source': MEASURED_SCREEN_SOURCE,
    }


def cadence_table(
    *,
    target_seconds: float,
    targets_options,
    cadences,
    content_seconds: float | None = None,
    **duration_options,
) -> list[dict]:
    """One row per (targets per trial, seconds between targets) combination.

    Targets per trial is achieved by PT + NPT counts, so the content window must
    be targets x cadence long; the trial then also carries TRIAL_BUFFER_DUR at
    each end, and the row reports how many trials then fit in the target time.
    """
    rows = []
    for targets in targets_options:
        for cadence in cadences:
            content = targets * cadence
            trial = trial_seconds(content)
            solution = trials_for_duration(
                target_seconds, content_seconds=content, **duration_options,
            )
            if not solution['candidates']:
                continue
            chosen = closest_candidate(solution)
            rows.append({
                'targets_per_trial': targets,
                'cadence_seconds': cadence,
                'content_seconds': content,
                'trial_seconds': trial,
                'trials_per_block': chosen['trials_per_block'],
                'trials_total': chosen['trials_total'],
                'minutes': chosen['minutes'],
                'difference_seconds': chosen['difference_seconds'],
                'targets_total_mean': targets * chosen['trials_total'],
            })
    return rows


def _print_summary(report: dict, target_seconds: float) -> None:
    solution, chosen = report['solution'], report['chosen']
    print('SESSION TIMING MODEL')
    print('=' * 78)
    print(f'Target participant-facing duration: {target_seconds / 60:.1f} min ({target_seconds:.0f} s)')
    print(f'Trials per block today: {report["config_trials_per_block"]} '
          f'({report["config_minutes"]:.1f} min session, '
          f'{trial_seconds():.0f} s trial)')
    print(f'Screen times: {report["calibration_source"]}')
    print()
    print(f'Solved trials per block (multiple of {solution["granularity"]} so every PT is '
          'seen equally often):')
    print(f'  session length is therefore quantized in {solution["step_seconds"]:.0f} s steps; '
          f'the nearest reachable length is at most '
          f'{solution["step_seconds"] / 2:.0f} s from the target')
    print(f'  ideal {solution["ideal_trials_per_block"]:.2f} ->')
    for candidate in solution['candidates']:
        marker = '  <-- closest' if candidate is chosen else ''
        print(f'    {candidate["trials_per_block"]:3d} per block '
              f'({candidate["trials_total"]:3d} total, {candidate["trials_per_pt"]:3d} per PT '
              f'per block): {candidate["minutes"]:5.1f} min '
              f'({candidate["difference_seconds"]:+.0f} s){marker}')
    print()
    print(f'Chosen: {chosen["trials_per_block"]} trials/block, {chosen["trials_total"]} trials '
          f'total, {chosen["minutes"]:.1f} min, '
          f'{chosen["seconds"] / chosen["trials_total"]:.1f} s per trial including screens')
    print()
    print('Breakdown:')
    total = session_duration(report['breakdown'])
    for label, seconds in report['breakdown']:
        print(f'  {seconds:7.1f} s  {100 * seconds / total:5.1f}%  {label}')
    print()
    load = report['load']
    print('Stimulus load at those trial counts (from the configured ranges):')
    print(f'  targets/trial: {load["targets_per_trial_min"]}-{load["targets_per_trial_max"]} '
          f'(mean {load["targets_per_trial_mean"]:.1f})')
    print(f'  visuals/trial: ~{load["visuals_per_trial_mean"]:.1f}')
    print(f'  session totals: ~{load["targets_total_mean"]:.0f} targets, '
          f'~{load["visuals_total_mean"]:.0f} visuals, ~{load["sounds_total_mean"]:.0f} sounds')
    if load['mean_target_interval_seconds']:
        print(f'  one target every {load["mean_target_interval_seconds"]:.2f} s of the '
              f'{load["content_seconds"]:.0f} s content window '
              f'(~{load["responses_per_minute"]:.1f} responses/min)')


def _print_length_table(per_block_values, target_seconds, options) -> None:
    print('TRIALS PER BLOCK -> SESSION LENGTH')
    print('=' * 78)
    print(f'{"per block":>9s} {"per PT":>7s} {"total":>6s} {"minutes":>8s}'
          '   targets   visuals')
    for per_block in per_block_values:
        total = per_block * block_count()
        seconds = session_duration(duration_breakdown(
            trials_per_block_count=per_block, **options,
        ))
        load = trial_content_stats(total, content_seconds=options.get('content_seconds'))
        print(f'{per_block:9d} {per_block // config.PT_COUNT_PER_BLOCK:7d} {total:6d} '
              f'{seconds / 60:8.1f}   ~{load["targets_total_mean"]:7.0f}  '
              f'~{load["visuals_total_mean"]:8.0f}')


def _print_cadence_table(rows, target_seconds) -> None:
    print('TARGET CADENCE -> TRIAL LENGTH -> TRIALS THAT FIT')
    print('=' * 78)
    print('Targets per trial = TRIAL_PT_RANGE + TRIAL_NPT_RANGE; content window = targets x cadence.')
    print(f'{"targets":>7s} {"cadence":>8s} {"content":>8s} {"trial":>7s} {"per block":>10s}'
          f' {"total":>6s} {"minutes":>8s} {"targets":>9s}')
    for row in rows:
        print(f'{row["targets_per_trial"]:7d} {row["cadence_seconds"]:7.1f}s '
              f'{row["content_seconds"]:7.1f}s {row["trial_seconds"]:6.1f}s '
              f'{row["trials_per_block"]:10d} {row["trials_total"]:6d} '
              f'{row["minutes"]:8.1f} {row["targets_total_mean"]:9.0f}')
    print(f'\nAll rows land within {max(abs(row["difference_seconds"]) for row in rows):.0f} s '
          f'of the {target_seconds / 60:.1f} min target.')


# --- Pilot calibration -------------------------------------------------------

def _session_stats(session_dir: Path) -> dict | None:
    """Measured screen times and inter-trial gaps for one session folder."""
    metadata_path = session_dir / 'session_metadata.json'
    if not metadata_path.is_file():
        return None
    metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    participant_dir = session_dir.parent
    practice = metadata.get('practice')
    practice_seconds = practice.get('duration_seconds') if isinstance(practice, dict) else None
    pre_task = None
    report = participant_dir / 'preflight_report.txt'
    if report.is_file() and practice_seconds is not None and metadata.get('started_utc'):
        for line in report.read_text(encoding='utf-8').splitlines():
            if line.startswith('measured_at='):
                measured = datetime.fromisoformat(line.split('=', 1)[1])
                started = datetime.fromisoformat(metadata['started_utc'])
                pre_task = (started - measured).total_seconds() - practice_seconds
    gaps = []
    log_path = session_dir / 'trial_log.csv'
    if log_path.is_file():
        with log_path.open(encoding='utf-8') as source:
            rows = [row for row in csv.DictReader(source)
                    if row.get('trial_complete') == 'True']
        gaps = [
            float(right['trial_start_session_time']) - float(left['trial_end_session_time'])
            for left, right in zip(rows, rows[1:]) if left['block'] == right['block']
        ]
    return {
        'participant': participant_dir.name,
        'session': session_dir.name,
        'status': metadata.get('completion_status'),
        'pre_task_seconds': pre_task,
        'practice_seconds': practice_seconds,
        'trial_gaps_seconds': gaps,
        'break_seconds': [item.get('elapsed_seconds') for item in metadata.get('breaks') or []],
    }


def calibrate(data_dir) -> dict:
    """Aggregate measured screen times across every session under data_dir."""
    data_dir = Path(data_dir)
    sessions = [
        stats
        for participant in sorted(data_dir.glob('participant_*'))
        for session in sorted(participant.glob('session_*'))
        if (stats := _session_stats(session)) is not None
    ]

    def median_of(field):
        values = [item[field] for item in sessions if item[field] is not None]
        return statistics.median(values) if values else None

    gaps = [gap for item in sessions for gap in item['trial_gaps_seconds']]
    return {
        'data_dir': str(data_dir),
        'sessions': len(sessions),
        'sessions_detail': sessions,
        'medians': {
            'pre_task_seconds': median_of('pre_task_seconds'),
            'practice_seconds': median_of('practice_seconds'),
            'continuation_seconds': statistics.median(gaps) if gaps else None,
        },
        'within_block_trial_gaps': {
            'count': len(gaps),
            'median_seconds': statistics.median(gaps) if gaps else None,
            'mean_seconds': statistics.fmean(gaps) if gaps else None,
            'maximum_seconds': max(gaps) if gaps else None,
        },
    }


def _print_calibration(report: dict) -> None:
    print('PILOT CALIBRATION')
    print('=' * 78)
    print(f'{report["sessions"]} sessions under {report["data_dir"]}')
    for item in report['sessions_detail']:
        pre, practice = item['pre_task_seconds'], item['practice_seconds']
        gaps = ', '.join(f'{gap:.1f}' for gap in item['trial_gaps_seconds']) or 'none'
        print(f"  {item['participant']:16s} {str(item['status']):9s} "
              f"pre-task={'n/a' if pre is None else f'{pre:.0f}s':>6s} "
              f"practice={'n/a' if practice is None else f'{practice:.0f}s':>6s} "
              f"trial gaps=[{gaps}]")
    print()
    print('Medians (the defaults this model uses):')
    for name, value in report['medians'].items():
        print(f'  {name}: {"n/a" if value is None else f"{value:.1f} s"}')
    gaps = report['within_block_trial_gaps']
    if gaps['count']:
        print(f"  within-block trial gaps: n={gaps['count']}, median={gaps['median_seconds']:.1f}s, "
              f"mean={gaps['mean_seconds']:.1f}s, max={gaps['maximum_seconds']:.1f}s")
        print('  The maximum is a participant who left the room; the model uses the median.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target-minutes', type=float, default=45.0,
                        help='participant-facing session length to solve for (default: 45)')
    parser.add_argument('--trials-per-block', type=int, nargs='+',
                        help='print a session-length table for these trials-per-block values')
    parser.add_argument('--cadence-table', action='store_true',
                        help='print the targets-per-trial x target-cadence decision table')
    parser.add_argument('--targets-per-trial', type=int, nargs='+', default=[8, 11, 12, 14, 16],
                        help='rows for --cadence-table (default: 8 11 12 14 16)')
    parser.add_argument('--cadences', type=float, nargs='+', default=[2.0, 2.5, 3.0],
                        help='seconds between targets for --cadence-table (default: 2.0 2.5 3.0)')
    parser.add_argument('--content-seconds', type=float,
                        help='override TRIAL_CONTENT_DUR (trial length follows from it)')
    parser.add_argument('--trial-seconds', type=float,
                        help='override the whole trial length directly (config.TRIAL_DURATION)')
    parser.add_argument('--break-every', type=int, metavar='TRIALS',
                        help='model a break inside the trial loop every N trials '
                             '(not implemented in experiment.py yet)')
    parser.add_argument('--blocks', type=int, help='override the number of blocks (default: 2)')
    for name in MEASURED_SCREEN_SECONDS:
        parser.add_argument(f'--{name.replace("_", "-")}', type=float,
                            dest=name, help=f'override the measured {name}')
    parser.add_argument('--calibrate', type=Path,
                        help='recompute the pilot screen-time medians from a data directory')
    parser.add_argument('--json-report', type=Path, help='write the report as JSON')
    args = parser.parse_args()

    options = {name: getattr(args, name) for name in MEASURED_SCREEN_SECONDS
               if getattr(args, name) is not None}
    if args.blocks is not None:
        options['blocks'] = args.blocks
    if args.break_every is not None:
        options['break_every_trials'] = args.break_every
    if args.trial_seconds is not None:
        options['trial_seconds_override'] = args.trial_seconds
    elif args.content_seconds is not None:
        options['content_seconds'] = args.content_seconds

    target_seconds = args.target_minutes * 60.0
    report = summary(target_seconds, **options)
    _print_summary(report, target_seconds)

    if args.trials_per_block:
        print()
        _print_length_table(args.trials_per_block, target_seconds, options)
    if args.cadence_table:
        print()
        _print_cadence_table(cadence_table(
            target_seconds=target_seconds,
            targets_options=args.targets_per_trial,
            cadences=args.cadences,
            **options,
        ), target_seconds)
    if args.calibrate:
        print()
        _print_calibration(calibrate(args.calibrate))
    if args.json_report:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(f'\nJSON report: {args.json_report}')


if __name__ == '__main__':
    main()
