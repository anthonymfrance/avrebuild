"""run_trial timing tests against fake window/clock/sound objects.

The fakes put every flip on a perfect frame grid and report PTB start times
exactly, so planned-vs-actual behavior can be asserted in milliseconds.
"""

from types import SimpleNamespace

import pytest

import config
import trial_runner
from trial_runner import planned_image_alpha

FRAME_PERIOD = 1.0 / 120.0
RESET = 1000.0  # session_clock.getLastResetTime(): PTB time = session time + RESET


class FakeClock:
    def __init__(self, reset_time):
        self.now = 0.0
        self.reset_time = reset_time

    def getTime(self):
        return self.now

    def getLastResetTime(self):
        return self.reset_time


class FakeWindow:
    """Flips land exactly on the frame grid; the flip predictor can be biased
    (predict_bias > 0 reports the next flip earlier than it will land)."""

    def __init__(self, clock, frame_period, predict_bias=0.0):
        self.clock = clock
        self.frame_period = frame_period
        self.predict_bias = predict_bias
        self.next_flip = 0.0

    def getFutureFlipTime(self, clock=None):
        return self.next_flip - self.predict_bias

    def flip(self):
        timestamp = self.next_flip
        self.clock.now = timestamp
        self.next_flip += self.frame_period
        return timestamp


class FakeKeyboard:
    def __init__(self, clock, escape_at=None):
        self.clock = clock
        self.escape_at = escape_at
        self.fired = False

    def getKeys(self, waitRelease=False, clear=True):
        if (self.escape_at is not None and not self.fired
                and bool(self.clock.now >= self.escape_at)):
            self.fired = True
            return [SimpleNamespace(name='escape', rt=self.escape_at)]
        return []


class FakeTrack:
    def __init__(self, sound):
        self.sound = sound

    @property
    def status(self):
        plays = self.sound.plays
        if plays and bool(self.sound.clock.now >= plays[-1][1] - RESET):
            return {'StartTime': plays[-1][1]}
        return {'StartTime': 0.0}


class FakeSound:
    def __init__(self, clock):
        self.clock = clock
        self.plays = []  # (session call time, requested PTB time)
        self.stopped = False
        self.track = FakeTrack(self)

    def play(self, when=None):
        self.plays.append((self.clock.now, when))

    def stop(self):
        self.stopped = True


class FakeStim:
    def __init__(self):
        self.pos = (0.0, 0.0)
        self.opacity = 1.0
        self.lineColor = 'white'
        self.draws = []

    def draw(self):
        self.draws.append(self.opacity)


def visual_event(event_id, onset, stimulus='img', role='NPD'):
    return {
        'event_id': event_id, 'event_type': 'visual', 'role': role,
        'stimulus': stimulus, 'trial_onset': onset, 'x': 1.0, 'y': 2.0,
    }


def sound_event(event_id, onset, stimulus='snd', slot=0):
    return {
        'event_id': event_id, 'event_type': 'sound', 'role': 'PT',
        'stimulus': stimulus, 'trial_onset': onset,
        'source_event_id': 'missing_visual', 'soa': 0.5, 'sound_slot': slot,
    }


def run(events, predict_bias=0.0, escape_at=None):
    clock = FakeClock(RESET)
    window = FakeWindow(clock, FRAME_PERIOD, predict_bias)
    kb = FakeKeyboard(clock, escape_at)
    stimuli = {row['stimulus'] for row in events}
    pool = {stim: [FakeSound(clock), FakeSound(clock)] for stim in stimuli}
    images = {
        row['stimulus']: FakeStim() for row in events if row['event_type'] == 'visual'
    }
    metadata = {}
    trial_events = [dict(row) for row in events]
    result = trial_runner.run_trial(
        window=window, kb=kb, session_clock=clock,
        logging=SimpleNamespace(
            defaultClock=SimpleNamespace(getLastResetTime=lambda: RESET)),
        block='animate', trial=1, trial_events=trial_events, trial_keys=[],
        sound_pool=pool, image_cache=images, backgrounds=[FakeStim()],
        fixation=FakeStim(), overlay=None, frame_period=FRAME_PERIOD,
        metadata=metadata,
    )
    events_out, _keys, trial_row, aborted = result
    return SimpleNamespace(
        events=events_out, trial_row=trial_row, aborted=aborted,
        pool=pool, images=images, metadata=metadata,
    )


def nearest_frame(planned):
    return round(planned / FRAME_PERIOD) * FRAME_PERIOD


ONSET_FRACTIONS = [0.1, 0.3, 0.7, 0.9]


@pytest.mark.parametrize('fraction', ONSET_FRACTIONS)
def test_visual_onsets_snap_to_nearest_frame(fraction):
    planned = 3.0 + fraction * FRAME_PERIOD
    out = run([visual_event('v1', planned)])
    row = out.events[0]
    assert row['actual_onset'] == pytest.approx(nearest_frame(planned), abs=1e-9)
    assert row['onset_deviation'] == pytest.approx(
        nearest_frame(planned) - planned, abs=1e-9)
    assert abs(row['onset_deviation']) <= FRAME_PERIOD / 2 + 1e-9
    assert row['timing_flags'] == ''


@pytest.mark.parametrize('fraction', ONSET_FRACTIONS)
def test_visual_onsets_ignore_flip_predictor_bias(fraction):
    # A predictor biased 4 ms early must not shift onsets off the nearest
    # frame (the real sessions showed exactly this bias).
    planned = 3.0 + fraction * FRAME_PERIOD
    out = run([visual_event('v1', planned)], predict_bias=0.004)
    row = out.events[0]
    assert row['actual_onset'] == pytest.approx(nearest_frame(planned), abs=1e-9)
    assert abs(row['onset_deviation']) <= FRAME_PERIOD / 2 + 1e-9


def test_fade_ramp_is_anchored_to_recorded_onset():
    planned = 3.1
    out = run([visual_event('v1', planned)])
    draws = out.images['img'].draws
    assert draws[0] == pytest.approx(planned_image_alpha(0.0)) == pytest.approx(0.02)
    assert draws[1] == pytest.approx(planned_image_alpha(FRAME_PERIOD))
    assert draws[0] < draws[1] < draws[2]


def test_sounds_are_requested_at_trial_start():
    out = run([sound_event('s1', 5.0, slot=0)])
    plays = out.pool['snd'][0].plays
    assert len(plays) == 1
    call_time, requested_ptb = plays[0]
    assert call_time == pytest.approx(0.0, abs=1e-9)
    assert requested_ptb == pytest.approx(5.0 + RESET, abs=1e-9)
    row = out.events[0]
    assert row['audio_timing_source'] == 'PTB backend-reported startTime'
    assert row['onset_deviation'] == pytest.approx(0.0, abs=1e-9)


def test_pooled_replay_is_requested_as_soon_as_object_is_free():
    # One stimulus, slots 0/1/0: the third play re-uses slot 0 and must wait
    # for the first play to end (2.0 + SOUND_DUR + margin = 3.05).
    out = run([
        sound_event('s1', 2.0, slot=0),
        sound_event('s2', 2.75, slot=1),
        sound_event('s3', 3.5, slot=0),
    ])
    slot0 = out.pool['snd'][0].plays
    slot1 = out.pool['snd'][1].plays
    assert len(slot0) == 2 and len(slot1) == 1
    assert slot0[0] == pytest.approx((0.0, 2.0 + RESET), abs=1e-9)
    assert slot1[0] == pytest.approx((0.0, 2.75 + RESET), abs=1e-9)
    third_call, third_ptb = slot0[1]
    assert third_call == pytest.approx(
        2.0 + config.SOUND_DUR + config.SOUND_POOL_RESTART_MARGIN,
        abs=FRAME_PERIOD)
    assert third_ptb == pytest.approx(3.5 + RESET, abs=1e-9)
    assert out.events[2]['timing_flags'] == ''


def test_late_replay_is_requested_with_minimum_lead_and_flag():
    out = run([
        sound_event('s1', 2.0, slot=0),
        sound_event('s2', 3.02, slot=0),
    ])
    plays = out.pool['snd'][0].plays
    assert len(plays) == 2
    call_time, requested_ptb = plays[1]
    assert requested_ptb == pytest.approx(
        call_time + config.SOUND_REQUEST_MIN_LEAD + RESET, abs=1e-9)
    assert requested_ptb > 3.02 + RESET
    assert 'audio_schedule_late' in out.events[1]['timing_flags']


def test_abort_cancels_plays_that_have_not_started():
    out = run([sound_event('s1', 10.0, slot=0)], escape_at=1.0)
    assert out.aborted is True
    assert out.trial_row['trial_complete'] is False
    assert out.pool['snd'][0].stopped is True
    row = out.events[0]
    assert row['audio_backend_start_session_time'] == ''
    assert 'trial_aborted_before_audio_start_report' in row['timing_flags']
