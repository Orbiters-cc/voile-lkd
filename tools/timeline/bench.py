#!/usr/bin/env python3
"""One benchmark run of VRChat on a Mac through obelisk-cli (docs/mac-performance.md of Orbiters-N4N0, the procedure).

This is tools/mac-bench/bench.py of Orbiters-N4N0 (as of 4bf9ecb9) with two things more, to be taken over there: the game is brought
to the front (below) and every window's cuts are stamped on the trace's clock (`from_uptime_ns`, `to_uptime_ns`).

Why to the front: macOS gives the keyboard to no program that the app in front neither started nor yields to, so the window of a
game started from a terminal or a service is shown, full screen, over an app that stays the active one (2026-11-23: nine windows
of three starts, the window server at `app_active=0` and level 0 throughout, Safari in front of it all along). Once the local player
arrived, and whenever something else is in front before the first window, the app bundle of this session's own window server is
opened with `open`, as a click on its Dock icon does. What was in front is told by name.

Starts VRChat with `obelisk-cli steam play 438100 [--render-percent N] -- <arguments> <link>` in a private instance of a
fixed world, waits until the local player is in that very instance, as this start's own VRChat log says it (the log whose
command line holds the link: a fallback destination is no arrival), and loading and shader compilation have settled (a
start that does not settle is not scored), then records equal timed windows with nobody touching the game, quits by
session (never forced) and writes one results file, whatever happened (the outcome says what). Nothing here sends input to
the game, changes a setting or injects anything: it reads the engine's log and session records, VRChat's log, `ps`, `ioreg`,
`pmset` and `lsappinfo`.

The session is the one the program started here names (its `starting` event, obelisk-cli 0.1.10, before the game runs), and
the only one ever asked to quit: what the library's records say is current may be somebody else's. Its own record says how it
ended. A run whose session did not end, or that may have started one it was not told the name of, exits with 5, and session.sh
stops there.

exit status: 0 measured, 2 did not start, 3 did not arrive, 4 did not settle or ended before a window, 5 its session did not
end (whatever else happened).

The three frame counters are kept apart (R3), per swapchain generation (a new one at each `guest swapchain: created`):
  - guest Present: Neptune's nptunix line, `<n> presents (<m> shown events), last 60: interval avg X ms, fence wait avg
    Y ms` (X: time between the game's submissions; Y: how long each waited for the host to finish it);
  - worker shown events: the `(<m> shown events)` of the same line (counts zero-time callbacks too);
  - wsd's positive Metal presentation: the Metal HUD's per-frame intervals (`metal-HUD:` lines, raw).
Rates are counted: the presents between two lines of the same generation divided by the time between those two lines
(read times; lines read together are one reading, the last of them), the line before a window included as its base, never a
whole window's length. The HUD's lines carry their own times and process: only the owned window server's count.

A window is scored only when all of it was seen: from its start to its end, with no gap longer than GAP between two looks,
the session lived, the screen was unlocked, VRChat's own window server was the frontmost app and the local player stayed in
the destination; its submissions were read over at least COVERED of it, inside it, with no two readings further apart than GAP,
and its shown frames fill as much of it. Everything that decides it is kept with its times (`observed`), to score it again.
Otherwise it is kept with `valid: false` and why. `--allow-locked` scores production alone behind a locked screen (and says so in every window).

usage: bench.py --link 'vrchat://launch?...' [--percent N] [--arg A]... [--warm 90] [--window 60] [--windows 3]
                [--cli PATH] [--allow-locked] --out results.json
"""
import argparse, datetime, glob, json, os, re, subprocess, sys, threading, time, urllib.parse

HOME = os.path.expanduser("~")
ENGINE_LOG = f"{HOME}/Library/Logs/Obelisk/Steam/wine-438100.log"
LIBRARY = f"{HOME}/Library/Application Support/cc.orbiters.obelisk-cli"
VRC_LOGS = f"{LIBRARY}/Prefixes/steam-438100-windows-linux/prefix/drive_c/users/crossover/AppData/LocalLow/VRChat/VRChat"

NPT = re.compile(r"neptune unixlib wsi \(wsd\): (\d+) presents \((\d+) shown events\), last 60: interval avg ([\d.]+) ms, fence wait avg ([\d.]+) ms")
HELD = re.compile(r"wsd: window \d+ overlay: frame held ([\d.]+) ms")
HUD = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+) \S*?\[(\d+):\d+\] metal-HUD: (.*)$")
SWAP = re.compile(r"guest swapchain: created (\d+)x(\d+) fmt=(\d+) buffers=(\d+)")
RENDER = re.compile(r"wsd: render percent: requested (\S+), applied (\d+).*\(desktop (\d+)x(\d+) px\)")
STOP = re.compile(r"lkd: sig: |lkd: ptrace: ")
START_DEADLINE = 900   # s for the engine to say the game runs (it may download first)
ARRIVE_DEADLINE = 600  # s from running to the local player's arrival
CLOSE_DEADLINE = 120   # s from the quit to the session's end
SETTLE_DEADLINE = 180  # s after the warm time for the frames to settle
GAP = 5.0              # s between two looks (or two shown frames' lines) at most in a scored window
COVERED = 0.9          # of a scored window its counted submissions and its shown frames must fill
RECORDS = f"{LIBRARY}/SteamSessions"


def now():
    return time.monotonic()


def run(cmd, timeout=10):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception as e:  # noqa: BLE001 - recorded, never fatal
        return f"<{cmd[0]}: {e}>"


def screen_locked():
    """True / False from the console's own state (ioreg IOConsoleLocked), None when it cannot be told."""
    out = run(["/usr/sbin/ioreg", "-n", "Root", "-d1", "-a"])
    m = re.search(r"<key>IOConsoleLocked</key>\s*<(true|false)/>", out)
    return None if not m else m.group(1) == "true"


def frontmost():
    """The frontmost app's process (lsappinfo), or None."""
    asn = run(["/usr/bin/lsappinfo", "front"]).strip()
    return front_pid(run(["/usr/bin/lsappinfo", "info", "-only", "pid", asn]) if asn else "")


def front_name():
    """The frontmost app's name as macOS tells it, for the record (no path, no document)."""
    asn = run(["/usr/bin/lsappinfo", "front"]).strip()
    m = re.match(r'\s*"([^"\n]{1,80})"', run(["/usr/bin/lsappinfo", "info", asn])) if asn else None
    return m.group(1) if m else None


def bundle_of(path):
    """The app bundle a program runs from (`…/VRChat.app/Contents/MacOS/wsd`), or None."""
    m = re.match(r"(/.*\.app)/Contents/MacOS/wsd$", path)
    return m.group(1) if m else None


def bring_to_front(state, programs):
    """Opens the app bundle of this session's own window server when another app is in front (a click on its Dock icon). What was
    done is kept; whether it is in front then is what the next look says. `programs`: own pid -> path."""
    own = {pid: path for pid, path in programs.items() if path.endswith("/wsd")}
    front = frontmost()
    if not own or front in own:
        return bool(own)
    bundle = next((b for b in map(bundle_of, own.values()) if b), None)
    state["fronted"].append({"at": now(), "instead_of": front_name(), "bundle": os.path.basename(bundle) if bundle else None})
    if bundle:
        run(["/usr/bin/open", bundle])
    return False


def front_pid(out):
    """The process `lsappinfo info -only pid` names: `"pid"=11538`, or on macOS 27 `    pid = 11538 !cgsConnection ...`."""
    m = re.search(r'(?m)^\s*"?pid"?\s*=\s*(\d+)', out)
    return int(m.group(1)) if m else None


def record(session):
    """The record of a session, or None when it cannot be read."""
    try:
        with open(f"{RECORDS}/{session}.v2.json") as f:
            value = json.load(f)
        return value if value.get("id") == session else None
    except (OSError, ValueError):
        return None


def ended(session):
    """How a session ended, as its record says it (its terminal phase), or None while it has not."""
    value = record(session)
    if value is None or value.get("phase") not in ("Finished", "Failed") or value.get("game") or value.get("starting"):
        return None
    return {"phase": value["phase"], "exit_code": value.get("exit_code"), "played": value.get("played"), "error": value.get("error")}


def place(text):
    """A location's world, instance number and tags: `wrld_…:25038~private(usr_…)~region(eu)`."""
    m = re.match(r"(wrld_[0-9a-fA-F-]+):([^~\s]+)(.*)$", text.strip())
    if not m:
        return None
    return m.group(1), m.group(2), dict(re.findall(r"~(\w+)\(([^)]*)\)", m.group(3)))


def destination(link):
    """The location a launch link names."""
    query = urllib.parse.urlsplit(link).query
    found = re.search(r"(?:^|&)id=([^&]+)", query)
    return place(urllib.parse.unquote(found.group(1))) if found else None


def same_place(wanted, said):
    """Whether the location VRChat said is the one wanted: the world, the instance and every tag the link asked for."""
    return bool(wanted and said) and wanted[:2] == said[:2] and all(said[2].get(k) == v for k, v in wanted[2].items())


JOINING = re.compile(r"\[Behaviour\] Joining (wrld_\S+)")
LOCAL = re.compile(r"\[Behaviour\] Initialized PlayerAPI \".*\" is local")
LEFT = re.compile(r"\[Behaviour\] OnLeftRoom")
ARGUMENT = re.compile(r"^.*?\bArg: ")


def whereabouts(vlines, wanted):
    """(time, there) at every change, as this start's own VRChat log says it: there once the local player is in the
    destination wanted, not from a join (to it or elsewhere) or a leave on."""
    out, joining = [], False
    for t, line in vlines:
        m = JOINING.search(line)
        if m:
            joining = same_place(wanted, place(m.group(1)))
            out.append((t, False))
        elif LEFT.search(line):
            joining = False
            out.append((t, False))
        elif LOCAL.search(line) and joining:
            out.append((t, True))
    return out


def there_all_along(moves, t0, t1):
    """Whether the local player was in the destination from t0 to t1."""
    before = [there for t, there in moves if t <= t0]
    return bool(before) and before[-1] and all(there for t, there in moves if t0 < t < t1)


def tree(listing, root):
    """The processes of `ps -A -o pid=,ppid=,comm=` under `root`, itself included: {pid: name}."""
    rows = []
    for line in listing.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            rows.append((int(parts[0]), int(parts[1]), parts[2].rsplit("/", 1)[-1]))
    kept = {root}
    while True:
        more = {pid for pid, parent, _ in rows if parent in kept and pid not in kept}
        if not more:
            break
        kept |= more
    return {pid: name for pid, _, name in rows if pid in kept}


def settled(lines, at):
    """No frame held over 250 ms in the 20 s before `at`, and frames were presented in them."""
    recent = [(t, l) for t, l in lines if at - 20 < t <= at]
    held = [float(m.group(1)) for m in (HELD.search(l) for _, l in recent) if m]
    return any(NPT.search(l) for _, l in recent) and not any(x > 250 for x in held)


class Follow(threading.Thread):
    """Follows a growing file, opened once it is found to be this launch's, each line stamped with the monotonic time it was
    read (the engine's lines carry none)."""

    def __init__(self, open_fn, sink):
        super().__init__(daemon=True)
        self.open_fn, self.sink, self.stop = open_fn, sink, False

    def run(self):
        file = None
        while not self.stop and not file:
            file = self.open_fn()
            time.sleep(0.5)
        if not file:
            return
        with file as f:
            buf = ""
            while not self.stop:
                chunk = f.read()
                if not chunk:
                    time.sleep(0.05)
                    continue
                buf += chunk
                *lines, buf = buf.split("\n")
                t = now()
                for line in lines:
                    self.sink(t, line)


def own_vrchat_log(since, link):
    """This start's VRChat log, open at its beginning: made since the start, one of the arguments its head lists being the link."""
    for p in glob.glob(f"{VRC_LOGS}/output_log_*.txt"):
        try:
            f = open(p, "r", errors="replace")
        except OSError:
            continue
        made = getattr(os.fstat(f.fileno()), "st_birthtime", 0)
        if made >= since and any(ARGUMENT.sub("", line).strip() == link for line in f.read(256 * 1024).split("\n") if ARGUMENT.search(line)):
            f.seek(0)
            return f
        f.close()
    return None


def opened_engine_log(old, since):
    """The engine's log of this start, open: another file than the one there was before it (`old`), made since."""
    try:
        f = open(ENGINE_LOG, "r", errors="replace")
    except OSError:
        return None
    st = os.fstat(f.fileno())
    if (st.st_ino, st.st_dev) != old and getattr(st, "st_birthtime", since) >= since:
        return f
    f.close()
    return None


def paths(own):
    """The programs of the processes `own`, by path (`tree` gives names alone)."""
    out = {}
    for line in run(["/bin/ps", "-A", "-ww", "-o", "pid=,comm="], 5).splitlines():
        p = line.split(None, 1)
        if len(p) == 2 and p[0].isdigit() and int(p[0]) in own:
            out[int(p[0])] = p[1].strip()
    return out


def sampler(state, stop, session):
    """Once a second: the session's life, GPU utilization (ioreg), the CPU of its own processes' threads (ps -M, the tree of
    its own launcher), lock and front state."""
    while not stop.is_set():
        t = now()
        value = record(session["id"]) or {}
        game = value.get("game") or {}
        own = tree(run(["/bin/ps", "-A", "-o", "pid=,ppid=,comm="], 5), game.get("pid") or -1)
        wsd = sorted(pid for pid, name in own.items() if name == "wsd")
        out = run(["/usr/sbin/ioreg", "-r", "-d", "1", "-c", "IOAccelerator"], 5)
        m = re.search(r'"Device Utilization %"=(\d+)', out)
        state["gpu"].append((t, int(m.group(1)) if m else None))
        state["look"].append({"at": t, "wall": time.time(), "alive": value.get("phase") == "Running" and game.get("pid") in own, "locked": screen_locked(), "front": frontmost(), "front_name": front_name(), "wsd": wsd})
        state["programs"] = {pid: path for pid, path in paths(own).items()}
        names = {str(pid): name for pid, name in own.items() if name in ("fexdarwin-run", "virgl_render_server", "wsd")}
        snap = {}
        if names:
            for line in run(["/bin/ps", "-M", "-p", ",".join(names)], 5).splitlines()[1:]:
                tok = line.split()
                try:
                    if len(tok) >= 4 and tok[1] in names:
                        snap.setdefault(tok[1], []).append(float(tok[3]))
                    elif len(tok) >= 2 and tok[0] in names:
                        snap.setdefault(tok[0], []).append(float(tok[1]))
                except ValueError:
                    pass
        state["cpu"].append((t, {p: {"name": names[p], "sum": round(sum(v), 1)} for p, v in snap.items()}))
        stop.wait(1.0)


def pct(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 3)


def generations(lines):
    """Each NPT line with its swapchain generation: (read time, generation, presents, shown events, interval, fence)."""
    gen, out = 0, []
    for t, l in lines:
        if SWAP.search(l):
            gen += 1
            continue
        m = NPT.search(l)
        if m:
            out.append((t, gen, int(m.group(1)), int(m.group(2)), float(m.group(3)), float(m.group(4))))
    return out


def counted_rate(points, t0, t1, index):
    """Counted per second over [t0, t1): per generation, from the last line before t0 (the base) or the first in the
    window to the last in it; summed counts over summed time between matching lines. A count that went back is a new
    generation's (never subtracted across). None when no two lines of one generation span part of the window."""
    total, seconds = 0, 0.0
    for gen in sorted({p[1] for p in points}):
        pts = [p for p in points if p[1] == gen]
        before = [p for p in pts if p[0] < t0]
        inside = [p for p in pts if t0 <= p[0] < t1]
        # Lines read together are one reading: the last of them, over the time since the reading before.
        chain = {p[0]: p for p in ([before[-1]] if before else []) + inside}
        chain = [chain[t] for t in sorted(chain)]
        for a, b in zip(chain, chain[1:]):
            if b[index] >= a[index] and b[0] > a[0]:
                total += b[index] - a[index]
                seconds += b[0] - a[0]
    return (round(total / seconds, 2) if seconds > 0 else None), round(seconds, 1)


def coverage(points, t0, t1):
    """How much of [t0, t1] lies between two readings of one generation no further apart than GAP, in seconds; what is
    outside the window counts for nothing of it."""
    total = 0.0
    for gen in sorted({p[1] for p in points}):
        times = sorted({p[0] for p in points if p[1] == gen})
        total += sum(max(0.0, min(b, t1) - max(a, t0)) for a, b in zip(times, times[1:]) if b - a <= GAP)
    return round(total, 1)


def shown_lines(lines, state, t0, t1):
    """The owned window server's HUD lines written from t0 to t1: (time, [positive intervals]). Their own times are told on
    this run's clock by the looks, which note both."""
    looks = state["look"]
    if not looks:
        return []
    ahead = looks[0]["wall"] - looks[0]["at"]
    owned = {pid for look in looks for pid in look["wsd"]}
    out = []
    for _, l in lines:
        m = HUD.search(l)
        if not m or int(m.group(2)) not in owned:
            continue
        at = datetime.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S.%f").timestamp() - ahead
        if t0 <= at < t1:
            vals = m.group(3).split(",")[3:]
            out.append((at, [float(v) for v in vals[0::2] if re.fullmatch(r"[\d.]+", v) and float(v) > 0]))
    return out


def longest_gap(times, t0, t1):
    """The longest stretch of [t0, t1] without one of `times`."""
    marks = [t0] + sorted(t for t in times if t0 <= t <= t1) + [t1]
    return max(b - a for a, b in zip(marks, marks[1:]))


def summarize(lines, t0, t1, state, allow_locked, moves=()):
    win = [(t, l) for t, l in lines if t0 <= t < t1]
    points = generations(lines)
    inside = [p for p in points if t0 <= p[0] < t1]
    shown = shown_lines(lines, state, t0, t1)
    hud = [v for _, vals in shown for v in vals]
    held = [float(m.group(1)) for m in (HELD.search(l) for _, l in win) if m]
    looks = [x for x in state["look"] if t0 <= x["at"] < t1]
    length = t1 - t0
    submitted, sub_s = counted_rate(points, t0, t1, 2)
    shown_events, ev_s = counted_rate(points, t0, t1, 3)
    why = []
    if not looks:
        why.append("no lock or front state was read")
    elif (gap := longest_gap([x["at"] for x in looks], t0, t1)) > GAP:
        why.append(f"nothing was looked at for {gap:.1f} s of the window")
    if not all(x["alive"] for x in looks):
        why.append("the session did not live all along")
    if not there_all_along(moves, t0, t1):
        why.append("the local player was not in the destination all along")
    if any(x["locked"] is not False for x in looks):
        why.append("the screen was locked (or its state unknown) during the window")
    if any(x["front"] is None or x["front"] not in x["wsd"] for x in looks):
        others = {}
        for x in looks:
            if x["front"] is None or x["front"] not in x["wsd"]:
                name = x.get("front_name") or (f"pid {x['front']}" if x["front"] else "nothing that could be told")
                others[name] = others.get(name, 0) + 1
        why.append("VRChat was not frontmost all along: " + ", ".join(f"{n} in {c} of {len(looks)} looks" for n, c in sorted(others.items(), key=lambda x: -x[1])))
    gens = sorted({p[1] for p in inside})
    covered = coverage(points, t0, t1)
    if not inside:
        why.append("no guest Present line in the window")
    elif covered < COVERED * length:
        why.append(f"its submissions were counted over {covered} s of {length:.1f}")
    elif (gap := longest_gap([p[0] for p in inside], t0, t1)) > GAP:
        why.append(f"its submissions were not read for {gap:.1f} s of the window")
    if not hud:
        why.append("no frame was shown (no positive presentation time)")
    elif sum(hud) / 1000 < COVERED * length or longest_gap([t for t, vals in shown if vals], t0, t1) > GAP:
        why.append(f"no frame was shown all along: {sum(hud) / 1000:.1f} s of {length:.1f}")
    production_only = allow_locked and why and all(w.startswith(("the screen was locked", "VRChat was not frontmost", "no frame was shown")) for w in why)
    valid = not why
    g = [x[1] for x in state["gpu"] if t0 <= x[0] < t1 and x[1] is not None]
    rs = {}
    for t, snap in state["cpu"]:
        if t0 <= t < t1:
            for pid, v in snap.items():
                rs.setdefault(v["name"] + ":" + pid, []).append(v["sum"])
    return {
        "seconds": round(length, 1),
        "looks": len(looks),
        "valid": valid,
        "production_only": bool(production_only),
        "invalid_because": why,
        "generations_in_window": gens,
        "guest_present": {
            "batches_of_60": len(inside),
            "interval_ms_per_batch": [p[4] for p in inside],
            "interval_ms_median": pct([p[4] for p in inside], 0.5),
            "interval_ms_p10_p90": [pct([p[4] for p in inside], 0.1), pct([p[4] for p in inside], 0.9)],
            "fence_wait_ms_median": pct([p[5] for p in inside], 0.5),
            "submitted_per_second_counted": submitted,
            "counted_over_seconds": sub_s,
            "read_over_seconds_of_the_window": covered,
        },
        "worker_shown_events_per_second_counted": shown_events,
        "wsd_shown": {
            "hud_intervals_ms": hud,
            "frames": len(hud),
            "per_second": round(len(hud) / length, 2),
            "covered_seconds": round(sum(hud) / 1000, 1),
            "interval_ms_p50_p90_p99": [pct(hud, 0.5), pct(hud, 0.9), pct(hud, 0.99)],
            "held_over_50ms": len(held),
            "held_over_100ms": sum(1 for x in held if x > 100),
        },
        "gpu_device_utilization_pct": {"median": pct(g, 0.5), "p10_p90": [pct(g, 0.1), pct(g, 0.9)]},
        "process_cpu_pct_median": {k: pct(v, 0.5) for k, v in rs.items()},
    }


def told(session, event, at):
    """What the program's event says of the session: which it is, by the admission of this very request alone (`starting`: the
    first name said), and that it runs. A `running` that names another is somebody else's session, found again (`foreign`):
    it is never this one, and says nothing of it."""
    if event.get("event") == "starting":
        session["id"] = session["id"] or event.get("session_id")
    if event.get("event") == "running" and session["running_at"] is None and event.get("session_id") in (None, session["id"]):
        session["running_at"] = at


def foreign(events):
    """The session a `running` of the program's names that is not the one its own `starting` said, if any."""
    own = next((e.get("session_id") for e in events if e.get("event") == "starting" and e.get("session_id")), None)
    told = (e.get("session_id") for e in events if e.get("event") == "running")
    return next((name for name in told if name is not None and name != own), None)


def refused(events):
    """Whether the program said that it started nothing: an error, and never that its launch was admitted."""
    said = [e.get("event") for e in events]
    return "error" in said and not {"starting", "running", "exited"} & set(said)


def close(cli, session, proc, res, started_nothing=False):
    """Ends the launch: the session `session` asked to quit until its record is terminal, the program waited for. Whether
    everything this run started is known to have ended; what is not is said in `res`. Without a session's name nothing is
    ever asked to quit, and only the program's word that it started nothing (`started_nothing`) resolves the launch."""
    if session and ended(session) is None:
        res["quit"] = run([cli, "steam", "quit", "438100", "--session", session, "--wait", "60"], 90)
    until = now() + CLOSE_DEADLINE
    while now() < until and ((session and ended(session) is None) or proc.poll() is None):
        time.sleep(1)
    res["terminal"] = ended(session) if session else None
    if proc.poll() is None:
        if session and res["terminal"]:
            # Its session ended; the program is only left behind.
            proc.terminate()
        else:
            res["outcome"] += f"; the program had not ended {CLOSE_DEADLINE} s after the quit"
            return False
    if not session and not started_nothing:
        res["outcome"] += "; what the program may have started was never named: nothing was asked to quit, and it may run"
        return False
    if session and res["terminal"] is None:
        res["outcome"] += f"; the session {session} had not ended {CLOSE_DEADLINE} s after the quit: it may still run"
        return False
    return True


def main():
    ending = {"resolved": True}
    status = measure(ending)
    return status if ending["resolved"] else 5


def measure(ending):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cli", default=None)
    ap.add_argument("--link", required=True)
    ap.add_argument("--percent", type=int)
    ap.add_argument("--arg", action="append", default=[])
    ap.add_argument("--warm", type=float, default=90)
    ap.add_argument("--window", type=float, default=60)
    ap.add_argument("--windows", type=int, default=3)
    ap.add_argument("--label", default="")
    ap.add_argument("--no-sample", action="store_true")
    ap.add_argument("--allow-locked", action="store_true")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.percent is not None and not 1 <= a.percent <= 100:
        ap.error("--percent is the engine's percent, 1 to 100")
    cli = a.cli or sorted(glob.glob(f"{HOME}/Library/Application Support/orbiters-desktop/obelisk-cli/obelisk-cli-*-arm64/obelisk-cli"))[-1]
    started_wall = time.time()
    lines, vlines, events = [], [], []
    command = [cli, "steam", "play", "438100"] + (["--render-percent", str(a.percent)] if a.percent else []) + ["--", "-screen-fullscreen", "1", "-window-mode", "borderless"] + a.arg + [a.link]
    res = {
        "label": a.label,
        "when": datetime.datetime.now().isoformat(timespec="seconds"),
        "command": command[1:-1] + ["<link>"],
        "power": {"pmset_custom": run(["/usr/bin/pmset", "-g", "custom"]), "batt": run(["/usr/bin/pmset", "-g", "batt"]).splitlines()[:2], "thermal_start": run(["/usr/bin/pmset", "-g", "therm"])},
        "not_measured": ["GPU frequency and command-buffer start/end (powermetrics and Metal counters need root or the game's process)", "queue depth", "host-thread runnable and wake-up intervals"],
        "outcome": "not started",
        "windows": [],
    }
    try:
        st = os.stat(ENGINE_LOG)
        old_log = (st.st_ino, st.st_dev)
    except FileNotFoundError:
        old_log = None
    wanted = destination(a.link)
    if wanted is None:
        ap.error("--link names no world and instance")
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    session = {"id": None, "running_at": None}
    state = {"gpu": [], "cpu": [], "look": [], "fronted": [], "programs": {}}
    stop = threading.Event()
    status = 4
    eng = vrc = None

    def read_events():
        for line in proc.stdout:
            try:
                e = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            events.append((now(), e))
            told(session, e, now())
    reader = threading.Thread(target=read_events, daemon=True)
    reader.start()
    t_start = now()
    try:
        # The game's own session: admitted (with its id), then running, an error or an exit, within a deadline, the program
        # alive.
        while session["running_at"] is None and now() - t_start < START_DEADLINE:
            if any(e.get("event") in ("error", "exited") for _, e in events) or proc.poll() is not None:
                break
            if foreign([e for _, e in events]):
                res["outcome"] = "error: the program follows another session than the one it started: nothing was asked to quit"
                return status
            time.sleep(0.5)
        if session["running_at"] is None or session["id"] is None:
            res["outcome"] = "did not start: " + json.dumps([e for _, e in events if e.get("event") in ("error", "exited")])[:400]
            status = 2
            return status

        eng = Follow(lambda: opened_engine_log(old_log, started_wall), lambda t, l: lines.append((t, l)))
        vrc = Follow(lambda: own_vrchat_log(started_wall, a.link), lambda t, l: vlines.append((t, l)))
        eng.start(); vrc.start()
        threading.Thread(target=sampler, args=(state, stop, session), daemon=True).start()
        def lives():
            return proc.poll() is None and ended(session["id"]) is None
        # Arrival: the local player in this very destination, in this start's own log.
        arrived = None
        while arrived is None and now() - session["running_at"] < ARRIVE_DEADLINE and lives():
            arrived = next((t for t, there in whereabouts(list(vlines), wanted) if there), None)
            time.sleep(1)
        res["arrived_after_s"] = round(arrived - t_start, 1) if arrived else None
        if arrived is None:
            res["outcome"] = "did not arrive (the local player was never in the destination, in this start's own log): nothing scored"
            status = 3
            return status
        # Settled: the warm time, then 20 s without a frame held over 250 ms, within the deadline: else nothing is scored.
        calm = False
        tried = 0.0
        while not calm and lives() and now() - arrived < a.warm + SETTLE_DEADLINE:
            if now() - tried >= 5:
                tried = now()
                bring_to_front(state, dict(state["programs"]))
            calm = now() - arrived >= a.warm and settled(list(lines)[-4000:], now())
            time.sleep(1)
        if not calm:
            res["outcome"] = "did not settle (frames were still held after the warm time): nothing scored" if lives() else "the game ended before any window"
            return status
        windows = []
        for _ in range(a.windows):
            if not lives():
                break
            t0, u0 = now(), time.clock_gettime_ns(time.CLOCK_UPTIME_RAW)
            time.sleep(a.window)
            windows.append((t0, now(), u0, time.clock_gettime_ns(time.CLOCK_UPTIME_RAW)))
        # The last second's lines are read.
        time.sleep(2)
        moves = whereabouts(list(vlines), wanted)
        res["windows"] = [summarize(list(lines), t0, t1, state, a.allow_locked, moves) | {"from_s": round(t0 - t_start, 1), "from": t0, "to": t1, "from_uptime_ns": u0, "to_uptime_ns": u1} for t0, t1, u0, u1 in windows]
        res["outcome"] = "measured" if windows else "the game ended before any window"
        status = 0 if windows else 4
        # Unscored, after the windows: 3 s stack samples of the render server and the game.
        samples = {}
        if not a.no_sample and proc.poll() is None:
            procs = [l.split(None, 3) for l in run(["/bin/ps", "-A", "-o", "pid=,rss=,%cpu=,comm="]).splitlines() if l.strip()]
            own = tree(run(["/bin/ps", "-A", "-o", "pid=,ppid=,comm="]), ((record(session["id"]) or {}).get("game") or {}).get("pid") or -1)
            for name, ends, key in (("render-server", "virgl_render_server", 2), ("game", "fexdarwin-run", 1)):
                group = [p for p in procs if len(p) == 4 and p[3].endswith(ends) and int(p[0]) in own]
                if group:
                    out = run(["/usr/bin/sample", max(group, key=lambda p: float(p[key]))[0], "3", "-mayDie"], 60)
                    samples[name] = out[out.find("Call graph:"):][:200000]
        res["samples"] = samples
        return status
    finally:
        # Always: this launch's own session, whether or not the program that started it lives, is asked to quit (never
        # forced) until its own record says how it ended, and what happened is written.
        if proc.poll() is not None:
            # Its last words are read.
            reader.join(5)
        res["session"] = session["id"]
        said = [e for _, e in events]
        if foreign(said):
            # Which session is this run's is not known any more: none is asked to quit.
            res["foreign_session"] = True
            resolved = close(cli, None, proc, res)
        else:
            resolved = close(cli, session["id"], proc, res, refused(said))
        stop.set()
        for f in (eng, vrc):
            if f:
                f.stop = True
        res["power"]["thermal_end"] = run(["/usr/bin/pmset", "-g", "therm"])
        snapshot = list(lines)
        res["swapchains"] = [{"at_s": round(t - t_start, 1), "size": f"{m.group(1)}x{m.group(2)}", "fmt": m.group(3), "buffers": m.group(4)} for t, l in snapshot for m in [SWAP.search(l)] if m]
        res["render"] = [m.groups() for _, l in snapshot for m in [RENDER.search(l)] if m][:1]
        res["engine_trace"] = [l for _, l in snapshot if STOP.search(l)][:40]
        res["events"] = [e for _, e in events]
        res["observed"] = {
            "started_at": t_start,
            "look": list(state["look"]),
            "fronted": list(state["fronted"]),
            "moves": whereabouts(list(vlines), wanted),
            "lines": [[t, l] for t, l in snapshot if NPT.search(l) or SWAP.search(l) or HUD.search(l) or HELD.search(l)],
        }
        with open(a.out, "w") as f:
            json.dump(res, f, indent=1)
        for w in res["windows"]:
            print(("valid " if w["valid"] else "INVALID ") + "; ".join(w["invalid_because"]), "| submitted/s", w["guest_present"]["submitted_per_second_counted"], "interval", w["guest_present"]["interval_ms_median"], "shown/s", w["wsd_shown"]["per_second"])
        print("outcome:", res["outcome"])
        # Whatever is returned above: nothing more may be started while this one may still run.
        ending["resolved"] = resolved


if __name__ == "__main__":
    sys.exit(main())
