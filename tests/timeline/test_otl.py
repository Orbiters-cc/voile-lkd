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
