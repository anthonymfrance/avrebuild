# Planning a 45-minute session and a harder task

Two questions, answered with the code and the pilot data rather than by feel:

1. **How many trials does 45 minutes buy?** It is fully determined by how long one
   trial lasts, and one trial's length is set by the config. Today the session is
   **5.9 minutes**; 45 minutes needs **~68 or ~100 trials** depending on the
   trial length you choose.
2. **Does making the task harder break trial generation?** No — but only up to a
   target count that depends on the content window. With the current 20 s window,
   placement survives **11-13 targets per trial** and starts failing at 14-16.
   With a 30 s window, **18-20 targets** place on the first attempt.

Everything below is reproducible with the two tools added in this branch:
[`session_timing.py`](session_timing.py) (duration model and solver) and
[`capacity_sweep.py`](capacity_sweep.py) (feasibility sweep over config variants).

---

## 1. How long is a session, and how many trials fit in 45 minutes?

### 1.1 What the session is made of

`experiment.py` runs a fixed sequence. Only the main task scales with the trial
count; everything else is participant-paced and roughly constant.

| Component | Source |
| --- | --- |
| Finger placement, numpad check, sound check, instructions, scoring rules | `screens.py`, participant-paced |
| Practice (3 coached steps + held screen + paced round + summary) | `practice.py` |
| Main task: `trials` x `TRIAL_DURATION` | `config.TRIAL_DURATION = 24.0 s` |
| Feedback screen after every trial (SPACE), plus one before every block | `screens.continuation` |
| Break between blocks | `config.BREAK_OFFER_SECONDS = 30` |
| Completion screen | `experiment.py` |

So, in seconds:

```
T = pre_task + practice
  + trials x trial_seconds                       # 24.0 s today
  + (trials + 2) x continuation_seconds          # 2 feedback screens per block, 1 per trial
  + (blocks - 1) x break_seconds                 # 30 s
  + completion
```

### 1.2 Calibrating the participant-paced parts from the pilot

`python session_timing.py --calibrate /path/to/data` recomputes these medians
from `preflight_report.txt`, `session_metadata.json` and `trial_log.csv`:

| Parameter | Pilot median | Where it comes from |
| --- | --- | --- |
| Pre-task screens | 65 s | `measured_at` to `started_utc`, minus practice |
| Practice | 29 s | `session_metadata.practice.duration_seconds` |
| Feedback screen | 2.0 s | gap between `trial_end` and the next `trial_start` within a block |
| Break | 30 s offered | `config.BREAK_OFFER_SECONDS` (pilots often ended early) |
| Completion screen | 20 s | not measured; an estimate |

One trial is exactly **24.0 s** in the data: `trial_log.csv` shows 2880 frames at
119.98 Hz for every trial of every session.

**Model check against the three completed pilot sessions** (preflight report to
`ended_utc`, i.e. the participant-facing span):

| Participant | Observed | Model | Notes |
| --- | --- | --- | --- |
| participant_04 | 295 s | 325 s | +10% |
| participant_05 | 240 s | 322 s | participant pressed SPACE almost instantly everywhere |
| participant_08 | 354 s (649 s incl. a 295 s pause) | 336 s | -5% |

The model is within about 10% for participants who read the screens, and
over-predicts for a participant who races through them. Those screens are the
only soft part of the arithmetic.

### 1.3 Trial length is the knob; 45 minutes needs many trials

45 min = 2700 s. Subtracting the ~114 s of fixed screens:

| Trial length | Trials that fit | Total trials | Model duration |
| --- | --- | --- | --- |
| 20 s (content 16 s) | 58 / block | 116 | 45.0 min |
| 24 s (today: content 20 s) | 48 / block | 96 | 44.1 min |
| 24 s | 50 / block | 100 | 45.8 min |
| 28 s (content 24 s) | 42 / block | 84 | 44.5 min |
| 34 s (content 30 s) | 36 / block | 72 | 45.7 min |
| 34 s (content 30 s) + a break every 12 trials | 34 / block | 68 | 45.3 min |
| 40 s (content 36 s) | 30 / block | 60 | 44.5 min |
| 52 s (content 48 s) | 24 / block | 48 | 45.7 min |

`python session_timing.py --target-minutes 45 --cadence-table` prints the version
of this that is indexed by targets per trial rather than raw trial length.

### 1.4 Reachable trial counts are quantized, and that is not obvious

Each PT must be the active PT the same number of times, so trials per block is a
multiple of `PT_COUNT_PER_BLOCK` (2). With 24 s trials that quantizes session
length in **104 s steps** (1.7 min), so the best you can do is land within ~52 s
of any target. If 45:00 exactly matters, tune `BREAK_OFFER_SECONDS`,
`TRIAL_CONTENT_DUR` or `TRIAL_BUFFER_DUR` instead of the trial count.

---

## 2. What 45 minutes of this task actually costs the participant

At 45 minutes, keeping today's trial shape needs ~100 trials:

| | Today | 100 trials, 24 s each | 68 trials, 34 s each (recommended) |
| --- | --- | --- | --- |
| Targets | ~64 | ~800 (8/trial) | ~884 (13/trial) |
| Visual events | ~288 | ~3600 | ~3978 (58.5/trial) |
| Sounds | ~52 | ~650 | ~510 |
| Target cadence | one per 2.5 s | one per 2.5 s | one per 2.3 s |
| Response rate | 24/min | 24/min | 26/min |

Two consequences worth designing for:

- **One 30 s break in a 40-minute continuous response task is not enough.** The
  vigilance literature is consistent that decrements appear after roughly
  30 minutes, that they can appear within 10 minutes in demanding tasks, and that
  ~20-minute breaks are the common countermeasure (Al-Shargie et al. 2019;
  Klein & Feltmate 2025; Wolfe et al. 2007). Adding a break inside the trial
  loop is an **`experiment.py` change**: the block loop only breaks between
  blocks today. `session_timing.py --break-every 12` models it; for the
  recommended 68-trial plan a break every 12 trials means 5 breaks and ~150 s of
  total break time.
- **Report performance in time bins** (5 or 10 minutes) so a vigilance decrement
  is measurable rather than confounded with the difficulty manipulation.

---

## 3. How to make the task harder

Pilots 8 and 9 sat near ceiling (participant_08: 1 miss, 4 late, ~64 targets). The
levers below are ranked by how much they move difficulty per unit of risk.

### 3.1 Exposure 0.6 s -> 0.3 s (the professor's first idea): do this

`FADE_IN_DUR = FADE_OUT_DUR = 0.15` makes `VISUAL_DURATION = 0.3 s`. At the
required 120 Hz that is 37 frames instead of 73, and because
`PEAK_HOLD_DUR` is 0.0 the profile is a triangle:

| Profile | Frames | Frames at >= 50% opacity | Frames at full opacity | Integrated opacity-time |
| --- | --- | --- | --- | --- |
| 0.3 / 0.0 / 0.3 (today) | 73 | 36 | 1 | 0.300 opacity*s |
| 0.15 / 0.0 / 0.15 (proposed) | 37 | 18 | 1 | 0.150 opacity*s |
| 0.05 / 0.2 / 0.05 (alternative) | 37 | 30 | 25 | 0.250 opacity*s |

The proposed change **halves both the frame count and the integrated
contrast-time**, which is a defensible way to state the manipulation: not "0.3 s
instead of 0.6 s" but "half the contrast-time, and half the frames above 50%
opacity".

Note what the triangular profile means: with `PEAK_HOLD_DUR = 0.0` there is
**one frame at full opacity** in every profile, so this is a flash, not a
0.3 s look. If the intent is graded difficulty rather than a step change, hold
the peak: `0.05 / 0.2 / 0.05` gives the same total exposure with 25 frames at
full contrast. Worth deciding explicitly, because these two are very different
manipulations that both get called "0.3 s".

Also note the **0.9 s response window does not restore lost exposure** — it only
allows a delayed keypress. Hit rate and RT should be analysed separately.

The literature gives no guarantee this removes the ceiling: animal-category
pictures in RSVP are detectable at 20-113 ms (Potter & Fox 2009; Potter et al.
2014), and one picture-RSVP series showed a graded duration effect of
**64% at 240 ms, 77% at 400 ms, 86% at 720 ms** with masking. So 300 ms is a real
but not extreme manipulation, and the confident claim is "graded reduction", not
"ceiling removed".

### 3.2 Smaller stimulus 150 px -> 100 px: do this, but record viewing distance

The panel in the pilots is 597 mm wide across 1920 px (from
`preflight_report.txt`), so at a 60 cm viewing distance:

| Image | Physical size | Visual angle | Area vs 150 px | Centre eccentricity |
| --- | --- | --- | --- | --- |
| 150 px | 46.6 mm | 4.45 deg | 100% | 3.1-28.1 deg |
| 100 px | 31.1 mm | 2.97 deg | 44% | 2.1-29.0 deg |
| 75 px | 23.3 mm | 2.23 deg | 25% | 1.6-29.4 deg |
| 50 px | 15.5 mm | 1.48 deg | 11% | 1.0-29.9 deg |

100 px is 44% of the present area at ~3 deg. That is a reasonable target size at
these eccentricities, but **pixels are not a psychophysical unit**: write the
viewing distance into the protocol, and prefer 100 px over anything smaller so
the far corner of a quadrant stays comfortably supra-threshold.

### 3.3 More targets per trial: there is a hard placement ceiling

`capacity_sweep.py` runs the real generator
(`participant_setup.build_plan` -> `build_timeline` -> `validate_timeline`) for
every seed, with the exposure levers applied, and reports how often a whole
participant plan builds. 100 seeds per scenario, content window 20 s:

| Scenario | Targets/trial | Fail | First try | Within 5 seeds | Placement orders per plan |
| --- | --- | --- | --- | --- | --- |
| baseline (0.6 s, 150 px) | 5-11 | 2% | 98% | 100% | 20.6 |
| 0.3 s exposure only | 5-11 | 0% | 100% | 100% | 8.3 |
| 100 px only | 5-11 | 2% | 98% | 100% | 20.6 |
| 0.3 s + 100 px | 5-11 | 0% | 100% | 100% | 8.3 |
| 0.3 s + 100 px | **11-13** | 1% | 96% | 100% | 39.4 |
| 0.3 s + 100 px | **12-14** | 16% | 72% | 100% | 132.6 |
| 0.3 s + 100 px | 14-16 | **99%** | 0% | 4.9% | 515 |
| 0.3 s + 100 px | 16-18 | **100%** | 0% | 0% | - |

`create_participant_plan` retries with a fresh seed up to 5 times, so the
"within 5 seeds" column is the number that matters operationally. Note that the
failures are `placement_failure_within_capacity`: only ~47 of the ~130 visuals
that would physically fit are ever placed. The binding constraints are
`RESPONSE_WINDOW` (0.9 s between any two target onsets) and
`TARGET_CORNER_HOLD` (1.4 s for two targets in the same corner), made worse by
`TARGET_SPATIAL_BIAS = 0.80` putting ~80% of each identity's appearances in
`top_right`.

**The content window, not the target count, is the real limit.** Same generator,
content window 30 s, 60 seeds:

| Targets/trial | Fail | First try | Placement orders per plan |
| --- | --- | --- | --- |
| 12-14 | 0% | 100% | 8.0 |
| 14-16 | 0% | 100% | 8.0 |
| 16-18 | 0% | 100% | 8.1 |
| 18-20 | 0% | 100% | 8.8 |
| 12-14, distractors scaled to hold prevalence 22% | 0% | 100% | 8.1 |
| 12-14, prevalence-matched, 68 trials (the recommended plan) | 0% | 100% | 68.2 total, ~8.5 per trial |

With 30 s of content, even 18-20 targets place on the first attempt with ~9
placement orders per plan — *easier* than today's baseline at 20 s. The exposure
change helps here as well: a 0.3 s stimulus leaves more room in the schedule.

So the professor's "at least 11-12, ideally more" is comfortably reachable:
**11-13 targets in a 20 s window**, or **up to 18-20 in a 30 s window**.

### 3.3.1 What a target count means inside one trial

`TRIAL_PT_RANGE` is **not** the number of different privileged targets in a trial.
There is exactly one active PT per trial (`PT_COUNT_PER_BLOCK` per block, each
active on `TRIALS_PER_PT` trials); the range is how many times **that one image is
repeated** in the trial. `TRIAL_NPT_RANGE` is sampled **with replacement** from the
six remaining in-category items, so any count above 6 necessarily repeats
identities within the trial.

Per block the 10 category items split **2 PT / 2 PD / 6 NPT / 6 NPD**. A trial
generated at the recommended ranges (seed 7, animate trial 1, 61 events):

```
PT :  3 presentations from 1 identity    {elephant: 3}
NPT:  9 presentations from 4 identities  {horse: 4, pig: 2, cow: 2, frog: 1}
PD :  4 presentations from 2 identities  {phone: 3, toilet: 1}
NPD: 45 presentations from 6 identities  {camera: 13, helicopter: 9, ...}
```

The other NPT identities appear in other trials; across the block all six are
used. So a "12-14 target trial" is **~13 presentations of targets drawn from 1-7
distinct images**, not 12-14 distinct images. If the design needs more distinct
targets per trial, `PT_COUNT_PER_BLOCK` / `PD_COUNT_PER_BLOCK` are the knobs — and
they also change the PT manipulation, so they are not a difficulty lever.

### 3.3.2 Widening PT when the distractors are scaled too (30 s window)

Monte Carlo, 100 seeds per scenario, 8-trial plans, `HARDER` exposure levers,
`TRIAL_NPT_RANGE = (9, 10)`, `TRIAL_NPD_RANGE = (38, 45)`:

| `TRIAL_PT_RANGE` | Targets/trial | Placement failures | First try | Orders/plan | PT observations/session | Sounds/session |
| --- | --- | --- | --- | --- | --- | --- |
| (3, 4) | 12-14 | **0/100** | 100% | 8.0 | 237 (3.5/trial) | 504 (7.4/trial) |
| (3, 5) | 12-15 | **0/100** | 100% | 8.2 | 273 (4.0/trial) | 540 (7.9/trial) |
| (3, 6) | 12-16 | **0/100** | 100% | 8.5 | 297 (4.4/trial) | 564 (8.3/trial) |

All three are in the 30 s content window. Widening PT to 3-5 is **free**: same
zero failures, 8.2 vs 8.0 randomized placement orders per plan, and it buys 36
more PT observations and 36 more sounds across the session. Prevalence stays
22-23.5% because NPD absorbs the extra targets, and the PT corner mix stays
exactly 80% in `top_right` (the bias is per identity across the block, so it is
scale-invariant).

**With those same dense distractors, this PT range in a 20 s window fails 60/60
seeds (100%).** Each failed seed burns the full 750 placement orders, so that
scenario alone took 523 s to simulate. That failure is the distractor count and the
content window, **not** the PT range: PT (3, 5) plus NPT (9, 10) plus NPD (38, 45)
is ~59-65 visual events in a trial, and a 20 s window cannot host that load under
the corner-hold and response-window rules.

Do not read this as "PT 5 needs a 30 s window". With today's distractor count
(20, 28), PT 3-5 places fine in a 20 s window — section 3.3.3.
The distractor count is what has to move with the content window, which is why
option B below deliberately leaves NPD alone.

### 3.3.3 In a 20 s window the cap is the target total, not the PT count

**Read section 3.3.4 before acting on this table.** These rows are 8-trial plans;
a real session is 68-100 trials, and failure compounds with the trial count.

All rows: `HARDER` exposure levers, content 20 s, `TRIAL_NPD_RANGE` left at
today's (20, 28), 8-trial plans. Monte Carlo per row, n as shown.

| `TRIAL_PT_RANGE` | `TRIAL_NPT_RANGE` | Targets/trial | n | Placement failures | First try | Within 5 seeds |
| --- | --- | --- | --- | --- | --- | --- |
| (3, 5) | (7, 8) | 10-13 | 60 | **1/60** | 98.3% | 100% |
| (2, 3) | (9, 10) | 11-13 | 100 | **1/100** | 96.0% | 100% |
| (4, 5) | (7, 8) | 11-13 | 60 | **5/60** | 88.3% | 100% |
| (3, 5) | (8, 9) | 11-14 | 100 | **16/100** | 72.0% | 100% |
| (3, 4) | (9, 10) | 12-14 | 100 | **16/100** | 72.0% | 100% |
| (4, 5) | (8, 9) | 12-14 | 100 | **20/100** | 72.0% | 100% |
| (3, 5) | (9, 10) | 12-15 | 60 | **30/60** | 38.3% | 96.9% |
| (3, 6) | (9, 10) | 12-16 | 60 | **52/60** | 10.0% | 51.1% |
| (3, 4) | (11, 12) | 14-16 | 100 | **99/100** | 0.0% | 4.9% |

**PT (3, 4) is not a hard ceiling on PT.** PT 5 and PT 6 both place fine in a 20 s
window — what is capped is the **total number of target presentations per trial**, at
roughly 14. Read the table by that column, not by the PT column: 10-14 targets
sits at 1-20% per-seed failure, 15 targets jumps to 50%, 16 to 87%, and 14-16
(mean 15) to 99%.

Two consequences for a 20 s design:

- At 8 trials, `TRIAL_PT_RANGE = (3, 5)` with `TRIAL_NPT_RANGE = (8, 9)` (11-14
  targets) looks free: 16/100, identical to (3, 4) / (9, 10) at 12-14. **It is not
  free at full length** — that split fails 28/30 as a 100-trial plan (3.3.4). The
  20 s way to reach PT 5 is `(3, 5)` with `(7, 8)`, i.e. 10-13 targets, not 11-14.
- The mix is a secondary cost at a fixed total. At 11.8 vs 12.0 targets/trial,
  PT (4, 5) produces **8.4 sounds/trial against 6.2** for PT (2, 3), and sounds must
  be at least `SOUND_DUR + MIN_AUDIO_GAP` = 1.2 s apart. That is 10.1 s of the 20 s
  window locked up versus 7.4 s, which is why the failure rate rises from 1% to 8%
  even though the target total is identical. PT carries sound; NPT does not.

### 3.3.4 The 8-trial rates understate long-plan risk — measure at the real length

`create_participant_plan` builds **one plan per participant**, so what matters is the
failure probability of the whole 68- or 100-trial plan, not of an 8-trial plan. A
per-trial failure probability `p` compounds: `p_plan(N) ~= 1 - (1 - p)^N`.

Same configuration, same exposure levers, only the trial count changed (n=30 per
row, all `placement_failure_within_capacity`):

| Config | Targets | Trials | Plan failures | First try | Within 5 seeds |
| --- | --- | --- | --- | --- | --- |
| PT (3, 5) / NPT (8, 9) | 11-14 | 8 | 16% (n=100) | 72.0% | 100% |
| PT (3, 5) / NPT (8, 9) | 11-14 | **100** | **28/30 (93.3%)** | 0.0% | **29.2%** |
| PT (2, 3) / NPT (9, 10) | 11-13 | 8 | 1% (n=100) | 96.0% | 100% |
| PT (2, 3) / NPT (9, 10) | 11-13 | **100** | **6/30 (20%)** | 63.3% | **100%** |
| PT (3, 5) / NPT (7, 8) | 10-13 | 8 | 1.7% (n=60) | 98.3% | 100% |
| PT (3, 5) / NPT (7, 8) | 10-13 | **100** | **9/30 (30%)** | 53.3% | **99.8%** |
| recommended 30 s plan | 12-14 | **68** | **0/30** | 100% | 100% |
| option A + PT (3, 5) | 12-15 | **68** | **0/30** | 100% | 100% |
| option A + PT (3, 6) | 12-16 | **68** | **0/30** | 100% | 100% |

**The 11-14 target split is not usable in a 20 s window at 100 trials.** It looked
identical to 11-13 at 8 trials (16/100 both) and collapses to a 29% chance of ever
producing a plan when the plan is 100 trials long. Do the sweep at the plan length
you are going to run.

For the 20 s window this leaves two viable target splits at 100 trials:
**11-13** (PT 2-3 / NPT 9-10, 100% within 5 seeds) and **10-13** (PT 3-5 / NPT 7-8,
99.8%, which is the way to get PT up to 5). Compare that with the 30 s window,
where a 68-trial plan with 12-14 targets has *never* failed in 2040 simulated
trials.

### 3.4 A confound to decide about: more targets also raises target prevalence

Today: ~8 targets among ~36 images = **22% prevalence**. Raising targets to
12-14 while leaving the distractor counts alone gives 13 of ~41 = **32%**.

Target prevalence is a known driver of misses: hit rate *improves* and misses
fall as prevalence rises (Wolfe et al. 2007; Chan & Chan 2022). So raising the
target count while holding distractors fixed partly works against the intended
difficulty increase, and stacks a prevalence change on top of the exposure and
size changes — three manipulations at once.

#### The splitting arithmetic (why NPD always dominates)

`prevalence = targets / (targets + PD + NPD)`, so holding prevalence fixed while
targets rise forces **NPD up by ~3.5 per extra target** at the pilot's 22%
(`capacity_sweep.npd_for_prevalence`):

| Targets/trial | NPD needed for 22% prevalence (PD=4) | Prevalence if NPD stays at today's 24 |
| --- | --- | --- |
| 8 (today) | 24 | 22.2% |
| 11 | 35 | 28.2% |
| 12 | 38 | 30.0% |
| 13 | 42 | 31.7% |
| 14 | 45 | 33.3% |

That is the whole splitting problem in one line: more targets and the pilot's
prevalence both demand *more* NPD, and NPD is already the largest role by count
because it absorbs everything the PD cap leaves over. So NPD rising is not a
symptom of a bad split; it is what prevalence control requires.

#### But in a 20 s window you cannot have both

Targets pinned at 11-14 (PT 3-5 / NPT 8-9), 20 s content, `HARDER` levers, 8-trial
plans, n=50 per row — pushing NPD up to chase the pilot's prevalence:

| PD | NPD | Prevalence | Plan failures | First try | Within 5 seeds |
| --- | --- | --- | --- | --- | --- |
| (3, 5) | **(20, 28)** — today | 31% | **16/100** | 72.0% | 100% |
| (3, 5) | (28, 34) | 26% | **32/50** | 24.0% | 89.3% |
| (3, 5) | (34, 40) | 23% | **48/50** | 2.0% | 18.5% |
| (3, 5) | (40, 46) | 21% | **50/50** | 0.0% | 0.0% |
| (5, 7) | (34, 40) | 23% | **50/50** | 0.0% | 0.0% |

Raising PD does not rescue it either: at the same NPD (34, 40), PD (5, 7) fails
50/50, because PD is also a sound event and the sound budget is what is left.

So in a 20 s window the target count and the pilot's prevalence are in direct
conflict, and prevalence loses. With 11-13 targets the achievable prevalence is
~30%, and there is no NPD range that gets it back to 22% without killing
placement. If holding prevalence near 22% matters, it is another argument for the
30 s content window, where 12-14 targets at 22% prevalence placed 100% first try
over 68 trials.

Two clean ways out:

- **Hold prevalence constant**: with 12-14 targets, `TRIAL_NPD_RANGE = (38, 45)`
  restores ~22%. Swept above: placement is still 100% first try (64 images per
  trial, vs 36 today).
- **Say it is a manipulation**: keep distractors as they are and pre-register
  prevalence as an independent variable.

### 3.5 Levers to leave alone, and why

- `RESPONSE_WINDOW` / `LATE_WINDOW` (0.9 / 0.5 s): these define what a hit, late
  response and miss *are*, and all three screens plus `scoring.py`, the completed
  pilots and the between-trial feedback key off them. Changing them changes the
  dependent variable, not the difficulty.
- `TARGET_SPATIAL_BIAS` (0.80 to `top_right`): this looks like the study's actual
  manipulation, so do not spend it on difficulty. It is also the main reason the
  placement solver struggles past 13 targets.
- **Inter-target spacing below ~0.5 s**: two targets within 200-500 ms engage the
  attentional blink (Dux & Marois 2009). The generator already enforces
  >= `RESPONSE_WINDOW` = 0.9 s between target onsets, so nothing needs to change
  — but do not shrink the response window later without rechecking this.
- `PT_COUNT_PER_BLOCK = 2` and `TRIALS_PER_PT`: these belong to the design, not
  to difficulty, and they are also what quantizes session length (section 1.4).

---

## 4. Recommended configuration

**Option A (recommended): 30 s content window, 68 trials, 12-14 targets.**

| Constant | Today | Proposed | Why |
| --- | --- | --- | --- |
| `FADE_IN_DUR` | 0.3 | **0.15** | halves contrast-time (3.1) |
| `FADE_OUT_DUR` | 0.3 | **0.15** | ditto |
| `IMAGE_SIZE` | (150, 150) | **(100, 100)** | 44% of the area, ~3 deg (3.2) |
| `TRIAL_PT_RANGE` | (2, 3) | **(3, 4)** | repeats of the single active PT (3.3.1) |
| `TRIAL_NPT_RANGE` | (3, 8) | **(9, 10)** | drawn with replacement from the 6-item NPT pool |
| `TRIAL_NPD_RANGE` | (20, 28) | **(38, 45)** | holds prevalence at ~22% (3.4) |
| `TRIAL_CONTENT_DUR` | 20.0 | **30.0** | 13 targets at a 2.3 s cadence; placement becomes trivial |
| `TRIALS_PER_PT` | 2 | **17** | 34 trials/block, 68 total = 45.3 min |
| (new) break every N trials | - | **12** | needs an `experiment.py` change (section 2) |

Derived: `VISUAL_DURATION` 0.3 s, `TRIAL_DURATION` 34.0 s, ~884 targets and
~3978 images per session, one target every 2.3 s.

This exact configuration is verified end to end as
`pilot_45min_recommended` in `capacity_sweep.py`:

```
pilot_45min_recommended  0.30s 100px targets 12-14 content 30s trials 68 prev 22%
  fail 0.0%  first-try 100.0%  5-attempt 100.0%  attempts/plan 68.2
  visuals 64  target gap min 0.60s mean 1.65s  last onset 9.5s
```

30 seeds of the full 68-trial plan, 30 generated and validated on the first
attempt, with ~8.5 randomized placement orders per trial (today's baseline is
~2.6 per trial). The mean gap between consecutive targets is 1.65 s, so no
pair of targets sits anywhere near the 200-500 ms attentional-blink window.

**Option B (keeps the 20 s window): 100 trials, 11-13 targets.**

`TRIAL_CONTENT_DUR` stays 20.0, `TRIALS_PER_PT = 25` (50 trials/block, 100 total,
45.8 min), `TRIAL_NPD_RANGE` stays at (20, 28). With a 20 s window the distractor
count cannot scale, so prevalence rises to ~30% and has to be accepted as a
manipulation or reported. Verified at the real plan length of 100 trials (n=30):

| PT range | NPT range | Targets | Plan failures | Within 5 seeds |
| --- | --- | --- | --- | --- |
| (2, 3) | (9, 10) | 11-13 | 6/30 | **100%** |
| (3, 5) | (7, 8) | 10-13 | 9/30 | **99.8%** |

Do not use PT (3, 5) with NPT (8, 9) (11-14 targets) here, even though it tests
clean at 8 trials: at 100 trials it fails 28/30 and only 29% of participants would
get a plan at all (section 3.3.4).

Choose B if the trial is the unit of analysis and you want 50 observations per PT
per block; choose A if you want the cadence near the pilot's 2.5 s, prevalence
held at 22%, and a generator that has never failed in simulation.

**Do not ship both exposure levers at once with no psychometric check.** The
literature supports a graded duration effect but not a specific hit rate for
this task, and 300 ms may not be short enough to leave the ceiling. Treat the
first 2-4 participants of the new configuration as a calibration sample and be
ready to step exposure down (0.15 -> 0.10 -> 0.08 s fades) or size down
(100 -> 75 px) if hit rate stays above ~90%.

---

### 4.1 Optional: widen PT to 3-5

If more PT observations per session are wanted, `TRIAL_PT_RANGE = (3, 5)` is a
verified drop-in for `(3, 4)` in option A: targets become 12-15, sessions stay
45.3 min, and the cost is 36 extra sounds (~0.5 more per trial). Verified at the
real 68-trial length, not just at 8 trials — 0/30 plan failures for `(3, 5)` and
0/30 for `(3, 6)`, both 100% first try (section 3.3.4). That is 60 full plans and
~4080 trials with no placement failure, so this one does not have the 8-trial trap
that the 20 s option B had.

In the 20 s window (option B) the equivalent move is PT (3, 5) with
`TRIAL_NPT_RANGE = (7, 8)`, giving 10-13 targets, 9/30 failures at 100 trials and
99.8% within the 5-seed budget. `(8, 9)` instead of `(7, 8)` reaches 11-14 targets
but is not usable at full length (section 3.3.4). Either way the limit is the
target total, not the PT range.

### 4.2 Every tested configuration against clean-start

`clean-start` is the base branch; this work changes no config, so the first column
is exactly what the pilots ran. All values are `config.py` settings except the
derived ones marked below.

| Setting | clean-start / pilots | 20 s option B | 20 s + prevalence matched | 30 s option A (recommended) |
| --- | --- | --- | --- | --- |
| `FADE_IN_DUR` / `FADE_OUT_DUR` | 0.3 / 0.3 | **0.15 / 0.15** | 0.15 / 0.15 | **0.15 / 0.15** |
| `VISUAL_DURATION` *(derived)* | 0.6 | 0.3 | 0.3 | 0.3 |
| `PEAK_HOLD_DUR` | 0.0 | 0.0 | 0.0 | 0.0 |
| `IMAGE_SIZE` | (150, 150) | **(100, 100)** | (100, 100) | **(100, 100)** |
| `TRIAL_CONTENT_DUR` | 20.0 | 20.0 | 20.0 | **30.0** |
| `TRIAL_DURATION` *(derived)* | 24.0 | 24.0 | 24.0 | **34.0** |
| `TRIAL_PT_RANGE` | (2, 3) | **(2, 3)** or **(3, 5)** | (3, 5) | **(3, 4)** |
| `TRIAL_NPT_RANGE` | (3, 8) | **(9, 10)** or **(7, 8)** | (8, 9) | **(9, 10)** |
| `TRIAL_PD_RANGE` | (3, 5) | (3, 5) | (3, 5) or (5, 7) | (3, 5) |
| `TRIAL_NPD_RANGE` | (20, 28) | (20, 28) | (28, 34) … (40, 46) | **(38, 45)** |
| `TRIALS_PER_PT` | 2 | **25** | — | **17** |
| Trials per session | 8 | **100** | — | **68** |
| Session length | 5.9 min | **45.8 min** | — | **45.3 min** |
| Targets/trial | 5-11 | **11-13 / 10-13** | 11-14 | **12-14** |
| Distractors/trial | 23-33 | 23-33 | 43-51 | 41-50 |
| Visuals/trial *(mean)* | ~36 | ~41 | ~55-62 | ~59 |
| Target prevalence *(mean)* | 22% | **~29-30%** | 21-26% | **~22%** |
| Sounds/trial *(mean, PT+PD)* | ~6.5 | ~6.5 / ~8.0 | ~8.0 | ~7.5 |
| Plan failures at full length | **2/100** at 8 trials | **6/30** or **9/30** at 100 | **50/50** at 8 | **0/30** at 68 |
| Within 5-seed retry budget | 100% | 100% / 99.8% | 0% | 100% |

Unchanged in every option, and deliberately so: `RESPONSE_WINDOW` (0.9),
`LATE_WINDOW` (0.5), `TARGET_CORNER_HOLD` (1.4, derived), `TARGET_SPATIAL_BIAS`
(0.80), `CORNERS`, `PT_COUNT_PER_BLOCK`, `PD_COUNT_PER_BLOCK`, `TRIAL_BUFFER_DUR`
(2.0), `BREAK_OFFER_SECONDS` (30) and the SOA ranges.

## 5. How to verify

```bash
# Duration model, solver, and the cadence decision table
python session_timing.py --target-minutes 45 --cadence-table
python session_timing.py --target-minutes 45 --trials-per-block 8 16 25 34 50 --break-every 12
python session_timing.py --calibrate /path/to/data      # re-derive the screen medians

# Feasibility of every candidate configuration (100 seeds each, ~4 min)
python capacity_sweep.py --n 100
python capacity_sweep.py --n 60 --scenario content_30s_targets_12_14_dense
python capacity_sweep.py --n 30 --scenario pilot_45min_recommended
python capacity_sweep.py --list

# Unit tests
python -m pytest tests/test_session_timing.py
```

After changing `config.py`, `python capacity_sweep.py --n 100 --scenario baseline`
becomes the new control (the `baseline` row reads the shipped config), so the
same sweep re-run compares "before" and "after" without editing the tool.

---

## 6. Limits of this analysis

- **No participant simulation.** The sweep proves that *plans generate and
  validate*, and it quantifies stimulus exposure, cadence and prevalence. It
  cannot predict hit rate. Whether 0.3 s at 3 deg actually removes the ceiling is
  an empirical question and the literature does not settle it for this task.
- **Participant-paced screens** are the soft part of the duration model: the
  pilot median is 65 s of pre-task screens, but one pilot took 144 s and another
  15 s. Sessions will run long for slow readers.
- **The block transition** is modelled as one break per block plus two feedback
  screens. Real block transitions in the pilots ranged from 2.8 s (a participant
  who raced through) to 41 s.
- **The 45-minute target excludes** the preflight dialogs, the consent/setup
  conversation, and the post-session server sync (which took 3.6 minutes for
  participant_08). Add those for a lab-slot estimate.
