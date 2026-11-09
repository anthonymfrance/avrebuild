#!/usr/bin/env bash
# Edit these simple values when the lab machine or server location changes.

# Xorg is recommended; the GUI asks whether to continue if another session is active.

# The legacy study runner's GVFS SMB mount and data destination.
PREFLIGHT_SERVER_MOUNT_GLOB='smb-share:server=psyc-files.ucsc.edu,share=jamal*'
PREFLIGHT_SERVER_DATA_PATH='Experiments/Anthony/data'

# Browser steps before the experiment starts. Preflight opens the consent form,
# then the participant log, and waits for the RA to confirm each one before
# showing the reminder to close the browser. Set either to '' to skip that step
# (the report then records it as not_configured).
PREFLIGHT_CONSENT_URL='https://ucsantacruz.co1.qualtrics.com/jfe/form/SV_0Mw9ifZPHyAhqXY'
PREFLIGHT_PARTICIPANT_LOG_URL='https://docs.google.com/spreadsheets/d/1KQaIyga6T54EGzbkSicpzeNjQrhpWTZD_gHhSKwB68w/edit?gid=1574254185#gid=1574254185'
