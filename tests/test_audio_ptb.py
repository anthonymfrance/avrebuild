from types import SimpleNamespace

import pytest

import audio_ptb
from audio_ptb import backend_start_time, open_ptb_speaker, ptb_to_session, resolve_trial_audio


def sound_with_status(status):
    return SimpleNamespace(track=SimpleNamespace(status=status))


def test_reads_start_time_from_track_status():
    assert backend_start_time(sound_with_status({'StartTime': 100.02}), 100.0) == 100.02


def test_rejects_stale_start_from_previous_play():
    assert backend_start_time(sound_with_status({'StartTime': 90.0}), 100.0) is None


def test_accepts_small_early_report_within_tolerance():
    assert backend_start_time(sound_with_status({'StartTime': 99.97}), 100.0) == 99.97


def test_missing_or_unstarted_status_is_none():
    assert backend_start_time(sound_with_status({'StartTime': 0.0}), 100.0) is None
    assert backend_start_time(sound_with_status({'StartTime': 0.0}), 0.0) is None
    assert backend_start_time(sound_with_status(-1), 100.0) is None
    assert backend_start_time(SimpleNamespace(track=None), 100.0) is None


def test_ptb_to_session():
    assert ptb_to_session(1005.25, 1000.0) == 5.25


def trial(backend_session_time):
    visual = {'event_id': 'v1', 'event_type': 'visual', '_actual_onset': 10.0}
    sound = {
        'event_id': 'v1_sound', 'event_type': 'sound', 'source_event_id': 'v1', 'soa': 1.0,
        'audio_requested_session_time': 9.30, 'audio_backend_start_session_time': backend_session_time,
        'audio_timing_source': 'PTB scheduled playback', 'timing_flags': '',
    }
    return [visual, sound]


def test_realized_soa_uses_backend_start():
    events = trial(9.28)
    assert resolve_trial_audio(events, fade_in=0.3) == 0
    visual = events[0]
    assert visual['realized_soa_seconds'] == pytest.approx(10.0 + 0.3 - 9.28)
    assert visual['soa_error_seconds'] == pytest.approx(10.3 - 9.28 - 1.0)
    assert events[1]['audio_timing_source'] == 'PTB scheduled playback'


def test_requested_only_fallback():
    events = trial('')
    assert resolve_trial_audio(events, fade_in=0.3) == 1
    assert events[1]['audio_timing_source'] == 'requested_only'
    assert 'audio_start_unreported' in events[1]['timing_flags']
    assert events[0]['realized_soa_seconds'] == pytest.approx(10.3 - 9.30)


def test_aborted_trial_unreported_sound_is_not_requested_only():
    events = trial('')
    assert resolve_trial_audio(events, fade_in=0.3, complete=False) == 0
    assert events[1]['audio_timing_source'] == 'PTB scheduled playback'
    assert 'trial_aborted_before_audio_start_report' in events[1]['timing_flags']
    assert 'realized_soa_seconds' not in events[0]


class FakePTB:
    """Minimal PTB audio module; the selection patches replace get_devices/Stream."""

    def __init__(self, devices):
        self.devices = [dict(device) for device in devices]

    def get_devices(self, *args, **kwargs):
        return [dict(device) for device in self.devices]

    def Stream(self, *args, **kwargs):
        raise AssertionError('Device selection must not open a stream')


class FakeSpeaker:
    def __init__(self, index=None, latencyClass=None):
        self.index = index
        self.latency_class = latencyClass


JACK = 'JACK Audio Connection Kit'
DEVICES = [
    {'DeviceName': 'Built-in Audio Analog Stereo', 'HostAudioAPIName': JACK,
     'NrOutputChannels': 2, 'DeviceIndex': 1},
    {'DeviceName': 'Built-in Audio Digital Stereo (IEC958)', 'HostAudioAPIName': JACK,
     'NrOutputChannels': 2, 'DeviceIndex': 9},
    {'DeviceName': 'iFi USB Audio SE UAC1 Digital Stereo (IEC958)', 'HostAudioAPIName': JACK,
     'NrOutputChannels': 2, 'DeviceIndex': 7},
]


def test_opens_the_exported_default_device_not_the_built_in_one(monkeypatch):
    """preflight exports the validated sink; the old ranking chose built-in audio."""
    monkeypatch.setenv('AV_STUDY_AUDIO_DEVICE', 'iFi USB Audio SE UAC1 Digital Stereo (IEC958)')
    speaker, chosen = open_ptb_speaker(FakePTB(DEVICES), FakeSpeaker)
    assert chosen['DeviceName'].startswith('iFi')
    assert chosen['DeviceIndex'] == 7
    assert speaker.index == 7


def test_follows_the_pipewire_default_when_preflight_did_not_export_it(monkeypatch):
    monkeypatch.delenv('AV_STUDY_AUDIO_DEVICE', raising=False)
    monkeypatch.setattr(
        audio_ptb, '_default_sink_description',
        lambda: 'iFi USB Audio SE UAC1 Digital Stereo (IEC958)',
    )
    _, chosen = open_ptb_speaker(FakePTB(DEVICES), FakeSpeaker)
    assert chosen['DeviceName'].startswith('iFi')


def test_unavailable_expected_device_is_an_error(monkeypatch):
    monkeypatch.setenv('AV_STUDY_AUDIO_DEVICE', 'No Such DAC')
    with pytest.raises(RuntimeError, match='not a PTB stereo device'):
        open_ptb_speaker(FakePTB(DEVICES), FakeSpeaker)


def test_no_resolvable_default_keeps_the_built_in_preference(monkeypatch):
    """A bare ALSA machine with no pactl still opens a sane device."""
    monkeypatch.delenv('AV_STUDY_AUDIO_DEVICE', raising=False)
    monkeypatch.setattr(audio_ptb, '_default_sink_description', lambda: '')
    _, chosen = open_ptb_speaker(FakePTB(DEVICES), FakeSpeaker)
    assert chosen['DeviceName'] == 'Built-in Audio Analog Stereo'


def test_unpresented_visual_or_unscheduled_sound_has_no_soa():
    events = trial(9.28)
    events[0]['_actual_onset'] = None
    resolve_trial_audio(events, fade_in=0.3)
    assert 'realized_soa_seconds' not in events[0]
    events = trial('')
    events[1]['audio_requested_session_time'] = ''
    assert resolve_trial_audio(events, fade_in=0.3) == 0
    assert 'realized_soa_seconds' not in events[0]
