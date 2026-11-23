#!/usr/bin/env bash
# Put an "AV Study Preflight" launcher in the app grid and on the desktop.
#
#     ./tools/install_shortcut.sh
#
# Re-run it after moving the checkout: the launcher records this directory.
set -euo pipefail

study_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
apps_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
# xdg-user-dir knows where the desktop actually is, including non-English names.
desktop_dir="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
[[ -n "$desktop_dir" ]] || desktop_dir="$HOME/Desktop"

mkdir -p "$apps_dir" "$desktop_dir"
entry="$apps_dir/av-preflight.desktop"
cat > "$entry" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=AV Study Preflight
Comment=Set the study display mode, check audio and the lab server, then run a session
Exec=bash -c 'cd "$study_dir" && exec ./preflight.sh'
Path=$study_dir
Terminal=false
Icon=applications-science
Categories=Science;Education;
StartupNotify=true
EOF

chmod 755 "$entry"
cp -f "$entry" "$desktop_dir/av-preflight.desktop"
chmod 755 "$desktop_dir/av-preflight.desktop"
# GNOME will not launch a desktop file it has not been told to trust, which looks
# exactly like a broken shortcut.
gio set "$desktop_dir/av-preflight.desktop" metadata::trusted true 2>/dev/null || true
update-desktop-database "$apps_dir" >/dev/null 2>&1 || true

echo "App grid:  $entry"
echo "Desktop:   $desktop_dir/av-preflight.desktop"
echo "Launches:  bash -c 'cd \"$study_dir\" && exec ./preflight.sh'"
