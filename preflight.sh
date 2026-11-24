#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$script_dir/preflight_config.sh"
# Machine-local values (name, headphones) live in an untracked file, so a clone
# on another computer does not inherit this one's identity.
if [[ -f "$script_dir/preflight_local.sh" ]]; then
  source "$script_dir/preflight_local.sh"
fi
study_dir="${AV_STUDY_DIR:-$script_dir}"
python_bin="${AV_STUDY_PYTHON:-}"

if ! command -v zenity >/dev/null 2>&1; then
  echo 'Zenity is required for the graphical preflight. Install zenity, then run this launcher again.' >&2
  exit 1
fi
if ! command -v xdg-open >/dev/null 2>&1; then
  echo 'xdg-open is required to open the consent form and the participant log. Install xdg-utils, then run this launcher again.' >&2
  exit 1
fi
gui_error() { zenity --error --title='AV study preflight' --width=520 --text="$1"; }
gui_info() { zenity --info --title='AV study preflight' --width=520 --text="$1"; }
gui_yes() { zenity --question --title='AV study preflight' --width=560 --ok-label='Yes, continue' --cancel-label='No, stop' --text="$1"; }
# Explicit labels stop a habitual right-hand 'continue' click from starting a
# debug run by mistake. Participant is the default and the cancel button, so
# Enter or closing the dialog never enables debug.
gui_debug_choice() { zenity --question --title='AV study preflight' --width=560 --ok-label='Debug run' --cancel-label='Participant run' --default-cancel --text="$1"; }
# The browser steps are gates: the RA confirms the outside action before the
# session continues. Debug runs may skip the remaining steps; a participant run
# has no skip button, only a stop. Returns 0 confirmed, 2 skip, 1 stop.
gui_browser_gate() {
  local ok_label="$1" text="$2" answer='' status=0
  local -a extra=()
  if [[ "${debug_overlay:-false}" == true ]]; then
    extra=(--extra-button='Skip (debug)')
  fi
  answer="$(zenity --question --title='AV study preflight' --width=600 \
    --ok-label="$ok_label" --cancel-label='No, stop' ${extra[@]+"${extra[@]}"} \
    --text="$text" 2>/dev/null)" || status=$?
  if (( status == 0 )); then
    return 0
  fi
  if [[ "$answer" == 'Skip (debug)' ]]; then
    return 2
  fi
  return 1
}

if [[ ! -d "$study_dir" || ! -f "$study_dir/config.py" || ! -f "$study_dir/experiment.py" ]]; then
  gui_error "Study directory is missing config.py or experiment.py:
$study_dir"
  exit 1
fi
study_dir="$(cd -- "$study_dir" && pwd)"
cd -- "$study_dir"
export AV_STUDY_DIR="$study_dir"

# A project-local venv built from requirements-lock.txt is the standard runtime;
# the PsychoPy app's own runtime is only a fallback, and only if it still imports
# what the study needs.
if [[ -z "$python_bin" && -x "$study_dir/.venv/bin/python" ]] \
  && "$study_dir/.venv/bin/python" -c 'import psychopy' >/dev/null 2>&1; then
  python_bin="$study_dir/.venv/bin/python"
fi
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
  gui_error "The selected Python runtime is missing PsychoPy, NumPy, Pillow, or psychtoolbox:
$python_bin

Set AV_STUDY_PYTHON to the PsychoPy environment's bin/python3 path."
  exit 1
fi

# PsychoPy's PTB wheel bundles PortAudio and its own JACK client library. Route
# that client through PipeWire's JACK shim, then require PTB to see the output the
# system is actually configured to play through. The sink is resolved at run time
# because hardware names differ between machines (codec, chassis, USB headset).
default_sink_desc=''
default_sink="$(pactl get-default-sink 2>/dev/null || true)"
if [[ -n "$default_sink" ]]; then
  default_sink_desc="$(pactl list sinks 2>/dev/null | awk -v want="$default_sink" '
    /^[^ \t]/ { if ($0 ~ /^Sink #/) { name = ""; desc = "" } }
    /^[[:space:]]+Name: / { line = $0; sub(/^[[:space:]]+Name: /, "", line); name = line }
    /^[[:space:]]+Description: / { line = $0; sub(/^[[:space:]]+Description: /, "", line); desc = line }
    name == want && desc != "" { print desc; exit }
  ' || true)"
fi
# A digital output (S/PDIF, HDMI) is not the study's headphone route, even when
# PTB can open it.
default_sink_is_digital=0
if [[ "$default_sink_desc" =~ [Dd]igital|[Ii][Ee][Cc]958|[Hh][Dd][Mm][Ii] ]]; then
  default_sink_is_digital=1
fi
# The output this machine is supposed to use, from the untracked
# preflight_local.sh. Empty means any output the route check accepts is fine; the
# session still follows whatever the OS default is.
expected_audio_device="${PREFLIGHT_AUDIO_DEVICE:-}"
pipewire_jack_lib=''
shopt -s nullglob
pipewire_jack_candidates=( /usr/lib/*/pipewire-0.3/jack/libjack.so )
shopt -u nullglob
if (( ${#pipewire_jack_candidates[@]} > 0 )); then
  pipewire_jack_lib="${pipewire_jack_candidates[0]}"
fi
pipewire_jack_ready=0
if [[ -n "$pipewire_jack_lib" ]] && command -v pw-jack >/dev/null 2>&1; then
  if AV_EXPECTED_SINK_DESC="${expected_audio_device:-$default_sink_desc}" pw-jack env LD_PRELOAD="$pipewire_jack_lib" "$python_bin" -c '
import os
import sys
import psychtoolbox.audio as audio
expected = os.environ.get("AV_EXPECTED_SINK_DESC", "").strip().lower()
names = [
    str(profile.get("DeviceName", "")).lower()
    for profile in audio.get_devices()
    if "jack" in str(profile.get("HostAudioAPIName", "")).lower()
    and int(profile.get("NrOutputChannels", 0)) >= 2
]
# Match the configured output when its name is known; otherwise keep the
# historical analog-stereo requirement so an unknown sink never passes silently.
needle = expected if expected else "analog stereo"
sys.exit(0 if any(needle in name for name in names) else 1)
' >/dev/null 2>&1; then
    pipewire_jack_ready=1
  fi
fi

# Record which code revision is running and warn when the checkout is behind its
# upstream. This fetches but never merges or checks out: an update has to be a
# deliberate act, because a changed config.py invalidates existing plans.
git_state='unavailable'
git_commit=''
git_branch=''
git_upstream=''
git_behind=''
git_dirty=''
if command -v git >/dev/null 2>&1 && git -C "$study_dir" rev-parse --git-dir >/dev/null 2>&1; then
  git_state='checked_out'
  git_commit="$(git -C "$study_dir" rev-parse --short HEAD 2>/dev/null || true)"
  git_branch="$(git -C "$study_dir" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  # Untracked files do not change the code that runs. participant_setup.git_state()
  # ignores them for the same reason, so the two records agree.
  if [[ -n "$(git -C "$study_dir" status --porcelain --untracked-files=no 2>/dev/null)" ]]; then
    git_dirty=1
  fi
  git_upstream="$(git -C "$study_dir" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)"
  if [[ -n "$git_upstream" ]]; then
    # Bounded so an offline machine does not stall at launch; a LAN fetch is ~1 s.
    if timeout 5 git -C "$study_dir" fetch --quiet --prune 2>/dev/null; then
      git_behind="$(git -C "$study_dir" rev-list --count "HEAD..$git_upstream" 2>/dev/null || true)"
    else
      git_state='fetch_failed'
    fi
  fi
fi
# Identity for the multi-device pilot: a human name from the untracked local
# config, plus values the machine supplies itself, so a changed hostname or a
# swapped disk cannot silently merge two computers into one row of the data.
machine_name="${PREFLIGHT_MACHINE_NAME:-}"
[[ -n "$machine_name" ]] || machine_name="$(uname -n 2>/dev/null || true)"
# The DMI product UUID and serial are root-only, so preflight cannot read them at
# launch. Values read once with sudo into preflight_local.sh are used when present;
# /etc/machine-id is the readable fallback (unique per install, not per machine).
machine_uuid="${PREFLIGHT_MACHINE_UUID:-}"
[[ -n "$machine_uuid" ]] || machine_uuid="$(cat /etc/machine-id 2>/dev/null || true)"
machine_serial="${PREFLIGHT_MACHINE_SERIAL:-}"
[[ -n "$machine_serial" ]] || machine_serial="$(cat /sys/class/dmi/id/product_serial 2>/dev/null || true)"
machine_vendor="$(cat /sys/class/dmi/id/sys_vendor 2>/dev/null || true)"
machine_product="$(cat /sys/class/dmi/id/product_name 2>/dev/null || true)"
# 'Alienware' plus 'Alienware Aurora R6' would repeat the vendor.
if [[ -n "$machine_vendor" && "$machine_product" == "$machine_vendor"* ]]; then
  machine_model="$machine_product"
elif [[ -n "$machine_vendor" ]]; then
  machine_model="$machine_vendor $machine_product"
else
  machine_model="$machine_product"
fi
# A wired NIC is stable across reboots; enx* devices are USB adapters that move.
machine_mac=''
for nic in /sys/class/net/*; do
  nic_name="$(basename "$nic")"
  case "$nic_name" in lo|docker*|veth*|br-*|virbr*|enx*) continue ;; esac
  machine_mac="$(cat "$nic/address" 2>/dev/null || true)"
  [[ -z "$machine_mac" ]] || break
done
rows=()
add_row() { rows+=("$1" "$2" "$3"); }
fatal=0
add_row '✅' 'Experiment runtime' "$python_bin"
add_row 'ℹ️' 'Machine' "$machine_name${machine_uuid:+ | uuid ${machine_uuid:0:8}}${machine_mac:+ | ${machine_mac}}"
if (( ! pipewire_jack_ready )); then
  add_row '❌' 'PTB audio route' "PipeWire JACK could not expose ${default_sink_desc:-the configured default output (description unavailable)}; check the pipewire-jack package and the selected output"
  fatal=1
elif (( default_sink_is_digital )); then
  # A digital sink is the wrong route on most machines, but this lab runs the DAC's
  # S/PDIF output deliberately, so PREFLIGHT_ALLOW_DIGITAL_SINK accepts it. The row
  # still names the output, so the route in use is visible in the checklist and in
  # the saved report rather than passing silently.
  if [[ "${PREFLIGHT_ALLOW_DIGITAL_SINK:-0}" == 1 ]]; then
    add_row '✅' 'PTB audio route' "Digital output accepted (PREFLIGHT_ALLOW_DIGITAL_SINK): $default_sink_desc"
  else
    add_row '❌' 'PTB audio route' "Default output is digital ($default_sink_desc); select the wired headphone output as the default sink"
    fatal=1
  fi
else
  add_row '✅' 'PTB audio route' "PipeWire JACK exposes $default_sink_desc"
fi

# The session follows the OS default output, so this row is what guarantees the
# default is the output this machine is meant to use. Only shown when the machine
# records one, so a machine without the hardware can still run a debug session.
if [[ -n "$expected_audio_device" ]]; then
  if [[ "${default_sink_desc,,}" == "${expected_audio_device,,}" ]]; then
    add_row '✅' 'Expected audio device' "$expected_audio_device"
  else
    add_row '❌' 'Expected audio device' "Default output is ${default_sink_desc:-unknown}, but PREFLIGHT_AUDIO_DEVICE expects $expected_audio_device"
    fatal=1
  fi
fi

# The machine knows the codec or DAC and nothing about the headphones plugged
# into it, so the headphone model is configuration and is recorded beside the
# detected output.
audio_headphones="${PREFLIGHT_AUDIO_HEADPHONES:-}"
audio_chain="${default_sink_desc:-unknown output}"
if [[ -n "$audio_headphones" ]]; then
  audio_chain+=" + $audio_headphones"
  add_row '✅' 'Audio chain' "$audio_chain"
else
  add_row '⚠️' 'Audio chain' 'Headphones not recorded; set PREFLIGHT_AUDIO_HEADPHONES in preflight_config.sh'
fi

# Pin the level on the sink the route check just validated, so the route check
# and the volume cannot disagree if the system default changes between them.
volume_target="${default_sink:-@DEFAULT_SINK@}"
# Pin the output level so every session and every device runs at the level in
# config.py. The experiment keeps its own playback gain at 1.0 to avoid
# attenuating the signal twice.
system_volume="$(PYTHONPATH="$study_dir${PYTHONPATH:+:$PYTHONPATH}" "$python_bin" -c '
import config
value = int(config.SYSTEM_VOLUME_PERCENT)
if not 0 < value <= 100:
    raise SystemExit(1)
print(value)
')" || system_volume=''
system_volume_actual=''
system_volume_status='unverified'
if ! command -v pactl >/dev/null 2>&1; then
  add_row '⚠️' 'System output volume' 'pactl is unavailable; set the output to the configured level manually'
elif [[ -z "$system_volume" ]]; then
  add_row '❌' 'System output volume' 'Could not read SYSTEM_VOLUME_PERCENT from config.py'
  fatal=1
elif pactl set-sink-volume "$volume_target" "${system_volume}%" >/dev/null 2>&1; then
  system_volume_info="$(pactl get-sink-volume "$volume_target" 2>/dev/null || true)"
  system_volume_actual="$(grep -o '[0-9]\+%' <<< "$system_volume_info" | head -n 1 | tr -d '%')"
  if [[ -n "$system_volume_actual" && "$system_volume_actual" == "$system_volume" ]]; then
    system_volume_status='pinned'
    add_row '✅' 'System output volume' "${system_volume_actual}% (pinned automatically)"
  else
    system_volume_status='mismatch'
    add_row '❌' 'System output volume' "Set to ${system_volume}%, but the output reports ${system_volume_actual:-an unknown level}%"
    fatal=1
  fi
else
  system_volume_status='failed'
  add_row '❌' 'System output volume' "Could not set the default output to ${system_volume}%"
  fatal=1
fi

# Require a centered OS output balance so the left and right headphone channels
# receive equal levels. pactl reports a normalized balance of 0.00 at center.
audio_balance=''
audio_balance_status='unverified'
if command -v pactl >/dev/null 2>&1; then
  audio_volume_info="$(pactl get-sink-volume "$volume_target" 2>/dev/null || true)"
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

session_type="${XDG_SESSION_TYPE:-unknown}"

# The experiment screen is the connected primary output, else the first connected
# output with an active (*) mode. Reads the whole display state, and is called a
# second time after a mode switch so the checklist reports what the panel did.
read_display_state() {
  display_info=''
  if command -v xrandr >/dev/null 2>&1; then
    display_info="$(xrandr --current 2>&1 || true)"
  fi
  # Prints output=, mode=, rate=, then connected= lines.
  display_summary="$(awk '
    /^[^ \t]/ {
      output = ""
      if ($2 == "connected") { output = $1; connected[++n] = $0; is_primary[output] = ($3 == "primary") }
      next
    }
    output != "" && /\*/ && !(output in mode) {
      mode[output] = $1
      for (i = 2; i <= NF; i++) if ($i ~ /\*/) { value = $i; gsub(/[^0-9.]/, "", value); rate[output] = value }
      active[++m] = output
    }
    END {
      chosen = ""
      for (i = 1; i <= m; i++) if (is_primary[active[i]]) { chosen = active[i]; break }
      if (chosen == "" && m > 0) chosen = active[1]
      printf "output=%s\nmode=%s\nrate=%s\n", chosen, mode[chosen], rate[chosen]
      for (i = 1; i <= n; i++) print "connected=" connected[i]
    }' <<< "$display_info")"
  display_output="$(sed -n 's/^output=//p' <<< "$display_summary")"
  active_mode="$(sed -n 's/^mode=//p' <<< "$display_summary")"
  display_refresh_hz="$(sed -n 's/^rate=//p' <<< "$display_summary")"
  [[ "$display_refresh_hz" =~ ^[0-9]+([.][0-9]+)?$ ]] || display_refresh_hz=''
}
read_display_state
expected_mode="$(PYTHONPATH="$study_dir${PYTHONPATH:+:$PYTHONPATH}" "$python_bin" -c 'import config; print("%dx%d" % tuple(config.WINDOW_SIZE))')" || expected_mode=''
expected_refresh="$(PYTHONPATH="$study_dir${PYTHONPATH:+:$PYTHONPATH}" "$python_bin" -c 'import config; print(config.REQUIRED_REFRESH_HZ)')" || expected_refresh=''
refresh_tol="$(PYTHONPATH="$study_dir${PYTHONPATH:+:$PYTHONPATH}" "$python_bin" -c 'import config; print(config.REFRESH_TOLERANCE_HZ)')" || refresh_tol=''

# Put the panel in the mode config.py requires before the session starts, and put
# the best mode the panel offers back on exit -- finished, ESC, crash, or a failed
# check -- so the next person finds a usable desktop rather than a 120 Hz
# experiment screen. X11 only: xrandr cannot change modes on Wayland.
display_mode_action='unchanged'
display_mode_set=''
display_mode_changed=0
available_rates_for_mode() {  # <output> <mode>: one available rate per line
  xrandr --query 2>/dev/null | awk -v want="$1" -v mode="$2" '
    $0 ~ "^" want " connected" { inside = 1; next }
    /^[^ \t]/ { inside = 0 }
    inside && $1 == mode {
      for (i = 2; i <= NF; i++) {
        rate = $i
        gsub(/[*+]/, "", rate)
        if (rate ~ /^[0-9]+([.][0-9]+)?$/) print rate
      }
    }'
}
best_mode_for() {  # <output>: "<largest mode> <highest rate at that mode>"
  xrandr --query 2>/dev/null | awk -v want="$1" '
    $0 ~ "^" want " connected" { inside = 1; next }
    /^[^ \t]/ { inside = 0 }
    inside && $1 ~ /^[0-9]+x[0-9]+$/ {
      split($1, size, "x")
      pixels = size[1] * size[2]
      for (i = 2; i <= NF; i++) {
        rate = $i
        gsub(/[*+]/, "", rate)
        if (rate !~ /^[0-9]+([.][0-9]+)?$/) continue
        if (best_mode == "" || pixels > best_pixels ||
            (pixels == best_pixels && rate + 0 > best_rate + 0)) {
          best_mode = $1
          best_rate = rate
          best_pixels = pixels
        }
      }
    }
    END { if (best_mode != "") print best_mode, best_rate }'
}
restore_best_display_mode() {
  (( display_mode_changed )) || return 0
  local best
  best="$(best_mode_for "$display_output" 2>/dev/null || true)"
  [[ -n "$best" ]] || return 0
  xrandr --output "$display_output" --mode "${best%% *}" --rate "${best##* }" >/dev/null 2>&1 || true
}
# One EXIT trap owns both jobs that must happen however the launcher ends.
on_exit() {
  if [[ "${claim_active:-0}" == 1 ]] && declare -F release_claim >/dev/null; then
    release_claim
  fi
  restore_best_display_mode
}
trap on_exit EXIT
if [[ -n "$display_output" && -n "$expected_mode" && -n "$expected_refresh" && -n "$refresh_tol" ]]; then
  if [[ "$active_mode" == "$expected_mode" && -n "$display_refresh_hz" ]] \
    && awk -v hz="$display_refresh_hz" -v expected="$expected_refresh" -v tolerance="$refresh_tol" \
      'BEGIN { exit (hz >= expected - tolerance && hz <= expected + tolerance) ? 0 : 1 }'; then
    display_mode_action='already'
  else
    # The rate closest to the required one; an exact match wins by offset 0.
    chosen_rate="$(available_rates_for_mode "$display_output" "$expected_mode" \
      | awk -v target="$expected_refresh" '
        { offset = $1 - target; if (offset < 0) offset = -offset
          if (best == "" || offset < best_offset) { best = $1; best_offset = offset } }
        END { if (best != "") print best }')"
    if [[ -z "$chosen_rate" ]]; then
      display_mode_action='unsupported'
    elif xrandr --output "$display_output" --mode "$expected_mode" --rate "$chosen_rate" >/dev/null 2>&1; then
      display_mode_action='set'
      display_mode_set="$expected_mode@$chosen_rate"
      display_mode_changed=1
      read_display_state
    else
      display_mode_action='set_failed'
    fi
  fi
fi
while IFS= read -r connected_line; do
  [[ -n "$connected_line" ]] || continue
  # The full xrandr line is much wider than the checklist column, so keep just
  # the output name and whether it is the primary output.
  connected_label="${connected_line%% *} connected"
  [[ "$connected_line" != *" primary "* ]] || connected_label+=" (primary)"
  add_row 'ℹ️' 'Connected output' "$connected_label"
done < <(sed -n 's/^connected=//p' <<< "$display_summary")
mode_detail=''
case "$display_mode_action" in
  set) mode_detail='; set by preflight' ;;
  unsupported) mode_detail='; this output does not offer that mode' ;;
  set_failed) mode_detail='; xrandr could not switch to it' ;;
esac
if [[ -z "$active_mode" ]]; then
  add_row '❌' 'Experiment display mode' 'Could not read the active mode of a connected output with xrandr'
  fatal=1
elif [[ -z "$expected_mode" ]]; then
  add_row '❌' 'Experiment display mode' 'Could not read WINDOW_SIZE from config.py'
  fatal=1
elif [[ "$active_mode" != "$expected_mode" ]]; then
  add_row '❌' 'Experiment display mode' "$display_output is $active_mode; config.WINDOW_SIZE requires $expected_mode$mode_detail"
  fatal=1
else
  add_row '✅' 'Experiment display mode' "$display_output at $active_mode (matches config.WINDOW_SIZE$mode_detail)"
fi

if [[ -n "$display_refresh_hz" && -n "$expected_refresh" && -n "$refresh_tol" ]]; then
  if awk -v hz="$display_refresh_hz" -v expected="$expected_refresh" -v tolerance="$refresh_tol" 'BEGIN { exit (hz >= expected - tolerance && hz <= expected + tolerance) ? 0 : 1 }'; then
    add_row '✅' 'Required refresh rate' "${display_refresh_hz} Hz (within ${refresh_tol} Hz of required ${expected_refresh} Hz)"
  else
    add_row '❌' 'Required refresh rate' "${display_refresh_hz} Hz is outside ${refresh_tol} Hz of required ${expected_refresh} Hz"
    fatal=1
  fi
elif [[ -n "$display_refresh_hz" ]]; then
  add_row '✅' 'Reported refresh rate' "${display_refresh_hz} Hz (active xrandr mode)"
else
  add_row '❌' 'Reported refresh rate' 'Could not read a refresh frequency from the active xrandr mode'
  fatal=1
fi

gvfs_dir="/run/user/$(id -u)/gvfs"
configured_mount_used=0
find_server_mount() {
  local matches candidate
  server_root=''
  # A configured absolute mount point wins over the gvfs glob. The Camp-Lab share
  # is a CIFS entry from the machine's own mount configuration (under /mnt), so it
  # never appears under the gvfs directory. Testing the path is what triggers a
  # systemd automount, so no mount command is issued here and no credentials are
  # kept in this repository. The timeout bounds an unreachable server.
  if [[ -n "${PREFLIGHT_SERVER_ROOT:-}" ]] && timeout 5 test -d "$PREFLIGHT_SERVER_ROOT"; then
    server_root="$PREFLIGHT_SERVER_ROOT"
    configured_mount_used=1
    return 0
  fi
  shopt -s nullglob
  matches=( "$gvfs_dir"/$PREFLIGHT_SERVER_MOUNT_GLOB )
  shopt -u nullglob
  for candidate in "${matches[@]}"; do
    if [[ -d "$candidate" ]]; then server_root="$candidate"; break; fi
  done
}
find_server_mount
if (( configured_mount_used )); then
  server_mount_status='configured_mount'
else
  server_mount_status='already_mounted'
fi
if [[ -z "$server_root" ]]; then
  # Try to mount the share so the operator does not have to open a file manager
  # first. Credentials come from the login keyring; gvfs may also show its own
  # authentication dialog, which is why this waits instead of failing instantly.
  if [[ -n "${PREFLIGHT_SERVER_URI:-}" ]] && command -v gio >/dev/null 2>&1; then
    # stdin is closed so a credential prompt fails immediately instead of
    # blocking on input nobody will type (gvfs otherwise prints
    # "User [name]:" and waits). The timeout only bounds a slow server.
    if timeout 10 gio mount "$PREFLIGHT_SERVER_URI" </dev/null >/dev/null 2>&1; then
      server_mount_status='mounted'
    else
      server_mount_status='mount_failed'
    fi
    find_server_mount
    # gvfs can report success while the share still does not appear under the
    # configured glob; never report that as a plain 'mounted'.
    if [[ -z "$server_root" && "$server_mount_status" == 'mounted' ]]; then
      server_mount_status='mount_not_visible'
    fi
  else
    server_mount_status='not_attempted'
  fi
fi
# A freshly mounted share can appear under the gvfs directory, and even pass a
# writability test, while gvfsd-smb is still connecting; the first read then
# fails with an I/O error. Probe the data path with a short retry rather than
# trusting -w on the mount root alone.
server_data_readable=0
if [[ -n "$server_root" ]]; then
  for _attempt in 1 2 3 4 5; do
    if [[ -d "$server_root/$PREFLIGHT_SERVER_DATA_PATH" ]] \
      && ls -- "$server_root/$PREFLIGHT_SERVER_DATA_PATH" >/dev/null 2>&1; then
      server_data_readable=1
      break
    fi
    sleep 0.4
  done
fi
if [[ -n "$server_root" && -w "$server_root" ]] && (( server_data_readable )); then
  add_row '✅' 'Lab server' "Mounted and writable: $server_root"
  export AV_STUDY_SERVER_ROOT="$server_root"
  export AV_STUDY_SERVER_DATA_PATH="$PREFLIGHT_SERVER_DATA_PATH"
else
  if [[ -n "$server_root" ]]; then
    add_row '⚠️' 'Lab server' "Mounted but $PREFLIGHT_SERVER_DATA_PATH is not readable/writable; check the share and re-run"
  else
    if [[ -n "${PREFLIGHT_SERVER_URI:-}" ]]; then
      add_row '⚠️' 'Lab server' "Not mounted ($server_mount_status); run 'gio mount $PREFLIGHT_SERVER_URI' once to store the credential, then re-run preflight"
    else
      add_row '⚠️' 'Lab server' "Not mounted ($server_mount_status); mount the lab server to continue"
    fi
  fi
  unset AV_STUDY_SERVER_ROOT AV_STUDY_SERVER_DATA_PATH || true
fi

# Code revision is reported at the end of the environment section: it informs the
# operator, and never blocks a session here.
if [[ "$git_state" == 'unavailable' ]]; then
  add_row '⚠️' 'Study code revision' 'Not a git checkout; session metadata will record no commit hash'
else
  git_label="${git_branch:-detached}@${git_commit:-unknown}"
  if [[ -n "$git_dirty" ]]; then
    add_row '⚠️' 'Study code revision' "$git_label has local modifications; commit them before collecting data"
  else
    add_row '✅' 'Study code revision' "$git_label"
  fi
  if [[ "$git_state" == 'fetch_failed' ]]; then
    add_row '⚠️' 'Study code updates' "Could not reach $git_upstream; update check skipped"
  elif [[ "$git_behind" =~ ^[0-9]+$ ]]; then
    if (( git_behind > 0 )); then
      add_row '⚠️' 'Study code updates' "$git_behind commit(s) behind $git_upstream; update deliberately, then re-run preflight"
    else
      add_row '✅' 'Study code updates' "Up to date with $git_upstream"
    fi
  fi
fi

# Reserve the ID on the shared server with an atomic claim. This is what stops
# two machines from both starting participant_03. Allocation order is still the
# lowest unused number.
claim_output="$(PYTHONPATH="$study_dir${PYTHONPATH:+:$PYTHONPATH}" "$python_bin" -c '
from pathlib import Path
from participant_setup import claim_next_participant_id
claim = claim_next_participant_id(Path("data"))
print(claim["participant_id"])
print(claim["path"])
print(claim["token"])
')" || {
  gui_error 'Could not reserve the next participant ID. Check that the lab server is writable, then run preflight again.'
  exit 1
}
participant_id="$(sed -n '1p' <<< "$claim_output")"
claim_path="$(sed -n '2p' <<< "$claim_output")"
claim_token="$(sed -n '3p' <<< "$claim_output")"
if [[ ! "$participant_id" =~ ^participant_[0-9]+$ || -z "$claim_path" || -z "$claim_token" ]]; then
  gui_error 'Could not reserve a valid participant ID and claim.'
  exit 1
fi
claim_active=1
release_claim() {
  PYTHONPATH="$study_dir${PYTHONPATH:+:$PYTHONPATH}" "$python_bin" -c '
import sys
from pathlib import Path
from participant_setup import release_participant_claim_if_unused
release_participant_claim_if_unused(Path("data"), Path(sys.argv[1]), sys.argv[2], sys.argv[3])
' "$claim_path" "$claim_token" "$participant_id" >/dev/null 2>&1 || true
}
# The EXIT trap installed with the display switch releases this claim too.
add_row '✅' 'Participant ID' "$participant_id (reserved on the lab server)"

# Created before the checklist so its early exits can remove it, and filled in
# after the debug-screen question so the report records that operator choice.
report="$(mktemp "${TMPDIR:-/tmp}/av-preflight-${participant_id}.XXXXXX")"
add_row '✅' 'Preflight report' 'Will be saved in the participant folder after launch'

summary="Review the checks below. Red items must be fixed before starting.
Yellow items need a manual check; if the lab server is unavailable you
will be asked to confirm local-only storage.

The experiment shows the finger placement screen, then checks the four
numpad keys and the sound before creating the participant plan."
zenity --list --title='AV study preflight checklist' --width=900 --height=480 \
  --text="$summary

Participant: $participant_id" \
  --column='Status' --column='Check' --column='Result' --print-column=2 \
  "${rows[@]}" >/dev/null || { rm -f -- "$report"; echo 'Preflight window closed.'; exit 1; }

if (( fatal )); then
  rm -f -- "$report"
  gui_error 'One or more required preflight checks failed. Fix the red items before starting.'
  exit 1
fi
if [[ -z "$server_root" || ! -w "$server_root" ]]; then
  if ! gui_yes "The lab server is unavailable or not writable.
Data will stay on this computer and will not be copied automatically.
Continue with local-only storage?"; then
    rm -f -- "$report"
    gui_info 'Preflight stopped. Mount the lab server and run preflight again, or acknowledge local-only storage to continue.'
    exit 1
  fi
fi
if gui_debug_choice "Run this session with the debug/testing screens?

Participant run is the safe default for real participants.
Debug run shows the operator plan screen and a per-frame overlay."; then
  debug_overlay=true
else
  debug_overlay=false
fi

# The consent form and the participant log live in the browser, which cannot be
# used from inside the fullscreen PsychoPy window. These steps run here: after
# the debug choice (a debug run may skip them) and before the report is written
# (so the report records what the RA confirmed). No participant folder exists
# yet, so stopping at a gate does not consume the reserved ID.
consent_form='not_requested'
participant_log='not_requested'
browser_close='not_requested'
browser_urls_opened=''
browser_gate_status=0

zenity --info --title='AV study preflight' --width=600 \
  --text="Participant ID for this session:

        $participant_id

Use this ID on the consent form and in the participant log." \
  >/dev/null || { rm -f -- "$report"; echo 'Preflight window closed.'; exit 1; }

open_in_browser() {
  [[ -n "$1" ]] || return 0
  xdg-open "$1" >/dev/null 2>&1 &
  browser_urls_opened+="${browser_urls_opened:+ }$1"
}

browser_gate() {
  gui_browser_gate "$1" "$2" && browser_gate_status=0 || browser_gate_status=$?
}

stop_at_browser_gate() {
  rm -f -- "$report"
  gui_info "The session was stopped at the $1 step. No participant folder was created; run preflight again when the participant is ready." || true
  exit 1
}

if [[ -z "${PREFLIGHT_CONSENT_URL:-}" || -z "${PREFLIGHT_PARTICIPANT_LOG_URL:-}" ]]; then
  consent_form='not_configured'
  participant_log='not_configured'
  browser_close='not_configured'
else
  open_in_browser "$PREFLIGHT_CONSENT_URL"
  browser_gate 'Consent completed' "The consent form was opened in the default browser.

Ask the participant to complete it, then confirm here.

Participant: $participant_id"
  case "$browser_gate_status" in
    0) consent_form='completed' ;;
    2) consent_form='skipped'; participant_log='skipped'; browser_close='skipped' ;;
    *) consent_form='declined' ;;
  esac
  if [[ "$consent_form" == 'declined' ]]; then
    stop_at_browser_gate 'consent'
  fi

  if [[ "$consent_form" == 'completed' ]]; then
    open_in_browser "$PREFLIGHT_PARTICIPANT_LOG_URL"
    browser_gate 'Added to the log' "The participant log was opened in the default browser.

Add $participant_id to the log, then confirm here."
    case "$browser_gate_status" in
      0) participant_log='confirmed' ;;
      2) participant_log='skipped'; browser_close='skipped' ;;
      *) participant_log='declined' ;;
    esac
    if [[ "$participant_log" == 'declined' ]]; then
      stop_at_browser_gate 'participant-log'
    fi
  fi

  if [[ "$participant_log" == 'confirmed' ]]; then
    browser_gate 'Browser closed' "Remember to close your browser before the study starts.

The experiment opens a fullscreen window, so close or hide every browser window first.

Participant: $participant_id"
    case "$browser_gate_status" in
      0) browser_close='confirmed' ;;
      2) browser_close='skipped' ;;
      *) browser_close='declined' ;;
    esac
    if [[ "$browser_close" == 'declined' ]]; then
      stop_at_browser_gate 'browser'
    fi
  fi
fi

# Versions the session actually ran on, so parity between machines is recorded
# rather than assumed. An import failure leaves this empty, which the report
# parser skips, instead of aborting the launcher.
runtime_versions="$(PYTHONPATH="$study_dir${PYTHONPATH:+:$PYTHONPATH}" "$python_bin" -c '
import platform
import numpy
import PIL
import psychopy
import psychtoolbox
print(f"python_version={platform.python_version()}")
print(f"psychopy_version={psychopy.__version__}")
print(f"psychtoolbox_version={psychtoolbox.__version__}")
print(f"numpy_version={numpy.__version__}")
print(f"pillow_version={PIL.__version__}")
' 2>/dev/null || true)"

# Identity for the saved report only: the checklist is already long, so none of
# this becomes a row. The OS release and the panel's own EDID identity are stored
# with the session so a run can be attributed to a specific distro and panel, not
# just a kernel version and an output name.
os_release=''
if [[ -r /etc/os-release ]]; then
  os_release="$(. /etc/os-release 2>/dev/null; printf '%s' "${PRETTY_NAME:-}")"
fi
# Decoded from the active output's EDID: bytes 8-9 are the PNP id, the 0xFC
# descriptor is the model name and 0xFF the serial. Empty when the driver exposes
# no EDID for the output, and never fatal.
monitor_identity="$(PYTHONPATH="$study_dir${PYTHONPATH:+:$PYTHONPATH}" "$python_bin" - "$display_output" <<'PY' 2>/dev/null || true
import subprocess
import sys

output = sys.argv[1] if len(sys.argv) > 1 else ""
if not output:
    raise SystemExit(0)
try:
    text = subprocess.run(
        ["xrandr", "--props"], capture_output=True, text=True, timeout=5
    ).stdout
except Exception:
    raise SystemExit(0)
blocks, inside, in_edid = [], False, False
for line in text.splitlines():
    if line and not line[0].isspace():
        fields = line.split()
        inside = bool(fields) and fields[0] == output and " connected" in line
        in_edid = False
        continue
    if not inside:
        continue
    stripped = line.strip()
    if stripped.startswith("EDID:"):
        in_edid = True
        continue
    if in_edid:
        token = stripped.split()[0] if stripped else ""
        if len(token) == 32 and all(c in "0123456789abcdef" for c in token):
            blocks.append(token)
        else:
            in_edid = False
data = bytes.fromhex("".join(blocks)) if blocks else b""
if len(data) < 128:
    raise SystemExit(0)
manufacturer = (data[8] << 8) | data[9]
pnp = "".join(chr(((manufacturer >> shift) & 0x1f) + 64) for shift in (10, 5, 0))
model, serial = "", ""
for offset in range(54, 126, 18):
    block = data[offset:offset + 18]
    if block[0:3] != b"\x00\x00\x00":
        continue
    value = block[5:].split(b"\n")[0].decode("ascii", "replace").strip()
    if block[3] == 0xFC and not model:
        model = value
    elif block[3] == 0xFF and not serial:
        serial = value
print(f"pnp={pnp}")
print(f"product_code=0x{data[11] << 8 | data[10]:04x}")
print(f"model={model}")
print(f"serial={serial}")
PY
)"
monitor_pnp_id="$(sed -n 's/^pnp=//p' <<< "$monitor_identity")"
monitor_product_code="$(sed -n 's/^product_code=//p' <<< "$monitor_identity")"
monitor_model="$(sed -n 's/^model=//p' <<< "$monitor_identity")"
monitor_serial="$(sed -n 's/^serial=//p' <<< "$monitor_identity")"
# Every USB device the machine can see, on one line: the DAC/amp and the input
# devices have no other machine-readable identity on this hardware.
usb_devices=''
if command -v lsusb >/dev/null 2>&1; then
  # awk, not 'paste -sd "; "': paste cycles every character of its delimiter
  # list, which interleaves ';' and ' ' instead of joining with both.
  usb_devices="$(lsusb 2>/dev/null \
    | sed -n 's/^Bus [0-9]* Device [0-9]*: ID //p' \
    | awk 'NR > 1 { printf "; " } { printf "%s", $0 } END { printf "\n" }' || true)"
fi

# Written here rather than with the checklist above so the saved report (and the
# session metadata parsed from it) records whether the debug overlay ran.
{
  printf 'measured_at=%s\n' "$(date --iso-8601=seconds)"
  printf 'study_dir=%s\nparticipant_id=%s\n' "$study_dir" "$participant_id"
  printf '%s\n' "$runtime_versions"
  printf 'session_type=%s\ndisplay_output=%s\nactive_mode=%s\ndisplay_refresh_hz=%s\n' "$session_type" "$display_output" "$active_mode" "$display_refresh_hz"
  printf 'display_mode_action=%s\ndisplay_mode_set=%s\n' "$display_mode_action" "${display_mode_set:-}"
  printf 'audio_route=%s\npipewire_jack_library=%s\n' 'PTB via PipeWire JACK' "$pipewire_jack_lib"
  printf 'audio_route_device=%s\naudio_route_sink=%s\n' "${default_sink_desc:-}" "${default_sink:-}"
  printf 'audio_chain=%s\naudio_headphones=%s\n' "$audio_chain" "$audio_headphones"
  printf 'audio_device_expected=%s\naudio_device_actual=%s\n' "$expected_audio_device" "${default_sink_desc:-}"
  printf 'git_branch=%s\ngit_commit=%s\ngit_dirty=%s\ngit_behind=%s\ngit_upstream=%s\n' "${git_branch:-}" "${git_commit:-}" "${git_dirty:-}" "${git_behind:-}" "${git_upstream:-}"
  # Machine identity belongs in the saved report only; the checklist does not show
  # it. glxinfo comes from mesa-utils and is absent on some machines.
  printf 'machine_name=%s\nmachine_uuid=%s\nmachine_model=%s\nmachine_serial=%s\nmachine_mac=%s\nmachine_host=%s\n' \
    "$machine_name" "$machine_uuid" "$machine_model" "$machine_serial" "$machine_mac" "$(uname -n 2>/dev/null || true)"
  printf 'os_release=%s\nmonitor_pnp_id=%s\nmonitor_product_code=%s\nmonitor_model=%s\nmonitor_serial=%s\n' \
    "$os_release" "$monitor_pnp_id" "$monitor_product_code" "$monitor_model" "$monitor_serial"
  printf 'usb_devices=%s\n' "$usb_devices"
  printf 'hardware_host=%s\nhardware_cpu=%s\nhardware_cores=%s\nhardware_memory=%s\nhardware_kernel=%s\nhardware_gpu=%s\n' \
    "$(uname -n 2>/dev/null || true)" \
    "$(awk -F': ' '/^model name/{print $2; exit}' /proc/cpuinfo 2>/dev/null || true)" \
    "$(nproc 2>/dev/null || true)" \
    "$(awk '/^MemTotal:/{printf "%.1f GB", $2/1048576}' /proc/meminfo 2>/dev/null || true)" \
    "$(uname -r 2>/dev/null || true)" \
    "$(glxinfo -B 2>/dev/null | sed -n 's/^OpenGL renderer string: //p' | head -n 1 || true)"
  printf 'server_mount_status=%s\n' "${server_mount_status:-not_attempted}"
  printf 'system_volume_percent=%s\nsystem_volume_actual=%s\nsystem_volume_status=%s\n' "$system_volume" "$system_volume_actual" "$system_volume_status"
  printf 'audio_balance=%s\naudio_balance_status=%s\n' "${audio_balance:-unknown}" "$audio_balance_status"
  printf 'debug_overlay=%s\n' "$debug_overlay"
  printf 'consent_form=%s\nparticipant_log=%s\nbrowser_close=%s\n' "$consent_form" "$participant_log" "$browser_close"
  printf 'browser_urls_opened=%s\n' "$browser_urls_opened"
  printf 'server_mounted=%s\n' "$([[ -n "$server_root" && -w "$server_root" ]] && printf true || printf false)"
  [[ -z "$server_root" ]] || printf 'server_root=%s\nserver_data_path=%s\n' "$server_root" "$PREFLIGHT_SERVER_DATA_PATH"
  printf '\nConnected display modes:\n%s\n' "$display_info"
} > "$report"
planned_block_order="$(PYTHONPATH="$study_dir${PYTHONPATH:+:$PYTHONPATH}" "$python_bin" -c 'from pathlib import Path; from participant_setup import planned_block_order, data_directories; order, count = planned_block_order(data_directories(Path("data"))); print("Animals, then Objects" if order[0] == "animate" else "Objects, then Animals")')" || {
  rm -f -- "$report"
  gui_error 'Could not calculate the planned block order.'
  exit 1
}
gui_yes "Preflight checks are complete. Start $participant_id?

Planned block order: $planned_block_order
The participant plan will be created when the experiment starts." || { rm -f -- "$report"; gui_info 'Preflight passed. The experiment was not started.'; exit 0; }
export AV_STUDY_PREFLIGHT_REPORT="$report"
export AV_STUDY_DEBUG_OVERLAY="$debug_overlay"
# The device the session must open: the machine's pinned expectation when it has
# one, otherwise the default sink this launcher just validated and pinned the
# volume on. audio_ptb.open_ptb_speaker opens exactly this instead of ranking
# device names.
export AV_STUDY_AUDIO_DEVICE="${expected_audio_device:-$default_sink_desc}"
export AV_STUDY_PARTICIPANT_CLAIM="$claim_path"
export AV_STUDY_PARTICIPANT_CLAIM_TOKEN="$claim_token"
runner_log="$(mktemp "${TMPDIR:-/tmp}/av-experiment-${participant_id}.XXXXXX")"
warnings_file="$study_dir/data/$participant_id/operator_warnings.txt"
show_operator_warnings() {
  zenity --text-info --title="AV study operator warnings — $participant_id" --width=760 --height=420 \
    --filename="$warnings_file" || true
}
if pw-jack env LD_PRELOAD="$pipewire_jack_lib" "$python_bin" "$study_dir/experiment.py" "$participant_id" >"$runner_log" 2>&1; then
  if [[ -s "$warnings_file" ]]; then
    cp -- "$runner_log" "$study_dir/data/$participant_id/runner.log"
    show_operator_warnings
  fi
  rm -f -- "$runner_log"
  if [[ ! -d "$study_dir/data/$participant_id" ]]; then
    gui_info "The runner stopped during the finger placement, numpad, or sound check. No plan was created and $participant_id was not used."
  elif ! compgen -G "$study_dir/data/$participant_id/session_*" >/dev/null; then
    gui_info "The runner stopped after creating the plan for $participant_id but before the session began. That ID is now used; run preflight again for the next participant."
  fi
else
  run_status=$?
  # Keep the temporary log if no plan exists; do not create a participant
  # folder just for diagnostics, since any such folder consumes its ID.
  log_copy="$runner_log"
  if [[ -d "$study_dir/data/$participant_id" ]]; then
    participant_log="$study_dir/data/$participant_id/launch_error.log"
    if cp -- "$runner_log" "$participant_log"; then
      log_copy="$participant_log"
    fi
  fi
  error_tail="$(tail -n 18 -- "$runner_log")"
  if [[ "$log_copy" != "$runner_log" ]]; then
    rm -f -- "$runner_log"
  fi
  if [[ -s "$warnings_file" ]]; then
    show_operator_warnings
  fi
  gui_error "The experiment runner exited with status $run_status.

$error_tail

Full log: $log_copy"
  exit "$run_status"
fi
