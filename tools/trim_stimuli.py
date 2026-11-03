"""Re-cut the 1 s stimulus sounds to the 0.5 s the study now schedules.

`config.SOUND_DUR` is 0.5 s and `session_io.load_timeline` refuses a plan whose
scheduled duration differs from the WAV by more than 2 ms, so the 1 s files in
`20_stimuli/*/obj_snds/_cleaned` have to become 24 000 frames at 48 kHz.  The
study reads the re-cut set from `20_stimuli/*/obj_snds/_cleaned_0.5`, which
`session_io.stimulus_paths` points at; `_cleaned` keeps the 1 s originals.

Where the cut goes is the only real decision.  Every one of these sounds is a
1 s excerpt of a longer recording, and most carry energy past 0.5 s, so some
part of each sound is always lost.  Three policies are measured here:

    onset    keep the natural attack: 0.5 s from the first rise (timing-safe).
    peak     put the envelope peak 0.40 s into the clip, so the loudest moment
             survives with a little decay after it (starts mid-swell).
    hybrid   `onset` for fast attacks, `peak` for slow ones (see ATTACK_SPLIT).

Each written clip gets a 5 ms fade-in, a 40 ms fade-out and one shared
loudness target, measured as the loudest 200 ms K-weighted level.  That treats
a short click and a sustained texture more evenly than RMS does; a clip that
would clip before reaching the target is limited at PEAK_CEILING and reported.

    python3 tools/trim_stimuli.py --report
    python3 tools/trim_stimuli.py --install
    python3 tools/trim_stimuli.py --verify study
    python3 tools/trim_stimuli.py --policy onset --out 20_stimuli/_trim_candidates/onset
    python3 tools/trim_stimuli.py --audition 20_stimuli/_trim_candidates
"""

import argparse
import html
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import lfilter

ROOT = Path(__file__).resolve().parents[1]

CLIP_SECONDS = 0.5
SAMPLE_RATE = 48000
FADE_IN_SECONDS = 0.005
FADE_OUT_SECONDS = 0.04
TARGET_MOMENTARY_LUFS = -17.5   # median of the 1 s set, so most files barely move
PEAK_CEILING_DBFS = -1.0
ATTACK_SPLIT_SECONDS = 0.25     # 10-90% rise time above which the attack is a swell
PEAK_LEAD_SECONDS = 0.40        # where the peak sits inside a `peak` clip
ONSET_GUARD_SECONDS = 0.005
ACTIVITY_RANGE_DB = 25.0        # a frame belongs to the event within this much of its peak
EDGE_SECONDS = 0.02
CATEGORIES = ('animate', 'inanimate')
SOUND_DIR = '_cleaned_0.5'      # must match session_io.stimulus_paths
POLICIES = ('onset', 'peak', 'hybrid')
MEASURED_POLICIES = POLICIES + ('loudest',)

# Hand-picked cut points for the hybrid set, added after auditioning. The two
# entries below are dense textures whose loudest 10 ms frame is a fluctuation,
# not a swell, so the peak anchor starts them mid-texture for no gain; keeping
# their natural attack is the better cut. Only --policy hybrid reads these, so
# --report and the audition page still compare the raw policies.
OVERRIDES = {'animate/7': 0.0, 'inanimate/9': 0.0}


def cleaned_path(category, number):
    return ROOT / '20_stimuli' / category / 'obj_snds' / '_cleaned' / f'snd_{number}.wav'


def read_source(path):
    samples, rate = sf.read(str(path), dtype='float64')
    if samples.ndim == 1:
        samples = samples[:, None]
    if rate != SAMPLE_RATE:
        raise SystemExit(f'{path} is {rate} Hz, not {SAMPLE_RATE} Hz')
    return samples


def frame_rms(mono, seconds=0.01):
    size = int(seconds * SAMPLE_RATE)
    count = len(mono) // size
    return np.sqrt((mono[:count * size].reshape(count, size) ** 2).mean(axis=1))


def frame_levels_db(mono, seconds=0.01):
    return 20 * np.log10(np.maximum(frame_rms(mono, seconds), 1e-12))


def k_weighted_square(mono):
    """BS.1770 pre-filter squared, for momentary loudness."""
    shelf_f0, shelf_gain, shelf_q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    k = np.tan(np.pi * shelf_f0 / SAMPLE_RATE)
    vh = 10 ** (shelf_gain / 20)
    vb = vh ** 0.4996667741545416
    a0 = 1 + k / shelf_q + k * k
    b = np.array([(vh + vb * k / shelf_q + k * k) / a0, 2 * (k * k - vh) / a0,
                  (vh - vb * k / shelf_q + k * k) / a0])
    a = np.array([1.0, 2 * (k * k - 1) / a0, (1 - k / shelf_q + k * k) / a0])
    high_shelf = lfilter(b, a, mono)
    hp_f0, hp_q = 38.13547087602444, 0.5003270373238773
    k = np.tan(np.pi * hp_f0 / SAMPLE_RATE)
    b = np.array([1.0, -2.0, 1.0])
    a = np.array([1.0, 2 * (k * k - 1) / (1 + k / hp_q + k * k),
                  (1 - k / hp_q + k * k) / (1 + k / hp_q + k * k)])
    return lfilter(b, a, high_shelf) ** 2


def momentary_lufs(weighted_square, start=0, length=None, window_seconds=0.2):
    """Loudest K-weighted level over `window_seconds` inside one clip."""
    segment = weighted_square[start:None if length is None else start + length]
    size = int(window_seconds * SAMPLE_RATE)
    if len(segment) < size:
        return -0.691 + 10 * np.log10(max(segment.mean(), 1e-20))
    cumulative = np.cumsum(segment)
    windows = cumulative[size - 1:] - np.concatenate(([0.0], cumulative[:-size]))
    return -0.691 + 10 * np.log10(max(windows.max() / size, 1e-20))


def analyse(samples):
    """Onset, end, peak position and 10-90% attack time of one source file."""
    mono = samples.mean(axis=1)
    levels_db = frame_levels_db(mono)
    levels = frame_rms(mono)
    active = np.where(levels_db > max(levels_db.max() - ACTIVITY_RANGE_DB, -70.0))[0]
    onset = active[0] * 0.01 if len(active) else 0.0
    peak_frame = int(np.argmax(levels_db))
    rise = levels[:peak_frame + 1]
    above_10 = np.where(rise > 0.1 * rise.max())[0]
    above_90 = np.where(rise > 0.9 * rise.max())[0]
    attack = (above_90[0] - above_10[0]) * 0.01 if len(above_10) and len(above_90) else 0.0
    energy = mono ** 2
    return {
        'onset': onset,
        'end': (active[-1] + 1) * 0.01 if len(active) else 0.0,
        'peak': peak_frame * 0.01,
        'attack': attack,
        'front_share': energy[:len(mono) // 2].sum() / energy.sum(),
    }


def loudest_start(weighted_square):
    length = int(CLIP_SECONDS * SAMPLE_RATE)
    cumulative = np.cumsum(weighted_square)
    windows = cumulative[length - 1:] - np.concatenate(([0.0], cumulative[:-length]))
    return float(np.argmax(windows)) / SAMPLE_RATE


def clip_start(policy, info, weighted_square, source_seconds):
    """Where the 0.5 s window begins for one policy, in seconds."""
    if policy == 'loudest':
        start = loudest_start(weighted_square)
    elif policy == 'peak':
        start = info['peak'] - PEAK_LEAD_SECONDS
    elif policy == 'onset':
        start = info['onset'] - ONSET_GUARD_SECONDS
    else:
        slow = info['attack'] > ATTACK_SPLIT_SECONDS
        start = info['peak'] - PEAK_LEAD_SECONDS if slow else info['onset'] - ONSET_GUARD_SECONDS
    return min(max(0.0, start), max(0.0, source_seconds - CLIP_SECONDS))


def apply_fades(segment):
    length = len(segment)
    fade_in = min(int(FADE_IN_SECONDS * SAMPLE_RATE), length)
    fade_out = min(int(FADE_OUT_SECONDS * SAMPLE_RATE), length)
    ramp_in = 0.5 - 0.5 * np.cos(np.pi * np.arange(fade_in) / fade_in)
    ramp_out = 0.5 + 0.5 * np.cos(np.pi * np.arange(1, fade_out + 1) / fade_out)
    faded = segment.copy()
    faded[:fade_in] *= ramp_in[:, None]
    faded[length - fade_out:] *= ramp_out[:, None]
    return faded


def edge_level_db(mono, at_start):
    """RMS of the first or last EDGE_SECONDS of a clip, in dBFS."""
    size = int(EDGE_SECONDS * SAMPLE_RATE)
    edge = mono[:size] if at_start else mono[-size:]
    return 20 * np.log10(max(np.sqrt((edge ** 2).mean()), 1e-12))


def build(category, number, policy):
    """Return (samples, report row) for one source file and policy."""
    samples = read_source(cleaned_path(category, number))
    mono = samples.mean(axis=1)
    info = analyse(samples)
    weighted = k_weighted_square(mono)
    length = int(CLIP_SECONDS * SAMPLE_RATE)
    override = OVERRIDES.get(f'{category}/{number}') if policy == 'hybrid' else None
    start = override if override is not None else clip_start(policy, info, weighted, len(mono) / SAMPLE_RATE)
    begin = min(int(round(start * SAMPLE_RATE)), len(samples) - length)
    cut = samples[begin:begin + length]
    segment = apply_fades(cut)
    before = momentary_lufs(weighted, begin, length)
    cut_peak = 20 * np.log10(max(np.abs(segment).max(), 1e-12))
    gain = TARGET_MOMENTARY_LUFS - before
    limited = cut_peak + gain > PEAK_CEILING_DBFS
    if limited:
        gain = PEAK_CEILING_DBFS - cut_peak
    out = segment * 10 ** (gain / 20)
    clip_peak = 20 * np.log10(max(np.abs(segment).max(), 1e-12))
    row = {
        'category': category, 'number': number, 'policy': policy, 'start': begin / SAMPLE_RATE,
        'onset': info['onset'], 'peak': info['peak'], 'attack': info['attack'],
        'front': info['front_share'],
        'kept': float((cut.mean(axis=1) ** 2).sum() / (mono ** 2).sum()),
        'lufs_before': before, 'gain': gain, 'limited': limited,
        'start_level': edge_level_db(cut.mean(axis=1), True) - clip_peak,
        'end_level': edge_level_db(cut.mean(axis=1), False) - clip_peak,
        'peak_after': 20 * np.log10(max(np.abs(out).max(), 1e-12)),
        'rms_after': 20 * np.log10(max(np.sqrt((out ** 2).mean()), 1e-12)),
        'lufs_after': momentary_lufs(k_weighted_square(out.mean(axis=1))),
    }
    return out, row


def envelope_bars(mono, columns=20):
    levels = frame_rms(mono, len(mono) / columns / SAMPLE_RATE)[:columns]
    levels = levels / levels.max() if levels.max() > 0 else levels
    return ''.join(' .:-=+*#%@'[min(9, int(value * 9.99))] for value in levels)


def print_report(rows):
    print('| sound | onset | attack | peak | cut at | kept | start | end | gain | peak | loudness |')
    print('| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |')
    for row in rows:
        flag = ' (limited)' if row['limited'] else ''
        print(f"| {row['category'][:3]} {row['number']:>2} | {row['onset']:.2f} | {row['attack']:.2f} | "
              f"{row['peak']:.2f} | {row['start']:.2f} | {row['kept'] * 100:.0f}% | "
              f"{row['start_level']:+.0f} | {row['end_level']:+.0f} | {row['gain']:+.1f} | "
              f"{row['peak_after']:.1f} | {row['lufs_after']:.1f}{flag} |")
    print('\nstart/end: first and last 20 ms of the cut in dB below the clip peak '
          '(a natural attack starts near the noise floor)')
    for policy in sorted({row['policy'] for row in rows}):
        subset = [row for row in rows if row['policy'] == policy]
        loudness = np.array([row['lufs_after'] for row in subset])
        kept = np.array([row['kept'] for row in subset])
        print(f"{policy}: loudness {loudness.min():.1f} to {loudness.max():.1f} dB "
              f"(spread {loudness.max() - loudness.min():.1f}), energy kept "
              f"{kept.min() * 100:.0f}-{kept.max() * 100:.0f}%, "
              f"{sum(row['limited'] for row in subset)} limited")


def study_targets():
    """(category, number, path) in the layout the study loads."""
    return [(category, number,
             ROOT / '20_stimuli' / category / 'obj_snds' / SOUND_DIR / f'snd_{number}.wav')
            for category in CATEGORIES for number in range(1, 11)]


def candidate_targets(directory):
    """(category, number, path) in the audition layout: <policy>/<category>/snd_N.wav."""
    return [(category, number, Path(directory) / category / f'snd_{number}.wav')
            for category in CATEGORIES for number in range(1, 11)]


def write_set(targets, policy, show_envelopes=False):
    rows = []
    for category, number, path in targets:
        samples, row = build(category, number, policy)
        path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(path), samples, SAMPLE_RATE, subtype='PCM_16')
        rows.append(row)
        if show_envelopes:
            bars = envelope_bars(read_source(cleaned_path(category, number)).mean(axis=1))
            marker = [' '] * len(bars)
            marker[min(len(bars) - 1, int(row['start'] * 20))] = '^'
            print(f'{category[:3]} {number:>2} {bars}  cut at {row["start"]:.2f}s')
            print(f'           {"".join(marker)}')
    print_report(rows)
    return rows


def window_bar(mono, start, columns=40):
    """The source envelope over 1 s, with dots outside the kept 0.5 s window."""
    seconds = len(mono) / SAMPLE_RATE
    levels = frame_rms(mono, seconds / columns)[:columns]
    levels = levels / levels.max() if levels.max() > 0 else levels
    return ''.join(
        ' .:-=+*#%@'[min(9, int(value * 9.99))]
        if start <= index * seconds / columns < start + CLIP_SECONDS else '·'
        for index, value in enumerate(levels)
    )


def audition_page(directory, policies):
    """One block per sound so the policies can be compared by eye and by ear."""
    blocks = []
    for category in CATEGORIES:
        for number in range(1, 11):
            mono = read_source(cleaned_path(category, number)).mean(axis=1)
            rows = []
            for policy in policies:
                _, row = build(category, number, policy)
                if not (directory / policy / category / f'snd_{number}.wav').is_file():
                    continue
                rows.append(
                    f'<div class="p"><span class="tag">{policy}</span>'
                    f'<pre class="bar">{html.escape(window_bar(mono, row["start"]))}</pre>'
                    f'<audio controls preload="none" src="{policy}/{category}/snd_{number}.wav"></audio>'
                    f'<span class="m">{row["kept"] * 100:.0f}% kept, {row["lufs_after"]:.1f} dB</span></div>'
                )
            blocks.append(
                f'<section><h2>{html.escape(category[:3])} {number}</h2>{"".join(rows)}</section>'
            )
    page = f"""<!doctype html>
<meta charset="utf-8">
<title>0.5 s stimulus candidates</title>
<style>
 body {{ font: 14px/1.4 system-ui, sans-serif; margin: 2rem; background: #111; color: #eee; max-width: 960px; }}
 h1 {{ font-size: 18px; }} h2 {{ font-size: 13px; margin: 0 0 .3rem; color: #ddd; }}
 p {{ color: #aaa; }} section {{ border-top: 1px solid #333; padding: .7rem 0; }}
 .p {{ display: flex; align-items: center; gap: .7rem; }}
 .tag {{ width: 3.6rem; color: #888; font-size: 12px; }}
 .bar {{ margin: 0; color: #6cf; font-size: 12px; letter-spacing: 1px; }}
 .m {{ color: #777; font-size: 11px; white-space: nowrap; }}
 audio {{ height: 28px; width: 260px; }}
</style>
<h1>0.5 s stimulus candidates — same loudness target, different cut points</h1>
<p>Each bar is the 1 s source over its full length; bright characters are the 0.5 s that survives
(the cut starts where the dots stop). Percentages are the share of the source's energy kept.</p>
{''.join(blocks)}
"""
    target = directory / 'audition.html'
    target.write_text(page, encoding='utf-8')
    print(f'wrote {target}')


def verify(targets):
    """Re-read a written set and check duration, channels, peak and loudness."""
    print('| sound | frames | seconds | peak | loudness |')
    print('| --- | --- | --- | --- | --- |')
    loudness, failures = [], []
    for category, number, path in targets:
        if not path.is_file():
            failures.append(f'{path} is missing')
            continue
        samples, rate = sf.read(str(path), dtype='float64')
        if samples.ndim == 1:
            samples = samples[:, None]
        seconds = len(samples) / rate
        if rate != SAMPLE_RATE or abs(seconds - CLIP_SECONDS) > 0.002 or samples.shape[1] != 2:
            failures.append(f'{path}: {rate} Hz, {len(samples)} frames, {samples.shape[1]} channels')
        peak = 20 * np.log10(max(np.abs(samples).max(), 1e-12))
        level = momentary_lufs(k_weighted_square(samples.mean(axis=1)))
        loudness.append(level)
        print(f'| {category[:3]} {number:>2} | {len(samples)} | {seconds:.3f} | {peak:.1f} | {level:.1f} |')
    print(f'\nloudness spread {max(loudness) - min(loudness):.1f} dB over {len(loudness)} files')
    if failures:
        print('\n'.join(failures))
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--policy', choices=POLICIES, default='hybrid')
    parser.add_argument('--report', action='store_true', help='measure every policy, write nothing')
    parser.add_argument('--install', action='store_true', help=f'write the study layout (_cleaned_0.5)')
    parser.add_argument('--out', type=Path, help='write a candidate set into DIR/<category>/snd_N.wav')
    parser.add_argument('--audition', type=Path, help='directory holding <policy>/<category>/snd_N.wav')
    parser.add_argument('--verify', help="'study' or a candidate directory to re-read and check")
    args = parser.parse_args()
    if args.verify:
        targets = study_targets() if args.verify == 'study' else candidate_targets(args.verify)
        sys.exit(1 if verify(targets) else 0)
    if args.report:
        for policy in MEASURED_POLICIES:
            print(f'\n### {policy}')
            print_report([build(category, number, policy)[1]
                          for category in CATEGORIES for number in range(1, 11)])
        return
    if args.audition:
        audition_page(args.audition, POLICIES)
        return
    if args.install:
        write_set(study_targets(), args.policy, show_envelopes=True)
        return
    if not args.out:
        parser.error('pass --report, --install, --out DIR, --audition DIR, or --verify PATH')
    write_set(candidate_targets(args.out), args.policy)


if __name__ == '__main__':
    main()
