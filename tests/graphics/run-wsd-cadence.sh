#!/bin/sh
# Display cadence of wsd with the owned client: numbered moving frames, full screen, at a rate, as a game sends them.
# Runs wsd as an app bundle of the games category, as launch.sh does (Game Mode, a full-screen app of its own).
# Each run covers the screen for its seconds: at most 60.
#
# Usage: run-wsd-cadence.sh <out-folder> <rate>[,<rate>...] [seconds=12] [render-percent=100] [frame-rate=0]
#   WSD=<wsd binary>            the one to run (default: wsd/bin/wsd of this checkout)
#   OBELISK_TIMELINE_OFF=1      without the timeline
# Refuses to run while the screen is locked. Records the power state beside the results.
set -eu
W=$(cd "$(dirname "$0")" && pwd)
EXP=$(cd "$W/../.." && pwd)
OUT=${1:?out folder}; RATES=${2:?rates}; SECONDS_EACH=${3:-12}; PERCENT=${4:-100}; FR=${5:-0}
WSD=${WSD:-$EXP/wsd/bin/wsd}
CLIENT="$W/bin/wsd_client"
if ioreg -n Root -d1 -a | grep -A1 IOConsoleLocked | grep -q '<true/>'; then echo "the screen is locked: nothing run" >&2; exit 3; fi
mkdir -p "$OUT"
APP="$OUT/wsd cadence.app"
rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS"; cp "$WSD" "$APP/Contents/MacOS/wsd"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleExecutable</key><string>wsd</string>
  <key>CFBundleIdentifier</key><string>cc.orbiters.wsd-cadence</string>
  <key>CFBundleName</key><string>wsd cadence</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.games</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
for RATE in $(printf %s "$RATES" | tr , ' '); do
  RUN="$OUT/$(date +%H%M%S)-rate$RATE-percent$PERCENT-fr$FR"
  mkdir -p "$RUN"
  {
    date "+%Y-%m-%d %H:%M:%S"
    pmset -g batt | head -1
    echo "low power mode (the setting in use): $(pmset -g | awk '/lowpowermode/{print $2}')"
    pmset -g therm
  "$W/others-busy.sh"
    echo "wsd: $(shasum -a 256 "$WSD" | cut -c1-16) percent $PERCENT rate $RATE frame_rate $FR"
  } > "$RUN/conditions.txt" 2>&1
  D=$(mktemp -d "${TMPDIR:-/tmp}/wsdc.XXXXXX")
  if [ -z "${OBELISK_TIMELINE_OFF-}" ]; then OBELISK_TIMELINE="$RUN"; export OBELISK_TIMELINE; fi
  caffeinate -dimsu "$APP/Contents/MacOS/wsd" --dir "$D" --exit-on-disconnect --render-percent "$PERCENT" > "$RUN/wsd.log" 2>&1 &
  SPID=$!
  i=0; while [ ! -S "$D/wsd.sock" ] && [ $i -lt 100 ]; do sleep 0.1; i=$((i+1)); done
  perl -e 'alarm shift; exec @ARGV' 80 "$CLIENT" "$D/wsd.sock" --cadence "$RATE" "$SECONDS_EACH" --frame-rate "$FR" > "$RUN/client.txt" 2>&1 || true
  i=0; while kill -0 "$SPID" 2>/dev/null && [ $i -lt 30 ]; do sleep 0.1; i=$((i+1)); done
  kill "$SPID" 2>/dev/null || true; wait "$SPID" 2>/dev/null || true
  rm -rf "$D"
  ioreg -n Root -d1 -a | grep -A1 IOConsoleLocked | grep -q '<true/>' && echo "the screen was locked at the end: not a result" >> "$RUN/conditions.txt"
  grep -h CADENCE "$RUN/client.txt" || cat "$RUN/client.txt"
done
