#!/bin/bash
# The timeline recorder's own checks, and the reader's of what it wrote.
set -eu
W=$(cd "$(dirname "$0")" && pwd)
D=$(mktemp -d "${TMPDIR:-/tmp}/otl.XXXXXX"); trap 'rm -rf "$D"' EXIT
clang -arch arm64 -std=gnu11 -O2 -Wall -Wextra -Wno-unused-function -o "$D/otl_test" "$W/otl_test.c"
mkdir "$D/off" "$D/paced" "$D/burst" "$D/identity" "$D/cap"
unset OBELISK_TIMELINE
"$D/otl_test" "$D/off" off && echo "off ok"
for m in paced burst identity; do OBELISK_TIMELINE="$D/$m" "$D/otl_test" "$D/$m" $m; done
OBELISK_TIMELINE="$D/cap" OBELISK_TIMELINE_MB=1 "$D/otl_test" "$D/cap" paced >/dev/null
python3 -I - "$D" "$W/../../tools/timeline/otl.py" <<'PY'
import glob, importlib.util, os, sys
d, p = sys.argv[1:]
spec = importlib.util.spec_from_file_location("otl", p); otl = importlib.util.module_from_spec(spec); spec.loader.exec_module(otl)
read = lambda m: otl.File(glob.glob(f"{d}/{m}/*.bin")[0])
f = read("paced")
by = {}
for r in f.get("W_TICK"): by.setdefault(r.a, []).append(r.v[0])
assert all(sorted(v) == list(range(20000)) for v in by.values()) and len(by) == 4 and f.lost == 0, (len(by), f.lost)
assert len(f.get("W_RX")) == 3 * 96 * 10, len(f.get("W_RX"))
b = read("burst")
assert len(b.get("W_RX")) + b.lost == 200000 and b.lost > 0, (len(b.get("W_RX")), b.lost)
c = read("cap")
assert os.path.getsize(c.path) < (1 << 20) + 4096 and c.lost > 0, (os.path.getsize(c.path), c.lost)
print("reader ok")
PY
