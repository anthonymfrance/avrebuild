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

## Known issues (not fixed, need a decision)
- None.
