#!/usr/bin/env python3
"""The runner (tools/timeline/real_session.py): what authorizes the next start of a series, and what starts nothing; and what a whole series
says (score_series.py). No game, nothing of this Mac's own. Run: python3 -I test_session.py"""
import argparse, contextlib, copy, importlib.util, io, json, os, re, shutil, subprocess, sys, tempfile, time, unittest

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
                rescues_of_another_chunk_than_its_end_s=0, rescues=90, rescues_whose_commit_is_not_recorded=0, rescues_whose_end_is_not_recorded=0,
                debts=dict(accepted=0, covered=0, cancelled=0, outstanding_at_the_end=0, oldest_outstanding_ns=None),
                tries=dict(looks_of_half_a_ms_or_more=0, looks_of_5_ms_or_more=0, tries_of_looks_that_could_not=0, tries_of_the_rescue_thread_that_could_not=0),
                window=dict(looks=9000, s_false=8000, s_ok=900, rescues=90),
                one_by_one=dict(recorded=400, not_seen_though_looked_at_of_more_than_a_second=0, in_lists=0), signals=100, ended=dict(event=300, disjoint=100)) | more


def window(n, once, **more):
    return dict(window=n, valid=True, why=[], clock="stamped", frames=2400, whole_share=0.99, trace_not_complete=[], shown_per_s=40.0, from_s=200.0, arrived_after_s=60.0,
                conditions=dict(looks=10, whole_looks=5, seconds=60.0, longest_without_s=7.8, longest_without_a_whole_one_s=13.0, pressure=[0], on_ac=True, low_power_mode=["0"], locked=False), queries=queries(once), queries_of_every_queue=queries(once),
                production=dict(interval_ms=dict(mean=25.0)), work=dict(draws=1000.0, command_buffers=4.0),
                cadence=[dict(shown_interval_ms=dict(p95=33.4, p99=50.0), client_to_shown_ms=dict(p95=45.0), largest_gap_ms=66.0, holds_of_3_refreshes_or_more=3)]) | more


def result(once=False, windows=3, **more):
    return dict(percent=45, switches=dict(OBELISK_DXMT_QUERY_RESCUE="once") if once else {}, not_in_the_inventory=[], why_not=[], bench_status=0, outcome="measured", terminal=dict(phase="Finished", error=None, played=dict(ended_by_obelisk=True, exit_signal=None, exit_code=0)),
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
            q = r["windows"][2]["queries_of_every_queue"]
            q |= {k: q[k] | v if isinstance(v, dict) else v for k, v in change.items()}  # (that alone: the rest of what it holds is there)
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

    def test_a_counter_that_is_not_there_is_missing_and_not_zero(self):
        # (the review's fixture: without the slow calls' counters, nothing was said against it)
        for once in (False, True):
            for group, names in rs.COUNTERS.items():
                for name in names:
                    for how in ("gone", "null"):
                        r = result(once)
                        q = r["windows"][0]["queries_of_every_queue"]
                        of = q[group] if group else q
                        of.pop(name) if how == "gone" else of.update({name: None})
                        why = self.why(r, once)
                        self.assertTrue(any("window 1: not recorded: " in w and name in w for w in why), (group, name, how, why))
                if group:
                    r = result(once)
                    r["windows"][0]["queries_of_every_queue"].pop(group)
                    self.assertTrue(any("not recorded" in w for w in self.why(r, once)), group)
            r = result(once)
            r["windows"][0]["queries_of_every_queue"]["debts"].pop("oldest_outstanding_ns")
            self.assertEqual(len(self.why(r, once)), 1)
            for change in (dict(signals=0), dict(one_by_one=dict(recorded=0, not_seen_though_looked_at_of_more_than_a_second=0))):
                r = result(once)
                r["windows"][0]["queries_of_every_queue"] |= change
                self.assertIn("not recorded: any", self.why(r, once)[0])
        quiet = result(True)
        quiet["windows"][0]["queries_of_every_queue"] |= dict(ended=dict(event=0, disjoint=0), one_by_one=dict(recorded=0, not_seen_though_looked_at_of_more_than_a_second=0))
        self.assertEqual(self.why(quiet, True), [])

    def test_a_rescue_that_nothing_else_recorded_speaks_for_is_told_so(self):
        r = result(True)
        r["windows"][0]["queries_of_every_queue"]["rescues_whose_commit_is_not_recorded"] = 2
        self.assertEqual(self.why(r, True), ["window 1: 2 rescues whose commit is not recorded"])
        r = result(True)
        q = r["windows"][0]["queries_of_every_queue"]
        self.assertIsNone(rs.uncorroborated(q))
        q["rescues_whose_end_is_not_recorded"] = 7
        self.assertIn("of 90 rescues the End of 7 is not recorded", rs.uncorroborated(q))
        self.assertEqual(self.why(r, True), [], "Ends are a sample: told, and no series ends by it")

    def test_a_window_that_was_hardly_looked_at_is_not_known(self):
        r = result(True)
        for w in r["windows"]:
            w["conditions"]["looks"] = 1  # (the review's)
        self.assertEqual(sum("looked at 1 times" in w for w in self.why(r, True)), 3)
        for change in (dict(longest_without_s=15.5), dict(longest_without_a_whole_one_s=21.0), dict(whole_looks=1), dict(longest_without_s=None), dict(seconds=None)):
            r = result()
            r["windows"][1]["conditions"] |= change
            self.assertTrue(self.why(r) and all(w.startswith("window 2: ") for w in self.why(r)), change)
        ns, whole = 10**9, dict(thermal_pressure="com.apple.system.thermalpressurelevel 0", power=["'AC Power'"], low_power_mode="0")
        look = lambda t, n: dict(uptime_ns=t * ns, locked=False) | (whole if n % 2 == 0 else {})
        of = lambda times: rs.not_looked_at(rs.window_conditions([look(t, n) for n, t in enumerate(times)], 100 * ns, 160 * ns))
        self.assertEqual(of(range(94, 170, 6)), [])
        self.assertEqual(len(of(range(106, 140, 6))), 2, "not to its end")
        self.assertEqual(len(of(range(118, 170, 6))), 1, "not from its start")
        self.assertEqual(len(of([100, 106, 112, 118, 136, 142, 148, 154, 160])), 2, "a hole in the middle")
        self.assertEqual(len(of([130])), 2)
        self.assertEqual(len(of([])), 2)

    def test_what_every_host_program_loaded_is_known(self):
        for told in (None, ["wsd 8: wsd (it was not looked at)"]):
            self.assertTrue(any("loaded is not known" in w for w in self.why(result(not_in_the_inventory=told))), told)

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
        self.assertEqual(s.told["starts"][-1]["go_on"], not why)

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
                f.write(settings) if isinstance(settings, str) else json.dump(settings, f)
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

    def refused(self, said, *, settings=None, files=()):
        status, told = self.main(settings, files=files)
        self.assertEqual((status, self.started), (1, []), said)
        self.assertIn(said, told)
        for private in ("usr_", "wrld_", "12345"):
            self.assertNotIn(private, told)

    def test_a_profile_is_read_as_n4n0_reads_it_or_nothing_is_started(self):
        profiles = lambda *keys: {"launch": {"profiles": {k: "usr_secret" for k in keys}}}
        for key in ("+1", " +1 ", "01", "\u20031\u2003", "4294967295", "+0000000000000001"):
            self.refused("several VRChat profiles", settings=profiles("0", key))
        for key in ("0", "+0", " 0\u00a0", "0000000000000000"):
            self.assertEqual((self.main(profiles(key)), self.started), ((0, ""), [True]), key)
        for key in ("", "+", "-0", "-1", "++1", "+ 1", "1.0", "1e0", "1_0", "x", "4294967296", "\u0661", "\uff11", "\x1c1", "0x1", "\u200b1"):
            self.refused("no number", settings=profiles("0", key))
        for text in ('{"launch": {"profiles": {"0": "usr_x", "0": "usr_y"}}}', '{"launch": {}, "launch": {"profiles": {"1": "usr_x"}}}', '{"launch": {"profiles": {}}, "x": NaN}',
                     '{"launch": {"profiles": {"0": 1}}}', '{"launch": {"profiles": null}}', '{"launch": null}', '\ufeff{}', '{"x": "\\ud800"}', "", "[" * 100000):
            self.refused("is not known", settings=text)

    def test_settings_that_cannot_be_read_are_not_taken_for_none(self):
        n4n0 = f"{self.root}/n4n0"
        os.symlink("nowhere", f"{n4n0}/settings.json")
        self.refused("is not known")
        os.remove(f"{n4n0}/settings.json")
        os.mkdir(f"{n4n0}/settings.json")
        self.refused("is not known")
        os.rmdir(f"{n4n0}/settings.json")
        with open(f"{n4n0}/settings.json", "wb") as f:
            f.write(b'{"launch": {"profiles": {"\xff1": "usr_x"}}}')
        self.refused("is not known")
        with open(f"{n4n0}/settings.json", "w") as f:
            f.write("{}")
        os.chmod(f"{n4n0}/settings.json", 0)
        self.refused("is not known")
        os.remove(f"{n4n0}/settings.json")
        os.chmod(n4n0, 0o300)  # (it can be written in, and not be looked into)
        try:
            self.refused("cannot be read")
            os.chmod(n4n0, 0)
            self.refused("cannot be taken")
        finally:
            os.chmod(n4n0, 0o700)
        os.rename(n4n0, n4n0 + "-was")
        os.symlink("nowhere", n4n0)
        self.refused("cannot be taken")
        os.remove(n4n0)
        self.assertEqual((self.main(), self.started), ((0, ""), [True]), "no N4N0 at all")

    def record(self, name="00000000-0000-0000-0000-00000000000a", age=1000.0, text=None, mode=0o600, **more):
        folder = f"{self.root}/library/SteamSessions"
        os.makedirs(folder, mode=0o700, exist_ok=True)
        for old in os.listdir(folder):
            os.remove(f"{folder}/{old}")
        with open(f"{folder}/{name}.v2.json", "w") as f:
            f.write(text if text is not None else json.dumps(dict(version=2, id=name, store=dict(app_id=438100), phase="Finished", played=dict(seconds=300)) | more))
        os.chmod(f.name, mode)
        os.utime(f.name, (time.time() - age,) * 2)

    def test_when_the_last_session_ended_is_known_or_nothing_is_started(self):
        boot, at = rs.module(f"{TOOLS}/bench.py", "b").boot_clock()
        ended = lambda seconds, of=boot: dict(played=dict(seconds=300, ended=dict(boot=of, seconds=seconds)))
        other = "00000000-0000-0000-0000-00000000000b"
        good = ({}, ended(at - 1000), ended(at - 5, other), dict(store=dict(app_id=570), phase=3), dict(played=None), dict(phase="Running", played=None), dict(played=dict(ended=None)))
        for more in good:
            self.record(**more)
            self.assertEqual((self.main(), self.started), ((0, ""), [True]), more)
        self.record(name="session", text=json.dumps(dict(version=2, id=other)))
        self.assertEqual((self.main(), self.started), ((0, ""), [True]))
        for age, more in ((5, {}), (89, {}), (1000, ended(at - 5)), (5, ended(at - 1000)), (5, dict(store=dict(app_id=570)))):
            self.record(age=age, **more)
            self.refused("wait until 90 s have passed")
        for age, more in ((-5, {}), (-100000, {}), (1000, ended(at + 50)), (-5, ended(at - 1000))):
            self.record(age=age, **more)
            self.refused("still to come")
        damaged = [dict(text=x) for x in ("{", "", "[]", "3", "\x00", '{"id": NaN}')] + [dict(id=other), dict(id=None), dict(store=None), dict(store=dict(app_id="438100")), dict(store=dict(app_id=True)),
                   dict(store=dict(app_id=-1)), dict(phase=None), dict(played=3), dict(mode=0o644), dict(text=" " * 70000), dict(mode=0)]
        damaged += [dict(played=dict(ended=x)) for x in (3, dict(boot=boot), dict(boot="bad", seconds=1), dict(boot=boot, seconds=-1), dict(boot=boot, seconds="1"), dict(boot=boot, seconds=True))]
        damaged += [dict(name="session", text=json.dumps(dict(id="../x"))), dict(name="session", text="{")]
        for more in damaged:
            for age in (1, 95, 100000):
                self.record(age=age, **more)
                self.refused("cannot be read")
        folder = f"{self.root}/library/SteamSessions"
        self.record()
        os.remove(f"{folder}/{os.listdir(folder)[0]}")
        os.symlink("nowhere", f"{folder}/{other}.v2.json")
        self.refused("cannot be read")
        os.remove(f"{folder}/{other}.v2.json")
        os.chmod(folder, 0)
        self.refused("cannot be listed")
        os.chmod(folder, 0o700)
        os.rmdir(folder)
        os.symlink("nowhere", folder)
        self.refused("cannot be listed")
        os.remove(folder)
        with open(folder, "w"):
            pass
        self.refused("cannot be listed")
        os.remove(folder)
        self.assertEqual((self.main(), self.started), ((0, ""), [True]), "nothing ever ran")
        os.chmod(f"{self.root}/library", 0)
        try:
            self.refused("cannot be listed")
        finally:
            os.chmod(f"{self.root}/library", 0o700)

    def test_a_gate_that_n4n0_would_not_take_as_it_is_starts_nothing(self):
        boot, at = rs.module(f"{TOOLS}/bench.py", "b").boot_clock()
        whole = dict(version=2, boot=boot, until=None, seen={})
        without = lambda k: {x: v for x, v in whole.items() if x != k}
        for gate in (dict(boot="bad"), without("version"), without("seen"), without("boot"), whole | dict(version=1), whole | dict(version=True), whole | dict(boot=1795469782), whole | dict(boot="bad"),
                     whole | dict(until="1"), whole | dict(until=True), whole | dict(seen=[]), whole | dict(seen={"x": "1"}), whole | dict(seen=None), 3, None):
            self.refused("cannot be read", files=[("obelisk-start-gate.json", json.dumps(gate))])
        self.refused("cannot be read", files=[("obelisk-start-gate.json", json.dumps(whole)[:-1] + ', "until": Infinity}')])
        self.refused("ended early", files=[("obelisk-start-gate.json", json.dumps(whole | dict(until=at + 60)))])
        for gate in (whole, without("until"), whole | dict(boot="process-1-2", until=at + 60), whole | dict(seen={"x": 1.5}, until=at - 1)):
            self.assertEqual((self.main(files=[("obelisk-start-gate.json", json.dumps(gate))]), self.started), ((0, ""), [True]), gate)

    def test_nothing_is_started_while_the_release_is_owed(self):
        os.makedirs(f"{self.root}/out")
        with open(f"{self.root}/out/restoration-owed.json", "w") as f:
            json.dump(dict(library="/another"), f)  # (not this one's to put back, and no start beside it)
        status, said = self.main()
        self.assertEqual((status, self.started), (1, []))
        self.assertIn("--restore", said)

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
            self.assertIsNone(told["restored"], "nothing goes on before the released generation is back")
            self.assertEqual(told["not_in_the_inventory"], ["no host program was seen"])
            self.assertTrue(any("0 pictures" in w for w in told["why_not"]) and any("which plane" in w for w in told["why_not"]), told["why_not"])


class Inventory(unittest.TestCase):
    KNOWN = {p: f"{n:064x}" for n, p in enumerate(sorted({p for l in rs.INVENTORY.values() for p in l}))}
    FILES = [f"/t/otl-{role}-{pid}.bin" for role, pid in (("wsd", 8), ("vtest", 9), ("npt", 10), ("dxmt", 10))]

    def told(self, images, files=FILES, queues=[[10, 1]]):
        with tempfile.TemporaryDirectory() as root:
            for name, value in (("timeline.json", dict(voile="v")), ("engine-files.json", dict(released={}, timeline={}, timeline_graphics=self.KNOWN))) + ((("images.json", images),) if images is not None else ()):
                with open(f"{root}/{name}", "w") as f:
                    json.dump(value, f)
            session = rs.Session(argparse.Namespace(generation=root, bench=TOOLS, out=root, library=root, cli="/x"))
            return session.not_in_the_inventory(root, files, queues)

    def whole(self):
        of = lambda *roles: {f"/x/{p}": self.KNOWN[p] for role in roles for p in rs.INVENTORY[role]}
        return [dict(pid=8, name="wsd", images=of("wsd") | {"/x/other.data": None}), dict(pid=9, name="virgl_test_server", images=of("vtest")), dict(pid=10, name="virgl_render_server", images=of("npt", "dxmt"))]

    def test_every_process_that_recorded_is_in_it_with_the_generation_s_files(self):
        self.assertEqual(self.told(self.whole()), [])
        self.assertEqual(self.told(self.whole(), self.FILES + ["/t/otl-npt-77.bin"]), [], "another worker, that nothing of the game's was made on")

    def test_an_empty_or_a_partial_one_is_not_whole(self):
        for images in (None, [], {}, [dict(pid=8)], "x"):
            self.assertTrue(self.told(images), images)
        for n in range(3):
            self.assertEqual(len(self.told([p for i, p in enumerate(self.whole()) if i != n])), 2 if n == 2 else 1, n)
            images = self.whole()
            for path in [p for p in images[n]["images"] if not p.endswith(".data")]:
                for digest in (None, "f" * 64, "<[Errno 2]>"):
                    images = self.whole()
                    images[n]["images"][path] = digest
                    self.assertTrue(self.told(images), (path, digest))
        self.assertTrue(self.told(self.whole(), self.FILES[1:]), "no wsd recorded")
        self.assertTrue(self.told(self.whole(), self.FILES, None), "which worker is the game's is not known")


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

    def test_what_cannot_be_compared_is_for_nobody(self):
        other = dict(work=dict(draws=1500.0))
        slow = dict(shown_per_s=38.0)
        tail = dict(cadence=[dict(shown_interval_ms=dict(p95=60.0, p99=80.0), client_to_shown_ms=dict(p95=45.0))])
        for change in (slow, tail, self.BETTER, slow | tail):
            for why in (other, dict(conditions=dict(pressure=[2])), dict(queries=queries(True, ended=dict(event=100)))):
                told = self.series(change | why)
                self.assertEqual(told["verdict"], "INCONCLUSIVE", (change, why, told["why"]))
            self.assertEqual(self.series(change | other, b3=change)["verdict"], "INCONCLUSIVE", "one of the two windows")
        self.assertTrue(any("no verdict: " in n for n in self.series(slow | other)["notes"]), "it is told, and is none")
        # what B got wrong is wrong whatever the work was, and though its series ended by it
        for wrong in (dict(handed_over_and_committed=3), dict(left_not_handed_over=1), dict(debts=dict(cancelled=1)), dict(one_by_one=dict(not_seen_though_looked_at_of_more_than_a_second=1))):
            q = queries(True, **wrong)
            self.assertEqual(self.series(self.BETTER | other | dict(queries_of_every_queue=q))["verdict"], "REJECT", wrong)
            b = result(True, go_on=False)
            b["windows"][0]["queries_of_every_queue"] = q
            self.assertEqual(sc.score([result(go_on=True), b])["verdict"], "REJECT")
            b["windows"][0]["trace_not_complete"] = ["dxmt: records lost"]
            self.assertEqual(sc.score([result(go_on=True), b])["verdict"], "INCONCLUSIVE", "where records are lost nothing is shown")

    def test_what_is_not_there_is_not_known_and_no_error(self):
        cadence = [dict(shown_interval_ms=dict(p95=33.4, p99=50), client_to_shown_ms=dict(p95=80), tick_to_shown_ms=dict(p50=50))]
        told = self.series(self.BETTER | dict(cadence=cadence))  # (the review's: the As' tick to shown is not told)
        self.assertEqual(told["verdict"], "INCONCLUSIVE")
        self.assertIn("the As' not known and not known", "; ".join(told["why"]))

        def without(x):
            """x, less one thing, wherever that is"""
            if isinstance(x, dict):
                for k in x:
                    yield {a: b for a, b in x.items() if a != k}
                    yield x | {k: None}
                    yield from (x | {k: v} for v in without(x[k]))
            elif isinstance(x, list):
                yield []
                for i in range(len(x)):
                    yield x[:i] + x[i + 1:]
                    yield from (x[:i] + [v] + x[i + 1:] for v in without(x[i]))
        whole = [result(once, go_on=True) for once in (False, True, False)]
        for i in range(3):
            for less in without(whole[i]):
                self.assertIn(sc.score(whole[:i] + [less] + whole[i + 1:])["verdict"], ("KEEP", "REJECT", "INCONCLUSIVE"))

    def test_the_combined_switch_is_said_where_lists_have_queries(self):
        listed = queries(True)
        listed["one_by_one"] = listed["one_by_one"] | dict(in_lists=9)
        self.assertTrue(any("as a whole" in n for n in self.series(self.BETTER | dict(queries=listed))["notes"]))

    def test_a_series_that_is_not_whole_says_nothing(self):
        self.assertEqual(sc.score([result(go_on=True)] * 2)["verdict"], "INCONCLUSIVE")
        self.assertEqual(sc.score([result(go_on=True), result(True, go_on=False), result(go_on=True)])["verdict"], "INCONCLUSIVE")


class SeriesFiles(unittest.TestCase):
    """score_series.py on a series' own files: what they show, never what the journal says alone."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.starts, better = [], Scored.BETTER
        for n, once in enumerate((False, True, False)):
            r = result(once, go_on=True, restored=dict(verified=True, files={"engine/wsd": "0"}))
            for w in r["windows"]:
                w |= better if once else {}
            folder = f"{self.root}/{n}/start-45"
            os.makedirs(folder)
            self.starts.append(dict(switches=r["switches"], fixed=dict(plan=[45], windows=3), go_on=True, why=[], result=f"{folder}/result.json", nothing_wrong_seen_before_it=n > 0))
            self.put(n, r)

    def put(self, n, r, digest=True):
        with open(self.starts[n]["result"], "w") as f:
            json.dump(r, f)
        if digest:
            self.starts[n]["result_sha256"] = rs.sha(self.starts[n]["result"])
        self.save()

    def save(self):
        with open(f"{self.root}/series.json", "w") as f:
            json.dump(dict(starts=self.starts), f)

    def result(self, n):
        with open(self.starts[n]["result"]) as f:
            return json.load(f)

    def scored(self, *more):
        out = subprocess.run([f"{TOOLS}/score_series.py", self.root, *more, "--json", f"{self.root}/out.json"], capture_output=True, text=True)
        self.assertEqual((out.returncode, out.stderr), (0, ""))
        with open(f"{self.root}/out.json") as f:
            told = json.load(f)
        self.assertIn(f"{told['verdict']}{' (timing only)' if told['timing_only'] else ''}: ", out.stdout)
        return told

    def pictures(self, a, b, **more):
        with open(f"{self.root}/pictures-{a}-{b}.json", "w") as f:
            json.dump(dict(starts=[os.path.dirname(self.starts[i - 1]["result"]) for i in (a, b)], pairs=9, flagged=[]) | more, f)

    def test_a_whole_series_is_timing_only_until_the_pictures_and_the_eye_are_recorded(self):
        told = self.scored()
        self.assertEqual((told["verdict"], len(told["timing_only"])), ("KEEP", 3), told["why"])
        self.pictures(1, 2)
        self.assertEqual(len(self.scored()["timing_only"]), 2)
        self.pictures(2, 3)
        self.assertEqual(len(self.scored()["timing_only"]), 1)
        self.assertEqual(self.scored("--nothing-wrong-seen")["timing_only"], [])
        self.assertEqual(self.scored()["timing_only"], [], "it is kept")
        for wrong in (dict(flagged=["x"]), dict(flagged=None), dict(pairs=4), dict(starts=["/a", "/b"])):
            self.pictures(2, 3, **wrong)
            self.assertEqual(len(self.scored()["timing_only"]), 1, wrong)
        self.pictures(2, 3)
        self.starts[2]["nothing_wrong_seen_before_it"] = False
        self.save()
        self.assertEqual(len(self.scored()["timing_only"]), 1)

    def test_files_that_contradict_each_other_are_invalid(self):
        b = self.result(1)
        # (the review's: B's result says it did not go as planned, and its windows are not valid; the journal says it did)
        self.put(1, b | dict(go_on=False, why_not=["invalid window"], windows=[w | dict(valid=False) for w in b["windows"]]))
        told = self.scored("--nothing-wrong-seen")
        self.assertEqual(told["verdict"], "INVALID")
        self.assertFalse(os.path.exists(f"{self.root}/observed.json"), "of such a series nothing is kept")
        for change in (dict(go_on=False), dict(why_not=["x"]), dict(why_not=None), dict(switches={}), dict(switches=dict(OBELISK_DXMT_INIT_ORDER="1")), dict(restored=None), dict(restored=dict(verified=False, files=dict(a="b"))),
                       dict(restored=dict(verified=True, files={})), dict(windows=b["windows"][:2]), dict(windows=[w | dict(valid=False) for w in b["windows"]]), dict(percent=58), dict(bench_status=5),
                       dict(foreign_images=["x"]), dict(not_in_the_inventory=None), dict(windows=3), dict(windows=[w | dict(conditions=w["conditions"] | dict(looks=1)) for w in b["windows"]])):
            self.put(1, b | change)
            self.assertEqual(self.scored()["verdict"], "INVALID", change)
        self.put(1, b | dict(percent=45.0, x=1), digest=False)
        self.assertEqual(self.scored()["verdict"], "INVALID", "another file than the one that was published")
        self.put(1, b)
        self.assertEqual(self.scored()["verdict"], "KEEP")
        whole = copy.deepcopy(self.starts)
        for change in ((1, dict(go_on=False)), (1, dict(switches={})), (0, dict(switches=Scored.BETTER)), (2, dict(result=whole[0]["result"], result_sha256=whole[0]["result_sha256"])), (2, dict(result=None)),
                       (2, dict(result="/nowhere")), (1, dict(fixed=dict(plan=[58], windows=3)))):
            self.starts = copy.deepcopy(whole)
            self.starts[change[0]] |= change[1]
            self.save()
            self.assertEqual(self.scored()["verdict"], "INVALID", change)
        self.starts = whole + [whole[0]]
        self.save()
        self.assertEqual(self.scored()["verdict"], "INVALID")
        with open(f"{self.root}/series.json", "w") as f:
            f.write("{")
        self.assertEqual(self.scored()["verdict"], "INVALID")

    def test_a_series_that_ended_as_both_its_files_say_is_inconclusive(self):
        b = self.result(1)
        self.put(1, b | dict(go_on=False, why_not=["window 1: no frames"], windows=b["windows"][:1]))
        self.starts = self.starts[:2]
        self.starts[1] |= dict(go_on=False)
        self.save()
        self.assertEqual(self.scored()["verdict"], "INCONCLUSIVE")
        self.starts[1].pop("result")  # (and one whose end was not seen)
        self.save()
        self.assertEqual(self.scored()["verdict"], "INCONCLUSIVE")


class Pictures(unittest.TestCase):
    def test_a_whole_series_is_compared_and_kept_for_the_scorer(self):
        cp, kept = load("compare_pictures"), None
        with tempfile.TemporaryDirectory() as root:
            starts = []
            for n in range(3):
                os.makedirs(f"{root}/{n}")
                starts.append(dict(result=f"{root}/{n}/result.json"))
                for i in (1, 2, 3):
                    open(f"{root}/{n}/picture-{i}.png", "w").close()
            with open(f"{root}/series.json", "w") as f:
                json.dump(dict(starts=starts), f)
            same = dict(same_size=True, mean_difference=1.0, psnr_db=30.0, ssim=0.99, pixels_over_8=0.1, pixels_over_32=0.02, black_a=0.0, black_b=0.0, over_8_by_cell_16x9=[[0.0]])
            off = same | dict(ssim=0.97, pixels_over_32=0.04)
            cp.diff = lambda a, b, heat=None: off if "/2/" in b and "/1/" in a else same
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cp.whole_series(root), 0)
            for name, n, flagged in (("pictures-1-2.json", (0, 1), 0), ("pictures-2-3.json", (1, 2), 2)):
                with open(f"{root}/{name}") as f:
                    told = json.load(f)
                self.assertEqual((told["starts"], told["pairs"], len(told["flagged"])), ([f"{root}/{i}" for i in n], 9, flagged))
            cp.diff = lambda a, b, heat=None: dict(same_size=False)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cp.whole_series(root), 1)
            with open(f"{root}/pictures-1-2.json") as f:
                self.assertTrue(json.load(f)["flagged"])


class Commands(unittest.TestCase):
    """What README.md says to type runs as it is typed."""

    def test_each_command_of_the_readme_runs(self):
        with open(os.path.join(TOOLS, "README.md")) as f:
            named = {m[1] for m in re.finditer(r"(?m)^(?:python3 )?(tools/timeline/\w+\.(?:py|sh))\b", f.read())}
        self.assertLessEqual({f"tools/timeline/{n}.py" for n in ("real_session", "score_series", "compare_pictures", "rehearse", "otl")}, named)
        root = os.path.join(HERE, "../..")
        for name in sorted(named):
            listed = subprocess.run(["git", "ls-files", "-s", name], cwd=root, capture_output=True, text=True).stdout
            if listed:
                self.assertTrue(listed.startswith("100755 "), listed)
            out = subprocess.run([name, "--help"], cwd=root, capture_output=True, text=True)
            self.assertEqual((out.returncode, out.stderr), (0, ""), name)
            self.assertIn("usage:", out.stdout)


if __name__ == "__main__":
    unittest.main()
