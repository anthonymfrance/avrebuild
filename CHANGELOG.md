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
