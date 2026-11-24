#!/usr/bin/env python3
"""Checks of bench.py's scoring, arrival and cleanup (fourth verification, finding 11; fifth, findings 11 and 12), without
a game: python3 -I tests/timeline/test_bench.py"""
import contextlib, datetime, fcntl, io, json, os, shutil, signal, subprocess, sys, tempfile, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../tools/timeline"))
import bench  # noqa: E402

bench.N4N0 = "/nonexistent/n4n0-of-the-tests"  # (never this Mac's own: each test that starts anything names one)


def npt(n, shown=0, interval=16.0, fence=8.0):
    return f"neptune unixlib wsi (wsd): {n} presents ({shown} shown events), last 60: interval avg {interval} ms, fence wait avg {fence} ms, pacing wait avg 0.0 ms"


class Scoring(unittest.TestCase):
    def test_the_boundary_interval_counts_and_the_rate_is_over_matching_times(self):
        lines = [(9.0, npt(0)), (10.5, npt(60)), (11.5, npt(120)), (12.5, npt(180))]
        rate, seconds = bench.counted_rate(bench.generations(lines), 10.0, 13.0, 2)
        self.assertEqual((rate, seconds), (51.43, 3.5), "from the line before the window: 180 presents in 3.5 s")

    def test_a_new_swapchain_is_never_subtracted_across(self):
        lines = [(1.0, npt(9000)), (2.0, npt(9060)), (2.5, "guest swapchain: created 1705x1109 fmt=29 buffers=1"), (3.0, npt(60)), (4.0, npt(120))]
        rate, seconds = bench.counted_rate(bench.generations(lines), 1.5, 5.0, 2)
        self.assertEqual((rate, seconds), (60.0, 2.0), "60 in gen 0 (1 s) + 60 in gen 1 (1 s)")

    def test_a_measured_zero_stays_zero(self):
        lines = [(1.0, npt(100, 5)), (2.0, npt(160, 5))]
        rate, _ = bench.counted_rate(bench.generations(lines), 0.0, 3.0, 3)
        self.assertEqual(rate, 0.0)
        self.assertIsNone(bench.counted_rate(bench.generations(lines[:1]), 0.0, 3.0, 2)[0], "one line: not known")

    def test_lines_read_together_are_one_reading(self):
        # 90 a second, read once a second: two or one line at a time (was 60/s).
        lines, n = [], 0
        for second in range(1, 11):
            for _ in range(2 if second % 2 else 1):
                n += 60
                lines.append((float(second), npt(n)))
        rate, seconds = bench.counted_rate(bench.generations(lines), 1.0, 10.5, 2)
        self.assertAlmostEqual(rate, 90.0, delta=4.0)
        self.assertEqual(seconds, 9.0)

    # ---- windows ----------------------------------------------------------------------------------------------------

    WSD = 500
    WALL = 1_800_000_000.0  # the wall clock when this run's was 0

    def look(self, at, **other):
        return {"at": at, "wall": self.WALL + at, "alive": True, "locked": False, "front": self.WSD, "wsd": [self.WSD]} | other

    def hud(self, at, frames=60, pid=None, every=16.6667):
        stamp = datetime.datetime.fromtimestamp(self.WALL + at).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        values = ",".join(f"{every},0.1" for _ in range(frames))
        return f"{stamp} wsd[{pid or self.WSD}:123] metal-HUD: {frames},90.0,100.0,{values}"

    def window(self, seconds=60, hud=True, production=True, looks=True):
        """A whole, healthy window of `seconds` from 10 s on: (lines, state, moves)."""
        lines, n = [], 0
        for at in range(8, 10 + seconds + 1):
            if production:
                n += 60
                lines.append((at + 0.5, npt(n)))
            if hud:
                lines.append((at + 0.9, self.hud(at + 0.9)))
        state = {"gpu": [], "cpu": [], "look": [self.look(at + 0.2) for at in range(9, 10 + seconds)] if looks else []}
        return lines, state, [(5.0, True)]

    def scored(self, lines, state, moves, allow_locked=False, seconds=60):
        return bench.summarize(lines, 10.0, 10.0 + seconds, state, allow_locked, moves)

    def test_what_was_in_front_is_named(self):
        # 2026-11-23: nine windows said only "not frontmost"; Safari was, in every look.
        lines, state, moves = self.window()
        state = state | {"look": [x | {"front": 1184, "front_name": "Safari"} for x in state["look"]]}
        why = "; ".join(bench.summarize(lines, 10.0, 70.0, state, False, moves)["invalid_because"])
        self.assertIn(f"Safari in {len([x for x in state['look'] if 10 <= x['at'] < 70])} of", why)

    def test_the_pictures_are_of_the_own_window_server_s_window_alone(self):
        ran, kept = [], (bench.run, bench.time.sleep)
        with tempfile.TemporaryDirectory() as d:
            def run(cmd, timeout=10):
                ran.append(cmd)
                open(cmd[3], "w").close()
                return "77 1470 956 0\n"
            try:
                bench.run, bench.time.sleep = run, lambda s: None
                programs = {7: "/bin/bash", 8: "/x/VRChat.app/Contents/MacOS/wsd"}
                got = bench.take_pictures({"programs": programs}, "/tool", f"{d}/picture", bench.now())
                self.assertEqual([p["file"] for p in got], ["picture-1.png", "picture-2.png", "picture-3.png"])
                self.assertEqual({tuple(c[:3]) for c in ran}, {("/tool", "shot", "8")})
                self.assertEqual((got[0]["window"], got[0]["points"]), (77, [1470, 956]))
                for other in ({7: "/bin/bash"}, programs | {9: "/y/wsd"}):  # none of its own, or not known which: no picture
                    ran.clear()
                    self.assertEqual([p["file"] for p in bench.take_pictures({"programs": other}, "/tool", f"{d}/none", bench.now())], [None] * 3)
                    self.assertEqual(ran, [])
            finally:
                bench.run, bench.time.sleep = kept

    def test_the_game_is_brought_to_the_front_by_its_own_bundle_only(self):
        ran, kept = [], {n: getattr(bench, n) for n in ("run", "frontmost", "front_name")}
        try:
            bench.run = lambda cmd, timeout=10: ran.append(cmd) or ""
            bench.front_name = lambda: "Safari"
            bench.frontmost = lambda: 1184
            app = "/private/var/folders/x/T/obelisk-apps/VRChat/VRChat.app"
            state = {"fronted": []}
            programs = {7: "/bin/bash", 8: f"{app}/Contents/MacOS/wsd", 9: f"{app}/Contents/Helpers/dxmt.app/Contents/MacOS/virgl_render_server"}
            self.assertFalse(bench.bring_to_front(state, programs))
            self.assertEqual(ran, [["/usr/bin/open", app]])
            self.assertEqual((state["fronted"][0]["instead_of"], state["fronted"][0]["bundle"]), ("Safari", "VRChat.app"))
            bench.frontmost = lambda: 8
            self.assertTrue(bench.bring_to_front(state, programs), "it is in front")
            bench.frontmost = lambda: 1184
            self.assertFalse(bench.bring_to_front(state, {7: "/bin/bash"}), "no window server of this session: nothing is opened")
            bench.bring_to_front(state, {8: "/somewhere/wsd"})
            self.assertEqual(len(ran), 1, "a window server of no bundle is not opened")
        finally:
            for n, v in kept.items():
                setattr(bench, n, v)

    def test_the_front_process_is_read_on_every_macos(self):
        # 2026-11-23, macOS 27: no window of a whole series was scored, the front app always read as None.
        as_macos_27 = ' ASN:0x0-0x4c34c3: (in front) \n    bundleID=[ NULL ] \n    executable path=[ NULL ] \n    pid = 11538 !cgsConnection !signalled type=[ NULL ]  flavor=[ NULL ] \n\n'
        self.assertEqual(bench.front_pid(as_macos_27), 11538)
        self.assertEqual(bench.front_pid('"pid"=11538\n'), 11538)
        self.assertIsNone(bench.front_pid(""))
        self.assertIsNone(bench.front_pid("    pid = [ NULL ] \n"))

    def test_a_whole_window_is_scored(self):
        good = self.scored(*self.window())
        self.assertTrue(good["valid"], good["invalid_because"])
        self.assertEqual(good["guest_present"]["submitted_per_second_counted"], 60.0)
        self.assertAlmostEqual(good["wsd_shown"]["per_second"], 60.0, delta=1.5)

    def test_a_window_without_shown_frames_or_behind_a_lock_is_not_scored(self):
        lines, state, moves = self.window(hud=False)
        state["look"] = [look | {"locked": True, "front": 77} for look in state["look"]]
        bad = self.scored(lines, state, moves)
        self.assertFalse(bad["valid"])
        self.assertFalse(bad["production_only"])
        self.assertTrue(any("locked" in w for w in bad["invalid_because"]))
        self.assertTrue(any("no frame was shown" in w for w in bad["invalid_because"]))
        prod = self.scored(lines, state, moves, True)
        self.assertTrue(prod["production_only"], "allowed explicitly: production only, and said")
        self.assertEqual(prod["wsd_shown"]["per_second"], 0.0, "zero shown is measured as zero")

    def test_one_look_one_batch_and_one_shown_interval_score_nothing(self):
        # Fifth verification, finding 11: this was valid, with zero seconds counted.
        lines = [(40.0, npt(60)), (40.1, self.hud(40.1, frames=1))]
        state = {"gpu": [], "cpu": [], "look": [self.look(40.0)]}
        bad = self.scored(lines, state, [(5.0, True)])
        self.assertFalse(bad["valid"])
        for what in ("nothing was looked at for", "counted over 0.0 s", "no frame was shown all along"):
            self.assertTrue(any(what in w for w in bad["invalid_because"]), (what, bad["invalid_because"]))
        self.assertFalse(self.scored(lines, state, [(5.0, True)], True)["production_only"], "nor its production")

    def test_every_part_of_the_window_is_seen(self):
        lines, state, moves = self.window()
        invalid = lambda l, s, m, what: self.assertTrue(any(what in w for w in self.scored(l, s, m)["invalid_because"]), what)
        gap = state | {"look": [x for x in state["look"] if not 30 < x["at"] < 40]}
        invalid(lines, gap, moves, "nothing was looked at for")
        invalid(lines, state | {"look": [x for x in state["look"] if x["at"] < 60]}, moves, "nothing was looked at for")
        died = state | {"look": [x | {"alive": x["at"] < 50} for x in state["look"]]}
        invalid(lines, died, moves, "the session did not live")
        covered = state | {"look": [x | {"front": 77} if 30 < x["at"] < 31.5 else x for x in state["look"]]}
        invalid(lines, covered, moves, "not frontmost")
        invalid(lines, state | {"look": [x | {"front": None} for x in state["look"]]}, moves, "not frontmost")
        stopped = [(t, l) for t, l in lines if t < 50]
        invalid(stopped, state, moves, "its submissions were counted over")
        invalid(stopped, state, moves, "no frame was shown all along")
        # Another program's frames, or another session's window server's, are not this one's.
        others = [(t, l.replace(f"wsd[{self.WSD}:", "wsd[501:")) for t, l in lines]
        invalid(others, state, moves, "no frame was shown (no positive")
        # Few frames, each shown long ago: 100 ms of every second.
        sparse = [(t, self.hud(t, frames=6)) if "metal-HUD" in l else (t, l) for t, l in lines]
        invalid(sparse, state, moves, "no frame was shown all along")
        # The player left, or went elsewhere.
        invalid(lines, state, [], "in the destination")
        invalid(lines, state, [(5.0, True), (40.0, False)], "in the destination")
        invalid(lines, state, [(5.0, True), (40.0, False), (45.0, True)], "in the destination")
        invalid(lines, state, [(5.0, True), (8.0, False)], "in the destination")

    def test_coverage_is_of_the_window_and_its_readings_are_close(self):
        """Sixth verification, finding 11 (the verifier's): a baseline at -100 and one batch at 10.5 claimed 110.5 s of a
        60 s window; two readings 59.8 s apart passed."""
        hud = [(t, l) for t, l in self.window()[0] if "metal-HUD" in l]
        _, state, moves = self.window()
        for batches in ([(-100.0, npt(0)), (10.5, npt(60))], [(10.1, npt(0)), (69.9, npt(3600))]):
            bad = self.scored(sorted(hud + batches), state, moves)
            self.assertFalse(bad["valid"], bad["invalid_because"])
            self.assertEqual(bad["guest_present"]["read_over_seconds_of_the_window"], 0.0)
            self.assertTrue(any("counted over 0.0 s of 60.0" in w for w in bad["invalid_because"]), bad["invalid_because"])
        # The line before the window is the rate's base, and nothing of its coverage.
        points = bench.generations([(9.0, npt(0)), (10.5, npt(60)), (11.5, npt(120)), (12.5, npt(180))])
        self.assertEqual(bench.coverage(points, 10.0, 13.0), 2.5)
        # A swapchain's first reading covers nothing before it; six seconds without a reading are no coverage.
        points = bench.generations([(1.0, npt(0)), (2.0, npt(60)), (2.5, "guest swapchain: created 1705x1109 fmt=29 buffers=1"), (3.0, npt(60)), (4.0, npt(120)), (10.0, npt(180))])
        self.assertEqual(bench.coverage(points, 0.0, 20.0), 2.0)
        lines, state, moves = self.window()
        hole = [(t, l) for t, l in lines if "metal-HUD" in l or not 31 < t < 36]
        self.assertTrue(any("submissions were not read for" in w for w in self.scored(hole, state, moves)["invalid_because"]))

    def test_a_start_that_does_not_settle_is_not_calm(self):
        quiet = [(t / 2, npt(t * 30)) for t in range(0, 200)]
        self.assertTrue(bench.settled(quiet, 99.0))
        held = quiet + [(90.0, "wsd: window 1 overlay: frame held 300.0 ms, shown at 11:05:58.362")]
        self.assertFalse(bench.settled(held, 99.0))
        self.assertFalse(bench.settled([], 99.0), "nothing presented is not calm")
        self.assertFalse(bench.settled(quiet, 200.0), "nothing presented lately")


WORLD = "wrld_4432ea9b-729c-46e3-8eaf-846aa0a37fdd"
OTHER = "wrld_99999999-729c-46e3-8eaf-846aa0a37fdd"
HERE = f"{WORLD}:25038~private(usr_1)~region(eu)"
LINK = f"vrchat://launch?ref=orbiters.cc&id={HERE}"


class Arrival(unittest.TestCase):
    def joined(self, *said):
        return [(float(n), f"2026.11.23 11:29:24 Debug      -  [Behaviour] {text}") for n, text in enumerate(said)]

    def test_arrival_is_the_local_player_in_this_very_destination(self):
        wanted = bench.destination(LINK)
        self.assertEqual(wanted, (WORLD, "25038", {"private": "usr_1", "region": "eu"}))
        self.assertEqual(bench.destination(LINK.replace("~", "%7E").replace("(", "%28")), wanted)
        self.assertIsNone(bench.destination("vrchat://launch?ref=x"))
        there = lambda *said: [x for _, x in bench.whereabouts(self.joined(*said), wanted)]
        local = 'Initialized PlayerAPI "Some One" is local'
        self.assertEqual(there(f"Joining {HERE}", "OnPlayerJoinComplete Some One", local), [False, True])
        self.assertEqual(there(f"Joining {HERE}~nonce(x)", local), [False, True], "a tag the link did not ask for")
        # Finding 12: any join used to do, the fallback's too.
        for elsewhere in (f"{OTHER}:1~private(usr_1)~region(eu)", f"{WORLD}:25039~private(usr_1)~region(eu)", f"{WORLD}:25038~private(usr_2)~region(eu)", f"{WORLD}:25038", f"{WORLD}:25038~private(usr_1)~region(us)"):
            self.assertEqual(there(f"Joining {elsewhere}", "OnPlayerJoinComplete Some One", local), [False], elsewhere)
        # Another player's arrival, a join not yet made, a join after it.
        self.assertEqual(there(f"Joining {HERE}", "OnPlayerJoinComplete Another", 'Initialized PlayerAPI "Another" is remote'), [False])
        self.assertEqual(there(local), [])
        self.assertEqual(there(f"Joining {HERE}", local, f"Joining {OTHER}:1", local), [False, True, False])
        self.assertEqual(there(f"Joining {HERE}", local, "OnLeftRoom"), [False, True, False])


class Ownership(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.kept = bench.RECORDS
        bench.RECORDS = self.root.name

    def tearDown(self):
        bench.RECORDS = self.kept
        self.root.cleanup()

    def write(self, session, pointer=True, **fields):
        value = {"id": session, "store": {"app_id": 438100}, "phase": "Running", "supervisor": {"birth_seconds": 1000}, "game": {"pid": 5}} | fields
        for name in ([session] + (["session"] if pointer else [])):
            with open(f"{self.root.name}/{name}.v2.json", "w") as f:
                json.dump(value, f)

    def test_a_session_is_known_from_the_program_s_own_word_alone(self):
        """Sixth verification, finding 3: the library's current session is whoever's (until then it was taken by its
        supervisor's birth, which two launches share)."""
        self.write("foreign")
        session = {"id": None, "running_at": None}
        bench.told(session, {"event": "preparing"}, 1.0)
        self.assertIsNone(session["id"])
        bench.told(session, {"event": "starting", "session_id": "b"}, 1.0)
        self.assertEqual(session, {"id": "b", "running_at": None}, "before it runs")
        self.assertFalse(bench.refused([{"event": "preparing"}]), "said nothing of what became of it")
        self.assertTrue(bench.refused([{"event": "preparing"}, {"event": "error"}]))
        self.assertFalse(bench.refused([{"event": "starting"}, {"event": "error"}]))
        self.assertFalse(hasattr(bench, "admitted") or hasattr(bench, "pointer"))

    def test_the_log_is_the_one_whose_argument_is_the_link(self):
        kept = bench.VRC_LOGS
        bench.VRC_LOGS = self.root.name
        try:
            since = os.stat(self.root.name).st_birthtime
            write = lambda name, text: open(f"{self.root.name}/output_log_{name}.txt", "w").write(text)
            write("1", f"2026.11.23 11:29:24 Debug      -  seen on a portal: {LINK}\n")
            write("2", f"2026.11.23 11:29:24 Debug      -  Arg: {LINK}&x=1\n")
            self.assertIsNone(bench.own_vrchat_log(since, LINK))
            write("3", f"2026.11.23 11:29:24 Debug      -  Arg: -screen-fullscreen\n2026.11.23 11:29:24 Debug      -  Arg: {LINK}\nlater\n")
            with bench.own_vrchat_log(since, LINK) as f:
                # What is put at its path later is not read.
                os.rename(f.name, f.name + ".old")
                write("3", "another's")
                self.assertTrue(f.read().endswith("later\n"))
            self.assertIsNone(bench.own_vrchat_log(since + 1000, LINK), "made before")
        finally:
            bench.VRC_LOGS = kept

    def test_a_launch_is_closed_by_its_own_record_whether_or_not_its_program_lives(self):
        asked, clock = [], [0.0]
        kept = bench.run, bench.now, bench.time.sleep
        bench.run = lambda command, timeout=10: asked.append(command) or ""
        bench.now = lambda: clock[0]

        class Proc:
            def __init__(self, code):
                self.code = code

            def poll(self):
                return self.code

            def terminate(self):
                self.code = -15

        def slept(seconds):
            clock[0] += seconds
        bench.time.sleep = slept
        try:
            # The program died and the game runs on: its session is asked to quit all the same; it does not end.
            self.write("a")
            res = {"outcome": "x"}
            self.assertFalse(bench.close("/cli", "a", Proc(1), res))
            self.assertEqual(asked[-1], ["/cli", "steam", "quit", "438100", "--session", "a", "--wait", "60"])
            self.assertIn("may still run", res["outcome"])
            # It ends: known from its record.
            self.write("a", phase="Finished", game=None, exit_code=0)
            res = {"outcome": "x"}
            self.assertTrue(bench.close("/cli", "a", Proc(0), res))
            self.assertEqual(res["terminal"]["phase"], "Finished")
            self.assertEqual(len(asked), 1, "an ended session is asked nothing")
            # Its session ended and the program hangs: the program alone is ended.
            hung = Proc(None)
            self.assertTrue(bench.close("/cli", "a", hung, {"outcome": "x"}))
            self.assertEqual(hung.code, -15)
            # No session was named: only the program's word that it started nothing resolves it (until the sixth verification
            # its end alone did), and nothing is ever asked to quit.
            self.assertTrue(bench.close("/cli", None, Proc(1), {"outcome": "x"}, True))
            res = {"outcome": "x"}
            self.assertFalse(bench.close("/cli", None, Proc(1), res))
            self.assertIn("never named", res["outcome"])
            self.assertFalse(bench.close("/cli", None, Proc(None), {"outcome": "x"}, True))
            self.assertEqual(len(asked), 1)
            # A record that cannot be read, or whose game still lives, is no end.
            with open(f"{self.root.name}/b.v2.json", "w") as f:
                f.write("{ half")
            self.assertFalse(bench.close("/cli", "b", Proc(1), {"outcome": "x"}))
            self.write("c", phase="Finished")
            self.assertFalse(bench.close("/cli", "c", Proc(1), {"outcome": "x"}))
        finally:
            bench.run, bench.now, bench.time.sleep = kept

    def test_only_the_launcher_s_own_tree_is_sampled(self):
        listing = "  1     0 /sbin/launchd\n 10     1 /bin/bash\n 11    10 /x/wsd\n 12    11 /x/a b/child\n 20     1 /y/wsd\n"
        self.assertEqual(bench.tree(listing, 10), {10: "bash", 11: "wsd", 12: "child"})
        self.assertEqual(bench.tree(listing, -1), {})


FAKE_CLI = r"""#!/usr/bin/env python3
# Answers as obelisk-cli does, for a game that is this very process: root is the folder it keeps everything in.
import datetime, json, os, sys, time
root, how = ROOT, json.load(open(ROOT + "/how.json"))
say = lambda **event: print(json.dumps(event), flush=True)
def write(session, phase, game):
    value = {"id": session, "store": {"app_id": 438100}, "phase": phase, "supervisor": {"birth_seconds": int(time.time())}, "game": game, "exit_code": 0}
    for name in (session, "session"):
        open(f"{root}/records/{name}.new", "w").write(json.dumps(value))
        os.rename(f"{root}/records/{name}.new", f"{root}/records/{name}.v2.json")
open(f"{root}/argv", "a").write(json.dumps(sys.argv[1:]) + "\n")
if sys.argv[1:3] == ["steam", "quit"]:
    open(f"{root}/quit", "a").write(" ".join(sys.argv) + "\n")
    sys.exit(0)
say(event="preparing", app_id=438100)
if how.get("fails"):
    say(event="error", code="busy", message="m")
    sys.exit(1)
if how.get("foreign"):
    # Somebody else's start, at the same moment: the library's current session is theirs.
    write("foreign", "Running", {"pid": 1})
if how.get("dies_unnamed"):
    sys.exit(1)
def current(session, phase, game):
    write(session, phase, game)
    if how.get("foreign"):
        write("foreign", "Running", {"pid": 1})
current("s-1", "Preparing", None)
say(event="starting", app_id=438100, session_id=None if how.get("unnamed") else "s-1")
time.sleep(1.5)  # the admission is seen well before it runs
current("s-1", "Running", {"pid": 4242})
if how.get("dies"):
    sys.exit(1)
if "recovered" in how:
    # Its handoff was lost, and the program follows the session that runs in the library instead.
    say(event="running", app_id=438100, pid=1, session_id=how["recovered"])
    time.sleep(8)
    sys.exit(1)
say(event="running", app_id=438100, pid=4242, session_id="s-1")
link = sys.argv[-1]
import fcntl
slot = open(f"{root}/n4n0/obelisk-start-gate.lock", "r+")
try:
    fcntl.flock(slot, fcntl.LOCK_EX | fcntl.LOCK_NB)
    held = "free"
except BlockingIOError:
    held = "held"
open(f"{root}/slot", "w").write(held + " " + slot.read())
log = open(f"{root}/vrchat/output_log_1.txt", "w")
log.write(f"Arg: {link}\n[Behaviour] Joining {how['joins']}\n[Behaviour] OnPlayerJoinComplete Some One\n[Behaviour] Initialized PlayerAPI \"Some One\" is local\n")
log.flush()
engine, n = open(f"{root}/engine.log", "w"), 0
while not os.path.exists(f"{root}/quit"):
    time.sleep(0.2)
    n += 12
    engine.write(f"neptune unixlib wsi (wsd): {n} presents (0 shown events), last 60: interval avg 16.6 ms, fence wait avg 8.0 ms, x\n")
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    engine.write(f"{stamp} wsd[500:1] metal-HUD: 12,1,1," + ",".join(["16.7,0.1"] * 12) + "\n")
    engine.flush()
if how.get("stays"):
    sys.exit(0)
current("s-1", "Finished", None)
say(event="exited", app_id=438100, session_id="s-1", exit_code=0)
"""


class WholeRun(unittest.TestCase):
    """measure() against a program that answers as obelisk-cli does; no game, nothing of this Mac's own."""

    def run_with(self, deadline=8, settings=None, files=None, link=LINK, args=(), prepare=None, **how):
        with tempfile.TemporaryDirectory() as root:
            for folder in ("records", "vrchat", "n4n0"):
                os.mkdir(f"{root}/{folder}")
            if settings is not None:
                with open(f"{root}/n4n0/settings.json", "w") as f:
                    f.write(settings)
            for name, text in (files or {}).items():
                with open(f"{root}/n4n0/{name}", "w") as f:
                    f.write(text)
            if prepare:
                prepare(f"{root}/n4n0")
            with open(f"{root}/how.json", "w") as f:
                json.dump({"joins": HERE} | how, f)
            cli = f"{root}/obelisk-cli"
            with open(cli, "w") as f:
                f.write(FAKE_CLI.replace("ROOT,", repr(root) + ",").replace("ROOT +", repr(root) + " +"))
            os.chmod(cli, 0o755)
            patches = {
                "N4N0": f"{root}/n4n0", "ENGINE_LOG": f"{root}/engine.log", "VRC_LOGS": f"{root}/vrchat", "RECORDS": f"{root}/records",
                "START_DEADLINE": deadline, "ARRIVE_DEADLINE": 4, "CLOSE_DEADLINE": 4, "SETTLE_DEADLINE": 3,
                "settled": lambda lines, at: not how.get("never_calm"),
                "screen_locked": lambda: False, "frontmost": lambda: 500, "front_name": lambda: "VRChat", "tree": lambda listing, pid: {pid: "bash", 500: "wsd"},
            }
            kept = {name: getattr(bench, name) for name in patches}
            argv, sys.argv = sys.argv, ["bench.py", "--cli", cli, "--link", link, "--warm", "0", "--window", "3", "--windows", "1", "--no-sample", "--out", f"{root}/out.json", *args]
            try:
                for name, value in patches.items():
                    setattr(bench, name, value)
                said = io.StringIO()
                with open(os.devnull, "w") as quiet, contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(said):
                    status = bench.main()
                self.said = said.getvalue()
            finally:
                sys.argv = argv
                for name, value in kept.items():
                    setattr(bench, name, value)
            self.argv, self.slot = [], None
            if os.path.exists(f"{root}/argv"):
                with open(f"{root}/argv") as f:
                    self.argv = [json.loads(line) for line in f]
            if os.path.exists(f"{root}/n4n0/obelisk-start-gate.lock"):
                with open(f"{root}/n4n0/obelisk-start-gate.lock") as f:
                    self.slot = f.read()
            if os.path.exists(f"{root}/slot"):
                with open(f"{root}/slot") as f:
                    self.slot_while_it_ran = f.read()
            if not os.path.exists(f"{root}/out.json"):
                return status, None, False
            with open(f"{root}/out.json") as f:
                self.quits = []
                if os.path.exists(f"{root}/quit"):
                    with open(f"{root}/quit") as asked:
                        self.quits = asked.read().split("\n")[:-1]
                return status, json.load(f), bool(self.quits)

    def test_a_start_admitted_before_it_runs_is_measured(self):
        # 2026-11-23 11:51, a real start: admitted, then running, and "did not start: []" 900 s later, the game untouched.
        status, res, quit = self.run_with()
        self.assertEqual((status, res["outcome"], res["session"]), (0, "measured", "s-1"), res["outcome"])
        self.assertEqual(len(res["windows"]), 1)
        self.assertTrue(res["windows"][0]["valid"], res["windows"][0]["invalid_because"])
        self.assertTrue(quit)
        self.assertEqual(res["terminal"]["phase"], "Finished")
        # Everything that decided its window is kept with its times: scored again, it is the same.
        seen, window = res["observed"], res["windows"][0]
        state = {"gpu": [], "cpu": [], "look": seen["look"]}
        again = bench.summarize([tuple(x) for x in seen["lines"]], window["from"], window["to"], state, False, [tuple(x) for x in seen["moves"]])
        for key in ("valid", "invalid_because", "guest_present", "wsd_shown", "looks"):
            self.assertEqual(again[key], window[key], key)

    def test_a_start_is_given_its_own_arguments_alone_as_home_s_is(self):
        for settings in (None, '{"launch": {"profiles": {}}}', '{"launch": {"profiles": {"0": "usr_x"}}}', '{"launch": {}}', "{}"):
            status, res, _ = self.run_with(settings=settings, args=("--percent", "45"))
            self.assertEqual(status, 0, (settings, self.said))
            self.assertEqual(self.argv[0], ["steam", "play", "438100", "--no-saved-arguments", "--render-percent", "45", "--", "-screen-fullscreen", "1",
                                            "-window-mode", "borderless", LINK], "one profile: the link accompanies the start")
        self.assertNotIn("usr_", json.dumps(res["command"]), "what is kept of it names no place")
        self.run_with(args=("--arg=--fps=60",))
        self.assertEqual(self.argv[0][-2:], ["--fps=60", LINK])
        self.assertLess(self.argv[0].index("--no-saved-arguments"), self.argv[0].index("--"))

    def test_with_several_profiles_nothing_is_started_and_why_is_said(self):
        for profiles in ({"0": "usr_secret", "2": "usr_other"}, {"1": "usr_secret"}, {"0": "usr_secret", " 3 ": "x"}):
            status, res, _ = self.run_with(settings=json.dumps({"launch": {"profiles": profiles}}))
            self.assertEqual((status, res, self.argv), (6, None, []), profiles)
            self.assertIn("several VRChat profiles", self.said)
            for private in ("usr_", WORLD, "25038"):
                self.assertNotIn(private, self.said, "neither an account nor the place is told")
        for unknown in ("{", "[]", '{"launch": 3}', '{"launch": {"profiles": [1]}}'):
            status, res, _ = self.run_with(settings=unknown)
            self.assertEqual((status, res, self.argv), (6, None, []), unknown)
            self.assertIn("is not known", self.said)

    def test_what_is_not_read_as_n4n0_reads_it_starts_nothing(self):
        # (the review: Home's parse::<u32> takes "+1", the settings' reader here did not, and the private link was admitted)
        for key, why in (("+1", "several"), ("\u20031 ", "several"), ("x", "no number"), ("", "no number"), ("4294967296", "no number"), ("\u0661", "no number"), ("-1", "no number")):
            status, res, _ = self.run_with(settings=json.dumps({"launch": {"profiles": {"0": "usr_x", key: "usr_secret"}}}))
            self.assertEqual((status, res, self.argv), (6, None, []), key)
            self.assertIn(why, self.said)
            for private in ("usr_", WORLD, "25038"):
                self.assertNotIn(private, self.said)

        def unreadable(n4n0):
            with open(f"{n4n0}/settings.json", "w") as f:
                f.write("{}")
            os.chmod(f"{n4n0}/settings.json", 0)
        for prepare in (lambda n4n0: os.symlink("nowhere", f"{n4n0}/settings.json"), unreadable, lambda n4n0: os.mkdir(f"{n4n0}/settings.json"), lambda n4n0: os.chmod(n4n0, 0o300),
                        lambda n4n0: (os.rmdir(n4n0), os.symlink("nowhere", n4n0))):
            status, res, _ = self.run_with(prepare=prepare)
            self.assertEqual((status, res, self.argv), (6, None, []), self.said)
        for settings in ('{"launch": {"profiles": {"+0": "usr_x", " 00 ": "usr_x"}}}',):
            self.assertEqual(self.run_with(settings=settings)[0], 0, self.said)

    def test_a_gate_that_is_not_n4n0_s_starts_nothing(self):
        status, res, _ = self.run_with(files={"obelisk-start-gate.json": '{"boot":"bad"}'})
        self.assertEqual((status, res, self.argv), (6, None, []))
        status, res, _ = self.run_with(prepare=lambda n4n0: os.symlink("nowhere", f"{n4n0}/obelisk-start-gate.json"))
        self.assertEqual((status, res, self.argv), (6, None, []))

    def test_what_it_starts_is_noted_for_whoever_started_it(self):
        with tempfile.TemporaryDirectory() as d:
            status, _, _ = self.run_with(files={"obelisk-start-gate.lock": ""}, args=("--slot-held", "--note", f"{d}/note", "--caller", str(os.getppid())))
            self.assertEqual(status, 0)
            with open(f"{d}/note") as f:
                note = json.load(f)
            self.assertEqual((note["session"], bool(note["program"]["pid"]), bool(note["program"]["born"])), ("s-1", True, True))
            self.assertEqual(os.stat(f"{d}/note").st_mode & 0o777, 0o600)
            # whoever held the slot for it is gone: nothing is started, and nothing is noted
            status, res, _ = self.run_with(args=("--slot-held", "--note", f"{d}/other", "--caller", str(os.getppid() + 1)))
            self.assertEqual((status, res, self.argv, os.path.exists(f"{d}/other")), (6, None, [], False))

    def test_told_to_stop_it_ends_its_session_once_it_knows_it(self):
        for at, more in (("starting", {}), ("running", {})):
            kept, fired = bench.told, []

            def told(session, event, when):
                kept(session, event, when)
                if event.get("event") == at and not fired:
                    fired.append(1)
                    os.kill(os.getpid(), signal.SIGTERM)
                    os.kill(os.getpid(), signal.SIGINT)  # (and again: it ends what it started all the same)
            handlers = {n: signal.signal(n, bench.cut) for n in (signal.SIGINT, signal.SIGTERM)}
            try:
                bench.told = told
                status, res, quit = self.run_with(**more)
            finally:
                bench.told = kept
                bench.cut.__init__()
                for n, h in handlers.items():
                    signal.signal(n, h)
            self.assertEqual((status, res["session"], quit, self.slot, res["terminal"]["phase"]), (7, "s-1", True, "", "Finished"), at)
            self.assertEqual(len(self.quits), 1)

    def test_no_argument_names_a_profile_or_another_place(self):
        for arg in ("--profile=1", "--profile", LINK):
            status, res, _ = self.run_with(args=(f"--arg={arg}",))
            self.assertEqual((status, res, self.argv), (6, None, []), arg)
            self.assertNotIn("usr_", self.said)

    def test_the_link_is_one_instance_s_in_vrchat_s_own_grammar(self):
        good = (LINK, LINK.replace("~", "%7E").replace("(", "%28"), LINK + "&shortName=ab12", f"vrchat://launch?id={HERE}~canRequestInvite~nonce(0a1b-2c)")
        for link in good:
            bench.check_link(link)
        for link in (LINK + " --profile=1", LINK + '"', LINK + "&id=" + HERE, LINK + "&x=1", LINK.replace("launch", "evil"), LINK + "%20--x", "vrchat://launch?ref=x",
                     f"vrchat://launch?id={WORLD}:", f"vrchat://launch?id=wrld_1:{HERE}", LINK + "~re gion(x)", LINK + "~region()", "https://x/?id=" + HERE):
            with self.assertRaises(bench.Refused, msg=link) as refused:
                bench.check_link(link)
            self.assertNotIn("usr_", str(refused.exception))

    def test_the_slot_for_a_start_is_held_while_its_game_is_there_and_left_empty(self):
        status, _, _ = self.run_with()
        self.assertEqual((status, self.slot), (0, ""))
        held, note = self.slot_while_it_ran.split(" ", 1)
        note = json.loads(note)
        self.assertEqual((held, note["session"], note["program"], note["until"]), ("held", "s-1", None, None))
        self.assertEqual(note["boot"], bench.boot_clock()[0])
        # A start whose session may still run stays said: N4N0 waits for it as after one that ended early.
        status, _, _ = self.run_with(stays=True)
        self.assertEqual((status, json.loads(self.slot)["session"]), (5, "s-1"))

    def test_nothing_is_started_beside_n4n0_s_start_nor_in_its_wait(self):
        boot, at = bench.boot_clock()
        gate = lambda **k: {"obelisk-start-gate.json": json.dumps(dict(version=2, boot=boot, until=None, seen={}) | k)}
        for files, why in ((gate(until=at + 50), "ended early"), ({"obelisk-start-gate.json": "{ half"}, "cannot be read"), ({"obelisk-start-gate.json": "[]"}, "cannot be read"),
                           ({"obelisk-start-gate.lock": '{"boot": "x"}'}, "not settled")):
            status, res, _ = self.run_with(files=files)
            self.assertEqual((status, res, self.argv), (6, None, []), why)
            self.assertIn(why, self.said)
        for files in (gate(), gate(until=at - 1), gate(boot="00000000-0000-0000-0000-000000000000", until=at + 50)):
            self.assertEqual(self.run_with(files=files)[0], 0)
        with tempfile.TemporaryDirectory() as root:
            kept, bench.N4N0 = bench.N4N0, root
            try:
                with bench.Slot():
                    with self.assertRaisesRegex(bench.Refused, "beside"):
                        bench.Slot().__enter__()
                with bench.Slot():
                    pass  # (let go of)
            finally:
                bench.N4N0 = kept

    def test_somebody_else_s_session_is_never_asked_to_quit(self):
        """Sixth verification, finding 3 (the verifier's): a concurrent session's fresh pointer and record were taken for this
        launch's, and it was asked to quit."""
        status, res, _ = self.run_with(foreign=True)
        self.assertEqual((status, res["session"]), (0, "s-1"), res["outcome"])
        self.assertTrue(self.quits and all("--session s-1" in quit for quit in self.quits), self.quits)
        # The program died before it said what it started: nothing is asked to quit, and the series stops.
        status, res, quit = self.run_with(foreign=True, dies_unnamed=True)
        self.assertEqual((status, res["session"], quit), (5, None, False), res["outcome"])

    def test_a_session_the_program_found_instead_of_its_own_stops_the_series_untouched(self):
        """Seventh verification (the verifier's follower fixture): the program recovered an unrelated session and named it in
        `running`: an error, nothing of this Mac is asked to quit, and nothing more is started."""
        for how in ({"unnamed": True}, {}):
            status, res, quit = self.run_with(recovered="foreign", **how)
            self.assertEqual((status, quit), (5, False), (how, res["outcome"]))
            self.assertIn("another session", res["outcome"])
            self.assertNotEqual(res["session"], "foreign")
        session = {"id": None, "running_at": None}
        bench.told(session, {"event": "running", "session_id": "foreign"}, 1.0)
        self.assertEqual(session, {"id": None, "running_at": None})

    def test_each_run_that_does_not_go_as_planned_ends_its_session_and_says_so(self):
        for how, expected, outcome in (
            ({"joins": f"{OTHER}:1"}, 3, "did not arrive"),
            ({"never_calm": True}, 4, "did not settle"),
            ({"fails": True}, 2, "did not start"),
            # The program died once its game ran: the session is known from its admission, and asked to quit; here nothing
            # ends it.
            ({"dies": True}, 5, "did not start"),
            ({"stays": True}, 5, "measured"),
        ):
            status, res, quit = self.run_with(**how)
            self.assertEqual(status, expected, (how, res["outcome"]))
            self.assertIn(outcome, res["outcome"], how)
            self.assertEqual(quit, "fails" not in how, how)

    def test_running_is_the_program_s_word(self):
        session = {"id": "a", "running_at": None}
        bench.told(session, {"event": "starting"}, 1.0)
        self.assertEqual(session, {"id": "a", "running_at": None})
        bench.told(session, {"event": "running", "session_id": "a"}, 2.0)
        self.assertEqual(session, {"id": "a", "running_at": 2.0})
        # (the first name said is this launch's own: until the sixth verification the last one won)
        bench.told(session, {"event": "running", "session_id": "c"}, 3.0)
        self.assertEqual(session, {"id": "a", "running_at": 2.0})
        older = {"id": "a", "running_at": None}
        bench.told(older, {"event": "running", "session_id": None}, 2.0)
        self.assertEqual(older, {"id": "a", "running_at": 2.0})


if __name__ == "__main__":
    unittest.main()
