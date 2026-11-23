#!/bin/bash
# The timeline recorder's own checks, and the reader's of what it wrote (test_otl.py checks the reader's joins).
set -eu
W=$(cd "$(dirname "$0")" && pwd)
D=$(mktemp -d "${TMPDIR:-/tmp}/otl.XXXXXX"); D=$(cd "$D" && pwd -P)
IMAGE=
trap '[ -n "$IMAGE" ] && hdiutil detach -quiet -force "$D/disk" >/dev/null 2>&1; rm -rf "$D"' EXIT
build() { clang -arch arm64 -std=gnu11 -O2 -Wall -Wextra -Wno-unused-function "$@" "$W/otl_test.c"; }
build -o "$D/otl_test"
build -DTEST_FREE=0 -o "$D/otl_test_any"           # writes on however full the disk is
build -DTEST_FREE='(1ull<<60)' -o "$D/otl_test_full" # no disk has that much
mkdir "$D/off" "$D/paced" "$D/burst" "$D/identity" "$D/cap" "$D/first" "$D/exit" "$D/short" "$D/many" "$D/full" "$D/disk"
unset OBELISK_TIMELINE OBELISK_TIMELINE_MB OBELISK_TIMELINE_PASSES
"$D/otl_test" "$D/off" off && echo "off ok"
for m in paced burst identity first exit short; do OBELISK_TIMELINE="$D/$m" "$D/otl_test" "$D/$m" $m; done
echo "exit ok"
# four recorders, one budget of 8 MiB
for i in 1 2 3 4; do OBELISK_TIMELINE="$D/cap" OBELISK_TIMELINE_MB=8 "$D/otl_test" "$D/cap" fill & done; wait
# a session takes 64 recorders and no more
for i in $(seq 1 64); do OBELISK_TIMELINE="$D/many" "$D/otl_test" "$D/many" exit; done
OBELISK_TIMELINE="$D/many" "$D/otl_test" "$D/many" refused && echo "many ok"
OBELISK_TIMELINE="$D/full" "$D/otl_test_full" "$D/full" refused && echo "no space ok"
# a disk that fills up under it
if hdiutil create -quiet -size 12m -fs APFS -volname otltest "$D/disk.dmg" 2>/dev/null &&
    hdiutil attach -quiet -nobrowse -mountpoint "$D/disk" "$D/disk.dmg"; then
    IMAGE=1
    mkdir "$D/disk/session"
    OBELISK_TIMELINE="$D/disk/session" "$D/otl_test_any" "$D/disk/session" fill && echo "full disk ok"
    mkdir "$D/enospc"; cp "$D/disk/session/"*.bin "$D/enospc/"
else echo "full disk NOT RUN (no disk image)"; fi
python3 -I - "$D" "$W/../../tools/timeline/otl.py" <<'PY'
import glob, importlib.util, os, struct, sys
d, p = sys.argv[1:]
spec = importlib.util.spec_from_file_location("otl", p); otl = importlib.util.module_from_spec(spec); spec.loader.exec_module(otl)
paths = lambda m: sorted(glob.glob(f"{d}/{m}/*.bin"))
read = lambda m: otl.File(paths(m)[0])
f = read("paced")
by = {}
for r in f.get("W_TICK"): by.setdefault(r.a, []).append(r.v[0])
assert all(v == list(range(20000)) for v in by.values()) and len(by) == 4 and f.lost == 0, (len(by), f.lost)
assert len(f.get("W_RX")) == 3 * 64 * 10, len(f.get("W_RX"))
assert f.end and f.end["reason"] == "exit", f.end
b = read("burst")
assert len(b.get("W_RX")) + b.lost == 400000 and b.lost > 0, (len(b.get("W_RX")), b.lost)
assert b.lossy and sum(n for _, _, n in b.lossy) == b.lost and all(t0 < t1 for t0, t1, _ in b.lossy), b.lossy
e = read("exit")
assert len(e.get("W_RX")) == 1000 and e.end["reason"] == "exit" and e.lost == 0, e.end
s = read("short")
assert os.path.getsize(s.path) % 64 == 0 and s.end is None or s.end["reason"] == "write", s.end
assert [r.v[0] % 4000 for r in s.get("W_RX")] == [i % 4000 for i in range(len(s.get("W_RX")))], "the records of a failed write are not whole"
caps = [otl.File(x) for x in paths("cap")]
total = sum(os.path.getsize(x) for x in glob.glob(f"{d}/cap/*"))
assert len(caps) == 4 and total <= 8 << 20 and all(c.end["reason"] == "budget" and c.lost > 0 for c in caps), (total, [c.end for c in caps])
assert len(paths("many")) == 64
for m in ("enospc",) if paths("enospc") else ():
    x = read(m)
    assert os.path.getsize(x.path) % 64 == 0 and (x.end is None or x.end["reason"] in ("write",)), x.end
    print("full disk: end", x.end)
print("reader ok; four recorders of a session of 8 MiB:", total, "bytes")
PY
