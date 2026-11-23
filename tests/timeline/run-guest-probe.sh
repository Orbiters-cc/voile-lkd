#!/bin/bash
# What the launcher gives the process that becomes the game, with a probe in the engine's place: the same, to the last
# descriptor, flag, variable, signal, argument and process group, under the released generation and the timeline's, with the
# recorder off and on, and with the variables in the launcher's own environment.
# Usage: run-guest-probe.sh <generation folder (released/, timeline/)> <launch.sh of the timeline branch> [<launch.sh as released>]
set -eu
W=$(cd "$(dirname "$0")" && pwd)
GEN=$(cd "$1" && pwd) LAUNCH=$2 RELEASED=${3:-}
D=$(mktemp -d "${TMPDIR:-/tmp}/probe.XXXXXX"); D=$(cd "$D" && pwd -P); trap 'rm -rf "$D"' EXIT
clang -arch arm64 -O1 -o "$D/probe" "$W/guest_probe.c"; codesign -s - -f "$D/probe" 2>/dev/null
mkdir -p "$D/home/prefix" "$D/install" "$D/out" "$D/trace" "$D/tmp"
# one <name> <tree> <launch.sh> [variable=value ...]: the same runtime path each time, so that nothing differs by its name
one() {
    local name=$1 tree=$2 script=$3; shift 3
    rm -rf "$D/runtime"; cp -Rc "$GEN/$tree" "$D/runtime"
    cat "$D/probe" > "$D/runtime/engine/fexdarwin-run"
    (
        exec 3<&-
        exec env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin HOME="$D/home" TMPDIR="$D/tmp" OBELISK_APP_NAME=Probe "$@" /bin/bash -c "$(cat "$script")" obelisk-linux-engine \
            "$D/runtime" "$D/home" "$D/install" /opt/game --graphics dxmt --env WINEPREFIX=/home/user/prefix --env TZ=UTC -- /opt/game/none.exe one "two three" \
            < /dev/null > /dev/null 2> "$D/out/$name.log"
    ) || true
    local made; made=$(ls -d "$D"/tmp/obelisk-engine-* 2>/dev/null || true)
    sed -E -e 's/obelisk-engine-[0-9]+/obelisk-engine-PID/g' -e 's/FEXDARWIN_SUPERVISOR_PID=[0-9]+/FEXDARWIN_SUPERVISOR_PID=PID/' -e "s#$D/out/$name.log#LOG#" \
        "$D/runtime/probe.txt" > "$D/out/$name.txt" || { echo "$name: the probe did not run"; cat "$D/out/$name.log"; exit 1; }
    [ -z "$made" ] || { echo "$name: $made is left"; exit 1; }
}
mkdir "$D/on" "$D/inherited"
one released-off released "$LAUNCH"
[ -z "$RELEASED" ] || one released-script released "$RELEASED"
one timeline-off timeline "$LAUNCH"
one timeline-on timeline "$LAUNCH" OBELISK_TIMELINE="$D/on" OBELISK_TIMELINE_MB=64 OBELISK_TIMELINE_PASSES=8
one timeline-half timeline "$LAUNCH" OBELISK_TIMELINE_MB=64 OBELISK_TIMELINE_PASSES=8
one switches timeline "$LAUNCH" OBELISK_WSD_UPSCALE=metalfx OBELISK_WSD_PRESENT=arrival
one queries timeline "$LAUNCH" OBELISK_DXMT_QUERY_RESCUE=once
one all timeline "$LAUNCH" OBELISK_WSD_UPSCALE=metalfx OBELISK_WSD_PRESENT=arrival OBELISK_DXMT_QUERY_RESCUE=once OBELISK_TIMELINE="$D/on" OBELISK_TIMELINE_MB=64 OBELISK_TIMELINE_PASSES=8
status=0
for name in ${RELEASED:+released-script} timeline-off timeline-on timeline-half switches queries all; do
    if diff "$D/out/released-off.txt" "$D/out/$name.txt" > "$D/out/$name.diff"; then
        echo "identical: $name ($(wc -l < "$D/out/$name.txt" | tr -d ' ') lines: $(cut -d' ' -f1 "$D/out/$name.txt" | sort | uniq -c | awk '{printf "%s%s %s", s, $1, $2; s=", "}'))"
    else
        echo "DIFFERENT: $name"; cat "$D/out/$name.diff"; status=1
    fi
done
grep -lE "OBELISK_(TIMELINE|WSD|DXMT)" "$D"/out/*.txt && { echo "THE GAME SEES THE TIMELINE'S VARIABLES"; status=1; }
grep -q "wsd: switches: upscale metalfx (MetalFX), present arrival" "$D/out/switches.log" || { echo "the window server had no switches"; status=1; }
grep -l "wsd: switches" "$D/out/released-off.log" "$D/out/timeline-off.log" "$D/out/timeline-on.log" && { echo "a window server had switches nobody gave"; status=1; }
echo "recorded with the recorder on: $(ls "$D"/on/*/ 2>/dev/null | tr '\n' ' ')"
ls "$D"/on/*/otl-wsd-*.bin >/dev/null 2>&1 || { echo "the recorder was not on"; status=1; }
exit $status
