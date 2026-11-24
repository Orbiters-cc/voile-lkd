#!/usr/bin/env python3
"""The reader (tools/timeline/otl.py) on recordings made by hand: what may be joined is, what may not is counted, nothing is
filled in. Run: python3 -I test_otl.py"""
import contextlib, csv, importlib.util, io, json, os, struct, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("otl", os.path.join(HERE, "../../tools/timeline/otl.py"))
otl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(otl)
MS = 1_000_000


class Recording:
    """One start: a worker (npt and dxmt), a vtest and a wsd, and frames as the programs record them."""

    def __init__(self, passes=0):
        self.dir = tempfile.mkdtemp()
        self.passes = passes
        self.records = {("npt", 10): [], ("dxmt", 10): [], ("vtest", 9): [], ("wsd", 8): []}
        self.put("dxmt", 1, "D_QUEUE", 1, 1)
        for t in (1 * MS, 10_000 * MS):
            self.put("dxmt", t, "D_CLOCK", 0, t * 2, t * 2 + 14, t, t + 100, 1)
        self.n, self.exports, self.ends = 0, {}, {}

    def put(self, role, t, kind, a, *v, thr=1, pid=None):
        pid = pid or {"npt": 10, "dxmt": 10, "vtest": 9, "wsd": 8}[role]
        self.records.setdefault((role, pid), []).append((t, otl.K[kind], thr, a, *(list(v) + [0] * 6)[:6]))

    def export(self, t, ident, pointer=0x1000, export=1, buffer=1, client=1):
        self.put("npt", t, "N_EXPORT", 1, pointer, ident, 2940 << 32 | 1912, 28, export)
        self.put("wsd", t + 1, "W_ATTACH", buffer, ident, 2940 << 32 | 1912, 1, client)
        self.exports[export] = (ident, buffer, client)

    def frame(self, t, export=1, plane=5, window=1, leave=(), value=None, fence=0x77, handle=0x88, status=4, copies=1, rc=1, chunks=1,
              client_at=None, shown=True, replaced=0, queue=1, notify_early=False):
        """A frame whose Signal is decoded at t; its boundaries follow at fixed distances, those named in `leave` are not recorded."""
        self.n += 1
        n, v = self.n, value or self.n
        ident, buffer, client = self.exports[export]
        put = lambda name, *a, **k: None if name in leave else self.put(*a, **k)
        fid, chunk = 1000 + n, 100 + n * chunks
        put("EVENT", "npt", t - 6 * MS, "N_EVENT", 0, 500 + n, handle, 1)
        put("ARM", "npt", t - 5 * MS, "N_ARM", 2, 700 + n, 500 + n, 1)
        put("FENCE", "npt", t - 4 * MS, "N_FENCE", 2, fid, 1)
        put("PAIR", "npt", t - 4 * MS + 1, "N_PAIR", 2, fid, 500 + n, 1, 700 + n)
        put("SEOC", "dxmt", t - 3 * MS, "D_SEOC", 0, fence, v, handle, 0x99)
        put("SIGNAL", "npt", t, "N_SIGNAL", 1, t - 100_000, fence, v, 50_000, t - 2 * MS, 200)
        put("COUNTS", "npt", t, "N_COUNTS", 1, 10, 1, 1, 1, 0, 1 << 32)
        put("FRAME", "npt", t, "N_FRAME", copies, fence, v, export, t - 200_000, t - 150_000, n)
        put("DSIGNAL", "dxmt", t - 50_000, "D_SIGNAL", 0, chunk, fence, v, 0x99, queue, n)
        for c in range(chunk - chunks + 1, chunk + 1):
            put("READY", "dxmt", t + 10_000, "D_READY", 0, queue, c, 0, n)
            put("ENCODE", "dxmt", t + 300_000, "D_ENCODE", 0, c, t + 50_000, t + 100_000, t + 250_000, 0, queue)
            put("DONE", "dxmt", t + 8 * MS + 5000, "D_DONE", status, c, t + 400_000 if c == chunk else t + 300_000, t + 8 * MS, 0, 0, queue)
        put("NOTIFY", "dxmt", t + (7 * MS if notify_early else 8 * MS + 60_000), "D_NOTIFY", 0, 0x99, v, handle)
        put("RETIRE", "npt", t + 8 * MS + 90_000, "N_RETIRE", 2, fid, t + 8 * MS + 70_000, t - 3 * MS, 1, rc & 2**64 - 1)
        put("VRETIRE", "vtest", t + 8 * MS + 95_000, "V_RETIRE", 2, fid, 4000 + n, 1)
        at = client_at or t + 8 * MS + 120_000
        put("RX", "wsd", at + 20_000, "W_RX", window | (1 << 31 if replaced else 0), buffer, n, at, at + 20_000, replaced, client << 32 | plane)
        if shown:
            put("DRAW", "wsd", at + 3 * MS, "W_DRAW", window, buffer, n, at + 2 * MS, at + 2 * MS + 10_000, 1, plane)
            put("GPU", "wsd", at + 4 * MS, "W_GPU", window, n, at + 3 * MS, at + 3 * MS + 500_000, 0, 0, plane)
            put("SHOWN", "wsd", at + 20 * MS, "W_SHOWN", window, n, at + 18 * MS, 1, plane)
            put("TICK", "wsd", at + 2 * MS, "W_TICK", window | 1 << 16, at, at + 16 * MS, 16_666_667, plane)
        self.ends[n] = at

    def finish(self, only=None):
        for (role, pid), l in self.records.items():
            if only and role not in only:
                continue
            with open(f"{self.dir}/otl-{role}-{pid}.bin", "wb") as f:
                f.write(struct.pack("<4sIII16sQQQQ", b"OTL1", 2, pid, self.passes, role.encode(), 1, 1, 1, 1 << 30))
                for r in sorted(l, key=lambda r: r[0]):
                    f.write(otl.REC.pack(*r))
                if not any(r[1] == otl.K["END"] for r in l):
                    f.write(otl.REC.pack(10**12, otl.K["END"], 0xffff, 0, len(l), 0, 0, 0, 0, 0))
        return otl.Session(self.dir)


def steady(frames=5, **k):
    r = Recording()
    r.export(MS, 0xAAA)
    for i in range(frames):
        r.frame((100 + 20 * i) * MS, **k)
    return r


class Joins(unittest.TestCase):
    def test_whole_frames_are_whole_and_their_parts_sum(self):
        s = steady().finish()
        whole = [f for f in s.frames if "parts" in f]
        self.assertEqual(len(whole), 4)  # the first's wait has no beginning that is known
        self.assertIn("first of its plane", s.frames[0]["why"][0])
        for f in whole:
            self.assertEqual(sum(f["parts"]), f["wait"])
            self.assertEqual(f["shown"], f["client"] + 18 * MS)

    def test_a_boundary_that_is_missing_is_said_and_never_filled_in(self):
        for leave, said in (("NOTIFY", "missing: notify"), ("READY", "missing: ready"), ("ENCODE", "missing: enc"), ("DONE", "missing: done"),
                            ("FENCE", "missing: fence"), ("RETIRE", "missing: retire"), ("VRETIRE", "missing: proxy"), ("PAIR", "missing: pair"),
                            ("ARM", "missing: arm"), ("EVENT", "missing: the event of its HANDLE"), ("SEOC", "missing: SetEventOnCompletion"),
                            ("DSIGNAL", "missing: DXMT's signal"), ("RX", "missing: presentation")):
            r = steady(3)
            r.frame(200 * MS, leave=(leave,), handle=0x200)
            s = r.finish()
            f = s.frames[-1]
            self.assertEqual(f["why"][0], said, leave)
            self.assertNotIn("parts", f)
            self.assertNotIn("wait", f)
            told = otl.counted(s, s.frames)
            self.assertEqual(told["whole"], 2)
            self.assertEqual(told["not_whole"][said], 1)

    def test_a_failed_command_buffer_or_wait_is_no_boundary(self):
        r = steady(3)
        r.frame(200 * MS, status=5)
        r.frame(220 * MS, rc=0)
        r.frame(240 * MS, rc=-1)
        s = r.finish()
        self.assertEqual([f["why"][:1] for f in s.frames[-3:]],
                         [["its command buffer's status is 5"], ["its fence was retired without its signal"]] + [["its fence was retired without its signal"]])

    def test_boundaries_out_of_order_are_not_clamped(self):
        r = steady(3)
        r.frame(200 * MS, notify_early=True)
        s = r.finish()
        self.assertEqual(s.frames[-1]["why"], ["out of order: notify before gpu_end"])
        self.assertNotIn("parts", s.frames[-1])

    def test_a_fence_pointer_and_value_used_again_join_their_own(self):
        r = Recording()
        r.export(MS, 0xAAA)
        for i in range(6):  # a new device's fence at the same address, its values from 1 again, and the same handle
            r.frame((100 + 20 * i) * MS, value=i % 3 + 1, handle=0x88)
        s = r.finish()
        # two SetEventOnCompletion of one fence and value cannot be told apart by them alone: said, not guessed
        for f in s.frames:
            self.assertTrue("parts" in f or f["why"], f)
        for f in s.frames:
            if "parts" in f:
                self.assertEqual(f["gpu_end"], f["signal_end"] + 8 * MS)
        self.assertEqual(sum("ambiguous: SetEventOnCompletion" in f["why"] for f in s.frames), 6)

    def test_an_event_handle_used_again_is_another_event(self):
        s = steady(6, handle=0x88).finish()  # one handle, an event made anew for each wait: six ids
        self.assertEqual(sum("parts" in f for f in s.frames), 5)

    def test_an_event_armed_twice_before_one_wait_is_not_told(self):
        r = steady(3)
        r.put("npt", 195 * MS, "N_EVENT", 0, 9000, 0x200, 1)
        r.put("npt", 196 * MS - 5, "N_ARM", 2, 9001, 9000, 1)
        r.put("npt", 196 * MS - 4, "N_ARM", 2, 9002, 9000, 1)
        r.frame(200 * MS, leave=("EVENT", "ARM"), handle=0x200)
        s = r.finish()
        self.assertIn("ambiguous: arm", s.frames[-1]["why"])

    def test_a_buffer_id_used_again_names_the_image_it_was_attached_to_then(self):
        r = Recording()
        r.export(MS, 0xAAA, export=1, buffer=1)
        r.frame(100 * MS, export=1)
        r.frame(120 * MS, export=1)
        r.put("wsd", 140 * MS, "W_DETACH", 1, 1)
        r.export(141 * MS, 0xBBB, pointer=0x1000, export=2, buffer=1)  # a resize: the same pointer and buffer id, another memory
        r.frame(160 * MS, export=2, plane=6)
        r.frame(180 * MS, export=2, plane=6)
        s = r.finish()
        self.assertEqual([f["identity"] for f in s.frames], [0xAAA, 0xAAA, 0xBBB, 0xBBB])
        self.assertEqual([("parts" in f) for f in s.frames], [False, True, False, True])  # a new plane has a first frame too

    def test_another_client_s_buffer_of_the_same_number_is_another(self):
        r = Recording()
        r.export(MS, 0xAAA, export=1, buffer=1, client=1)
        r.export(2 * MS, 0xBBB, pointer=0x2000, export=2, buffer=1, client=2)
        for i in range(4):
            r.frame((100 + 40 * i) * MS, export=1, plane=5)
            r.frame((120 + 40 * i) * MS, export=2, plane=6, window=2)
        s = r.finish()
        self.assertEqual(sum("parts" in f for f in s.frames), 6)
        for f in s.frames:
            self.assertEqual(f["plane"], 5 if f["identity"] == 0xAAA else 6)

    def test_two_frames_of_one_image_before_its_presentation_are_not_told_apart(self):
        r = steady(3)
        r.frame(200 * MS, leave=("RX",))
        r.frame(220 * MS)
        s = r.finish()
        self.assertEqual(sum("ambiguous: presented with another frame of its image" in f["why"] for f in s.frames), 2)
        self.assertEqual(s.unseen["presentations after several frames of their image"], 1)

    def test_a_presentation_without_its_frame_takes_no_older_one(self):
        r = steady(3)
        r.frame(200 * MS, leave=("SIGNAL", "FRAME", "COUNTS"))
        s = r.finish()
        self.assertEqual(s.unseen["presentations without a recorded frame"], 1)
        self.assertEqual(len(s.frames), 3)

    def test_a_presentation_of_a_detached_buffer_joins_nothing(self):
        r = steady(3)
        r.put("wsd", 180 * MS, "W_DETACH", 1, 1)
        r.frame(200 * MS)
        s = r.finish()
        self.assertEqual(s.unseen["presentations of a buffer whose attachment is not recorded"], 1)
        self.assertIn("missing: presentation", s.frames[-1]["why"])

    def test_two_exported_copies_before_one_signal_are_not_told_apart(self):
        s = steady(3, copies=2).finish()
        self.assertEqual(sum("parts" in f for f in s.frames), 0)
        self.assertTrue(all("more than one exported copy" in f["why"][0] for f in s.frames))

    def test_the_wait_begins_at_the_presentation_before_of_the_same_plane(self):
        r = Recording()
        r.export(MS, 0xAAA, export=1, buffer=1)
        r.export(2 * MS, 0xBBB, pointer=0x2000, export=2, buffer=2)
        r.frame(100 * MS, export=1, plane=5)
        r.frame(115 * MS, export=2, plane=6, window=2)
        r.frame(120 * MS, export=1, plane=5)
        s = r.finish()
        f = s.frames[-1]
        self.assertEqual(f["before"], r.ends[1])
        self.assertEqual(f["start"], max(f["submit"], r.ends[1]))

    def test_frames_made_while_records_were_lost_are_not_whole(self):
        r = steady(6)
        r.put("dxmt", 999 * MS, "LOST", 0, 139 * MS, 141 * MS, 7, 7, thr=0xffff)
        s = r.finish()
        self.assertEqual([("parts" in f) for f in s.frames], [False, True, False, True, True, True])
        self.assertIn("records lost while it was made", s.frames[2]["why"][0])

    def test_a_recorder_that_ended_before_is_said(self):
        r = steady(6)
        r.put("wsd", 181 * MS, "END", 1, 10, 3, 0, 0, 0, thr=0xffff)
        s = r.finish()
        self.assertIn("its recorder ended (budget)", s.frames[-1]["why"][0])
        self.assertIn("ended: budget", next(f for f in s.files if f.role == "wsd").says())

    def test_the_chunks_of_the_first_frame_are_not_guessed(self):
        s = steady(3, chunks=3).finish()
        self.assertNotIn("chunks", s.frames[0])
        self.assertEqual(s.frames[1]["chunks"], [104, 105, 106])
        self.assertNotIn("encode_frame", s.frames[0])


class Idle(unittest.TestCase):
    def said(self, s):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            otl.report(s, s.frames, "all")
        return out.getvalue()

    def test_idle_is_the_gap_of_every_queue_together(self):
        r = steady(4)
        for i in range(4):  # another queue works in the gap between the frames
            r.put("dxmt", (109 + 20 * i) * MS + 5 * MS, "D_DONE", 4, 900 + i, (113 + 20 * i) * MS, (117 + 20 * i) * MS, 0, 0, 2)
        s = r.finish()
        text = self.said(s)
        self.assertIn("GPU idle of this session", text)
        self.assertNotIn("not covered by this queue", text)
        f = s.frames[-1]
        # 20 ms: 7.6 of the frame, 4 of the other queue, 0.5 of wsd's
        self.assertEqual(f["interval"] - f["gpu_busy"], 20 * MS - 7_600_000 - 4 * MS - 500_000)

    def test_idle_is_not_claimed_when_a_queue_is_not_known(self):
        for spoil, why in (
                (lambda r: r.put("dxmt", 900 * MS, "LOST", 0, 120 * MS, 121 * MS, 1, 1, thr=0xffff), "records lost"),
                (lambda r: r.put("dxmt", 150 * MS, "D_ENCODE", 0, 4000, 150 * MS, 150 * MS, 150 * MS, 0, 3), "never seen done"),
                (lambda r: r.put("npt", 150 * MS, "N_FLUSH", 0, 1, pid=77), "those of worker 77 are not recorded"),
                (lambda r: r.put("wsd", 150 * MS, "END", 3, 1, 0, 0, 0, 0, thr=0xffff), "its recorder ended (space)")):
            r = steady(4)
            spoil(r)
            text = self.said(r.finish())
            self.assertNotIn("GPU idle of this session", text)
            if "whole: " in text and "FENCE WAIT" in text:
                self.assertIn("not covered by this queue", text)
                self.assertIn(why, text)

    def test_idle_is_not_claimed_without_wsd(self):
        s = steady(4).finish(only=("npt", "dxmt", "vtest"))
        self.assertIsNotNone(s.not_all_gpu(0, 2**62))


class Bounds(unittest.TestCase):
    def main(self, *args):
        out, old = io.StringIO(), sys.argv
        sys.argv = ["otl.py", *args]
        try:
            with contextlib.redirect_stdout(out):
                otl.main()
        finally:
            sys.argv = old
        return out.getvalue()

    def test_lost_records_and_unjoined_frames_come_first(self):
        r = steady(6)
        r.put("dxmt", 999 * MS, "LOST", 0, 139 * MS, 141 * MS, 7, 7, thr=0xffff)
        r.finish()
        text = self.main(r.dir)
        self.assertTrue(text.startswith("LOST records: dxmt 7, npt 0, vtest 0, wsd 0"), text[:200])

    def test_the_csv_and_the_cadence_are_cut_to_the_time_and_the_plane_asked_for(self):
        r = Recording()
        r.export(MS, 0xAAA, export=1, buffer=1)
        r.export(2 * MS, 0xBBB, pointer=0x2000, export=2, buffer=2)
        for i in range(30):
            r.frame((100 + 20 * i) * MS, export=1, plane=5)
            r.frame((107 + 20 * i) * MS, export=2, plane=6, window=2)
        r.finish()
        out = os.path.join(r.dir, "out.csv")
        self.main(r.dir, "--from", str(200 * MS), "--to", str(400 * MS), "--plane", "5", "--csv", out, "--cadence")
        with open(out) as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 11)
        self.assertEqual({row["plane"] for row in rows}, {"5"})
        # frames just inside keep what came just before: the cut takes nothing from them
        self.assertTrue(all(row["whole"] == "1" for row in rows), [row["why"] for row in rows])
        told = os.path.join(r.dir, "out.json")
        self.main(r.dir, "--from", str(200 * MS), "--to", str(400 * MS), "--cadence", "--json", told)
        with open(told) as f:
            planes = json.load(f)["reports"][0]["cadence"]
        self.assertEqual([p["plane"] for p in planes], [5, 6])
        self.assertAlmostEqual(planes[0]["shown_per_s"], 50.0)   # between the first and the last: not one frame too many
        self.assertAlmostEqual(planes[0]["refresh_ms"], 16.667, 2)
        self.assertEqual(planes[0]["shown"], planes[0]["received"])

    def test_a_zero_time_callback_and_a_redisplay_are_no_shown_frame(self):
        r = steady(4)
        r.put("wsd", 300 * MS, "W_SHOWN", 1, 77, 0, 1, 5)
        r.put("wsd", 301 * MS, "W_SHOWN", 1 | 1 << 31, 4, 300 * MS, 1, 5)
        s = r.finish()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            planes = otl.cadence(s, 0, 2**62)
        self.assertEqual((planes[0]["shown"], planes[0]["zero_time"], planes[0]["redisplays_shown"]), (4, 1, 1))

    def read(self, r, lo, hi, *more):
        told = os.path.join(r.dir, "out.json")
        text = self.main(r.dir, "--from", str(lo), "--to", str(hi), "--cadence", "--json", told, *more)
        with open(told) as f:
            return json.load(f)["reports"][0], text

    def presented(self, r, serial, at, plane=5, callback=None, sent=None, a=1):
        sent = sent if sent is not None else at - 20 * MS
        r.put("wsd", sent, "W_RX", 1, 1, serial, sent, sent, 0, 1 << 32 | plane)
        r.put("wsd", callback if callback is not None else at + MS, "W_SHOWN", a, serial, at, 1, plane)

    def test_a_window_s_rate_is_over_all_of_it(self):
        # the review's case: 60 s, 2300 frames 25 ms apart, then nothing for 2.525 s. 40.00 was told, 38.33 are.
        r = Recording()
        base = 1000 * MS
        for i in range(2300):
            self.presented(r, i + 1, base + i * 25 * MS)
        r.finish()
        one, text = self.read(r, base, base + 60_000 * MS, "--plane", "5")
        c = one["cadence"][0]
        self.assertEqual((c["shown"], round(c["shown_per_s"], 2), round(c["shown_per_s_from_the_first_to_the_last"], 2)), (2300, 38.33, 40.0))
        self.assertEqual((c["leading_gap_ms"], c["trailing_gap_ms"], c["largest_gap_ms"], c["holds_of_3_refreshes_or_more"]), (0, 2525, 2525, 1))
        self.assertIn("SHOWN 2300 (38.33/s over 60.000 s)", text)

    def test_a_frame_is_of_the_window_it_was_presented_in_whenever_its_callback_ran(self):
        r = Recording()
        cut = 2000 * MS
        self.presented(r, 1, cut - 10 * MS, callback=cut + 200 * MS)  # told late: of the window before
        self.presented(r, 2, cut)                                      # at the cut itself: of the one after
        self.presented(r, 3, cut + 1000 * MS - 1, callback=cut + 2500 * MS)
        self.presented(r, 4, cut + 1000 * MS)
        r.put("wsd", cut + 500 * MS, "W_SHOWN", 1, 1, cut + 500 * MS, 1, 5)            # (told again: it was new once)
        r.put("wsd", cut + 510 * MS, "W_SHOWN", 1 | 1 << 31, 2, cut + 510 * MS, 1, 5)  # a redisplay
        r.put("wsd", cut + 520 * MS, "W_SHOWN", 1, 9, 0, 1, 5)
        r.finish()
        before, at, after = (self.read(r, cut + k * 1000 * MS, cut + (k + 1) * 1000 * MS, "--plane", "5")[0]["cadence"][0] for k in (-1, 0, 1))
        self.assertEqual([c["shown"] for c in (before, at, after)], [1, 2, 1], "each once, none in two windows")
        self.assertEqual((at["zero_time"], at["redisplays_shown"]), (1, 1))
        self.assertEqual([round(c["shown_per_s"], 3) for c in (before, at, after)], [1.0, 2.0, 1.0])

    def test_a_callback_that_ran_long_after_is_of_its_frame_s_window(self):
        # the review's case: two presented in the window, the second one's callback 3.1 s beyond it. One was counted.
        base = 1_000_000_000
        r = Recording()
        self.presented(r, 1, base + 100 * MS)
        self.presented(r, 2, base + 900 * MS, callback=base + 4100 * MS)
        self.presented(r, 3, base + 950 * MS, callback=base + 60_000 * MS)
        self.presented(r, 4, base + 5000 * MS, callback=base + 5000 * MS)  # (presented after it)
        r.finish()
        c = self.read(r, base, base + 1000 * MS, "--plane", "5")[0]["cadence"][0]
        self.assertEqual((c["shown"], c["shown_per_s"], c["received"], c["trailing_gap_ms"]), (3, 3.0, 3, 50))
        self.assertEqual(c["client_to_shown_ms"]["p50"], 20)

    def test_a_frame_received_long_before_it_was_shown_keeps_its_stamp(self):
        base = 10_000 * MS
        r = Recording()
        self.presented(r, 1, base + 100 * MS, sent=base - 5000 * MS)
        self.presented(r, 9, base - 4000 * MS, sent=base - 4900 * MS)  # (shown before it: of another window)
        r.put("wsd", base + 200 * MS, "W_SHOWN", 1, 9, base + 200 * MS, 1, 5)  # and again: it was new once
        r.finish()
        for more in (("--plane", "5"), ()):
            c, = self.read(r, base, base + 1000 * MS, *more)[0]["cadence"]
            self.assertEqual((c["plane"], c["shown"], c["received"], c["client_to_shown_ms"]["p50"]), (5, 1, 0, 5100))

    def test_a_window_of_no_frame_or_of_one_has_its_rate_and_its_gaps(self):
        r = Recording()
        self.presented(r, 1, 1500 * MS)
        self.presented(r, 2, 9000 * MS)
        r.finish()
        one = self.read(r, 1000 * MS, 2000 * MS, "--plane", "5")[0]["cadence"][0]
        self.assertEqual((one["shown"], one["shown_per_s"], one["largest_gap_ms"], one["shown_interval_ms"]["p50"], one["holds_of_3_refreshes_or_more"]),
                         (1, 1.0, 500, None, 2))
        none = self.read(r, 3000 * MS, 5000 * MS, "--plane", "5")[0]["cadence"]
        # (nothing of this plane is loaded with the window at all, or it is told with nothing shown)
        self.assertTrue(not none or (none[0]["shown"], none[0]["shown_per_s"], none[0]["largest_gap_ms"]) == (0, 0.0, 2000), none)
        near = self.read(r, 2000 * MS, 4000 * MS, "--plane", "5")[0]["cadence"][0]
        self.assertEqual((near["shown"], near["shown_per_s"], near["largest_gap_ms"], near["holds_of_3_refreshes_or_more"]), (0, 0.0, 2000, 1))

    def test_what_is_told_of_a_plane_is_its_own(self):
        r = Recording()
        r.export(MS, 0xAAA, export=1, buffer=1)
        r.export(2 * MS, 0xBBB, pointer=0x2000, export=2, buffer=2)
        for i in range(40):  # the game's: on its queue 1; another window's, half as many, on queue 2
            r.frame((1000 + 20 * i) * MS, export=1, plane=5)
            if i % 2:
                r.frame((1007 + 20 * i) * MS, export=2, plane=6, window=2, queue=2, chunks=3)
        for queue, events in ((1, 3), (2, 50)):
            r.put("dxmt", 1300 * MS, "D_QUERIES", 1 | 2, queue, 1, events, 0, 0, 0)
            r.put("dxmt", 1300 * MS, "D_STALL", 2 | 8, queue, 7, 50, 49, 51, 1)
        r.finish()
        one, text = self.read(r, 1200 * MS, 1600 * MS, "--plane", "game", "--splits")
        self.assertEqual((one["plane"], round(one["plane_share"], 2), one["queues"]), (5, round(21 / 31, 2), [[10, 1]]))
        self.assertEqual([c["plane"] for c in one["cadence"]], [5])
        self.assertEqual((one["production"]["frames"], one["production"]["per_s"], one["production"]["interval_ms"]["mean"]), (20, 50.0, 20.0))
        self.assertEqual((one["work"]["frames"], one["work"]["draws"]), (21, 10))
        self.assertEqual((one["queries"]["ended"]["event"], one["queries_of_every_queue"]["ended"]["event"]), (3, 53))
        self.assertEqual((one["queries"]["stall_flushes"], one["queries_of_every_queue"]["stall_flushes"]), (1, 2))
        self.assertEqual(one["whole_share"], 1.0)
        self.assertEqual(one["trace_not_complete"], [])

    def test_a_frame_of_the_game_s_queue_that_is_not_told_is_one_of_its_frames(self):
        r = steady(10)
        r.frame(400 * MS, leave=("RX",))
        r.finish()
        one, _ = self.read(r, 90 * MS, 500 * MS, "--plane", "5")
        self.assertEqual((one["frames"], one["whole"]), (11, 9), "the one that was not presented, and the first of its plane")
        self.assertLess(one["whole_share"], 0.95)

    def test_a_frame_that_lost_what_it_belongs_to_is_still_one(self):
        # the review's fixture: 50 of 96 frames without DXMT's signal and without a receive. 46 were told, 97.83 % of them whole.
        r = Recording()
        r.export(MS, 0xAAA)
        for i in range(120):
            r.frame((1000 + i * 20) * MS, leave=("DSIGNAL", "RX") if 30 <= i < 80 else ())
        r.finish()
        for plane in ("game", "5"):
            one, _ = self.read(r, 1300 * MS, 3200 * MS, "--plane", plane)
            self.assertEqual((one["frames"], one["whole"], round(one["whole_share"], 4)), (96, 45, round(45 / 96, 4)))
        self.assertLess(self.read(r, 1300 * MS, 3200 * MS, "--plane", "game")[0]["plane_share"], 0.5)

    def test_what_is_known_to_be_another_plane_s_is_not_counted(self):
        r = Recording()
        r.export(MS, 0xAAA, export=1, buffer=1)
        r.export(2 * MS, 0xBBB, pointer=0x2000, export=2, buffer=2)
        for i in range(40):
            r.frame((1000 + 20 * i) * MS, export=1, plane=5)
            r.frame((1007 + 20 * i) * MS, export=2, plane=6, window=2, queue=2, leave=("DSIGNAL", "RX") if i % 4 == 0 else ())
        r.finish()
        one, _ = self.read(r, 1200 * MS, 1600 * MS, "--plane", "5")
        self.assertEqual((one["frames"], one["whole_share"]), (21, 1.0), "that image was only ever presented on the other")
        self.assertLess(self.read(r, 1200 * MS, 1600 * MS, "--plane", "6")[0]["whole_share"], 0.95)

    def test_a_presentation_without_a_frame_is_one_that_is_not_whole(self):
        r = steady(20)
        for i in range(5):
            r.frame((600 + 20 * i) * MS, leave=("SIGNAL", "FRAME", "COUNTS"))
        r.finish()
        one, text = self.read(r, 110 * MS, 900 * MS, "--plane", "5")
        self.assertEqual((one["frames"], one["whole"], one["received_without_a_frame"], one["whole_share"]), (19, 19, 5, 19 / 24))
        self.assertIn("5  presentations without a recorded frame", text)

    def test_a_window_that_is_not_recorded_whole_says_so(self):
        told = lambda r, lo=150 * MS, hi=250 * MS: self.read(r, lo, hi, "--plane", "5")[0]["trace_not_complete"]
        r = steady(20)
        r.finish()
        self.assertEqual(told(r), [])
        r.put("dxmt", 999 * MS, "LOST", 0, 160 * MS, 170 * MS, 7, 7, thr=0xffff)
        r.finish()
        self.assertEqual(told(r), ["dxmt 10: records lost"])
        r = steady(20)
        r.put("wsd", 200 * MS, "END", 1, 1, 0, 0, 0, 0)
        r.finish()
        self.assertEqual(told(r), ["wsd 8: its recorder ended (budget)"], "its last record may be later")
        r = steady(20)
        r.records[("vtest", 9)].clear()
        r.finish(only=("npt", "dxmt", "wsd"))
        self.assertEqual(told(r), ["vtest: not recorded"])

    def test_a_file_cut_in_a_record_is_read_to_its_last_whole_one(self):
        r = steady(3)
        r.finish()
        p = f"{r.dir}/otl-wsd-8.bin"
        size = os.path.getsize(p)
        os.truncate(p, size - 100)
        f = otl.File(p)
        self.assertEqual((f.cut, f.end), (28, None))
        self.assertIn("no end record", f.says())


class Splits(unittest.TestCase):
    """What committed a frame's command buffers and cut its main colour target."""

    def recording(self):
        r = Recording(passes=1)
        r.export(MS, 0xAAA)
        for i in range(3):
            t = (100 + 20 * i) * MS
            r.frame(t, chunks=3)
            last = 100 + r.n * 3
            for c, why, asked, opened in ((last - 2, 17, 0, 1), (last - 1, 6, 15, 0), (last, 19, 0, 0)):
                r.put("dxmt", t - MS, "D_COMMIT", why | asked << 8 | opened << 16, 1, c, r.n, t - 2 * MS if asked else 0, 1000, 0)
            # the main target (texture 7): two encoders in the first command buffer, one in each other; another one's between
            def encoder(chunk, index, texture, ops, stop, width=1323):
                key, at = 1 << 48 | chunk, t - MS + chunk * 1000 + index
                r.put("dxmt", at, "D_PASS", index | 1 << 16, key, width << 32 | 860, otl_attachment(115, 2, width, 860))
                r.put("dxmt", at + 1, "D_PASS_ID", index | 1 << 16, key, texture, 0, stop)
                r.put("dxmt", at + 2, "D_OPS", index, key, ops, 0, ops * 10)
            encoder(last - 2, 1, 7, 50, 3)       # a blit needs it
            encoder(last - 2, 2, 9, 5, 0, 512)
            encoder(last - 2, 3, 7, 40, 0)
            encoder(last - 1, 1, 7, 30, 0)
            encoder(last, 1, 7, 20, 0)
        return r

    def test_each_cut_is_told_by_what_made_it(self):
        s = self.recording().finish()
        with contextlib.redirect_stdout(io.StringIO()) as out:
            told = otl.splits(s, s.frames)
        self.assertEqual((told["recorded_frames"], told["encoders"], told["cuts"]), (2, 4.0, 3.0), "the first frame's command buffers are not known")
        self.assertEqual(told["cut_by"], {
            "encoder: a blit that needs it": 1.0,
            "command buffer: GetData(DONOTFLUSH) of an event query not there 64 times before": 1.0,
            "command buffer: End of an occlusion query, committed at ClearUnorderedAccessView": 1.0})
        self.assertEqual((told["command_buffers"], told["open_pass"]), (3.0, 1.0))
        self.assertIn("RGBA16F 1323x860 2x", out.getvalue())

    def test_a_recording_of_before_says_nothing(self):
        s = steady().finish()
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(otl.splits(s, s.frames)["frames_with_commits"], 0)
        self.assertEqual(out.getvalue(), "")


def otl_attachment(fmt, samples, w, h):
    return fmt | samples << 16 | 1 << 24 | 1 << 28 | w << 34 | h << 49


class Passes(unittest.TestCase):
    def recording(self, every=2):
        r = Recording(passes=every)
        r.export(MS, 0xAAA)
        for i in range(8):
            t = (100 + 20 * i) * MS
            r.frame(t)
            n = r.n
            if n % every == 0:
                key = 1 << 48 | 100 + n
                r.put("dxmt", t + 200_000, "D_PASS", 1 | 1 << 16, key, 2940 << 32 | 1912, 0x1010046)
                r.put("dxmt", t + 210_000, "D_OPS", 1, key, 10 + i, 0, 100)
                r.put("dxmt", t + 220_000, "D_BLIT", 2, key)
                r.put("dxmt", t + 230_000, "D_OPS", 2 | 2 << 16, key, 1, 1000, 1)
                gpu = lambda x: x * 2 + 14
                self.clock_rate = 2
                r.put("dxmt", t + 9 * MS, "D_PASS_TIME", 1, key, gpu(t + MS), gpu(t + 2 * MS), gpu(t + MS), gpu(t + 4 * MS))
                # a blit's third and fourth samples are nothing, whatever they hold
                r.put("dxmt", t + 9 * MS, "D_PASS_TIME", 2 | 2 << 16, key, gpu(t + 4 * MS), gpu(t + 5 * MS), 5, 6)
        return r

    def test_the_times_are_in_the_gpu_s_clock_and_only_what_was_written(self):
        r = self.recording()
        # its clock counts half nanoseconds here: two clocks apart tell it
        for k, l in r.records.items():
            for i, rec in enumerate(l):
                if rec[1] == otl.K["D_CLOCK"]:
                    l[i] = rec[:4] + (rec[0], rec[0] * 2 + 14, rec[0], rec[0] + 100, 1, 0)
        s = r.finish()
        f = next(f for f in s.frames if f.get("group") == 4)
        render, blit = s.passes(f)
        self.assertEqual([(n, round((b - a) / MS, 3)) for n, a, b in render["times"]], [("vertex", 1.0), ("fragment", 3.0)])
        self.assertEqual([(n, round((b - a) / MS, 3)) for n, a, b in blit["times"]], [("blit", 1.0)])

    def test_the_frames_between_are_not_said_to_have_no_encoders(self):
        s = self.recording().finish()
        self.assertIsNone(s.passes(next(f for f in s.frames if f.get("group") == 3)))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            otl.passes_report(s, s.frames)
        self.assertIn("every Nth frame, N = 2", out.getvalue())
        self.assertIn("of 4 recorded", out.getvalue())

    def test_times_outside_their_command_buffer_are_refused(self):
        r = self.recording()
        key = 1 << 48 | 100 + 4
        r.records[("dxmt", 10)] = [x for x in r.records[("dxmt", 10)] if not (x[1] == otl.K["D_PASS_TIME"] and x[4] == key)]
        r.put("dxmt", 300 * MS, "D_PASS_TIME", 1, key, (50 * MS) * 2 + 14, (51 * MS) * 2 + 14, 0, 0)
        s = r.finish()
        e = s.passes(next(f for f in s.frames if f.get("group") == 4))[0]
        self.assertEqual((e["times"], e["times_why"]), (None, "outside its command buffer's GPU time"))

    def test_another_queue_s_chunk_of_the_same_number_is_another(self):
        r = self.recording()
        r.put("dxmt", 160 * MS, "D_COMPUTE", 3, 2 << 48 | 104)
        s = r.finish()
        self.assertEqual(len(s.passes(next(f for f in s.frames if f.get("group") == 4))), 2)

    def test_without_two_clocks_there_are_no_times(self):
        r = self.recording()
        r.records[("dxmt", 10)] = [x for x in r.records[("dxmt", 10)] if x[1] != otl.K["D_CLOCK"]]
        s = r.finish()
        e = s.passes(next(f for f in s.frames if f.get("group") == 4))[0]
        self.assertEqual(e["times_why"], "fewer than two clocks of both")


class Queries(unittest.TestCase):
    def test_the_flushes_of_stalled_looks_are_told_by_whether_anything_was_owed(self):
        r = Recording()
        # two with the marker not handed over, of one chunk; one of another that was left; two with it handed over, one of them a commit
        for t, a, chunk in ((10, 2, 7), (11, 2, 7), (12, 4, 8), (13, 1 | 2, 9), (14, 1, 9), (900, 2, 70)):
            r.put("dxmt", t * MS, "D_STALL", a | 8, 1, chunk, 50, 40, 51, 1)
        r.put("dxmt", 15 * MS, "D_COMMIT", 17, 1, 9, 1, 0, 0, 0)
        for t in (16, 17):
            r.put("dxmt", t * MS, "D_QUERIES", 1 | 2, 1, t, 3 | 1 << 16 | 4 << 32 | 2 << 48, 1 | 5 << 32, 64 | 30 << 32, 29 | 2 << 32)
        s = r.finish()
        with contextlib.redirect_stdout(io.StringIO()):
            told = otl.queries(s, 5 * MS, 500 * MS)
        self.assertEqual([told[k] for k in ("stall_flushes", "not_handed_over", "handed_over", "handed_over_and_committed", "left_not_handed_over",
                                            "most_rescues_of_a_chunk", "signals")], [5, 3, 2, 1, 1, 2, 2])
        self.assertEqual((told["once"], told["locked"], told["ended"]), ([True], [True], dict(event=6, disjoint=2, timestamp=8, occlusion=4)))
        self.assertEqual(told["commits"], {otl.WHY[17]: 1})
        self.assertEqual(told["looks"]["rescues left to the next look"], 10)
        self.assertEqual(told["looks"]["of those, nothing to rescue and nothing done"], 58)

    def told(self, r, lo=5, hi=900):
        out = io.StringIO()
        s = r.finish()
        with contextlib.redirect_stdout(out):
            told = otl.queries(s, lo * MS, hi * MS)
        return told, out.getvalue()

    def test_the_counts_of_a_window_are_what_its_records_say(self):
        r = Recording()
        for t, at_a_look in ((10, 0), (20, 4), (1200, 0)):
            r.put("dxmt", t * MS, "D_QUERIES", 1 | 2 | at_a_look, 1, t, 3, 0, 64, 0)
            r.put("dxmt", t * MS + 1, "D_LOOKS", 1 | 2 | at_a_look, 1, t, 100 | 90 << 32, 10 | 2 << 32, 3 | 4 << 16 | 5 << 32 | 1 << 48, (7 + t) * 1000 | 9000 << 32)
        told, text = self.told(r)
        self.assertEqual(told["window"], dict(looks=200, s_false=180, s_ok=20, rescues=4, not_made_for_the_lock=6, not_made_for_a_full_queue=8,
                                              uploads_left_to_the_rescue_thread=10, rescues_by_the_rescue_thread=2))
        self.assertEqual((told["longest"], told["signals"]), (dict(look_ns=27000, rescue_ns=9000), 1))
        self.assertIn("200 looks at event and disjoint queries, 180 answered S_FALSE, 20 S_OK; 4 rescues (2 by the rescue thread)", text)
        self.assertEqual([w["looks"] for w in self.told(r, 5, 2000)[0]["per_second"]], [200, 100])

    def query(self, r, t, query, end, event, chunk, a=0, queue=1):
        r.put("dxmt", t * MS, "D_QUERY", a, queue, query << 32 | end, event, chunk, 1)

    def seen(self, r, t, query, end, first, last, looks, event, a=0, queue=1):
        r.put("dxmt", t * MS, "D_QUERY_SEEN", a, queue, query << 32 | end, first * MS, last * MS, looks, event)

    def test_a_commit_is_judged_by_its_watermarks_not_by_what_it_says(self):
        r = Recording()
        for t, a, chunk, event, before, after in ((10, 2, 7, 50, 49, 51),    # a rescue
                                                  (20, 2, 8, 51, 51, 52),    # says nothing of it, and its marker had been handed over
                                                  (30, 2, 9, 60, 52, 53)):   # and one that left its marker where it was
            r.put("dxmt", t * MS, "D_STALL", a | 8, 1, chunk, event, before, after, 1)
            r.put("dxmt", t * MS, "D_READY", 0, 1, chunk, 0, 1)
            r.put("dxmt", t * MS, "D_COMMIT", 17, 1, chunk, 1, 0, 0, 0)
        told, text = self.told(r)
        self.assertEqual([told[k] for k in ("handed_over_and_committed", "left_not_handed_over", "said_otherwise_than_its_watermarks", "most_rescues_of_a_chunk")], [1, 1, 2, 1])
        self.assertIn("NOT AS IT IS MEANT TO BE: 2 said otherwise", text)

    def test_a_rescue_is_of_the_chunk_its_marker_is_in_and_that_chunk_was_handed_over(self):
        r = Recording()
        for t, chunk, event, ready, why in ((10, 7, 50, True, 17), (20, 8, 60, False, 17), (30, 9, 70, True, 19), (40, 10, 80, True, 17)):
            r.put("dxmt", t * MS, "D_STALL", 2 | 8, 1, chunk, event, event - 1, event + 1, 1)
            if ready:
                r.put("dxmt", t * MS, "D_READY", 0, 1, chunk, 0, 1)
            r.put("dxmt", t * MS, "D_COMMIT", why, 1, chunk, 1, 0, 0, 0)
        self.query(r, 5, 7, 1, 50, 7)
        self.query(r, 35, 7, 2, 80, 9)   # its marker is of the chunk before
        told, _ = self.told(r)
        self.assertEqual([told[k] for k in ("rescues_whose_chunk_was_not_handed_over", "rescues_of_a_chunk_something_else_committed",
                                            "rescues_of_another_chunk_than_its_end_s", "handed_over_and_committed")], [1, 1, 1, 0])
        self.assertEqual([told[k] for k in ("rescues", "rescues_whose_commit_is_not_recorded", "rescues_whose_end_is_not_recorded")], [4, 0, 2])

    def test_what_nothing_else_recorded_speaks_for_is_taken_for_neither(self):
        # (the review: a commit and an End that are not recorded were taken for the ones that were expected)
        r = Recording()
        r.put("dxmt", 10 * MS, "D_STALL", 2 | 8, 1, 7, 50, 49, 51, 1)
        r.put("dxmt", 10 * MS, "D_READY", 0, 1, 7, 0, 1)
        told, text = self.told(r)
        self.assertEqual([told[k] for k in ("rescues", "rescues_whose_commit_is_not_recorded", "rescues_whose_end_is_not_recorded",
                                            "rescues_of_a_chunk_something_else_committed", "rescues_of_another_chunk_than_its_end_s")], [1, 1, 1, 0, 0])
        self.assertIn("not corroborated, of 1 rescues: 1 rescues whose commit is not recorded, 1 rescues whose end is not recorded", text)

    def owed(self, r, t, what, event, submitted, why=0, queue=1):
        r.put("dxmt", t * MS, "D_OWED", what | why << 8, queue, event, submitted, t * MS)

    def test_what_is_owed_is_followed_until_it_is_handed_over_or_its_context_ends(self):
        r = Recording()
        self.owed(r, 10, 0, 50, 49, why=2)
        self.owed(r, 20, 0, 52, 49, why=1)
        self.owed(r, 30, 1, 50, 50)          # the first alone
        self.owed(r, 45, 1, 52, 52)
        self.owed(r, 50, 0, 60, 59, why=1)   # with a context that ends
        self.owed(r, 60, 2, 60, 59)
        self.owed(r, 70, 0, 9, 8, why=2, queue=2)
        told, text = self.told(r)
        self.assertEqual(told["debts"], dict(accepted=4, covered=2, cancelled=1, for_the_lock=2, for_a_full_queue=2, longest_ns=25 * MS,
                                             outstanding_at_the_end=1, highest_outstanding=9, oldest_outstanding_ns=830 * MS))
        self.assertIn("4 markers (2 for the device's lock, 2 for a full queue), handed over 2 times", text)
        self.assertEqual(told["left_not_handed_over"], 0)

    def test_a_debt_that_was_dropped_stays_owed_whatever_is_said_of_it(self):
        # (the review's transition: the rescue thread said it was done, its marker was not handed over)
        r = Recording()
        self.owed(r, 10, 0, 50, 49, why=2)
        self.owed(r, 12, 1, 50, 49)
        told, _ = self.told(r)
        self.assertEqual((told["debts"]["outstanding_at_the_end"], told["debts"]["oldest_outstanding_ns"], told["left_not_handed_over"]), (1, 890 * MS, 1))
        # and it is known in a window long after it
        told, _ = self.told(r, 50_000, 60_000)
        self.assertEqual((told["debts"]["outstanding_at_the_end"], told["debts"]["highest_outstanding"]), (1, 50))

    def test_slow_looks_are_counted(self):
        r = Recording()
        for t in (10, 20):
            r.put("dxmt", t * MS, "D_DEBTS", 1 | 2, 1, t, 1 | 1 << 32, 5 | 9 << 32, 50, 400 * (t == 20) | 3 << 32 | 2 << 48)
        told, text = self.told(r)
        self.assertEqual(told["tries"], dict(debts_accepted=2, debts_handed_over=2, tries_of_looks_that_could_not=10,
                                             tries_of_the_rescue_thread_that_could_not=18, looks_of_half_a_ms_or_more=6, looks_of_5_ms_or_more=4))
        self.assertEqual((told["longest"]["oldest_owed_ns"], told["longest"]["highest_owed"]), (400, 50))
        self.assertIn("of 0.5 ms or more: 6, of them of 5 ms or more: 4", text)

    def test_an_end_that_was_looked_at_and_never_found_is_told_from_one_nobody_asked(self):
        r = Recording()
        self.query(r, 10, 7, 1, 50, 5)
        r.put("dxmt", 14 * MS, "D_QUERY_SEEN", 2, 1, 7 << 32 | 1, 11 * MS, 0, 65, 50)
        self.query(r, 10, 8, 1, 51, 5)
        self.query(r, 10, 9, 1, 52, 5)
        self.seen(r, 20, 9, 1, 0, 0, 0, 52, a=1)
        r.put("dxmt", 3000 * MS, "D_READY", 0, 1, 99, 0, 1)
        q = self.told(r, 5, 2900)[0]["one_by_one"]
        self.assertEqual((q["not_seen"], q["not_seen_though_looked_at"], q["not_seen_of_more_than_a_second"], q["ended_again_without_a_look"]),
                         ({"not seen by the end of the recording": 2, "ended again before it was seen": 1}, 1, 2, 1))
        self.assertGreater(q["oldest_not_seen_though_looked_at_ns"], 2000 * MS)

    def test_a_query_is_timed_by_its_own_records_alone(self):
        r = Recording()
        self.query(r, 10, 7, 1, 50, 5)
        self.seen(r, 40, 7, 1, 12, 39, 100, 50)
        self.query(r, 50, 7, 2, 60, 6, a=1)  # the same query again, a disjoint one's; another queue has an End of the same numbers
        self.query(r, 51, 7, 2, 60, 6, queue=2)
        self.seen(r, 70, 7, 2, 55, 0, 1, 60, queue=2)
        for queue, chunk, t in ((1, 5, 20), (1, 6, 60), (2, 6, 52)):
            r.put("dxmt", t * MS, "D_READY", 0, queue, chunk, 0, 1)
            r.put("dxmt", (t + 9) * MS, "D_DONE", 4, chunk, (t + 1) * MS, (t + 8) * MS, 0, 0, queue)
        r.put("dxmt", 20 * MS, "D_STALL", 2 | 8, 1, 5, 50, 49, 51, 1)
        r.put("dxmt", 53 * MS, "D_STALL", 1 | 2, 2, 6, 60, 61, 62, 1)  # (of a chunk whose event was handed over: no rescue)
        q = self.told(r)[0]["one_by_one"]
        self.assertEqual((q["recorded"], q["seen"], q["rescued"], q["not_seen"]), (3, 2, 1, {"not seen by the end of the recording": 1}))
        ns = q["ns"]
        self.assertEqual((ns["issue_to_rescue"]["n"], ns["issue_to_rescue"]["most"], ns["issue_to_hand_over"]["n"]), (1, 10 * MS, 3))
        self.assertEqual((ns["issue_to_first_look"]["most"], ns["issue_to_last_look_without_it"]["n"], ns["issue_to_last_look_without_it"]["most"]),
                         (4 * MS, 1, 29 * MS))
        self.assertEqual((ns["issue_to_seen"]["n"], ns["issue_to_seen"]["most"], ns["issue_to_gpu_end"]["n"]), (2, 30 * MS, 3))
        self.assertEqual((ns["gpu_end_to_seen"]["most"], q["looks"]["most"]), (12 * MS, 100))

    def test_what_was_not_seen_is_not_timed(self):
        r = Recording()
        self.query(r, 10, 7, 1, 50, 5)
        self.seen(r, 30, 7, 1, 12, 29, 9, 50, a=1)  # ended again
        self.query(r, 30, 7, 2, 50, 5, a=2 | 4)     # clean, in a list: its marker is another's
        self.seen(r, 31, 7, 2, 31, 0, 1, 50)
        r.put("dxmt", 20 * MS, "D_READY", 0, 1, 5, 0, 1)
        r.put("dxmt", 25 * MS, "D_DONE", 5, 5, 21 * MS, 22 * MS, 0, 0, 1)  # failed
        q, text = self.told(r)
        q = q["one_by_one"]
        self.assertEqual((q["clean"], q["in_lists"], q["seen"], q["not_seen"]), (1, 1, 1, {"ended again before it was seen": 1}))
        self.assertEqual((q["ns"]["issue_to_hand_over"]["n"], q["ns"]["issue_to_gpu_end"], q["ns"]["issue_to_seen"]["n"]), (1, None, 1))
        self.assertIn("1 with nothing new before them, 1 in command lists; 1 seen, 0 rescued; 1 ended again before it was seen", text)

    def test_two_records_of_one_end_are_not_picked_from(self):
        r = Recording()
        self.query(r, 10, 7, 1, 50, 5)
        self.seen(r, 30, 7, 1, 12, 29, 9, 50)
        self.seen(r, 31, 7, 1, 12, 29, 9, 50)
        q = self.told(r)[0]["one_by_one"]
        self.assertEqual((q["seen"], q["not_seen"]), (0, {"its looks: ambiguous": 1}))

    def test_a_recording_without_these_records_says_nothing_of_them(self):
        r = steady()
        told, text = self.told(r)
        self.assertEqual((told["window"], told["one_by_one"]["recorded"], told["per_second"]), ({}, 0, []))
        self.assertNotIn("one by one", text)


if __name__ == "__main__":
    unittest.main()
