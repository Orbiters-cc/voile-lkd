#!/bin/bash
# The pass-cost client through the whole chain (the engine's own Wine, Neptune's driver, the render server, DXMT, wsd),
# in a TEMPORARY runtime and prefix: never the owner's library.
#
# Usage: run-pass-costs.sh <runtime> <home> <launch.sh> <out-folder> <render-percent> <seconds per mode> [mode ...]
#   <runtime>   a copy of a Voile release's linux folder; <home> one whose prefix was made with it (wineboot)
#   <launch.sh> Obelisk's crates/game-runtime/src/wine/linux_engine/launch.sh, branch perf-timeline
#   TIMELINE=1  with the host timeline; INTERVAL=n the sync interval (0)
# Refuses to run while the screen is locked.
set -u
W=$(cd "$(dirname "$0")" && pwd)
RUNTIME=$1 HOMEDIR=$2 LAUNCH=$3 OUT=$4 PERCENT=$5 SECONDS_EACH=$6
shift 6
locked() { ioreg -n Root -d1 -a | grep -A1 IOConsoleLocked | grep -q '<true/>'; }
locked && { echo "the screen is locked: nothing run" >&2; exit 3; }
mkdir -p "$OUT"
INSTALL=$(mktemp -d "${TMPDIR:-/tmp}/passcosts.XXXXXX")
cp "$W/bin/pass_costs.exe" "$INSTALL/"
{
  date "+%Y-%m-%d %H:%M:%S"
  pmset -g batt | head -1
  echo "low power mode (the setting in use): $(pmset -g | awk '/lowpowermode/{print $2}')"
  pmset -g therm
  "$W/others-busy.sh"
  echo "percent $PERCENT interval ${INTERVAL-0} timeline ${TIMELINE-0} modes: $*"
  for f in engine/wsd graphics/libexec/virgl_render_server graphics/bin/virgl_test_server graphics/lib/libvirglrenderer.1.dylib \
           graphics/dxmt-native.framework/Versions/A/dxmt-native; do
    echo "$f $(shasum -a 256 "$RUNTIME/$f" | cut -c1-16)"
  done
} > "$OUT/conditions.txt" 2>&1
[ -n "${TIMELINE-}" ] && export OBELISK_TIMELINE="$OUT" || unset OBELISK_TIMELINE
export OBELISK_APP_NAME="Pass costs"
caffeinate -dimsu "$RUNTIME/engine/run-with-timeout.sh" 170 /bin/bash "$LAUNCH" "$RUNTIME" "$HOMEDIR" "$INSTALL" /opt/game \
  --render-percent "$PERCENT" --env HOME=/home/user --env USER=user --env LOGNAME=user --env PATH=/opt/wine/bin:/usr/bin:/bin \
  --env LANG=en_US.UTF-8 --env LC_ALL=en_US.UTF-8 --env WINEPREFIX=/home/user/prefix --env WINEARCH=win64 \
  --env WINEDEBUG=-all --env "WINEDLLOVERRIDES=mscoree,mshtml=;winemenubuilder.exe=d;d3d11,dxgi,d3d12=n" \
  --env VTEST_SOCKET_NAME=/run/obelisk/vtest.sock --env NPT_DEBUG=force_vtest \
  -- /opt/game/pass_costs.exe "$SECONDS_EACH" "${INTERVAL-0}" "$@" > "$OUT/run.log" 2>&1
echo "rc=$?" >> "$OUT/run.log"
rm -rf "$INSTALL"
locked && echo "the screen was locked at the end: not a result" >> "$OUT/conditions.txt"
grep -a -E "^(PASSCOSTS|MODE|FAILED|DONE)" "$OUT/run.log" || tail -20 "$OUT/run.log"
