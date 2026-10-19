# Study environment setup (per lab computer)

Ubuntu 24.04 LTS. Everything below was captured from a known-working install on
2026-10-12. Keep versions identical across devices so timing and audio behavior
match.

## 1. System packages (apt)

```bash
sudo apt-get update
sudo apt-get install -y \
  zenity \
  pipewire pipewire-pulse pipewire-jack wireplumber \
  pulseaudio-utils \
  x11-xserver-utils \
  gvfs-backends \
  git \
  mesa-utils
```

Why each is required:

| Package | Why |
| --- | --- |
| `zenity` | `preflight.sh` GUI dialogs |
| `pipewire`, `pipewire-pulse`, `wireplumber` | Default Ubuntu audio stack; drives the analog headphone sink |
| `pipewire-jack` | Ships `pw-jack` and the PipeWire JACK `libjack.so`; **this one is easy to miss** — it is *not* a dependency of the base PipeWire install. Without it the PTB audio-route check fails and preflight will not pass. |
| `pulseaudio-utils` | `pactl` (reads/clears the headphone L/R balance) |
| `x11-xserver-utils` | `xrandr` (display mode + refresh checks) |
| `gvfs-backends` | SMB mounts of the lab file server (shows under `/run/user/<uid>/gvfs/`) |
| `git` | experiment metadata records the commit hash |
| `mesa-utils` | `glxinfo` sanity check of the GL stack when debugging display timing |

This machine uses **Intel HD Graphics 530** graphics (no NVIDIA card is present).
The leftover `nvidia-535` packages installed by an old image are unused; they can
be cleaned with `sudo apt autoremove` if desired.

## 2. Audio route used by the study

The experiment runs PTB (PortAudio) through `pw-jack` so audio goes
PTB → PipeWire JACK → built-in analog headphone out.

1. Install `pipewire-jack` (see above).
2. Confirm PipeWire daemons are running: `pgrep -c pipewire` should print ≥ 3
   (`pipewire`, the `filter-chain.conf` instance, and `pipewire-pulse`).
3. Default sink must be the built-in analog stereo output with balance 0.00:

   ```bash
   pactl get-sink-volume @DEFAULT_SINK@   # front-left and front-right equal, balance 0.00
   ```

   `preflight.sh` automatically sets the default sink to
   `config.SYSTEM_VOLUME_PERCENT` (75%) on every launch and verifies the level,
   so output volume does not drift between sessions or devices.

4. `preflight.sh` verifies the full route itself (PTB sees the JACK-built-in
   device); it is the source of truth.

## 3. PsychoPy runtime

- PsychoPy **2026.1.3**, provisioned by the PsychoPy app under
  `~/.config/psychopy4/.python/2026.1.3/bin/python3` (Python 3.10.18).
- On a fresh device, launch the PsychoPy app once so it creates that runtime,
  or set `AV_STUDY_PYTHON` to an equivalent `bin/python3` path.
- Frozen Python package list: see
  [`requirements-psychopy-2026.1.3.txt`](requirements-psychopy-2026.1.3.txt).
  The packages the study code touches directly (versions must match):

  - psychopy-lib 2026.1.3
  - psychtoolbox 3.0.19.14
  - numpy 2.2.6
  - pillow 11.3.0
  - pyglet 1.5.27
  - questplus 2023.1

## 4. Display + session

- X11 session (`XDG_SESSION_TYPE=x11`), not Wayland.
- Screen: HDMI-1, primary, **1920×1080 @ 120 Hz**
  (`config.WINDOW_SIZE = (1920, 1080)`, `config.REQUIRED_REFRESH_HZ = 120`,
  tolerance 1 Hz).

## 5. Lab server mount

Server destination: `Experiments/Anthony/data/participant_NN/` (see `PREFLIGHT_SERVER_DATA_PATH` in `preflight_config.sh`).

Preflight reserves each participant ID with an atomic claim in
`Experiments/Anthony/data/.claims/participant_NN.lock` before the session
starts. The claim records the allocating PID, host, and UTC start time, so two
lab computers cannot both run the same participant number. Abandoned claims
expire after `config.PARTICIPANT_CLAIM_TTL_HOURS` (12 hours).

## 6. Optional (dev only)

- `pytest` is **not** installed in either Python on this machine. If you want to
  run `tests/`, install it into the PsychoPy runtime:

  ```bash
  ~/.config/psychopy4/.python/2026.1.3/bin/python3 -m pip install pytest
  ```

## 7. Sanity checks after setup

1. `./preflight.sh` → checklist all green.
2. Confirm the "PTB audio route" row is ✅ (this is the check that fails when
   `pipewire-jack` is missing).
3. If display or audio check fails, re-check sections 2 and 4 above.
