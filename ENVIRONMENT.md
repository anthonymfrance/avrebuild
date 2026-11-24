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
| `gvfs-backends` | SMB mounts made through Files (shows under `/run/user/<uid>/gvfs/`). Only the legacy fallback: the Camp-Lab share is a system-level CIFS mount, see section 5. |
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
resolved at run time, so a different codec, chassis or USB DAC is fine.

A digital sink (S/PDIF, HDMI) is rejected by default, because most machines
should play from the wired headphone output. This lab's route *is* the DAC's
S/PDIF output, so `preflight_config.sh` sets `PREFLIGHT_ALLOW_DIGITAL_SINK='1'`
and the row reports an accepted digital route instead of a red one. Leave it at
`0` on a machine where the route is meant to be analog.

The session follows the **system default output**. `preflight.sh` exports the sink
it validated as `AV_STUDY_AUDIO_DEVICE`, and `audio_ptb.open_ptb_speaker` opens
exactly that PTB device; it no longer ranks device names, which used to prefer any
device called “Built-in Audio” and could send a USB DAC's session to the
motherboard output while the volume was pinned on the DAC.

A machine records the output it expects with `PREFLIGHT_AUDIO_DEVICE` in
`preflight_local.sh` (exact PTB device name, for example
`'iFi USB Audio SE UAC1 Digital Stereo (IEC958)'`). Preflight then shows an
**Expected audio device** row and fails when the OS default is something else, and
the session opens that device.

### Finding that value on a new machine

`PREFLIGHT_AUDIO_DEVICE` must match the *description* of the sink the machine
uses, which is also the name PTB sees through PipeWire JACK. Read both, then copy
the description:

```bash
pactl get-default-sink                                  # which sink is the default
pactl list sinks | grep -A3 'Description:'              # its human name + the others

# the names PTB will actually open (needs pipewire-jack, section 1)
pw-jack env LD_PRELOAD=$(ls /usr/lib/*/pipewire-0.3/jack/libjack.so | head -1) \
  .venv/bin/python -c 'import psychtoolbox.audio as a; [print(p["DeviceName"]) for p in a.get_devices() if int(p["NrOutputChannels"]) >= 2]'
```

If the default is not the output the study should use, change it in **Settings →
Sound** (or `pactl set-default-sink <sink name>`) before preflight — the launcher
only reads the default, it never chooses one. A digital output also needs
`PREFLIGHT_ALLOW_DIGITAL_SINK='1'` on that machine (section 2). Leave
`PREFLIGHT_AUDIO_DEVICE` empty when any default output is acceptable: the session
then follows whatever the OS default is.

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
PREFLIGHT_MACHINE_ROOM='405'
PREFLIGHT_AUDIO_HEADPHONES=''
EOF
```

The name, the room and the machine's UUID, DMI model, serial and wired NIC MAC are
written into every session as `machine_name`, `machine_room`, `machine_uuid`,
`machine_model`, `machine_serial` and `machine_mac`, and are the first columns of
`tools/device_report.py`. A changed hostname, a moved disk or a swapped NIC cannot
merge two computers in the data.

`PREFLIGHT_MACHINE_ROOM` is **one-time operator setup**, written by hand when the
computer is installed: it is never asked of a participant, never shown to one, and
never parsed out of the machine name (names get reworded, rooms do not). Leave it
empty and sessions simply record no room.

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

The name, UUID and serial for each computer are also written down with the rest
of its hardware (CPU, GPU, monitor, audio device, keyboard, mouse) in
[`HARDWARE.md`](HARDWARE.md), so a machine can be identified in the data without
logging into it.

## 4. Display + session

- X11 session (`XDG_SESSION_TYPE=x11`), not Wayland — verify with
  `echo "$XDG_SESSION_TYPE"` (see section 0, step 5). The display automation uses
  `xrandr`, which cannot change modes under Wayland.
- **1920×1080 @ 120 Hz** (`config.WINDOW_SIZE = (1920, 1080)`,
  `config.REQUIRED_REFRESH_HZ = 120`, tolerance 1 Hz).
- `preflight.sh` switches the active output to that mode when it launches, fails
  clearly if the panel cannot offer it, and restores the panel's largest, fastest
  mode when the launcher exits (including a failure or ESC).

## 5. Lab server

The lab share is a CIFS mount provided by the machine's own mount configuration,
not by Files:

```
//psyc-files.ucsc.edu/PSYC-Projects/Camp-Lab  ->  /mnt/camp-lab-server
```

`preflight_config.sh` points at it with
`PREFLIGHT_SERVER_ROOT='/mnt/camp-lab-server/Anthony'` and
`PREFLIGHT_SERVER_DATA_PATH='data'`, so sessions land in
`/mnt/camp-lab-server/Anthony/data/participant_NN/`. Merely testing that path
triggers the systemd automount, so preflight never mounts the share itself, stores
no credentials, and does not need `gio`. If the mount is unavailable (off campus,
for example) the row turns yellow and the operator is asked to accept local-only
storage.

`PREFLIGHT_SERVER_URI` and `PREFLIGHT_SERVER_MOUNT_GLOB` remain in
`preflight_config.sh` as a fallback for a machine that still mounts the SMB share
through Files; they are used only when `PREFLIGHT_SERVER_ROOT` is empty or missing.

Preflight reserves each participant ID with an atomic claim in
`<data>/.claims/participant_NN.lock` before the session starts. The claim records
the allocating PID, host, and UTC start time, so two lab computers cannot both run
the same participant number. Abandoned claims expire after
`config.PARTICIPANT_CLAIM_TTL_HOURS` (12 hours).

A claim whose participant folder is missing from **every** data root is reclaimed
after `participant_setup.ORPHAN_CLAIM_AGE_HOURS` (2 hours) instead, so a setup that
died before the plan was generated cannot hold a number for half a day. The window
is that long on purpose: a session running on another computer keeps its folder on
that computer and copies nothing to the share until it is saved, so from here a
live session and a dead claim look the same, and only age tells them apart. Nothing
but the reservation file is deleted — participant folders are never touched.

`/mnt/camp-lab-server/Anthony/data/old data/` holds the five sessions collected
before this machine moved to the Camp-Lab share (`participant_01`..`participant_05`).
Those folders do not match `participant_NN`, so allocation in `data/` restarts at
`participant_01` and the block-order rotation restarts at animate-first. To
continue that numbering instead, set
`PREFLIGHT_SERVER_DATA_PATH='data/old data'`.

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

### Updating the code from the launcher

Preflight compares the checkout with its upstream on every launch, so nobody has
to walk between computers to `git pull`. When the machine is behind it asks
first:

- **Yes, update** runs `git pull --ff-only` (never a merge, never touching local
  changes), then restarts preflight so every check runs on the new code.
- **No, run this version** starts the session on the code already installed. The
  "Study code updates" row then says the update was offered and declined.

Either way `preflight_report.txt` records `git_update=`, so a session can be
traced to the revision it actually ran on. No offer is made when the checkout has
local modifications or the remote cannot be reached; those show as a yellow row
instead.

## 8. Machine-local requirements (not in git)

A clone gets the code, never a computer's identity or its mounts. Everything a
machine needs beyond `git clone` and the packages in section 1 lives on that
machine, and preflight reports each one:

| Requirement | Where it lives | Preflight row |
| --- | --- | --- |
| `PREFLIGHT_MACHINE_NAME` | `preflight_local.sh` | Machine |
| `PREFLIGHT_MACHINE_ROOM` (one-time operator setup) | `preflight_local.sh` | Machine |
| `PREFLIGHT_MACHINE_UUID`, `PREFLIGHT_MACHINE_SERIAL` | `preflight_local.sh`, read once with sudo from `/sys/class/dmi/id` | Machine, session metadata |
| `PREFLIGHT_AUDIO_HEADPHONES` | `preflight_local.sh` | Audio chain |
| `PREFLIGHT_AUDIO_DEVICE` (exact PTB device name; see section 2 for how to read it) | `preflight_local.sh` | Expected audio device |
| Lab share mount | the machine's mount configuration (`//psyc-files.ucsc.edu/PSYC-Projects/Camp-Lab` on `/mnt/camp-lab-server`) | Lab server |
| `.venv` from `requirements-lock.txt` | the checkout | Experiment runtime |
| System packages | apt, section 1 | PTB audio route, Lab server |
| A panel offering 1920×1080 @ ~120 Hz | hardware | Experiment display mode, Required refresh rate |
| X11 session | login screen | `XDG_SESSION_TYPE=x11` gate |

Record the same values in [`HARDWARE.md`](HARDWARE.md) so a session's
`machine_uuid` can be traced to a computer and a room during analysis. Neither a
clone nor another machine inherits any of this, which is the point: two computers
must never share an identity. A machine is ready when `./preflight.sh` shows no
red rows.
