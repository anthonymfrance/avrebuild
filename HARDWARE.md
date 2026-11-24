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
| Room | 435 |
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
