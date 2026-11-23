#!/bin/sh
# Builds wsd_icon, starts wsd on a private 0700 directory and runs it with wsd's socket and log, under timeouts.
# Exit 0 when the Dock icon stayed the game's at every step (wsd_icon.c).
set -u
W=$(cd "$(dirname "$0")" && pwd)
EXP=$(cd "$W/../.." && pwd)
TO="$EXP/fexdarwin/scripts/run-with-timeout.sh"
D=$(mktemp -d "${TMPDIR:-/tmp}/wsd.XXXXXX")
clang -O2 -Wall -o "$D/wsd_icon" "$W/wsd_icon.c" || exit 1
"$TO" 60 "$EXP/wsd/bin/wsd" --dir "$D" --exit-on-disconnect > "$D/wsd.log" 2>&1 &
SPID=$!
i=0; while [ ! -S "$D/wsd.sock" ] && [ $i -lt 50 ]; do sleep 0.1; i=$((i+1)); done
"$TO" 40 "$D/wsd_icon" "$D/wsd.sock" "$D/wsd.log"
RC=$?
i=0; while kill -0 "$SPID" 2>/dev/null && [ $i -lt 30 ]; do sleep 0.1; i=$((i+1)); done
kill "$SPID" 2>/dev/null; wait "$SPID" 2>/dev/null
echo "## wsd log (icons)"; grep -i "icon\|disconnected\|overlay plane" "$D/wsd.log"
rm -rf "$D"
exit $RC
