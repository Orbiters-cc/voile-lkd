#!/usr/bin/env python3
"""One real start with the host timeline at one scale, with a named combination of switches; never a replacement.

Usage: real_session.py '<the owner's private instance link>' --plan 45 [--switch upscale=metalfx] [--switch present=arrival]

One start per invocation: the timeline generation is put in place for it and the released one put back after it, whatever
happened. At the Mac, unlocked, plugged in, idle and cool, hands off for about eight minutes. The options:
  --switch NAME=VALUE  upscale=metalfx: wsd scales a frame smaller than the window with MetalFX Spatial; present=<list> of arrival,
                       attime, nosync, two: how wsd presents (wsd/wsd.m says what each is); queries=once: DXMT's looks at an event query
                       that is not there flush once, not at each look (dxmt, src/d3d11/d3d11_query.hpp). None is the programs as ever.
                       They reach wsd, and the last the render server, alone (launch.sh), never the game. In the manifest, the
                       result and the folder's name
  --cli PATH         the developer's obelisk-cli (feature developer-timeline), signed as the one that holds the Steam session
  --generation DIR   what scripts/build-timeline-generation.sh of the Obelisk fork wrote
  --bench DIR        the folder of bench.py (this one)
  --out DIR          the evidence, one folder per session, readable by this user alone
  --passes N         the encoders and their GPU times of every Nth frame, the same at every scale (8)
  --mb N             the trace's budget per start, in MiB (1536)
  --plan 45          the scale, 1 to 100: one

What it does: refuses when the screen is locked, when anything of the engine runs, when the disk is short; holds the display
awake; puts the timeline generation in the library through the developer's obelisk-cli (verified, atomic, pinned, refused while
anything of the engine runs); then one start by bench.py (arrival, the game's app brought to the front, 120 s warm, three windows
of 60 s cut on the trace's own clock, no stack sample, its own session quit by session; 100 s after the arrival three pictures of the
game's window alone, picture-1.png to -3.png in the start's folder: compare_pictures.py tells two starts' apart from what moves by itself), at least 90 s after the last start this
library knows of ended; and in every case, interrupted or failed, puts the
released generation back through the same program and proves it by every digest. A start that fails ends the series. Nothing of
the game is attached to, sampled or touched: of the host programs, what macOS says from outside (ps, lsof, pmset, notifyutil).

Interrupted with Ctrl-C, it still quits its session and reverts. If it was killed, by hand, once VRChat is closed:
  OBELISK_DEVELOPER_ENGINE=released OBELISK_DEVELOPER_ENGINE_FILES=<generation> <cli> engine generation
(or obelisk-cli engine repair of any released obelisk-cli, which lays the whole release again).
"""
import argparse, datetime, glob, hashlib, json, os, re, shutil, signal, stat, subprocess, sys, threading, time

HOME = os.path.expanduser("~")
HERE = os.path.dirname(os.path.abspath(__file__))
BETWEEN = 90       # s after a start's session ended before the next
LEAST_FREE = 8     # GiB
HOST = ("wsd", "virgl_test_server", "virgl_render_server")
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


signalled = []  # what this program was told to stop with


def interrupted(number, _):
    signalled.append(number)
    raise KeyboardInterrupt


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


def processes():
    """pid -> (parent, program), by path alone: never a command line."""
    out = {}
    for line in run(["/bin/ps", "-A", "-ww", "-o", "pid=,ppid=,comm="]).splitlines():
        p = line.split(None, 2)
        if len(p) == 3 and p[0].isdigit():
            out[int(p[0])] = (int(p[1]), p[2])
    return out


SWITCHES = {"upscale": ("OBELISK_WSD_UPSCALE", {"metalfx"}), "present": ("OBELISK_WSD_PRESENT", {"arrival", "attime", "nosync", "two"}),
            "queries": ("OBELISK_DXMT_QUERY_RESCUE", {"once"})}
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


def last_ended(library):
    """When the last session of this library ended, as its record was last written, or None when there is none. A record that
    cannot be read counts as one that has just been written."""
    newest = None
    for path in glob.glob(f"{library}/SteamSessions/*.v2.json"):
        try:
            newest = max(newest or 0, os.path.getmtime(path))
        except OSError:
            newest = time.time()
    return newest


def engine_running():
    return [f"{pid} {os.path.basename(name)}" for pid, (_, name) in processes().items() if ENGINE.search(name)]


class Session:
    def __init__(self, a):
        self.a = a
        self.library = a.library or f"{HOME}/Library/Application Support/cc.orbiters.obelisk-cli"
        with open(os.path.join(a.generation, "timeline.json")) as f:
            self.manifest = json.load(f)
        self.linux = os.path.join(self.library, "Voile", self.manifest["voile"], "linux")
        self.out = os.path.join(a.out, f"{datetime.datetime.now():%Y-%m-%d_%H-%M-%S}")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("OBELISK_")}
        self.installed = False
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

    def preflight(self):
        problems = []
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
        wrong = self.digests("released")
        if wrong:
            problems.append(f"the library's engine files are not the released set this generation was made from: {', '.join(wrong)}")
        ended = last_ended(self.library)
        if ended is not None and 0 <= time.time() - ended < self.a.between:
            problems.append(f"a session of this library ended {time.time() - ended:.0f} s ago: wait until {self.a.between} s have passed")
        here = os.path.realpath(self.a.out)
        for guest in (self.library, os.path.join(HOME, "Library/Caches/cc.orbiters.obelisk-cli")):
            if (here + "/").startswith(os.path.realpath(guest) + "/"):
                problems.append("the evidence may not be inside what the game sees")
        return problems

    def install(self):
        say("putting the timeline generation in the library")
        self.installed = True  # (from here on it is reverted, whatever happened)
        code, events = self.cli("timeline", "engine", "generation")
        write(f"{self.out}/install.json", events)
        wrong = self.digests("timeline")
        if code or wrong:
            raise SystemExit(f"the timeline generation could not be put in place ({json.dumps(events[-1:])[:400]}; not it: {wrong})")

    def revert(self):
        say("putting the released generation back")
        for attempt in range(8):
            code, events = self.cli("released", "engine", "generation")
            wrong = self.digests("released")
            if code == 0 and not wrong:
                write(f"{self.out}/revert.json", events)
                self.installed = False
                say("the released generation is in place: every engine file is the one released (revert.json)")
                return True
            say(f"not yet: {json.dumps(events[-1:])[:300]} {wrong}")
            time.sleep(15 if not self.a.rehearse else 2)
        write(f"{self.out}/revert.json", events)
        say("THE RELEASED ENGINE FILES ARE NOT BACK. Close VRChat, then run:\n"
            f"  OBELISK_DEVELOPER_ENGINE=released OBELISK_DEVELOPER_ENGINE_FILES='{self.a.generation}' '{self.a.cli}' engine generation\n"
            "or: obelisk-cli engine repair")
        return False

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
                   str(self.a.windows), "--no-sample", "--picture", f"{folder}/picture", "--picture-tool", PICTURE, "--picture-at",
                   str(max(1, min(100, self.a.warm - 20))), "--out", f"{folder}/bench.json"]
        stop = threading.Event()
        watcher = threading.Thread(target=self.conditions, args=(folder, stop), daemon=True)
        watcher.start()
        status, cut = None, None
        with open(os.open(f"{folder}/bench.log", os.O_WRONLY | os.O_CREAT, 0o600), "w") as log:
            bench = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=env)
            while status is None:
                try:
                    status = bench.wait()
                except KeyboardInterrupt as e:
                    if cut is None:
                        # It quits its own session, whoever was told to stop, and that is waited for (it has deadlines).
                        cut = e
                        say("interrupted: the bench quits its session")
                        if signalled[-1:] != [signal.SIGINT]:
                            bench.send_signal(signal.SIGINT)
        stop.set()
        watcher.join(40)
        self.keep(folder)
        if cut is not None:
            raise cut
        return self.report(folder, trace, percent, status)

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
        try:
            with open(f"{folder}/bench.json") as f:
                bench = json.load(f)
        except (OSError, ValueError):
            bench = dict(windows=[], outcome="no result")
        result["outcome"] = bench.get("outcome")
        result["brought_to_front"] = bench.get("observed", {}).get("fronted")
        result["pictures"] = bench.get("pictures")
        taken = [p for p in result["pictures"] or [] if p["file"]]
        say(f"  {len(taken)} pictures of the game's window" + (f" {taken[0]['after_arrival_s']:.1f} s after the arrival" if taken else " (macOS may not let this terminal record windows)"))
        clocks = self.clocks(folder, bench)
        for i, w in enumerate(bench.get("windows", []), 1):
            told = dict(window=i, valid=w["valid"], why=w["invalid_because"], submitted=w["guest_present"]["submitted_per_second_counted"],
                        fence_wait_ms=w["guest_present"]["fence_wait_ms_median"], shown_per_s=w["wsd_shown"]["per_second"])
            if len(traces) == 1 and ("from_uptime_ns" in w or clocks):
                base = f"{folder}/window-{i}"
                if "from_uptime_ns" in w:  # stamped on the trace's own clock as it was cut
                    told["from_ns"], told["to_ns"], told["clock"] = w["from_uptime_ns"], w["to_uptime_ns"], "stamped"
                else:
                    told["from_ns"], told["to_ns"], told["clock"] = clocks(w["from"]), clocks(w["to"]), "by the wall clock"
                text = run(["/usr/bin/python3", "-I", f"{HERE}/otl.py", traces[0], "--from", str(told["from_ns"]), "--to", str(told["to_ns"]),
                            "--passes", "--splits", "--cadence", "--csv", f"{base}.csv", "--json", f"{base}.json"], 600)
                write(f"{base}.txt", text)
                try:
                    with open(f"{base}.json") as f:
                        read = json.load(f)
                    one = read["reports"][0]
                    told["splits"] = one.get("splits")
                    told["queries"] = one.get("queries")
                    told.update(lost=read["lost"], not_told=read["not_told"], frames=one["frames"], whole=one["whole"], not_whole=one["not_whole"],
                                cadence=[{k: c[k] for k in ("plane", "window", "region", "received", "replaced", "shown", "shown_per_s", "zero_time",
                                                            "shown_interval_ms", "tick_to_shown_ms", "client_to_shown_ms", "gpu_ms",
                                                            "drawn_on_arrival", "drawn_scaled")} for c in one.get("cadence", [])])
                except (OSError, ValueError, KeyError, IndexError) as e:
                    told["reader"] = f"failed: {e}"
            result["windows"].append(told)
        write(f"{folder}/result.json", result)
        for told in result["windows"]:
            if told.get("frames") == 0:
                result["no_frames"] = True
            say(f"  window {told['window']}: {'valid' if told['valid'] else 'INVALID ' + '; '.join(told['why'])}; shown {told['shown_per_s']}/s, "
                f"frames {told.get('frames')}, whole {told.get('whole')}, lost {told.get('lost')}")
        if result["foreign_images"]:
            say(f"  HOST PROGRAMS LOADED WHAT IS NOT THE GENERATION'S: {result['foreign_images']}")
        say(f"  {result['outcome']}; {len(files)} trace files of {', '.join(result['roles']) or 'no role'}")
        result["go_on"] = status == 0 and not result.get("no_frames") and not result["foreign_images"] and {"wsd", "vtest", "npt", "dxmt"} <= set(result["roles"])
        return result

    def main(self):
        problems = self.preflight()
        if problems:
            print("Not started:\n  " + "\n  ".join(problems), file=sys.stderr)
            return 1
        os.makedirs(self.out, mode=0o700)
        for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(number, interrupted)
        awake = subprocess.Popen(["/usr/bin/caffeinate", "-dimsu", "-w", str(os.getpid())], stdout=subprocess.DEVNULL)  # (gone with this program)
        results = []
        try:
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
                result = self.start(percent)
                ended = time.time()
                results.append(result)
                if not result["go_on"]:
                    say("this start did not go as planned: no other is made, and none replaces it")
                    break
        except KeyboardInterrupt:
            say("interrupted")
        finally:
            for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                signal.signal(number, signal.SIG_IGN)
            back = self.revert() if self.installed else True
            awake.terminate()
            write(f"{self.out}/results.json", results)
            say(f"the evidence is in {self.out}")
        return 0 if back and len(results) == len(self.a.plan) and all(r["go_on"] for r in results) else 1


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("link")
    p.add_argument("--cli", default=f"{HOME}/.orbiters-forks/timeline-cli/obelisk-cli")
    p.add_argument("--generation", default=f"{HOME}/.orbiters-forks/timeline-generation")
    p.add_argument("--bench", default=HERE)
    p.add_argument("--switch", action="append", default=[], metavar="NAME=VALUE")
    p.add_argument("--out", default=f"{HOME}/Library/Logs/Obelisk/timeline-sessions")
    p.add_argument("--passes", type=int, default=8)
    p.add_argument("--mb", type=int, default=1536)
    p.add_argument("--plan", required=True)
    # for the rehearsal (tools/timeline/rehearse.py) alone
    for name, value in (("--warm", 120), ("--window", 60), ("--windows", 3), ("--between", BETWEEN)):
        p.add_argument(name, type=int, default=value, help=argparse.SUPPRESS)
    p.add_argument("--library", help=argparse.SUPPRESS)
    p.add_argument("--rehearse", action="store_true", help=argparse.SUPPRESS)
    a = p.parse_args()
    a.plan = [int(x) for x in a.plan.split(",")]
    if not all(1 <= x <= 100 for x in a.plan) or len(a.plan) > (3 if a.rehearse else 1):
        p.error("one scale of 1 to 100 (one start per invocation)")
    try:
        a.switches = switches(a.switch)
    except ValueError as e:
        p.error(str(e))
    if not (1 <= a.passes <= 1000 and 64 <= a.mb <= 8192):
        p.error("--passes is 1 to 1000, --mb 64 to 8192")
    if not a.rehearse:
        if not re.match(r"vrchat://launch\?", a.link) or "~private(" not in a.link:
            p.error("the link of a private instance of the owner's is needed (vrchat://launch?...~private(usr_...)...)")
        if a.warm < 120 or a.window < 60 or a.windows < 3 or a.between < BETWEEN or a.library:
            p.error("a real session warms 120 s, scores three windows of 60 s, waits 90 s between starts and uses the library of obelisk-cli")
    a.cli, a.generation, a.bench, a.out = (os.path.abspath(os.path.expanduser(x)) for x in (a.cli, a.generation, a.bench, a.out))
    return Session(a).main()


if __name__ == "__main__":
    sys.exit(main())
