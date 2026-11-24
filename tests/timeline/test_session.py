#!/usr/bin/env python3
"""The runner (tools/timeline/real_session.py): what authorizes the next start of a series, and what starts nothing; and what a whole series
says (score_series.py). No game, nothing of this Mac's own. Run: python3 -I test_session.py"""
import argparse, contextlib, copy, importlib.util, io, json, os, shutil, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, "../../tools/timeline")


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(TOOLS, name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


rs, sc = load("real_session"), load("score_series")
LINK = "vrchat://launch?ref=orbiters.cc&id=wrld_00000000-0000-0000-0000-000000000000:12345~private(usr_test)~region(eu)"


def queries(once, **more):
    return dict(once=[once], locked=[True], said_otherwise_than_its_watermarks=0, handed_over_and_committed=0 if once else 900, left_not_handed_over=0,
                most_rescues_of_a_chunk=1, rescues_whose_chunk_was_not_handed_over=0, rescues_of_a_chunk_something_else_committed=0,
                rescues_of_another_chunk_than_its_end_s=0, debts=dict(cancelled=0, oldest_outstanding_ns=None), tries=dict(looks_of_5_ms_or_more=0),
                one_by_one=dict(not_seen_though_looked_at_of_more_than_a_second=0, in_lists=0), signals=100, ended=dict(event=300, disjoint=100)) | more


def window(n, once, **more):
    return dict(window=n, valid=True, why=[], clock="stamped", frames=2400, whole_share=0.99, trace_not_complete=[], shown_per_s=40.0, from_s=200.0, arrived_after_s=60.0,
                conditions=dict(looks=12, pressure=[0], on_ac=True, low_power_mode=["0"], locked=False), queries=queries(once), queries_of_every_queue=queries(once),
                production=dict(interval_ms=dict(mean=25.0)), work=dict(draws=1000.0, command_buffers=4.0),
                cadence=[dict(shown_interval_ms=dict(p95=33.4, p99=50.0), client_to_shown_ms=dict(p95=45.0), largest_gap_ms=66.0, holds_of_3_refreshes_or_more=3)]) | more


def result(once=False, windows=3, **more):
    return dict(bench_status=0, outcome="measured", terminal=dict(phase="Finished", error=None, played=dict(ended_by_obelisk=True, exit_signal=None, exit_code=0)),
                roles=["dxmt", "npt", "vtest", "wsd"], foreign_images=[], pictures=[dict(file=f"picture-{i}.png") for i in (1, 2, 3)], plane=5, plane_share=0.99,
                windows=[window(n, once) for n in range(1, windows + 1)]) | more


class Judged(unittest.TestCase):
    def why(self, r, once=False, first=None):
        return rs.judge(r, 3, once, first)

    def test_a_start_that_went_as_planned_authorizes_the_next(self):
        self.assertEqual(self.why(result()), [])
        self.assertEqual(self.why(result(True), True), [])
        self.assertEqual(self.why(result(True), True, result()), [])

    def test_each_gate_of_the_readme_ends_the_series(self):
        r = result()
        for change, said in (
            (dict(bench_status=4), "status 4"), (dict(outcome="did not settle"), "did not settle"), (dict(terminal=None), "did not end as it was asked"),
            (dict(terminal=r["terminal"] | dict(phase="Failed")), "did not end"), (dict(terminal=r["terminal"] | dict(error="x")), "did not end"),
            (dict(terminal=r["terminal"] | dict(played=dict(ended_by_obelisk=False, exit_signal=None))), "a crash"),
            (dict(terminal=r["terminal"] | dict(played=dict(ended_by_obelisk=True, exit_signal=11))), "a crash"),
            (dict(windows=r["windows"][:2]), "2 windows of 3"), (dict(roles=["wsd", "npt", "dxmt"]), "the trace is of"), (dict(roles=[]), "no role"),
            (dict(foreign_images=["x"]), "not the generation's"), (dict(pictures=r["pictures"][:2]), "2 pictures"), (dict(pictures=None), "0 pictures"),
            (dict(plane=None), "which plane"), (dict(plane_share=0.6), "which plane")):
            why = self.why(r | change)
            self.assertTrue(any(said in w for w in why), (change, why))
        for change, said in (
            (dict(valid=False, why=["VRChat was not frontmost all along"]), "not valid: VRChat was not frontmost"), (dict(reader="failed"), "not read"),
            (dict(clock="by the wall clock"), "stamped"), (dict(frames=0), "no frames"), (dict(frames=None), "no frames"), (dict(whole_share=0.9499), "95.0 % of its frames"),
            (dict(trace_not_complete=["dxmt 10: records lost"]), "records lost"), (dict(trace_not_complete=None), "not told"), (dict(shown_per_s=None), "no shown rate"),
            (dict(conditions=None), "state in it is not known"), (dict(conditions=r["windows"][0]["conditions"] | dict(locked=True)), "locked"),
            (dict(conditions=r["windows"][0]["conditions"] | dict(on_ac=False)), "AC power"), (dict(conditions=r["windows"][0]["conditions"] | dict(pressure=[None])), "pressure is not known"),
            (dict(queries=None, queries_of_every_queue=None), "not told")):
            changed = copy.deepcopy(r)
            changed["windows"][1] |= change
            why = self.why(changed)
            self.assertTrue(why and all(w.startswith("window 2: ") for w in why) and any(said in w for w in why), (change, why))

    def test_the_mechanism_is_judged_in_the_arm_that_has_it(self):
        for change in (dict(handed_over_and_committed=1), dict(left_not_handed_over=1), dict(most_rescues_of_a_chunk=2), dict(rescues_whose_chunk_was_not_handed_over=1),
                       dict(rescues_of_a_chunk_something_else_committed=1), dict(rescues_of_another_chunk_than_its_end_s=1), dict(debts=dict(cancelled=1)),
                       dict(debts=dict(cancelled=0, oldest_outstanding_ns=2 * 10**9)), dict(tries=dict(looks_of_5_ms_or_more=2)),
                       dict(one_by_one=dict(not_seen_though_looked_at_of_more_than_a_second=1)), dict(locked=[True, False]), dict(locked=[]), dict(once=[False]), dict(once=[False, True]),
                       dict(said_otherwise_than_its_watermarks=1), dict(handed_over_and_committed=None)):
            r = result(True)
            r["windows"][2]["queries_of_every_queue"] |= change
            self.assertEqual(len(self.why(r, True)), 1, change)
        r = result()
        r["windows"][0]["queries_of_every_queue"] |= dict(handed_over_and_committed=5000, most_rescues_of_a_chunk=9, left_not_handed_over=3)
        self.assertEqual(self.why(r), [], "without the switch that is what is looked for")
        for change in (dict(locked=[False]), dict(once=[True])):
            r = result()
            r["windows"][0]["queries_of_every_queue"] |= change
            self.assertEqual(len(self.why(r)), 1, change)
        r = result(True)
        r["windows"][0]["queries"] |= dict(left_not_handed_over=7)
        self.assertEqual(self.why(r, True), [], "every queue's is what is judged")

    def test_heat_that_one_start_alone_had_ends_it(self):
        hot = result(True)
        hot["windows"][1]["conditions"] = hot["windows"][1]["conditions"] | dict(pressure=[0, 2])
        self.assertEqual(self.why(hot, True), [])
        self.assertIn("the first start's was 0", self.why(hot, True, result())[0])
        self.assertEqual(self.why(hot, True, {**result(), "windows": copy.deepcopy(hot["windows"])}), [])

    def test_the_conditions_of_a_window_are_its_own(self):
        look = lambda t, **more: dict(uptime_ns=t, locked=False) | more
        whole = dict(thermal_pressure="com.apple.system.thermalpressurelevel 1", power=["Now drawing from 'AC Power'", "x"], low_power_mode="0")
        looks = [look(1, **whole), look(10, **whole), look(15), look(20, **whole | dict(thermal_pressure="com.apple.system.thermalpressurelevel 2")), look(90, **whole | dict(power=["'Battery Power'"]))]
        c = rs.window_conditions(looks, 5, 30)
        self.assertEqual((c["looks"], c["pressure"], c["on_ac"], c["locked"]), (3, [1, 2], True, False))
        self.assertFalse(rs.window_conditions(looks, 80, 99)["on_ac"])
        self.assertEqual(rs.window_conditions(looks, 200, 300)["looks"], 0)
        self.assertEqual((rs.pressure("nothing"), rs.pressure("com.apple.system.thermalpressurelevel 0\n")), (None, 0))


class SeriesOfStarts(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)

    def series(self):
        return rs.Series(os.path.join(self.root, "s"))

    def made(self, s, switches, why=(), fixed=None, r=None):
        s.begin(switches, fixed or dict(cli="1"), "/x")
        path = os.path.join(self.root, f"r{len(s.told['starts'])}.json")
        with open(path, "w") as f:
            json.dump(r or result(), f)
        s.ended(path, list(why))

    ONCE = dict(OBELISK_DXMT_QUERY_RESCUE="once")

    def test_three_starts_a_b_a_and_no_fourth(self):
        fixed = dict(cli="1")
        self.assertEqual(self.series().problems({}, fixed, False), [])
        self.assertIn("without a switch", self.series().problems(self.ONCE, fixed, False)[0])
        self.made(self.series(), {})
        self.assertEqual(self.series().problems(self.ONCE, fixed, True), [])
        self.assertIn("with the switch under test", self.series().problems({}, fixed, True)[0])
        self.assertIn("for the person at the Mac to say", self.series().problems(self.ONCE, fixed, False)[0])
        self.assertIsNone(rs.Series(os.path.join(self.root, "other")).first())
        self.made(self.series(), self.ONCE)
        self.assertEqual(self.series().first()["outcome"], "measured")
        self.assertEqual(self.series().problems({}, fixed, True), [])
        self.assertTrue(self.series().problems(self.ONCE, fixed, True))
        self.made(self.series(), {})
        self.assertEqual(self.series().problems({}, fixed, True), ["the series has had its 3 starts"])
        self.assertEqual(os.stat(os.path.join(self.root, "s/series.json")).st_mode & 0o777, 0o600)

    def test_a_start_that_was_not_as_planned_or_not_seen_to_its_end_ends_the_series(self):
        s = self.series()
        self.made(s, {}, ["window 1: no frames"])
        told = self.series().problems(self.ONCE, dict(cli="1"), True)
        self.assertEqual(len(told), 1)
        self.assertIn("ended at its start 1: window 1: no frames", told[0])
        s = rs.Series(os.path.join(self.root, "t"))
        s.begin({}, dict(cli="1"), "/x")  # (and this program was killed)
        self.assertIn("what became of it is not known", rs.Series(os.path.join(self.root, "t")).problems(self.ONCE, dict(cli="1"), True)[0])

    def test_what_is_the_same_for_all_is_checked_and_the_place_is_not_kept(self):
        s = self.series()
        fixed = dict(cli="1", generation="g", place=s.place(LINK))
        self.made(s, {}, fixed=fixed)
        again = self.series()
        self.assertEqual(again.place(LINK), fixed["place"])
        for k, v in (("cli", "2"), ("generation", "h"), ("place", again.place(LINK.replace("12345", "12346")))):
            self.assertEqual(again.problems(self.ONCE, fixed | {k: v}, True), [f"{k} is not the one of the series' first start"])
        with open(os.path.join(self.root, "s/series.json")) as f:
            text = f.read()
        for private in ("usr_", "wrld_", "12345"):
            self.assertNotIn(private, text)

    def test_a_series_that_cannot_be_read_starts_nothing(self):
        os.makedirs(os.path.join(self.root, "s"))
        with open(os.path.join(self.root, "s/series.json"), "w") as f:
            f.write("{ half")
        with self.assertRaises(ValueError):
            self.series()


class NothingIsStarted(unittest.TestCase):
    """main(): what it refuses before anything is put in place."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        generation = os.path.join(self.root, "generation")
        os.makedirs(generation)
        os.makedirs(os.path.join(self.root, "n4n0"))
        for name, text in (("timeline.json", '{"voile": "v"}'), ("engine-files.json", '{"released": {}, "timeline": {}, "timeline_graphics": {}}')):
            with open(os.path.join(generation, name), "w") as f:
                f.write(text)
        self.cli = os.path.join(self.root, "cli")
        with open(self.cli, "w") as f:
            f.write(f"#!/bin/sh\necho \"$@\" >> '{self.root}/asked'\n")
        os.chmod(self.cli, 0o755)
        self.kept = {n: getattr(rs, n) for n in ("locked", "engine_running", "PICTURE", "run")}
        rs.locked, rs.engine_running, rs.PICTURE = lambda: False, lambda: [], os.path.join(TOOLS, "otl.py")
        self.said = dict(pressure="com.apple.system.thermalpressurelevel 0", power="Now drawing from 'AC Power'", may="yes")
        rs.run = lambda cmd, timeout=15, env=None: (self.said["may"] if cmd[-1] == "may" else self.said["pressure"] if "notifyutil" in cmd[0] else self.said["power"] if "pmset" in cmd[0] else "")
        self.addCleanup(lambda: [setattr(rs, n, v) for n, v in self.kept.items()])

    def main(self, settings=None, link=LINK, switches=None, rehearse=False, files=()):
        if settings is not None:
            with open(f"{self.root}/n4n0/settings.json", "w") as f:
                json.dump(settings, f)
        for name, text in files:
            with open(f"{self.root}/n4n0/{name}", "w") as f:
                f.write(text)
        a = argparse.Namespace(link=link, cli=self.cli, generation=f"{self.root}/generation", bench=TOOLS, out=f"{self.root}/out", passes=8, mb=1536, plan=[45], warm=120, window=60,
                               windows=3, between=90, library=f"{self.root}/library", rehearse=rehearse, switches=switches or {}, series="s", nothing_wrong_seen=False)
        session = rs.Session(a)
        session.bench.N4N0 = f"{self.root}/n4n0"
        session.starts = lambda slot: self.started.append(slot.file is not None) or 0
        self.started, err = [], io.StringIO()
        with contextlib.redirect_stderr(err):
            status = session.main()
        self.assertFalse(os.path.exists(f"{self.root}/asked"), "the program was asked for something")
        return status, err.getvalue()

    def test_one_profile_goes_on_with_the_slot_held(self):
        for settings in (None, {"launch": {"profiles": {"0": "usr_x"}}}):
            self.assertEqual((self.main(settings), self.started), ((0, ""), [True]))

    def test_several_profiles_start_nothing(self):
        status, said = self.main({"launch": {"profiles": {"0": "usr_secret", "2": "usr_other"}}})
        self.assertEqual((status, self.started), (1, []))
        self.assertIn("several VRChat profiles", said)
        for private in ("usr_", "wrld_", "12345"):
            self.assertNotIn(private, said)

    def test_n4n0_s_own_start_and_wait_are_respected(self):
        status, said = self.main(files=[("obelisk-start-gate.lock", '{"boot": "x"}')])
        self.assertEqual((status, self.started), (1, []))
        self.assertIn("not settled", said)

    def test_the_mac_s_state_and_the_pictures_are_looked_at_before_a_start_is_spent(self):
        for change, why in ((dict(pressure="com.apple.system.thermalpressurelevel 1"), "thermal pressure is 1"), (dict(pressure=""), "pressure is None"),
                            (dict(power="'Battery Power'"), "AC power"), (dict(may="no"), "record windows")):
            kept = dict(self.said)
            self.said |= change
            status, said = self.main()
            self.said = kept
            self.assertEqual((status, self.started), (1, []), change)
            self.assertIn(why, said)

    def test_a_link_that_is_not_one_instance_s_or_a_switch_out_of_turn_starts_nothing(self):
        for link in (LINK + "&id=x", LINK + " --profile=1"):
            status, said = self.main(link=link)
            self.assertEqual((status, self.started), (1, []))
            self.assertNotIn("usr_", said)
        status, said = self.main(switches=dict(OBELISK_DXMT_QUERY_RESCUE="once"))
        self.assertEqual((status, self.started), (1, []))
        self.assertIn("without a switch", said)


class Reported(unittest.TestCase):
    """report(): the reader's numbers of the game's plane, of a recording made by hand (test_otl.py's)."""

    def test_the_windows_are_told_of_the_game_s_plane_alone(self):
        spec = importlib.util.spec_from_file_location("test_otl", os.path.join(HERE, "test_otl.py"))
        made = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(made)
        MS = made.MS
        with tempfile.TemporaryDirectory() as root:
            r = made.Recording()
            r.export(MS, 0xAAA, export=1, buffer=1)
            r.export(2 * MS, 0xBBB, pointer=0x2000, export=2, buffer=2)
            for i in range(200):  # the game's, 50 a second; and another plane's, of another queue
                r.frame((1000 + 20 * i) * MS, export=1, plane=5)
                if i % 4 == 0:
                    r.frame((1007 + 20 * i) * MS, export=2, plane=6, window=2, queue=2)
            for t in (2100, 3100):
                for queue, events in ((1, 3), (2, 99)):
                    r.put("dxmt", t * MS, "D_QUERIES", 2, queue, 1, events, 0, 0, 0)
            r.finish()
            folder = os.path.join(root, "start")
            os.makedirs(os.path.join(folder, "trace"))
            shutil.move(r.dir, os.path.join(folder, "trace", "one"))
            one = lambda lo: dict(valid=True, invalid_because=[], from_uptime_ns=lo * MS, to_uptime_ns=(lo + 1000) * MS, from_s=1.0, guest_present=dict(submitted_per_second_counted=1, fence_wait_ms_median=1),
                                  wsd_shown=dict(per_second=99.0))
            with open(os.path.join(folder, "bench.json"), "w") as f:
                json.dump(dict(outcome="measured", windows=[one(2000), one(3000)], observed={}, pictures=[], arrived_after_s=0.5, session="s"), f)
            with open(os.path.join(folder, "conditions.jsonl"), "w") as f:
                f.write(json.dumps(dict(wall=1, uptime_ns=2500 * MS, locked=False, thermal_pressure="com.apple.system.thermalpressurelevel 1", power=["'AC Power'"], low_power_mode="0")) + "\n")
            generation = os.path.join(root, "generation")
            os.makedirs(generation)
            for name, text in (("timeline.json", '{"voile": "v"}'), ("engine-files.json", '{"released": {}, "timeline": {}, "timeline_graphics": {}}')):
                with open(os.path.join(generation, name), "w") as f:
                    f.write(text)
            a = argparse.Namespace(link=LINK, cli="/x", generation=generation, bench=TOOLS, out=root, passes=8, mb=1536, plan=[45], windows=2, library=root, rehearse=True, switches={}, series=None)
            with contextlib.redirect_stdout(io.StringIO()):
                told = rs.Session(a).report(folder, os.path.join(folder, "trace"), 45, 0)
            self.assertEqual((told["plane"], told["queues"], round(told["plane_share"], 1)), (5, [[10, 1]], 0.8))
            for w in told["windows"]:
                self.assertEqual((w["plane"], w["shown_per_s"], w["hud_per_s"], w["production"]["per_s"]), (5, 50.0, 99.0, 50.0))
                self.assertEqual((w["queries"]["ended"]["event"], w["queries_of_every_queue"]["ended"]["event"], len(w["cadence"])), (3, 102, 1))
                self.assertEqual((w["trace_not_complete"], w["whole_share"], w["clock"]), ([], 1.0, "stamped"))
            self.assertEqual((told["windows"][0]["conditions"]["pressure"], told["windows"][1]["conditions"]["looks"]), ([1], 0))
            self.assertFalse(told["go_on"])
            self.assertTrue(any("0 pictures" in w for w in told["why_not"]) and any("which plane" in w for w in told["why_not"]), told["why_not"])


class Scored(unittest.TestCase):
    def series(self, b=dict(), a=dict(), a2=None, b3=None):
        out = []
        for once, change in ((False, a), (True, b), (False, a if a2 is None else a2)):
            r = result(once, go_on=True)
            for w in r["windows"]:
                w |= dict(shown_per_s=40.0, production=dict(interval_ms=dict(mean=25.0))) | (b3 if once and b3 is not None and w["window"] == 3 else change)
            out.append(r)
        return sc.score(out)

    BETTER = dict(shown_per_s=43.0, production=dict(interval_ms=dict(mean=23.2)))

    def test_better_than_both_in_both_is_a_provisional_keep_and_40_is_said_apart(self):
        told = self.series(self.BETTER)
        self.assertEqual((told["verdict"], told["holds_40"]), ("KEEP", True), told)
        slow = dict(shown_per_s=36.0, production=dict(interval_ms=dict(mean=27.7)))
        told = self.series(dict(shown_per_s=38.33, production=dict(interval_ms=dict(mean=26.1))), slow)
        self.assertEqual((told["verdict"], told["holds_40"]), ("KEEP", False))

    def test_under_the_bands_or_mixed_is_inconclusive(self):
        for b in (dict(shown_per_s=40.7), dict(shown_per_s=43.0), dict(shown_per_s=43.0, production=dict(interval_ms=dict(mean=24.6)))):
            self.assertEqual(self.series(b)["verdict"], "INCONCLUSIVE", b)
        # 2 % above both, but not more than the two As are apart
        self.assertEqual(self.series(self.BETTER, a2=dict(shown_per_s=36.5, production=dict(interval_ms=dict(mean=27.4))))["verdict"], "INCONCLUSIVE")
        told = self.series(self.BETTER, b3=dict(shown_per_s=40.1))
        self.assertEqual((told["verdict"], told["why"]), ("INCONCLUSIVE", ["W2 and W3 disagree"]))

    def test_work_that_is_not_the_same_or_an_a_without_stalls_is_inconclusive(self):
        for change, why in ((dict(work=dict(draws=800.0)), "another workload"), (dict(queries=queries(True, ended=dict(event=100))), "Ends of queries"),
                            (dict(conditions=dict(pressure=[2])), "thermal pressure"), (dict(work=None), "not known")):
            told = self.series(self.BETTER | change)
            self.assertEqual(told["verdict"], "INCONCLUSIVE", change)
            self.assertTrue(any(why in w for w in told["why"]), told["why"])
        none = queries(False, handed_over_and_committed=0)
        self.assertEqual(self.series(self.BETTER, a=dict(queries=none, queries_of_every_queue=none))["verdict"], "INCONCLUSIVE")

    def test_worse_is_a_rejection(self):
        self.assertEqual(self.series(dict(shown_per_s=38.0))["verdict"], "REJECT")
        slow = [dict(shown_interval_ms=dict(p95=33.4, p99=80.0), client_to_shown_ms=dict(p95=45.0))]
        self.assertEqual(self.series(self.BETTER | dict(cadence=slow))["verdict"], "REJECT")
        self.assertEqual(self.series(self.BETTER | dict(queries_of_every_queue=queries(True, handed_over_and_committed=3)))["verdict"], "REJECT")
        # the window server had a drawable more in flight for the whole of the start: not a rejection, and no keep either
        state = lambda tick, client: [dict(shown_interval_ms=dict(p95=33.4, p99=50.0), client_to_shown_ms=dict(p95=client), tick_to_shown_ms=dict(p50=tick))]
        told = self.series(self.BETTER | dict(cadence=state(49.5, 62.0)), a=dict(cadence=state(32.8, 45.0)))
        self.assertEqual(told["verdict"], "INCONCLUSIVE")
        self.assertTrue(any("tick to shown" in w for w in told["why"]))
        self.assertEqual(self.series(self.BETTER | dict(cadence=state(32.9, 62.5)), a=dict(cadence=state(32.8, 45.0)))["verdict"], "REJECT", "the part before the tick")
        a_little = [dict(shown_interval_ms=dict(p95=34.0, p99=51.0), client_to_shown_ms=dict(p95=45.0))]
        told = self.series(self.BETTER | dict(cadence=a_little))
        self.assertEqual(told["verdict"], "KEEP")
        self.assertTrue(any("is worse" in n for n in told["notes"]))

    def test_the_combined_switch_is_said_where_lists_have_queries(self):
        listed = queries(True)
        listed["one_by_one"] = listed["one_by_one"] | dict(in_lists=9)
        self.assertTrue(any("as a whole" in n for n in self.series(self.BETTER | dict(queries=listed))["notes"]))

    def test_a_series_that_is_not_whole_says_nothing(self):
        self.assertEqual(sc.score([result(go_on=True)] * 2)["verdict"], "INCONCLUSIVE")
        self.assertEqual(sc.score([result(go_on=True), result(True, go_on=False), result(go_on=True)])["verdict"], "INCONCLUSIVE")


if __name__ == "__main__":
    unittest.main()
