# ==============================================================================
# Main entry point for the AV spatiotemporal study runtime.
# PSYCHOPY EXPERIMENT: AV SPATIOTEMPORAL AWARENESS
# VERSION 28
#   - Central fixation cross, flashes green on valid in-window hits.
#   - Non-PT appearance count ranges raised (NPT 2-6, PD 2-4, NPD 4-9).
#   - responses.csv: key_pressed_corner column (numpad key -> corner name).
#
# Timing notes:
#   - Visual onset is stamped from the VBL-synchronised timestamp returned by
#     win.flip(), converted into the shared keyboard clock timebase.
#
#   - PTB audio is scheduled against the upcoming flip with play(when=...),
#     and sound_start is logged as that flip-aligned request time. This is a
#     tight software timestamp, but not a microphone-confirmed DAC onset.
#   - av_sync_error_ms captures the change in recorded sound-vs-visual
#     alignment relative to the planned SOA, which helps expose late-flip AV
#     desync even when PTB sound scheduling itself looks clean.
#   - Frame intervals are summarised per trial into trials.csv so dropped/long
#     frames can be debugged alongside the response and stimulus logs.
# Retains:
#   - Audio normalization via pydub (TARGET_DBFS)
#   - Spatial jitter within quadrants
#   - Expanded 20-item stimulus pool
#   - Flattened target hit label to 'hit'
# ==============================================================================

import os
import sys
from psychopy import prefs

# 1. SESSION GUARD (strict mode optional)
STRICT_XORG = os.environ.get('AV_STUDY_STRICT_XORG', '0') == '1'
if os.environ.get('XDG_SESSION_TYPE') == 'wayland':
    if STRICT_XORG:
        raise RuntimeError("Wayland detected. Switch to Xorg or set AV_STUDY_STRICT_XORG=0.")
    print("WARNING: Wayland session detected. Xorg is recommended for timing-critical runs.")

# 2. AUDIO PREFERENCES
DEFAULT_AUDIO_LIB_ORDER = ['ptb', 'sounddevice', 'pygame']
audio_lib_env = os.environ.get('AV_STUDY_AUDIO_LIBS', '')
audio_lib_order = [x.strip() for x in audio_lib_env.split(',') if x.strip()] if audio_lib_env else DEFAULT_AUDIO_LIB_ORDER
audio_latency_mode = int(os.environ.get('AV_STUDY_AUDIO_LATENCY_MODE', '2'))
audio_device_name = os.environ.get('AV_STUDY_AUDIO_DEVICE', 'default')
audio_speaker_name = os.environ.get('AV_STUDY_AUDIO_SPEAKER', audio_device_name)

prefs.hardware['audioLib'] = audio_lib_order
prefs.hardware['audioLatencyMode'] = [audio_latency_mode]
prefs.hardware['audioDevice'] = [audio_device_name]
prefs.hardware['audioSpeaker'] = [audio_speaker_name]

# 3. FORCE LOCAL WORKING DIRECTORY
# AV_STUDY_DIR override can point at lab SMB/local mirror. Default is script dir.
STUDY_DIR = os.environ.get('AV_STUDY_DIR', os.path.dirname(os.path.abspath(__file__)))
if not os.path.exists(STUDY_DIR):
    raise RuntimeError(f"Study directory does not exist: {STUDY_DIR}")
os.chdir(STUDY_DIR)
print(f"Working directory: {STUDY_DIR}")

# 4. LOCK IN PREFERENCES
from psychopy import sound

# 5. Now import everything else
import numpy as np
import random
from psychopy import visual, core, event, logging
from psychopy.hardware import keyboard
import csv
from datetime import datetime
from PIL import Image


try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False

_PYDUB_FALLBACK_WARNED = False


def _warn_pydub_fallback_once():
    """pydub is only needed for on-the-fly normalization of *raw* WAVs.

    When ``PREFER_CLEANED_AUDIO`` is on and ``_cleaned/*.wav`` exist (the bundle
    default), we never hit this path — don't scare the operator at import time.
    """
    global _PYDUB_FALLBACK_WARNED
    if _PYDUB_FALLBACK_WARNED or PYDUB_AVAILABLE:
        return
    _PYDUB_FALLBACK_WARNED = True
    print(
        "WARNING: pydub not installed — cannot build ``_normalized`` clips from "
        "raw WAVs. Using original files as-is.\n"
        "         Fix: use pre-built ``_cleaned/`` WAVs (default), or install pydub:\n"
        f"              {sys.executable} -m pip install pydub"
    )


# ==============================================================================
# 1. CONFIGURATION
# ==============================================================================

# --- File paths ---
# Resolved once at startup above via AV_STUDY_DIR or script directory.

# --- Privileged target selection ---
PT_COUNT_PER_GROUP = 2      

# --- PT SOA (fixed per PT for whole experiment) ---
PT_SOA_MIN = 0.5            
PT_SOA_MAX = 1.5

# --- Privileged Distractor config ---
PD_COUNT_PER_BLOCK = 2      
PD_SOA_MIN = 0.5            
PD_SOA_MAX = 1.5

# --- Trial counts ---
NUM_ANIMATE_TRIALS   = 5   
NUM_INANIMATE_TRIALS = 5   

PT_SUBBLOCK_ORDER = 'random'
ALLOW_BOTH_PTS_SAME_TRIAL = False

# --- Stimulus appearance counts per trial (randomly sampled each trial) ---
# Non-PT ranges raised 2026-07-15 (~50%) to make trials denser/more engaging.
# PT counts unchanged so the privileged-target design is untouched.
TRIAL_PT_MIN   = 2      
TRIAL_PT_MAX   = 3
TRIAL_NPT_MIN  = 3      
TRIAL_NPT_MAX  = 8
TRIAL_PD_MIN   = 3      
TRIAL_PD_MAX   = 5
TRIAL_NPD_MIN  = 6      
TRIAL_NPD_MAX  = 11

# --- Spatial bias ---
TARGET_SPATIAL_BIAS = 0.80  

# --- Visual timing (seconds) ---
FADE_IN_DUR   = 0.3
PEAK_HOLD_DUR = 0.0
FADE_OUT_DUR  = 0.3
STIM_DUR      = FADE_IN_DUR + PEAK_HOLD_DUR + FADE_OUT_DUR  
MIN_VISUAL_ONSET_GAP = 0.15
MIN_SAME_ITEM_GAP = 0.75

# --- Trial timing ---
TRIAL_CONTENT_DUR  = 20.0   
TRIAL_BUFFER_DUR   = 2.0    
WINDOW_EXTEND_SEC  = 3.0    
MAX_WINDOW_EXTENDS = 5      

BETWEEN_PT_STIMULUS_GAP = 0.5  

# --- Audio ---
SOUND_DUR     = 1.0     
MIN_AUDIO_GAP = 0.2     
TARGET_DBFS   = -20.0   
PREFER_CLEANED_AUDIO = os.environ.get('AV_STUDY_PREFER_CLEANED_AUDIO', '1') == '1'
CLEANED_AUDIO_SUBDIR = '_cleaned'
PREFER_NORMALIZED_IMAGES = os.environ.get('AV_STUDY_PREFER_NORMALIZED_IMAGES', '1') == '1'
NORMALIZED_IMAGE_SUBDIR = '_normalized'
CANONICAL_AUDIO_HZ = 48000
CANONICAL_AUDIO_CHANNELS = 2
CANONICAL_AUDIO_SAMPLE_WIDTH_BYTES = 2
MAX_AUDIO_PRELOAD_FAILURES = int(os.environ.get('AV_STUDY_MAX_AUDIO_PRELOAD_FAILURES', '0'))
MAX_AUDIO_RUNTIME_FAILURES = int(os.environ.get('AV_STUDY_MAX_AUDIO_RUNTIME_FAILURES', '2'))
SKIP_AUDIO_PREFLIGHT = os.environ.get('AV_STUDY_SKIP_AUDIO_PREFLIGHT', '0') == '1'
AUDIO_RUNTIME_FAILURES = 0

# --- Response ---
RESPONSE_WINDOW = 1.5   
FA_LATE_GRACE_SEC = 0.5

# --- Display / debug timing ---
FALLBACK_REFRESH_HZ = 120.0
FRAME_DROP_THRESHOLD_FACTOR = 1.2

# --- Background ---
BG_NOISE_OPACITY = 0.3
BG_SOURCE_FILE   = 'otherblobs.png'
BG_UPDATE_RATE   = 0.4

# --- Visuals ---
IMAGE_SIZE  = [200, 200]  # Reduced by 50%
MAX_OPACITY = 1.0

# --- Fixation cross ---
# Drawn at screen center every frame. Stimulus jitter keeps a 100px clearance
# from the center axes (see make_event), so the cross never overlaps stimuli.
FIXATION_SIZE       = 30      # full width/height of the cross, px
FIXATION_LINE_WIDTH = 3
FIXATION_COLOR      = 'white'
FIXATION_HIT_COLOR  = 'green'   # flashed on valid in-window hits
FIXATION_FLASH_DUR  = 0.2       # seconds

# --- Debug overlay ---
# Off by default for production timing. Set AV_STUDY_DEBUG_OVERLAY=1 to enable
# during layout/dev passes (adds per-frame text/line/dot draws that worsen
# frame timing).
DEBUG_OVERLAY = os.environ.get('AV_STUDY_DEBUG_OVERLAY', '0') == '1'

# --- Numpad mapping (Linux Safe) ---
CORNER_TO_KEY = {
    'top_left':     ['num_4', 'KP_Left'],
    'top_right':    ['num_5', 'KP_Begin'],
    'bottom_left':  ['num_1', 'KP_End'],
    'bottom_right': ['num_2', 'KP_Down'],
}
# Flatten the list so PsychoPy can listen to all variations
ALL_RESPONSE_KEYS  = [k for keys in CORNER_TO_KEY.values() for k in keys]
ALL_CORNERS        = list(CORNER_TO_KEY.keys())
NON_BIASED_CORNERS = ['top_left', 'bottom_left', 'bottom_right']

KEY_TO_CORNER = {
    key: corner
    for corner, keys in CORNER_TO_KEY.items()
    for key in keys
}


def key_to_corner(key):
    """Map a recorded numpad key name to its corner label, or '' if unknown."""
    return KEY_TO_CORNER.get(key, '')


# ==============================================================================
# 2. STIMULUS NAME LOOKUP 
# ==============================================================================

ANIMATE_NAMES = {
    1: 'cat',   2: 'frog',    3: 'duck',
    4: 'cow',   5: 'rooster', 6: 'dog',
    7: 'horse', 8: 'lion',    9: 'pig',
   10: 'elephant',
}

ANIMATE_SOUNDS = {
    1: 'meow',  2: 'ribbit',  3: 'quack',
    4: 'moo',   5: 'crow',    6: 'bark',
    7: 'neigh', 8: 'roar',    9: 'oink',
   10: 'trumpet',
}

INANIMATE_NAMES = {
    1: 'camera',     2: 'door',        3: 'phone',
    4: 'toilet',     5: 'clock',       6: 'car',
    7: 'wineglass',  8: 'helicopter',  9: 'motorcycle',
   10: 'ship',
}

INANIMATE_SOUNDS = {
    1: 'click',  2: 'knock',  3: 'ring',
    4: 'flush',  5: 'tick',   6: 'vroom',
    7: 'clink',  8: 'blades', 9: 'rev',
   10: 'horn',
}

def friendly_name(item):
    """Return human-readable name for a stimulus item."""
    n = item['obj_num']
    if item['cat'] == 'animate':
        return f"{ANIMATE_NAMES[n]} ({ANIMATE_SOUNDS[n]})"
    else:
        return f"{INANIMATE_NAMES[n]} ({INANIMATE_SOUNDS[n]})"


# ==============================================================================
# 3. STIMULI DEFINITIONS
# ==============================================================================

def get_path(category, obj_num, file_type='img'):
    if file_type == 'img':
        fname = f'obj_{obj_num}_bw.png'
        objdir = os.path.join('20_stimuli', category, 'objects_numbered')
        if PREFER_NORMALIZED_IMAGES:
            normalized = os.path.join(objdir, NORMALIZED_IMAGE_SUBDIR, fname)
            if os.path.exists(normalized):
                return normalized
        return os.path.join(objdir, fname)
    elif file_type == 'snd':
        return os.path.join('20_stimuli', category, 'obj_snds', f'snd_{obj_num}.wav')

animate_pool   = [{'name': f'animate_obj_{i}',   'cat': 'animate',   'obj_num': i} for i in range(1, 11)]
inanimate_pool = [{'name': f'inanimate_obj_{i}', 'cat': 'inanimate', 'obj_num': i} for i in range(1, 11)]

print(f"Loaded {len(animate_pool)} animate and {len(inanimate_pool)} inanimate stimuli")


# ==============================================================================
# 3b. AUDIO NORMALIZATION 
# ==============================================================================

_normalized_cache = {}


def trim_leading_silence(seg, silence_thresh_dbfs=-40.0, chunk_ms=10):
    """Trim leading silence so perceptual onset better matches logged onset."""
    trim_ms = 0
    while trim_ms < len(seg):
        chunk = seg[trim_ms:trim_ms + chunk_ms]
        if chunk.dBFS != float('-inf') and chunk.dBFS > silence_thresh_dbfs:
            break
        trim_ms += chunk_ms
    return seg[trim_ms:]


def get_cleaned_audio_path(snd_path):
    cleaned_path = os.path.join(
        os.path.dirname(snd_path),
        CLEANED_AUDIO_SUBDIR,
        os.path.basename(snd_path),
    )
    if os.path.exists(cleaned_path):
        return cleaned_path
    return None


def normalize_audio(snd_path):
    if PREFER_CLEANED_AUDIO:
        cleaned_path = get_cleaned_audio_path(snd_path)
        if cleaned_path is not None:
            return cleaned_path

    if not PYDUB_AVAILABLE:
        _warn_pydub_fallback_once()
        return snd_path

    cache_key = (snd_path, SOUND_DUR, TARGET_DBFS)
    if cache_key in _normalized_cache:
        return _normalized_cache[cache_key]

    try:
        norm_dir = os.path.join(os.path.dirname(snd_path), '_normalized')
        os.makedirs(norm_dir, exist_ok=True)
        stem, ext = os.path.splitext(os.path.basename(snd_path))
        norm_name = f"{stem}_trimmed_{int(SOUND_DUR * 1000)}ms_{int(abs(TARGET_DBFS) * 10)}.wav"
        norm_path = os.path.join(norm_dir, norm_name)

        if not os.path.exists(norm_path):
            seg = AudioSegment.from_wav(snd_path)
            seg = trim_leading_silence(seg)
            seg = seg.set_frame_rate(CANONICAL_AUDIO_HZ)
            seg = seg.set_channels(CANONICAL_AUDIO_CHANNELS)
            seg = seg.set_sample_width(CANONICAL_AUDIO_SAMPLE_WIDTH_BYTES)

            target_ms = int(SOUND_DUR * 1000)
            if len(seg) > target_ms:
                seg = seg[:target_ms]
            elif len(seg) < target_ms:
                seg += AudioSegment.silent(duration=target_ms - len(seg), frame_rate=seg.frame_rate)

            if seg.dBFS != float('-inf'):
                delta = TARGET_DBFS - seg.dBFS
                peak_limited_delta = min(delta, -1.0 - seg.max_dBFS)
                seg = seg.apply_gain(peak_limited_delta)
            seg.export(norm_path, format='wav')
            print(f"  [AUDIO] Normalized {os.path.basename(snd_path)}: "
                  f"trimmed to {SOUND_DUR:.2f}s, matched near {TARGET_DBFS:.1f} dBFS, "
                  f"exported at {CANONICAL_AUDIO_HZ} Hz")
        else:
            print(f"  [AUDIO] Using cached normalized {os.path.basename(snd_path)}")

        _normalized_cache[cache_key] = norm_path
        return norm_path

    except Exception as e:
        print(f"  WARNING: audio normalization failed for {snd_path}: {e} — using original")
        _normalized_cache[cache_key] = snd_path
        return snd_path


# ==============================================================================
# 4. PARTICIPANT ID
# ==============================================================================

participant_pid = datetime.now().strftime('%Y%m%d_%H%M%S')
data_dir        = os.path.join(STUDY_DIR, 'data', participant_pid)
os.makedirs(data_dir, exist_ok=True)
data_filename      = f"participant_{participant_pid}_stimulus.csv"
data_filepath      = os.path.join(data_dir, data_filename)
responses_filename = f"participant_{participant_pid}_responses.csv"
responses_filepath = os.path.join(data_dir, responses_filename)
trials_filename    = f"participant_{participant_pid}_trials.csv"
trials_filepath    = os.path.join(data_dir, trials_filename)

print(f"\nParticipant PID: {participant_pid}")
print(f"Stimulus file:   {data_filename}")
print(f"Responses file:  {responses_filename}")
print(f"Trials file:     {trials_filename}\n")


# ==============================================================================
# 4b. RUN-START SYSTEM DIAGNOSTICS
# ==============================================================================
# Captures static system tuning state once at session start. The dynamic
# trajectory (per-trial CPU temp) is captured inside run_trial via
# _cpu_temp_celsius() and recorded in the trials CSV as cpu_temp_c_at_start.
# All measurements happen at trial boundaries -- never inside the per-frame
# loop -- so this adds zero per-frame cost.

def _cpu_temp_celsius():
    """Hottest CPU thermal-zone temperature in degrees Celsius, or None.

    Reads /sys/class/thermal/thermal_zone*/temp (millicelsius) and returns
    max across all zones. Best-effort -- silently returns None on systems
    without thermal sysfs (e.g., some VMs, non-Linux). ~50 us on a typical
    desktop, safe to call once per trial.
    """
    try:
        import glob as _glob
        zones = sorted(_glob.glob("/sys/class/thermal/thermal_zone*/temp"))
        if not zones:
            return None
        temps = []
        for zone in zones:
            try:
                with open(zone) as f:
                    temps.append(int(f.read().strip()) / 1000.0)
            except (OSError, ValueError):
                continue
        return max(temps) if temps else None
    except Exception:
        return None


def _log_run_start_diagnostics():
    """One-shot dump of system tuning state at session start.

    Captures: CPU governor (per core), xset DPMS / screensaver state,
    PipeWire quantum, known load-generating background apps, ambient
    CPU temp. Output goes to stdout (= diag_run.log via run_diag.py).
    Failures are non-fatal -- each probe is independently try/except'd.
    """
    import subprocess as _sub
    import re as _re
    import glob as _glob
    from collections import Counter as _Counter

    print("=== run-start system snapshot ===", flush=True)

    try:
        govs = []
        for p in sorted(_glob.glob("/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor")):
            try:
                with open(p) as f:
                    govs.append(f.read().strip())
            except OSError:
                pass
        if not govs:
            print("  governor:                <not available>")
        else:
            counts = _Counter(govs)
            if len(counts) == 1:
                print(f"  governor:                {next(iter(counts))} (all {len(govs)} cpus)")
            else:
                print(f"  governor:                MIXED {dict(counts)}  (consider running ./run_study.sh for tuning)")
    except Exception as e:
        print(f"  governor:                <error: {type(e).__name__}>")

    try:
        out = _sub.run(["xset", "q"], capture_output=True, text=True, timeout=2)
        text = out.stdout
        dpms_m = _re.search(r"DPMS is (\w+)", text)
        ss_to = _re.search(r"timeout:\s*(\d+)", text)
        prefer_blanking = _re.search(r"prefer blanking:\s*(\w+)", text)
        dpms_state = dpms_m.group(1) if dpms_m else "?"
        marker = "  <-- WARNING: DPMS active" if dpms_state == "Enabled" else ""
        print(f"  xset DPMS:               {dpms_state}{marker}")
        print(f"  xset screensaver:        timeout={ss_to.group(1) if ss_to else '?'}s, "
              f"prefer_blanking={prefer_blanking.group(1) if prefer_blanking else '?'}")
    except Exception as e:
        print(f"  xset:                    <error: {type(e).__name__}>")

    try:
        out = _sub.run(["pw-metadata", "-n", "settings"],
                       capture_output=True, text=True, timeout=2)
        force_q = _re.search(r"clock\.force-quantum.*?value:'?(\d+)'?", out.stdout)
        nominal_q = _re.search(r"'clock\.quantum'.*?value:'?(\d+)'?", out.stdout)
        if force_q:
            print(f"  PipeWire quantum:        force={force_q.group(1)} (pinned)")
        elif nominal_q:
            print(f"  PipeWire quantum:        {nominal_q.group(1)} (nominal, not pinned)")
        else:
            print(f"  PipeWire quantum:        <not parsed>")
    except Exception as e:
        print(f"  PipeWire quantum:        <not queryable: {type(e).__name__}>")

    try:
        watchlist = ("firefox chromium chrome slack discord zoom teams "
                     "spotify dropbox syncthing nextcloud insync onedrive").split()
        running = []
        for app in watchlist:
            r = _sub.run(["pgrep", "-x", app], capture_output=True, timeout=1)
            if r.returncode == 0:
                running.append(app)
        if running:
            print(f"  background apps:         WARNING running: {running}")
        else:
            print(f"  background apps:         none from watchlist")
    except Exception as e:
        print(f"  background apps:         <error: {type(e).__name__}>")

    temp = _cpu_temp_celsius()
    if temp is None:
        print(f"  CPU temp at run start:   <not available>")
    else:
        warn = "  <-- WARNING: hot start" if temp >= 80.0 else ""
        print(f"  CPU temp at run start:   {temp:.1f} C{warn}")

    print(f"  Display refresh target:  120 Hz (FALLBACK_REFRESH_HZ)")
    print(f"  PREFER_CLEANED_AUDIO:    {PREFER_CLEANED_AUDIO}")
    print(f"  PREFER_NORMALIZED_IMAGES: {PREFER_NORMALIZED_IMAGES}")
    print("=== end run-start snapshot ===\n", flush=True)


_log_run_start_diagnostics()


# ==============================================================================
# 5. PRIVILEGED GROUP ASSIGNMENT
# ==============================================================================

def assign_pt_group():
    animate_pts   = random.sample(animate_pool,   PT_COUNT_PER_GROUP)
    inanimate_pts = random.sample(inanimate_pool, PT_COUNT_PER_GROUP)
    pt_group = {}
    for item in animate_pts + inanimate_pts:
        soa = round(random.uniform(PT_SOA_MIN, PT_SOA_MAX), 2)
        pt_group[item['name']] = {'item': item, 'soa': soa, 'role': 'PT'}
    return pt_group

def assign_pd_group(pt_group, block_type):
    pt_names = set(pt_group.keys())

    if block_type == 'animate':
        base_pool = inanimate_pool
    else:
        base_pool = animate_pool

    distractor_pool = [x for x in base_pool if x['name'] not in pt_names]

    count    = min(PD_COUNT_PER_BLOCK, len(distractor_pool))
    pd_items = random.sample(distractor_pool, count)
    pd_names = {x['name'] for x in pd_items}

    pd_group = {item['name']: {'item': item, 'role': 'PD'} for item in pd_items}
    npd_pool = [x for x in distractor_pool if x['name'] not in pd_names]

    return pd_group, npd_pool


# ==============================================================================
# 6. WINDOW & CORNERS
# ==============================================================================

def default_clock_to(clock_obj, default_clock_time):
    """Convert a logging.defaultClock timestamp into the given clock's timebase."""
    return (
        default_clock_time
        + logging.defaultClock.getLastResetTime()
        - clock_obj.getLastResetTime()
    )


def measure_refresh_hz(window):
    """Measure the achieved refresh rate and fall back gracefully if needed."""
    try:
        measured = window.getActualFrameRate(
            nIdentical=20,
            nMaxFrames=240,
            nWarmUpFrames=60,
            threshold=1,
        )
        if measured:
            return float(measured)
    except Exception as e:
        print(f"WARNING: getActualFrameRate failed: {e}")

    try:
        frame_metrics = window.getMsPerFrame(nFrames=120, showVisual=False)
        reference_ms = None
        if isinstance(frame_metrics, (list, tuple)) and frame_metrics:
            reference_ms = frame_metrics[-1] or frame_metrics[0]
        if reference_ms:
            return 1000.0 / float(reference_ms)
    except Exception as e:
        print(f"WARNING: getMsPerFrame failed: {e}")

    return None

win = visual.Window(
    size=[1920, 1080],
    units='pix',
    color=[0, 0, 0],
    fullscr=True,
    screen=0,
    checkTiming=True
)

actual_size = win.size
print(f"Window size: {actual_size[0]} x {actual_size[1]}")
MEASURED_REFRESH_HZ = measure_refresh_hz(win)
ACTIVE_REFRESH_HZ = MEASURED_REFRESH_HZ or FALLBACK_REFRESH_HZ
FRAME_PERIOD_SEC = 1.0 / ACTIVE_REFRESH_HZ if ACTIVE_REFRESH_HZ else (1.0 / FALLBACK_REFRESH_HZ)
HALF_FRAME_SEC = FRAME_PERIOD_SEC / 2.0
BG_UPDATE_EVERY_FRAMES = max(1, int(round(BG_UPDATE_RATE / FRAME_PERIOD_SEC)))
win.monitorFramePeriod = FRAME_PERIOD_SEC
win.recordFrameIntervals = False
win.refreshThreshold = FRAME_PERIOD_SEC * FRAME_DROP_THRESHOLD_FACTOR
if MEASURED_REFRESH_HZ:
    print(f"Measured refresh rate: {MEASURED_REFRESH_HZ:.2f} Hz")
else:
    print(f"WARNING: Could not measure refresh rate; using fallback {FALLBACK_REFRESH_HZ:.1f} Hz")
w, h = actual_size[0] / 4, actual_size[1] / 4
kb = keyboard.Keyboard()
SHARED_CLOCK = kb.clock

CORNERS = {
    'top_right':    [ w,  h],
    'top_left':     [-w,  h],
    'bottom_left':  [-w, -h],
    'bottom_right': [ w, -h],
}


# ==============================================================================
# 7. BACKGROUND NOISE
# ==============================================================================

def load_background():
    print("Loading background noise...")
    try:
        img_array = np.array(Image.open(BG_SOURCE_FILE).convert('L'))
        print(f"Loaded: {BG_SOURCE_FILE}")
    except FileNotFoundError:
        print(f"WARNING: {BG_SOURCE_FILE} not found — using synthetic noise.")
        img_array = np.random.rand(512, 512) * 255

    frames = []
    for _ in range(20):
        fft_data   = np.fft.fftshift(np.fft.fft2(img_array))
        mag        = np.abs(fft_data)
        rand_phase = -np.pi + 2 * np.pi * np.random.random(fft_data.shape)
        recon      = np.real(np.fft.ifft2(np.fft.ifftshift(mag * np.exp(1j * rand_phase))))
        recon      = (recon - recon.min()) / (recon.max() - recon.min())
        frames.append(visual.ImageStim(win, image=(recon * 2) - 1,
                                       size=win.size, opacity=BG_NOISE_OPACITY))
    print("Background ready.\n")
    return frames

noise_stims = load_background()


SHARED_SPEAKER = None
TARGET_OUTPUT_CHANNELS = int(os.environ.get('AV_STUDY_OUTPUT_CHANNELS', '2'))
PTB_PREFLIGHT_LEAD_SEC = float(os.environ.get('AV_STUDY_PTB_PREFLIGHT_LEAD_SEC', '0.5'))


PTB_PREFLIGHT_SUPPORTED = False


def _detect_ptb_preflight_supported(sample_sound=None):
    """Return (supported, diagnostic_string).

    PsychoPy 2026.x doesn't reliably set the module-level ``sound.audioLib``,
    so we inspect a real preloaded Sound instance instead. PTB-backed sounds
    live in ``psychopy.sound.backend_ptb`` and expose ``play(when=...)``.
    """
    import inspect

    if sample_sound is None:
        return False, "no sample sound provided"

    cls = type(sample_sound)
    module = getattr(cls, '__module__', '') or ''
    is_ptb = 'backend_ptb' in module or module.endswith('.SoundPTB')

    play = getattr(sample_sound, 'play', None)
    if play is None:
        return False, f"sound class {module}.{cls.__name__} has no play()"

    try:
        sig = inspect.signature(play)
    except (TypeError, ValueError):
        return False, f"could not introspect play() of {module}.{cls.__name__}"

    accepts_when = 'when' in sig.parameters or any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    )

    diagnostic = (
        f"sound class={module}.{cls.__name__} "
        f"accepts_when={accepts_when} "
        f"sound.audioLib={getattr(sound, 'audioLib', None)!r}"
    )
    return (is_ptb and accepts_when), diagnostic


def _refresh_ptb_preflight_status(sample_sound=None):
    """Re-probe and announce PTB preflight support. Call after preload."""
    global PTB_PREFLIGHT_SUPPORTED
    supported, diag = _detect_ptb_preflight_supported(sample_sound=sample_sound)
    PTB_PREFLIGHT_SUPPORTED = supported
    if PTB_PREFLIGHT_SUPPORTED:
        print(f"PTB preflight scheduling enabled "
              f"(lead {PTB_PREFLIGHT_LEAD_SEC:.3f}s, {diag}).")
    else:
        print(f"PTB preflight scheduling not available; "
              f"using post-flip play(). [{diag}]")
    return PTB_PREFLIGHT_SUPPORTED


def _patch_ptb_channel_count():
    """Clamp PortAudio device NrOutputChannels to TARGET_OUTPUT_CHANNELS.

    PipeWire/PulseAudio often reports virtual devices with 128 output channels.
    PsychoPy opens streams with that count, then can't fill a 2-channel WAV.
    Pulse handles channel up-mix internally, so opening at stereo is safe.
    """
    try:
        import psychtoolbox.audio as ptb_audio
    except Exception as e:
        print(f"  WARNING: could not import psychtoolbox.audio for channel patch: {e}")
        return

    if getattr(ptb_audio.get_devices, '_av_study_patched', False):
        return

    _orig = ptb_audio.get_devices

    def _patched(*args, **kwargs):
        devs = _orig(*args, **kwargs)
        for d in devs:
            try:
                n = float(d.get('NrOutputChannels', 0))
            except Exception:
                continue
            if n > TARGET_OUTPUT_CHANNELS:
                d['NrOutputChannels'] = float(TARGET_OUTPUT_CHANNELS)
        return devs

    _patched._av_study_patched = True
    ptb_audio.get_devices = _patched
    print(f"  Patched psychtoolbox.audio.get_devices to clamp output channels to "
          f"{TARGET_OUTPUT_CHANNELS}.")


def _resolve_shared_speaker():
    """Construct one SpeakerDevice and reuse it for all Sound() calls.

    Bypasses PsychoPy 2026's prefs-based default-device path, which can crash
    when getAvailableDevices() returns an empty list (e.g., misconfigured
    Linux PortAudio/ALSA bridge).
    """
    global SHARED_SPEAKER
    if SHARED_SPEAKER is not None:
        return SHARED_SPEAKER

    _patch_ptb_channel_count()

    try:
        from psychopy.hardware.speaker import SpeakerDevice
    except Exception as e:
        print(f"  WARNING: could not import SpeakerDevice: {e}")
        return None

    try:
        available = SpeakerDevice.getAvailableDevices()
    except Exception as e:
        print(f"  WARNING: SpeakerDevice.getAvailableDevices() failed: {e}")
        available = []

    print(f"  Available speakers (filtered): {[d.get('deviceName') for d in available]}")

    if not available:
        print("  WARNING: no audio output devices visible to PsychoPy. "
              "Sound() calls will fall back to PsychoPy's default-device path.")
        return None

    requested = audio_speaker_name
    chosen = None
    for d in available:
        if d.get('deviceName') == requested:
            chosen = d
            break
    if chosen is None:
        chosen = available[0]
        print(f"  NOTE: requested speaker '{requested}' not found; using "
              f"'{chosen.get('deviceName')}' instead.")

    try:
        SHARED_SPEAKER = SpeakerDevice(
            name=chosen.get('deviceName'),
            latencyClass=audio_latency_mode,
        )
        print(f"  Bound shared speaker: name='{SHARED_SPEAKER.name}' "
              f"index={SHARED_SPEAKER.index} latencyClass={audio_latency_mode}")
    except Exception as e:
        print(f"  WARNING: SpeakerDevice construction failed for "
              f"'{chosen.get('deviceName')}': {type(e).__name__}: {e}")
        SHARED_SPEAKER = None

    return SHARED_SPEAKER


def preload_stimulus_resources():
    """Load visual and audio assets once so trial building stays lightweight.

    Sound objects are instantiated here at startup (not per-trial) so that
    make_event() never blocks on audio init after the participant presses a key.
    sounddevice Sound objects are reusable across trials.
    """
    image_cache = {}
    sound_path_cache = {}
    sound_stim_cache = {}
    failed_sound_items = []

    shared_speaker = _resolve_shared_speaker()

    print("Preloading stimulus resources...")
    for item in animate_pool + inanimate_pool:
        item_name = item['name']

        img_path = get_path(item['cat'], item['obj_num'], 'img')
        try:
            image_cache[item_name] = visual.ImageStim(
                win,
                image=img_path,
                pos=(0, 0),
                size=IMAGE_SIZE,
            )
        except Exception as e:
            print(f"  WARNING: image preload failed {img_path}: {e}")
            image_cache[item_name] = None

        snd_path = get_path(item['cat'], item['obj_num'], 'snd')
        snd_path = normalize_audio(snd_path)
        sound_path_cache[item_name] = snd_path

        # Pre-instantiate Sound object — eliminates blocking init at trial start
        try:
            sound_kwargs = dict(stereo=True, hamming=True, preBuffer=-1)
            if shared_speaker is not None:
                sound_kwargs['speaker'] = shared_speaker
            snd_obj = sound.Sound(snd_path, **sound_kwargs)
            sound_stim_cache[item_name] = snd_obj
        except Exception as e:
            import traceback as _tb
            print(f"  WARNING: sound preload failed {item_name} ({snd_path}): {type(e).__name__}: {e}")
            if os.environ.get('AV_STUDY_DEBUG_AUDIO', '0') == '1':
                _tb.print_exc()
            sound_stim_cache[item_name] = None
            failed_sound_items.append(item_name)

    print("Stimulus preload complete.")
    print(f"  Audio preload failures: {len(failed_sound_items)}")
    if failed_sound_items:
        preview = ', '.join(failed_sound_items[:5])
        print(f"  Failed items (sample): {preview}")
    print("")
    if len(failed_sound_items) > MAX_AUDIO_PRELOAD_FAILURES:
        raise RuntimeError(
            f"Audio preload failed for {len(failed_sound_items)} items. "
            "Fix backend/device and rerun."
        )
    return image_cache, sound_path_cache, sound_stim_cache


IMAGE_STIM_CACHE, SOUND_PATH_CACHE, SOUND_STIM_CACHE = preload_stimulus_resources()
_sample_sound_for_probe = next(iter(SOUND_STIM_CACHE.values()), None) if SOUND_STIM_CACHE else None
_refresh_ptb_preflight_status(sample_sound=_sample_sound_for_probe)


def print_audio_runtime_summary():
    print("Audio runtime config:")
    print(f"  Requested audioLib order: {audio_lib_order}")
    print(f"  Requested latency mode: {audio_latency_mode}")
    print(f"  Requested device: {audio_device_name}")
    print(f"  Requested speaker: {audio_speaker_name}")
    active_lib = getattr(sound, 'audioLib', None)
    if active_lib is not None:
        print(f"  PsychoPy selected backend: {active_lib}")
    print(f"  Canonical audio format: {CANONICAL_AUDIO_HZ} Hz, {CANONICAL_AUDIO_CHANNELS} ch, {CANONICAL_AUDIO_SAMPLE_WIDTH_BYTES * 8}-bit")
    print(f"  Max preload failures before abort: {MAX_AUDIO_PRELOAD_FAILURES}")
    print(f"  Max runtime failures before abort: {MAX_AUDIO_RUNTIME_FAILURES}")


def run_audio_preflight():
    if SKIP_AUDIO_PREFLIGHT:
        print("WARNING: skipping audio preflight (AV_STUDY_SKIP_AUDIO_PREFLIGHT=1)")
        return

    print("\nAudio preflight: playing short calibration tone.")
    try:
        tone_kwargs = dict(value=440, secs=0.25, stereo=True, hamming=True)
        if SHARED_SPEAKER is not None:
            tone_kwargs['speaker'] = SHARED_SPEAKER
        tone = sound.Sound(**tone_kwargs)
        tone.play()
        core.wait(0.35)
        tone.stop()
    except Exception as e:
        raise RuntimeError(f"Audio preflight playback failed: {e}")

    prompt = visual.TextStim(
        win,
        text=(
            "Audio check:\n\n"
            "Did you hear the calibration tone?\n\n"
            "Press Y = yes, N = no, ESC = quit."
        ),
        height=32,
        wrapWidth=1300,
        color='white',
    )
    prompt.draw()
    win.flip()
    resp = event.waitKeys(keyList=['y', 'n', 'escape'])
    choice = resp[0] if resp else 'n'
    if choice == 'escape':
        win.close()
        core.quit()
    if choice != 'y':
        raise RuntimeError(
            "Audio preflight failed: operator did not hear calibration tone. "
            "Check PipeWire sink selection and AV_STUDY_AUDIO_DEVICE."
        )
    print("Audio preflight passed.\n")


def write_audio_preflight_status(passed):
    status_path = os.path.join(data_dir, f"participant_{participant_pid}_audio_preflight.txt")
    with open(status_path, 'w', encoding='utf-8') as f:
        f.write(f"audio_preflight_passed={bool(passed)}\n")
        f.write(f"audio_lib_order={audio_lib_order}\n")
        f.write(f"audio_device={audio_device_name}\n")
        f.write(f"audio_speaker={audio_speaker_name}\n")
        f.write(f"audio_latency_mode={audio_latency_mode}\n")
    print(f"Audio preflight status saved: {status_path}")


print_audio_runtime_summary()
_audio_preflight_passed = False
try:
    run_audio_preflight()
    _audio_preflight_passed = True
finally:
    write_audio_preflight_status(_audio_preflight_passed)


# ==============================================================================
# 8. TRIAL BUILDER 
# ==============================================================================

def build_trial_appearances(block_type, pt_group, pd_group, npd_pool, active_pt_name):
    pt_names      = set(pt_group.keys())
    active_pt     = pt_group[active_pt_name]

    block_pt_names    = {k for k, v in pt_group.items() if v['item']['cat'] == block_type}
    inactive_pt_names = block_pt_names - {active_pt_name}

    target_pool    = (animate_pool if block_type == 'animate' else inanimate_pool)
    npt_candidates = [x for x in target_pool if x['name'] not in pt_names]
    pd_list        = list(pd_group.values())

    appearances = []

    for i in range(random.randint(TRIAL_PT_MIN, TRIAL_PT_MAX)):
        appearances.append({
            'role': 'PT', 'item': active_pt['item'],
            'soa': active_pt['soa'], 'sound': True, 'app_id': f'PT_{i+1}',
        })

    for i in range(random.randint(TRIAL_NPT_MIN, TRIAL_NPT_MAX)):
        appearances.append({
            'role': 'NPT', 'item': random.choice(npt_candidates),
            'soa': None, 'sound': False, 'app_id': f'NPT_{i+1}',
        })

    for i in range(random.randint(TRIAL_PD_MIN, TRIAL_PD_MAX)):
        appearances.append({
            'role': 'PD', 'item': random.choice(pd_list)['item'],
            'soa': round(random.uniform(PD_SOA_MIN, PD_SOA_MAX), 3),
            'sound': True, 'app_id': f'PD_{i+1}',
        })

    for i in range(random.randint(TRIAL_NPD_MIN, TRIAL_NPD_MAX)):
        appearances.append({
            'role': 'NPD', 'item': random.choice(npd_pool),
            'soa': None, 'sound': False, 'app_id': f'NPD_{i+1}',
        })

    return appearances


def build_timeline(appearances, block_type):
    content_end = [TRIAL_BUFFER_DUR + TRIAL_CONTENT_DUR]

    corner_windows     = {c: [] for c in ALL_CORNERS}
    audio_windows      = []
    target_cat_windows = []
    item_windows       = {}
    visual_onsets      = []

    def is_corner_free(corner, start, end):
        return all(end <= ws or start >= we for (ws, we) in corner_windows[corner])

    def is_audio_free(snd_start, snd_end):
        return all(
            snd_end + MIN_AUDIO_GAP <= ws or snd_start >= we + MIN_AUDIO_GAP
            for (ws, we) in audio_windows
        )

    def is_item_free(item_name, start_vis, end_vis):
        windows = item_windows.get(item_name, [])
        return all(end_vis <= ws or start_vis >= we for (ws, we) in windows)

    def is_item_gap_free(item_name, start_vis, end_vis):
        windows = item_windows.get(item_name, [])
        return all(
            end_vis + MIN_SAME_ITEM_GAP <= ws or start_vis >= we + MIN_SAME_ITEM_GAP
            for (ws, we) in windows
        )

    def is_visual_onset_free(start_vis):
        return all(abs(start_vis - existing) >= MIN_VISUAL_ONSET_GAP
                   for existing in visual_onsets)

    def is_target_cat_slot_free(start_vis, end_vis, snd_start):
        zone_start = min(snd_start, start_vis) if snd_start is not None else start_vis
        zone_end   = end_vis + BETWEEN_PT_STIMULUS_GAP
        return all(zone_end <= ws or zone_start >= we
                   for (ws, we) in target_cat_windows)

    def register(corner, start_vis, peak_vis, end_vis, snd_start, snd_end, is_target, item_name):
        corner_windows[corner].append((start_vis, end_vis))
        visual_onsets.append(start_vis)
        if snd_start is not None:
            audio_windows.append((snd_start, snd_end))
        if is_target:
            zone_start = min(snd_start, start_vis) if snd_start is not None else start_vis
            zone_end   = end_vis + BETWEEN_PT_STIMULUS_GAP
            target_cat_windows.append((zone_start, zone_end))
        if item_name not in item_windows:
            item_windows[item_name] = []
        item_windows[item_name].append((start_vis, end_vis))

    def make_event(app, corner, start_vis, snd_start, snd_end):
        peak_vis  = start_vis + FADE_IN_DUR
        end_vis   = peak_vis + PEAK_HOLD_DUR + FADE_OUT_DUR
        is_target = app['role'] in ('PT', 'NPT')
        
        # --- JITTER CALCULATION ---
        # Sample the object center uniformly from anywhere in its quadrant,
        # with a 100px (half image size) clearance from the center axes and
        # screen edges so the object never crosses the quadrant boundary or
        # clips off screen. This gives the illusion of full-screen randomness
        # while preserving the quadrant structure for spatial analysis.
        half_img = IMAGE_SIZE[0] / 2          # 100px
        half_w   = actual_size[0] / 2         # 960px
        half_h   = actual_size[1] / 2         # 540px
        x_min    = half_img                   # 100px from center axis
        x_max    = half_w - half_img          # 860px from center axis
        y_min    = half_img                   # 100px from center axis
        y_max    = half_h - half_img          # 440px from center axis

        # Sign of each axis determines which quadrant
        x_sign = 1 if 'right' in corner else -1
        y_sign = 1 if 'top'   in corner else -1

        jittered_pos = [
            x_sign * random.uniform(x_min, x_max),
            y_sign * random.uniform(y_min, y_max),
        ]

        item_name = app['item']['name']
        vis_stim = IMAGE_STIM_CACHE.get(item_name)
        aud_stim = None
        snd_init_failed = False
        if app['sound'] and snd_start is not None:
            # Use preloaded Sound object — no blocking init at trial start
            cached_snd = SOUND_STIM_CACHE.get(item_name)
            if cached_snd is not None:
                try:
                    cached_snd.stop()  # reset playhead to start
                except Exception:
                    pass
                aud_stim = cached_snd
            else:
                print(f"  WARNING: no preloaded sound for {item_name} — audio skipped")
                snd_init_failed = True
                snd_start = None
                snd_end = None

        correct_key     = CORNER_TO_KEY[corner] if is_target else None
        resp_window_end = (start_vis + RESPONSE_WINDOW) if is_target else None

        return {
            'app_id':              app['app_id'],
            'role':                app['role'],
            'item':                app['item'],
            'friendly_name':       friendly_name(app['item']),
            'soa':                 app['soa'],
            'corner':              corner,
            'correct_key':         correct_key,
            'scheduled_start_vis': start_vis,
            'scheduled_peak_vis':  peak_vis,
            'scheduled_end_vis':   end_vis,
            'scheduled_start_snd': snd_start,
            'scheduled_end_snd':   snd_end,
            'vis_pos':             jittered_pos,
            'start_vis':           start_vis,
            'peak_vis':            peak_vis,
            'end_vis':             end_vis,
            'start_snd':           snd_start,
            'end_snd':             snd_end,
            'requested_start_snd': None,
            'response_window_end': resp_window_end,
            'vis_stim':            vis_stim,
            'aud_stim':            aud_stim,
            'sound_played':        False,
            'sound_is_playing':    False,
            'sound_failed':        snd_init_failed,
            'sound_stopped':       False,
            'sound_start_source':  'failed' if snd_init_failed else '',
            'visual_started':      False,
            'response_made':       False,
            'response_key':        None,
            'response_time':       None,
            'response_in_window':  False,
        }

    def find_free_time(corner, soa, item_name, n_attempts=400):
        content_start = TRIAL_BUFFER_DUR
        ce            = content_end[0]
        latest        = ce - STIM_DUR
        if latest < content_start:
            latest = content_start

        for _ in range(n_attempts):
            start_vis = round(random.uniform(content_start, latest), 3)
            peak_vis  = start_vis + FADE_IN_DUR
            end_vis   = peak_vis + PEAK_HOLD_DUR + FADE_OUT_DUR

            if not is_corner_free(corner, start_vis, end_vis):
                continue
            if not is_item_free(item_name, start_vis, end_vis):
                continue
            if not is_item_gap_free(item_name, start_vis, end_vis):
                continue
            if not is_visual_onset_free(start_vis):
                continue

            snd_start = snd_end = None
            if soa is not None:
                snd_start = peak_vis - soa
                if snd_start < 0:
                    continue
                snd_end   = snd_start + SOUND_DUR
                if not is_audio_free(snd_start, snd_end):
                    continue

            if not is_target_cat_slot_free(start_vis, end_vis, snd_start):
                continue

            return start_vis, snd_start, snd_end

        return None

    def find_free_time_distractor(corner, soa, item_name, n_attempts=400):
        content_start = TRIAL_BUFFER_DUR
        ce            = content_end[0]
        latest        = ce - STIM_DUR
        if latest < content_start:
            latest = content_start

        for _ in range(n_attempts):
            start_vis = round(random.uniform(content_start, latest), 3)
            peak_vis  = start_vis + FADE_IN_DUR
            end_vis   = peak_vis + PEAK_HOLD_DUR + FADE_OUT_DUR

            if not is_corner_free(corner, start_vis, end_vis):
                continue
            if not is_item_free(item_name, start_vis, end_vis):
                continue
            if not is_item_gap_free(item_name, start_vis, end_vis):
                continue
            if not is_visual_onset_free(start_vis):
                continue

            snd_start = snd_end = None
            if soa is not None:
                snd_start = peak_vis - soa
                if snd_start < 0:
                    continue
                snd_end   = snd_start + SOUND_DUR
                if not is_audio_free(snd_start, snd_end):
                    continue

            return start_vis, snd_start, snd_end

        return None

    pt_apps  = [a for a in appearances if a['role'] == 'PT']
    pd_apps  = [a for a in appearances if a['role'] == 'PD']
    npt_apps = [a for a in appearances if a['role'] == 'NPT']
    npd_apps = [a for a in appearances if a['role'] == 'NPD']

    timeline = []

    for app in pt_apps:
        item_name = app['item']['name']

        def draw_pt_corner():
            return ('top_right' if random.random() < TARGET_SPATIAL_BIAS
                    else random.choice(NON_BIASED_CORNERS))

        corner  = draw_pt_corner()
        result  = find_free_time(corner, app['soa'], item_name)
        if result is None:
            other = [c for c in ALL_CORNERS if c != corner]
            random.shuffle(other)
            for c in other:
                result = find_free_time(c, app['soa'], item_name)
                if result:
                    corner = c
                    break
        extends = 0
        while result is None and extends < MAX_WINDOW_EXTENDS:
            content_end[0] += WINDOW_EXTEND_SEC
            extends += 1
            print(f"  [WINDOW EXTEND] {app['app_id']} couldn't fit — "
                  f"extending to {content_end[0]:.1f}s (#{extends})")
            corner = draw_pt_corner()   
            result = find_free_time(corner, app['soa'], item_name)

        if result is None:
            print(f"  !! CRITICAL: Could not place {app['app_id']} — skipped.")
            continue

        start_vis, snd_start, snd_end = result
        peak_vis = start_vis + FADE_IN_DUR
        end_vis  = peak_vis + PEAK_HOLD_DUR + FADE_OUT_DUR
        register(corner, start_vis, peak_vis, end_vis, snd_start, snd_end,
                 is_target=True, item_name=item_name)
        timeline.append(make_event(app, corner, start_vis, snd_start, snd_end))

    for app in pd_apps:
        item_name = app['item']['name']
        corner    = random.choice(ALL_CORNERS)
        result    = find_free_time_distractor(corner, app['soa'], item_name)
        if result is None:
            other = [c for c in ALL_CORNERS if c != corner]
            random.shuffle(other)
            for c in other:
                result = find_free_time_distractor(c, app['soa'], item_name)
                if result:
                    corner = c
                    break
        if result is None:
            print(f"  WARNING: Could not place {app['app_id']} — skipped.")
            continue
        start_vis, snd_start, snd_end = result
        peak_vis = start_vis + FADE_IN_DUR
        end_vis  = peak_vis + PEAK_HOLD_DUR + FADE_OUT_DUR
        register(corner, start_vis, peak_vis, end_vis, snd_start, snd_end,
                 is_target=False, item_name=item_name)
        timeline.append(make_event(app, corner, start_vis, snd_start, snd_end))

    for app in npt_apps:
        item_name = app['item']['name']
        corner    = random.choice(ALL_CORNERS)
        result    = find_free_time(corner, None, item_name)
        if result is None:
            other = [c for c in ALL_CORNERS if c != corner]
            random.shuffle(other)
            for c in other:
                result = find_free_time(c, None, item_name)
                if result:
                    corner = c
                    break
        if result is None:
            print(f"  WARNING: Could not place {app['app_id']} — skipped.")
            continue
        start_vis, snd_start, snd_end = result
        peak_vis = start_vis + FADE_IN_DUR
        end_vis  = peak_vis + PEAK_HOLD_DUR + FADE_OUT_DUR
        register(corner, start_vis, peak_vis, end_vis, None, None,
                 is_target=True, item_name=item_name)
        timeline.append(make_event(app, corner, start_vis, None, None))

    for app in npd_apps:
        item_name = app['item']['name']
        corner    = random.choice(ALL_CORNERS)
        result    = find_free_time_distractor(corner, None, item_name)
        if result is None:
            other = [c for c in ALL_CORNERS if c != corner]
            random.shuffle(other)
            for c in other:
                result = find_free_time_distractor(c, None, item_name)
                if result:
                    corner = c
                    break
        if result is None:
            print(f"  WARNING: Could not place {app['app_id']} — skipped.")
            continue
        start_vis, snd_start, snd_end = result
        peak_vis = start_vis + FADE_IN_DUR
        end_vis  = peak_vis + PEAK_HOLD_DUR + FADE_OUT_DUR
        register(corner, start_vis, peak_vis, end_vis, None, None,
                 is_target=False, item_name=item_name)
        timeline.append(make_event(app, corner, start_vis, None, None))

    timeline.sort(key=lambda e: e['start_vis'])
    return timeline, content_end[0]


# ==============================================================================
# 10. TIMELINE VALIDATOR
# ==============================================================================

def validate_timeline(timeline):
    errors = []

    for i, ev1 in enumerate(timeline):
        for ev2 in timeline[i+1:]:
            if ev1['corner'] == ev2['corner']:
                if not (ev1['end_vis'] <= ev2['start_vis'] or ev2['end_vis'] <= ev1['start_vis']):
                    errors.append(
                        f"VISUAL OVERLAP [{ev1['corner']}]: "
                        f"{ev1['friendly_name']} {ev1['start_vis']:.2f}-{ev1['end_vis']:.2f}s "
                        f"vs {ev2['friendly_name']} {ev2['start_vis']:.2f}-{ev2['end_vis']:.2f}s"
                    )

    visual_onsets = sorted((ev['start_vis'], ev['friendly_name']) for ev in timeline)
    for i in range(len(visual_onsets) - 1):
        t1, n1 = visual_onsets[i]
        t2, n2 = visual_onsets[i + 1]
        gap = t2 - t1
        if gap < MIN_VISUAL_ONSET_GAP:
            errors.append(
                f"VISUAL ONSET GAP VIOLATION: {n1}@{t1:.3f}s vs {n2}@{t2:.3f}s "
                f"(gap={gap:.3f}s < {MIN_VISUAL_ONSET_GAP:.3f}s)"
            )

    same_item_events = {}
    for ev in timeline:
        same_item_events.setdefault(ev['item']['name'], []).append(ev)
    for item_name, item_events in same_item_events.items():
        item_events.sort(key=lambda ev: ev['start_vis'])
        for i in range(len(item_events) - 1):
            left = item_events[i]
            right = item_events[i + 1]
            if right['start_vis'] < left['end_vis']:
                errors.append(
                    f"SAME ITEM OVERLAP [{item_name}]: "
                    f"{left['friendly_name']} {left['start_vis']:.3f}-{left['end_vis']:.3f}s "
                    f"vs {right['start_vis']:.3f}-{right['end_vis']:.3f}s"
                )
                continue
            gap = right['start_vis'] - left['end_vis']
            if gap < MIN_SAME_ITEM_GAP:
                errors.append(
                    f"SAME ITEM GAP VIOLATION [{item_name}]: "
                    f"{left['friendly_name']} gap={gap:.3f}s < {MIN_SAME_ITEM_GAP:.3f}s"
                )

    audio = sorted(
        (ev['start_snd'], ev['end_snd'], ev['friendly_name'])
        for ev in timeline
        if ev['start_snd'] is not None and ev['end_snd'] is not None
    )
    for i, (s1, e1, n1) in enumerate(audio):
        for s2, e2, n2 in audio[i+1:]:
            gap = s2 - e1
            if gap < MIN_AUDIO_GAP:
                errors.append(
                    f"AUDIO GAP VIOLATION: {n1} {s1:.3f}-{e1:.3f}s vs "
                    f"{n2} {s2:.3f}-{e2:.3f}s (gap={gap:.3f}s < {MIN_AUDIO_GAP:.3f}s)"
                )

    if errors:
        print(f"✗ Validation FAILED — {len(errors)} issue(s):")
        for e in errors: print(f"    {e}")
    else:
        print("✓ Timeline valid")

    return len(errors) == 0, errors


def release_audio_stim(ev, context):
    aud_stim = ev.get('aud_stim')
    if aud_stim is None:
        return

    try:
        aud_stim.stop()
    except Exception as e:
        print(f"  WARNING: {context} stop() failed for {ev.get('friendly_name', '?')}: {e}")
    finally:
        # Do NOT delete the Sound object — it lives in SOUND_STIM_CACHE and is
        # reused across trials. Just clear the reference in this event dict.
        ev['aud_stim'] = None
        ev['sound_is_playing'] = False
        ev['sound_stopped'] = True


# ==============================================================================
# 11. CSV SETUP
# ==============================================================================

with open(data_filepath, 'w', newline='') as f:
    csv.writer(f).writerow([
        'appearance_id', 'role', 'object_id', 'object_name', 'category',
        'sound_lead_sec', 'corner', 'target_key',
        'was_displayed',
        'fade_in_start', 'peak_opacity_time', 'fade_out_end',
        'sound_start', 'sound_end', 'response_deadline',
        'scheduled_fade_in_start', 'scheduled_peak_opacity_time', 'scheduled_fade_out_end',
        'scheduled_sound_start', 'scheduled_sound_end', 'requested_sound_start',
        'visual_onset_error_ms', 'sound_onset_error_ms', 'av_sync_error_ms', 'sound_start_source',
        'response_made', 'response_key', 'response_time', 'rt_from_fade_in',
        'response_in_window', 'response_correct',
        'participant_pid', 'block_type', 'trial_num', 'is_practice',
        'active_pt_name', 'active_pt_friendly',
    ])

with open(responses_filepath, 'w', newline='') as f:
    csv.writer(f).writerow([
        'keypress_time', 'key_pressed', 'key_pressed_corner', 'response_type',
        'hit_appearance_id',
        'hit_object', 'hit_role', 'hit_corner', 'hit_sound_lead_sec',
        'rt_from_fade_in', 'rt_from_sound_start', 'hit_sound_start_source', 'response_in_window',
        'fa_pre_visual',
        'most_visible_object', 'most_visible_role', 'most_visible_opacity',
        'most_visible_corner', 'most_visible_sound_lead_sec',
        'sound_playing_object', 'sound_playing_role',
        'sounds_in_last_3sec', 'all_visible_at_keypress',
        'pending_target_appearance_id', 'pending_target_scheduled_fade_in',
        'pending_target_scheduled_sound_start', 'pending_target_time_since_sound',
        'participant_pid', 'block_type', 'trial_num', 'is_practice',
        'active_pt_name', 'active_pt_friendly',
    ])

with open(trials_filepath, 'w', newline='') as f:
    csv.writer(f).writerow([
        'participant_pid', 'block_type', 'trial_num', 'is_practice',
        'active_pt_name', 'active_pt_friendly', 'active_pt_soa',
        'pt_corner_this_trial',
        'n_pt_appearances', 'n_npt_appearances',
        'n_pd_appearances', 'n_npd_appearances', 'total_appearances',
        'trial_duration_sec',
        'n_hits', 'n_false_alarms',
        'pt_hit_rate', 'npt_hit_rate',
        'measured_refresh_hz', 'mean_frame_ms', 'median_frame_ms',
        'max_frame_ms', 'n_long_frames',
        'cpu_temp_c_at_start',
        'trial_start_iso',
    ])


def save_trial_data(trial_num, block_type, active_pt_name, timeline, is_practice,
                    cpu_temp_c_at_start=None):
    pt_item = next((ev['item'] for ev in timeline if ev['role'] == 'PT'), None)
    active_pt_friendly = friendly_name(pt_item) if pt_item else "UNKNOWN_PT"
    try:
        with open(data_filepath, 'a', newline='') as f:
            writer = csv.writer(f)
            for ev in timeline:
                rt = (ev['response_time'] - ev['start_vis']) if ev['response_time'] else ''
                was_displayed = bool(ev['visual_started'])
                if was_displayed:
                    visual_onset_error_ms = round((ev['start_vis'] - ev['scheduled_start_vis']) * 1000, 3)
                else:
                    # Never reached the screen: no measured visual timing exists.
                    # Leave numeric cells blank (was_displayed=False marks the row).
                    visual_onset_error_ms = ''
                sound_onset_error_ms = ''
                av_sync_error_ms = ''
                if ev['scheduled_start_snd'] is not None and ev['start_snd'] is not None:
                    sound_onset_error_ms = round((ev['start_snd'] - ev['scheduled_start_snd']) * 1000, 3)
                    if ev['visual_started']:
                        # Derived from the recorded timestamps, not external hardware.
                        planned_av_offset = ev['scheduled_start_vis'] - ev['scheduled_start_snd']
                        logged_av_offset = ev['start_vis'] - ev['start_snd']
                        av_sync_error_ms = round((logged_av_offset - planned_av_offset) * 1000, 3)

                if ev['role'] in ('PT', 'NPT'):
                    resp_corr = (ev['response_made'] and ev['response_in_window']
                                 and ev['response_key'] is not None
                                 and ev['response_key'] in ev['correct_key'])
                    response_in_window = ev['response_in_window']
                else:
                    resp_corr = False if ev['response_made'] else ''
                    response_in_window = ''

                writer.writerow([
                    ev.get('app_id', ''), ev['role'], ev['item']['name'],
                    ev['friendly_name'], ev['item']['cat'],
                    ev['soa'] if ev['soa'] is not None else '',
                    ev['corner'], ev['correct_key'][0] if ev['correct_key'] else '',
                    was_displayed,
                    round(ev['start_vis'],  4) if was_displayed else '',
                    round(ev['peak_vis'],   4) if was_displayed else '',
                    round(ev['end_vis'],    4) if was_displayed else '',
                    round(ev['start_snd'],  4) if ev['start_snd'] is not None else '',
                    round(ev['end_snd'],    4) if ev['end_snd']   is not None else '',
                    round(ev['response_window_end'], 4)
                    if (was_displayed and ev['response_window_end'] is not None) else '',
                    round(ev['scheduled_start_vis'], 4), round(ev['scheduled_peak_vis'], 4), round(ev['scheduled_end_vis'], 4),
                    round(ev['scheduled_start_snd'], 4) if ev['scheduled_start_snd'] is not None else '',
                    round(ev['scheduled_end_snd'], 4) if ev['scheduled_end_snd'] is not None else '',
                    round(ev['requested_start_snd'], 4) if ev['requested_start_snd'] is not None else '',
                    visual_onset_error_ms, sound_onset_error_ms, av_sync_error_ms, ev.get('sound_start_source', ''),
                    ev['response_made'],
                    ev['response_key'] if ev['response_key'] else '',
                    round(ev['response_time'], 4) if ev['response_time'] else '',
                    round(rt, 4) if rt != '' else '',
                    response_in_window, resp_corr,
                    participant_pid, block_type, trial_num, is_practice,
                    active_pt_name, active_pt_friendly,
                ])
    except Exception as e:
        print(f"  !! ERROR saving trial data: {e}")


def snapshot_scene(timeline, t):
    visible = []
    for ev in timeline:
        if ev['start_vis'] <= t < ev['end_vis']:
            if t < ev['peak_vis']:
                opacity = (t - ev['start_vis']) / FADE_IN_DUR
            elif t < ev['peak_vis'] + PEAK_HOLD_DUR:
                opacity = 1.0
            else:
                opacity = 1.0 - (t - ev['peak_vis'] - PEAK_HOLD_DUR) / FADE_OUT_DUR
            opacity = max(0.0, min(1.0, opacity))
            if opacity > 0:
                visible.append((ev, round(opacity, 3)))

    visible.sort(key=lambda x: x[1], reverse=True)

    salient_ev      = visible[0][0] if visible else None
    salient_opacity = visible[0][1] if visible else 0.0

    sound_now_ev = next(
        (ev for ev in timeline
         if ev['start_snd'] is not None and ev['start_snd'] <= t <= ev['end_snd']),
        None
    )

    fa_pre_visual = (
        salient_ev is not None
        and salient_ev['start_snd'] is not None
        and salient_ev['start_snd'] <= t < salient_ev['peak_vis']
    )

    # ' | ' separator (not ';'): spreadsheet apps with semicolon enabled as a
    # delimiter split ';'-joined cells and misalign every following column.
    all_visible_str = ' | '.join(
        f"{ev['friendly_name']}[{ev['role']}]@opacity={op}@corner={ev['corner']}"
        for ev, op in visible
    ) or 'nothing'

    return {
        'salient_ev':      salient_ev,
        'salient_opacity': salient_opacity,
        'fa_pre_visual':   fa_pre_visual,
        'sound_now_ev':    sound_now_ev,
        'all_visible_str': all_visible_str,
    }


def classify_fa_type(key, key_time, timeline, target_cat):
    target_visible = any(
        ev['item']['cat'] == target_cat and ev['start_vis'] <= key_time < ev['end_vis']
        for ev in timeline
    )
    target_recently_gone = any(
        ev['item']['cat'] == target_cat
        and ev['response_window_end'] is not None
        and ev['response_window_end'] < key_time <= ev['response_window_end'] + FA_LATE_GRACE_SEC
        and not ev['response_made']
        for ev in timeline
    )
    anything_visible = any(
        ev['start_vis'] <= key_time < ev['end_vis'] for ev in timeline
    )

    if target_visible:
        return 'fa_wrong_corner'   
    elif target_recently_gone:
        return 'fa_late'           
    elif anything_visible:
        return 'fa_no_target'      
    else:
        return 'fa_empty'          


def save_trial_summary(trial_num, block_type, is_practice, active_pt_name,
                       active_pt_friendly, timeline, trial_duration, n_false_alarms,
                       frame_stats, cpu_temp_c_at_start=None, trial_start_iso=''):
    pt_evs  = [ev for ev in timeline if ev['role'] == 'PT']
    npt_evs = [ev for ev in timeline if ev['role'] == 'NPT']
    pd_evs  = [ev for ev in timeline if ev['role'] == 'PD']
    npd_evs = [ev for ev in timeline if ev['role'] == 'NPD']

    pt_corner = pt_evs[0]['corner'] if pt_evs else ''
    active_pt_soa = pt_evs[0]['soa'] if pt_evs else ''

    def hit_rate(evs):
        if not evs:
            return ''
        hits = sum(
            1 for ev in evs
            if ev['response_made'] and ev['response_in_window']
            and ev['response_key'] is not None
            and ev['response_key'] in ev['correct_key']
        )
        return round(hits / len(evs), 4)

    n_hits = sum(
        1 for ev in timeline
        if ev['role'] in ('PT', 'NPT')
        and ev['response_made'] and ev['response_in_window']
        and ev['response_key'] is not None
        and ev['response_key'] in ev['correct_key']
    )

    try:
        with open(trials_filepath, 'a', newline='') as f:
            csv.writer(f).writerow([
                participant_pid, block_type, trial_num, is_practice,
                active_pt_name, active_pt_friendly, active_pt_soa,
                pt_corner,
                len(pt_evs), len(npt_evs), len(pd_evs), len(npd_evs), len(timeline),
                round(trial_duration, 4),
                n_hits, n_false_alarms,
                hit_rate(pt_evs), hit_rate(npt_evs),
                round(frame_stats['refresh_hz'], 4) if frame_stats['refresh_hz'] is not None else '',
                round(frame_stats['mean_frame_ms'], 4) if frame_stats['mean_frame_ms'] is not None else '',
                round(frame_stats['median_frame_ms'], 4) if frame_stats['median_frame_ms'] is not None else '',
                round(frame_stats['max_frame_ms'], 4) if frame_stats['max_frame_ms'] is not None else '',
                frame_stats['n_long_frames'],
                round(cpu_temp_c_at_start, 1) if cpu_temp_c_at_start is not None else '',
                trial_start_iso,
            ])
    except Exception as e:
        print(f"  !! ERROR saving trial summary: {e}")


# Must exceed PT_SOA_MAX (3.0): a max-lead PT sound has to stay inside the
# lookback window at the moment of an early (anticipatory) keypress.
SOUND_LOOKBACK_SEC = 4.0

def save_response(trial_num, block_type, is_practice, active_pt_name, active_pt_friendly,
                  key, key_time, response_type, hit_ev, scene, sound_history,
                  timeline=None):
    salient_ev = scene['salient_ev']
    sound_ev   = scene['sound_now_ev']

    recent = [
        e for e in sound_history
        if 0 <= key_time - e['fired_at'] <= SOUND_LOOKBACK_SEC
    ]
    recent.sort(key=lambda x: x['fired_at'], reverse=True)
    recent_sounds_str = ' | '.join(
        f"{e['ev']['friendly_name']}[{e['ev']['role']}]@t={round(e['fired_at'], 4)}"
        for e in recent
    ) or 'none'

    # Nearest *pending* target event: a PT/NPT whose visual hasn't started yet
    # at keypress time. For anticipatory presses (sound heard, image not yet
    # shown) this records which upcoming target most plausibly drove the press.
    pending_id = pending_fade_in = pending_snd_start = pending_since_snd = ''
    if timeline is not None:
        pending = [
            ev for ev in timeline
            if ev['role'] in ('PT', 'NPT')
            and not ev['visual_started']
            and ev['scheduled_start_vis'] > key_time
        ]
        if pending:
            pend_ev = min(pending, key=lambda e: e['scheduled_start_vis'])
            pending_id = pend_ev.get('app_id', '')
            pending_fade_in = round(pend_ev['scheduled_start_vis'], 4)
            snd_t = pend_ev['start_snd'] if pend_ev['start_snd'] is not None \
                else pend_ev['scheduled_start_snd']
            if snd_t is not None:
                pending_snd_start = round(snd_t, 4)
                pending_since_snd = round(key_time - snd_t, 4)

    rt_visual = rt_sound = in_window = None
    hit_item = hit_role = hit_corner = hit_soa = hit_sound_source = None
    hit_app_id = ''
    if hit_ev:
        rt_visual  = round(key_time - hit_ev['start_vis'], 4)
        if hit_ev['start_snd'] is not None and not hit_ev.get('sound_failed'):
            rt_sound = round(key_time - hit_ev['start_snd'], 4)
        in_window  = hit_ev['response_in_window']
        hit_app_id = hit_ev.get('app_id', '')
        hit_item   = hit_ev['friendly_name']
        hit_role   = hit_ev['role']
        hit_corner = hit_ev['corner']
        hit_soa    = hit_ev['soa']
        hit_sound_source = hit_ev.get('sound_start_source')

    try:
        with open(responses_filepath, 'a', newline='') as f:
            csv.writer(f).writerow([
                round(key_time, 4), key, key_to_corner(key), response_type,
                hit_app_id,
                hit_item, hit_role, hit_corner, hit_soa,
                rt_visual, rt_sound, hit_sound_source, in_window,
                scene['fa_pre_visual'],
                salient_ev['friendly_name'] if salient_ev else None,
                salient_ev['role']          if salient_ev else None,
                scene['salient_opacity'],
                salient_ev['corner']        if salient_ev else None,
                salient_ev['soa']           if salient_ev else None,
                sound_ev['friendly_name']   if sound_ev else None,
                sound_ev['role']            if sound_ev else None,
                recent_sounds_str,
                scene['all_visible_str'],
                pending_id, pending_fade_in, pending_snd_start, pending_since_snd,
                participant_pid, block_type, trial_num, is_practice,
                active_pt_name, active_pt_friendly,
            ])
    except Exception as e:
        print(f"  !! ERROR saving response: {e}")


def phase_opacity(sample_time, start_vis, peak_vis):
    """Compute opacity from the actual onset/phase times."""
    if sample_time < peak_vis:
        opacity = (sample_time - start_vis) / FADE_IN_DUR
    elif sample_time < peak_vis + PEAK_HOLD_DUR:
        opacity = 1.0
    else:
        opacity = 1.0 - (sample_time - peak_vis - PEAK_HOLD_DUR) / FADE_OUT_DUR
    return max(0.0, min(MAX_OPACITY, opacity))


def push_participant_data_to_share(reason='session_end'):
    """Best-effort copy of the participant directory to the lab SMB share.

    Called from:
      - the ESC handler in run_trial (reason='escape_abort'), so an early exit
        still gets whatever CSV rows were written before the participant quit.
      - the normal end-of-experiment path (reason='session_complete').

    Safe to call multiple times -- shutil.copytree(..., dirs_exist_ok=True)
    overwrites whatever is already on the share, and local data is the source
    of truth so a failed push is non-fatal.

    Skipped when AV_STUDY_SKIP_SYNC=1 (set by run_study.sh --no-sync).
    """
    if os.environ.get('AV_STUDY_SKIP_SYNC', '0') == '1':
        return

    try:
        import glob as _glob
        import hashlib as _hashlib
        import shutil as _shutil

        def _md5_file(path):
            h = _hashlib.md5()
            with open(path, 'rb') as fh:
                for chunk in iter(lambda: fh.read(65536), b''):
                    h.update(chunk)
            return h.hexdigest()

        _share_glob = (
            f"/run/user/{os.getuid()}/gvfs/"
            f"smb-share:server=psyc-files.ucsc.edu,share=jamal*"
        )
        _share_matches = sorted(_glob.glob(_share_glob))
        _share_root = _share_matches[0] if _share_matches else None

        if _share_root is None:
            print(
                f"\n[sync:{reason}] Lab share not mounted; data is safe at:\n"
                f"       {data_dir}\n"
                f"       To push later, run from a terminal:\n"
                f"           gio mount smb://psyc-files.ucsc.edu/jamal\n"
                f"           cp -rp {data_dir} \\\n"
                f"               \"/run/user/$(id -u)/gvfs/\"smb-share:*share=jamal*/"
                f"Experiments/Anthony/AudioVisualSpatiotemporalStudy-codex-sanji-runtime-bundle/data/",
                flush=True,
            )
            return

        _dest_data = os.path.join(
            _share_root,
            "Experiments/Anthony/AudioVisualSpatiotemporalStudy-codex-sanji-runtime-bundle/data",
        )
        os.makedirs(_dest_data, exist_ok=True)

        # diag_run.log is held open by run_diag.py; the OS lets us read it
        # anyway. Snapshot it into the participant dir so the run log travels
        # with the data on the share. The final boilerplate lines won't be
        # captured, but all experiment output is.
        _diag_src = os.path.join(STUDY_DIR, 'diag_run.log')
        if os.path.exists(_diag_src):
            try:
                _shutil.copy(_diag_src, os.path.join(data_dir, 'diag_run.log'))
            except OSError as _e:
                print(f"[sync:{reason}] could not snapshot diag_run.log ({_e}); continuing.",
                      flush=True)

        _dest_pid_dir = os.path.join(_dest_data, participant_pid)

        # Content-only copy + checksum verification. shutil.copytree/copy2
        # try to preserve timestamps/permissions, which GVFS SMB rejects
        # (Errno 95) — making a fully successful copy report as failed.
        verified, failed = [], []
        for _root, _dirs, _files in os.walk(data_dir):
            _rel = os.path.relpath(_root, data_dir)
            _dest_root = _dest_pid_dir if _rel == '.' else os.path.join(_dest_pid_dir, _rel)
            os.makedirs(_dest_root, exist_ok=True)
            for _fn in _files:
                _src = os.path.join(_root, _fn)
                _dst = os.path.join(_dest_root, _fn)
                try:
                    _shutil.copyfile(_src, _dst)
                    if _md5_file(_src) == _md5_file(_dst):
                        verified.append(_fn)
                    else:
                        failed.append((_fn, 'checksum mismatch after copy'))
                except OSError as _e:
                    failed.append((_fn, f'{type(_e).__name__}: {_e}'))

        if failed:
            print(f"\n[sync:{reason}] PARTIAL push for participant {participant_pid}: "
                  f"{len(verified)} file(s) verified, {len(failed)} FAILED:", flush=True)
            for _fn, _why in failed:
                print(f"       FAILED  {_fn}  ({_why})", flush=True)
            print(f"       Local data remains the source of truth: {data_dir}", flush=True)
        else:
            print(
                f"\n[sync:{reason}] Pushed participant {participant_pid} to lab share "
                f"({len(verified)} files, all checksums verified):\n"
                f"       {_dest_pid_dir}",
                flush=True,
            )
    except Exception as _e:
        print(
            f"\n[sync:{reason}] WARNING: lab-share push failed ({type(_e).__name__}: {_e})\n"
            f"       Data is still safe at {data_dir}\n"
            f"       Manual catch-up: cp -rp {data_dir} <share>/Experiments/Anthony/"
            f"AudioVisualSpatiotemporalStudy-codex-sanji-runtime-bundle/data/",
            flush=True,
        )


def summarize_frame_intervals(frame_intervals):
    """Return frame timing diagnostics for this trial."""
    if not frame_intervals:
        return {
            'refresh_hz': ACTIVE_REFRESH_HZ,
            'mean_frame_ms': None,
            'median_frame_ms': None,
            'max_frame_ms': None,
            'n_long_frames': 0,
        }

    intervals = np.array(frame_intervals, dtype=float)
    expected_frame_ms = FRAME_PERIOD_SEC * 1000.0
    median_frame_ms = float(np.median(intervals) * 1000.0)
    return {
        'refresh_hz': (1000.0 / median_frame_ms) if median_frame_ms > 0 else ACTIVE_REFRESH_HZ,
        'mean_frame_ms': float(np.mean(intervals) * 1000.0),
        'median_frame_ms': median_frame_ms,
        'max_frame_ms': float(np.max(intervals) * 1000.0),
        'n_long_frames': int(np.sum((intervals * 1000.0) > (expected_frame_ms * FRAME_DROP_THRESHOLD_FACTOR))),
    }


# ==============================================================================
# 12. DEBUG SCREEN
# ==============================================================================

def show_debug_screen(pt_group, pd_group_animate, npd_pool_animate,
                      pd_group_inanimate, npd_pool_inanimate):
    lines = [
        "━━━  DEBUG: Participant Stimulus Assignment  ━━━\n",
        "PRIVILEGED TARGETS  (sound plays a fixed amount before image appears — same every time)",
        f"  Sound lead time range: {PT_SOA_MIN}–{PT_SOA_MAX}s   "
        f"(e.g. 2.45s = sound plays 2.45s before image reaches full brightness)",
    ]
    for name, info in pt_group.items():
        lines.append(f"    [{info['item']['cat'].upper()[:4]}]  "
                     f"{friendly_name(info['item']):35s}  "
                     f"sound leads by {info['soa']:.2f}s (fixed)")

    lines.append("\n── ANIMATE BLOCK  (target = animate, distractors = inanimate) ──")
    lines.append("  Privileged Distractors  [have sound, but lead time is random every appearance]:")
    for name, info in pd_group_animate.items():
        lines.append(f"    [PD]   {friendly_name(info['item']):35s}  "
                     f"random lead {PD_SOA_MIN}–{PD_SOA_MAX}s each time")
    lines.append("  Non-Privileged Distractors  [no sound, visual only]:")
    for item in npd_pool_animate:
        lines.append(f"    [NPD]  {friendly_name(item)}")
    lines.append(f"  Pool sizes: {len(pd_group_animate)} PD  |  {len(npd_pool_animate)} NPD")

    lines.append("\n── INANIMATE BLOCK  (target = inanimate, distractors = animate) ──")
    lines.append("  Privileged Distractors  [have sound, but lead time is random every appearance]:")
    for name, info in pd_group_inanimate.items():
        lines.append(f"    [PD]   {friendly_name(info['item']):35s}  "
                     f"random lead {PD_SOA_MIN}–{PD_SOA_MAX}s each time")
    lines.append("  Non-Privileged Distractors  [no sound, visual only]:")
    for item in npd_pool_inanimate:
        lines.append(f"    [NPD]  {friendly_name(item)}")
    lines.append(f"  Pool sizes: {len(pd_group_inanimate)} PD  |  {len(npd_pool_inanimate)} NPD")

    lines.append(f"\n  Block order: {' → '.join(b.upper() for b in block_order)}")
    lines.append("\nPress any key to continue to instructions.")

    visual.TextStim(win, text='\n'.join(lines),
                    height=20, wrapWidth=1700, color='white', pos=[0, 0]).draw()
    win.flip()
    event.waitKeys()


# ==============================================================================
# 13. TRIAL RUNNER
# ==============================================================================

def run_trial(trial_num, block_type, active_pt_name, pt_group, pd_group, npd_pool, is_practice=False):
    global AUDIO_RUNTIME_FAILURES
    # Trial-boundary CPU temp sample. Single sysfs read (~50us); zero
    # per-frame cost. Captured BEFORE timeline / appearances build so it
    # reflects "ambient" thermal state at trial entry, not work in this trial.
    cpu_temp_c_at_start  = _cpu_temp_celsius()
    # Wall-clock label for this trial (fatigue / time-on-task analyses).
    # Never used in RT math — all reaction times stay on SHARED_CLOCK.
    trial_start_iso      = datetime.now().isoformat(timespec='milliseconds')
    appearances          = build_trial_appearances(block_type, pt_group, pd_group, npd_pool, active_pt_name)
    timeline, actual_content_end = build_timeline(appearances, block_type)
    is_valid, _          = validate_timeline(timeline)

    if not is_valid:
        print("  *** WARNING: Timeline issues detected. Continuing. ***")

    total_dur = actual_content_end + TRIAL_BUFFER_DUR

    active_pt_friendly = "UNKNOWN_PT"
    try:
        active_pt_friendly = friendly_name(pt_group[active_pt_name]['item'])
    except KeyError as e:
        print(f"  WARNING: active_pt_name '{active_pt_name}' not found in pt_group: {e}")

    print(f"\n  Trial {trial_num} ({block_type.upper()}) — "
          f"target group: {block_type.upper()} — duration: {total_dur:.1f}s")
    for ev in timeline:
        snd = (f"  sound@{ev['start_snd']:.2f}s (SOA {ev['soa']:.2f}s)"
               if ev['start_snd'] is not None else "")
        print(f"    [{ev['role']:3s}] {ev['friendly_name']:28s} {ev['corner']:13s} "
              f"vis={ev['start_vis']:.2f}-{ev['end_vis']:.2f}s{snd}")

    # Use the keyboard backend clock for both stimulus and response timing so
    # keypress.rt and our onset timestamps stay in the same timebase.
    trial_clock = SHARED_CLOCK
    trial_clock.reset()
    kb.clearEvents()

    sound_history = []
    false_alarms = 0
    frame_intervals = []
    last_flip_trial = None

    # ── FIXATION CROSS ────────────────────────────────────────────────────────
    # One ShapeStim reused all trial; lineColor is only touched on state
    # changes (hit flash on/off), never per frame.
    _fix_half = FIXATION_SIZE / 2
    fixation_cross = visual.ShapeStim(
        win,
        vertices=((0, -_fix_half), (0, _fix_half), (0, 0),
                  (-_fix_half, 0), (_fix_half, 0)),
        closeShape=False,
        lineColor=FIXATION_COLOR,
        lineWidth=FIXATION_LINE_WIDTH,
        pos=(0, 0),
        autoLog=False,
    )
    fix_flash_until = None   # trial-clock time until which the cross shows green
    fix_is_green = False
    # ─────────────────────────────────────────────────────────────────────────

    # ── DEBUG MARKERS ─────────────────────────────────────────────────────────
    # Controlled by DEBUG_OVERLAY in config -- flip to False before real runs.
    if DEBUG_OVERLAY:
        _hw, _hh = win.size[0] / 2, win.size[1] / 2
        debug_fix_h = visual.Line(win, start=(-_hw, 0), end=(_hw, 0), lineColor='white', lineWidth=1)
        debug_fix_v = visual.Line(win, start=(0, -_hh), end=(0, _hh), lineColor='white', lineWidth=1)
        debug_corner_dots = [
            visual.Circle(win, radius=8, pos=CORNERS[c], fillColor='red', lineColor='red')
            for c in ALL_CORNERS
        ]
        debug_timer = visual.TextStim(win, text='t=0.0000s | frame=0', pos=(0, -_hh + 30),
                                      height=22, color='yellow', bold=True)
    # ─────────────────────────────────────────────────────────────────────────

    frame_n = 0

    while trial_clock.getTime() < total_dur:
        t = trial_clock.getTime()

        noise_stims[(frame_n // BG_UPDATE_EVERY_FRAMES) % len(noise_stims)].draw()

        want_green = fix_flash_until is not None and t < fix_flash_until
        if want_green != fix_is_green:
            fixation_cross.lineColor = (
                FIXATION_HIT_COLOR if want_green else FIXATION_COLOR
            )
            fix_is_green = want_green
        fixation_cross.draw()

        if DEBUG_OVERLAY:
            debug_fix_h.draw()
            debug_fix_v.draw()
            for dot in debug_corner_dots:
                dot.draw()
            debug_timer.text = (
                f't={t:.4f}s | frame={frame_n} | '
                f'display={ACTIVE_REFRESH_HZ:.2f}Hz'
            )
            debug_timer.draw()

        next_flip_trial = win.getFutureFlipTime(clock=trial_clock)
        next_flip_ptb = win.getFutureFlipTime(clock='ptb')
        ptb_offset = next_flip_ptb - next_flip_trial
        frame_sample_t = next_flip_trial + HALF_FRAME_SEC

        frame_visual_onsets = []
        frame_sound_onsets = []
        for ev in timeline:
            if (ev['aud_stim'] is not None
                    and ev['sound_played']
                    and not ev.get('sound_stopped', False)
                    and ev['end_snd'] is not None
                    and t >= ev['end_snd']):
                try:
                    ev['aud_stim'].stop()
                except Exception as e:
                    print(f"  WARNING: stop() failed for {ev['friendly_name']}: {e}")
                ev['sound_is_playing'] = False
                ev['sound_stopped'] = True

            if (ev['scheduled_start_snd'] is not None and ev['aud_stim'] is not None
                    and not ev['sound_played']):
                target_trial = ev['scheduled_start_snd']
                lead_remaining = target_trial - next_flip_trial

                if PTB_PREFLIGHT_SUPPORTED and lead_remaining <= PTB_PREFLIGHT_LEAD_SEC \
                        and lead_remaining > HALF_FRAME_SEC:
                    target_ptb = target_trial + ptb_offset
                    try:
                        ev['aud_stim'].play(when=target_ptb)
                        ev['sound_played'] = True
                        ev['scheduled_ptb_target'] = target_ptb
                        frame_sound_onsets.append((ev, target_trial, 'ptb_preflight'))
                    except Exception as e:
                        print(f"  WARNING: PTB preflight play(when=) failed for "
                              f"{ev['friendly_name']}: {e}; will retry immediate play().")

                elif next_flip_trial >= target_trial - HALF_FRAME_SEC:
                    try:
                        ev['aud_stim'].play()
                        ev['sound_played'] = True
                        source = 'ptb_postflip' if PTB_PREFLIGHT_SUPPORTED else 'sounddevice_postflip'
                        frame_sound_onsets.append((ev, next_flip_trial, source))
                    except Exception as e:
                        print(f"  ERROR playing sound: {e}")
                        AUDIO_RUNTIME_FAILURES += 1
                        ev['sound_played'] = True
                        ev['sound_failed'] = True
                        ev['start_snd'] = None
                        ev['end_snd'] = None
                        ev['sound_start_source'] = 'failed'
                        ev['sound_is_playing'] = False
                        ev['sound_stopped'] = True
                        if AUDIO_RUNTIME_FAILURES > MAX_AUDIO_RUNTIME_FAILURES:
                            raise RuntimeError(
                                f"Audio runtime failure threshold exceeded "
                                f"({AUDIO_RUNTIME_FAILURES} failures)."
                            )

            if not ev['visual_started']:
                visual_start = ev['scheduled_start_vis']
                peak_vis = ev['scheduled_peak_vis']
                visual_end = ev['scheduled_end_vis']
                if visual_start <= next_flip_trial < visual_end:
                    frame_visual_onsets.append(ev)
                    visual_start = next_flip_trial
                    peak_vis = visual_start + FADE_IN_DUR
                    visual_end = peak_vis + PEAK_HOLD_DUR + FADE_OUT_DUR
            else:
                visual_start = ev['start_vis']
                peak_vis = ev['peak_vis']
                visual_end = ev['end_vis']

            if ev['vis_stim'] is not None and visual_start <= frame_sample_t < visual_end:
                ev['vis_stim'].pos = ev['vis_pos']
                ev['vis_stim'].opacity = phase_opacity(next_flip_trial, visual_start, peak_vis)
                ev['vis_stim'].draw()

        flip_time_default = win.flip()
        flip_time = (
            default_clock_to(trial_clock, flip_time_default)
            if flip_time_default is not None else trial_clock.getTime()
        )
        if last_flip_trial is not None:
            frame_intervals.append(flip_time - last_flip_trial)
        last_flip_trial = flip_time
        frame_n += 1

        for ev in frame_visual_onsets:
            if ev['visual_started']:
                continue
            ev['visual_started'] = True
            ev['start_vis'] = flip_time
            ev['peak_vis'] = flip_time + FADE_IN_DUR
            ev['end_vis'] = ev['peak_vis'] + PEAK_HOLD_DUR + FADE_OUT_DUR
            if ev['role'] in ('PT', 'NPT'):
                ev['response_window_end'] = ev['start_vis'] + RESPONSE_WINDOW

        for ev, requested_sound_time, source in frame_sound_onsets:
            if source == 'ptb_preflight':
                start_snd = requested_sound_time
            elif source in ('sounddevice_postflip', 'ptb_postflip'):
                start_snd = trial_clock.getTime()
            else:
                start_snd = trial_clock.getTime()
                source = 'unknown_postflip'
            ev['sound_start_source'] = source
            ev['requested_start_snd'] = (
                requested_sound_time if requested_sound_time is not None else start_snd
            )
            ev['start_snd'] = start_snd
            ev['end_snd'] = start_snd + SOUND_DUR
            ev['sound_is_playing'] = True
            ev['sound_stopped'] = False
            sound_history.append({'ev': ev, 'fired_at': start_snd})

        keys = kb.getKeys(keyList=ALL_RESPONSE_KEYS + ['escape'], waitRelease=False, clear=True)
        for keypress in keys:
            key = keypress.name
            key_time = keypress.rt
            if key == 'escape':
                save_trial_data(trial_num, block_type, active_pt_name, timeline, is_practice,
                                cpu_temp_c_at_start=cpu_temp_c_at_start)
                trial_duration_so_far = trial_clock.getTime()
                frame_stats_esc = summarize_frame_intervals(frame_intervals)
                active_pt_friendly_esc = "UNKNOWN_PT"
                try:
                    active_pt_friendly_esc = friendly_name(pt_group[active_pt_name]['item'])
                except KeyError:
                    pass
                save_trial_summary(
                    trial_num, block_type, is_practice,
                    active_pt_name, active_pt_friendly_esc,
                    timeline, trial_duration_so_far, false_alarms, frame_stats_esc,
                    cpu_temp_c_at_start=cpu_temp_c_at_start,
                    trial_start_iso=trial_start_iso,
                )
                for ev in timeline:
                    release_audio_stim(ev, context='escape cleanup')
                win.close()
                # Push whatever local CSVs exist so far. Done after
                # win.close() so network jitter can't bleed into the frame
                # loop, and before core.quit() because core.quit() raises
                # SystemExit and skips the bottom-of-file sync block.
                push_participant_data_to_share(reason='escape_abort')
                core.quit()

            elif key in ALL_RESPONSE_KEYS:
                target_cat = block_type
                scene      = snapshot_scene(timeline, key_time)

                hit_ev = None
                for ev in timeline:
                    if (ev['visual_started']
                            and ev['item']['cat'] == target_cat
                            and not ev['response_made']
                            and key in ev['correct_key']
                            and ev['start_vis'] <= key_time <= ev['response_window_end']):
                        hit_ev = ev
                        break

                if hit_ev:
                    hit_ev['response_made']      = True
                    hit_ev['response_key']       = key
                    hit_ev['response_time']      = key_time
                    hit_ev['response_in_window'] = True
                    fix_flash_until = key_time + FIXATION_FLASH_DUR

                    response_type = 'hit'
                    rt = key_time - hit_ev['start_vis']
                    print(f"  ✓ [{hit_ev['role']:3s}] {hit_ev['friendly_name']} "
                          f"key={key} RT={rt:.3f}s | "
                          f"salient: {scene['salient_ev']['friendly_name'] if scene['salient_ev'] else 'none'} | "
                          f"sound: {scene['sound_now_ev']['friendly_name'] if scene['sound_now_ev'] else 'none'}")

                    save_response(trial_num, block_type, is_practice,
                                  active_pt_name, active_pt_friendly,
                                  key, key_time, response_type,
                                  hit_ev, scene, sound_history,
                                  timeline=timeline)

                else:
                    fa_type = classify_fa_type(key, key_time, timeline, target_cat)
                    false_alarms += 1
                    matched_late_ev = None

                    if fa_type == 'fa_late':
                        for ev in timeline:
                            if (ev['item']['cat'] == target_cat
                                    and not ev['response_made']
                                    and key in ev['correct_key']
                                    and ev['response_window_end'] is not None
                                    and ev['response_window_end'] < key_time <= ev['response_window_end'] + FA_LATE_GRACE_SEC):
                                ev['response_made']      = True
                                ev['response_key']       = key
                                ev['response_time']      = key_time
                                ev['response_in_window'] = False
                                matched_late_ev = ev
                                break

                    salient = scene['salient_ev']
                    snd_now = scene['sound_now_ev']
                    print(f"  ✗ FA [{fa_type}] key={key} t={key_time:.3f}s | "
                          f"salient: {salient['friendly_name'] if salient else 'nothing'} "
                          f"({scene['salient_opacity']:.0%}) | "
                          f"sound: {snd_now['friendly_name'] if snd_now else 'none'} | "
                          f"pre-vis: {scene['fa_pre_visual']}")

                    save_response(trial_num, block_type, is_practice,
                                  active_pt_name, active_pt_friendly,
                                  key, key_time, fa_type,
                                  matched_late_ev, scene, sound_history,
                                  timeline=timeline)

    for ev in timeline:
        release_audio_stim(ev, context='trial cleanup')

    save_trial_data(trial_num, block_type, active_pt_name, timeline, is_practice,
                    cpu_temp_c_at_start=cpu_temp_c_at_start)
    frame_stats = summarize_frame_intervals(frame_intervals)

    valid_responses = sum(
        1 for ev in timeline
        if ev['role'] in ('PT', 'NPT')
        and ev['response_made']
        and ev['response_in_window']
        and ev['response_key'] is not None
        and ev['response_key'] in ev['correct_key']
    )

    if frame_stats['mean_frame_ms'] is not None:
        print(f"  Frame timing: median={frame_stats['median_frame_ms']:.3f} ms | "
              f"max={frame_stats['max_frame_ms']:.3f} ms | "
              f"long frames={frame_stats['n_long_frames']}")

    active_pt_friendly_local = "UNKNOWN_PT"
    try:
        active_pt_friendly_local = friendly_name(pt_group[active_pt_name]['item'])
    except KeyError:
        pass
    save_trial_summary(
        trial_num, block_type, is_practice,
        active_pt_name, active_pt_friendly_local,
        timeline, total_dur, false_alarms, frame_stats,
        cpu_temp_c_at_start=cpu_temp_c_at_start,
        trial_start_iso=trial_start_iso,
    )

    return {
        'valid_responses': valid_responses,
        'false_alarms':    false_alarms,
        'target_group':    block_type.upper(),
        'total_stimuli':   len(timeline),
    }


def write_session_info(pt_group, pd_group_animate, npd_pool_animate,
                       pd_group_inanimate, npd_pool_inanimate, block_order):
    """Write one machine-readable snapshot of this session's design and config.

    Everything in here is otherwise scattered across the debug screen,
    diag_run.log prose, and inference from the CSVs. One small JSON per
    participant makes "which settings/stimuli was participant N run with?"
    a file lookup instead of an archaeology project.
    """
    import hashlib
    import json
    import subprocess

    def _md5(path):
        try:
            h = hashlib.md5()
            with open(path, 'rb') as fh:
                for chunk in iter(lambda: fh.read(65536), b''):
                    h.update(chunk)
            return h.hexdigest()
        except OSError:
            return None

    git_hash = None
    try:
        git_hash = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'],
            cwd=STUDY_DIR, stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except Exception:
        pass

    psychopy_version = None
    try:
        import psychopy
        psychopy_version = psychopy.__version__
    except Exception:
        pass

    image_fingerprints = {}
    audio_fingerprints = {}
    for item in animate_pool + inanimate_pool:
        img_path = get_path(item['cat'], item['obj_num'], 'img')
        image_fingerprints[item['name']] = {
            'path': img_path, 'md5': _md5(os.path.join(STUDY_DIR, img_path)
                                          if not os.path.isabs(img_path) else img_path),
        }
        snd_path = SOUND_PATH_CACHE.get(item['name'])
        if snd_path:
            audio_fingerprints[item['name']] = {
                'path': snd_path, 'md5': _md5(os.path.join(STUDY_DIR, snd_path)
                                              if not os.path.isabs(snd_path) else snd_path),
            }

    info = {
        'participant_pid': participant_pid,
        'session_start_iso': datetime.now().isoformat(timespec='seconds'),
        'script_git_hash': git_hash,
        'psychopy_version': psychopy_version,
        'block_order': block_order,
        'pt_assignments': {
            name: {
                'friendly': friendly_name(v['item']),
                'object_id': v['item']['name'],
                'category': v['item']['cat'],
                'sound_lead_sec': v['soa'],
            }
            for name, v in pt_group.items()
        },
        'pd_assignments': {
            'animate_block': [friendly_name(v['item']) for v in pd_group_animate.values()],
            'inanimate_block': [friendly_name(v['item']) for v in pd_group_inanimate.values()],
        },
        'npd_pools': {
            'animate_block': [friendly_name(it) for it in npd_pool_animate],
            'inanimate_block': [friendly_name(it) for it in npd_pool_inanimate],
        },
        'config': {
            'RESPONSE_WINDOW': RESPONSE_WINDOW,
            'FA_LATE_GRACE_SEC': FA_LATE_GRACE_SEC,
            'FADE_IN_DUR': FADE_IN_DUR,
            'PEAK_HOLD_DUR': PEAK_HOLD_DUR,
            'FADE_OUT_DUR': FADE_OUT_DUR,
            'SOUND_DUR': SOUND_DUR,
            'SOUND_LOOKBACK_SEC': SOUND_LOOKBACK_SEC,
            'PT_SOA_MIN': PT_SOA_MIN, 'PT_SOA_MAX': PT_SOA_MAX,
            'PD_SOA_MIN': PD_SOA_MIN, 'PD_SOA_MAX': PD_SOA_MAX,
            'NUM_ANIMATE_TRIALS': NUM_ANIMATE_TRIALS,
            'NUM_INANIMATE_TRIALS': NUM_INANIMATE_TRIALS,
            'TRIAL_PT_MIN': TRIAL_PT_MIN, 'TRIAL_PT_MAX': TRIAL_PT_MAX,
            'TRIAL_NPT_MIN': TRIAL_NPT_MIN, 'TRIAL_NPT_MAX': TRIAL_NPT_MAX,
            'TRIAL_PD_MIN': TRIAL_PD_MIN, 'TRIAL_PD_MAX': TRIAL_PD_MAX,
            'TRIAL_NPD_MIN': TRIAL_NPD_MIN, 'TRIAL_NPD_MAX': TRIAL_NPD_MAX,
            'TRIAL_CONTENT_DUR': TRIAL_CONTENT_DUR,
            'TRIAL_BUFFER_DUR': TRIAL_BUFFER_DUR,
            'MIN_VISUAL_ONSET_GAP': MIN_VISUAL_ONSET_GAP,
            'MIN_SAME_ITEM_GAP': MIN_SAME_ITEM_GAP,
            'MIN_AUDIO_GAP': MIN_AUDIO_GAP,
            'TARGET_SPATIAL_BIAS': TARGET_SPATIAL_BIAS,
            'IMAGE_SIZE': IMAGE_SIZE,
            'PT_SUBBLOCK_ORDER': PT_SUBBLOCK_ORDER,
            'PTB_PREFLIGHT_LEAD_SEC': PTB_PREFLIGHT_LEAD_SEC,
            'FIXATION_SIZE': FIXATION_SIZE,
            'FIXATION_LINE_WIDTH': FIXATION_LINE_WIDTH,
            'FIXATION_COLOR': FIXATION_COLOR,
            'FIXATION_HIT_COLOR': FIXATION_HIT_COLOR,
            'FIXATION_FLASH_DUR': FIXATION_FLASH_DUR,
        },
        'display': {
            'measured_refresh_hz': MEASURED_REFRESH_HZ,
            'active_refresh_hz': ACTIVE_REFRESH_HZ,
        },
        'audio': {
            'lib_order': audio_lib_order,
            'device': audio_device_name,
            'speaker': audio_speaker_name,
            'latency_mode': audio_latency_mode,
            'prefer_cleaned': PREFER_CLEANED_AUDIO,
            'ptb_preflight_supported': PTB_PREFLIGHT_SUPPORTED,
        },
        'images': {
            'prefer_normalized': PREFER_NORMALIZED_IMAGES,
        },
        'stimulus_fingerprints': {
            'images': image_fingerprints,
            'audio': audio_fingerprints,
        },
    }

    info_path = os.path.join(data_dir, 'session_info.json')
    try:
        with open(info_path, 'w', encoding='utf-8') as fh:
            json.dump(info, fh, indent=2, default=str)
        print(f"Session info saved: {info_path}")
    except Exception as e:
        print(f"  !! ERROR saving session_info.json: {e}")


# ==============================================================================
# 14. EXPERIMENT SETUP & ASSIGNMENT
# ==============================================================================

pt_group = assign_pt_group()

pd_group_animate,   npd_pool_animate   = assign_pd_group(pt_group, 'animate')
pd_group_inanimate, npd_pool_inanimate = assign_pd_group(pt_group, 'inanimate')

block_order = random.choice([['animate', 'inanimate'], ['inanimate', 'animate']])

print("\nPT Group:")
for name, info in pt_group.items():
    print(f"  {friendly_name(info['item'])} — SOA {info['soa']}s")
print(f"\nPD Animate block: {[friendly_name(v['item']) for v in pd_group_animate.values()]}")
print(f"PD Inanimate block: {[friendly_name(v['item']) for v in pd_group_inanimate.values()]}")
print(f"Block order: {block_order}")

write_session_info(pt_group, pd_group_animate, npd_pool_animate,
                   pd_group_inanimate, npd_pool_inanimate, block_order)

show_debug_screen(pt_group, pd_group_animate, npd_pool_animate,
                  pd_group_inanimate, npd_pool_inanimate)


# ==============================================================================
# 15. INSTRUCTIONS
# ==============================================================================

# Participant-facing words for the two block types. The hit logic accepts ANY
# target-category item (PT and NPT), so all screens must describe the task as
# a category, never a single object.
BLOCK_FRIENDLY = {'animate': 'ANIMALS', 'inanimate': 'OBJECTS'}
BLOCK_FRIENDLY_SINGULAR = {'animate': 'animal', 'inanimate': 'object'}

visual.TextStim(
    win,
    text="""Welcome to the AV Spatiotemporal Awareness Study

You will see objects appear and disappear in the corners of the screen.
Some objects will be accompanied by sounds.

YOUR TASK:
Each block has a TARGET GROUP: either ANIMALS or OBJECTS.
Whenever ANY item from your target group appears, press the
NUMPAD key matching its corner — as quickly as possible.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    4 = Top Left     |  5 = Top Right
    1 = Bottom Left  |  2 = Bottom Right
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

You have 1.5 seconds after a target appears to respond.
Respond to EVERY item from your target group — ignore the rest.

Press any key to begin the practice trial.""",
    height=26, wrapWidth=1400, color='white'
).draw()
win.flip()
event.waitKeys()


# ==============================================================================
# 16. PRACTICE
# ==============================================================================

practice_schedule = []
for pt_name, pt_info in pt_group.items():
    cat          = pt_info['item']['cat']
    cat_pt_group = {k: v for k, v in pt_group.items() if v['item']['cat'] == cat}
    pd_g         = pd_group_animate   if cat == 'animate' else pd_group_inanimate
    npd_p        = npd_pool_animate   if cat == 'animate' else npd_pool_inanimate
    practice_schedule.append({
        'block_type': cat,
        'pt_name':    pt_name,
        'pt_group':   cat_pt_group,
        'pd_group':   pd_g,
        'npd_pool':   npd_p,
    })

random.shuffle(practice_schedule)  

total_practice = len(practice_schedule)

for p, prac in enumerate(practice_schedule):
    pt_label = friendly_name(prac['pt_group'][prac['pt_name']]['item'])
    visual.TextStim(
        win,
        text=f"PRACTICE TRIAL {p+1}/{total_practice}\n\n"
             f"Target group: {BLOCK_FRIENDLY[prac['block_type']]}\n"
             f"Press the corner key for EVERY {BLOCK_FRIENDLY_SINGULAR[prac['block_type']]} you see.\n"
             f"(One of them will be: {pt_label})\n\n"
             f"Press any key to begin.",
        height=28, wrapWidth=1400, color='yellow'
    ).draw()
    win.flip()
    event.waitKeys()

    print(f"\n{'='*70}\nPRACTICE TRIAL {p+1} — {prac['block_type'].upper()} block\n{'='*70}")
    stats = run_trial(
        p + 1,
        prac['block_type'],
        prac['pt_name'],
        prac['pt_group'],
        prac['pd_group'],
        prac['npd_pool'],
        is_practice=True,
    )

    visual.TextStim(
        win,
        text=f"Practice Trial {p+1}/{total_practice} Complete!\n\n"
             f"Valid target responses: {stats['valid_responses']}\n"
             f"False alarms: {stats['false_alarms']}\n\nPress any key to continue.",
        height=26, wrapWidth=1400, color='white'
    ).draw()
    win.flip()
    event.waitKeys()


# ==============================================================================
# 17. REAL TRIALS
# ==============================================================================

visual.TextStim(
    win,
    text=f"Practice complete! Now beginning REAL TRIALS.\n\n"
         f"Block order: {BLOCK_FRIENDLY[block_order[0]]} → {BLOCK_FRIENDLY[block_order[1]]}\n\n"
         f"Press any key to begin.",
    height=28, wrapWidth=1400, color='white'
).draw()
win.flip()
event.waitKeys()


def make_pt_sequence(block_type, pt_group, n_trials):
    block_pts = [k for k, v in pt_group.items() if v['item']['cat'] == block_type]

    if ALLOW_BOTH_PTS_SAME_TRIAL or len(block_pts) == 1:
        return [random.choice(block_pts) for _ in range(n_trials)]

    pt_a, pt_b   = block_pts[0], block_pts[1]
    n_a          = (n_trials + 1) // 2
    n_b          = n_trials - n_a
    raw_sequence = [pt_a] * n_a + [pt_b] * n_b

    if PT_SUBBLOCK_ORDER == 'grouped':
        return raw_sequence
    elif PT_SUBBLOCK_ORDER == 'alternating':
        seq = []
        for i in range(n_trials):
            seq.append(pt_a if i % 2 == 0 else pt_b)
        return seq[:n_trials]
    elif PT_SUBBLOCK_ORDER == 'random':
        random.shuffle(raw_sequence)
        return raw_sequence
    else:
        print(f"  WARNING: Unknown PT_SUBBLOCK_ORDER '{PT_SUBBLOCK_ORDER}' — defaulting to random.")
        random.shuffle(raw_sequence)
        return raw_sequence


trial_counter = 0
block_config  = {
    'animate':   (NUM_ANIMATE_TRIALS,   pd_group_animate,   npd_pool_animate),
    'inanimate': (NUM_INANIMATE_TRIALS, pd_group_inanimate, npd_pool_inanimate),
}

for block_type in block_order:
    n_trials, pd_group, npd_pool = block_config[block_type]
    pt_sequence = make_pt_sequence(block_type, pt_group, n_trials)

    block_pts   = {k: v for k, v in pt_group.items() if v['item']['cat'] == block_type}
    pt_name_map = {k: friendly_name(v['item']) for k, v in block_pts.items()}
    subblock_str = ' → '.join(pt_name_map[p] for p in pt_sequence[:6])
    if n_trials > 6:
        subblock_str += f'  … ({n_trials} trials total)'

    visual.TextStim(
        win,
        text=f"Beginning {block_type.upper()} BLOCK\n\n"
             f"{n_trials} trials — target group: {BLOCK_FRIENDLY[block_type]}.\n"
             f"Press the corner key for EVERY {BLOCK_FRIENDLY_SINGULAR[block_type]} you see.\n\n"
             f"Sub-block order (first 6): {subblock_str}\n\n"
             f"Press any key to start.",
        height=26, wrapWidth=1500, color='cyan'
    ).draw()
    win.flip()
    event.waitKeys()

    for t in range(n_trials):
        trial_counter  += 1
        active_pt_name  = pt_sequence[t]
        active_pt_label = friendly_name(pt_group[active_pt_name]['item'])

        print(f"\n{'='*70}\nTRIAL {trial_counter} — {block_type.upper()} "
              f"({t+1}/{n_trials})\n{'='*70}")

        stats = run_trial(trial_counter, block_type, active_pt_name,
                          pt_group, pd_group, npd_pool, is_practice=False)

        is_last = (trial_counter == NUM_ANIMATE_TRIALS + NUM_INANIMATE_TRIALS)
        visual.TextStim(
            win,
            text=f"Trial {t+1}/{n_trials} Complete!\n\n"
                 f"Valid target responses: {stats['valid_responses']}\n"
                 f"False alarms: {stats['false_alarms']}\n\n"
                 f"{'Press any key to continue.' if not is_last else 'Press any key for summary.'}",
            height=26, wrapWidth=1400, color='white'
        ).draw()
        win.flip()
        event.waitKeys()


# ==============================================================================
# 18. FINAL SUMMARY
# ==============================================================================

total_target_appearances, total_valid, total_fa = 0, 0, 0
try:
    with open(data_filepath, 'r') as f:
        for row in csv.DictReader(f):
            if row['is_practice'] == 'False' and row['role'] in ('PT', 'NPT'):
                total_target_appearances += 1
    with open(responses_filepath, 'r') as f:
        for row in csv.DictReader(f):
            if row['is_practice'] == 'False':
                if row['response_type'] == 'hit':   
                    total_valid += 1
                elif row['response_type'].startswith('fa_'):
                    total_fa += 1
except Exception as e:
    print(f"  WARNING: Could not read summary: {e}")

hit_rate = (total_valid / total_target_appearances * 100) if total_target_appearances > 0 else 0

visual.TextStim(
    win,
    text=f"Experiment Complete!\n\nParticipant: {participant_pid}\n\n"
         f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
         f"Target Appearances: {total_target_appearances}\n"
         f"Valid Responses: {total_valid} ({hit_rate:.1f}%)\n"
         f"False Alarms: {total_fa}\n"
         f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
         f"Data saved to:\n{data_filename}\n{responses_filename}\n{trials_filename}\n\n"
         f"Thank you!\n\nPress any key to exit.",
    height=24, wrapWidth=1400, color='white'
).draw()
win.flip()
event.waitKeys()

win.close()


# ==============================================================================
# 18. POST-SESSION: PUSH PARTICIPANT DATA TO LAB SHARE (best-effort)
# ==============================================================================
# Local-first design: every CSV row above was written to local disk, so network
# jitter could not feed into long_frames during the run. Now that the window is
# closed and there are no more frame-loop concerns, push the participant
# directory to the lab SMB share. Failure here is non-fatal -- the data is
# already safe locally and a manual `cp -rp` can catch up later.
#
# The same helper is invoked from the ESC handler in run_trial so an aborted
# session also gets pushed. Skip with: AV_STUDY_SKIP_SYNC=1 (set by
# run_study.sh's --no-sync flag).

push_participant_data_to_share(reason='session_complete')


core.quit()
