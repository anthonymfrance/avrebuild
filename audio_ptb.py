"""PTB audio: speaker setup, software start timestamps, realized SOA.

No PsychoPy/psychtoolbox imports at module level; PTB modules are passed in.

All audio times are PTB software-reported; nothing here is a physical measurement.
"""

from __future__ import annotations

import config

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


def resolve_trial_audio(trial_events, fade_in, complete=True):
    """Finish audio timing for one trial in place; return the requested-only sound count.

    Scheduled sounds without a backend start fall back to the requested time
    (audio_timing_source='requested_only'). Each presented PT/PD visual gets
    realized_soa_seconds (visual onset + fade_in - audio onset, best available
    audio time) and soa_error_seconds (realized - planned). In an aborted trial
    an unreported sound may simply not have started yet, so it gets no fallback.
    """
    visuals = {row['event_id']: row for row in trial_events if row['event_type'] == 'visual'}
    requested_only = 0
    for sound in trial_events:
        if sound['event_type'] != 'sound' or sound['audio_requested_session_time'] in ('', None):
            continue
        if sound['audio_backend_start_session_time'] in ('', None) and not complete:
            sound['timing_flags'] = ';'.join(filter(None, [
                sound['timing_flags'], 'trial_aborted_before_audio_start_report',
            ]))
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


def _patch_ptb_output_channels(ptb_audio, target_channels=2):
    """Limit virtual PortAudio device profiles to the study's stereo output."""
    original_get_devices = ptb_audio.get_devices
    if getattr(original_get_devices, '_av_study_patched', False):
        return

    def get_devices_with_stereo_limit(*args, **kwargs):
        profiles = original_get_devices(*args, **kwargs)
        for profile in profiles:
            try:
                output_channels = int(profile.get('NrOutputChannels', 0))
            except (TypeError, ValueError):
                continue
            if output_channels > target_channels:
                profile['NrOutputChannels'] = float(target_channels)
        return profiles

    get_devices_with_stereo_limit._av_study_patched = True
    ptb_audio.get_devices = get_devices_with_stereo_limit


def _patch_ptb_scalar_latency_argument(ptb_audio):
    """Adapt PsychoPy's one-item latency list to this PTB binding's scalar API."""
    original_stream = ptb_audio.Stream
    if getattr(original_stream, '_av_study_scalar_latency', False):
        return

    def stream_with_scalar_latency(*args, **kwargs):
        if 'latency_class' in kwargs:
            latency = kwargs['latency_class']
            if isinstance(latency, (list, tuple)) and len(latency) == 1:
                kwargs['latency_class'] = latency[0]
        elif len(args) >= 3:
            latency = args[2]
            if isinstance(latency, (list, tuple)) and len(latency) == 1:
                args = (*args[:2], latency[0], *args[3:])
        return original_stream(*args, **kwargs)

    stream_with_scalar_latency._av_study_scalar_latency = True
    ptb_audio.Stream = stream_with_scalar_latency


def open_ptb_speaker(ptb_audio, speaker_device_class):
    """Open one explicit stereo-capable PTB speaker for the full session."""
    _patch_ptb_output_channels(ptb_audio)
    _patch_ptb_scalar_latency_argument(ptb_audio)
    profiles = ptb_audio.get_devices()
    outputs = [
        profile for profile in profiles
        if int(profile.get('NrOutputChannels', 0)) >= 2
    ]
    if not outputs:
        raise RuntimeError(
            'PTB found no stereo output devices. Device profiles: '
            f'{profiles!r}. Check the Linux audio server and output device.'
        )

    requested = config.AUDIO_SPEAKER
    if requested in {'', 'default', 'None'} and config.AUDIO_DEVICE not in {'', 'default', 'None'}:
        requested = config.AUDIO_DEVICE
    if requested in {'', 'default', 'None'}:
        def default_route_rank(profile):
            name = str(profile.get('DeviceName', '')).lower()
            host_api = str(profile.get('HostAudioAPIName', '')).lower()
            if 'jack' in host_api:
                if 'built-in audio analog stereo' in name:
                    return 0
                if 'built-in audio' in name:
                    return 1
                return 2
            if 'pipewire' in name:
                return 3
            if 'pulse' in name:
                return 4
            if name in {'default', 'sysdefault'}:
                return 5 if name == 'default' else 6
            return 7

        chosen = min(outputs, key=default_route_rank)
    else:
        chosen = next(
            (profile for profile in outputs if profile.get('DeviceName') == requested),
            None,
        )
        if chosen is None:
            available = [profile.get('DeviceName') for profile in outputs]
            raise RuntimeError(
                f'Configured PTB speaker {requested!r} is unavailable. '
                f'Stereo output devices: {available!r}.'
            )

    try:
        speaker = speaker_device_class(
            index=int(chosen['DeviceIndex']), latencyClass=config.AUDIO_LATENCY_MODE,
        )
    except Exception as exc:
        raise RuntimeError(
            f"PTB could not open '{chosen.get('DeviceName')}' "
            f"(index {chosen.get('DeviceIndex')}, channels "
            f"{chosen.get('NrOutputChannels')}, host API "
            f"{chosen.get('HostAudioAPIName')}, rate "
            f"{chosen.get('DefaultSampleRate')} Hz): {type(exc).__name__}: {exc}. "
            f'Available output profiles: {outputs!r}'
        ) from exc
    return speaker, chosen
