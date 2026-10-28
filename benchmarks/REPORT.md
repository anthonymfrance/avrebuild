# Stimulus placement at 100 trials: investigation and results

Branch `scheduler-100-trials`, forked from `integration` at `920da3a`. No `config.py`
value changed, so plans generated before this branch still load (`session_io.load_timeline`
refuses a plan if any uppercase config value differs from its snapshot).

## Summary

- The current code produced a 100-trial plan for **45 of 100 seeds**. Because
  `create_participant_plan` tries 5 seeds, about 1 participant in 20 (0.55^5) would get
  `PlanGenerationError`.
- About **a third of 100-trial seeds cannot be scheduled by any algorithm**. They draw at
  least one trial whose favored (top-right) corner needs more than the 20 s content window
  (0.28% of trials). The cause is that 80% of targets go to that corner and each target
  holds it for 1.4 s. The old capacity check only tested the 0.15 s onset gap, so it never
  caught these. Each one then burned 750 placement orders before failing.
- The improved scheduler does three things. It rejects those trials before placement using
  order-independent lower bounds. It keeps every placed trial instead of restarting the
  timeline. It retries only the trials the unchanged random-order pass missed, using
  "repaired" orders. Result at 100 trials: **66 of 100 seeds** succeed, with **no
  placement-search failures** at any length. Every remaining failure is a provable (or
  zero-slack) lower-bound rejection, found in under a second.
- With 20 seed attempts (was 5), the chance of no plan at 100 trials is about 0.34^20 ≈ 1e-9.
  In an end-to-end run, **50 of 50 participants** got valid 100-trial plans that load through
  the runtime. They needed a mean of 1.6 seeds (max 5) and a median of 3.2 s per participant
  (max 7.1 s).
- Any seed the old code placed on its first timeline attempt gives a **byte-identical plan**
  (67/67 checked across 8, 20 and 100 trials). Timing distributions are unchanged within
  sampling noise.
- **Density is limited by the favored corner, not by the scheduler.** Raising PT or NPT counts
  at today's 0.6 s display makes most 100-trial plans impossible. Halving the display to
  0.3 s (0.15 s fades) removes that limit for today's counts and for PT 3–4.

## 1. How the current code works (verified against `920da3a`)

Execution path from master seed to plan:

1. `participant_setup.create_participant_plan` (l. 285) draws a 64-bit
   `secrets.randbits` seed and calls `build_plan(seed, block_order)` (l. 44).
2. `build_plan` creates two independent streams with `derive_rng(seed, label)`, which is
   `random.Random(f'{seed}:{label}')` (l. 37):
   - `split_slotting`: `stimulus_split.split_pool` shuffles each category once. That gives
     2 PT and 2 PD per category, and the remaining 6 items become NPT/NPD (`split_group`,
     l. 22). `build_slotting_key` then runs on the same stream.
   - `timeline`: PT SOAs (one per block × PT identity), PD/NPD draws (count, item, corner,
     PD SOA), event order and slack, and finally x/y jitter.
3. `slotting_key.build_slotting_key` (l. 58), per block:
   - `pt_sequence` (`stimulus_split.py` l. 97) lists each PT `TRIALS_PER_PT` times and
     shuffles the list. Its length is the trial count.
   - Each trial draws a PT count from `TRIAL_PT_RANGE`. All of a trial's PT events are its
     one active PT.
   - Per PT, `corner_pile` (l. 35) assigns `round(0.8 × appearances)` to `top_right` and
     splits the rest as evenly as possible over the other three corners, then shuffles.
   - NPTs: a count from `TRIAL_NPT_RANGE` per trial, items drawn with replacement, and the
     same corner rule per NPT identity.
4. `timeline_key.build_timeline` (l. 561) derives `trial_count = max(trial)` (l. 583). There
   is no independent session-length setting. It checks only the onset-gap capacity
   (l. 625), then makes up to `MAX_TIMELINE_ATTEMPTS = 3` passes (l. 639). Each pass starts
   from `timeline = []` (l. 642) and places every trial in order with
   `_construct_trial_schedule` (l. 229).
5. `_construct_trial_schedule` tries up to `MAX_PLACEMENT_ATTEMPTS = 250` random orders
   (l. 375) from `random_order` (l. 236). That is a shuffle that avoids repeating the
   previous identity or following a target into its corner when it can. `schedule`
   (l. 283) packs each order at the minimum pairwise separation, then makes 9 attempts at
   spreading random slack (l. 296; the last attempt uses zero slack). It finally re-checks
   every pair with `_conflict`.

Answers to the specific questions:

- **Trial count.** Trials per block = `PT_COUNT_PER_BLOCK × TRIALS_PER_PT` = 2 × 2 = 4.
  Total = 2 blocks × 4 = 8. Nothing else hard-codes 4 or 8; a grep found none, and the
  benchmarks run 8–100 by setting `TRIALS_PER_PT` alone.
- **An event or trial cannot be placed.** Events are never placed one at a time; a whole
  order either fits or it doesn't. After 250 orders, `_construct_trial_schedule` raises
  `PlacementFailure`.
- **A timeline fails.** The exception aborts the pass (l. 651). **All previously placed
  trials are discarded** and the next pass starts over from trial 1.
- **Retry limits and seeds.** Retries are 250 orders per trial per pass, 3 passes per seed,
  and 5 seeds per participant. Timeline passes **do not reseed**: they continue the same
  `timeline` stream, and the required events (counts, items, corners, SOAs) are frozen
  before the first pass, so a pass retry can only change orders and slack. Each new
  participant attempt uses a fresh secret seed, and failed seeds are recorded in metadata.
- **Hard-coded assumptions.** Exactly two blocks, named `animate`/`inanimate`. 10 items per
  category, with `PT + PD ≤ 10`. NPT/NPD drawn with replacement. Block order counterbalanced
  over two blocks. The 24 s trial grid assumes cross-trial gaps are always safe (2 × 2 s
  buffers).
- **Which constraint fails.** It is always the favored corner. Every failed trial in the
  baseline had its corner bound as its largest bound. Trial failure rate by corner load
  (lower bound ÷ 20 s), per 250-order call at 100 trials: under 0.5% below 0.85, 1.4% at
  0.85–0.90, 21% at 0.90–0.95, 68% at 0.95–1.00, and 100% at 1.00 or above
  (`baseline.json`, `trial_failure_by_load_bucket`).
- **A side observation.** The packing in `schedule` models every `_conflict` rule.
  Re-checking 7,304 orders whose tightest packing fits (100-trial plans, seeds 7001–7020),
  `_conflict` still rejected 35 of them (0.5%). Every case was a pair placed at exactly a
  minimum spacing, where float rounding left the gap at most 3.6e-13 s short;
  `_conflict` compares with no tolerance. That is conservative, not a correctness issue,
  and was left alone. So "placement failure" means "no tried order was short enough", not a
  hidden constraint.

## 2. Valid session lengths

- Each PT is active in exactly `TRIALS_PER_PT` trials per block, so trials per block =
  `PT_COUNT_PER_BLOCK × TRIALS_PER_PT`. With 2 PTs per block, a block must have an **even**
  number of trials. With two blocks, the total must be a **multiple of 4**.
- 8, 20, 40, 60, 80 and 100 are all valid. A total of 100 means `TRIALS_PER_PT = 25`:
  50 animate-target trials and 50 inanimate-target trials, each PT active in 25 trials per
  block.
- 98 or 102 are not valid: each would need 49 or 51 trials per block, which cannot be split
  equally between 2 PTs.
- The corner rule scales without change. A PT's 50–75 appearances per block get
  `round(0.8n)` on the favored corner. The validator checks this per identity, and it held
  on every generated plan.
- Setting the length for a real study means editing `TRIALS_PER_PT` in `config.py`. That
  intentionally refuses plans made at the old length.

## 3. Baseline (unmodified `920da3a`)

Seeds 1–100 per length, block order animate→inanimate. "1st pass" means placed without a
timeline restart. The repro column counts the first 20 successful seeds, each rebuilt and
compared by sha256. Every successful plan also passed the independent validator.
File: `baseline.json`.

| Total trials | Plans | 1st pass | Mean s per seed (all / success) | Mean orders per seed | Repro |
|---|---|---|---|---|---|
| 8 | 98/100 | 98 | 0.10 / 0.05 | 36 | 20/20 |
| 20 | 90/100 | 87 | 0.58 / 0.29 | 149 | 20/20 |
| 40 | 83/100 | 67 | 1.54 / 1.05 | 351 | 20/20 |
| 60 | 69/100 | 56 | 2.23 / 1.43 | 506 | 20/20 |
| 80 | 55/100 | 45 | 4.09 / 2.58 | 721 | 20/20 |
| 100 | 45/100 | 35 | 4.73 / 3.28 | 857 | 20/20 |

Every failure occurred in placement. Re-measuring the trial draws themselves (1000 seeds at
100 trials, no placement):

- 0.28% of trials have a favored-corner lower bound above 20 s.
- 24.9% of 100-trial plans contain at least one such trial.

The old code spent 750 orders on each of those before failing.

## 4. Alternatives compared

These live in `tools/placement_experiments.py`. Every candidate ends in the same
`_schedule_layout` and `_conflict` code, so all of them enforce exactly the production rules;
they differ only in how they choose an order.

- **A. Critical-first:** randomized list scheduling. It picks among events that can start
  earliest, weighted toward the corner with the most remaining hold time.
- **B. Trial-local retries:** the same sampler, but a failing trial retries alone.
- **C. Repair:** a random order, then single-event moves kept whenever the packed length
  does not grow (bounded local search).
- **Hybrid:** the current 250 random orders first, then repair (or critical-first) for the
  rest of the 750-order budget.
- **D. A constraint solver** was considered and not built. The lower bounds below show the
  residual failures are infeasible draws, not search failures, and a solver would add a
  dependency without changing that.

### Hard trials

Source: `corpus_hard.json`. All 10,000 trials from 100-trial plans, seeds 1–100, of which
542 are feasible with corner load ≥ 0.85. Each placer gets the same seed per trial.

| Placer | Solved | Total s | Worst trial s |
|---|---|---|---|
| Current sampler, 750 orders | 493 | 327 | 6.8 |
| Current sampler, 20,000 orders (reference) | 530 | 1804 | 114.7 |
| Repair | 536 | 301 | 61.1 |
| Critical-first | 536 | 46 | 7.5 |
| Hybrid (repair fallback) | 536 | 139 | 5.9 |

The 6 trials nobody solved all had a corner bound of exactly 20.0 s. They are now rejected
as zero-slack (section 5).

### Bias

Source: `bias.json`. A typical set (all trials from plans 1–10) and an out-of-sample hard
set (plans 1001–1040, load ≥ 0.85). Metrics are computed on trials every placer solved. The
reference is today's sampler with a large budget. KS is the two-sample Kolmogorov–Smirnov
distance over onset-by-role, gap and target-rank distributions; the column shows the worst
of those.

| Placer | Typical: identical to reference | Typical: span s | Typical: max KS | Hard: target rank | Hard: max KS |
|---|---|---|---|---|---|
| Reference | — | 18.51 | 0 | 0.504 | 0 |
| Critical-first | 0/997 | 15.63 | 0.219 (gaps) | 0.615 | 0.308 |
| Repair everywhere | 726/997 | 18.60 | 0.022 | 0.509 | 0.049 |
| **Hybrid (repair)** | **991/997** | **18.51** | **0.002** | **0.506** | **0.015** |
| Hybrid (critical) | 991/997 | 18.50 | 0.002 | 0.516 | 0.033 |

**Why critical-first was rejected.** It is fast, but it compresses trials (15.6 s span
instead of 18.5 s) and pushes targets later in the trial.

**Why the hybrid with repair was chosen.** It matches every other method's reliability. It
has the lowest worst-case time. It is identical to today's output wherever today's code
succeeds. And where it isn't identical, it stays within about 0.015 KS of "today's sampler
with unlimited budget", which is about sampling noise for roughly 8000 onsets.

## 5. What changed

Commits:

- `39c1478`: `plan_validator.py`, the independent validator.
- `8d857e9`: `timeline_key._lower_bounds` / `_infeasibility`, round-based `build_timeline`,
  and `_repaired_order`. `build_plan` now validates every plan.
- `d078c18`: zero-slack rejection and `PLAN_SEED_ATTEMPTS = 20`.

Behavior:

- **Lower bounds before placement.** Four bounds, each true for every order:
  - corner: `1.4·T + 0.6·D − 0.8`
  - targets: `(T−1)·0.9 + 0.6`
  - audio: `(A−1)·1.2 + 1.0`
  - onsets: `(n−1)·0.15 + 0.6`

  A trial is rejected if any bound exceeds 20 s. It is also rejected if a bound equals
  20 s, because the only schedule would pin that family at minimum spacing with no
  randomness left. Either way the seed fails in milliseconds with a message naming the
  bound.
- **Placement passes.**
  - Pass 1 is the old sampler, unchanged.
  - Passes 2 and 3 (still `MAX_TIMELINE_ATTEMPTS`) retry only unplaced trials, with
    `REPAIR_RESTARTS = 25` repaired orders each (`REPAIR_MOVES = 400`).
  - Placed trials are never discarded.
  - These two repair constants live in `timeline_key`, not `config`, so existing plans keep
    loading.
- **Validation.** `build_plan` runs `validate_plan` and raises `PlanValidationError` on any
  problem. That error is never retried with a new seed: it means a bug, not a hard draw.
- **Metadata.** Participant metadata now records `failed_plan_reasons` and
  `placement.repaired_trials`, so every failed seed can be rebuilt with
  `build_plan(seed, block_order)` and any trial that needed repair can be audited.
- **Reproducibility.** The master seed plus config still determine the plan exactly. Trial
  caching was not adopted. Within a seed it is now implicit, because placed trials are kept.
  Across seeds it would mix draws from different seeds and break "seed → plan".

**Selection bias from rejecting impossible seeds.** Rejection is exact conditioning on a
feasible plan. Mean targets per trial moves from 8.010 to 8.003, and P(≥ 10 favored-corner
targets in a trial) from 4.36% to 4.16% (1000 plans, seeds 20001–21000). That is the
unavoidable cost of excluding impossible trials.

## 6. Validator and tests

`plan_validator.validate_plan` re-derives every rule from `config.py` and the stimulus lists.
It shares no checking code with the generator, and it returns all problems rather than the
first. It checks:

- Total and per-block trial count.
- Category pools, including the cross-block complement.
- One active PT per trial, and each PT active exactly `TRIALS_PER_PT` times.
- Per-trial PT/NPT/PD/NPD counts within their ranges.
- The slotting ↔ timeline 1:1 mapping.
- The per-identity 80% corner rule.
- Content windows; response plus late window inside the trial.
- SOA ranges and a fixed PT SOA per identity.
- Quadrant positions.
- Every pairwise rule: onset gap, same-corner overlap and hold, same-item gap, target gaps,
  PT spacing and PT sound vs. the previous response window, audio gap.

`tests/test_scheduler.py` (12 tests) covers:

- The 8-trial plan for seed 7 stays byte-identical to `920da3a`.
- A complete, valid, reproducible 100-trial plan, with 50 trials per block from the right
  category.
- Wrong-length and zero-length plans are rejected.
- A trial moved to the other PT is rejected.
- Broken corner balance and broken spacing are rejected.
- `build_plan` refuses a plan the validator rejects.
- The corner bound, including the zero-slack case.
- Rejection happens before any placement order.
- A failed trial is retried alone (9 placement calls for 8 trials).
- The pass limit is enforced.

The full suite passes: 132 tests.

## 7. 100-trial reliability with the final code

Seeds 1–100, file `improved.json`. "1st pass" means placed without any repair.

| Total trials | Plans | 1st pass | Mean s per seed (all / success) | Mean orders per seed | Failures | Repro |
|---|---|---|---|---|---|---|
| 8 | 99/100 | 98 | 0.08 / 0.08 | 23 | 1 zero-slack | 20/20 |
| 20 | 99/100 | 87 | 0.46 / 0.46 | 95 | 1 bound | 20/20 |
| 40 | 89/100 | 67 | 1.05 / 1.18 | 177 | 11 bound | 20/20 |
| 60 | 89/100 | 56 | 1.41 / 1.59 | 272 | 11 bound | 20/20 |
| 80 | 78/100 | 45 | 1.52 / 1.94 | 337 | 22 bound | 20/20 |
| 100 | 66/100 | 35 | 1.60 / 2.41 | 326 | 34 bound | 20/20 |

Every success passed the independent validator.

Timing profile at 100 trials compared with baseline:

- Adjacent visual gaps at the 0.15 s minimum: 4.51% vs 4.46%.
- Mean trial span: 18.47 s vs 18.46 s.

End to end (`tools/plan_e2e.py`, 50 participants, seed 2026, `TRIALS_PER_PT = 25`): 50/50
plans written and loaded by `session_io.load_timeline`.

**Remaining limitations.**

- About a third of 100-trial seeds are rejected. This is a property of the design, not of
  the scheduler: the favored corner can't hold 11 targets plus 9 distractors in 20 s. The
  seed budget makes it harmless.
- Lower bounds can only reject; they never accept. A trial that passes them can still be
  unplaceable. None was observed with the final code in 100 seeds at any length, but it is
  not ruled out.
- `validate_timeline` is still O(n²) per block, about 1.3 s at 100 trials. That is
  acceptable once per participant, so it was left alone.

## 8. Sensitivity (separate from the comparison above; no setting was changed in the code)

Each scenario is 100 trials, seeds 1–100, with all other constraints unchanged. The bound
columns come from 300 plans (seeds 50001–50300) and show how many trials and plans the lower
bounds reject. That rejection rate is a ceiling on success that no scheduler can beat.

Fades: 0.15 s in + 0.15 s out with `PEAK_HOLD_DUR = 0` is a **0.3 s total display**. Opacity
rises linearly to full for an instant and falls (`trial_runner.planned_image_alpha`). The
SOA is anchored at that peak (onset + `FADE_IN_DUR`). Response and late windows do not
depend on the fades, so a target still holds its corner for 1.4 s.

| Scenario | Targets/trial | Target share | Trials rejected by bound | Plans with a rejected trial | Plans generated | Median s/success |
|---|---|---|---|---|---|---|
| Today (PT 2–3, NPT 3–8, 0.6 s) | 8.0 | 22% | 0.36% | 28% | 66/100 | 1.7 |
| PT 3–4 | 9.0 | 24% | 1.4% | 81% | 25/100 | 9.1 |
| PT 4–5 | 10.0 | 26% | 4.0% | 99% | 0/100 | — |
| NPT 5–10 | 10.0 | 26% | 4.4% | 99% | 1/100 | 19.9 |
| NPT 8–12 | 12.5 | 31% | 21% | 100% | 0/100 | — |
| PT 3–4 + NPT 5–10 | 11.0 | 28% | 9.5% | 100% | 0/100 | — |
| 0.15 s fades | 8.0 | 22% | 0 | 0% | **100/100** | 1.6 |
| 0.15 s fades + PT 3–4 | 9.0 | 24% | 0 | 0% | **100/100** | 1.4 |
| 0.15 s fades + NPT 5–10 | 10.0 | 26% | 0.07% | 7% | 93/100 | 1.7 |
| 0.15 s fades + PT 3–4 + NPT 5–10 | 11.0 | 28% | 0.71% | 52% | 52/100 | 5.5 |

Every failure in every scenario was a corner-bound rejection, apart from a few search
failures: 11 for PT 3–4 and at most 3 in any other scenario. The first seven scenarios ran
before the zero-slack rule, which would reclassify some of those. Reproducibility held for
every scenario that produced plans (up to 5 seeds each).

**What limits density.** The favored corner's budget:

> 1.4 s × favored targets + display duration × favored distractors − (1.4 − display duration) ≤ 20 s.

With 80% of targets on one corner, each extra target per trial costs about 1.1 s of that
corner. At 0.6 s display, the corner runs out at about 11 targets, and only for trials with
few top-right distractors. Shortening the display only buys back time on the distractors
sharing that corner (0.3 s each), which is why it helps so much at today's counts.

The levers that would actually raise capacity are all experimental-design choices, not
scheduler work:

- `TARGET_SPATIAL_BIAS`
- `LATE_WINDOW` (which sets the 1.4 s hold)
- `TRIAL_CONTENT_DUR`
- the number of distractors allowed in the favored corner

Before adopting any of them, run `tools/trial_corpus_bench.py --placers ''` with the
candidate `--set` values: it reports the rejection ceiling in seconds.

## Reproducing

```bash
# baseline: check out 920da3a in a separate worktree, then
python3 tools/scheduler_bench.py --seeds 100 --repro 20 --json benchmarks/baseline.json
# final code
python3 tools/scheduler_bench.py --seeds 100 --repro 20 --json benchmarks/improved.json
python3 tools/trial_corpus_bench.py --plans 100 --min-load 0.85 --json benchmarks/corpus_hard.json
python3 tools/bias_check.py --json benchmarks/bias.json
python3 tools/plan_e2e.py --participants 50 --trials-per-pt 25
python3 tools/scheduler_bench.py --lengths 100 --set FADE_IN_DUR=0.15 --set FADE_OUT_DUR=0.15 \
    --set "TRIAL_PT_RANGE=(3,4)" --json benchmarks/sens_fade_pt34.json
python3 tools/trial_corpus_bench.py --plans 300 --start-seed 50001 --placers '' --set "TRIAL_PT_RANGE=(3,4)"
```

`baseline.json` was produced by the harness before the placement code changed. Its
`--placer baseline` label is now `current`, and the harness's lower-bound helper now imports
`timeline_key._lower_bounds`, which `920da3a` lacks. To re-run the baseline, copy
`tools/scheduler_bench.py` from this branch and replace `trial_load` with the inline bounds
from section 5.
