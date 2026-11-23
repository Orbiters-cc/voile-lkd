#!/usr/bin/env python3
"""Reads a host timeline (wsd/otl.h, format 2) and says where each frame's time went, and how much of it is known.

Usage: otl.py <session folder> [--from NS] [--to NS] [--modes run.log] [--plane ID] [--frames N] [--passes] [--cadence]
              [--csv out.csv] [--json out.json]

The session folder holds otl-npt-*.bin and otl-dxmt-*.bin (one of each per render server worker), otl-vtest-*.bin and
otl-wsd-*.bin. A frame is one presentation signal of a ring: a CopyResource into an exported image, then a Signal.

What is joined, and by what (each record is used once; nothing is joined by being the nearest in time):
  ring -> frame            the ring's own record (N_FRAME follows its N_SIGNAL); two exported copies before one Signal: not told
  ring -> DXMT             the fence's pointer and value, and D_SIGNAL made inside that very call; then queue id and chunk
  DXMT -> event thread     the HANDLE SetEventOnCompletion was given is an event id (N_EVENT: the last made with that handle), its
                           arm (N_ARM, N_PAIR), which names the ring, the fence id and the context (N_FENCE, N_RETIRE, V_RETIRE)
  ring -> wsd              the memory and offset of the exported image (export id), the buffer the client attached (client id,
                           attach to detach); between two presentations of one image there is one frame, or it is not told which
  inside wsd               plane id and presentation serial
An id is never reused (a pointer or a handle is). What is missing or ambiguous is counted and the frame is not "whole": no boundary
is ever filled in from another. All times are host uptime nanoseconds. Standard library only.
"""
import argparse, bisect, collections, csv, glob, json, os, re, struct, sys

K = dict(THREAD=1, SUMMARY=2, HIST=3, LOST=4, END=5, N_EXPORT=16, N_SIGNAL=18, N_COUNTS=19, N_FENCE=20, N_PAIR=21, N_RETIRE=22,
         N_FLUSH=23, V_RETIRE=24, N_GONE=26, N_FRAME=27, N_EVENT=28, N_ARM=29, D_READY=32, D_ENCODE=33, D_DONE=34, D_SIGNAL=35,
         D_SEOC=36, D_NOTIFY=37, D_PIPELINE=38, D_INIT=39, D_INIT_DONE=40, D_PASS=41, D_PASS_DS=42, D_BLIT=43, D_COMPUTE=44,
         D_OPS=45, D_PASS_TIME=46, D_QUEUE=47, D_PASS_SKIP=48, D_CLOCK=49, W_ATTACH=64, W_RX=65, W_TICK=66, W_DRAW=67, W_GPU=68,
         W_SHOWN=69, W_RELEASE=70, W_DETACH=71)
REC = struct.Struct("<QHHI6Q")
Rec = collections.namedtuple("Rec", "t kind thr a v")
LOAD = {0: "dontcare", 1: "load", 2: "clear"}
STORE = {0: "dontcare", 1: "store", 2: "resolve", 3: "store+resolve", 4: "unknown"}
END = {0: "exit", 1: "budget", 2: "write", 3: "space"}
SKIP = {1: "no sample buffer free", 2: "too many encoders", 3: "no GPU timestamps here", 4: "its command buffer failed",
        5: "not resolved"}
COMPLETED, NONE, SERIAL = 4, 2**64 - 1, (1 << 48) - 1  # MTLCommandBufferStatusCompleted
# Kept whatever the time asked for: what names things that live longer than it.
ALWAYS = {K[k] for k in ("THREAD", "SUMMARY", "HIST", "LOST", "END", "N_EXPORT", "N_GONE", "N_EVENT", "D_QUEUE", "D_CLOCK",
                         "W_ATTACH", "W_DETACH")}
FORMAT = {10: ("R8", 1), 13: ("R8ui", 1), 25: ("R16F", 2), 30: ("RG8", 2), 53: ("R32ui", 4), 55: ("R32F", 4), 65: ("RG16F", 4),
          70: ("RGBA8", 4), 71: ("RGBA8s", 4), 80: ("BGRA8", 4), 81: ("BGRA8s", 4), 90: ("RGB10A2", 4), 92: ("RG11B10F", 4),
          105: ("RG32F", 8), 110: ("RGBA16", 8), 115: ("RGBA16F", 8), 125: ("RGBA32F", 16), 250: ("D16", 2), 252: ("D32F", 4),
          253: ("S8", 1), 255: ("D24S8", 4), 260: ("D32FS8", 8), 261: ("X32S8", 8)}


class File:
    """One recorder's file: its records of [lo, hi] by kind, in order, and what it says of itself."""

    def __init__(self, path, lo=0, hi=2**64, margin=3_000_000_000):
        self.path, self.by, self.windows, self.hist = path, collections.defaultdict(list), [], {}
        self.lost, self.lossy, self.end, self.last, self.kept, self.cut = 0, [], None, 0, 0, 0
        lo, hi = max(0, lo - margin), hi + margin
        with open(path, "rb") as f:
            head = f.read(64)
            magic, version, self.pid, self.passes = struct.unpack_from("<4sIII", head, 0)
            if magic != b"OTL1" or version != 2:
                raise SystemExit(f"{path}: not a timeline of format 2")
            self.role = head[16:32].split(b"\0")[0].decode()
            self.uptime, self.wall_us, self.continuous, self.limit = struct.unpack_from("<QQQQ", head, 32)
            while True:
                block = f.read(64 * 16384)
                whole = len(block) - len(block) % 64
                self.cut += len(block) - whole
                for t, kind, thr, a, *v in REC.iter_unpack(memoryview(block)[:whole]):
                    self.kept += 1
                    if thr != 0xffff:
                        self.last = max(self.last, t)
                    if lo <= t <= hi or kind in ALWAYS:
                        self.take(t, kind, thr, a, v)
                if len(block) < 64 * 16384:
                    break
        for l in self.by.values():
            l.sort(key=lambda r: r.t)

    def take(self, t, kind, thr, a, v):
        if kind == K["SUMMARY"]:
            self.windows.append((a, v))
            self.lost = max(self.lost, v[4])
        elif kind == K["LOST"]:
            self.lossy.append((v[0], v[1], v[2]))
            self.lost = max(self.lost, v[3])
        elif kind == K["END"]:
            self.end = dict(reason=END.get(a, a), kept=v[0], lost=v[1], errno=v[3], refused=v[4], t=t)
            self.lost = max(self.lost, v[1])
        elif kind == K["HIST"]:
            h = self.hist.setdefault((len(self.windows), a & 0xff), [0] * 36)
            h[(a >> 8) * 12:(a >> 8) * 12 + 12] = struct.unpack("<12I", struct.pack("<6Q", *v))
        else:
            self.by[kind].append(Rec(t, kind, thr, a, v))

    def get(self, kind):
        return self.by.get(K[kind], [])

    def lost_in(self, lo, hi):
        """Whether records may be missing from [lo, hi]: lost in it, or the recorder ended before its end."""
        if any(a <= hi and b >= lo for a, b, _ in self.lossy):
            return "records lost"
        if self.end and self.end["reason"] != "exit" and self.end["t"] < hi:
            return f"its recorder ended ({self.end['reason']})"
        return None

    def says(self):
        end = f"ended: {self.end['reason']}" if self.end else "no end record (killed: up to 50 ms of its last records are not there)"
        if self.end and self.end["errno"]:
            end += f" (errno {self.end['errno']})"
        if self.end and self.end["refused"]:
            end += f", {self.end['refused']} recorders refused"
        return (f"{os.path.basename(self.path)}: {self.role} pid {self.pid}, {self.kept} records, {self.lost} LOST"
                + (f" in {len(self.lossy)} intervals" if self.lossy else "") + (f", {self.cut} bytes cut" if self.cut else "") + f", {end}")


class Table:
    """Records by key, each taken at most once. A key with several candidates is told as such, never picked from."""

    def __init__(self, records, key):
        self.by = collections.defaultdict(list)
        for r in records:
            self.by[key(r)].append(r)

    def take(self, key, lo=0, hi=2**64):
        l = [r for r in self.by.get(key, ()) if lo <= r.t <= hi]
        if len(l) != 1:
            return None, "missing" if not l else "ambiguous"
        self.by[key].remove(l[0])
        return l[0], None


def pct(values, p):
    if not values:
        return float("nan")
    s = sorted(values)
    return s[min(len(s) - 1, int(p / 100 * len(s)))]


def mean(values):
    return sum(values) / len(values) if values else float("nan")


class Intervals:
    """The union of intervals."""

    def __init__(self, intervals):
        self.a, self.b = [], []
        for a, b in sorted(i for i in intervals if i[1] > i[0]):
            if self.b and a <= self.b[-1]:
                self.b[-1] = max(self.b[-1], b)
            else:
                self.a.append(a)
                self.b.append(b)

    def inside(self, lo, hi):
        """Its length inside [lo, hi]."""
        total = 0
        for i in range(bisect.bisect_right(self.b, lo), len(self.a)):
            if self.a[i] >= hi:
                break
            total += min(self.b[i], hi) - max(self.a[i], lo)
        return total


def attachment(w):
    fmt, n = FORMAT.get(w & 0xffff, (f"fmt{w & 0xffff}", 4))
    return dict(format=fmt, bytes=n, samples=w >> 16 & 0xff, load=w >> 24 & 0xf, store=w >> 28 & 0xf, resolved=w >> 32 & 1,
                memoryless=w >> 33 & 1, width=w >> 34 & 0x7fff, height=w >> 49 & 0x7fff)


def attachment_text(w):
    a = attachment(w)
    return (f"{a['format']} {a['width']}x{a['height']}" + (f" {a['samples']}x" if a["samples"] > 1 else "") +
            f" {LOAD.get(a['load'], a['load'])}/{STORE.get(a['store'], a['store'])}" + (" memoryless" if a["memoryless"] else ""))


def attachment_bytes(w, plane=None):
    """Nominal tile traffic of one attachment: what its load and store move, uncompressed. plane: which plane of a
    combined depth and stencil format (4 bytes and 1; Apple's GPUs keep them apart)."""
    a = attachment(w)
    size = a["width"] * a["height"] * ({"depth": 4, "stencil": 1}[plane] if plane and a["bytes"] == 8 else a["bytes"])
    return size * a["samples"] * ((a["load"] == 1) + (a["store"] in (1, 3))) + size * (a["store"] in (2, 3))


# The boundaries of a presented frame in order, and the parts of the fence wait between them. A part over before the stopwatch
# began counts nothing; a boundary that is not known, or before the one it follows, leaves the frame without parts.
MARKS = ["ready", "woken", "flushed", "gpu_start", "gpu_end", "notify", "retire_woken", "proxy", "client"]
PARTS = ["replay tail", "encode queue", "encode", "commit to GPU start", "GPU execution", "GPU end to notify", "notify to worker awake",
         "worker awake to proxy", "proxy to guest stamp"]
POST = ["to wsd", "to tick", "drawable wait", "tick to commit", "commit to GPU end", "GPU end to shown", "client to shown"]


class Session:
    def __init__(self, folder, lo=0, hi=2**64):
        paths = sorted(glob.glob(os.path.join(folder, "otl-*.bin")))
        if not paths:
            raise SystemExit(f"{folder}: no otl-*.bin")
        self.files = [File(p, lo, hi) for p in paths]
        self.wsd = [f for f in self.files if f.role == "wsd"]
        self.vtest = [f for f in self.files if f.role == "vtest"]
        self.dxmt = {f.pid: f for f in self.files if f.role == "dxmt"}
        self.npt = [f for f in self.files if f.role == "npt"]
        self.frames, self.unseen = [], collections.Counter()
        self.passes_by = None
        for f in self.npt:
            if f.pid in self.dxmt:
                self.join_worker(f, self.dxmt[f.pid])
        self.frames.sort(key=lambda f: f["signal_end"])
        for f in self.wsd:
            self.join_wsd(f)
        self.gpu_intervals()
        self.measure()

    def roles(self, f):
        """The files a frame's boundaries come from."""
        return [f["npt"], self.dxmt[f["npt"].pid]] + self.vtest + self.wsd

    def join_worker(self, n, d):
        signals = {(r.thr, r.t): r for r in n.get("N_SIGNAL")}
        counts = {(r.thr, r.t): r for r in n.get("N_COUNTS")}
        exports = {r.v[4]: r for r in n.get("N_EXPORT")}
        chunk = lambda q, c: lambda r: (r.v[q], r.v[c])
        d_signal = Table(d.get("D_SIGNAL"), lambda r: (r.v[1], r.v[2]))
        ready, enc = Table(d.get("D_READY"), chunk(0, 1)), Table(d.get("D_ENCODE"), chunk(5, 0))
        done = Table(d.get("D_DONE"), chunk(5, 0))
        all_enc = {(r.v[5], r.v[0]): r for r in d.get("D_ENCODE")}
        seocs = Table(d.get("D_SEOC"), lambda r: (r.v[0], r.v[1]))
        notify = Table(d.get("D_NOTIFY"), lambda r: (r.v[0], r.v[1], r.v[2]))
        events = collections.defaultdict(list)  # HANDLE -> [(made, event id)]
        for r in n.get("N_EVENT"):
            events[r.v[1]].append((r.t, r.v[0]))
        seoc_times = collections.defaultdict(list)  # event id -> times of its SetEventOnCompletion calls
        event_at = {}
        for r in d.get("D_SEOC"):
            l = events.get(r.v[2], [])
            i = bisect.bisect_right(l, (r.t, 2**64)) - 1
            if i >= 0:
                event_at[id(r)] = l[i][1]
                seoc_times[l[i][1]].append(r.t)
        arms = collections.defaultdict(list)
        for r in n.get("N_ARM"):
            arms[r.v[1]].append(r)
        pair = Table(n.get("N_PAIR"), lambda r: r.v[3])
        fence = Table(n.get("N_FENCE"), lambda r: (r.v[1], r.a, r.v[0]))
        retire = Table(n.get("N_RETIRE"), lambda r: (r.v[3], r.a, r.v[0]))
        vret = Table([r for f in self.vtest for r in f.get("V_RETIRE")], lambda r: (r.v[2], r.a, r.v[0]))
        last_chunk = {}
        for r in n.get("N_FRAME"):
            s = signals.get((r.thr, r.t))
            f = dict(npt=n, id=r.v[5], signal_end=r.t, thread=r.thr, fence=r.v[0], value=r.v[1], why=[], copy=r.v[3], copy_end=r.v[4])
            self.frames.append(f)
            miss = f["why"].append
            if r.a != 1:
                miss("ambiguous: more than one exported copy before the Signal")
            ex = exports.get(r.v[2])
            f.update(export=r.v[2], identity=ex.v[1] if ex else 0, size=ex.v[2] if ex else 0)
            if not ex:
                miss("missing: export")
            if not s:
                miss("missing: signal")
                continue
            f.update(context=s.a, signal=s.v[0], decode=s.v[3], first=s.v[4], commands=s.v[5])
            cr = counts.get((r.thr, r.t))
            if cr:
                f.update(draws=cr.v[0], maps=cr.v[1], updates=cr.v[3], flushes=cr.v[4], copies=cr.v[5] >> 32,
                         targets=cr.v[5] & 0xffffffff)
            ds, why = d_signal.take((f["fence"], f["value"]), s.v[0], r.t)
            if not ds:
                miss(f"{why}: DXMT's signal")
                continue
            q, c = ds.v[4], ds.v[0]
            f.update(queue=q, chunk=c, group=ds.v[5])
            # the frame's chunks: those since the one before it on this queue ended; the first frame's are not known
            if q in last_chunk:
                f["chunks"] = list(range(last_chunk[q] + 1, c + 1))
            last_chunk[q] = c
            for name, table in (("ready", ready), ("enc", enc), ("done", done)):
                x, why = table.take((q, c))
                if not x:
                    miss(f"{why}: {name}")
                    continue
                f[name + "_rec"] = x
            if "ready_rec" in f:
                f["ready"] = f["ready_rec"].t
            if "enc_rec" in f:
                f["woken"], f["flushed"], f["committed"] = f["enc_rec"].v[1], f["enc_rec"].v[3], f["enc_rec"].t
            if "done_rec" in f:
                x = f["done_rec"]
                if x.a == COMPLETED and 0 < x.v[1] <= x.v[2]:
                    f["gpu_start"], f["gpu_end"] = x.v[1], x.v[2]
                else:
                    miss(f"its command buffer's status is {x.a}")
            if "chunks" in f and all((q, x) in all_enc for x in f["chunks"]):
                f["encode_frame"] = sum(all_enc[(q, x)].v[3] - all_enc[(q, x)].v[1] for x in f["chunks"])
                f["pipeline_frame"] = sum(all_enc[(q, x)].v[4] for x in f["chunks"])
            so, why = seocs.take((f["fence"], f["value"]))
            if not so:
                miss(f"{why}: SetEventOnCompletion")
                continue
            event = event_at.get(id(so))
            if event is None:
                miss("missing: the event of its HANDLE")
                continue
            nt, why = notify.take((so.v[3], so.v[1], so.v[2]), so.t)
            if nt:
                f["notify"] = nt.t
            else:
                miss(f"{why}: notify")
            # its arm: the one between the call before on the same event and this one
            before = [t for t in seoc_times[event] if t < so.t]
            l = [x for x in arms[event] if x.t <= so.t and (not before or x.t > before[-1])]
            if len(l) != 1:
                miss(f"{'missing' if not l else 'ambiguous'}: arm")
                continue
            p, why = pair.take(l[0].v[0])
            if not p:
                miss(f"{why}: pair")
                continue
            key = (p.v[2], p.a, p.v[0])
            x, why = fence.take(key)
            if x:
                f["submit"] = x.t
            else:
                miss(f"{why}: fence")
            x, why = retire.take(key)
            if x:
                said = x.v[4] - 2**64 if x.v[4] >> 63 else x.v[4]
                if said > 0:
                    f["retired"], f["retire_woken"] = x.t, x.v[1]
                else:
                    miss("its fence was retired without its signal")
            else:
                miss(f"{why}: retire")
            x, why = vret.take(key)
            if x:
                f["proxy"] = x.t
            else:
                miss(f"{why}: proxy")

    def join_wsd(self, w):
        attach = collections.defaultdict(list)  # (client, buffer) -> [(t, identity or None once detached)]
        for r in w.get("W_ATTACH"):
            attach[(r.v[3], r.a)].append((r.t, r.v[0]))
        for r in w.get("W_DETACH"):
            attach[(r.v[0], r.a)].append((r.t, None))
        for l in attach.values():
            l.sort(key=lambda x: x[0])
        tables = {}
        for name in ("W_DRAW", "W_GPU", "W_SHOWN"):
            at = 1 if name == "W_DRAW" else 0
            plane = {"W_DRAW": 5, "W_GPU": 5, "W_SHOWN": 3}[name]
            tables[name] = Table([r for r in w.get(name) if not r.a >> 31 and not (name == "W_DRAW" and r.v[4] == NONE)],
                                 lambda r, at=at, plane=plane: (r.v[plane], r.v[at]))
        rx = w.get("W_RX")
        replaced = {(r.v[5] & 0xffffffff, r.v[4]) for r in rx if r.a >> 31}
        by_image = collections.defaultdict(list)
        for f in self.frames:
            if f["identity"]:
                by_image[f["identity"]].append(f)
        images, previous = collections.defaultdict(list), {}
        for r in rx:
            client, plane = r.v[5] >> 32, r.v[5] & 0xffffffff
            l = [i for t, i in attach.get((client, r.v[0]), ()) if t <= r.t]
            if not l or l[-1] is None:
                self.unseen["presentations of a buffer whose attachment is not recorded"] += 1
            else:
                images[l[-1]].append((r, previous.get(plane)))
            previous[plane] = r.v[2]
        for image, l in images.items():
            frames = by_image.get(image, [])
            times, at = [f["signal_end"] for f in frames], 0
            for r, before in l:
                end = bisect.bisect_right(times, r.v[2])
                mine, at = frames[at:end], end
                if len(mine) != 1:
                    self.unseen["presentations without a recorded frame" if not mine else "presentations after several frames of their image"] += 1
                    for f in mine:
                        f["why"].append("ambiguous: presented with another frame of its image")
                    continue
                f, plane, key = mine[0], r.v[5] & 0xffffffff, (r.v[5] & 0xffffffff, r.v[1])
                f.update(client=r.v[2], rx=r.v[3], serial=r.v[1], plane=plane, window=r.a & 0x3fffffff, region=r.a >> 30 & 1,
                         replaced=key in replaced, before=before)
                x, _ = tables["W_DRAW"].take(key)
                if x:
                    f.update(tick=x.v[2], drawable=x.v[3], wsd_commit=x.t)
                x, _ = tables["W_GPU"].take(key)
                if x:
                    f.update(wgpu_start=x.v[1], wgpu_end=x.v[2])
                x, _ = tables["W_SHOWN"].take(key)
                if x:
                    f["shown"] = x.v[1]
        for f in self.frames:
            if "client" not in f:
                f["why"].append("missing: presentation")

    def gpu_intervals(self):
        own = collections.defaultdict(list)  # (pid, queue) -> intervals
        rest = []
        for d in self.dxmt.values():
            for r in d.get("D_DONE"):
                own[(d.pid, r.v[5])].append((r.v[1], r.v[2]))
            rest += [(r.v[1], r.v[2]) for r in d.get("D_INIT_DONE")]
        for w in self.wsd:
            rest += [(r.v[1], r.v[2]) for r in w.get("W_GPU")]
        self.queue_gpu = {k: Intervals(l) for k, l in own.items()}
        self.all_gpu = Intervals([i for l in own.values() for i in l] + rest)

    def not_all_gpu(self, lo, hi):
        """Why the GPU intervals recorded are not all this session's in [lo, hi]; None when they are."""
        if not self.wsd:
            return "wsd's are not recorded"
        if not self.dxmt:
            return "no DXMT queue is recorded"
        for n in self.npt:
            if n.pid not in self.dxmt and n.last >= lo:
                return f"those of worker {n.pid} are not recorded"
        for f in list(self.dxmt.values()) + self.wsd:
            why = f.lost_in(lo, hi)
            if why:
                return f"{f.role} {f.pid}: {why}"
            if f.end and f.end["refused"]:
                return "a recorder was refused"
        for d in self.dxmt.values():
            done = {(r.v[5], r.v[0]) for r in d.get("D_DONE")}
            left = [r for r in d.get("D_ENCODE") if (r.v[5], r.v[0]) not in done and lo <= r.t <= hi]
            if left:
                return f"dxmt {d.pid}: {len(left)} command buffers committed and never seen done"
            inits = {r.v[0] for r in d.get("D_INIT_DONE")}
            if any(r.v[0] not in inits and lo <= r.t <= hi for r in d.get("D_INIT")):
                return f"dxmt {d.pid}: initializer command buffers never seen done"
        return None

    def measure(self):
        for f in self.frames:
            if f["why"]:
                continue
            if f.get("before") is None:
                f["why"].append("first of its plane: where its wait begins is not known")
                continue
            lossy = [x for x in (g.lost_in(f.get("copy", 0), f["client"]) for g in self.roles(f)) if x]
            if lossy:
                f["why"].append(f"{lossy[0]} while it was made")
                continue
            start, at, parts = max(f["submit"], f["before"]), None, []
            raw = [f[m] for m in MARKS]
            bad = [(a, b, y - x) for a, b, x, y in zip(MARKS, MARKS[1:], raw, raw[1:]) if y < x]
            if bad or f["client"] < start:
                a, b, by = bad[0] if bad else ("start", "client", f["client"] - start)
                f["why"].append(f"out of order: {b} before {a}")
                f["order"] = by
                continue
            at = start
            for m in raw:
                m = max(m, start)
                parts.append(m - at)
                at = m
            f.update(start=start, wait=f["client"] - start, parts=parts)
            f["gpu_in_wait"] = self.all_gpu.inside(start, f["client"])
            if all(k in f for k in ("tick", "wgpu_end")):
                f["post"] = [f["rx"] - f["client"], f["tick"] - f["rx"], f["drawable"] - f["tick"], f["wsd_commit"] - f["drawable"],
                             f["wgpu_end"] - f["wsd_commit"], f["shown"] - f["wgpu_end"] if f.get("shown") else None,
                             f["shown"] - f["client"] if f.get("shown") else None]
        # between two consecutive presentations of one plane: how much of it anything of this session ran on the GPU
        for f in self.frames:
            if f.get("before") is not None:
                f["interval"] = f["client"] - f["before"]
                f["gpu_busy"] = self.all_gpu.inside(f["before"], f["client"])
                if "queue" in f:
                    own = self.queue_gpu.get((f["npt"].pid, f["queue"]))
                    f["queue_busy"] = own.inside(f["before"], f["client"]) if own else 0

    def clock(self, d, queue):
        """GPU timestamps to uptime for a queue, from its recorded clocks: (rate, at, gpu) or why there is none."""
        l = [r for r in d.get("D_CLOCK") if r.v[4] == queue]
        if len(l) < 2 or l[-1].v[1] <= l[0].v[1]:
            return None, "fewer than two clocks of both"
        mid = lambda r: (r.v[2] + r.v[3]) / 2
        rate = (mid(l[-1]) - mid(l[0])) / (l[-1].v[1] - l[0].v[1])
        worst = max(abs(mid(l[0]) + (r.v[1] - l[0].v[1]) * rate - mid(r)) for r in l)
        if worst > 200_000:
            return None, f"the two clocks are up to {worst / 1e3:.0f} us apart"
        return (rate, mid(l[0]), l[0].v[1], worst), None

    def passes(self, f):
        """The encoder list of a frame, as Metal got it: None when it was not recorded (the frame is not one of every Nth)."""
        d = self.dxmt[f["npt"].pid]
        if self.passes_by is None:
            self.passes_by = {}
        if d.pid not in self.passes_by:
            by = self.passes_by[d.pid] = collections.defaultdict(list)
            for k in ("D_PASS", "D_PASS_DS", "D_BLIT", "D_COMPUTE", "D_OPS", "D_PASS_TIME", "D_PASS_SKIP"):
                for r in d.get(k):
                    by[r.v[0]].append(r)
            self.clocks = getattr(self, "clocks", {})
            self.chunk_done = getattr(self, "chunk_done", {})
            self.chunk_done[d.pid] = {(r.v[5], r.v[0]): r for r in d.get("D_DONE")}
        if not d.passes or f.get("group") is None or f["group"] % d.passes or "chunks" not in f:
            return None
        out = []
        for c in f["chunks"]:
            by = {}
            for r in self.passes_by[d.pid].get(f["queue"] << 48 | c, []):
                i = r.a & 0xffff
                e = by.setdefault(i, dict(chunk=c, index=i, colours=[], ops=0, pixels=0))
                if r.kind == K["D_PASS"]:
                    n = r.a >> 16 & 0xff
                    e.update(type="render", colours=r.v[2:2 + min(n, 4)], more=max(0, n - 4))
                elif r.kind == K["D_PASS_DS"]:
                    e.update(depth=r.v[1], stencil=r.v[2])
                elif r.kind == K["D_BLIT"]:
                    e["type"] = "blit"
                elif r.kind == K["D_COMPUTE"]:
                    e["type"] = "compute"
                elif r.kind == K["D_OPS"]:
                    e["ops"] += r.v[1]
                    e["pixels"] += r.v[2]
                elif r.kind == K["D_PASS_TIME"]:
                    e["times"], e["times_why"] = self.times(d, f["queue"], c, r)
            out += [by[i] for i in sorted(by) if "type" in by[i]]
        return out

    def times(self, d, queue, chunk, r):
        """An encoder's stages as [(name, start, end)] in uptime, or why they cannot be told: only what the GPU wrote, and only
        inside its command buffer's own GPU time."""
        if (d.pid, queue) not in self.clocks:
            self.clocks[(d.pid, queue)] = self.clock(d, queue)
        clock, why = self.clocks[(d.pid, queue)]
        if not clock:
            return None, why
        to = lambda x: clock[1] + (x - clock[2]) * clock[0]
        names = ("vertex", "fragment") if r.a >> 16 & 0xff == 0 else ("compute" if r.a >> 16 & 0xff == 1 else "blit",)
        out, done = [], self.chunk_done[d.pid].get((queue, chunk))
        for i, name in enumerate(names):
            a, b = r.v[1 + 2 * i], r.v[2 + 2 * i]
            if a in (0, NONE) or b in (0, NONE):
                continue  # not written: a pass without that stage, or the GPU's error value
            if b < a:
                return None, "ends before it begins"
            a, b = to(a), to(b)
            if not done:
                return None, "its command buffer was not seen done"
            if a < done.v[1] - 50e3 - clock[3] or b > done.v[2] + 50e3 + clock[3]:
                return None, "outside its command buffer's GPU time"
            out.append((name, a, b))
        return (out, None) if out else (None, "nothing written")


def pass_text(e):
    if e["type"] != "render":
        return f"{e['type']}: {e['ops']} ops" + (f", {e['pixels']} px copied" if e["pixels"] else "")
    parts = [attachment_text(w) for w in e["colours"]]
    if e.get("more"):
        parts.append(f"{e['more']} colours more")
    if e.get("depth"):
        parts.append("depth " + attachment_text(e["depth"]))
    if e.get("stencil"):
        parts.append("stencil " + attachment_text(e["stencil"]))
    return f"render: {e['ops']} draws | " + " | ".join(parts)


def pass_bytes(e):
    if e["type"] == "blit":
        return e["pixels"] * 8
    return sum(attachment_bytes(w, p) for w, p in [(c, None) for c in e["colours"]] + [(e.get("depth", 0), "depth"),
                                                                                     (e.get("stencil", 0), "stencil")] if w)


def ms(x):
    return f"{x / 1e6:8.3f}"


def counted(s, frames):
    """What is known of these frames, and what is not: the same numbers as the report's first lines."""
    why = collections.Counter(w for f in frames for w in f["why"][:1])
    order = [f["order"] for f in frames if "order" in f]
    return dict(frames=len(frames), whole=sum(1 for f in frames if "parts" in f), not_whole=dict(why.most_common()),
                presented=sum(1 for f in frames if "client" in f), replaced=sum(1 for f in frames if f.get("replaced")),
                shown=sum(1 for f in frames if f.get("shown")), shown_at_zero=sum(1 for f in frames if f.get("shown") == 0),
                out_of_order_ms=[round(min(order) / 1e6, 3), round(max(order) / 1e6, 3)] if order else None)


def report(s, frames, title):
    n = counted(s, frames)
    print(f"\n== {title}: {n['frames']} frames, {n['whole']} whole (every boundary known, in order, nothing lost), "
          f"{n['frames'] - n['whole']} not; {n['presented']} presented, {n['replaced']} replaced in wsd, {n['shown']} shown, "
          f"{n['shown_at_zero']} called back without a time")
    for w, c in n["not_whole"].items():
        print(f"  not whole: {c:6d}  {w}")
    good = [f for f in frames if "parts" in f]
    if not good:
        return
    inner = [f for f in frames if "interval" in f]
    iv = [f["interval"] for f in inner]
    if iv:
        print(f"interval (guest stamp to guest stamp of one plane): mean {mean(iv) / 1e6:.3f} ms, {1e9 / mean(iv):.1f}/s")

    def row(name, values, share=None):
        values = [v for v in values if v is not None]
        if not values:
            return
        print(f"  {name:34s} mean {ms(mean(values))}  p10 {ms(pct(values, 10))}  p50 {ms(pct(values, 50))}  p90 {ms(pct(values, 90))}"
              f"  p99 {ms(pct(values, 99))} ms" + (f"  {100 * mean(values) / share:5.1f} %" if share else "") +
              (f"  ({len(values)})" if len(values) != len(good) else ""))

    wait = mean([f["wait"] for f in good])
    row("FENCE WAIT (as the host sees it)", [f["wait"] for f in good], wait)
    for i, p in enumerate(PARTS):
        row(p, [f["parts"][i] for f in good], wait)
    print("  beside it:")
    why = s.not_all_gpu(min(f["before"] for f in inner), max(f["client"] for f in inner)) if inner else "no interval"
    row("GPU work of the session in the wait", [f["gpu_in_wait"] for f in good], wait)
    row("GPU work of the session, interval", [f["gpu_busy"] for f in inner])
    if why is None:
        row("GPU idle of this session, interval", [f["interval"] - f["gpu_busy"] for f in inner])
        print("    (nothing of any of its queues, its uploads or wsd's ran; other programs' work is not seen)")
    else:
        row("not covered by this queue, interval", [f["interval"] - f["queue_busy"] for f in inner if "queue_busy" in f])
        print(f"    (GPU idle is not told: {why})")
    row("encode of the frame", [f.get("encode_frame") for f in good])
    row("of it, waiting for pipelines", [f.get("pipeline_frame") for f in good])
    row("ring decode", [f["decode"] for f in good])
    # (the proxy may see the fence published before the worker's own stamp of it: beside the parts, not one of them)
    row("worker awake to published", [f["retired"] - f["retire_woken"] for f in good])
    post = [f for f in good if "post" in f]
    if post:
        print("  after the fence:")
        for i, p in enumerate(POST):
            row(p, [f["post"][i] for f in post])
    per = lambda k: mean([f.get(k, 0) for f in good])
    print(f"  per frame: {mean([len(f['chunks']) for f in good if 'chunks' in f]):.1f} command buffers, {per('draws'):.0f} draws, "
          f"{per('commands'):.0f} commands, {per('maps'):.0f} maps, {per('updates'):.0f} updates, {per('targets'):.0f} target changes, "
          f"{per('flushes'):.1f} flushes")


def passes_report(s, frames):
    every = {d.passes for d in s.dxmt.values()}
    print(f"  encoders: recorded for every Nth frame, N = {', '.join(str(e) if e else 'none' for e in sorted(every)) or 'none'}")
    shapes = collections.defaultdict(list)
    looked = 0
    for f in frames:
        l = s.passes(f) if "queue" in f else None
        if l:
            looked += 1
            shapes[tuple((e["type"], e["index"], pass_text(e)) for e in l)].append(l)
    if not shapes:
        return
    skips = collections.Counter()
    for d in s.dxmt.values():
        for r in d.get("D_PASS_SKIP"):
            skips[SKIP.get(r.a, r.a)] += r.v[1] or 1
    untold = collections.Counter(e["times_why"] for l in shapes.values() for frame in l for e in frame if e.get("times_why"))
    for w, c in list(skips.items()) + list(untold.items()):
        print(f"    encoders without times: {c:6d}  {w}")
    # by the kinds and attachments alone (the draw counts vary): the commonest, and what each encoder took over all its frames
    loose = collections.defaultdict(list)
    for key, l in shapes.items():
        loose[tuple((t, re.sub(r"^\w+: \d+ (draws|ops)", t, text)) for t, _, text in key)] += l
    key, l = max(loose.items(), key=lambda x: len(x[1]))
    total = sum(pass_bytes(e) for e in l[0])
    print(f"  the commonest frame by its encoders ({len(l)} of {looked} recorded; {len(loose)} shapes), {len(key)} encoders, nominal "
          f"traffic {total / 1e6:.1f} MB (uncompressed; not a measurement):")
    for i, (_, text) in enumerate(key):
        es = [frame[i] for frame in l]
        stages = collections.defaultdict(list)
        for e in es:
            for name, a, b in e.get("times") or ():
                stages[name].append(b - a)
        t = ", ".join(f"{name} p50 {pct(v, 50) / 1e6:.3f} p90 {pct(v, 90) / 1e6:.3f} ms ({len(v)})" for name, v in stages.items())
        print(f"    {i + 1:3d} {text}  ops p50 {pct([e['ops'] for e in es], 50)}  ({pass_bytes(es[0]) / 1e6:.1f} MB)"
              + (f"  [GPU {t}]" if t else ""))
    busy = []
    for frame in l:
        u = Intervals([(a, b) for e in frame for _, a, b in e.get("times") or ()])
        if u.a:
            busy.append(u.inside(u.a[0], u.b[-1]))
    if busy:
        print(f"    all stages together (their union: stages overlap and are never added up): p50 {pct(busy, 50) / 1e6:.3f} ms")


def cadence(s, lo, hi, plane=None):
    """wsd alone, per plane: what its display link gave and what became of the frames it received."""
    out = []
    for w in s.wsd:
        rx_all = [r for r in w.get("W_RX") if lo <= r.t <= hi]
        for p in sorted({r.v[5] & 0xffffffff for r in rx_all}):
            if plane is not None and p != plane:
                continue
            rx = [r for r in rx_all if r.v[5] & 0xffffffff == p]
            window, ticks = rx[0].a & 0x3fffffff, [r for r in w.get("W_TICK") if lo <= r.t <= hi and r.v[3] == p]
            draws = [r for r in w.get("W_DRAW") if lo <= r.t <= hi and r.v[5] == p]
            new = [r for r in draws if not r.a >> 31 and r.v[4] != NONE]
            callbacks = [r for r in w.get("W_SHOWN") if lo <= r.t <= hi and r.v[3] == p]
            shown = {r.v[0]: r.v[1] for r in callbacks if r.v[1] and not r.a >> 31}
            wg = [r.v[2] - r.v[1] for r in w.get("W_GPU") if lo <= r.t <= hi and r.v[5] == p and r.v[2] > r.v[1]]
            waits = [r.v[3] - r.v[2] for r in new]
            lat = [shown[r.v[1]] - r.v[2] for r in new if r.v[1] in shown]
            links = [r.v[2] for r in ticks if r.v[2]]
            refresh = pct(links, 50) if links else 1e9 / 60
            times = sorted(shown.values())
            gaps = [b - a for a, b in zip(times, times[1:])]
            rate = lambda l: (len(l) - 1) / ((l[-1] - l[0]) / 1e9) if len(l) > 1 and l[-1] > l[0] else float("nan")
            states = collections.Counter(r.a >> 16 for r in ticks)
            d = dict(plane=p, window=window, region=rx[0].a >> 30 & 1, received=len(rx), received_per_s=rate([r.t for r in rx]),
                     replaced=sum(r.a >> 31 for r in rx), drawn=len(new), redrawn=sum(1 for r in draws if r.a >> 31),
                     no_drawable=sum(1 for r in draws if r.v[4] == NONE), shown=len(times), shown_per_s=rate(times),
                     zero_time=sum(1 for r in callbacks if not r.v[1]), redisplays_shown=sum(1 for r in callbacks if r.v[1] and r.a >> 31),
                     refresh_ms=refresh / 1e6, ticks=len(ticks), ticks_per_s=rate([r.t for r in ticks]),
                     tick_states=dict(empty=states[0], frame=states[1], hidden=states[2], again=states[3]),
                     shown_interval_ms={f"p{q}": pct(gaps, q) / 1e6 for q in (50, 95, 99)},
                     shown_intervals_in_refreshes=dict(sorted(collections.Counter(round(g / refresh) for g in gaps).items())),
                     next_drawable_ms={f"p{q}": pct(waits, q) / 1e6 for q in (50, 90, 99)}, gpu_ms={f"p{q}": pct(wg, q) / 1e6 for q in (50, 99)},
                     tick_to_shown_ms={f"p{q}": pct(lat, q) / 1e6 for q in (50, 90)})
            out.append(d)
            print(f"  plane {p} (window {window}{', overlay' if d['region'] else ''}): received {d['received']} ({d['received_per_s']:.2f}/s), "
                  f"replaced unshown {d['replaced']}, drawn {d['drawn']}, no drawable {d['no_drawable']}, SHOWN {d['shown']} "
                  f"({d['shown_per_s']:.2f}/s), called back without a time {d['zero_time']}; again: drawn {d['redrawn']}, shown {d['redisplays_shown']}")
            print(f"    display link: {d['ticks']} ticks ({d['ticks_per_s']:.2f}/s, refresh {d['refresh_ms']:.3f} ms), with a frame "
                  f"{states[1]}, empty {states[0]}, hidden {states[2]}, again {states[3]}")
            print(f"    shown intervals: p50 {d['shown_interval_ms']['p50']:.3f} p95 {d['shown_interval_ms']['p95']:.3f} p99 "
                  f"{d['shown_interval_ms']['p99']:.3f} ms; in refreshes: "
                  + ", ".join(f"{k}: {v}" for k, v in d["shown_intervals_in_refreshes"].items()))
            print(f"    nextDrawable p50 {d['next_drawable_ms']['p50']:.3f} p99 {d['next_drawable_ms']['p99']:.3f} ms; wsd GPU p50 "
                  f"{d['gpu_ms']['p50']:.3f} p99 {d['gpu_ms']['p99']:.3f} ms; tick to shown p50 {d['tick_to_shown_ms']['p50']:.3f} p90 "
                  f"{d['tick_to_shown_ms']['p90']:.3f} ms")
    if not out:
        print("  no frames received" + (f" on plane {plane}" if plane is not None else ""))
    return out


def write_csv(path, frames):
    with open(path, "w", newline="") as out:
        w = csv.writer(out)
        w.writerow(["pid", "context", "queue", "chunk", "frame", "fence_value", "plane", "window", "serial", "export", "whole", "why",
                    "submit", "before"] + MARKS + ["wait"] + [f"part: {p}" for p in PARTS] +
                   ["interval", "gpu_busy", "queue_busy", "gpu_in_wait", "rx", "tick", "drawable", "wsd_commit", "wgpu_start", "wgpu_end",
                    "shown", "replaced"])
        for f in frames:
            w.writerow([f["npt"].pid] + [f.get(k, "") for k in ("context", "queue", "chunk", "id", "value", "plane", "window", "serial", "export")]
                       + [int("parts" in f), "; ".join(f["why"])] + [f.get(k, "") for k in ["submit", "before"] + MARKS + ["wait"]]
                       + f.get("parts", [""] * len(PARTS))
                       + [f.get(k, "") for k in ("interval", "gpu_busy", "queue_busy", "gpu_in_wait", "rx", "tick", "drawable", "wsd_commit",
                                                 "wgpu_start", "wgpu_end", "shown")] + [int(f.get("replaced", 0))])


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("folder")
    p.add_argument("--from", dest="lo", type=int, default=0)
    p.add_argument("--to", dest="hi", type=int, default=2**63)
    p.add_argument("--modes", help="a log with pass_costs' MODE lines: one report per mode")
    p.add_argument("--plane", type=int, help="only the frames of this plane of wsd's")
    p.add_argument("--frames", type=int, default=0, help="print that many frames one by one")
    p.add_argument("--passes", action="store_true", help="the encoder list of the commonest frame")
    p.add_argument("--cadence", action="store_true", help="wsd's ticks, drawables and shown frames, per plane")
    p.add_argument("--csv", help="the frames reported, one per line")
    p.add_argument("--json", help="the counts, per report")
    a = p.parse_args()
    s = Session(a.folder, 0 if a.modes else a.lo, 2**64 if a.modes else a.hi)
    lost = collections.Counter()
    for f in s.files:
        lost[f.role] += f.lost
    print("LOST records: " + ", ".join(f"{role} {n}" for role, n in sorted(lost.items())) +
          (f"; presentations not told: {dict(s.unseen)}" if s.unseen else ""))
    for f in s.files:
        print(f.says())
    try:
        with open(os.path.join(a.folder, "otl-session"), "rb") as f:
            _, _, limit, used, files, refused = struct.unpack("<4sIQQII", f.read(32))
        print(f"session budget: {used >> 20} of {limit >> 20} MiB taken by {files} recorders" + (f", {refused} refused" if refused else ""))
    except (OSError, struct.error):
        print("session budget: not recorded")
    cuts = []
    # a mode's times are QueryPerformanceCounter's: the continuous clock, which counts sleep; uptime does not
    off = s.files[0].continuous - s.files[0].uptime
    if a.modes:
        for line in open(a.modes, errors="replace"):
            m = re.search(r"MODE (\S+) frames=(\d+) begin=(\d+) end=(\d+)(.*)", line)
            if m:
                cuts.append((f"{m[1]} ({m[2]} frames,{m[5]})", int(m[3]) - off, int(m[4]) - off))
    else:
        cuts.append(("all" if not a.lo and a.hi == 2**63 else f"{a.lo} to {a.hi}", a.lo, a.hi))
    told, written = [], []
    for title, lo, hi in cuts:
        frames = [f for f in s.frames if lo <= f["signal_end"] <= hi and (a.plane is None or f.get("plane") == a.plane)]
        written += frames
        told.append(dict(title=title, lo=lo, hi=hi) | counted(s, frames))
        if s.frames:
            report(s, frames, title)
            if a.passes:
                passes_report(s, frames)
            if a.frames:
                print("  " + " ".join(f"{h[:9]:>9s}" for h in ["value", "wait"] + PARTS))
                for f in [f for f in frames if "parts" in f][: a.frames]:
                    print("  " + " ".join([f"{f['value']:9d}", f"{f['wait'] / 1e6:9.3f}"] + [f"{x / 1e6:9.3f}" for x in f["parts"]]))
        if a.cadence and s.wsd:
            print(f"\n-- cadence: {title}")
            told[-1]["cadence"] = cadence(s, lo, hi, a.plane)
    if a.csv:
        write_csv(a.csv, written)
    if a.json:
        files = [dict(file=os.path.basename(f.path), role=f.role, pid=f.pid, records=f.kept, lost=f.lost, lossy_intervals=len(f.lossy),
                      end=f.end, passes=f.passes) for f in s.files]
        with open(a.json, "w") as out:
            json.dump(dict(lost=dict(lost), not_told=dict(s.unseen), files=files, reports=told), out, indent=1)


if __name__ == "__main__":
    main()
