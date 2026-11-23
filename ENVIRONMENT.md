# Study environment setup (per lab computer)

Ubuntu 24.04 LTS. Everything below was captured from a known-working install on
2026-10-12. Keep versions identical across devices so timing and audio behavior
match.

## 0. Quick start on a new computer

1. Install the system packages in section 1 (needs `sudo`, once per machine).
2. Clone the study and build the runtime:

   ```bash
   git clone https://github.com/anthonymfrance/avrebuild.git
   cd avrebuild
   git checkout pilot-2026-11.7                      # pinned pilot code; main tracks ongoing work
   curl -LsSf https://astral.sh/uv/install.sh | sh   # once per machine, no sudo
   uv venv --python 3.10 .venv
   uv pip install --python .venv/bin/python -r requirements-lock.txt
   .venv/bin/python -c 'import psychopy, psychtoolbox, numpy, PIL; print("runtime ok")'
   ```

3. Name the computer: write `preflight_local.sh` (section 3, *Name this computer*).
4. Mount the lab share once through Files and tick **Remember forever** (section 5).
5. Log in on **Xorg**, confirm it with the command below, then run `./preflight.sh`
   — every row should be green or a yellow you have deliberately accepted.

   ```bash
   echo "$XDG_SESSION_TYPE"     # must print: x11
   ```

   This is a gate, not a formality. On GNOME with the proprietary NVIDIA driver a
   login can default to Wayland without anything looking wrong, and `xrandr`
   cannot set or restore a mode there — the display rows would "pass" while the
   mode was never switched. If it prints `wayland`, log out, pick **Xorg** on the
   login screen's gear menu, and re-check before going further.

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

### Graphics: integrated Intel **plus** a discrete NVIDIA card

An earlier version of this file claimed the lab machines use Intel HD Graphics 530
with "no NVIDIA card present" and that the NVIDIA packages were leftovers safe to
autoremove. Both statements are wrong on the machines in use, and the autoremove
advice is dangerous.

What the lab computers actually report:

```bash
lspci | grep -Ei 'vga|3d'        # Intel HD Graphics 630 + NVIDIA GP104 [GeForce GTX 1080]
nvidia-smi --query-gpu=name,driver_version --format=csv,noheader   # GTX 1080, 580.178.04
glxinfo -B | grep renderer      # OpenGL renderer: NVIDIA GeForce GTX 1080/PCIe/SSE2
```

The NVIDIA 580 driver is the **live** display driver (`nvidia`, `nvidia_drm`,
`nvidia_modeset` are loaded), not a leftover. Do **not** run `sudo apt autoremove`,
`apt remove` or `apt purge` against the `nvidia-*` / `libnvidia-*` packages on a
lab machine: stripping the running driver can drop the session out of the
120 Hz display mode, and doing that the night before a participant is a data
loss, not an inconvenience.

`apt autoremove` may offer to remove an orphaned `nvidia-firmware-580-server`
firmware blob left by an older driver version. That one is harmless, but it is
the only NVIDIA package that is, so remove it by exact name at most.

Check the graphics stack with `lspci` and `glxinfo -B` on each computer rather
than trusting a model name written in this file.

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

Without `uv` you need `sudo apt-get install python3-venv` first: stock Ubuntu
24.04 has no working `ensurepip`, so `python3 -m venv` silently creates a venv
with no pip in it.

```bash
sudo apt-get install -y python3-venv
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-lock.txt
```

The lock also installs on 3.12 (verified), but run 3.10 to match the pilots;
`uv venv --python 3.10` fetches that interpreter without apt. If a `.venv`
already exists and is broken, rebuild it with `uv venv --clear --python 3.10 .venv`.

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

The name, plus the machine's UUID, DMI model, serial and wired NIC MAC, is written
into every session as `machine_name`, `machine_uuid`, `machine_model`,
`machine_serial` and `machine_mac`, and is the first column of
`tools/device_report.py`. A changed hostname, a moved disk or a swapped NIC
cannot merge two computers in the data.

`/sys/class/dmi/id/product_uuid` and `product_serial` are root-only, and preflight
runs as the normal user, so read them **once** with `sudo` and keep the values in
`preflight_local.sh` — never in the tracked config:

```bash
sudo cat /sys/class/dmi/id/product_uuid /sys/class/dmi/id/product_serial
```

```bash
# preflight_local.sh
PREFLIGHT_MACHINE_UUID='...'
PREFLIGHT_MACHINE_SERIAL='...'
```

Without them preflight falls back to `/etc/machine-id`, which is unique per
install but changes if the OS is reinstalled.

## 4. Display + session

- X11 session (`XDG_SESSION_TYPE=x11`), not Wayland — verify with
  `echo "$XDG_SESSION_TYPE"` (see section 0, step 5). The display automation uses
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

## 6. Running the tests

`pytest` is part of the lock, so it is already in `.venv`:

```bash
.venv/bin/python -m pytest tests/test_preflight.py -q
```

`tests/test_preflight.py` writes fake `zenity`/`pactl`/`xrandr` scripts whose
shebang is the interpreter's absolute path. If the project sits under a path with
a space in it, run the suite from a copy without one (for example `tar` the tree
into `/tmp/run-tests`); the study itself is unaffected.

## 7. Sanity checks after setup

1. `./preflight.sh` → checklist all green.
2. Confirm the "PTB audio route" row is ✅ (this is the check that fails when
   `pipewire-jack` is missing).
3. If display or audio check fails, re-check sections 2 and 4 above.
