#!/bin/sh
# Experiment 1 in the power state of the moment: the display links, then wsd's cadence at 20, 32 and 60 frames a second at
# full size and at 58 percent, then 32 with a display-link range asked for. About three minutes of full-screen test
# pictures; leave the Mac alone, unlocked, meanwhile. Nothing of it needs administrator rights, and it changes no setting.
# Usage: run-low-power-session.sh <out-folder>
set -eu
W=$(cd "$(dirname "$0")" && pwd)
OUT=${1:?out folder}
if ioreg -n Root -d1 -a | grep -A1 IOConsoleLocked | grep -q '<true/>'; then echo "the screen is locked: nothing run" >&2; exit 3; fi
mkdir -p "$OUT" "$W/bin"
[ -x "$W/../../wsd/bin/wsd" ] || "$W/../../wsd/build.sh" >/dev/null 2>&1
[ -x "$W/bin/wsd_client" ] || "$W/build-wsd-client.sh" >/dev/null
[ -x "$W/bin/display_link_probe" ] || {
  clang -arch arm64 -fobjc-arc -O2 -Wall -Wno-deprecated-declarations -o "$W/bin/display_link_probe" "$W/display_link_probe.m" \
    -framework Cocoa -framework Metal -framework QuartzCore -framework CoreVideo
}
pmset -g custom > "$OUT/pmset.txt"; pmset -g batt >> "$OUT/pmset.txt"
caffeinate -dimsu "$W/bin/display_link_probe" 2>&1 | tee "$OUT/links.txt"
for P in 100 58; do "$W/run-wsd-cadence.sh" "$OUT" 20,32,60 15 $P; done
"$W/run-wsd-cadence.sh" "$OUT" 32 15 58 60
for d in "$OUT"/*-rate*; do echo "### $(basename "$d")"; python3 -I "$W/../../tools/timeline/otl.py" "$d" --cadence | tail -n +3; done | tee "$OUT/summary.txt"
