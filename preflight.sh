#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$script_dir/preflight_config.sh"
study_dir="${AV_STUDY_DIR:-$script_dir}"
python_bin="${AV_STUDY_PYTHON:-}"

if ! command -v zenity >/dev/null 2>&1; then
  echo 'Zenity is required for the graphical preflight. Install zenity, then run this launcher again.' >&2
  exit 1
fi
gui_error() { zenity --error --title='AV study preflight' --width=520 --text="$1"; }
gui_info() { zenity --info --title='AV study preflight' --width=520 --text="$1"; }
gui_yes() { zenity --question --title='AV study preflight' --width=560 --ok-label='Yes, continue' --cancel-label='No, stop' --text="$1"; }

if [[ ! -d "$study_dir" || ! -f "$study_dir/config.py" || ! -f "$study_dir/experiment.py" ]]; then
  gui_error "Study directory is missing config.py or experiment.py:\n$study_dir"
  exit 1
fi
study_dir="$(cd -- "$study_dir" && pwd)"
cd -- "$study_dir"
export AV_STUDY_DIR="$study_dir"

if [[ -z "$python_bin" ]]; then
  psychopy_python_root="${XDG_CONFIG_HOME:-${HOME:-}/.config}/psychopy4/.python"
  shopt -s nullglob
  psychopy_candidates=( "$psychopy_python_root"/*/bin/python3 )
  shopt -u nullglob
  while IFS= read -r candidate; do
    [[ -n "$candidate" && -x "$candidate" ]] || continue
    if "$candidate" -c 'import importlib.util as u, sys; sys.exit(0 if all(u.find_spec(n) for n in ("psychopy", "numpy", "PIL", "psychtoolbox")) else 1)' >/dev/null 2>&1; then
      python_bin="$candidate"
      break
    fi
  done < <(printf '%s\n' "${psychopy_candidates[@]:-}" | sort -rV)
fi
if [[ -z "$python_bin" ]]; then
  gui_error "Could not find PsychoPy's Python runtime. Launch PsychoPy once to provision its environment, or set AV_STUDY_PYTHON to its bin/python3 path."
  exit 1
fi
if ! command -v "$python_bin" >/dev/null 2>&1; then
  gui_error "Python executable not found: $python_bin"
  exit 1
fi
if ! "$python_bin" -c 'import importlib.util as u, sys; sys.exit(0 if all(u.find_spec(n) for n in ("psychopy", "numpy", "PIL", "psychtoolbox")) else 1)' >/dev/null 2>&1; then
  gui_error "The selected Python runtime is missing PsychoPy, NumPy, Pillow, or psychtoolbox:\n$python_bin\n\nSet AV_STUDY_PYTHON to the PsychoPy environment's bin/python3 path."
  exit 1
fi

# PsychoPy's PTB wheel bundles PortAudio and its own JACK client library. Route
# that client through PipeWire's JACK shim, then require the built-in analog sink.
pipewire_jack_lib=''
shopt -s nullglob
pipewire_jack_candidates=( /usr/lib/*/pipewire-0.3/jack/libjack.so )
shopt -u nullglob
if (( ${#pipewire_jack_candidates[@]} > 0 )); then
  pipewire_jack_lib="${pipewire_jack_candidates[0]}"
fi
pipewire_jack_ready=0
if [[ -n "$pipewire_jack_lib" ]] && command -v pw-jack >/dev/null 2>&1; then
  if pw-jack env LD_PRELOAD="$pipewire_jack_lib" "$python_bin" -c '
import sys
import psychtoolbox.audio as audio
profiles = audio.get_devices()
sys.exit(0 if any(
    "jack" in str(p.get("HostAudioAPIName", "")).lower()
    and "built-in audio analog stereo" in str(p.get("DeviceName", "")).lower()
    and int(p.get("NrOutputChannels", 0)) >= 2
    for p in profiles
) else 1)
' >/dev/null 2>&1; then
    pipewire_jack_ready=1
  fi
fi
participant_id="$(PYTHONPATH="$study_dir${PYTHONPATH:+:$PYTHONPATH}" "$python_bin" -c 'from pathlib import Path; from participant_setup import next_participant_id; print(next_participant_id(Path("data")))')" || {
  gui_error 'Could not determine the next participant ID.'
  exit 1
}

rows=()
add_row() { rows+=("$1" "$2" "$3"); }
fatal=0
add_row '✅' 'Participant ID' "$participant_id (next available)"
add_row '✅' 'Experiment runtime' "$python_bin"
if (( pipewire_jack_ready )); then
  add_row '✅' 'PTB audio route' 'PipeWire JACK exposes the built-in headphone output'
else
  add_row '❌' 'PTB audio route' 'PipeWire JACK could not expose Built-in Audio Analog Stereo; check package and output settings'
  fatal=1
fi

# Require a centered OS output balance so the left and right headphone channels
# receive equal levels. pactl reports a normalized balance of 0.00 at center.
audio_balance=''
audio_balance_status='unverified'
if command -v pactl >/dev/null 2>&1; then
  audio_volume_info="$(pactl get-sink-volume @DEFAULT_SINK@ 2>/dev/null || true)"
  audio_balance="$(awk '/balance/ { print $2; exit }' <<< "$audio_volume_info")"
  if [[ "$audio_balance" =~ ^-?[0-9]+([.][0-9]+)?$ ]]; then
    if awk -v balance="$audio_balance" 'BEGIN { exit (balance >= -0.01 && balance <= 0.01) ? 0 : 1 }'; then
      audio_balance_status='centered'
      add_row '✅' 'Headphone L/R balance' "Centered (balance $audio_balance; equal channel levels)"
    else
      audio_balance_status='off_center'
      add_row '❌' 'Headphone L/R balance' "Off center (balance $audio_balance); set output balance to 50/50"
      fatal=1
    fi
  else
    add_row '⚠️' 'Headphone L/R balance' 'Could not read the system output balance; verify left/right levels manually'
  fi
else
  add_row '⚠️' 'Headphone L/R balance' 'pactl is unavailable; verify left/right levels manually'
fi

if [[ "$(uname -s)" == Linux ]]; then
  add_row '✅' 'Operating system' 'Linux'
else
  add_row '❌' 'Operating system' "Linux required; found $(uname -s)"
  fatal=1
fi

session_type="${XDG_SESSION_TYPE:-unknown}"
if [[ "$session_type" == x11 ]]; then
  add_row '✅' 'Display session' 'Xorg (X11) detected'
else
  add_row '⚠️' 'Display session' "$session_type detected; Xorg is recommended for timing-critical runs"
fi

display_info=''
active_mode=''
if command -v xrandr >/dev/null 2>&1; then
  display_info="$(xrandr --current 2>&1 || true)"
  active_mode="$(awk '/\*/ { print; exit }' <<< "$display_info")"
fi
if [[ -n "$active_mode" ]]; then
  add_row '✅' 'Active display mode' "$active_mode"
else
  add_row '❌' 'Active display mode' 'Could not read the active mode with xrandr'
  fatal=1
fi

# xrandr reports the refresh frequency of the active mode without opening a PsychoPy window.
display_refresh_hz="$(awk '/\*/ { for (i = 1; i <= NF; i++) if ($i ~ /\*/) { value = $i; gsub(/[^0-9.]/, "", value); if (value ~ /^[0-9]+([.][0-9]+)?$/) print value; exit } }' <<< "$display_info")"
if [[ -n "$display_refresh_hz" ]]; then
  add_row '✅' 'Reported refresh rate' "${display_refresh_hz} Hz (active xrandr mode)"
else
  add_row '❌' 'Reported refresh rate' 'Could not read a refresh frequency from the active xrandr mode'
  fatal=1
fi

gvfs_dir="/run/user/$(id -u)/gvfs"
shopt -s nullglob
server_matches=( "$gvfs_dir"/$PREFLIGHT_SERVER_MOUNT_GLOB )
shopt -u nullglob
server_root=''
for candidate in "${server_matches[@]}"; do
  if [[ -d "$candidate" ]]; then server_root="$candidate"; break; fi
done
if [[ -n "$server_root" && -w "$server_root" ]]; then
  add_row '✅' 'Lab server' "Mounted and writable: $server_root"
  export AV_STUDY_SERVER_ROOT="$server_root"
  export AV_STUDY_SERVER_DATA_PATH="$PREFLIGHT_SERVER_DATA_PATH"
else
  if [[ -n "$server_root" ]]; then
    add_row '⚠️' 'Lab server' 'Mounted but not writable; results will remain local'
  else
    add_row '⚠️' 'Lab server' 'Not mounted; results will be saved locally and will not be copied to the server'
  fi
  unset AV_STUDY_SERVER_ROOT AV_STUDY_SERVER_DATA_PATH || true
fi

report="$(mktemp "${TMPDIR:-/tmp}/av-preflight-${participant_id}.XXXXXX")"
{
  printf 'measured_at=%s\n' "$(date --iso-8601=seconds)"
  printf 'study_dir=%s\nparticipant_id=%s\n' "$study_dir" "$participant_id"
  printf 'session_type=%s\nactive_mode=%s\ndisplay_refresh_hz=%s\n' "$session_type" "$active_mode" "$display_refresh_hz"
  printf 'audio_route=%s\npipewire_jack_library=%s\n' 'PTB via PipeWire JACK' "$pipewire_jack_lib"
  printf 'audio_balance=%s\naudio_balance_status=%s\n' "${audio_balance:-unknown}" "$audio_balance_status"
  printf 'server_mounted=%s\n' "$([[ -n "$server_root" && -w "$server_root" ]] && printf true || printf false)"
  [[ -z "$server_root" ]] || printf 'server_root=%s\nserver_data_path=%s\n' "$server_root" "$PREFLIGHT_SERVER_DATA_PATH"
  printf '\nConnected display modes:\n%s\n' "$display_info"
} > "$report"
add_row '✅' 'Preflight report' 'Will be saved in the participant folder after launch'

summary="Review the checks below. A red item must be fixed before the study can start."
zenity --list --title='AV study preflight checklist' --width=900 --height=480 \
  --text="$summary\n\nParticipant: $participant_id" \
  --column='Status' --column='Check' --column='Result' --print-column=2 \
  "${rows[@]}" >/dev/null || { rm -f -- "$report"; echo 'Preflight window closed.'; exit 1; }

if (( fatal )); then
  rm -f -- "$report"
  gui_error 'One or more required preflight checks failed. Fix the red items before starting.'
  exit 1
fi
if [[ "$session_type" != x11 ]]; then
  gui_yes "Xorg is recommended for timing-critical runs. Your session is '$session_type'. Continue anyway?" || { rm -f -- "$report"; gui_info 'Preflight stopped. Log out and choose an Xorg session for the recommended setup.'; exit 1; }
fi
if [[ -z "$server_root" || ! -w "$server_root" ]]; then
  gui_yes 'The lab server is unavailable or not writable. Data will remain local and will not be copied automatically. Continue?' || { rm -f -- "$report"; gui_info 'Preflight stopped. Mount the writable lab share and run preflight again.'; exit 1; }
fi
gui_yes "All required checks passed. Start participant $participant_id now?" || { rm -f -- "$report"; gui_info 'Preflight passed. The experiment was not started.'; exit 0; }
export AV_STUDY_PREFLIGHT_REPORT="$report"
runner_log="$(mktemp "${TMPDIR:-/tmp}/av-experiment-${participant_id}.XXXXXX")"
if pw-jack env LD_PRELOAD="$pipewire_jack_lib" "$python_bin" "$study_dir/experiment.py" "$participant_id" >"$runner_log" 2>&1; then
  rm -f -- "$runner_log"
  if ! compgen -G "$study_dir/data/$participant_id/session_*" >/dev/null; then
    gui_info "The runner stopped before the session began. Participant $participant_id setup was preserved; run preflight again to resume it."
  fi
else
  run_status=$?
  log_copy="$study_dir/data/$participant_id/launch_error.log"
  if [[ -d "$study_dir/data/$participant_id" ]]; then
    cp -- "$runner_log" "$log_copy"
  fi
  error_tail="$(tail -n 18 -- "$runner_log")"
  rm -f -- "$runner_log"
  gui_error "The experiment runner exited with status $run_status.\n\n$error_tail\n\nFull log: $log_copy"
  exit "$run_status"
fi
