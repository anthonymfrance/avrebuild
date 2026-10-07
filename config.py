"""Study constants: no functions, no PsychoPy imports.
A constant is added here only when the first function that uses it is written."""

# --- Stimulus split ---
TRIALS_PER_PT = 15   # trials in which each PT is the active PT (per block)
PT_COUNT_PER_BLOCK = 2
PD_COUNT_PER_BLOCK = 2

# --- SOAs ---
PT_SOA_MIN = 0.5
PT_SOA_MAX = 1.5
PD_SOA_MIN = 0.5
PD_SOA_MAX = 1.5

# --- Items per trial (min, max) ---
TRIAL_PT_RANGE = (2, 3)
TRIAL_NPT_RANGE = (3, 8)
TRIAL_PD_RANGE = (3, 5)
TRIAL_NPD_RANGE = (11, 17)
MAX_PLACEMENT_ATTEMPTS = 250
MAX_TIMELINE_ATTEMPTS = 3

TARGET_SPATIAL_BIAS = 0.80
CORNERS = ('top_left', 'top_right', 'bottom_left', 'bottom_right')
FAVORED_CORNER = 'top_right'

# --- Visual timing (seconds) ---
WINDOW_SIZE = (1920, 1080)
FADE_IN_DUR = 0.3
PEAK_HOLD_DUR = 0.0
FADE_OUT_DUR = 0.3
MIN_VISUAL_ONSET_GAP = 0.15
MIN_TARGET_END_TO_ONSET_GAP = 0.15
MIN_SAME_ITEM_GAP = 0.75

# --- Trial structure: buffer + content + buffer = 24 s ---
TRIAL_BUFFER_DUR = 2.0     # applied at both the start and the end of the trial
TRIAL_CONTENT_DUR = 20.0
BETWEEN_PT_STIMULUS_GAP = 0.5

# --- Audio ---
AUDIO_BACKEND = 'ptb'
AUDIO_LATENCY_MODE = 2
AUDIO_DEVICE = 'default'
AUDIO_SPEAKER = 'default'
SOUND_DUR = 1.0
MIN_AUDIO_GAP = 0.2

# --- Responses ---
RESPONSE_WINDOW = 1.5

# --- Background ---
BG_NOISE_OPACITY = 0.3
BG_SOURCE_FILE = 'otherblobs.png'
BG_UPDATE_RATE = 0.4

# --- Images ---
IMAGE_SIZE = (200, 200)
MAX_OPACITY = 1.0

# --- Fixation ---
FIXATION_SIZE = 30
FIXATION_LINE_WIDTH = 3
FIXATION_COLOR = 'white'
FIXATION_HIT_COLOR = 'green'
FIXATION_FLASH_DUR = 0.2
