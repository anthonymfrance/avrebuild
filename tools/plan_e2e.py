"""Create real participant folders at a given length and load them as the runtime would.

Seeds come from random.Random(--seed) instead of secrets, so the run is reproducible.

    python3 tools/plan_e2e.py --participants 50 --trials-per-pt 25
"""

import argparse
import contextlib
import io
import os
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--participants', type=int, default=50)
    parser.add_argument('--trials-per-pt', type=int, default=25)
    parser.add_argument('--seed', type=int, default=2026)
    args = parser.parse_args()

    import config
    config.TRIALS_PER_PT = args.trials_per_pt  # as if edited in config.py before launch
    import participant_setup
    from session_io import load_timeline

    os.environ.pop('AV_STUDY_SERVER_ROOT', None)
    os.environ.pop('AV_STUDY_SERVER_DATA_PATH', None)
    rng = random.Random(args.seed)
    participant_setup.secrets.randbits = rng.getrandbits
    attempts, seconds, repaired, errors = [], [], [], 0
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp)
        for _ in range(args.participants):
            pid = participant_setup.next_participant_id(data)
            started = time.perf_counter()
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    path, meta = participant_setup.create_participant_plan(data, pid)
            except participant_setup.PlanGenerationError as exc:
                errors += 1
                print(f'{pid}: {exc}'[:300])
                continue
            seconds.append(time.perf_counter() - started)
            rows, _, _, trials = load_timeline(path, meta, ROOT)
            assert {b: len(t) for b, t in trials.items()} == {
                'animate': 2 * args.trials_per_pt, 'inanimate': 2 * args.trials_per_pt}
            attempts.append(meta['plan_attempts'])
            repaired.append(len(meta['placement']['repaired_trials']))
    print(f'participants={args.participants} trials={4 * args.trials_per_pt} plan_errors={errors}')
    print(f'seed attempts per plan: mean={statistics.fmean(attempts):.2f} max={max(attempts)} '
          f'distribution={ {k: attempts.count(k) for k in sorted(set(attempts))} }')
    print(f'seconds per plan: median={statistics.median(seconds):.2f} max={max(seconds):.2f}')
    print(f'repaired trials per plan: mean={statistics.fmean(repaired):.2f} max={max(repaired)}')


if __name__ == '__main__':
    main()
