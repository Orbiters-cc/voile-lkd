#!/usr/bin/env python3
"""One real start with the host timeline at one scale, with a named combination of switches; never a replacement.

Usage: real_session.py '<the owner's private instance link>' --plan 45 --series NAME [--switch queries=once] [--nothing-wrong-seen]
       real_session.py --restore      after a start that was cut off: the released generation put back, and nothing started

A series is at most three starts, A B A: the first without a switch, the second with the one under test, the third without it again, each
by an invocation of its own with the same --series. What each came to is in <out>/<NAME>/series.json, and it is what authorizes the next: a
start that was not whole, not valid or not as it was meant to be (judge() below, the gates of README.md) ends its series, and so does one
that failed, or that this program did not see the end of. Only the person at the Mac sees an anti-cheat warning, a black or frozen picture
or a game that misbehaves: the second and third starts are made with --nothing-wrong-seen alone, which says that there was none of it.

One start per invocation: the timeline generation is put in place for it and the released one put back after it, whatever
happened. At the Mac, unlocked, plugged in, idle and cool, hands off for about eight minutes. The options:
  --switch NAME=VALUE  upscale=metalfx: wsd scales a frame smaller than the window with MetalFX Spatial; present=<list> of arrival,
                       attime, nosync, two: how wsd presents (wsd/wsd.m says what each is); queries=once: DXMT's looks at an event query
                       that is not there flush once, not at each look (dxmt, src/d3d11/d3d11_query.hpp); order=1: DXMT orders an immutable resource's
                       data, and ends an occlusion query's counting with its pass (src/dxmt/dxmt_init_order.hpp). None is the programs as ever.
                       They reach wsd, and the last two the render server, alone (launch.sh), never the game. In the manifest, the
                       result and the folder's name
  --series NAME      the series (letters, digits, - and _): the folder in --out
  --nothing-wrong-seen   no warning, crash, hang or lost picture was seen in the series' starts so far
  --cli PATH         the developer's obelisk-cli (feature developer-timeline), signed as the one that holds the Steam session
  --generation DIR   what scripts/build-timeline-generation.sh of the Obelisk fork wrote
  --bench DIR        the folder of bench.py (this one)
  --out DIR          the evidence, one folder per session, readable by this user alone
  --passes N         the encoders and their GPU times of every Nth frame, the same at every scale (8)
  --mb N             the trace's budget per start, in MiB (1536)
  --plan 45          the scale, 1 to 100: one

What it does: refuses when the screen is locked, when anything of the engine runs, when the disk is short, when the Mac is on its battery or
warm, when this terminal may not take the window's picture, when the link is not one instance's, when this computer uses several VRChat
profiles, while Orbiters - N4N0 starts VRChat or waits after an early end (bench.py says how), and when the series does not go on; holds the
one slot for a start of VRChat, so that N4N0 makes none, until the released generation is back; holds the display
awake; puts the timeline generation in the library through the developer's obelisk-cli (verified, atomic, pinned, refused while
anything of the engine runs); then one start by bench.py (arrival, the game's app brought to the front, 120 s warm, three windows
of 60 s cut on the trace's own clock, no stack sample, its own session quit by session; 100 s after the arrival three pictures of the
game's window alone, picture-1.png to -3.png in the start's folder: compare_pictures.py tells two starts' apart from what moves by itself), at least 90 s after the last start this
library knows of ended; and in every case, interrupted or failed, puts the
released generation back through the same program and proves it by every digest. A start that fails ends the series. Nothing of
the game is attached to, sampled or touched: of the host programs, what macOS says from outside (ps, lsof, pmset, notifyutil).

Told to stop (Ctrl-C, SIGTERM, whoever is told), it ends the bench, which quits its session, and puts the release back. That it is owed is
written before the generation is put in place (<out>/restoration-owed.json) and taken away only when every digest is the released one;
only then does the series' entry say that it may go on. Killed in between, the next start, and --restore, first wait until nothing of it
runs, put the release back and prove it; until that succeeded nothing is started. The same by hand, once VRChat is closed:
  OBELISK_DEVELOPER_ENGINE=released OBELISK_DEVELOPER_ENGINE_FILES=<generation> <cli> engine generation
(or obelisk-cli engine repair of any released obelisk-cli, which lays the whole release again).
"""
import argparse, datetime, glob, hashlib, importlib.util, json, math, os, re, shutil, signal, stat, subprocess, sys, threading, time

HOME = os.path.expanduser("~")
HERE = os.path.dirname(os.path.abspath(__file__))
BETWEEN = 90       # s after a start's session ended before the next
LEAST_FREE = 8     # GiB
STARTS = 3         # of a series
WHOLE = 0.95       # of a window's frames
PRESSURE = 2       # the level a window of one arm alone, or any start's beginning above 0, speaks against
LOOK_GAP = 15      # s of a window without any look at the Mac's state, its ends included, at most
WHOLE_GAP = 20     # s without a whole one (power, pressure)
ENDING = 420       # s for the bench to end what it started (its own deadlines are shorter)
HOST = ("wsd", "virgl_test_server", "virgl_render_server")
# What a process of each role has mapped, at the least: the files of the generation, by their names.
INVENTORY = {"wsd": ("engine/wsd",), "vtest": ("graphics/bin/virgl_test_server", "graphics/lib/libvirglrenderer.1.dylib"),
             "npt": ("graphics/libexec/virgl_render_server",),
             "dxmt": ("graphics/libexec/virgl_render_server", "graphics/dxmt-native.framework/Versions/A/dxmt-native")}
ENGINE = re.compile(r"/(fexdarwin-run|virgl_render_server|virgl_test_server|wsd)$")


def run(cmd, timeout=15, env=None):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env).stdout
    except Exception as e:  # noqa: BLE001 - recorded, never fatal
        return f"<{cmd[0]}: {e}>"


def say(text):
    """Told, when anyone still listens: a terminal that is gone stops nothing, the revert least of all."""
    try:
        print(f"{datetime.datetime.now():%H:%M:%S} {text}", flush=True)
    except (OSError, ValueError):
        pass


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def locked():
    m = re.search(r"<key>IOConsoleLocked</key>\s*<(true|false)/>", run(["/usr/sbin/ioreg", "-n", "Root", "-d1", "-a"]))
    return None if not m else m[1] == "true"


def write(path, value):
    with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        if isinstance(value, str):
            f.write(value)
        else:
            json.dump(value, f, indent=1)


def durable(path, value):
    """Written whole or not at all, and there after this program was killed."""
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    with open(os.open(path + ".new", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        json.dump(value, f, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.rename(path + ".new", path)
    flushed(os.path.dirname(path))


def flushed(folder):
    fd = os.open(folder, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def processes():
    """pid -> (parent, program), by path alone: never a command line."""
    out = {}
    for line in run(["/bin/ps", "-A", "-ww", "-o", "pid=,ppid=,comm="]).splitlines():
        p = line.split(None, 2)
        if len(p) == 3 and p[0].isdigit():
            out[int(p[0])] = (int(p[1]), p[2])
    return out


SWITCHES = {"upscale": ("OBELISK_WSD_UPSCALE", {"metalfx"}), "present": ("OBELISK_WSD_PRESENT", {"arrival", "attime", "nosync", "two"}),
            "queries": ("OBELISK_DXMT_QUERY_RESCUE", {"once"}), "order": ("OBELISK_DXMT_INIT_ORDER", {"1"})}
PICTURE = os.path.join(HERE, "bin", "window_picture")  # (build-window-picture.sh)


def switches(asked):
    """--switch values -> the variables of the launcher; ValueError for what is not known."""
    out = {}
    for text in asked:
        name, _, value = text.partition("=")
        if name not in SWITCHES:
            raise ValueError(f"--switch {text}: {name} is none of {', '.join(SWITCHES)}")
        variable, known = SWITCHES[name]
        if variable in out:
            raise ValueError(f"--switch {name} is given twice")
        if not value or any(part not in known for part in value.split(",")):
            raise ValueError(f"--switch {text}: a list of {', '.join(sorted(known))}")
        out[variable] = value
    return out


UUID = re.compile(r"[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z")


def record_ended(path, folder, read):
    """(when it was last written, when its game ended on the boot clock or None) of a record of the engine's; ValueError or OSError for one
    that is not whole, or not the engine's own (N4N0's scan_records)."""
    st = os.lstat(path)
    if not stat.S_ISREG(st.st_mode) or st.st_uid != folder.st_uid or st.st_mode & 0o077 or st.st_size > 64 * 1024:
        raise ValueError("not the engine's own")
    with open(path, encoding="utf-8") as f:
        value = read(f.read())
    name = os.path.basename(path)
    need = lambda good: good or (_ for _ in ()).throw(ValueError("not a record"))
    need(isinstance(value, dict))
    if name == "session.v2.json":
        need(isinstance(value.get("id"), str) and UUID.match(value["id"]))
        return st.st_mtime, None
    store, played = value.get("store"), value.get("played")
    app = store.get("app_id") if isinstance(store, dict) else None
    need(isinstance(app, int) and not isinstance(app, bool) and 0 <= app < 2**64)
    if app == 438100:
        need(value.get("id") == name[: -len(".v2.json")] and isinstance(value.get("phase"), str))
    need(played is None or isinstance(played, dict))
    ended = (played or {}).get("ended")
    if ended is not None:
        need(isinstance(ended, dict) and isinstance(ended.get("boot"), str) and UUID.match(ended["boot"]))
        seconds = ended.get("seconds")
        need(isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and math.isfinite(seconds) and seconds >= 0)
        ended = (ended["boot"].upper(), seconds)
    return st.st_mtime, ended


def since_last(library, clock, wall, read):
    """(seconds since the last session of this library that is known ended, why that is not known). (None, None): none ever ran. A record
    that cannot be read, or that was written or ended in what is still to come, and records that cannot be listed, say nothing: as if one
    had ended just now, until they do."""
    folder = f"{library}/SteamSessions"
    try:
        try:
            names, of = os.listdir(folder), os.stat(folder)
        except FileNotFoundError:
            if os.path.lexists(folder):
                raise
            if os.path.lexists(library):
                os.listdir(library)
            return None, None
    except OSError as e:
        return 0.0, f"the engine's records cannot be listed ({e.strerror})"
    newest, why = None, None
    for name in sorted(n for n in names if n.endswith(".v2.json")):
        try:
            written, ended = record_ended(f"{folder}/{name}", of, read)
        except (OSError, ValueError, RecursionError):
            why = f"the engine's record {name} cannot be read"
            continue
        ages = [wall - written] + ([clock[1] - ended[1]] if ended and ended[0] == clock[0] else [])
        if min(ages) < 0:
            why = f"the engine's record {name} is of a time that is still to come"
        newest = min([min(ages)] + ([newest] if newest is not None else []))
    return (0.0, why) if why else (newest, None)


def engine_running():
    now = processes()
    if not now:
        return ["what runs is not known"]
    return [f"{pid} {os.path.basename(name)}" for pid, (_, name) in now.items() if ENGINE.search(name)]


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def pressure(text):
    """macOS's thermal pressure level (0 none) of `notifyutil -g com.apple.system.thermalpressurelevel`, or None."""
    found = re.search(r"thermalpressurelevel\s+(\d+)", text or "")
    return int(found[1]) if found else None


def in_window(looks, lo, hi):
    return [x for x in looks if lo <= x.get("uptime_ns", -1) <= hi]


def longest_without(looks, lo, hi):
    """The longest stretch of a window without one of them, in seconds, its two ends included."""
    marks = [lo] + sorted(x["uptime_ns"] for x in looks) + [hi]
    return max(b - a for a, b in zip(marks, marks[1:])) / 1e9


def window_conditions(looks, lo, hi):
    """What the Mac was like in a window, of the looks the conditions are (one every 5 s, whole ones every other)."""
    inside = in_window(looks, lo, hi)
    whole = [x for x in inside if "thermal_pressure" in x]
    return dict(looks=len(inside), whole_looks=len(whole), seconds=(hi - lo) / 1e9, longest_without_s=longest_without(inside, lo, hi),
                longest_without_a_whole_one_s=longest_without(whole, lo, hi),
                pressure=sorted({pressure(x["thermal_pressure"]) for x in whole}, key=lambda x: (x is None, x)),
                on_ac=bool(whole) and all("AC Power" in " ".join(x.get("power") or []) for x in whole),
                low_power_mode=sorted({str(x.get("low_power_mode")) for x in whole}), locked=any(x.get("locked") is not False for x in inside))


def not_looked_at(c):
    """What of a window the looks at the Mac's state do not cover."""
    seconds, why = c.get("seconds"), []
    for count, gap, most, what in (("looks", "longest_without_s", LOOK_GAP, "the Mac's state"), ("whole_looks", "longest_without_a_whole_one_s", WHOLE_GAP, "power and pressure")):
        if seconds is None or c.get(count) is None or c.get(gap) is None:
            why.append(f"how much of it {what} was looked at is not told")
        elif c[gap] > most or c[count] * most < seconds:
            why.append(f"{what} was looked at {c[count]} times in {seconds:.0f} s, not for {c[gap]:.0f} s")
    return why


# The counters of format 2 that say something against (or for) a window, of either arm: one that is not there is missing, not zero.
COUNTERS = {"": ("said_otherwise_than_its_watermarks", "handed_over_and_committed", "left_not_handed_over", "most_rescues_of_a_chunk", "rescues",
                 "rescues_whose_chunk_was_not_handed_over", "rescues_of_a_chunk_something_else_committed", "rescues_of_another_chunk_than_its_end_s",
                 "rescues_whose_commit_is_not_recorded", "rescues_whose_end_is_not_recorded", "signals"),
            "ended": ("event", "disjoint"), "window": ("looks", "s_false", "s_ok", "rescues"), "debts": ("accepted", "covered", "cancelled", "outstanding_at_the_end"),
            "tries": ("looks_of_half_a_ms_or_more", "looks_of_5_ms_or_more", "tries_of_looks_that_could_not", "tries_of_the_rescue_thread_that_could_not"),
            "one_by_one": ("recorded", "not_seen_though_looked_at_of_more_than_a_second")}


def counters_missing(q):
    of = lambda group: (q if not group else q.get(group)) or {}
    out = [f"{group}.{name}" if group else name for group, names in COUNTERS.items() for name in names if not isinstance(of(group).get(name), (int, float))]
    if "oldest_outstanding_ns" not in of("debts"):
        out.append("debts.oldest_outstanding_ns")
    if not out and not q["signals"]:
        out.append("any Signal")
    if not out and q["ended"]["event"] + q["ended"]["disjoint"] and not q["one_by_one"]["recorded"]:
        out.append("any End one by one")
    return out


def uncorroborated(q):
    """What of a window's rescues nothing else recorded speaks for (their Ends are a sample: that is told, and ends no series)."""
    n, of = (q or {}).get("rescues_whose_end_is_not_recorded"), (q or {}).get("rescues")
    return f"of {of} rescues the End of {n} is not recorded: that they were of their marker's chunk is not known of those" if n else None


def mechanism_wrong(q, once):
    """What a window's queries say against the mechanism, with the switch (once) or without."""
    missing = counters_missing(q)
    why = ["not recorded: " + ", ".join(missing)] if missing else []
    if q.get("once") != [once]:
        why.append(f"the switch was {q.get('once')}, not {[once]}")
    if q.get("locked") != [True]:
        why.append(f"the device's lock was {q.get('locked')}, not [True]")
    if q.get("said_otherwise_than_its_watermarks"):
        why.append(f"{q['said_otherwise_than_its_watermarks']} commits say of themselves what their watermarks do not")
    if not once:
        return why
    for name, most, what in (("handed_over_and_committed", 0, "commits for a marker already handed over"), ("left_not_handed_over", 0, "markers left not handed over"),
                             ("most_rescues_of_a_chunk", 1, "rescues of one chunk"), ("rescues_whose_chunk_was_not_handed_over", 0, "rescues whose chunk was not handed over"),
                             ("rescues_of_a_chunk_something_else_committed", 0, "rescues of a chunk something else committed"),
                             ("rescues_of_another_chunk_than_its_end_s", 0, "rescues of another chunk than their End's"),
                             ("rescues_whose_commit_is_not_recorded", 0, "rescues whose commit is not recorded")):
        if name not in missing and q[name] > most:
            why.append(f"{q.get(name)} {what}")
    debts = q.get("debts") or {}
    if debts.get("cancelled"):
        why.append(f"{debts['cancelled']} owed markers went with their context")
    if (debts.get("oldest_outstanding_ns") or 0) > 10**9:
        why.append(f"a marker is owed for {debts['oldest_outstanding_ns'] / 1e9:.1f} s")
    if (q.get("one_by_one") or {}).get("not_seen_though_looked_at_of_more_than_a_second"):
        why.append(f"{q['one_by_one']['not_seen_though_looked_at_of_more_than_a_second']} Ends were looked at and never found, a second and more before the window's end")
    if ((q.get("tries") or {}).get("looks_of_5_ms_or_more") or 0) > 1:
        why.append(f"{q['tries']['looks_of_5_ms_or_more']} looks of 5 ms or more")
    return why


def judge(result, windows, once, first=None):
    """Why this start does not authorize the next (README.md, "A start is inconclusive" and "The mechanism first"): nothing, it does.
    `first`: the series' first start's result, which this one is to be like."""
    why = []
    if result.get("bench_status") != 0 or result.get("outcome") != "measured":
        why.append(f"the bench: {result.get('outcome')} (status {result.get('bench_status')})")
    terminal = result.get("terminal") or {}
    played = terminal.get("played") or {}
    if terminal.get("phase") != "Finished" or terminal.get("error") or played.get("ended_by_obelisk") is not True or played.get("exit_signal") is not None:
        why.append("its session did not end as it was asked to (a crash, or somebody else ended it)")
    if len(result["windows"]) != windows:
        why.append(f"{len(result['windows'])} windows of {windows}")
    if not {"wsd", "vtest", "npt", "dxmt"} <= set(result.get("roles") or []):
        why.append(f"the trace is of {', '.join(result.get('roles') or []) or 'no role'} alone")
    if result.get("foreign_images"):
        why.append("host programs loaded what is not the generation's")
    if result.get("not_in_the_inventory") is None:
        why.append("what the host programs loaded is not known")
    elif result["not_in_the_inventory"]:
        why.append("what the host programs loaded is not known: " + "; ".join(result["not_in_the_inventory"]))
    pictures = [p for p in result.get("pictures") or [] if p.get("file")]
    if len(pictures) != 3:
        why.append(f"{len(pictures)} pictures of the game's window, of 3")
    if result.get("plane") is None or (result.get("plane_share") or 0) < 0.9:
        why.append("which plane of the window server's is the game's is not known")
    for w in result["windows"]:
        mine = []
        if not w.get("valid"):
            mine.append("not valid: " + "; ".join(w.get("why") or []))
        if w.get("reader"):
            mine.append(f"not read: {w['reader']}")
        if w.get("clock") != "stamped":
            mine.append("its ends are not stamped on the trace's clock")
        if not w.get("frames"):
            mine.append("no frames")
        elif (w.get("whole_share") or 0) < WHOLE:
            mine.append(f"{100 * (w.get('whole_share') or 0):.1f} % of its frames are whole")
        if w.get("trace_not_complete") is None or w["trace_not_complete"]:
            mine.append("not recorded whole: " + ("; ".join(w.get("trace_not_complete") or []) or "not told"))
        if w.get("shown_per_s") is None:
            mine.append("no shown rate of the game's plane")
        c = w.get("conditions")
        if not c or not c["looks"]:
            mine.append("the Mac's state in it is not known")
        else:
            mine += not_looked_at(c)
            if c["locked"]:
                mine.append("the screen was locked")
            if not c["on_ac"]:
                mine.append("not on AC power all along")
            if None in c["pressure"] or not c["pressure"]:
                mine.append("the thermal pressure is not known")
        q = w.get("queries_of_every_queue") or w.get("queries")
        mine += mechanism_wrong(q, once) if q else ["its queries are not told"]
        if first:
            of_first = next((x for x in first["windows"] if x["window"] == w["window"]), None)
            levels = [max((p for p in (x or {}).get("conditions", {}).get("pressure", []) if p is not None), default=0) for x in (of_first, w)]
            if (levels[0] >= PRESSURE) != (levels[1] >= PRESSURE):
                mine.append(f"the thermal pressure is {levels[1]}, the first start's was {levels[0]}")
        why += [f"window {w['window']}: {x}" for x in mine]
    return why


class Series:
    """Up to three starts, A B A (`<out>/<name>/series.json`, readable by this user alone), and whether another may be made."""

    def __init__(self, folder):
        self.folder, self.path, self.told = folder, os.path.join(folder, "series.json"), dict(starts=[], salt=None)
        if os.path.lexists(self.path):
            with open(self.path) as f:
                self.told = json.load(f)  # (not readable: an error, and no start)

    def place(self, link):
        """Whether the link is the series': kept salted and hashed, never as it is."""
        self.told["salt"] = self.told.get("salt") or os.urandom(32).hex()
        return hashlib.pbkdf2_hmac("sha256", link.encode(), bytes.fromhex(self.told["salt"]), 100000).hex()

    def problems(self, switches, fixed, nothing_wrong_seen):
        starts, out = self.told["starts"], []
        n = len(starts)
        if n >= STARTS:
            return [f"the series has had its {STARTS} starts"]
        if n and not starts[-1].get("go_on"):
            out.append(f"the series ended at its start {n}: " + ("; ".join(starts[-1].get("why") or []) or "what became of it is not known") + " (no other is made, and none replaces it)")
        if n and not nothing_wrong_seen:
            out.append("--nothing-wrong-seen is missing: whether an anti-cheat warning, a crash, a hang or a lost picture was seen in the starts so far "
                       "is for the person at the Mac to say (if there was any of it, the series is over)")
        if n % 2 == 0 and switches:
            out.append(f"start {n + 1} of a series is without a switch (A B A)")
        if n == 1 and not switches:
            out.append("start 2 of a series is with the switch under test (A B A)")
        if n:
            out += [f"{k} is not the one of the series' first start" for k, v in fixed.items() if starts[0]["fixed"].get(k) != v]
        return out

    def begin(self, switches, fixed, folder, nothing_wrong_seen=False):
        # (said before it is made: what this program does not see the end of ended its series)
        self.told["starts"].append(dict(when=datetime.datetime.now().isoformat(timespec="seconds"), switches=switches, fixed=fixed, folder=folder, go_on=False, why=[],
                                        nothing_wrong_seen_before_it=bool(nothing_wrong_seen)))
        self.save()

    def ended(self, result, why):
        """(once the released generation is back, and not before)"""
        self.told["starts"][-1].update(go_on=not why, why=why, result=result, result_sha256=sha(result))
        self.save()

    def save(self):
        durable(self.path, self.told)

    def first(self):
        """The result of the series' first start, for the ones after it."""
        starts = self.told["starts"]
        if len(starts) < 2:
            return None
        with open(starts[0]["result"]) as f:
            return json.load(f)


class Owed:
    """That the released generation is to be put back (`<out>/restoration-owed.json`, beside the series): there before the other one is put in
    place, and until the released one was proven."""

    def __init__(self, out):
        self.path = os.path.join(out, "restoration-owed.json")

    def there(self):
        try:
            os.lstat(self.path)
        except FileNotFoundError:
            return False
        except OSError:
            pass  # (not known: it may be)
        return True

    def read(self):
        """What it says; nothing, when it cannot be read: it is owed all the same."""
        try:
            with open(self.path) as f:
                told = json.load(f)
            return told if isinstance(told, dict) else {}
        except (OSError, ValueError):
            return {}

    def say(self, **more):
        durable(self.path, self.read() | more)

    def settle(self):
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            return
        flushed(os.path.dirname(self.path))


class Session:
    def __init__(self, a):
        self.a = a
        self.bench = module(os.path.join(a.bench, "bench.py"), "bench")
        self.cut = self.bench.Cut()  # (told to stop: once)
        self.series = Series(os.path.join(a.out, a.series)) if getattr(a, "series", None) else None
        self.library = a.library or f"{HOME}/Library/Application Support/cc.orbiters.obelisk-cli"
        with open(os.path.join(a.generation, "timeline.json")) as f:
            self.manifest = json.load(f)
        self.linux = os.path.join(self.library, "Voile", self.manifest["voile"], "linux")
        self.out = os.path.join(a.out, getattr(a, "series", None) or "", f"{datetime.datetime.now():%Y-%m-%d_%H-%M-%S}")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("OBELISK_")}
        self.bench.RECORDS = f"{self.library}/SteamSessions"
        self.owed = Owed(a.out)
        self.installed, self.restored = False, None
        self.child = self.bench_status = self.note = None  # the bench, how it ended, and the file that says what it started
        self.results, self.published = [], False
        self.hashes = {}

    def cli(self, generation, *words, timeout=300):
        env = self.env | {"OBELISK_DEVELOPER_ENGINE": generation, "OBELISK_DEVELOPER_ENGINE_FILES": self.a.generation}
        command = [self.a.cli] + (["--library", self.a.library] if self.a.library else []) + list(words)
        r = subprocess.run(command, capture_output=True, text=True, timeout=timeout, env=env)
        events = []
        for line in r.stdout.splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
        return r.returncode, events

    def digests(self, which):
        """The files of the generation in the library that are not what `which` ('released' or 'timeline') says."""
        wrong = []
        with open(os.path.join(self.a.generation, "engine-files.json")) as f:
            known = json.load(f)[which]
        for path, digest in sorted(known.items()):
            full = os.path.join(self.linux, path)
            st = os.lstat(full) if os.path.lexists(full) else None
            if st is None or not stat.S_ISREG(st.st_mode) or sha(full) != digest:
                wrong.append(path)
        return wrong

    def fixed(self):
        """What is the same for every start of a series."""
        return dict(generation=sha(os.path.join(self.a.generation, "timeline.json")), cli=sha(self.a.cli), bench=sha(os.path.join(self.a.bench, "bench.py")),
                    reader=sha(f"{HERE}/otl.py"), plan=self.a.plan, passes=self.a.passes, mb=self.a.mb, warm=self.a.warm, window=self.a.window,
                    windows=self.a.windows, place=self.series.place(self.a.link))

    def preflight(self):
        problems = []
        try:
            self.bench.check_link(self.a.link)
            self.bench.profile_arguments()
        except self.bench.Refused as e:
            problems.append(str(e))
        if locked() is not False:
            problems.append("the screen is locked (or its state unknown): unlock it")
        running = engine_running()
        if running:
            problems.append(f"something of the engine runs: {', '.join(running)}: quit it first")
        free = shutil.disk_usage(HOME).free >> 30
        if free < LEAST_FREE:
            problems.append(f"{free} GiB are free, {LEAST_FREE} are needed")
        for path in (self.a.cli, os.path.join(self.a.bench, "bench.py"), os.path.join(HERE, "otl.py"), PICTURE):
            if not os.path.isfile(path):
                problems.append(f"{path} is not there")
        if not self.a.rehearse:
            level = pressure(run(["/usr/bin/notifyutil", "-g", "com.apple.system.thermalpressurelevel"]))
            if level != 0:
                problems.append(f"macOS's thermal pressure is {level}, not 0: wait until the Mac has cooled (notifyutil -g com.apple.system.thermalpressurelevel)")
            if "AC Power" not in run(["/usr/bin/pmset", "-g", "batt"]):
                problems.append("the Mac is not on AC power")
            if os.path.isfile(PICTURE) and run([PICTURE, "may"]).strip() != "yes":
                problems.append("macOS does not let this terminal record windows, and a start without its pictures ends the series: System Settings, Privacy & "
                                "Security, Screen & System Audio Recording")
        if self.series and not problems:
            problems += self.series.problems(self.a.switches, self.fixed(), self.a.nothing_wrong_seen)
        wrong = self.digests("released")
        if wrong:
            problems.append(f"the library's engine files are not the released set this generation was made from: {', '.join(wrong)} (real_session.py --restore puts it back)")
        if self.owed.there():
            problems.append("the released generation is still to be put back (real_session.py --restore)")
        since, why = since_last(self.library, self.bench.boot_clock(), time.time(), self.bench.strict_json)
        if why:
            problems.append(f"{why}: when the last session of this library ended is not known, and nothing is started until it is")
        elif since is not None and since < self.a.between:
            problems.append(f"a session of this library ended {since:.0f} s ago: wait until {self.a.between} s have passed")
        here = os.path.realpath(self.a.out)
        for guest in (self.library, os.path.join(HOME, "Library/Caches/cc.orbiters.obelisk-cli")):
            if (here + "/").startswith(os.path.realpath(guest) + "/"):
                problems.append("the evidence may not be inside what the game sees")
        return problems

    def install(self):
        say("putting the timeline generation in the library")
        self.installed = True  # (from here on it is reverted, whatever happened)
        self.owed.say(when=datetime.datetime.now().isoformat(timespec="seconds"), library=self.library, generation=self.a.generation, cli=self.a.cli, folder=self.out, runner=os.getpid())
        code, events = self.cli("timeline", "engine", "generation")
        write(f"{self.out}/install.json", events)
        wrong = self.digests("timeline")
        if code or wrong:
            raise SystemExit(f"the timeline generation could not be put in place ({json.dumps(events[-1:])[:400]}; not it: {wrong})")

    def step(self, what, otherwise=None):
        """A step of putting things back: what becomes of it keeps none of the others from being made."""
        try:
            return what()
        except Exception as e:  # noqa: BLE001 - told, and the next step is made
            say(f"{type(e).__name__}: {e}")
            return otherwise

    def started(self, told):
        """What the bench says it started (its note), {} for nothing, None for what cannot be known."""
        if not told.get("note"):
            return {}
        try:
            with open(told["note"]) as f:
                note = json.load(f)
            return note if isinstance(note, dict) else None
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            return None

    def lives(self, who):
        """Whether a process noted with its birth is still there."""
        return isinstance(who, dict) and bool(who.get("born")) and self.bench.born(who.get("pid")) == who["born"]

    def alive(self, told):
        """What may still run of a start: the bench, the program it started, the engine's own supervisor (the same program), the engine."""
        out = engine_running()
        cli = os.path.realpath(self.a.cli)
        out += [f"{pid} {os.path.basename(name)}" for pid, (_, name) in processes().items() if os.path.realpath(name) == cli]
        note = self.started(told)
        out += [f"{who['pid']} {name}" for name, who in (("the bench", told.get("bench")), ("the program it started", (note or {}).get("program"))) if self.lives(who)]
        return out

    def restore(self, attempts=8):
        """The released generation put back and proven by every digest; only then is it owed no more. Raises nothing: what goes wrong in one
        attempt is told, and it is tried again."""
        say("putting the released generation back")
        events = []
        for attempt in range(attempts):
            try:
                if attempt:
                    time.sleep(15 if not self.a.rehearse else 2)
                still = self.alive(self.owed.read())
                if still:
                    why = f"{', '.join(still)} still runs"
                else:
                    code, events = self.cli("released", "engine", "generation")
                    wrong = self.digests("released")
                    if code == 0 and not wrong:
                        self.owed.settle()
                        with open(os.path.join(self.a.generation, "engine-files.json")) as f:
                            self.restored = dict(verified=True, when=datetime.datetime.now().isoformat(timespec="seconds"), files=json.load(f)["released"])
                        self.installed = False
                        self.step(lambda: os.path.isdir(self.out) and write(f"{self.out}/revert.json", events))
                        say("the released generation is in place: every engine file is the one released")
                        return True
                    why = f"{json.dumps(events[-1:])[:300]} {wrong}"
            except Exception as e:  # noqa: BLE001 - a timeout or a disk of one attempt ends none but it
                why = f"{type(e).__name__}: {e}"
            say(f"not yet: {why}")
        self.step(lambda: os.path.isdir(self.out) and write(f"{self.out}/revert.json", events))
        say("THE RELEASED ENGINE FILES ARE NOT BACK, and nothing is started until they are. Close VRChat, then run:\n"
            f"  '{os.path.abspath(__file__)}' --restore\n"
            "or, if that cannot:\n"
            f"  OBELISK_DEVELOPER_ENGINE=released OBELISK_DEVELOPER_ENGINE_FILES='{self.a.generation}' '{self.a.cli}' engine generation\n"
            "or: obelisk-cli engine repair")
        return False

    def recover(self):
        """What a start that was cut off still owes (this program was killed): nothing of it runs any more, the released generation is put back
        and proven. False: not, and nothing may be started."""
        told, until = self.owed.read(), time.monotonic() + getattr(self.a, "restore_wait", 900)
        say("a start was cut off: the released generation is still to be put back" if self.owed.there() else "the library's engine files are not the released ones")
        if told.get("library") not in (None, self.library):
            say("that is owed to another library than this one: nothing is done here")
            return False
        slot = self.bench.Slot(recovery=True)
        try:
            while True:
                try:
                    slot.__enter__()  # (no N4N0 starts VRChat meanwhile; its own start, or another of these programs, is waited for)
                    break
                except self.bench.Refused as e:
                    if time.monotonic() > until:
                        say(f"not put back: {e}")
                        return False
                    time.sleep(1)
            if self.lives(told.get("bench")):
                say("the bench of that start still runs: told to stop, it quits its session")
                os.kill(told["bench"]["pid"], signal.SIGINT)
            said = None
            while True:
                still = self.alive(told)
                if not still:
                    break
                if still != said:
                    said = still
                    say(f"waiting until nothing of it runs: {', '.join(still)} (VRChat, if it is still there, is closed by hand)")
                if time.monotonic() > until:
                    say("not put back: it still runs")
                    return False
                time.sleep(1)
            over = self.step(lambda: self.over(told), False)
            if not self.restore():
                return False
            self.step(lambda: self.settle_left(slot, told, over))
            return True
        finally:
            slot.let_go()

    def over(self, told):
        """Whether how a start ended is proven: it started nothing, or the record of its session says so."""
        note = self.started(told)
        return note == {} or bool(note and note.get("session") and self.bench.ended(note["session"]))

    def settle_left(self, slot, told, over):
        """The slot's note, when it is that start's own and how it ended is proven; else it is N4N0's to settle."""
        if slot.noted and slot.noted == told.get("slot") and over:
            slot.settled()
        elif slot.noted:
            say("a start is still noted in N4N0's slot: open Orbiters - N4N0, which settles it")

    def restore_command(self):
        if not self.owed.there() and not self.digests("released"):
            say("nothing is owed: every engine file is the one released")
            return 0
        return 0 if self.recover() else 1

    def stop_bench(self):
        """The bench ended, whoever was told to stop: it quits its session, and has deadlines for it."""
        if self.child is None:
            return
        if self.child.poll() is None:
            say("the bench is told to stop: it quits its session")
            self.child.send_signal(signal.SIGINT)
            try:
                self.child.wait(ENDING)
            except subprocess.TimeoutExpired:
                say("the bench did not end")
                self.child.kill()
                self.child.wait(30)
        self.bench_status = self.child.poll()

    def ended_for_good(self):
        """Whether all that was started is proven to have ended: by the bench's word, or, where it could give none, by the record of its session,
        which is asked to quit by its name once more."""
        if self.child is None or self.bench_status in (0, 2, 3, 4, 6, 7):
            return True
        note = self.started(dict(note=self.note))
        if note == {}:
            return True  # (it was never begun)
        session = (note or {}).get("session")
        if not session:
            return False
        if self.bench.ended(session) is None:
            say("the session of this start is asked to quit")
            self.step(lambda: self.cli("timeline", "steam", "quit", "438100", "--session", session, "--wait", "60", timeout=90))
            until = time.monotonic() + (120 if not self.a.rehearse else 10)
            while self.bench.ended(session) is None and time.monotonic() < until:
                time.sleep(1)
        return self.bench.ended(session) is not None

    def note_slot(self, slot, gone):
        if gone:
            slot.settled()
        else:  # (its session may still run: N4N0 waits for it, as after a start that ended early)
            slot.say((self.started(dict(note=self.note)) or {}).get("session"))

    def publish(self):
        """What the starts came to, the released generation back and proven: only now may a series go on."""
        for result in self.results:
            result["restored"], result["go_on"] = self.restored, not result["why_not"]
            durable(result["path"], result)
        if self.series and self.results:
            result = self.results[-1]
            self.series.ended(result["path"], result["why_not"])
            if result["go_on"]:
                n = len(self.series.told["starts"])
                say(f"start {n} of {STARTS} of the series {self.a.series} went as planned" + (": the series is whole, tools/timeline/score_series.py tells what it says" if n == STARTS else ""))
        self.published = True

    def images(self, pid, name):
        """The files a host program has mapped that are not macOS's own, with their digests."""
        out = {}
        for line in run(["/usr/sbin/lsof", "-a", "-p", str(pid), "-d", "txt", "-Fn"], 30).splitlines():
            path = line[1:]
            if not line.startswith("n/") or path.startswith(("/System/", "/usr/lib/", "/usr/share/", "/Library/Preferences/", "/private/var/db/")):
                continue
            try:
                st = os.stat(path)
                key = (path, st.st_ino, st.st_mtime_ns, st.st_size)
                if st.st_size > 256 << 20 or path.endswith((".metallib", ".data", ".maps", ".car")) or "/com.apple." in path:
                    out[path] = None
                    continue
                if key not in self.hashes:
                    self.hashes[key] = sha(path)
                out[path] = self.hashes[key]
            except OSError as e:
                out[path] = f"<{e}>"
        return dict(pid=pid, name=name, images=out)

    def conditions(self, folder, stop):
        """Every 10 s: the CPU of what uses most, the power and heat states; once per host program: what it loaded."""
        seen, began, n = {}, time.time(), 0
        with open(os.open(f"{folder}/conditions.jsonl", os.O_WRONLY | os.O_CREAT, 0o600), "w") as f:
            while not stop.is_set():
                look = dict(wall=time.time(), uptime_ns=time.clock_gettime_ns(time.CLOCK_UPTIME_RAW), monotonic=time.monotonic(), locked=locked())
                if n % 2 == 0:
                    top = run(["/usr/bin/top", "-l", "2", "-s", "1", "-n", "20", "-o", "cpu", "-stats", "pid,cpu,command"], 20)
                    rows = [l.split(None, 2) for l in top.split("PID")[-1].splitlines()[1:] if l.strip()]
                    look["top"] = [dict(pid=int(r[0].rstrip("*+-")), cpu=float(r[1]), name=r[2].strip()) for r in rows if len(r) == 3 and re.fullmatch(r"\d+[*+-]?", r[0])]
                    look["thermal_pressure"] = run(["/usr/bin/notifyutil", "-g", "com.apple.system.thermalpressurelevel"]).strip()
                    look["therm"] = run(["/usr/bin/pmset", "-g", "therm"])
                    look["power"] = run(["/usr/bin/pmset", "-g", "batt"]).splitlines()[:2]
                    look["low_power_mode"] = (re.search(r"lowpowermode\s+(\d)", run(["/usr/bin/pmset", "-g"])) or [None, None])[1]
                f.write(json.dumps(look) + "\n")
                f.flush()
                for pid, (_, name) in processes().items():
                    base = os.path.basename(name)
                    if base in HOST and pid not in seen and time.time() - began > 3:
                        seen[pid] = dict(self.images(pid, base), at=time.time())
                        write(f"{folder}/images.json", list(seen.values()))
                    elif base in HOST and pid in seen and time.time() - seen[pid]["at"] > 20 and not seen[pid].get("again"):
                        seen[pid] = dict(self.images(pid, base), at=time.time(), again=True)  # what it loaded since
                        write(f"{folder}/images.json", list(seen.values()))
                n += 1
                stop.wait(5)

    def allowed_images(self, folder):
        """Images of the host programs that are neither the generation's own files nor macOS's."""
        with open(os.path.join(self.a.generation, "engine-files.json")) as f:
            known = set(json.load(f)["timeline_graphics"].values())
        bad = []
        try:
            with open(f"{folder}/images.json") as f:
                seen = json.load(f)
        except OSError:
            return ["no host program was seen"]
        for p in seen:
            for path, digest in p["images"].items():
                if digest and digest not in known and path.endswith((".dylib", "dxmt-native", *HOST)):
                    bad.append(f"{p['name']} {p['pid']}: {path} {digest[:16]}")
        return bad

    def not_in_the_inventory(self, folder, files, queues):
        """Of what every process that recorded must have mapped, what is not in the inventory with the generation's digest. Of the render server's
        workers, the game's (`queues`): one that lived for a moment is in no inventory."""
        with open(os.path.join(self.a.generation, "engine-files.json")) as f:
            known = json.load(f)["timeline_graphics"]
        try:
            with open(f"{folder}/images.json") as f:
                seen = {p["pid"]: {os.path.basename(path): digest for path, digest in p["images"].items()} for p in json.load(f)}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return ["no host program was seen"]
        game, expected = {q[0] for q in queues or []}, {}
        for path in files:
            _, role, pid = os.path.basename(path)[: -len(".bin")].split("-")
            if role in ("wsd", "vtest") or int(pid) in game:
                expected.setdefault(role, []).append(int(pid))
        out = [f"no process of {role}" for role in INVENTORY if role not in expected]
        for role, pids in expected.items():
            for pid in pids:
                missing = [os.path.basename(p) for p in INVENTORY.get(role, ()) if not known.get(p) or seen.get(pid, {}).get(os.path.basename(p)) != known[p]]
                if missing:
                    out.append(f"{role} {pid}: {', '.join(missing)} " + ("not the generation's, or not there" if pid in seen else "(it was not looked at)"))
        return out

    def start(self, percent):
        named = "".join(f"-{n}-{v.replace(',', '-')}" for n, (k, _) in SWITCHES.items() for v in [self.a.switches.get(k)] if v)
        folder = os.path.join(self.out, f"start-{percent}{named}")
        trace = os.path.join(folder, "trace")
        os.makedirs(trace, mode=0o700)
        say(f"start at {percent} %" + "".join(f", {k}={v}" for k, v in self.a.switches.items()))
        env = self.env | {"OBELISK_DEVELOPER_ENGINE": "timeline", "OBELISK_DEVELOPER_ENGINE_FILES": self.a.generation,
                          "OBELISK_TIMELINE": trace, "OBELISK_TIMELINE_PASSES": str(self.a.passes), "OBELISK_TIMELINE_MB": str(self.a.mb)} | self.a.switches
        command = ["/usr/bin/python3", "-I", os.path.join(self.a.bench, "bench.py"), "--cli", self.a.cli, "--percent", str(percent), "--label",
                   str(percent), "--link", self.a.link, "--warm", str(self.a.warm), "--window", str(self.a.window), "--windows",
                   str(self.a.windows), "--no-sample", "--slot-held", "--caller", str(os.getpid()), "--note", f"{folder}/started.json", "--picture", f"{folder}/picture", "--picture-tool", PICTURE, "--picture-at",
                   str(max(1, min(100, self.a.warm - 20))), "--out", f"{folder}/bench.json"]
        stop = threading.Event()
        watcher = threading.Thread(target=self.conditions, args=(folder, stop), daemon=True)
        watcher.start()
        cut = None
        try:
            with open(os.open(f"{folder}/bench.log", os.O_WRONLY | os.O_CREAT, 0o600), "w") as log:
                self.note = f"{folder}/started.json"
                self.owed.say(note=self.note)
                self.cut.hold()  # (no signal between its start and its being known)
                # (a session of its own: a terminal's Ctrl-C reaches this program alone, which tells it once)
                self.child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
                self.owed.say(bench=dict(pid=self.child.pid, born=self.bench.born(self.child.pid)))
                self.cut.let()
                self.child.wait()
        except KeyboardInterrupt as e:
            cut = e
        finally:
            self.cut.hold()
            self.stop_bench()
            stop.set()
            self.step(lambda: watcher.join(40))
            self.step(lambda: self.keep(folder))
        if cut is not None:
            raise cut
        self.cut.let()
        return self.report(folder, trace, percent, self.bench_status)

    def keep(self, folder):
        """The session's own logs, as they are now."""
        logs = f"{HOME}/Library/Logs/Obelisk/Steam"
        try:
            with open(f"{folder}/bench.json") as f:
                session = json.load(f).get("session")
        except (OSError, ValueError):
            session = None
        wanted = [f"{logs}/wine-438100.log", f"{logs}/wine-438100.lkd-events"]
        if session:
            wanted.append(f"{self.library}/SteamSessions/{session}.v2.json")
        vrchat = f"{self.library}/Prefixes/steam-438100-windows-linux/prefix/drive_c/users/crossover/AppData/LocalLow/VRChat/VRChat/output_log_*.txt"
        wanted += sorted(glob.glob(vrchat), key=os.path.getmtime)[-1:]
        for path in wanted:
            try:
                shutil.copyfile(path, os.path.join(folder, os.path.basename(path)))
                os.chmod(os.path.join(folder, os.path.basename(path)), 0o600)
            except OSError as e:
                say(f"not kept: {os.path.basename(path)} ({e.strerror})")

    def clocks(self, folder, bench):
        """A time of the bench's own clock (its process's, whatever that counts from) in uptime nanoseconds, the trace's: by the
        wall clock both it and the conditions noted, at the moment nearest to it."""
        looks = [(x["at"], x["wall"]) for x in bench.get("observed", {}).get("look", [])]
        marks = []
        try:
            with open(f"{folder}/conditions.jsonl") as f:
                for line in f:
                    x = json.loads(line)
                    marks.append((x["wall"], x["uptime_ns"]))
        except (OSError, ValueError):
            pass
        if not looks or not marks:
            return None

        def told(at):
            near = min(looks, key=lambda x: abs(x[0] - at))
            wall = near[1] + (at - near[0])
            mark = min(marks, key=lambda x: abs(x[0] - wall))
            return int(mark[1] + (wall - mark[0]) * 1e9)
        return told

    def report(self, folder, trace, percent, status):
        """One line per window of what is known of it, and whether the series may go on."""
        result = dict(percent=percent, switches=self.a.switches, bench_status=status, windows=[])
        traces = sorted(d for d in glob.glob(f"{trace}/*") if os.path.isdir(d))
        files = sorted(glob.glob(f"{trace}/*/otl-*.bin"))
        result["roles"] = sorted({os.path.basename(f).split("-")[1] for f in files})
        result["trace_files"] = {os.path.relpath(f, trace): dict(bytes=os.path.getsize(f), sha256=sha(f)) for f in files}
        result["foreign_images"] = self.allowed_images(folder)
        result["restored"], result["go_on"] = None, False  # (publish(): once the released generation is back)
        try:
            with open(f"{folder}/bench.json") as f:
                bench = json.load(f)
        except (OSError, ValueError):
            bench = dict(windows=[], outcome="no result")
        result["outcome"] = bench.get("outcome")
        result["session"] = bench.get("session")
        result["brought_to_front"] = bench.get("observed", {}).get("fronted")
        result["pictures"] = bench.get("pictures")
        result["terminal"] = bench.get("terminal")
        looks = []
        try:
            with open(f"{folder}/conditions.jsonl") as f:
                looks = [json.loads(line) for line in f]
        except (OSError, ValueError):
            pass
        taken = [p for p in result["pictures"] or [] if p["file"]]
        say(f"  {len(taken)} pictures of the game's window" + (f" {taken[0]['after_arrival_s']:.1f} s after the arrival" if taken else " (macOS may not let this terminal record windows)"))
        clocks = self.clocks(folder, bench)
        stamped = [w for w in bench.get("windows", []) if "from_uptime_ns" in w]
        plane = None
        if len(traces) == 1 and stamped:
            # which of the window server's planes is the game's: the one most of the frames of all its windows are of
            text = run(["/usr/bin/python3", "-I", f"{HERE}/otl.py", traces[0], "--from", str(stamped[0]["from_uptime_ns"]), "--to", str(stamped[-1]["to_uptime_ns"]),
                        "--plane", "game", "--json", f"{folder}/plane.json"], 600)
            write(f"{folder}/plane.txt", text)
            try:
                with open(f"{folder}/plane.json") as f:
                    one = json.load(f)["reports"][0]
                plane, result["plane"], result["plane_share"], result["queues"] = one["plane"], one["plane"], one["plane_share"], one["queues"]
            except (OSError, ValueError, KeyError, IndexError):
                pass
        for i, w in enumerate(bench.get("windows", []), 1):
            told = dict(window=i, valid=w["valid"], why=w["invalid_because"], submitted=w["guest_present"]["submitted_per_second_counted"],
                        fence_wait_ms=w["guest_present"]["fence_wait_ms_median"], hud_per_s=w["wsd_shown"]["per_second"],
                        shown_per_s=None, from_s=w.get("from_s"), arrived_after_s=bench.get("arrived_after_s"))
            if len(traces) == 1 and ("from_uptime_ns" in w or clocks):
                base = f"{folder}/window-{i}"
                if "from_uptime_ns" in w:  # stamped on the trace's own clock as it was cut
                    told["from_ns"], told["to_ns"], told["clock"] = w["from_uptime_ns"], w["to_uptime_ns"], "stamped"
                else:
                    told["from_ns"], told["to_ns"], told["clock"] = clocks(w["from"]), clocks(w["to"]), "by the wall clock"
                told["conditions"] = window_conditions(looks, told["from_ns"], told["to_ns"])
                text = run(["/usr/bin/python3", "-I", f"{HERE}/otl.py", traces[0], "--from", str(told["from_ns"]), "--to", str(told["to_ns"]),
                            *(["--plane", str(plane)] if plane is not None else []), "--passes", "--splits", "--cadence", "--csv", f"{base}.csv", "--json", f"{base}.json"], 600)
                write(f"{base}.txt", text)
                try:
                    with open(f"{base}.json") as f:
                        read = json.load(f)
                    one = read["reports"][0]
                    told["splits"] = one.get("splits")
                    for k in ("queries", "queries_of_every_queue", "production", "work", "seconds", "whole_share", "trace_not_complete", "plane", "queues"):
                        told[k] = one.get(k)
                    told.update(lost=read["lost"], not_told=read["not_told"], frames=one["frames"], whole=one["whole"], not_whole=one["not_whole"],
                                cadence=[{k: c[k] for k in ("plane", "window", "region", "seconds", "received", "received_per_s", "replaced", "shown",
                                                            "shown_per_s", "zero_time", "redisplays_shown", "refresh_ms", "leading_gap_ms", "trailing_gap_ms",
                                                            "largest_gap_ms", "holds_of_3_refreshes_or_more", "shown_interval_ms", "tick_to_shown_ms", "client_to_shown_ms", "gpu_ms",
                                                            "drawn_on_arrival", "drawn_scaled")} for c in one.get("cadence", [])])
                    if plane is not None and len(told["cadence"]) == 1:
                        told["shown_per_s"] = told["cadence"][0]["shown_per_s"]
                except (OSError, ValueError, KeyError, IndexError) as e:
                    told["reader"] = f"failed: {e}"
            result["windows"].append(told)
        for told in result["windows"]:
            rate = f"{told['shown_per_s']:.2f}" if told["shown_per_s"] is not None else "not told"
            say(f"  window {told['window']}: {'valid' if told['valid'] else 'INVALID ' + '; '.join(told['why'])}; shown {rate}/s, "
                f"frames {told.get('frames')}, whole {told.get('whole')}, lost {told.get('lost')}")
        if result["foreign_images"]:
            say(f"  HOST PROGRAMS LOADED WHAT IS NOT THE GENERATION'S: {result['foreign_images']}")
        say(f"  {result['outcome']}; {len(files)} trace files of {', '.join(result['roles']) or 'no role'}")
        result["not_in_the_inventory"] = self.not_in_the_inventory(folder, files, result.get("queues"))
        result["not_corroborated"] = [f"window {w['window']}: {x}" for w in result["windows"] for x in [uncorroborated(w.get("queries_of_every_queue"))] if x]
        for x in result["not_corroborated"]:
            say(f"  {x}")
        result["why_not"] = judge(result, self.a.windows, self.a.switches.get("OBELISK_DXMT_QUERY_RESCUE") == "once", self.series.first() if self.series else None)
        result["path"] = f"{folder}/result.json"
        for why in result["why_not"]:
            say(f"  NOT AS IT IS MEANT TO BE: {why}")
        write(f"{folder}/result.json", result)
        return result

    def main(self):
        if self.owed.there() and not self.recover():
            print("Not started:\n  the released generation is still to be put back (real_session.py --restore)", file=sys.stderr)
            return 1
        try:
            with self.bench.Slot() as slot:  # (until the released generation is back: no N4N0 starts VRChat meanwhile)
                problems = self.preflight()
                if problems:
                    print("Not started:\n  " + "\n  ".join(problems), file=sys.stderr)
                    return 1
                return self.starts(slot)
        except self.bench.Refused as e:
            print(f"Not started:\n  {e}", file=sys.stderr)
            return 1

    def starts(self, slot):
        numbers, awake, back = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP), None, False
        os.makedirs(self.out, mode=0o700)
        for number in numbers:
            signal.signal(number, self.cut)
        try:
            # (the inner one first: once it is past, or cut, nothing raises in the outer one)
            try:
                awake = subprocess.Popen(["/usr/bin/caffeinate", "-dimsu", "-w", str(os.getpid())], stdout=subprocess.DEVNULL)  # (gone with this program)
                self.measure(slot)
            finally:
                for number in numbers:
                    signal.signal(number, signal.SIG_IGN)
        except KeyboardInterrupt:
            say("interrupted")
        finally:
            self.cut.hold()
            for number in numbers:
                signal.signal(number, signal.SIG_IGN)
            back = self.put_back(slot)
            self.step(lambda: awake and awake.terminate())
            self.step(lambda: write(f"{self.out}/results.json", self.results))
            say(f"the evidence is in {self.out}")
        return 0 if back and self.published and len(self.results) == len(self.a.plan) and all(r["go_on"] for r in self.results) else 1

    def put_back(self, slot):
        """Its session ended, the released generation back and proven, then what the starts came to; each step whatever became of the others."""
        self.step(self.stop_bench)
        gone = self.step(self.ended_for_good, False)
        back = self.restore() if self.installed else True
        if back:
            self.step(self.publish)
        self.step(lambda: self.note_slot(slot, gone))
        return back

    def measure(self, slot):
        write(f"{self.out}/manifest.json", dict(
            when=datetime.datetime.now().isoformat(timespec="seconds"), plan=self.a.plan, switches=self.a.switches, passes=self.a.passes, mb=self.a.mb, warm=self.a.warm,
            window=self.a.window, windows=self.a.windows, generation=self.manifest, cli=dict(path=self.a.cli, sha256=sha(self.a.cli)),
            version=self.cli("released", "--version")[1], bench_sha256=sha(os.path.join(self.a.bench, "bench.py")), reader_sha256=sha(f"{HERE}/otl.py"),
            os=run(["/usr/bin/sw_vers"]), hardware=run(["/usr/sbin/sysctl", "-n", "hw.model", "machdep.cpu.brand_string", "hw.memsize"]).split("\n"),
            display=run(["/usr/sbin/system_profiler", "SPDisplaysDataType"], 60), pmset=run(["/usr/bin/pmset", "-g", "custom"]),
            powermetrics="not available without root: GPU clock, residency and power are unknown",
            clocks=dict(wall=time.time(), monotonic=time.monotonic(), uptime_ns=time.clock_gettime_ns(time.CLOCK_UPTIME_RAW))))
        self.install()
        ended = None
        for percent in self.a.plan:
            if ended is not None:
                left = self.a.between - (time.time() - ended)
                say(f"waiting {left:.0f} s before the next start")
                time.sleep(max(0, left))
            if locked() is not False:
                say("the screen is locked: the series ends here")
                break
            running = engine_running()
            if running:
                say(f"something of the engine runs ({running}): the series ends here")
                break
            if self.series:
                self.series.begin(self.a.switches, self.fixed(), self.out, self.a.nothing_wrong_seen)
            slot.say(None)
            self.owed.say(slot=slot.noted)
            result = self.start(percent)
            ended = time.time()
            self.results.append(result)
            if result["why_not"]:
                say("this start did not go as planned: no other is made, and none replaces it")
                break


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("link", nargs="?")
    p.add_argument("--restore", action="store_true", help="put the released generation back after a start that was cut off; start nothing")
    p.add_argument("--cli", default=f"{HOME}/.orbiters-forks/timeline-cli/obelisk-cli")
    p.add_argument("--generation", default=f"{HOME}/.orbiters-forks/timeline-generation")
    p.add_argument("--bench", default=HERE)
    p.add_argument("--switch", action="append", default=[], metavar="NAME=VALUE")
    p.add_argument("--out", default=f"{HOME}/Library/Logs/Obelisk/timeline-sessions")
    p.add_argument("--passes", type=int, default=8)
    p.add_argument("--mb", type=int, default=1536)
    p.add_argument("--plan")
    p.add_argument("--series")
    p.add_argument("--nothing-wrong-seen", action="store_true")
    # for the rehearsal (tools/timeline/rehearse.py) alone
    for name, value in (("--warm", 120), ("--window", 60), ("--windows", 3), ("--between", BETWEEN)):
        p.add_argument(name, type=int, default=value, help=argparse.SUPPRESS)
    p.add_argument("--library", help=argparse.SUPPRESS)
    p.add_argument("--rehearse", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--restore-wait", type=int, default=900, help=argparse.SUPPRESS)
    a = p.parse_args()
    a.cli, a.generation, a.bench, a.out = (os.path.abspath(os.path.expanduser(x)) for x in (a.cli, a.generation, a.bench, a.out))
    if a.restore:
        if a.link or a.plan or a.switch or a.series or (a.library and not a.rehearse):
            p.error("--restore starts nothing: it takes no link, plan, switch or series")
        a.series = None
        return Session(a).restore_command()
    if a.link is None or a.plan is None:
        p.error("the link of the owner's private instance and --plan are needed")
    a.plan = [int(x) for x in a.plan.split(",")]
    if not all(1 <= x <= 100 for x in a.plan) or len(a.plan) > (3 if a.rehearse else 1):
        p.error("one scale of 1 to 100 (one start per invocation)")
    try:
        a.switches = switches(a.switch)
    except ValueError as e:
        p.error(str(e))
    if not (1 <= a.passes <= 1000 and 64 <= a.mb <= 8192):
        p.error("--passes is 1 to 1000, --mb 64 to 8192")
    if a.series is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", a.series):
        p.error("--series is a name of letters, digits, - and _")
    if not a.rehearse:
        if a.series is None:
            p.error("--series names the series this start is of (the same for its three starts)")
        if not re.match(r"vrchat://launch\?", a.link) or "~private(" not in a.link:
            p.error("the link of a private instance of the owner's is needed (vrchat://launch?...~private(usr_...)...)")
        if a.warm < 120 or a.window < 60 or a.windows < 3 or a.between < BETWEEN or a.library:
            p.error("a real session warms 120 s, scores three windows of 60 s, waits 90 s between starts and uses the library of obelisk-cli")
    if a.series is not None and len(a.plan) > 1:
        p.error("a start of a series is at one scale")
    return Session(a).main()


if __name__ == "__main__":
    sys.exit(main())
