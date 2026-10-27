# Changelog — av-study-rebuild review fixes

Timing is PTB software-reported only; there is no microphone, photodiode, or loopback measurement
(the metadata note "PTB software-reported timing, no physical measurement" is kept).

## Items

1. **PT SOAs hidden from participants** (`79a066e`). Verified: SOAs appear only on the operator
   debug screen and overlay (`AV_STUDY_DEBUG_OVERLAY=true`).
2. **Independent RNG streams** (`2848de7`). Verified: split/slotting and timeline use
   `derive_rng(seed, label)`.
3. **Atomic participant allocation** (`054b6fc`, fix-up `4f06373`). Temp-folder plan creation,
   up to 5 seeds retried on `PlacementFailure` (recorded in metadata), no ID consumed on failure,
   block order from `planned_block_order()`. The fix-up moved plan creation after the numpad and
   sound checks, which the original commit had not done.
4. **Server sync never overwrites** (`19c3e76`). Verified: collisions recorded as `collision`,
   local data kept, allocation consults the server.
5. **Abort handling and keypress labeling** (`db08880`). Aborted trials are saved with
   `trial_complete=False` on event, key, and trial rows; their pending targets become
   `incomplete` (not `miss`). Keys on between-trial screens are `inter_trial` with the last
   trial's block/trial. Feedback comes from in-memory rows. Scoring lives in `scoring.py`
   (tests: `tests/test_scoring.py`). The untested `wip-item5` branch was not used.
6. **Audio start time** (`cfef13a`, fix-ups `8baf8da`, `246bec4`). Reads
   `sound.track.status["StartTime"]` (the per-sound PsychPortAudio slave). Keeps the
   `>= requested - 0.05 s` check and records `audio_start_source`. Unreported sounds fall back to
   the requested time as `requested_only`, with `audio_requested_only_count` per trial. PTB to
   session time is now `reported - session_clock.getLastResetTime()`, with a startup assert that
   both clocks share the PTB time base. New columns: `realized_soa_seconds` and
   `soa_error_seconds` (tests: `tests/test_audio_ptb.py`). The operator warning is raised from
   the sound-check tone, the first sound of the session. Fix-ups: `8baf8da` restores the N key on
   the sound check, broken by the first edit; `246bec4` gives aborted trials no fallback for
   unreported sounds (flag `trial_aborted_before_audio_start_report`).
7. **Timing flags** (`e27ec5e`). `visual_onset_deviation` fires above
   `VISUAL_ONSET_FLAG_FRAMES` × measured frame period (1 frame).
   `AUDIO_ONSET_FLAG_THRESHOLD = 0.005` s. Numeric deviations are always recorded.
8. **Display validation** (`b04758f`). Raises if `window.size != config.WINDOW_SIZE`. The refresh
   rate is measured with `getActualFrameRate`, stored in metadata, and used for the long-frame
   threshold, with a warning if it differs from xrandr by more than 1 Hz. `preflight.sh` picks the
   connected primary output (else the first output with an active `*` mode), lists all connected
   outputs, and fails if the mode isn't `config.WINDOW_SIZE` (read from Python).
9. **Smaller fixes** (`38dfab2`). Visuals skipped by a stall become `not_presented` /
   `visual_stalled`, and onsets are recorded only for drawn visuals. Backgrounds are seeded from
   `derive_rng(seed, 'background')`, with the label logged. The participant ID is checked by
   equality on the parsed report. The timeline sha is checked against the one stored at
   generation (replaces the hard-coded `timeline_used_unchanged`). The preflight report is copied
   into the participant folder. The Num Lock prompt is removed.
10. **One generation path** (`befc5c1`). `participant_setup.build_plan()` is used by both
    `create_participant_plan` and `monte_carlo`. Removed `_seed_inputs` and the module CLIs. The
    runtime never calls `build_plan`. Plans are byte-identical to before for the same seeds.
11. **Single validator** (`9a57870`). `validate_timeline` is the only full rule check.
    `session_io.load_timeline` checks schema/types, assets, WAV durations, the sha, and the config
    snapshot stored in `participant_metadata.json` (it fails with the list of changed keys).
    `_audit_timeline` calls `validate_timeline`.
12. **Shared constants** (`9a57870`). Derived constants and role sets are in `config.py`;
    duplicates are deleted.
13. **Dead code** (`9a57870`). Removed `_solve_trial`, `stats['last_failure']`,
    `read_slotting_key`, `read_stimulus_assignment`, and unused imports and variables.
14. **Split `run()`** (`e5e1147` session_io, `5161545` audio_ptb, `22be35d` screens, `4d68fd6`
    trial_runner). Intended to change no behavior. No automated test covers
    experiment.py/trial_runner.py/screens.py (PsychoPy cannot be imported in tests). Behavior
    preservation of the split is unverified until the pilot.
15. **Sound pool** (`51f33e0`). Each stimulus has `SOUND_POOL_SIZE = 2` `Sound` objects, built
    before the session. `audio_ptb.assign_sound_slots` assigns them round-robin per stimulus in
    planned-onset order, so a play is never scheduled on an object that is still sounding. The
    schedule-ahead lead is `config.SOUND_SCHEDULE_LEAD = 0.5`. Timeline generation and timing
    constants are unchanged. The start-time reader and its `>= requested - 0.05 s` check still
    read the object that was played. Tests (`tests/test_sound_pool.py`) cover 50 `build_plan`
    seeds: with the pool, every play is scheduled at least 0.05 s after the previous play on the
    same object ended. With `pool_size=1`, or with a mutated assignment, the check fails.
16. **Remote session metadata** (`3ccbdda`). `sync_participant` rewrites the server
    `session_metadata.json` only if it has the same `started_utc` and `seed` (or is absent).
    Otherwise it is preserved and the sync status becomes `collision`.
17. **Operator warnings** (`caa16ce`). `session_io.operator_warn(pid_dir, message)` prints and
    appends to `data/<pid>/operator_warnings.txt`. It is used only for anomalies: refresh-rate
    mismatch, missing sound-check audio start time, and server sync `partial`, `failed`, or
    `collision`. Local-only storage stays a plain print (status `local_only`). The
    refresh-mismatch and sound-check warnings are emitted right after plan creation, because the
    participant folder does not exist before then. After the runner exits, preflight.sh shows a
    non-empty warnings file in a zenity dialog and keeps the runner log
    (`data/<pid>/runner.log` on success, `launch_error.log` on failure as before).
18. **NumPy metadata is JSON-safe**. PsychoPy comparisons and clock/refresh values that
    land in metadata or event/trial/key rows are stored as Python `bool`/`float`/`int`.
    `session_io.json_default` converts NumPy bool, integer, floating, and ndarray values in
    session and participant metadata writes. CSV cells coerce NumPy scalars to Python values.

## Behavior changes
- New columns: `trial_complete` (event, key, and trial rows); `realized_soa_seconds` and
  `soa_error_seconds` (event rows); `audio_requested_only_count` (trial rows); `sound_slot`
  (sound rows).
- New values: response status `incomplete`, `not_presented`; key classification `inter_trial`;
  audio source `requested_only`; flags `visual_stalled`, `audio_start_unreported`,
  `trial_aborted_before_audio_start_report`.
- `visual_onset_deviation` now flags only deviations above one frame.
- Miss counts, the completion-screen false-alarm total, and `trial_summary` count complete
  trials only.
- Screen order is now: numpad check → sound check → plan creation → debug screen →
  instructions.
- A changed `config.py` after plan generation now stops the session.
- preflight.sh: no Num Lock prompt; fails on a wrong display mode.

## Verify in pilot
- PTB start time path: `sound.track.status["StartTime"]` is non-zero after a scheduled play on
  the lab machine, and `audio_start_source` is set in `session_metadata.json`. This was checked on
  PsychoPy 2026.2.2 here, not on the lab audio device.
- The startup clock assert (PTB vs session clock offset < 5 ms) passes.
- The `window.size` check passes on the lab display, and `getActualFrameRate` returns a value
  close to xrandr.
- Screen order: numpad check → sound check → plan → debug screen (debug only) → instructions.
- In a real `event_log.csv`, `audio_backend_start_ptb_time`, `audio_backend_start_session_time`,
  and `realized_soa_seconds` are populated, and `requested_only` is rare or absent.
- preflight.sh selects the correct xrandr output on the lab machine's multi-monitor setup.
- Operator warnings (refresh mismatch, missing sound-check start time) appear in the
  post-run warnings dialog.
- In a real `event_log.csv`, consecutive plays of the same stimulus use different `sound_slot`
  values, and every sound row has an audio start time.
- Item 14 split: run one normal full session and one session aborted with ESC mid-trial. Compare
  the `event_log.csv` columns and the `trial_complete` values against this changelog.

## Timing optimization pass (planned vs actual onset alignment)

Baseline across 9 pilot sessions (1604 visuals): visual `onset_deviation` mean +8.8 ms, median
+7.5 ms (frame quantization plus an early-biased flip predictor); sound deviation 0.00 ms;
`soa_error_seconds` inherited the visual bias (mean +8.3 ms).

- Visual onsets now snap to the frame **nearest** the planned time instead of the first frame at
  or after it. The decision uses the measured previous flip (`planned <= last_flip + 1.5 *
  frame_period`) with a `getFutureFlipTime` fallback for stall recovery, so a biased predictor
  cannot shift onsets (tests: `tests/test_trial_runner.py`). Expected: deviation within ±½ frame,
  zero mean.
- The fade ramp is anchored to the recorded onset frame, so `realized_soa_seconds` shares its
  reference with the displayed opacity. Opacity stays deterministic from onset (metadata
  `visual_fade_profile`), not logged per frame.
- All sounds of a trial are requested at trial start with absolute PTB times
  (`play(when=...)`), and a pooled object is re-requested only after its previous play ended
  plus `config.SOUND_POOL_RESTART_MARGIN`. A late request uses
  `config.SOUND_REQUEST_MIN_LEAD = 0.01` (was a 0.03 s pad inside a 0.5 s scheduling window)
  and keeps the `audio_schedule_late` flag. `SOUND_SCHEDULE_LEAD` is replaced by
  `SOUND_REQUEST_LEAD`, the pool sizing contract checked in `tests/test_sound_pool.py`.
- An aborted trial cancels plays that were requested but not started, so early requests cannot
  sound during later screens.
- Verify in pilot: visual `onset_deviation` mean near 0 (was +8.8 ms), exact
  `audio_backend_start_*` values, zero-mean `soa_error_seconds`, and no `audio_schedule_late`
  flags in a clean session.

## Known issues (not fixed, need a decision)
- None.

## 2026-10-20 pilot-prep changes

- **Non-response keys are no longer false alarms** (`scoring.classify_press`). A key with no
  response corner (SPACE, letters, modifiers) returns classification `ignored_key`, is logged, and
  is never counted as a false alarm. New classification value: `ignored_key`. Pressing SPACE during
  a trial used to score a false alarm, while practice ignored the same key.
- **Participants are told the rules they are scored by** (`screens.scoring_rules`). A new screen
  between the instructions and practice defines hit, late, miss and false alarm, with the window
  numbers read from `config`. This closes the gap where the between-trial screen reported a "late"
  count for a category nobody had defined. `INSTRUCTIONS_BOTTOM` now says "gain a miss or a late
  response; the next screen explains the difference", and its last line is "Press SPACE to
  continue." One extra screen: instructions → scoring rules → practice.
- **Practice is saved, including when it is skipped or aborted** (`practice.run` now returns
  `{'status', 'rows', 'summary'}`). Rows are written to `practice_log.csv`: `session_NN/practice_log.csv`
  when a session starts, and `data/<pid>/practice_log.csv` if the run aborts during practice, where
  no session folder exists yet. A skipped practice leaves one row with classification `skipped`.
  `session_metadata.json` `practice` is now a dict of counts instead of a status string.
- **The break counts down and its real duration is recorded** (`screens.rest_break`, new
  `config.BREAK_OFFER_SECONDS = 30`). The screen continues on its own at zero, SPACE ends it early,
  ESCAPE aborts. `session_metadata.json` now has `breaks: [{break_number, after_block,
  offer_seconds, elapsed_seconds, ended_early, outcome}]`. `break_skip_info` is gone; its
  `break_was_skipped` could never be true and `break_offer_seconds: 30` was recorded for a screen
  that was not timed.
- **Per-trial stats are persisted** as `session_NN/trial_log.csv` (`session_io.TRIAL_LOG_FIELDS`):
  frame count, long-frame count, mean/median/max frame interval, miss and late counts, trial start
  and end, `trial_complete`, `audio_requested_only_count`. These were computed by `run_trial` but
  only ever reduced to session totals in `metadata['trial_summary']`, so per-trial frame health and
  error clustering could not be audited after a session.
- **Existing plans are refused after this change**, because `config.BREAK_OFFER_SECONDS` is part of
  the config snapshot compared by `load_timeline`. `data/participant_01` can no longer be replayed;
  new participants generate new plans.
- Test that re-validated `data/participant_01/timeline_key.csv` against a hard-coded earlier seed
  replaced with a violating timeline the test builds itself, so it no longer depends on whichever
  plan happens to be in `data/`.

### Verify in pilot
- SPACE pressed inside a trial appears in `event_log.csv` as `ignored_key` and adds nothing to the
  false-alarm count on the between-trial or completion screen.
- The scoring-rules screen fits on the display without clipping and reads clearly at 24 px.
- The break countdown reaches 0 and continues without a keypress; `breaks[0].elapsed_seconds`
  matches wall-clock time, and `ended_early` is true when a participant presses SPACE early.
- `practice_log.csv` exists in the session folder, and a skipped practice leaves the single
  `skipped` row.
- `trial_log.csv` has one row per completed or aborted trial and its `miss_count`/`late_count` sum
  to the same totals as `trial_summary`.

## 2026-10-27 participant wording changes

- **The pre-task text is paged, one idea per SPACE press.** `screens.INSTRUCTION_PAGES` replaces
  `INSTRUCTIONS_TOP`/`INSTRUCTIONS_BOTTOM` (the two blocks were shown together on one page: 165
  words, 24 lines) and `screens.SCORING_PAGES` replaces `SCORING_RULES` (98 words). The new
  `screens._pages` helper draws each page and waits for SPACE; ESCAPE still aborts on any page. The
  pages are 44/47/69 and 45/57 words, so no page carries a wall of text. The `IE if your target is
  animals…` sentence is reworded, and the scoring page indentation is gone.
- **The hand-placement screen shows the real hand position** (`screens.HAND_PHOTO_NAME`,
  `Example Hand Placement Photo.jpg`). The photo sits in the left column under the caption and the
  finger diagram stays on the right as the labelled key reference. Dropped from the text to make
  room: "Reach up for the top number or down for the bottom number in each pair", the "so you can
  respond quickly" clause, and the `IE …` sentence.
- **The block intro names the target group** (`screens.BLOCK_TARGET_PHRASE`, derived from
  `config.BLOCK_LABELS`): "when you see any animal" / "any object" replaces "when you see one".
  It is deliberately not a config constant, because a new config value would change the config
  snapshot and refuse every existing participant plan (`session_io.load_timeline`). Verified:
  `data/participant_08/timeline_key.csv` still loads.
- **The between-trial recap and the practice summary share one wording**
  (`scoring.trial_recap_lines`), reporting what the participant did in their own words instead of a
  bare counter table: hits out of the trial's targets, too slow, missed the window, wrong time or
  corner. Counts pluralize and zero counts still show. The practice summary keeps the "real task is
  the same…" paragraph.
- **The block intro and the trial recap are built by `screens.block_intro_message` and
  `screens.trial_recap_message`** instead of inline in `experiment.py`, so the two pages that used
  to be assembled in the runner are now pinned by tests like every other screen.
- **No data-format or timing change.** No CSV column, metadata field, scoring rule or window was
  touched; only participant-facing text and the screen flow for reading it.
- New dev tools: `tools/participant_text_inventory.py` (word counts per screen string) and
  `tools/render_screen_mock.py` (draws the static screens to HTML with fake PsychoPy objects, no
  display or PsychoPy needed). `PARTICIPANT_TEXT_AUDIT.md` maps every screen, the wording, and the
  before/after word counts.

### Verify in pilot
- Every instruction and scoring page is fully readable at 26 px with no clipping, and each waits for
  SPACE before advancing; ESCAPE aborts from any page.
- The hand-placement screen shows the photo, the caption and the diagram with no overlap, and the
  participant's hand is on the number pad with a finger free for the space bar.
- The block intro reads "any animal" in the animals block and "any object" in the objects block.
- The recap after a trial lists all four counts with the trial's own numbers, and the practice
  summary shows the same four lines for the practice round.

## 2026-10-27 practice difficulty tiers

- **Practice runs three paced rounds after the coached steps: easy → medium → hard**, each behind
  its own hold screen, then a summary that breaks the counts down per round. Easy is the previous
  single round, unchanged (`PACED` → `EASY`).
- **Difficulty is density and overlap, never the response window.** `RESPONSE_WINDOW` (0.9 s) is the
  same in all three rounds and the same as the real task. Only *targets* are forbidden from sharing
  a decision window: target onsets stay at least `RESPONSE_WINDOW` apart, exactly as
  `timeline_key` enforces, while distractor onsets are free down to
  `MIN_VISUAL_ONSET_GAP` (0.15 s), so squares crowd circles and each other. One measurement script
  over the delivered scripts and all 11 published plans (88 real trials), span = first onset to the
  last shape disappearing:

  | round | items | targets | span | items/s | most on screen | gaps < 0.6 s | other onsets inside a target window | items per corner |
  | --- | --- | --- | --- | --- | --- | --- | --- | --- |
  | easy | 5 | 3 | 7.00 s | 0.71 | 1 | 0% | 0.00 | 1/1/1/2 |
  | medium | 12 | 4 | 8.30 s | 1.45 | 2 | 27% | 0.75 | 3/3/3/3 |
  | hard | 20 | 4 | 12.36 s | 1.62 | 3 | 42% | 1.25 | 5/5/5/5 |
  | *real trials (median)* | *36* (30–42) | *8* (5–11) | *18.5 s* | *1.98* | *3, up to 4* | *58%* | *1.16* | *even* |

  The pile-up, not the rate, was what was missing: the previous hard round never put more than two
  shapes on screen, while every real trial reaches three and some reach four. The hard round now
  sits at 1.62 items/s against the real median 1.98, and matches the real count of other onsets
  inside a target's window (1.25 against 1.16).
- **The hard round is a real trial's own picture stream, cut to its first 12 s.** The onsets are a
  generated schedule, chosen as the densest-sharing 12 s slice on the server (20 items, 8 "crowded"
  gaps, 1.25 other onsets per target window). It is frozen as constants, so it is identical for
  every participant and carries no runtime dependency on the plan it came from. Only the corners are
  repacked: **real trials put 79.3% of targets in `FAVORED_CORNER`** (`TARGET_SPATIAL_BIAS = 0.80`;
  distractors are spread evenly), which would leave keys 1, 2 and 4 barely trained, so the targets
  sit one to a corner and the distractors spread 5/5/5/5. Worth confirming that bias is intended.
- **Practice draws the real background noise.** `practice.run` now takes the `backgrounds` list
  `experiment.py` already builds, and draws it on every frame of the coached steps and the rounds,
  rotated at `BG_UPDATE_RATE` exactly as `run_trial` does. Practice previously drew white shapes on
  black, which is a large part of why it looked and read easier than the task.
- **Shapes are grey (`SHAPE_COLOR = '#B4B4B4'`), not white.** A solid white square reads far heavier
  than a grayscale stimulus photo, and it is 27% more area than a circle of the same box. The value
  must not be the colour name `'gray'`: PsychoPy resolves that to rgb 0.0039, essentially black.
  Sizes are unchanged (`config.IMAGE_SIZE`), and each shape still sits at a fixed per-event offset
  inside its quadrant, distinct within each corner.
- **`practice_log.csv` has a `tier` column** (`session_io.PRACTICE_LOG_FIELDS`, after `phase`), and
  paced `event_id`s are prefixed per round (`easy-0` … `hard-19`) so ids stay unique. Logs written
  before this change still parse; the new column comes out blank.
- **`session_metadata.json` `practice`** keeps its totals (`paced_hits`, `paced_late`,
  `paced_misses`, `paced_false_alarms`, summed over the three rounds) and gains `tiers` (one entry
  per round: counts, event count, duration, outcome) and `skipped_at_tier`.
- **The operator's `s` ends practice at any round change**, not only on the intro screen: rows
  collected so far are kept, status is `skipped`, and `skipped_at_tier` names the round that did not
  run. `s` is still not advertised to participants.
- **No new `config.py` constant**, so the config snapshot is unchanged and existing participant
  plans still load. Practice is not part of the timeline.
- Practice is longer: 34.6 s end to end with a scripted participant, against 28.9 s for the
  committed version (same harness, so the two are comparable). The 27.7 s of visual stream is
  carried by 5 + 12 + 20 = 37 items against 5 + 9 + 18 = 32 before, plus three participant-paced
  hold screens.
- Practice is still silent. The real trials carry 46–55 sounds per plan; adding them to practice is
  a separate change.

### Verify in pilot
- All three rounds run in order after the coached steps, each starting on SPACE, over the blob
  background: one shape at a time, then two, then the three-deep pile-up.
- The grey shapes are clearly visible against the noise field but no longer glare white; confirm on
  the rig and adjust `practice.SHAPE_COLOR` if they are too dim or too bright.
- `practice_log.csv` has one `tier` per round with unique `event_id`s, and its per-round counts
  match `session_metadata.json practice.tiers` and the per-round lines on the final screen.
- Pressing `s` on a round hold ends practice with `status: skipped`, `skipped_at_tier` set to the
  round that did not run, and the coached rows still saved.
- Whether hard is now hard enough: compare the participant's hard-round misses against their first
  real trial, which is the closest thing to a like-for-like comparison.
- PsychoPy is not installed on the machine used for this change, so the rounds were verified through
  the fake-clock tests in `tests/test_practice.py` (including that the background is drawn every
  frame), not at the console.

## 2026-10-27 session-length and task-difficulty planning (analysis only, no runtime change)

No participant-facing behavior changed: `config.py`, `experiment.py`, `trial_runner.py`,
`screens.py`, `scoring.py` and `timeline_key.py` are untouched. The plan and its numbers are in
`TASK_DIFFICULTY_PLAN.md`.

- **`session_timing.py`** models participant-facing session length from the config constants plus
  the pilot medians for the participant-paced screens (65 s pre-task, 29 s practice, 2.0 s per
  feedback screen), solves trials per block for a target duration, and prints the
  targets-per-trial x target-cadence decision table. `--calibrate DIR` recomputes those medians
  from `preflight_report.txt`, `session_metadata.json` and `trial_log.csv`. Validated against the
  three completed pilot sessions: within 10% for participants who read the screens, over-predicts
  for a participant who pressed SPACE immediately.
- **Findings**: the current session is 5.9 min; 45 min needs 96-100 trials at the present 24 s
  trial, or 64-68 trials once the content window is 30 s. Trials per block is a multiple of
  `PT_COUNT_PER_BLOCK`, so session length is quantized in 104 s steps at a 24 s trial.
- **`capacity_sweep.py`** runs the real generation path over scenarios that each state the full
  config they test, in a separate interpreter because `timeline_key` binds config values at import
  time. It reports success rate, first-attempt rate, the 5-seed retry budget that
  `create_participant_plan` actually has, placement orders per plan, and target prevalence.
- **Findings**: with the 20 s content window, 11-13 targets per trial place 96% first try and
  14-16 fail almost always (`placement_failure_within_capacity`, `RESPONSE_WINDOW` plus the 1.4 s
  same-corner hold and `TARGET_SPATIAL_BIAS`). With a 30 s content window, 12-14 through 18-20
  targets all place 100% first try, including the full 68-trial 45-minute plan with
  prevalence-matched distractors. Raising the target count without raising the distractor count
  also raises target prevalence from 22% to 32%, which on its own reduces misses.
- **`tests/test_session_timing.py`** covers the model arithmetic, the solver and its quantization,
  the cadence table, prevalence, scenario completeness, and pilot calibration on a synthetic
  session folder.
