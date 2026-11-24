#!/usr/bin/env python3
"""The released generation is back, whatever became of a start (tools/timeline/real_session.py): the runner itself in a process of its own, in a
scratch home and library, killed, interrupted and made to fail at each step; where the bench takes part it is the real one, and a program that
answers as obelisk-cli does stands in the game's place. No game, nothing of this Mac's own. Run: python3 -I test_restoration.py

TIMELINE_REAL=1: the same with the developer's obelisk-cli and generation (TIMELINE_CLI, TIMELINE_GENERATION) on a clone of the release
(TIMELINE_RELEASE), each in a scratch library; `steam` is the stand-in's all the same."""
import hashlib, json, os, shutil, signal, subprocess, sys, tempfile, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.realpath(os.path.join(HERE, "../../tools/timeline"))
LINK = "vrchat://launch?ref=orbiters.cc&id=wrld_00000000-0000-0000-0000-000000000000:12345~private(usr_test)~region(eu)"
REAL = bool(os.environ.get("TIMELINE_REAL"))
FORKS = os.path.expanduser("~/.orbiters-forks")
CLI = os.environ.get("TIMELINE_CLI", f"{FORKS}/timeline-cli/obelisk-cli")
GENERATION = os.environ.get("TIMELINE_GENERATION", f"{FORKS}/timeline-generation")
RELEASE = os.environ.get("TIMELINE_RELEASE", f"{FORKS}/voile-release/pristine/voile-v26.3.0-27.beta1")

# obelisk-cli: `engine generation` puts one in place (or is the real one's), refused while the game runs; `steam play` and `steam quit`.
FAKE_CLI = r"""#!/usr/bin/env python3
import json, os, shutil, signal, sys, time
HOME, GEN, REAL, VERSION = os.path.expanduser("~"), os.environ.get("OBELISK_DEVELOPER_ENGINE_FILES"), __REAL__, "__VERSION__"
LIB = HOME + "/Library/Application Support/cc.orbiters.obelisk-cli"
REC, SESSION = LIB + "/SteamSessions", "00000000-0000-0000-0000-00000000000a"
words = sys.argv[1:]
if words[:1] == ["--library"]:
    words = words[2:]
def how(name):
    try:
        return open(f"{HOME}/how-{name}").read()
    except OSError:
        return None
def running():
    try:
        pid = int(open(HOME + "/running").read())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False
open(HOME + "/asked", "a").write(json.dumps([os.environ.get("OBELISK_DEVELOPER_ENGINE")] + [w for w in words if "://" not in w]) + "\n")
def record(phase, game, **more):
    os.makedirs(REC, mode=0o700, exist_ok=True)
    with open(os.open(f"{REC}/{SESSION}.v2.json.new", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        json.dump(dict(id=SESSION, store=dict(app_id=438100), phase=phase, game=game) | more, f)
    os.rename(f"{REC}/{SESSION}.v2.json.new", f"{REC}/{SESSION}.v2.json")
say = lambda **e: print(json.dumps(e), flush=True)
if words[0] == "engine":
    if running():
        say(event="error", code="busy")
        sys.exit(1)
    if os.environ["OBELISK_DEVELOPER_ENGINE"] == "released" and how("fails"):
        left = int(how("fails"))
        open(HOME + "/how-fails", "w").write(str(left - 1) if left > 1 else "")
        sys.exit(1)
    if REAL:
        shutil.rmtree(REC, ignore_errors=True)  # (the real program does not know these records)
        os.execv(REAL, [REAL, *sys.argv[1:]])
    which = os.environ["OBELISK_DEVELOPER_ENGINE"]
    for name in ("engine/wsd", "graphics/other"):
        to = f"{LIB}/Voile/{VERSION}/linux/{name}"
        shutil.copy(f"{GEN}/{which}/{name}", to + ".new")
        os.rename(to + ".new", to)
    say(event="engine_generation", generation=which)
elif words[:2] == ["steam", "play"]:
    for n in (signal.SIGINT, signal.SIGTERM):
        signal.signal(n, signal.SIG_IGN)  # (a game's supervisor lives on)
    open(HOME + "/running", "w").write(str(os.getpid()))
    say(event="starting", app_id=438100, session_id=SESSION)
    record("Running", dict(pid=os.getpid()))
    say(event="running", app_id=438100, pid=os.getpid(), session_id=SESSION)
    end = time.monotonic() + 90
    while not (os.path.exists(HOME + "/quit") and not how("stays")) and time.monotonic() < end:
        time.sleep(0.1)
    record("Finished", None, exit_code=0, played=dict(seconds=9, ended_by_obelisk=True, exit_signal=None))
    say(event="exited", app_id=438100, session_id=SESSION, exit_code=0)
elif words[:2] == ["steam", "quit"]:
    open(HOME + "/quit", "a").write(" ".join(words) + "\n")
"""

# The runner, with the Mac's own state told as it is not, and, for what does not need the bench, a measurement that is none.
DRIVER = r"""
import argparse, importlib.util, json, os, signal, subprocess, sys, time
TOOLS, HOME, GEN, CASE, MORE = __TOOLS__, os.path.expanduser("~"), __GEN__, sys.argv[1], sys.argv[2:]
spec = importlib.util.spec_from_file_location("real_session", TOOLS + "/real_session.py")
rs = importlib.util.module_from_spec(spec); spec.loader.exec_module(rs)
LIB = HOME + "/Library/Application Support/cc.orbiters.obelisk-cli"
def game():
    try:
        pid = int(open(HOME + "/running").read()); os.kill(pid, 0); return [f"{pid} fexdarwin-run"]
    except (OSError, ValueError):
        return []
rs.locked, rs.engine_running = (lambda: False), game
real_run = rs.run
rs.run = lambda cmd, timeout=15, env=None: "" if cmd[0] in ("/usr/sbin/system_profiler", "/usr/bin/top") else real_run(cmd, timeout, env)
a = argparse.Namespace(cli=HOME + "/obelisk-cli", generation=GEN, bench=HOME + "/tools", out=HOME + "/evidence", passes=8, mb=64, plan=[45], warm=1, window=1, windows=1, between=0, library=LIB,
                       switches={}, rehearse=True, series="s", nothing_wrong_seen=False, link=__LINK__, restore_wait=int(os.environ.get("RESTORE_WAIT", "60")))
def ready():
    open(HOME + "/ready", "w").close()
def halt():
    ready()
    time.sleep(90)
if CASE == "--restore":
    a.series = None
    sys.exit(rs.Session(a).restore_command())
s = rs.Session(a)
s.fixed = lambda: dict(plan=[45], windows=1)
if not MORE:
    s.preflight = lambda: []
def result(*_):
    folder = s.out + "/start-45"; os.makedirs(folder)
    return dict(why_not=[], go_on=False, restored=None, windows=[], path=folder + "/result.json", switches={}, percent=45)
def standin(percent):
    assert s.digests("timeline") == [] and s.owed.there()
    if CASE in ("sigint", "sigterm", "killed-measuring", "sigint-slot"): halt()
    if CASE == "exception": raise RuntimeError("as injected")
    if CASE == "exit": sys.exit(3)
    return result()
if not CASE.startswith("bench"):
    s.start = standin
else:
    s.report = lambda *x: result()
def failing(*_, **__): raise OSError(28, "as injected")
if CASE == "slot-settled": s.bench.Slot.settled = s.bench.Slot.say = failing  # (and so nothing is measured either)
if CASE in ("sigint-slot", "slot-settled-alone"): s.bench.Slot.settled = failing
if CASE == "report-write":
    kept = rs.durable
    rs.durable = lambda path, value: failing() if path.endswith("result.json") else kept(path, value)
if CASE == "evidence-write":
    kept_write = rs.write
    rs.write = lambda path, value: failing() if path.endswith(("revert.json", "results.json")) else kept_write(path, value)
if CASE == "series-write":
    s.series.ended = failing
if CASE == "marker-write":
    s.owed.say = failing
if CASE in ("revert-raises", "revert-partial"):
    kept_cli, tries = s.cli, []
    def cli(generation, *words, **more):
        if generation == "released" and words[0] == "engine":
            tries.append(1)
            if len(tries) == 1: raise subprocess.TimeoutExpired("obelisk-cli", 300)
            if len(tries) == 2: raise OSError(5, "as injected")
            if len(tries) == 3 and CASE == "revert-partial": return 0, []   # (it says so, and it is not)
        return kept_cli(generation, *words, **more)
    s.cli = cli
if CASE == "digest-raises":
    kept_digests, looks = s.digests, []
    def digests(which):
        if which == "released":
            looks.append(1)
            if len(looks) < 3: raise OSError(5, "as injected")
        return kept_digests(which)
    s.digests = digests
if CASE == "killed-before-install":
    s.cli = lambda g, *w, **k: halt() if g == "timeline" else (0, [])
if CASE in ("killed-after-install", "sigterm-after-install", "sighup-after-install"):
    kept_write = rs.write
    rs.write = lambda path, value: halt() if path.endswith("install.json") else kept_write(path, value)
if CASE == "killed-restoring":
    kept_cli = s.cli
    s.cli = lambda g, *w, **k: halt() if g == "released" and w[0] == "engine" else kept_cli(g, *w, **k)
if CASE == "killed-before-verifying":
    kept_cli2 = s.cli
    def cli2(g, *w, **k):
        told = kept_cli2(g, *w, **k)
        if g == "released" and w[0] == "engine": halt()
        return told
    s.cli = cli2
if CASE == "killed-before-publication":
    s.publish = halt
if CASE == "killed-in-publication":
    s.series.ended = lambda *_: halt()
sys.exit(s.main())
"""


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class Restoration(unittest.TestCase):
    def setUp(self):
        self.home = os.path.realpath(tempfile.mkdtemp(prefix="restore."))
        self.addCleanup(self.clean)
        self.lib = f"{self.home}/Library/Application Support/cc.orbiters.obelisk-cli"
        self.n4n0 = f"{self.home}/Library/Application Support/orbiters-desktop"
        for folder in (f"{self.lib}/Voile", f"{self.n4n0}", f"{self.home}/tools", f"{self.home}/Library/Logs/Obelisk/Steam"):
            os.makedirs(folder)
        if REAL:
            self.gen = GENERATION
            with open(f"{self.gen}/timeline.json") as f:
                self.version = json.load(f)["voile"]
            subprocess.run(["/bin/cp", "-Rc", RELEASE, f"{self.lib}/Voile/{self.version}"], check=True)
            open(f"{self.lib}/Voile/prereleases", "w").close()
        else:
            self.gen, self.version = f"{self.home}/generation", "v"
            known = {}
            for which in ("released", "timeline"):
                for name in ("engine/wsd", "graphics/other"):
                    os.makedirs(os.path.dirname(f"{self.gen}/{which}/{name}"), exist_ok=True)
                    with open(f"{self.gen}/{which}/{name}", "w") as f:
                        f.write(f"{which} {name}")
                    known.setdefault(which, {})[name] = sha(f"{self.gen}/{which}/{name}")
            for name, value in (("timeline.json", dict(voile="v")), ("engine-files.json", known | dict(timeline_graphics={}))):
                with open(f"{self.gen}/{name}", "w") as f:
                    json.dump(value, f)
            shutil.copytree(f"{self.gen}/released", f"{self.lib}/Voile/v/linux")
        self.linux = f"{self.lib}/Voile/{self.version}/linux"
        with open(f"{self.gen}/engine-files.json") as f:
            self.known = json.load(f)
        with open(f"{self.home}/obelisk-cli", "w") as f:
            f.write(FAKE_CLI.replace("__REAL__", repr(CLI if REAL else None)).replace("__VERSION__", self.version))
        os.chmod(f"{self.home}/obelisk-cli", 0o755)
        # the bench as it is, with shorter deadlines
        with open(f"{TOOLS}/bench.py") as f:
            bench = f.read()
        self.assertEqual(bench.count("CLOSE_DEADLINE = 120 "), 1)
        with open(f"{self.home}/tools/bench.py", "w") as f:
            f.write(bench.replace("CLOSE_DEADLINE = 120 ", "CLOSE_DEADLINE = 4 "))
        with open(f"{self.home}/driver.py", "w") as f:
            f.write(DRIVER.replace("__TOOLS__", repr(TOOLS)).replace("__GEN__", repr(self.gen)).replace("__LINK__", repr(LINK)))
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("OBELISK_")} | {"HOME": self.home}
        if REAL:
            subprocess.run([f"{self.home}/obelisk-cli", "engine", "generation"], env=self.env | dict(OBELISK_DEVELOPER_ENGINE="released", OBELISK_DEVELOPER_ENGINE_FILES=self.gen), check=True, capture_output=True)
        self.assertTrue(self.released())

    def clean(self):
        for name in ("running", "bench-pid"):
            try:
                with open(f"{self.home}/{name}") as f:
                    os.kill(int(f.read()), signal.SIGKILL)
            except (OSError, ValueError):
                pass
        shutil.rmtree(self.home, ignore_errors=True)

    def holds(self, which):
        return all(sha(f"{self.linux}/{p}") == h for p, h in self.known[which].items())

    def released(self):
        return self.holds("released")

    def run_(self, case, *more, send=None, wait=90, then=None, ready="ready", **env):
        """The runner, sent `send` (it alone) once it is where the case is about. Its status."""
        p = subprocess.Popen([sys.executable, "-I", "-B", f"{self.home}/driver.py", case, *more], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=self.env | env, start_new_session=True)
        if send is not None:
            begin = time.monotonic()
            while not os.path.exists(f"{self.home}/{ready}"):
                self.assertTrue(p.poll() is None and time.monotonic() - begin < 60, p.poll() if p.poll() is None else p.stdout.read())
                time.sleep(0.05)
            if then:
                then()
            p.send_signal(send)
        if send == signal.SIGKILL:
            p.wait(10)
            p.stdout.close()
            return -9
        self.said = p.communicate(timeout=wait)[0]
        return p.returncode

    def series(self):
        with open(f"{self.home}/evidence/s/series.json") as f:
            return json.load(f)["starts"]

    def owed(self):
        return os.path.exists(f"{self.home}/evidence/restoration-owed.json")

    def slot(self):
        with open(f"{self.n4n0}/obelisk-start-gate.lock") as f:
            return f.read()

    def quits(self):
        try:
            with open(f"{self.home}/quit") as f:
                return f.read().splitlines()
        except OSError:
            return []

    def back(self, go_on):
        self.assertTrue(self.released(), getattr(self, "said", ""))
        self.assertFalse(self.holds("timeline"))
        self.assertFalse(self.owed(), "nothing is owed any more")
        self.assertEqual([s["go_on"] for s in self.series()] if os.path.exists(f"{self.home}/evidence/s/series.json") else [], go_on, getattr(self, "said", ""))

    def restore(self, status=0, **env):
        self.assertEqual(self.run_("--restore", **env), status, self.said)

    # ---- the runner sees its end

    def test_a_start_that_went_as_planned(self):
        self.assertEqual(self.run_("normal"), 0, self.said)
        self.back([True])
        entry, = self.series()
        with open(entry["result"]) as f:
            r = json.load(f)
        self.assertEqual((r["go_on"], r["restored"]["verified"], r["restored"]["files"]), (True, True, self.known["released"]))
        self.assertEqual(entry["result_sha256"], sha(entry["result"]))
        self.assertEqual(self.slot(), "")

    def test_a_failure_in_the_measurement(self):
        for case in ("exception", "exit"):
            shutil.rmtree(f"{self.home}/evidence", ignore_errors=True)
            self.assertNotEqual(self.run_(case), 0)
            self.back([False])

    def test_told_to_stop(self):
        for case, number in (("sigint", signal.SIGINT), ("sigterm", signal.SIGTERM), ("sigint", signal.SIGHUP)):
            shutil.rmtree(f"{self.home}/evidence", ignore_errors=True)
            if os.path.exists(f"{self.home}/ready"):
                os.remove(f"{self.home}/ready")
            self.assertEqual(self.run_(case, send=number), 1, self.said)
            self.back([False])

    def test_told_to_stop_right_after_the_install(self):
        self.assertEqual(self.run_("sigterm-after-install", send=signal.SIGTERM), 1, self.said)
        self.back([])
        os.remove(f"{self.home}/ready")
        shutil.rmtree(f"{self.home}/evidence")
        self.assertEqual(self.run_("sighup-after-install", send=signal.SIGHUP), 1, self.said)
        self.back([])

    def test_told_to_stop_again_and_again(self):
        p = subprocess.Popen([sys.executable, "-I", "-B", f"{self.home}/driver.py", "sigint"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=self.env, start_new_session=True)
        while not os.path.exists(f"{self.home}/ready"):
            self.assertIsNone(p.poll())
            time.sleep(0.05)
        while p.poll() is None:
            for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                try:
                    p.send_signal(number)
                except ProcessLookupError:
                    pass
            time.sleep(0.003)
        self.back([False])

    def test_the_slot_s_note_cannot_be_written(self):
        # (the review: an error of it skipped the revert)
        self.assertNotEqual(self.run_("slot-settled"), 0)
        self.back([False])
        shutil.rmtree(f"{self.home}/evidence")
        self.assertEqual(self.run_("slot-settled-alone"), 0, self.said)
        self.back([True])
        with open(f"{self.n4n0}/obelisk-start-gate.lock", "w"):
            pass
        shutil.rmtree(f"{self.home}/evidence")
        self.assertEqual(self.run_("sigint-slot", send=signal.SIGINT), 1, self.said)
        self.back([False])

    def test_what_is_told_cannot_be_written(self):
        self.assertEqual(self.run_("evidence-write"), 0, self.said)
        self.back([True])
        for case in ("report-write", "series-write"):
            shutil.rmtree(f"{self.home}/evidence")
            self.assertEqual(self.run_(case), 1, self.said)
            self.back([False])

    def test_that_it_is_owed_cannot_be_written(self):
        self.assertNotEqual(self.run_("marker-write"), 0)
        self.back([])
        with open(f"{self.home}/asked") as f:
            self.assertNotIn('"timeline", "engine"', f.read(), "nothing was put in place")

    def test_an_attempt_to_put_it_back_raises(self):
        for case in ("revert-raises", "revert-partial", "digest-raises"):
            shutil.rmtree(f"{self.home}/evidence", ignore_errors=True)
            self.assertEqual(self.run_(case), 0, self.said)
            self.back([True])

    def test_no_attempt_puts_it_back(self):
        with open(f"{self.home}/how-fails", "w") as f:
            f.write("99")
        self.assertEqual(self.run_("normal"), 1)
        self.assertTrue(self.owed() and self.holds("timeline"))
        self.assertEqual([s["go_on"] for s in self.series()], [False], "a series goes on once it is back, and not before")
        self.assertIn("--restore", self.said)
        self.assertEqual(self.run_("normal", "with its checks"), 1)
        self.assertIn("Not started", self.said)
        self.assertEqual(len(self.series()), 1)
        os.remove(f"{self.home}/how-fails")
        self.restore()
        self.back([False])

    # ---- it was killed

    def test_killed(self):
        for case, timeline, owed, entries in (("killed-before-install", False, True, []), ("killed-after-install", True, True, []), ("killed-measuring", True, True, [False]),
                                              ("killed-restoring", True, True, [False]), ("killed-before-verifying", False, True, [False]), ("killed-before-publication", False, False, [False]),
                                              ("killed-in-publication", False, False, [False])):
            shutil.rmtree(f"{self.home}/evidence", ignore_errors=True)
            if os.path.exists(f"{self.home}/ready"):
                os.remove(f"{self.home}/ready")
            with open(f"{self.n4n0}/obelisk-start-gate.lock", "w"):
                pass
            self.assertEqual(self.run_(case, send=signal.SIGKILL), -9)
            self.assertEqual((self.holds("timeline"), self.owed()), (timeline, owed), case)
            self.restore()
            self.back(entries)
            if case == "killed-measuring":
                self.assertEqual(self.slot(), "", "nothing was started by it, and that is known")
            self.restore()  # (nothing is owed: that too is told)
            self.assertIn("nothing is owed", self.said)

    def test_the_next_start_puts_it_back_first(self):
        self.run_("killed-measuring", send=signal.SIGKILL)
        self.assertTrue(self.holds("timeline"))
        self.run_("exit", "with its checks")  # (its preflight is the real one, and refuses: the series is over)
        self.back([False])
        self.assertIn("the released generation is in place", self.said)
        self.assertIn("Not started", self.said)

    def test_it_is_owed_though_what_says_so_is_damaged(self):
        self.run_("killed-measuring", send=signal.SIGKILL)
        with open(f"{self.home}/evidence/restoration-owed.json", "w") as f:
            f.write("{ half")
        self.restore()
        self.back([False])

    def test_the_files_are_not_the_released_ones_and_nothing_says_why(self):
        self.run_("killed-measuring", send=signal.SIGKILL)
        os.remove(f"{self.home}/evidence/restoration-owed.json")
        with open(f"{self.n4n0}/obelisk-start-gate.lock", "w"):
            pass  # (as N4N0 settles it)
        self.assertEqual(self.run_("normal", "with its checks"), 1)
        self.assertIn("--restore puts it back", self.said)
        self.restore()
        self.back([False])

    def test_while_another_runner_or_n4n0_holds_the_slot_nothing_is_put_back(self):
        import fcntl
        self.run_("killed-measuring", send=signal.SIGKILL)
        with open(f"{self.n4n0}/obelisk-start-gate.lock", "r+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            self.restore(1, RESTORE_WAIT="2")
            self.assertTrue(self.owed() and self.holds("timeline"))
        self.restore()
        self.back([False])

    # ---- the bench, and what it started

    def bench_pid(self):
        with open(f"{self.home}/evidence/restoration-owed.json") as f:
            return json.load(f)["bench"]["pid"]

    def note_bench(self):
        while True:  # (it is told once the bench is there, and the game's own program is after it)
            try:
                pid = self.bench_pid()
                break
            except (OSError, ValueError, KeyError):
                time.sleep(0.05)
        with open(f"{self.home}/bench-pid", "w") as f:
            f.write(str(pid))
        return pid

    def gone(self, pid):
        try:
            os.kill(pid, 0)
            return False
        except ProcessLookupError:
            return True

    def test_told_to_stop_it_alone_the_bench_and_the_session_end_before_it_is_put_back(self):
        for number in (signal.SIGINT, signal.SIGTERM):
            shutil.rmtree(f"{self.home}/evidence", ignore_errors=True)
            for name in ("running", "quit", "asked"):
                if os.path.exists(f"{self.home}/{name}"):
                    os.remove(f"{self.home}/{name}")
            self.assertEqual(self.run_("bench", send=number, ready="running", then=self.note_bench), 1, self.said)
            self.back([False])
            with open(f"{self.home}/bench-pid") as f:
                self.assertTrue(self.gone(int(f.read())))
            self.assertEqual(len(self.quits()), 1)
            self.assertIn("--session 00000000-0000-0000-0000-00000000000a", self.quits()[0])
            self.assertEqual(self.slot(), "", "its session ended: that is proven")
            with open(f"{self.home}/asked") as f:
                asked = [json.loads(line) for line in f]
            words = [a[1:3] for a in asked if a[1:3] in (["steam", "quit"], ["engine", "generation"])]
            self.assertEqual(words, [["engine", "generation"], ["steam", "quit"], ["engine", "generation"]])

    def test_the_bench_is_killed(self):
        p = subprocess.Popen([sys.executable, "-I", "-B", f"{self.home}/driver.py", "bench"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=self.env, start_new_session=True)
        while not os.path.exists(f"{self.home}/running"):
            self.assertIsNone(p.poll())
            time.sleep(0.05)
        time.sleep(1.5)  # (its session is noted)
        self.assertNotEqual(self.slot(), "")
        os.kill(self.note_bench(), signal.SIGKILL)
        p.communicate(timeout=90)
        self.assertTrue(self.released())
        self.assertFalse(self.owed())
        self.assertEqual(len(self.quits()), 1, "the runner asked the session by its name")
        self.assertEqual(self.slot(), "", "and only once its record said how it ended")

    def test_a_session_that_does_not_end_stays_noted_and_owed(self):
        with open(f"{self.home}/how-stays", "w") as f:
            f.write("1")
        self.assertEqual(self.run_("bench", send=signal.SIGINT, ready="running", then=self.note_bench, wait=150), 1, self.said)
        self.assertTrue(self.owed() and self.holds("timeline"))
        self.assertEqual([s["go_on"] for s in self.series()], [False])
        self.assertEqual(json.loads(self.slot())["session"], "00000000-0000-0000-0000-00000000000a")
        # nothing is started, and nothing put back, while it runs
        self.assertEqual(self.run_("normal", "with its checks", RESTORE_WAIT="2"), 1)
        self.assertIn("Not started", self.said)
        self.restore(1, RESTORE_WAIT="2")
        self.assertTrue(self.owed() and self.holds("timeline"))
        os.remove(f"{self.home}/how-stays")
        self.restore()
        self.back([False])

    def test_killed_with_the_game_running(self):
        self.run_("bench", send=signal.SIGKILL, ready="running", then=self.note_bench)
        self.assertTrue(self.owed() and self.holds("timeline"))
        self.assertNotEqual(self.slot(), "")
        self.restore()
        self.back([False])
        with open(f"{self.home}/bench-pid") as f:
            self.assertTrue(self.gone(int(f.read())), "the bench it left quit its session and ended")
        self.assertEqual(len(self.quits()), 1)
        self.assertEqual(self.slot(), "", "its session's record says how it ended")

    def test_both_killed_with_the_game_running(self):
        p = subprocess.Popen([sys.executable, "-I", "-B", f"{self.home}/driver.py", "bench"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=self.env, start_new_session=True)
        while not os.path.exists(f"{self.home}/running"):
            self.assertIsNone(p.poll())
            time.sleep(0.05)
        time.sleep(1.5)
        pid = self.note_bench()
        p.kill()
        p.wait()
        os.kill(pid, signal.SIGKILL)
        self.restore(1, RESTORE_WAIT="2")
        self.assertIn("waiting until nothing of it runs", self.said)
        self.assertEqual(self.quits(), [], "what is left running is the person's to close")
        self.assertTrue(self.owed() and self.holds("timeline"))
        open(f"{self.home}/quit", "w").close()  # (and it is)
        self.restore()
        self.back([False])


if __name__ == "__main__":
    unittest.main()
