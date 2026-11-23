#!/bin/bash
# What cuts the main colour target's passes, with the owned Direct3D 11 client: its q- and m- modes (pass_costs.cpp) through the
# whole chain, one mode a run, every frame's encoders and reasons recorded, and the reader's table of each.
#
# Usage: run-splits.sh <runtime> <home> <launch.sh> <out-folder> <render-percent> <seconds> [mode ...]   (as run-pass-costs.sh)
set -u
W=$(cd "$(dirname "$0")" && pwd)
RUNTIME=$1 HOMEDIR=$2 LAUNCH=$3 OUT=$4 PERCENT=$5 SECONDS_EACH=$6
shift 6
[ $# -gt 0 ] || set -- q-none q-event-frame q-disjoint-frame q-event-mid q-stamp-mid q-occ-mid q-occ-alone q-event-pollflush \
  m-discard m-nooverwrite m-dyntex m-update m-readback m-readback-end m-flush
for mode in "$@"; do
  TIMELINE=1 OBELISK_TIMELINE_PASSES=1 "$W/run-pass-costs.sh" "$RUNTIME" "$HOMEDIR" "$LAUNCH" "$OUT/$mode" "$PERCENT" "$SECONDS_EACH" "$mode" || exit $?
  for trace in "$OUT/$mode"/*/; do
    python3 -I "$W/../../tools/timeline/otl.py" "$trace" --modes "$OUT/$mode/run.log" --splits --json "$OUT/$mode/read.json" > "$OUT/$mode/read.txt" 2>&1
  done
  sed -n '/command buffers:/,$p' "$OUT/$mode/read.txt"
done
