#!/usr/bin/env python3
"""Reads a host timeline (wsd/otl.h) and says where each frame's time went.

Usage: otl.py <session folder> [--from NS] [--to NS] [--modes run.log] [--frames N] [--passes] [--csv out.csv] [--cadence]

The session folder holds otl-npt-*.bin and otl-dxmt-*.bin (one render server worker), otl-vtest-*.bin and otl-wsd-*.bin.
A frame is one presentation signal: the ring's CopyResource into a shared image, then its Signal.

How it is joined:
  render ring -> DXMT      the fence's pointer and value (N_SIGNAL, D_SIGNAL, D_SEOC), then DXMT's chunk
  DXMT -> event thread     the Metal event and value (D_NOTIFY); the event handle of SetEventOnCompletion (N_PAIR), which
                           gives the ring and fence id (N_FENCE, N_RETIRE, V_RETIRE)
  render ring -> wsd       the memory of the shared image (N_EXPORT, W_ATTACH) and the order in time: an image is copied
                           to, presented, and copied to again only once it was released
  inside wsd               window and presentation serial
All times are host uptime nanoseconds. Standard library only.
"""
import argparse, bisect, collections, csv, glob, os, re, struct, sys

K = dict(THREAD=1, SUMMARY=2, HIST=3, LOST=4, N_EXPORT=16, N_COPY=17, N_SIGNAL=18, N_COUNTS=19, N_FENCE=20, N_PAIR=21, N_RETIRE=22,
         N_FLUSH=23, V_RETIRE=24, D_READY=32, D_ENCODE=33, D_DONE=34, D_SIGNAL=35, D_SEOC=36, D_NOTIFY=37, D_PIPELINE=38,
         D_INIT=39, D_INIT_DONE=40, D_PASS=41, D_PASS_DS=42, D_BLIT=43, D_COMPUTE=44, D_OPS=45, D_PASS_TIME=46, W_ATTACH=64,
         W_RX=65, W_TICK=66, W_DRAW=67, W_GPU=68, W_SHOWN=69, W_RELEASE=70)
NAME = {v: k for k, v in K.items()}
REC = struct.Struct("<QHHI6Q")
Rec = collections.namedtuple("Rec", "t kind thr a v")
LOAD = {0: "dontcare", 1: "load", 2: "clear"}
STORE = {0: "dontcare", 1: "store", 2: "resolve", 3: "store+resolve", 4: "unknown"}
FORMAT = {10: ("R8", 1), 13: ("R8ui", 1), 25: ("R16F", 2), 30: ("RG8", 2), 53: ("R32ui", 4), 55: ("R32F", 4), 65: ("RG16F", 4),
          70: ("RGBA8", 4), 71: ("RGBA8s", 4), 80: ("BGRA8", 4), 81: ("BGRA8s", 4), 90: ("RGB10A2", 4), 92: ("RG11B10F", 4),
          105: ("RG32F", 8), 110: ("RGBA16", 8), 115: ("RGBA16F", 8), 125: ("RGBA32F", 16), 250: ("D16", 2), 252: ("D32F", 4),
          253: ("S8", 1), 255: ("D24S8", 4), 260: ("D32FS8", 8), 261: ("X32S8", 8)}


class File:
    def __init__(self, path):
        data = open(path, "rb").read()
        magic, version, self.pid, _ = struct.unpack_from("<4sIII", data, 0)
        if magic != b"OTL1" or version != 1:
            raise SystemExit(f"{path}: not a timeline of version 1")
        self.role = data[16:32].split(b"\0")[0].decode()
        self.uptime, self.wall_us, self.continuous = struct.unpack_from("<QQQ", data, 32)
        self.path, self.lost, self.by, self.windows, self.hist = path, 0, collections.defaultdict(list), [], {}
        for off in range(64, len(data) - 63, 64):  # whole records only: the last may be cut
            t, kind, thr, a, *v = REC.unpack_from(data, off)
            if kind == K["SUMMARY"]:
                self.windows.append((a, v))
                self.lost = max(self.lost, v[4])
            elif kind == K["LOST"]:
                self.lost = max(self.lost, v[0])
            elif kind == K["HIST"]:
                window = len(self.windows)
                counts = struct.unpack("<12I", struct.pack("<6Q", *v))
                h = self.hist.setdefault((window, a & 0xff), [0] * 36)
                h[(a >> 8) * 12:(a >> 8) * 12 + 12] = counts
            else:
                self.by[kind].append(Rec(t, kind, thr, a, v))
        for l in self.by.values():
            l.sort(key=lambda r: r.t)

    def get(self, kind):
        return self.by.get(K[kind], [])


def pct(values, p):
    if not values:
        return float("nan")
    s = sorted(values)
    return s[min(len(s) - 1, int(p / 100 * len(s)))]


def mean(values):
    return sum(values) / len(values) if values else float("nan")


def union(intervals, lo, hi):
    """The length of the union of the intervals inside [lo, hi]."""
    total, at = 0, lo
    for a, b in sorted(intervals):
        a, b = max(a, at), min(b, hi)
        if b > a:
            total += b - a
            at = b
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


# The parts of the fence wait, in order: each ends where the next begins.
PARTS = ["replay tail", "encode queue", "encode", "pipeline wait", "queue to GPU start", "GPU execution", "GPU end to notify",
         "notify to retire", "retire to vtest", "vtest to guest wake"]
POST = ["to wsd", "to tick", "drawable wait", "tick to commit", "commit to GPU end", "GPU end to shown", "client to shown"]


class Session:
    def __init__(self, folder):
        paths = sorted(glob.glob(os.path.join(folder, "otl-*.bin")))
        if not paths:
            raise SystemExit(f"{folder}: no otl-*.bin")
        self.files = [File(p) for p in paths]
        self.wsd = next((f for f in self.files if f.role == "wsd"), None)
        self.vtest = next((f for f in self.files if f.role == "vtest"), None)
        # the worker that presents: the one whose ring signalled most
        workers = [f for f in self.files if f.role == "npt"]
        self.npt = max(workers, key=lambda f: len(f.get("N_SIGNAL")), default=None)
        self.dxmt = next((f for f in self.files if f.role == "dxmt" and self.npt and f.pid == self.npt.pid), None)
        self.frames = []
        if self.npt and self.dxmt:
            self.join()

    def join(self):
        n, d = self.npt, self.dxmt
        exports = collections.defaultdict(list)  # pointer -> [(t, identity, size)]
        for r in n.get("N_EXPORT"):
            exports[r.v[0]].append((r.t, r.v[1], r.v[2]))
        counts = {(r.thr, r.t): r for r in n.get("N_COUNTS")}
        copies = collections.defaultdict(list)
        for r in n.get("N_COPY"):
            if r.v[1] in exports:
                copies[r.thr].append(r)
        copy_t = {thr: [c.t for c in l] for thr, l in copies.items()}
        d_signal = {(r.v[1], r.v[2], r.v[4]): r for r in d.get("D_SIGNAL")}
        self.d_signal_any = {(r.v[1], r.v[2]): r for r in d.get("D_SIGNAL")}
        seoc = {(r.v[0], r.v[1]): r for r in d.get("D_SEOC")}
        pairs = collections.defaultdict(list)
        for r in n.get("N_PAIR"):
            pairs[r.v[1]].append(r)
        pair_t = {h: [r.t for r in l] for h, l in pairs.items()}
        fence = {(r.a, r.v[0]): r for r in n.get("N_FENCE")}
        retire = {(r.a, r.v[0]): r for r in n.get("N_RETIRE")}
        vret = {(r.a, r.v[0]): r for r in self.vtest.get("V_RETIRE")} if self.vtest else {}
        notify = {(r.v[0], r.v[1]): r for r in d.get("D_NOTIFY")}
        ready = {(r.v[0], r.v[1]): r for r in d.get("D_READY")}
        encode = {(r.v[5], r.v[0]): r for r in d.get("D_ENCODE")}
        done = {(r.v[5], r.v[0]): r for r in d.get("D_DONE")}
        gpu = collections.defaultdict(list)
        for (q, c), r in sorted(done.items()):
            if r.v[2] > r.v[1]:
                gpu[q].append((r.v[1], r.v[2], c))
        for q in gpu:
            gpu[q].sort()
        gpu_start = {q: [g[0] for g in l] for q, l in gpu.items()}
        self.gpu = gpu
        last_chunk = {}
        for s in n.get("N_SIGNAL"):
            ts = copy_t.get(s.thr)
            if not ts:
                continue
            i = bisect.bisect_right(ts, s.v[0]) - 1
            if i < 0 or s.v[0] - ts[i] > 20_000_000:
                continue  # not a presentation's signal: no copy into a shared image just before it
            c = copies[s.thr][i]
            ds = self.d_signal_any.get((s.v[1], s.v[2]))
            if not ds:
                continue
            q, chunk = ds.v[4], ds.v[0]
            ex = [e for e in exports[c.v[1]] if e[0] <= c.t]
            f = dict(context=s.a, thread=s.thr, copy=c.v[0], copy_end=c.t, signal=s.v[0], signal_end=s.t, fence=s.v[1], value=s.v[2],
                     decode=s.v[3], first=s.v[4], commands=s.v[5], chunk=chunk, queue=q, identity=ex[-1][1] if ex else 0,
                     size=ex[-1][2] if ex else 0)
            cr = counts.get((s.thr, s.t))
            if cr:
                f.update(draws=cr.v[0], maps=cr.v[1], updates=cr.v[3], flushes=cr.v[4], copies=cr.v[5] >> 32,
                         targets=cr.v[5] & 0xffffffff)
            for name, table in (("ready", ready), ("enc", encode), ("done", done)):
                r = table.get((q, chunk))
                if r is None:
                    break
                f[name] = r
            else:
                first = last_chunk.get(q, chunk - 1) + 1
                f["chunks"] = list(range(first, chunk + 1)) if chunk - first < 64 else [chunk]
                last_chunk[q] = chunk
                so = seoc.get((f["fence"], f["value"]))
                if so:
                    f["seoc"] = so.t
                    l = pair_t.get(so.v[2], [])
                    if l:
                        j = min(range(max(0, bisect.bisect(l, so.t) - 2), min(len(l), bisect.bisect(l, so.t) + 2)),
                                key=lambda j: abs(l[j] - so.t))
                        p = pairs[so.v[2]][j]
                        key = (p.a, p.v[0])
                        if key in fence:
                            f["submit"] = fence[key].t
                        if key in retire:
                            f["retire"] = retire[key].t
                        if key in vret:
                            f["vtest"] = vret[key].t
                nt = notify.get((ds.v[3], f["value"]))
                if nt:
                    f["notify"] = nt.t
                self.frames.append(f)
        # wsd
        if self.wsd:
            attach = collections.defaultdict(list)
            for r in self.wsd.get("W_ATTACH"):
                attach[r.a].append((r.t, r.v[0]))
            by_image = collections.defaultdict(list)
            for f in self.frames:
                by_image[f["identity"]].append(f)
            times = {i: [f["signal_end"] for f in l] for i, l in by_image.items()}
            draw = {(r.a & 0x3fffffff, r.v[1]): r for r in self.wsd.get("W_DRAW") if not r.a >> 31 and r.v[4] != 2**64 - 1}
            wgpu = {(r.a & 0x3fffffff, r.v[0]): r for r in self.wsd.get("W_GPU") if not r.a >> 31}
            shown = {(r.a & 0x3fffffff, r.v[0]): r for r in self.wsd.get("W_SHOWN") if not r.a >> 31}
            replaced = {(r.a & 0x3fffffff, r.v[4]) for r in self.wsd.get("W_RX") if r.a >> 31}
            for r in self.wsd.get("W_RX"):
                a = [i for t, i in attach.get(r.v[0], []) if t <= r.t]
                l = by_image.get(a[-1]) if a else None
                if not l:
                    continue
                i = bisect.bisect_right(times[a[-1]], r.v[2]) - 1
                if i < 0 or "client" in l[i]:
                    continue
                f, key = l[i], (r.a & 0x3fffffff, r.v[1])
                f.update(client=r.v[2], rx=r.v[3], serial=r.v[1], replaced=key in replaced)
                if key in draw:
                    f.update(tick=draw[key].v[2], drawable=draw[key].v[3], committed=draw[key].t)
                if key in wgpu:
                    f.update(wgpu_start=wgpu[key].v[1], wgpu_end=wgpu[key].v[2])
                if key in shown:
                    f.update(shown=shown[key].v[1])
        prev = None
        for f in self.frames:
            if "client" not in f or "submit" not in f:
                continue
            start = max(f["submit"], prev["client"]) if prev else f["submit"]
            prev = f
            end = f["client"]
            enc, dn = f["enc"], f["done"]
            waited = min(enc.v[4], max(0, enc.t - enc.v[1]))
            marks = [f["ready"].t, enc.v[1], enc.t - waited, enc.t, dn.v[1], dn.v[2], f.get("notify", dn.v[2])]
            marks += [f.get("retire", marks[-1])]
            marks += [f.get("vtest", marks[-1]), end]
            at, parts = start, []
            for m in marks:  # the parts in order; what was over before the stopwatch began counts nothing
                m = min(max(m, at), end)
                parts.append(m - at)
                at = m
            f.update(start=start, wait=end - start, parts=parts, prev_client=None)
            q, l = f["queue"], self.gpu[f["queue"]]
            i = bisect.bisect_left(gpu_start[q], start - 500_000_000)
            j = bisect.bisect_left(gpu_start[q], end)
            f["gpu_in_wait"] = union([(a, b) for a, b, _ in l[i:j]], start, end)
            mine = set(f["chunks"])
            own = [(a, b) for a, b, c in l[i:j] if c in mine]
            f["gpu_frame"] = union(own, 0, 2**63)
            f["encode_frame"] = sum(encode[(q, c)].t - encode[(q, c)].v[1] for c in f["chunks"] if (q, c) in encode)
            f["pipeline_frame"] = sum(encode[(q, c)].v[4] for c in f["chunks"] if (q, c) in encode)
            if "shown" in f and "committed" in f:
                f["post"] = [f["rx"] - end, f["tick"] - f["rx"], f["drawable"] - f["tick"], f["committed"] - f["drawable"],
                             f.get("wgpu_end", f["committed"]) - f["committed"],
                             f["shown"] - f.get("wgpu_end", f["committed"]) if f["shown"] else None,
                             f["shown"] - end if f["shown"] else None]
        # between two frames: the time on the clock and how much of it the GPU was running anything of this queue (start to
        # end of one command buffer also counts the neighbours it overlaps with, so their sum says nothing)
        clients = [f for f in self.frames if "client" in f and "parts" in f]
        for a, b in zip(clients, clients[1:]):
            b["interval"] = b["client"] - a["client"]
            l, st = self.gpu[b["queue"]], gpu_start[b["queue"]]
            i, j = bisect.bisect_left(st, a["client"] - 500_000_000), bisect.bisect_left(st, b["client"])
            b["gpu_busy"] = union([(x, y) for x, y, _ in l[i:j]], a["client"], b["client"])
            b["gpu_gap"] = b["interval"] - b["gpu_busy"]

    def passes(self, f):
        """The encoder list of a frame, as Metal got it."""
        out = []
        kinds = ("D_PASS", "D_PASS_DS", "D_BLIT", "D_COMPUTE", "D_OPS", "D_PASS_TIME")
        if not hasattr(self, "_passes"):
            self._passes = collections.defaultdict(list)
            for k in kinds:
                for r in self.dxmt.get(k):
                    self._passes[r.v[0]].append(r)
        for c in f["chunks"]:
            by = {}
            for r in self._passes.get(c, []):
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
                    e["times"] = r.v[1:5]
            out += [by[i] for i in sorted(by) if "type" in by[i]]
        return out


def pass_text(e):
    if e["type"] != "render":
        return f"{e['type']}: {e['ops']} ops" + (f", {e['pixels']} px copied" if e["pixels"] else "")
    parts = [attachment_text(w) for w in e["colours"]]
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


def report(s, frames, title):
    good = [f for f in frames if "parts" in f]
    print(f"\n== {title}: {len(frames)} presented frames, {len(good)} joined end to end"
          + (f", {sum(1 for f in good if f.get('replaced'))} replaced in wsd, "
             f"{sum(1 for f in good if f.get('shown'))} shown" if good else ""))
    if not good:
        return
    inner = [f for f in good[1:] if "interval" in f]  # the first one's interval began before the cut
    iv = [f["interval"] for f in inner]
    if iv:
        print(f"interval (post-fence stamp to post-fence stamp): mean {mean(iv) / 1e6:.3f} ms, {1e9 / mean(iv):.1f}/s")

    def row(name, values, share=None):
        values = [v for v in values if v is not None]
        print(f"  {name:22s} mean {ms(mean(values))}  p10 {ms(pct(values, 10))}  p50 {ms(pct(values, 50))}  p90 {ms(pct(values, 90))}"
              f"  p99 {ms(pct(values, 99))} ms" + (f"  {100 * mean(values) / share:5.1f} %" if share else ""))

    wait = mean([f["wait"] for f in good])
    row("FENCE WAIT", [f["wait"] for f in good], wait)
    for i, p in enumerate(PARTS):
        row(p, [f["parts"][i] for f in good], wait)
    print("  beside it:")
    row("GPU busy in the wait", [f["gpu_in_wait"] for f in good], wait)
    row("GPU start to end", [f["gpu_frame"] for f in good])
    row("GPU busy per interval", [f["gpu_busy"] for f in inner])
    row("GPU idle per interval", [f["gpu_gap"] for f in inner])
    row("encode of the frame", [f["encode_frame"] for f in good])
    row("pipelines of the frame", [f["pipeline_frame"] for f in good])
    row("ring decode", [f["decode"] for f in good])
    post = [f for f in good if "post" in f]
    if post:
        print("  after the fence:")
        for i, p in enumerate(POST):
            row(p, [f["post"][i] for f in post])
    print(f"  per frame: {mean([len(f['chunks']) for f in good]):.1f} command buffers, "
          f"{mean([f.get('draws', 0) for f in good]):.0f} draws, {mean([f['commands'] for f in good]):.0f} commands, "
          f"{mean([f.get('maps', 0) for f in good]):.0f} maps, {mean([f.get('updates', 0) for f in good]):.0f} updates, "
          f"{mean([f.get('targets', 0) for f in good]):.0f} target changes, {mean([f.get('flushes', 0) for f in good]):.1f} flushes")


def passes_report(s, frames):
    good = [f for f in frames if "parts" in f]
    if not good:
        return
    texts = collections.Counter()
    example = {}
    for f in good[:: max(1, len(good) // 200)]:
        key = tuple((e["type"], pass_text(e)) for e in s.passes(f))
        texts[key] += 1
        example[key] = f
    key, n = texts.most_common(1)[0]
    l = s.passes(example[key])
    total = sum(pass_bytes(e) for e in l)
    print(f"  passes of the commonest frame ({n} of {sum(texts.values())} looked at; {len(texts)} shapes), nominal traffic "
          f"{total / 1e6:.1f} MB:")
    for e in l:
        t = ""
        if e.get("times"):
            a = e["times"]
            t = f"  [GPU vertex {max(0, a[1] - a[0]) / 1e6:.3f} fragment {max(0, a[3] - a[2]) / 1e6:.3f} ms]"
        print(f"    {e['index']:3d} {pass_text(e)}  ({pass_bytes(e) / 1e6:.1f} MB){t}")


def cadence(s, lo, hi):
    """wsd alone: what the display link gave and what became of the frames."""
    w = s.wsd
    inside = lambda r: lo <= r.t <= hi
    rx = [r for r in w.get("W_RX") if inside(r)]
    if not rx:
        print("no frames received")
        return
    lo, hi = max(lo, rx[0].t), min(hi, rx[-1].t)
    ticks = [r for r in w.get("W_TICK") if lo <= r.t <= hi]
    states = collections.Counter(r.a >> 16 for r in ticks)
    gaps = [b.t - a.t for a, b in zip(ticks, ticks[1:])]
    links = [b.v[0] - a.v[0] for a, b in zip(ticks, ticks[1:])]
    draws = [r for r in w.get("W_DRAW") if lo <= r.t <= hi]
    waits = [r.v[3] - r.v[2] for r in draws]
    shown = {(r.a, r.v[0]): r.v[1] for r in w.get("W_SHOWN")}
    cb = [r for r in w.get("W_SHOWN") if lo <= r.t <= hi]
    secs = (hi - lo) / 1e9
    print(f"  received {len(rx)} ({len(rx) / secs:.2f}/s), replaced unshown {sum(r.a >> 31 for r in rx)}, drawn {len(draws)}, "
          f"no drawable {sum(1 for r in draws if r.v[4] == 2**64 - 1)}, shown {sum(1 for r in cb if r.v[1])}, "
          f"zero-time callbacks {sum(1 for r in cb if not r.v[1])}")
    print(f"  display link: {len(ticks)} ticks ({len(ticks) / secs:.2f}/s), with a frame {states[1]}, empty {states[0]}, hidden "
          f"{states[2]}, again {states[3]}; between callbacks p50 {pct(gaps, 50) / 1e6:.3f} p99 {pct(gaps, 99) / 1e6:.3f} ms; between "
          f"link times p50 {pct(links, 50) / 1e6:.3f} max {max(links, default=0) / 1e6:.3f} ms")
    print(f"  nextDrawable: p50 {pct(waits, 50) / 1e6:.3f} p90 {pct(waits, 90) / 1e6:.3f} p99 {pct(waits, 99) / 1e6:.3f} max "
          f"{max(waits, default=0) / 1e6:.3f} ms")
    by = {(r.a, r.v[1]): r for r in draws}
    lat = [(shown[k] - r.v[2]) for k, r in by.items() if shown.get(k)]
    wg = [r.v[2] - r.v[1] for r in w.get("W_GPU") if lo <= r.t <= hi and r.v[2] > r.v[1]]
    print(f"  wsd GPU: p50 {pct(wg, 50) / 1e6:.3f} p99 {pct(wg, 99) / 1e6:.3f} ms; tick to shown: p50 {pct(lat, 50) / 1e6:.3f} p90 "
          f"{pct(lat, 90) / 1e6:.3f} ms")
    sh = sorted(v for v in (r.v[1] for r in cb) if v)
    refresh = collections.Counter(round((b - a) / (1e9 / 60)) for a, b in zip(sh, sh[1:]))
    print("  shown intervals in refreshes of 1/60 s: " + ", ".join(f"{k}: {v}" for k, v in sorted(refresh.items())))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("folder")
    p.add_argument("--from", dest="lo", type=int, default=0)
    p.add_argument("--to", dest="hi", type=int, default=2**63)
    p.add_argument("--modes", help="a log with pass_costs' MODE lines: one report per mode")
    p.add_argument("--frames", type=int, default=0, help="print that many frames one by one")
    p.add_argument("--passes", action="store_true", help="the encoder list of the commonest frame")
    p.add_argument("--cadence", action="store_true", help="wsd's ticks, drawables and shown frames")
    p.add_argument("--csv")
    a = p.parse_args()
    s = Session(a.folder)
    for f in s.files:
        n = sum(len(l) for l in f.by.values())
        print(f"{os.path.basename(f.path)}: {f.role} pid {f.pid}, {n} records, {f.lost} lost, {len(f.windows)} windows")
    cuts = []
    # a mode's times are QueryPerformanceCounter's: the continuous clock, which counts sleep; uptime does not
    off = s.files[0].continuous - s.files[0].uptime
    if a.modes:
        for line in open(a.modes, errors="replace"):
            m = re.search(r"MODE (\S+) frames=(\d+) begin=(\d+) end=(\d+)(.*)", line)
            if m:
                cuts.append((f"{m[1]} ({m[2]} frames,{m[5]})", int(m[3]) - off, int(m[4]) - off))
    else:
        cuts.append(("all", a.lo, a.hi))
    for title, lo, hi in cuts:
        if s.frames:
            frames = [f for f in s.frames if lo <= f["signal_end"] <= hi]
            report(s, frames, title)
            if a.passes:
                passes_report(s, frames)
            if a.frames:
                print("  " + " ".join(f"{h[:9]:>9s}" for h in ["value", "wait"] + PARTS))
                for f in [f for f in frames if "parts" in f][: a.frames]:
                    print("  " + " ".join([f"{f['value']:9d}", f"{f['wait'] / 1e6:9.3f}"] + [f"{x / 1e6:9.3f}" for x in f["parts"]]))
        if a.cadence and s.wsd:
            print(f"\n-- cadence: {title}")
            cadence(s, lo, hi)
    if a.csv:
        with open(a.csv, "w", newline="") as out:
            w = csv.writer(out)
            w.writerow(["value", "chunk", "start", "client", "wait"] + PARTS + ["gpu_frame", "gpu_in_wait"] + POST + ["replaced"])
            for f in s.frames:
                if "parts" in f:
                    w.writerow([f["value"], f["chunk"], f["start"], f["client"], f["wait"]] + f["parts"]
                               + [f["gpu_frame"], f["gpu_in_wait"]] + f.get("post", [""] * len(POST)) + [int(f.get("replaced", 0))])


if __name__ == "__main__":
    main()
