# Study environment setup (per lab computer)

Ubuntu 24.04 LTS. Everything below was captured from a known-working install on
2026-10-12. Keep versions identical across devices so timing and audio behavior
match.

## 1. System packages (apt)

```bash
sudo apt-get update
sudo apt-get install -y \
  zenity \
  xdg-utils \
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
| `xdg-utils` | `xdg-open` opens the consent form and the participant log in the default browser |
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
PTB → PipeWire JACK → whatever sink the system default points at. The sink is
resolved at run time, so a different codec, chassis or USB DAC is fine; a
digital sink (S/PDIF, HDMI) is rejected because it is not the headphone route.

1. Install `pipewire-jack` (see above).
2. Confirm PipeWire daemons are running: `pgrep -c pipewire` should print ≥ 3
   (`pipewire`, the `filter-chain.conf` instance, and `pipewire-pulse`).
3. Default sink must be the wired headphone output (any analog sink) with
   balance 0.00:

   ```bash
   pactl get-sink-volume @DEFAULT_SINK@   # front-left and front-right equal, balance 0.00
   ```

   `preflight.sh` automatically sets the default sink to
   `config.SYSTEM_VOLUME_PERCENT` (50% on the piloted branch) on every launch and
   verifies the level, so output volume does not drift between sessions or
   devices.

4. `preflight.sh` verifies the full route itself (PTB must see the configured
   sink through PipeWire JACK); it is the source of truth.
5. Record the headphones: set `PREFLIGHT_AUDIO_HEADPHONES` in
   `preflight_config.sh` (for example `'Sony MDR-7506'`). The machine can see the
   codec or DAC but never the headphones, so this is the one part of the audio
   chain that has to be written down per computer. It lands in every session's
   metadata and in `tools/device_report.py`.

## 3. Study runtime (one command per machine)

Every computer installs the same pinned package set, so timing and audio
behaviour match:

```bash
cd /path/to/avrebuild
uv venv --python 3.10 .venv
uv pip install --python .venv/bin/python -r requirements-lock.txt
```

Without `uv`, the standard library equivalent needs nothing extra:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-lock.txt
```

`preflight.sh` uses `./.venv/bin/python` automatically once it imports PsychoPy,
and falls back to the PsychoPy app runtime only when it does not.

- **[`requirements-lock.txt`](requirements-lock.txt) is the source of truth:**
  92 pinned packages, verified to install into a clean Python 3.10 environment.
  Launching the PsychoPy app is no longer needed to provision the experiments.
- [`requirements-psychopy-2026.1.3.txt`](requirements-psychopy-2026.1.3.txt) is a
  **reference snapshot** of the PsychoPy app's own runtime. It does not resolve
  (`javascripthon 0.13` requires `dukpy<=0.2.3` while the app ships `dukpy 0.5.1`),
  so do not install from it.
- The versions a session actually ran on are written into its metadata
  (`python_version`, `psychopy_version`, `psychtoolbox_version`, `numpy_version`,
  `pillow_version`). Compare machines with `python3 tools/device_report.py`.
- `pytest` is part of the lock, so `tests/` runs on any machine that uses it.

### Name this computer

Each computer keeps its identity in an untracked `preflight_local.sh` (gitignored),
so a clone never inherits another machine's name:

```bash
cat > preflight_local.sh <<'EOF'
PREFLIGHT_MACHINE_NAME='right-purple-405'
PREFLIGHT_AUDIO_HEADPHONES=''
EOF
```

The name, plus `/etc/machine-id`, the DMI model and the wired NIC's MAC, is written
into every session as `machine_name`, `machine_uuid`, `machine_model` and
`machine_mac`, and is the first column of `tools/device_report.py`. A changed
hostname or a moved disk therefore cannot merge two computers in the data. The DMI
product UUID and serial are root-only, which is why the machine-id is used instead.

## 4. Display + session

- X11 session (`XDG_SESSION_TYPE=x11`), not Wayland. The display automation uses
  `xrandr`, which cannot change modes under Wayland.
- **1920×1080 @ 120 Hz** (`config.WINDOW_SIZE = (1920, 1080)`,
  `config.REQUIRED_REFRESH_HZ = 120`, tolerance 1 Hz).
- `preflight.sh` switches the active output to that mode when it launches, fails
  clearly if the panel cannot offer it, and restores the panel's largest, fastest
  mode when the launcher exits (including a failure or ESC).

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
