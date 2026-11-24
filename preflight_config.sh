#!/usr/bin/env bash
# Edit these simple values when the lab machine or server location changes.

# Xorg is recommended; the GUI asks whether to continue if another session is active.

# Lab data destination. PREFLIGHT_SERVER_ROOT is the absolute mount point of the
# share and is used first; simply testing that path is what triggers the system's
# automount. PREFLIGHT_SERVER_DATA_PATH is relative to it, so sessions land in
# <root>/<data path>/participant_NN.
#
# The Camp-Lab share is mounted by the machine's own mount configuration
# (//psyc-files.ucsc.edu/PSYC-Projects/Camp-Lab on /mnt/camp-lab-server). Its
# credentials live there and must never be written into this file, the repo, or a
# shell command line.
PREFLIGHT_SERVER_ROOT='/mnt/camp-lab-server/Anthony'
PREFLIGHT_SERVER_DATA_PATH='data'

# Legacy GVFS fallback, used only when PREFLIGHT_SERVER_ROOT is empty or missing
# (a machine that still mounts the SMB share through Files).
# PREFLIGHT_SERVER_URI is only used to attempt the mount when it is not already
# mounted. Credentials are supplied by the login keyring and must never be
# written into this file, the repo, or a shell command line.
PREFLIGHT_SERVER_URI='smb://psyc-files.ucsc.edu/jamal'
PREFLIGHT_SERVER_MOUNT_GLOB='smb-share:server=psyc-files.ucsc.edu,share=jamal*'

# Headphones plugged into the output above. The machine can only see the codec or
# DAC, never the headphones, so this is the one part of the audio chain that has
# to be written down per computer. It is recorded in every session's metadata and
# reported by tools/device_report.py; leave it empty and preflight warns.
# Set these two per computer in an untracked preflight_local.sh (see
# ENVIRONMENT.md), so a clone does not inherit another machine's name.
PREFLIGHT_MACHINE_NAME=''
PREFLIGHT_AUDIO_HEADPHONES=''

# Audio route policy. A digital default sink (S/PDIF/IEC958, HDMI) is rejected by
# default, because most machines should play from the wired headphone output. This
# lab's route IS the DAC's S/PDIF output, as instructed, so it is accepted here and
# reported as an accepted digital route instead of a red row. Leave it at 0 on a
# machine where the route is meant to be analog.
PREFLIGHT_ALLOW_DIGITAL_SINK='1'

# Browser steps before the experiment starts. Preflight opens the consent form,
# then the participant log, and waits for the RA to confirm each one before
# showing the reminder to close the browser. Set either to '' to skip that step
# (the report then records it as not_configured).
PREFLIGHT_CONSENT_URL='https://ucsantacruz.co1.qualtrics.com/jfe/form/SV_0Mw9ifZPHyAhqXY'
PREFLIGHT_PARTICIPANT_LOG_URL='https://docs.google.com/spreadsheets/d/1KQaIyga6T54EGzbkSicpzeNjQrhpWTZD_gHhSKwB68w/edit?gid=1574254185#gid=1574254185'
