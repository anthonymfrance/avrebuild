"""PTB software audio timestamps and realized SOA (no PsychoPy imports).

All audio times are PTB software-reported; nothing here is a physical measurement.
"""

from __future__ import annotations

# psychopy.sound.backend_ptb.SoundPTB.track is a psychtoolbox.audio.Slave whose
# .status is PsychPortAudio('GetStatus') for that sound alone. SoundPTB.status
# is a PsychoPy state constant and SoundPTB.stream is the shared master stream.
AUDIO_START_SOURCE = 'sound.track.status["StartTime"]'
START_TOLERANCE = 0.05


def backend_start_time(sound_obj, requested_ptb):
    """Return this play's reported PTB start time, or None if not (yet) reported.

    A cached Sound keeps the StartTime of its previous play, so values earlier
    than the requested time (minus START_TOLERANCE) are rejected.
    """
    try:
        status = sound_obj.track.status
    except Exception:
        return None
    if not isinstance(status, dict):
        return None
    value = status.get('StartTime')
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    if value < requested_ptb - START_TOLERANCE:
        return None
    return float(value)


def ptb_to_session(ptb_time, session_reset_ptb):
    """Convert a PTB GetSecs time to the session clock (Clock.getLastResetTime base)."""
    return ptb_time - session_reset_ptb


def resolve_trial_audio(trial_events, fade_in):
    """Finish audio timing for one trial in place; return the requested-only sound count.

    Scheduled sounds without a backend start fall back to the requested time
    (audio_timing_source='requested_only'). Each presented PT/PD visual gets
    realized_soa_seconds (visual onset + fade_in - audio onset, best available
    audio time) and soa_error_seconds (realized - planned).
    """
    visuals = {row['event_id']: row for row in trial_events if row['event_type'] == 'visual'}
    requested_only = 0
    for sound in trial_events:
        if sound['event_type'] != 'sound' or sound['audio_requested_session_time'] in ('', None):
            continue
        if sound['audio_backend_start_session_time'] in ('', None):
            requested_only += 1
            sound['audio_timing_source'] = 'requested_only'
            sound['timing_flags'] = ';'.join(filter(None, [sound['timing_flags'], 'audio_start_unreported']))
            audio_onset = float(sound['audio_requested_session_time'])
        else:
            audio_onset = float(sound['audio_backend_start_session_time'])
        visual = visuals.get(sound['source_event_id'])
        if visual is None or visual['_actual_onset'] is None:
            continue
        realized = visual['_actual_onset'] + fade_in - audio_onset
        visual['realized_soa_seconds'] = realized
        visual['soa_error_seconds'] = realized - float(sound['soa'])
    return requested_only
