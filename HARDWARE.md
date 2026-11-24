# Lab computer inventory

One section per lab computer: the identity preflight records in every session
(`machine_name`, `machine_uuid`, `machine_serial`, `machine_mac`, `machine_model`)
plus the hardware around it, so a machine can be identified in the data without
logging into it.

**Why this file is tracked:** every session records `machine_uuid` and
`machine_name` in `session_metadata.json`. This file is the lookup from that UUID
to the physical computer and the room it sits in, so a session can be attributed
during analysis without logging into the machine. Add one section per computer and
keep it committed.

Values marked **auto** were read from the machine on 2026-11-24 with `lscpu`,
`lsblk`, `xrandr`, `lsusb`, `pactl`, `nvidia-smi` and `/sys/class/dmi/id`; the
same fields are re-measured at every run and land in each session's metadata.
Values marked **fill in** cannot be detected, so they are recorded by hand.

`preflight_local.sh` (untracked, gitignored) is the source of truth for
`PREFLIGHT_MACHINE_NAME`, `PREFLIGHT_MACHINE_UUID` and `PREFLIGHT_MACHINE_SERIAL`;
keep this file in sync with it.

---

## leftmost-435-dark-blue

| Field | Value |
| --- | --- |
| Study machine name | `leftmost-435-dark-blue` (`PREFLIGHT_MACHINE_NAME`) |
| Room | 435 (`PREFLIGHT_MACHINE_ROOM`, one-time operator setup) |
| DMI product UUID | `4c4c4544-0057-5210-8030-cac04f584b32` (`PREFLIGHT_MACHINE_UUID`) |
| DMI product serial | `JWR0XK2` (`PREFLIGHT_MACHINE_SERIAL`) |
| Hostname | `malibu-creek-Aurora-R6` |
| Model | Alienware Aurora R6 (DMI type 3, desktop) |
| Motherboard | Alienware `07HV66` rev `A01` |
| BIOS | `1.0.23`, 2020-06-11 |
| OS / kernel | Ubuntu 24.04.5 LTS, `6.17.0-14-generic` x86_64 |
| CPU | Intel Core i7-7700 @ 3.60 GHz, 4 cores / 8 threads, 1 socket (auto) |
| RAM | 15.4 GB (auto) |
| GPU | NVIDIA GP104 GeForce GTX 1080, driver `580.178.04`, OpenGL renderer `NVIDIA GeForce GTX 1080/PCIe/SSE2` (auto) |
| Storage | SanDisk X400 M.2 2280 256 GB (auto) |
| Wired NIC (recorded as `machine_mac`) | `enp4s0` `14:b3:1f:1a:76:4f` (auto) |
| Wireless NIC | `wlp3s0` `f8:34:41:8b:ce:b9` (auto, not recorded in sessions) |
| Session type | X11 (auto) |
| Monitor | DP-0, 2560×1440 @ 240 Hz, 600×340 mm; also offers 1920×1080 @ 119.98 Hz, which preflight selects (auto) |
| Monitor make / model | ViewSonic `XG2736-2K` (EDID PNP id `VSC`, product `0x0f41`, EDID serial `XPH243000271`, built week 30/2024, 60×34 cm) |
| Audio device(s) | iFi USB Audio SE UAC1 (USB DAC, card `alsa_card.usb-…iFi_USB_Audio_SE_UAC1…`), onboard Realtek (`alsa_card.pci-0000_00_1f.3`), GP104 HDMI audio (`alsa_card.pci-0000_01_00.1`) (auto) |
| AMP / DAC make / model | iFi uno (USB DAC/amp), USB `0000:6011` |
| Expected default output (`PREFLIGHT_AUDIO_DEVICE`) | `iFi USB Audio SE UAC1 Digital Stereo (IEC958)` |
| AMP / DAC gain (PowerMatch) | **fill in** — switch position (High/Low, or on/off) and the dB it adds on this unit |
| Headphones | Sennheiser HD 300 PRO (recorded 2026-11-24 as `PREFLIGHT_AUDIO_HEADPHONES`) |
| Keyboard | adesso `AKB-670UB`, black, S/N `K2405000392` (label); USB `1c4f:0043`, ODM descriptor reads “SiGma Micro AKB-670UB” (auto) |
| Mouse | Logitech G203 LIGHTSYNC, M/N `MU0054`, P/N `810-006916`, S/N `2521APQFSPT8`, made in Vietnam (label); USB `046d:c092` (auto) |

### How these values were read

```bash
# Monitor make/model/serial: EDID from the active output, decoded inline
xrandr --props | sed -n '/^DP-0 connected/,/^[^ \t]/p'   # 8 lines of EDID hex
#   bytes 8-9 -> PNP id (VSC = ViewSonic), bytes 10-11 -> product code,
#   0xFC descriptor -> model name, 0xFF descriptor -> serial
# edid-decode / parse-edid are not installed; the decode above is plain Python.

# DAC/amp: PipeWire's view of the USB card (no root needed)
pactl list cards | grep -A3 'iFi_USB'
lsusb | grep -i ifi

# Headphones: not detectable — written by hand, then recorded by preflight

# Default output, and the PTB name the session opens (PREFLIGHT_AUDIO_DEVICE)
pactl get-default-sink
pactl list sinks | grep -A3 'Description:'
pw-jack env LD_PRELOAD=$(ls /usr/lib/*/pipewire-0.3/jack/libjack.so | head -1) \
  .venv/bin/python -c 'import psychtoolbox.audio as a; [print(p["DeviceName"]) for p in a.get_devices() if int(p["NrOutputChannels"]) >= 2]'
```

### Open items on this machine

- **PowerMatch / XBass are outside software control.** The experiment pins the
  system sink to `config.SYSTEM_VOLUME_PERCENT` (50%) and keeps PTB playback gain
  at 1.0 to avoid attenuating twice, so any hardware gain the DAC/amp applies is
  invisible to it. PowerMatch (the amp's gain switch, `+4.6` to `+10 dB`
  depending on the iFi model) and any bass boost have to be set to one position
  and recorded here, identically on every lab machine.
- **The audio route is meant to be digital.** The default sink is the iFi uno's
  IEC958/S-PDIF output (`alsa_output.usb-…iFi…-00.iec958-stereo`), and that is the
  route the lab was told to prioritise — not the analog profile. `preflight.sh`
  rejects a `digital|iec958|hdmi` default sink by default, so
  `preflight_config.sh` now sets `PREFLIGHT_ALLOW_DIGITAL_SINK='1'` and the row
  reports an accepted digital route. Do **not** switch the card to
  `output:analog-stereo` on this machine.
  The output itself is pinned locally as `PREFLIGHT_AUDIO_DEVICE`, and the session
  opens exactly the sink preflight validated (`AV_STUDY_AUDIO_DEVICE`) instead of
  ranking device names.
- Do **not** `apt autoremove` on this machine: the orphan list currently offers
  `nvidia-*-535` packages next to the live 580 driver (see ENVIRONMENT.md §1).
- 47 packages have pending upgrades; update deliberately, not the night before a
  session.

### Setup state (2026-11-24)

| Item | State |
| --- | --- |
| `pipewire-jack` | installed (`pw-jack` at `/usr/bin/pw-jack`, `libjack.so` present) — the only required apt package this machine was missing |
| Study runtime | `.venv` built with `uv` → Python 3.10.22, PsychoPy `2026.1.3`, imports `psychopy, psychtoolbox, numpy, PIL` |
| Code revision | `pilot-2026-11.7` (= `main`), no tracked modifications |
| Lab server | `/mnt/camp-lab-server/Anthony` (CIFS, `//psyc-files.ucsc.edu/PSYC-Projects/Camp-Lab`), data at `Anthony/data` reachable and writable; the five earlier sessions are archived in `Anthony/data/old data/` |
| PTB audio route | passes: PipeWire JACK exposes `iFi USB Audio SE UAC1 Digital Stereo (IEC958)` and it is the default sink; accepted because the route is deliberately digital (`PREFLIGHT_ALLOW_DIGITAL_SINK='1'`) |
| Headphone L/R balance | centered (`balance 0.00`) |
| Output volume | currently 100%; `preflight.sh` pins it to `config.SYSTEM_VOLUME_PERCENT` (50%) at launch |
| Session audio device | follows the OS default: preflight exports the validated sink as `AV_STUDY_AUDIO_DEVICE` and the session opens exactly that device; `PREFLIGHT_AUDIO_DEVICE` pins it on this machine |
| Saved-report identity | `preflight.sh` now also writes `os_release`, `monitor_pnp_id`, `monitor_product_code`, `monitor_model`, `monitor_serial` and `usb_devices` to `preflight_report.txt` (and therefore `session_metadata.json`). Deliberately not shown in the checklist window. |

---

## middle-435-purple

Middle computer in room 435, one of the two machines in that room (the other is
`leftmost-435-dark-blue` above). Named by position and colour like its sibling; its
campsite hostname `carpinteria-Aurora-R6` is recorded as the hostname only. A different
physical computer: different DMI UUID, serial, wired NIC MAC and SSD, so sessions from
the two cannot merge.

| Field | Value |
| --- | --- |
| Study machine name | `middle-435-purple` (`PREFLIGHT_MACHINE_NAME`) |
| Room | 435 (`PREFLIGHT_MACHINE_ROOM`) |
| DMI product UUID | `4c4c4544-0057-5210-8031-cac04f4a4b32` (`PREFLIGHT_MACHINE_UUID`) |
| DMI product serial | `JWR1JK2` (`PREFLIGHT_MACHINE_SERIAL`) |
| Hostname | `carpinteria-Aurora-R6` |
| Model | Alienware Aurora R6 (DMI type 3, desktop) |
| Motherboard | Alienware `07HV66` rev `A01` |
| BIOS | `1.0.23`, 2020-06-11 |
| OS / kernel | Ubuntu 24.04.5 LTS, `7.0.0-43-generic` x86_64 |
| CPU | Intel Core i7-7700 @ 3.60 GHz, 4 cores / 8 threads, 1 socket (auto) |
| RAM | 15.4 GB (auto) |
| GPU | NVIDIA GP104 GeForce GTX 1080, driver `580.178.04`, OpenGL renderer `NVIDIA GeForce GTX 1080/PCIe/SSE2` (auto) |
| Storage | Crucial `CT250MX200SSD1` 250 GB (auto) |
| Wired NIC (recorded as `machine_mac`) | `enp4s0` `14:b3:1f:1b:c0:79` (auto) |
| Wireless NIC | `wlp3s0` `f8:34:41:8b:d0:49` (auto, not recorded in sessions) |
| Session type | X11 (auto) |
| Monitor | DP-4, 2560×1440 @ 240 Hz, 600×340 mm; also offers 1920×1080 @ 119.98 Hz, which preflight selects (auto) |
| Monitor make / model | ViewSonic `XG2736-2K` (EDID PNP id `VSC`, product `0x0f41`, EDID serial field `0x01010101` — not programmed; built week 2/2025, 60×34 cm) |
| Audio device(s) | iFi USB Audio SE UAC1 (USB DAC, card `alsa_card.usb-…iFi_USB_Audio_SE_UAC1…`), onboard Realtek (`alsa_card.pci-0000_00_1f.3`), GP104 HDMI audio (`alsa_card.pci-0000_01_00.1`) (auto) |
| AMP / DAC make / model | iFi USB DAC/amp, USB `0000:6011` with device description `iFi USB Audio SE UAC1` — identical USB identity to the machine above (auto; physical unit not re-read) |
| Expected default output (`PREFLIGHT_AUDIO_DEVICE`) | `iFi USB Audio SE UAC1 Digital Stereo (IEC958)` — pinned in `preflight_local.sh`, so preflight fails if any other sink becomes the default |
| AMP / DAC gain (PowerMatch) | **fill in** — switch position and XBass state not yet read on this machine |
| Headphones | Sennheiser HD 300 PRO (`PREFLIGHT_AUDIO_HEADPHONES`) |
| Keyboard | SiGma Micro `AKB-670UB`, USB `1c4f:0043` — same model as the machine above (auto) |
| Mouse | Logitech G102/G203 LIGHTSYNC, USB `046d:c092` — same model as the machine above (auto) |

Keyboard and mouse are identified here by their USB vendor:product IDs, not by the
serial numbers printed on their labels. The label serials recorded for
`leftmost-435-dark-blue` belong to that machine's individual units and must not be copied
to this row; this machine's own units have not been read off their labels yet.

### Setup state (2026-11-24)

| Item | State |
| --- | --- |
| `pipewire-jack` | installed (`pw-jack` at `/usr/bin/pw-jack`, `libjack.so` present) |
| Study runtime | `.venv` → Python 3.10.22, PsychoPy `2026.1.3`, numpy 2.2.6; imports `psychopy, psychtoolbox, numpy, PIL` |
| Code revision | `0fca303` (`main`), no tracked modifications |
| Lab server | `/mnt/camp-lab-server/Anthony` (CIFS, `//psyc-files.ucsc.edu/PSYC-Projects/Camp-Lab`, mounted by the machine's own mount configuration); `Anthony/data` reachable and writable |
| PTB audio route | default sink is the iFi's IEC958 output; accepted because the route is deliberately digital (`PREFLIGHT_ALLOW_DIGITAL_SINK='1'`) |
| Headphone L/R balance | centered (`balance 0.00`) |
| Output volume | currently 100%; `preflight.sh` pins it to `config.SYSTEM_VOLUME_PERCENT` (50%) at launch |
| Session audio device | pinned to `iFi USB Audio SE UAC1 Digital Stereo (IEC958)` via `PREFLIGHT_AUDIO_DEVICE`; preflight exports the validated sink as `AV_STUDY_AUDIO_DEVICE` |
| APT | 103 packages upgradable — update deliberately, not the night before a session |
| Not run | `./preflight.sh` has not been run on this machine, so the GUI checklist is unverified |

### Open items on this machine

- **PowerMatch / XBass are outside software control and currently unknown here.**
  Read the switch once, set it to the same position as the machine above, and replace
  **fill in** in the table. The system sink is pinned to 50% and PTB gain stays at 1.0,
  so any hardware gain the DAC applies is invisible to preflight and to the session
  metadata.
- **Kernel differs from the machine above** (`7.0.0-43-generic` vs `6.17.0-14-generic`),
  so `tools/device_report.py` will list a `kernel` difference between the two devices.
  Harmless for timing, but it means a timing question cannot be settled by "same kernel".
- **Name confirmed by the operator as the middle computer, purple.** `PREFLIGHT_MACHINE_NAME`
  is `middle-435-purple`; the camp-site hostname stays the hostname, matching the
  convention on the machine above.

---

## rightmost-435-white

Rightmost computer in room 435, named for its white mouse. It is also the
**older** of the three: a Dell OptiPlex 7040 SFF rather than the Alienware Aurora
R6 towers. Different DMI UUID, serial, wired NIC MAC, disk and monitor
serial from the two machines above, so sessions cannot merge.

| Field | Value |
| --- | --- |
| Study machine name | `rightmost-435-white` (`PREFLIGHT_MACHINE_NAME`) |
| Room | 435 (`PREFLIGHT_MACHINE_ROOM`) |
| DMI product UUID | `4c4c4544-0059-5910-8030-b4c04f4a4232` (`PREFLIGHT_MACHINE_UUID`) |
| DMI product serial | `4YY0JB2` (`PREFLIGHT_MACHINE_SERIAL`) |
| Hostname | `dogwood-OptiPlex-7040` |
| Model | Dell OptiPlex 7040 (DMI type 3, small form factor desktop) |
| Motherboard | Dell `0HD5W2` rev `A01` |
| BIOS | `1.24.0`, 2022-07-14 |
| OS / kernel | Ubuntu 24.04.4 LTS, `7.0.0-42-generic` x86_64 |
| CPU | Intel Core i5-6500 @ 3.20 GHz, 4 cores / 4 threads, 1 socket, **no hyper-threading** (auto) |
| RAM | 15 GB (auto) |
| GPU | Intel HD Graphics 530 only (Skylake GT2), Mesa `25.2.8-0ubuntu0.24.04.2`, OpenGL 4.6; **no discrete NVIDIA card** — `nvidia-smi` cannot reach a driver, which is expected here (auto) |
| Storage | TOSHIBA `THNSNK256GCS8` 256 GB SATA SSD (238.5 GiB), plus TSSTcorp `DVD+/-RW SU-208GB` (auto) |
| Wired NIC (recorded as `machine_mac`) | `enp0s31f6` `18:66:da:18:32:98` (`e1000e`) (auto) |
| Wireless NIC | none present (auto) |
| Session type | X11 (auto) |
| Monitor | DP-2, 1920×1080 @ 120.00 Hz active, 597×336 mm; the panel also offers 119.88/119.98/60 Hz (auto) |
| Monitor make / model | ViewSonic `XG2736-2K` (EDID PNP id `VSC`, product `0x0f41`, EDID serial `XPH252400389`, built week 24/2025, 60×34 cm) — same model as the two machines above, different unit |
| Audio device(s) | onboard Realtek only (`alsa_card.pci-0000_00_1f.3`); no USB DAC and no GP104 HDMI audio, unlike the two Alienware machines (auto) |
| AMP / DAC make / model | none — headphones plug into the onboard analog jack (active port `analog-output-headphones`) |
| Expected default output (`PREFLIGHT_AUDIO_DEVICE`) | **left empty on purpose**: the session follows the OS default, which is `Built-in Audio Analog Stereo`. This machine has no DAC to pin |
| AMP / DAC gain (PowerMatch) | not applicable — no DAC/amp in the chain |
| Headphones | Sennheiser HD 300 PRO (`PREFLIGHT_AUDIO_HEADPHONES`) |
| Keyboard | SiGma Micro `AKB-670UB`, USB `1c4f:0043` — same model as the two machines above (auto) |
| Mouse | Logitech G102/G203 LIGHTSYNC, USB `046d:c092`, white unit (auto) |

### Setup state (2026-11-24)

| Item | State |
| --- | --- |
| `pipewire-jack` | installed (`pw-jack` at `/usr/bin/pw-jack`, `libjack.so` present) |
| Study runtime | **no `.venv` on this machine.** Preflight falls back to the PsychoPy app runtime at `~/.config/psychopy4/.python/2026.1.3/bin/python3`, which is the documented fallback (ENVIRONMENT.md §3); the pinned `requirements-lock.txt` environment has not been built here |
| Code revision | `4a85241` (`main`), no tracked modifications; untracked local files only |
| Lab server | **not mounted yet** — `/mnt/camp-lab-server` does not exist here and this machine is not expected to reach the share for now. Preflight warns and asks you to accept local-only storage; sessions stay in `data/participant_NN/` |
| PTB audio route | analog default sink `alsa_output.pci-0000_00_1f.3.analog-stereo`, accepted (the tracked `PREFLIGHT_ALLOW_DIGITAL_SINK='1'` is irrelevant here) |
| Headphone L/R balance | centered (`balance 0.00`) |
| Output volume | currently 50%, which is `config.SYSTEM_VOLUME_PERCENT`; `preflight.sh` re-pins it at every launch |
| APT | 2 packages upgradable (`matlab-psychtoolbox-3` 3.0.19.14 → 3.0.22.3); update deliberately, not the night before a session |
| Not run | `./preflight.sh` has not been run on this machine, so the GUI checklist is unverified |

### Open items on this machine

- **No pinned runtime.** Building `.venv` with `uv venv --python 3.10 .venv` and
  `requirements-lock.txt` would make its timing/audio stack identical to the other
  two machines instead of relying on the PsychoPy app runtime.
- **No lab-server mount.** Every session from this machine is local-only until a
  mount is added here; add `PREFLIGHT_SERVER_ROOT` to `preflight_local.sh` (not to
  the tracked config) when that changes.
- **Intel-only graphics** where the other two have a GTX 1080. Not a timing
  guarantee either way — `preflight.sh`'s refresh row is the check that matters.
- **A slower CPU than its siblings** (i5-6500, 4 threads vs i7-7700, 8 threads).
  Worth watching the first session's dropped-frame counts before trusting its
  timing against the other two.

---

## left-blue-405

A fourth Alienware Aurora R6, a different unit from the two towers above
(different DMI UUID, serial, wired NIC MAC and SSD), and closer to
`rightmost-435-white` in one respect: it carries only 8 GB of RAM. Peripheral
differences matter more than the chassis: a TOSHIBA M.2 SSD instead of the
SanDisk/Crucial pair above, and an **iFi ZEN Air DAC 2** in place of the older
iFi USB Audio SE UAC1, so its audio device name and route profile are not
interchangeable with the machines in 435.

| Field | Value |
| --- | --- |
| Study machine name | `left-blue-405` (`PREFLIGHT_MACHINE_NAME`) |
| Room | 405 (`PREFLIGHT_MACHINE_ROOM`, one-time operator setup) |
| DMI product UUID | `4c4c4544-0057-5110-805a-cac04f574b32` (`PREFLIGHT_MACHINE_UUID`) |
| DMI product serial | `JWQZWK2` (`PREFLIGHT_MACHINE_SERIAL`) |
| Hostname | `point-magu-Aurora-R6` |
| Model | Alienware Aurora R6 (DMI type 3, desktop) |
| Motherboard | Alienware `07HV66` rev `A01` |
| BIOS | `1.0.23`, 2020-06-11 |
| OS / kernel | Ubuntu 24.04.5 LTS, `7.0.0-43-generic` x86_64 |
| CPU | Intel Core i7-7700 @ 3.60 GHz, 4 cores / 8 threads, 1 socket (auto) |
| RAM | 7.5 GB (auto) — about half of the two 435 Aurora towers |
| GPU | NVIDIA GP104 GeForce GTX 1080, driver `580.178.04` (auto) |
| Storage | TOSHIBA `KSG60ZMV256G` M.2 2280 256 GB (238.5 GiB), single disk (auto) |
| Wired NIC (recorded as `machine_mac`) | `enp4s0` `14:b3:1f:1b:c6:ee` (auto) |
| Wireless NIC | `wlp3s0` `f8:34:41:8b:ce:af` (auto, not recorded in sessions) |
| Session type | X11 (auto) |
| Monitor | DP-4, 2560×1440 @ 240.00 Hz active, 600×340 mm; the panel also offers 1920×1080 @ 119.98 Hz, which preflight selects (auto) |
| Monitor make / model | ViewSonic `XG2736-2K` (EDID PNP id `VSC`, product `0x0f41`, EDID serial `XPH252400377`, built week 24/2025, 60×34 cm) — same model as the three machines above, different unit |
| Audio device(s) | iFi ZEN Air DAC 2 (USB `2fc6:f082`, card `alsa_card.usb-iFi_ZEN_Air_DAC_2_iFi_USB_Audio_SE-00`, active profile `output:analog-stereo`), onboard Realtek ALC3861 (`alsa_card.pci-0000_00_1f.3`), GP104 HDMI audio (`alsa_card.pci-0000_01_00.1`) (auto) |
| AMP / DAC make / model | iFi ZEN Air DAC 2 (USB DAC/amp), USB `2fc6:f082` — **not** the UAC1 unit on the two 435 towers |
| Expected default output (`PREFLIGHT_AUDIO_DEVICE`) | `ZEN Air DAC 2 Analog Stereo` — pinned in `preflight_local.sh`, so preflight fails if another sink becomes the default |
| AMP / DAC gain (PowerMatch) | **fill in** — switch position and XBass state not yet read on this unit |
| Headphones | Sennheiser HD 300 PRO (`PREFLIGHT_AUDIO_HEADPHONES`) |
| Keyboard | SiGma Micro `AKB-670UB`, USB `1c4f:0043` — same model as the other machines (auto) |
| Mouse | Logitech G102/G203 LIGHTSYNC, USB `046d:c092` (auto) |

Keyboard and mouse are identified by their USB vendor:product IDs; the label
serials printed on this machine's individual units have not been read.

### Setup state (2026-11-24)

| Item | State |
| --- | --- |
| `pipewire-jack` | installed (`pw-jack` at `/usr/bin/pw-jack`, `libjack.so` present) |
| Study runtime | `.venv` → Python 3.10.22, PsychoPy `2026.1.3`, numpy 2.2.6; imports `psychopy, psychtoolbox, numpy, PIL` |
| Code revision | `b3497a8` (`main`), no tracked modifications |
| Lab server | `/mnt/camp-lab-server/Anthony` (CIFS, `//psyc-files.ucsc.edu/PSYC-Projects/Camp-Lab`); `Anthony/data` reachable |
| PTB audio route | default sink is the ZEN Air DAC 2's **analog** output, exposed through PipeWire JACK as `ZEN Air DAC 2 Analog Stereo`; the route check passes on the analog path |
| Headphone L/R balance | centered (`balance 0.00`) |
| Output volume | currently 100%; `preflight.sh` pins it to `config.SYSTEM_VOLUME_PERCENT` (50%) at launch |
| Session audio device | pinned to `ZEN Air DAC 2 Analog Stereo` via `PREFLIGHT_AUDIO_DEVICE` |
| APT | 87 packages upgradable — update deliberately, not the night before a session |
| Not run | `./preflight.sh` has not been run since this section was written, so the GUI checklist is unverified |

### Open items on this machine

- **The DAC differs from the two 435 Aurora towers.** This one's ZEN Air DAC 2
  runs its **analog** profile (`output:analog-stereo`) and that analog sink is the
  machine's pinned route, so the tracked `PREFLIGHT_ALLOW_DIGITAL_SINK='1'`
  (which the UAC1 machines need for their IEC958 route) is irrelevant here and
  merely harmless. If this card is ever switched to a digital/IEC958 profile that
  flag would let a digital default through, so the pinned
  `PREFLIGHT_AUDIO_DEVICE` is what actually keeps the route honest — do not clear
  it.
- **PowerMatch / XBass are outside software control.** The system sink is pinned
  to 50% and PTB gain stays at 1.0, so any hardware gain the ZEN Air DAC 2 applies
  is invisible to preflight and to session metadata. Read the switch once, set it
  to the same position as the machines above, and replace **fill in** in the table.
- **Half the RAM of the 435 towers (7.5 GB).** Watch the first session's
  dropped-frame counts and check `free -h` before launch; it is the only machine
  here where a browser left open could matter.
- **Different kernel** (`7.0.0-43-generic`) from the `6.17.0-14-generic` machine,
  so `tools/device_report.py` will list a `kernel` difference. Harmless for
  timing, but a timing question cannot be settled by "same kernel".
- **A second room.** The operator confirmed room **405**, so this machine is not
  a fourth computer in 435 and its sessions carry `machine_room=405`. The name was
  kept as `left-blue-405` rather than reworded to the 435 position/colour
  convention, so existing local records still match; room is stored separately and
  is never parsed out of the name (ENVIRONMENT.md §3).

---

## right-purple-405

The machine in room 405. Same Alienware Aurora R6 batch as the two towers in
room 435 — a third unit, with its own DMI UUID, serial, wired NIC MAC and disk,
so sessions from it cannot merge with theirs. Its camp-site hostname
`sycamore-canyon-R6` is recorded as the hostname only.

| Field | Value |
| --- | --- |
| Study machine name | `right-purple-405` (`PREFLIGHT_MACHINE_NAME`) |
| Room | 405 (`PREFLIGHT_MACHINE_ROOM`) |
| DMI product UUID | `4c4c4544-0057-5210-8032-cac04f4a4b32` (`PREFLIGHT_MACHINE_UUID`) |
| DMI product serial | `JWR2JK2` (`PREFLIGHT_MACHINE_SERIAL`) |
| Hostname | `sycamore-canyon-R6` |
| Model | Alienware Aurora R6 (DMI type 3, desktop) |
| Motherboard | Alienware `07HV66` rev `A01` |
| BIOS | `1.0.23`, 2020-06-11 |
| OS / kernel | Ubuntu 24.04.5 LTS, `7.0.0-43-generic` x86_64 |
| CPU | Intel Core i7-7700 @ 3.60 GHz, 4 cores / 8 threads, 1 socket (auto) |
| RAM | 15.4 GB (auto) |
| GPU | NVIDIA GP104 GeForce GTX 1080, driver `580.178.04`, OpenGL renderer `NVIDIA GeForce GTX 1080/PCIe/SSE2`; the i7-7700's Intel HD Graphics 630 is present but not driving the display (auto) |
| Storage | SK hynix `SC311 SATA 256GB` (238.5 GiB), SATA SSD (auto) |
| Wired NIC (recorded as `machine_mac`) | `enp4s0` `14:b3:1f:1b:c0:68` (auto) |
| Wireless NIC | `wlp3s0` `f8:34:41:8b:cf:8b`, plus an Intel `8087:0a2a` Bluetooth interface (auto, not recorded in sessions) |
| Session type | X11 (auto) |
| Monitor | DP-2, primary, 2560×1440 @ 240.00 Hz active, 600×340 mm; also offers 1920×1080 @ 119.98 Hz, which preflight selects (auto) |
| Monitor make / model | ViewSonic `XG2736-2K` (EDID PNP id `VSC`, product `0x0f41`, EDID serial `XPH252400502`, built week 24/2025, 60×34 cm) — same model as the three machines above, different unit |
| Audio device(s) | iFi `ZEN Air DAC 2` (USB DAC, card `alsa_card.usb-iFi_ZEN_Air_DAC_2_iFi_USB_Audio_SE-00`), onboard Realtek ALC3861 (`alsa_card.pci-0000_00_1f.3`), GP104 HDMI audio (`alsa_card.pci-0000_01_00.1`) (auto) |
| AMP / DAC make / model | iFi ZEN Air DAC 2, USB `2fc6:f082` (Comtrue) — **a different DAC from the room-435 machines**, which use an iFi USB Audio SE UAC1 (auto) |
| Expected default output (`PREFLIGHT_AUDIO_DEVICE`) | `ZEN Air DAC 2 Analog Stereo` — pinned in `preflight_local.sh`; PTB opens the same name through PipeWire JACK, so the exact-match row passes today |
| AMP / DAC gain (PowerMatch) | **fill in** — switch position and XBass state not yet recorded on this unit |
| Headphones | Sennheiser HD 300 PRO (`PREFLIGHT_AUDIO_HEADPHONES`) — same model as the three machines above |
| Keyboard | SiGma Micro `AKB-670UB`, USB `1c4f:0043` — same model as the three machines above (auto) |
| Mouse | Logitech G102/G203 LIGHTSYNC, USB `046d:c092` — same model as the three machines above (auto) |
| Camera | Point Grey `Chameleon3 CM3-U3-13Y3M`, USB `1e10:3300` — **not present on any room-435 machine**; unused by the study, which has no camera step (auto) |

### Setup state (2026-11-24)

| Item | State |
| --- | --- |
| `pipewire-jack` | installed (`pw-jack` at `/usr/bin/pw-jack`, `libjack.so` present) |
| Study runtime | `.venv` → Python 3.10.18, PsychoPy `2026.1.3`, psychtoolbox `3.0.19.14`, numpy 2.2.6, Pillow 11.3.0; imports `psychopy, psychtoolbox, numpy, PIL` |
| Code revision | `b3497a8` (`main`), no tracked modifications before this section was added |
| Lab server | `/mnt/camp-lab-server/Anthony` (CIFS, `//psyc-files.ucsc.edu/PSYC-Projects/Camp-Lab`) mounted and writable; `Anthony/data` present |
| PTB audio route | default sink is the ZEN Air DAC 2's analog output, accepted (analog route, so the tracked `PREFLIGHT_ALLOW_DIGITAL_SINK='1'` is irrelevant here) |
| Headphone L/R balance | centered (`balance 0.00`) |
| Output volume | currently 44%; `preflight.sh` re-pins it to `config.SYSTEM_VOLUME_PERCENT` (50%) at every launch |
| APT | 73 packages upgradable — update deliberately, not the night before a session |
| Not run | `./preflight.sh` has not been run on this machine, so the GUI checklist is unverified |

### Open items on this machine

- **PowerMatch is unrecorded.** It is a physical fact the machine cannot read:
  read the DAC's PowerMatch/XBass switch once, set it to the same position as the
  room-435 machines, and replace the **fill in** row.
- **This is a different DAC and an analog route** from the room-435 machines,
  which run an iFi USB Audio SE UAC1 over IEC958. Level matching across rooms is
  therefore not guaranteed by `PREFLIGHT_ALLOW_DIGITAL_SINK` or by the same
  hardware; the 50% sink pin plus PTB gain 1.0 is what keeps runs comparable.
- **Runtime differs slightly from the room-435 machines:** Python 3.10.18 here vs
  3.10.22 there, and psychtoolbox `3.0.19.14` is the same version the
  `rightmost-435-white` machine has pending in apt. Rebuilding from
  `requirements-lock.txt` would remove the Python patch-level difference.
- **A Chameleon3 camera is attached and unused.** It does not affect timing, but
  it is the one piece of hardware no other lab computer has; leave it unplugged
  during sessions if it draws enough USB bandwidth to disturb the DAC.
