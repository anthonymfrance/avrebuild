"""Study constants: no functions, no imports.
A constant is added here only when the first function that uses it is written.
Derived constants (computed from constants above them) are allowed so every
module shares one definition."""

# --- Stimulus split ---
TRIALS_PER_PT = 2   # trials in which each PT is the active PT (per block)
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
TRIAL_NPD_RANGE = (20, 28) #used to be 11 - 15
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

# --- Between-block break ---
# The break screen counts down from this and continues on its own at zero; the
# elapsed time a participant actually takes is recorded in session metadata.
BREAK_OFFER_SECONDS = 30

# --- Derived timing, roles, and labels ---
VISUAL_DURATION = FADE_IN_DUR + PEAK_HOLD_DUR + FADE_OUT_DUR
TRIAL_DURATION = 2 * TRIAL_BUFFER_DUR + TRIAL_CONTENT_DUR
CORNER_SIGNS = {
    'top_left': (-1, 1), 'top_right': (1, 1),
    'bottom_left': (-1, -1), 'bottom_right': (1, -1),
}
VISUAL_ROLES = frozenset({'PT', 'NPT', 'PD', 'NPD'})
TARGET_ROLES = frozenset({'PT', 'NPT'})
AUDIO_ROLES = frozenset({'PT', 'PD'})
BLOCK_LABELS = {'animate': 'ANIMALS', 'inanimate': 'OBJECTS'}

# --- Audio ---
# Preflight pins the OS output sink to this level before every session, so the
# participant hears the same level on every device. Keep the in-code playback
# gain at 1.0 so the system level is not attenuated twice.
SYSTEM_VOLUME_PERCENT = 50
AUDIO_VOLUME = 1.0
AUDIO_BACKEND = 'ptb'
AUDIO_LATENCY_MODE = 2
AUDIO_DEVICE = 'default'
AUDIO_SPEAKER = 'default'
SOUND_DUR = 1.0
MIN_AUDIO_GAP = 0.2
SOUND_POOL_SIZE = 2          # Sound objects per stimulus, used round-robin
SOUND_POOL_RESTART_MARGIN = 0.05  # play() must land this long after the previous play on a pooled object ended
SOUND_REQUEST_MIN_LEAD = 0.01     # seconds of future margin when a play request is already late
SOUND_REQUEST_LEAD = 0.5          # pool sizing contract: every play must be requestable this far ahead of its onset (tests/test_sound_pool.py)

# --- Timing flags ---
VISUAL_ONSET_FLAG_FRAMES = 1.0          # flag visual onsets later/earlier than this many frame periods
AUDIO_ONSET_FLAG_THRESHOLD = 0.005      # seconds; flag reported audio start deviations above this

# --- Responses ---
RESPONSE_WINDOW = 0.9 #used to be 1.5
LATE_WINDOW = 0.5  # after RESPONSE_WINDOW: a press here is a late response; the target's corner stays empty until it ends
TARGET_CORNER_HOLD = RESPONSE_WINDOW + LATE_WINDOW

# --- Background ---
BG_NOISE_OPACITY = 0.3
BG_SOURCE_FILE = 'otherblobs.png'
BG_UPDATE_RATE = 0.2
BG_SEED = 0xA1D0B04A

# --- Images ---
IMAGE_SIZE = (150, 150) #was at 200, 200
MAX_OPACITY = 1.0

# --- Fixation / centre mark ---
# What sits at the centre of the screen, or around its edge. 'cross' is the
# classic fixation cross, 'circle' an unfilled ring, 'border' a frame around the
# whole window with no centre icon. Whichever is chosen flashes
# FIXATION_HIT_COLOR on a hit, so the hit feedback is the same mark in every
# configuration (trial_runner and practice only set its lineColor).
#
# Presentation only: it changes how the screen looks, never what a timeline
# contains, so it is kept out of the participant-plan config snapshot
# (session_io.PRESENTATION_ONLY) and changing it cannot refuse a plan that was
# already generated. Each session records the mark it ran with in its metadata.
# The participant-facing name of each option lives with the wording it appears
# in, in screens.MARK_NAMES.
FIXATION_SHAPE = 'circle'   # options: 'cross', 'circle', 'border'
FIXATION_SIZE = 30          # pixels: cross arm length, or ring diameter
FIXATION_LINE_WIDTH = 3     # stroke width for 'cross' and 'circle'
# A 3 px stroke is a hairline along a 1920 px window edge, so the frame has its
# own width rather than sharing FIXATION_LINE_WIDTH.
FIXATION_BORDER_WIDTH = 16
FIXATION_COLOR = 'white'
FIXATION_HIT_COLOR = 'green'
FIXATION_FLASH_DUR = 0.2

# --- Display refresh ---
REQUIRED_REFRESH_HZ = 120
REFRESH_TOLERANCE_HZ = 1.0

# --- Cross-device participant reservation ---
# A preflight claim older than this is treated as abandoned and can be reused.
PARTICIPANT_CLAIM_TTL_HOURS = 12
