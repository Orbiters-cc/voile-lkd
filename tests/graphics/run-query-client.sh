#!/bin/bash
# The query client (query_client.cpp: no window) through the whole chain (the engine's own Wine, Neptune's driver, the render server,
# DXMT), in a TEMPORARY runtime and prefix: never the owner's library.
#
# Usage: run-query-client.sh <runtime> <home> <launch.sh> <out-folder> <limit, seconds> cases|soak|pending [...]   (as run-pass-costs.sh)
#   TIMELINE=1  with the host timeline, read by case; OBELISK_DXMT_QUERY_RESCUE=once: with the switch
set -u
W=$(cd "$(dirname "$0")" && pwd)
RUNTIME=$1 HOMEDIR=$2 LAUNCH=$3 OUT=$4 LIMIT=$5
shift 5
mkdir -p "$OUT"
INSTALL=$(mktemp -d "${TMPDIR:-/tmp}/queryclient.XXXXXX")
cp "$W/bin/query_client.exe" "$INSTALL/"
{
  date "+%Y-%m-%d %H:%M:%S"
  pmset -g therm
  "$W/others-busy.sh"
  echo "OBELISK_DXMT_QUERY_RESCUE=${OBELISK_DXMT_QUERY_RESCUE-} timeline ${TIMELINE-0}: $*"
  for f in engine/wsd graphics/libexec/virgl_render_server graphics/lib/libvirglrenderer.1.dylib graphics/dxmt-native.framework/Versions/A/dxmt-native; do
    echo "$f $(shasum -a 256 "$RUNTIME/$f" | cut -c1-16)"
  done
} > "$OUT/conditions.txt" 2>&1
[ -n "${TIMELINE-}" ] && export OBELISK_TIMELINE="$OUT" || unset OBELISK_TIMELINE
export OBELISK_APP_NAME="Query client"
caffeinate -i "$RUNTIME/engine/run-with-timeout.sh" "$LIMIT" /bin/bash "$LAUNCH" "$RUNTIME" "$HOMEDIR" "$INSTALL" /opt/game \
  --env HOME=/home/user --env USER=user --env LOGNAME=user --env PATH=/opt/wine/bin:/usr/bin:/bin \
  --env LANG=en_US.UTF-8 --env LC_ALL=en_US.UTF-8 --env WINEPREFIX=/home/user/prefix --env WINEARCH=win64 \
  --env WINEDEBUG=-all --env "WINEDLLOVERRIDES=mscoree,mshtml=;winemenubuilder.exe=d;d3d11,dxgi,d3d12=n" \
  --env VTEST_SOCKET_NAME=/run/obelisk/vtest.sock --env NPT_DEBUG=force_vtest \
  -- /opt/game/query_client.exe "$@" > "$OUT/run.log" 2>&1
echo "rc=$?" >> "$OUT/run.log"
rm -rf "$INSTALL"
if [ -n "${TIMELINE-}" ]; then
  for trace in "$OUT"/*/; do
    python3 -I "$W/../../tools/timeline/otl.py" "$trace" --modes "$OUT/run.log" --queries --json "$OUT/read.json" > "$OUT/read.txt" 2>&1
  done
fi
grep -a -E "FAIL|UNSUPPORTED|WATCHDOG|checks,|RESULT|^rc=" "$OUT/run.log" || tail -20 "$OUT/run.log"
