# Experiment Spec: Sound-Cued Attention Task (Animate vs Inanimate)

Status: draft v1. Anything marked **[CONFIG]** lives in `config.py` and must never be hard-coded elsewhere.

## 1. Overview

Within-subjects task. Each participant completes two blocks: **animals** and **objects**. In each block the participant presses a numpad key when a target-category image appears in a screen quadrant, and ignores the other category.

Hidden manipulation (participant is unaware):
- Some stimuli ("privileged") are paired with a sound that plays shortly **before** the image peaks.
- Privileged targets (PT) appear mostly in one corner (80% TR or top right), so participants may implicitly learn that location.
- Privileged distractors (PD) have sounds but no location bias.

Hypothesis (to confirm with Prof. Williams): a sound closer in time to a target's onset primes attention and speeds reaction time, and a sound-location association may be learned implicitly.

## 2. Stimulus roles

| Role | Meaning | Sound | Count per block | Location rule | SOA |
|---|---|---|---|---|---|
| PT | Privileged target (target category) | yes | 2 stimuli | 80% bias corner | one value per PT, fixed for the session |
| PD | Privileged distractor (other category) | yes | 2 stimuli | any corner | redrawn every appearance |
| NPT | Non-privileged target (target category) | no | 6 stimuli | any corner | n/a |
| NPD | Non-privileged distractor (other category) | no | 6 stimuli | any corner | n/a |

Rules:
- The pool is 10 animals + 10 objects, each with a paired WAV.
- Per participant, 8 stimuli are removed for privileged roles (4 animals + 4 objects). The other 12 are NPT/NPD.
- Block 1 and block 2 never share PT or PD stimuli.
- A block's NPT set is the other block's NPD set, and vice versa. These sets are fixed for the block and are not redrawn.
- Only PT and PD stimuli ever play sounds.

## 3. Session setup (once per participant)

1. **Seeding: not implemented for now.** Ideally we figure out a way to use participant id as a seed for placing events so auditors can verify but if csv's store event details that may be enough since auditors will be more concerned with if raw data aligns with reported results

2. Block order: ideally this would alter between participants so p1 would get animals objects p2 objects animals and so on so forth (one implementation idea would be to count participant folders in animate and compare to inanimate folder and just assign order based on which has less and if tie flip coin to choose
3. Shuffle animals and objects, then take 4 of each:
   - Animals: `[B1_PT_1, B1_PT_2, B2_PD_1, B2_PD_2]`
   - Objects: `[B1_PD_1, B1_PD_2, B2_PT_1, B2_PT_2]`
   - If objects are block 1, swap which category supplies PTs.
4. Remaining 6 animals and 6 objects become NPT/NPD per block (roles swap between blocks).
5. Draw one SOA per PT from `SOA_range` and fix it for the session. Example: cat = 0.6, dog = 1.3.
6. Write `session_config_snapshot.json` (resolved config and all drawn values) to the participant folder OR something alike this is again seeding and running notes like if we run participants based on older versions etc one idea was to use git hash for this

## 4. Timing model **[CONFIG]**

```
trial_length          = 24.0   # seconds or just make this fade in + hold dur + fade out 
buffer_before         = 2.0    # background noise only
content_window        = 20.0
buffer_after          = 2.0
fade_in               = 0.3
hold_duration         = 0.0    # kept as a variable, 0 for now
fade_out              = 0.3
sound_length          = 1.0
min_onset_gap         = 0.15   # onset-to-onset, any two stimuli
target_window_margin  = 0.15   # extra spacing between two targets' response windows
response_window_len   = 1.5    # from onset
SOA_range             = (0.5, 1.5)
PT_count_range        = (2, 3) # per trial
PD_count_range        = (2, 3) # per trial, per PD stimulus
NPT_count_range       = TBD    # per trial, total NPT slots use old av file to pull values as a starting range
NPD_count_range       = TBD    # per trial, total NPD slots
bias_corner           = TOP_RIGHT
bias_ratio            = 0.8
trials_per_block      = 6      # must be even
keys                  = {TL: 7, TR: 9, BL: 1, BR: 3}
frame_grid            = 1/120  # snap all times to this
```

Definitions (times relative to start of content window):

- `peak_start = onset + fade_in` (moment fade-in ends)
- `visual_end = onset + fade_in + hold_duration + fade_out`
- `sound_start = peak_start - SOA`
- `sound_end = sound_start + sound_length`
- `response_window = [onset, onset + response_window_len]`

Derived constraints on a legal onset:
- `sound_start >= 0`, so `onset >= SOA - fade_in`
- `sound_end <= content_window`
- `visual_end <= content_window`
- The response window may run into `buffer_after`. This is allowed because nothing else is shown there.

claude suggested using frame snapping but no idea what this is so use scrutiny but we may use 120 vs 240 hz monitors so preflight bash could just set all to 120 to keep things consistent. 

## 5. Block setup: the PT slot key

Done once per block, before any placement. The key is stored and never modified by the placer.

Example: animals block, 6 trials, PTs = cat and dog, bias corner TR.

1. **Focus order.** Build `[cat x3, dog x3]`, shuffle. Result: `[cat, cat, dog, cat, dog, dog]`.
2. **Counts.** For each trial draw once from `PT_count_range` and store:
   T1 cat 3, T2 cat 2, T3 dog 3, T4 cat 3, T5 dog 2, T6 dog 3. Cat total = 8, dog total = 8.
3. **Corner pool per PT.** For cat (8 appearances):
   - `n_bias = round(0.8 * 8) = round(6.4) = 6` go to TR.
   - The remaining 2 are split across TL, BL, BR as `floor(2/3) = 0` each.
   - Leftover 2 go to 2 randomly chosen distinct corners among TL/BL/BR, e.g. BL and TL.
   - Pool: `[TR, TR, TR, TR, TR, TR, BL, TL]`.
4. **Shuffle the pool**: `[TR, BL, TR, TR, TL, TR, TR, TR]`.
5. **Deal in trial order** (chronological over cat's focus trials only):
   - T1 (3): `[TR, BL, TR]`
   - T2 (2): `[TR, TL]`
   - T4 (3): `[TR, TR, TR]`


Rounding: round half up. Leftover corners go to a random distinct subset of the 3 non-bias corners (random distribution across them).

## 6. Per-trial event counts

For each trial, drawn once during timeline generation and then fixed:

- **PT**: count from the slot key (the trial's focus PT only).
- **PD**: for each of the 2 PDs, draw a count from `PD_count_range`. Both PDs may appear in the same trial.
- **NPT**: draw one total N from `NPT_count_range`, then fill each of the N slots by picking from the 6 NPT stimuli at random, with replacement.
- **NPD**: same, using `NPD_count_range` and the 6 NPD stimuli.
- Each PD appearance draws its own SOA from `SOA_range`.
- No effort is made to equalize how often each NPT/NPD is shown.

## 7. Placement algorithm (one trial)

Placement order: **PT, then PD, then NPT, then NPD**.

Each event has:
- a visual interval `[onset, visual_end]` in one corner
- optionally a sound interval `[sound_start, sound_end]`
- for targets, a response window

### Hard constraints
1. Visual and sound intervals lie within `[0, content_window]`.
2. Onset-to-onset gap between any two stimuli is at least `min_onset_gap`.
3. No two visual intervals overlap in the same corner.
4. No two sound intervals overlap.
5. No two targets (PT or NPT) on screen at the same time in the sense of response windows: their onsets are at least `response_window_len + target_window_margin` apart (1.65 s with defaults). This keeps each keypress unambiguous.
6. Distractors may overlap targets in time. They must only avoid sharing a corner with them at the same moment.
7. A sound may play while another image is visible.

timer should start at 0 when buffer begins so all RT and stimulu should happen after 2 seconds or decided buffer beginning amount

8. jitter logic should be ported over from old av file (will be provided in folder now titled old_av.py)

### Method
method / algo for placing stimuli TBD, maybe slot key could be used to build event key or something? ideally we plot out all events and their times before running and then cache or preload the images sounds and timing for the script itself from some csv. the reaction time could be its own seperate csv after the fact. 
I think obv stimulus categories w most constraints get placed first so maybe read from slot key and then place PD's and then place NPTs or NPDs but then why even read from PTs key when we could just keep our PT placement logic and build PD and NPTS and NPD logic after to just make event key csv? 

Im thinking place PTs, place PDs, place rest and if they cant fit just try again from PT placements or if another algo works better I am open to it. Just wanna keep things random yet deterministic


1. Read the CSV. Preload every PNG into an `ImageStim` and every WAV into a `Sound` object before the clock starts. No disk reads during trials.
2. Pre-generate a few noise backgrounds from the grey-white blob png by shuffling its pixels, and cycle through them. Do not generate per frame.
3. Each frame: compare the clock to row times, set opacity from the fade formula, trigger sounds at `sound_start`.
4. Record `win.flip()` timestamps for onset, peak, and end of each image, and the actual sound start time.
5. Log every keypress with its timestamp.
6. Fixation cross: small, white, centered. Flashes green on a hit. (this logic can also probably be ported over from old_av.py as well as the background shuffling unless theres a more optimal way to shuffle background and reduce overhead if its simple and not overengineered)

7. Sound is played equally in both ears (50/50) (this check to go in preflight) 
8. Measure and log the refresh rate and dropped frames. (maybe if this is deemed necessary)


### Scoring (done after each press and again offline)
- **Hit:** correct key for a target whose response window contains the press.
- **False alarm:** every other press (wrong key, outside any window, or pressing for a distractor).
- Reaction time is measured from the target's actual onset flip timestamp.
- Every press is logged regardless of score so anticipatory presses can be analyzed later.

## 11. Practice block

TBD. Proposal: reuse the same generator with a shorter content window, fewer trials and spare images outside the main pool.




## 12. Monte Carlo and validation (this here is more claude jumping the gun. Good stuff but I need to review this a bit more before implementing)

- `validate_timeline.py` independently re-checks every constraint in section 7 on a generated timeline. Used by the generator, the Monte Carlo script, and preflight.
- `tests/monte_carlo.py` generates thousands of timelines per config and reports:
  - first-attempt success rate and mean retries at each level
  - which role fails most often
  - content-window utilization
  - worst case (all ranges at max)
  - a sweep over `NPT_count_range` and `NPD_count_range`

## 13. Pre-flight (`preflight.sh`)

Check and report:
- X11 (Xorg) session, not Wayland
- display refresh rate (120 or 240 Hz) matches expectation
- CPU governor set to `performance`
- no heavy background processes running
- audio device present and sample rate as expected

PNG and WAV checks (non-empty pixel content, equal WAV length, similar loudness) and normalization are done outside this repo as a separate task.



## 14. Repo layout proposed by claude gimme some pros and cons of doing it this way. 

```
config.py
stimuli/                   # PNGs, WAVs, background blob likely in animate folder w inner sound and image folders same w inanimate
src/
  generate_timeline.py     # setup, slot key, placer, CSV writer
  validate_timeline.py
  run_experiment.py          this could be 
tests/
  monte_carlo.py
preflight.sh
data/<participant_id>/     #need to figure out what all to store here later. Could be organized into animals first or inanimate first folders pretty easy tho then maybe their data on rt and session info config stuff (could make their config after hitting Y at end of preflight 


README.md 
```
