#!/usr/bin/env python3
"""wsd's --free-unconfined-pointer and --pointer-socket on the real wsd, with an owned client and no game.

  wsd_pointer.py <wsd> [--released <wsd of before the option>] [--percent 100 45] [--window full win] [--force]

Opens a bundle of its own around wsd and a client that asks for what wineobelisk.drv asks for VRChat (a window over the screen
with the cursor hidden and the mouse captured; the pointer locked on one pixel while playing, the whole window while a menu is
open), moves the real pointer (CGEventPost), and looks at what the client is sent, at macOS's pointer, at the log and at the
channel. With --released it also sends one sequence of requests and test input to both programs without the option and
compares every event and every line of the two logs.
It covers the screen for some 30 s a run: it starts only when nobody used this Mac for a minute (--force: anyway), refuses a
locked screen, and needs the right to post events (Accessibility) of the program it is started from."""
import argparse, ctypes, mmap, os, pathlib, plistlib, queue, random, re, shutil, socket, struct, subprocess, sys, tempfile, threading, time

HERE = pathlib.Path(__file__).resolve().parent
cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")


class Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


cg.CGEventCreate.restype, cg.CGEventCreate.argtypes = ctypes.c_void_p, [ctypes.c_void_p]
cg.CGEventGetLocation.restype, cg.CGEventGetLocation.argtypes = Point, [ctypes.c_void_p]
cg.CGEventCreateMouseEvent.restype = ctypes.c_void_p
cg.CGEventCreateMouseEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, Point, ctypes.c_uint32]
cg.CGEventSetIntegerValueField.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int64]
cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
cg.CGPreflightPostEventAccess.restype = ctypes.c_bool
cg.CGCursorIsVisible.restype = ctypes.c_bool
cg.CGWarpMouseCursorPosition.argtypes = [Point]
cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
cf.CFRelease.argtypes = [ctypes.c_void_p]
MOVED, DOWN, UP, DRAGGED = 5, 1, 2, 6


def where():
    e = cg.CGEventCreate(None)
    p = cg.CGEventGetLocation(e)
    cf.CFRelease(e)
    return p.x, p.y


def post(kind, x, y, dx=0, dy=0):
    e = cg.CGEventCreateMouseEvent(None, kind, Point(x, y), 0)
    cg.CGEventSetIntegerValueField(e, 4, dx)  # kCGMouseEventDeltaX
    cg.CGEventSetIntegerValueField(e, 5, dy)
    cg.CGEventPost(0, e)
    cf.CFRelease(e)


def root():
    return subprocess.run(["/usr/sbin/ioreg", "-n", "Root", "-d1"], capture_output=True, text=True).stdout


def idle():
    out = subprocess.run(["/usr/sbin/ioreg", "-c", "IOHIDSystem"], capture_output=True, text=True).stdout
    return int(re.search(r'"HIDIdleTime" = (\d+)', out)[1]) / 1e9


class Wsd:
    """wsd from a bundle of its own, as launch.sh starts it, and one client."""

    def __init__(self, program, percent, options=(), channel=False):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="wp.", dir=os.environ.get("TMPDIR", "/tmp")))
        app = self.tmp / "PointerCheck.app"
        (app / "Contents/MacOS").mkdir(parents=True)
        shutil.copy2(program, app / "Contents/MacOS/wsd")
        (app / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleName": "PointerCheck", "CFBundleIdentifier": "cc.orbiters.pointer-check",
                                                                  "CFBundleExecutable": "wsd", "CFBundlePackageType": "APPL", "NSHighResolutionCapable": True}))
        self.dir = self.tmp / "s"
        self.dir.mkdir(mode=0o700)
        self.host = self.tmp / "h"
        self.host.mkdir(mode=0o700)
        self.log_path = self.tmp / "log"
        args = ["--dir", str(self.dir)] + (["--render-percent", str(percent)] if percent < 100 else []) + list(options)
        if channel:
            args += ["--pointer-socket", str(self.host / "pointer.sock")]
        subprocess.run(["/usr/bin/open", "-n", "--stderr", str(self.log_path), "--stdout", str(self.log_path), str(app), "--args"] + args, check=True)
        # (Launch Services may take its time: what it starts too late is ended too)
        try:
            self.pid = int(self.logged(r"listening on .*\(pid (\d+)", 40)[1])
        except AssertionError:
            subprocess.run(["/usr/bin/pkill", "-f", str(app / "Contents/MacOS/wsd")])  # its own folder's alone
            shutil.rmtree(self.tmp, ignore_errors=True)
            raise
        self.events, self.lock = [], threading.Condition()
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(str(self.dir / "wsd.sock"))
        self.out = threading.Lock()
        threading.Thread(target=self.read, daemon=True).start()
        self.send(1, struct.pack("<II", 1, os.getpid()))
        h = struct.unpack("<IIIIIIiiIIII", self.wait(101, 5)[2])
        self.width, self.height, self.scale = h[2], h[3], h[5] / 1000
        self.showing = False

    def log(self):
        return self.log_path.read_text(errors="replace") if self.log_path.exists() else ""

    def logged(self, pattern, seconds, start=0):
        until = time.time() + seconds
        while time.time() < until:
            m = re.search(pattern, self.log()[start:])
            if m:
                return m
            time.sleep(0.02)
        raise AssertionError(f"the log has no {pattern!r}:\n" + self.log()[start:][-1500:])

    def mark(self):
        return len(self.log())

    def send(self, kind, payload=b"", fd=None):
        data = struct.pack("<II", kind, len(payload)) + payload
        with self.out:
            if fd is None:
                self.sock.sendall(data)
            else:
                socket.send_fds(self.sock, [data], [fd])

    def read(self):
        buf = b""
        while True:
            try:
                data = self.sock.recv(65536)
            except OSError:
                return
            if not data:
                return
            buf += data
            while len(buf) >= 8:
                kind, n = struct.unpack_from("<II", buf)
                if len(buf) < 8 + n:
                    break
                p, buf = buf[8:8 + n], buf[8 + n:]
                if kind == 111:
                    with self.lock:
                        self.free = True
                with self.lock:
                    self.events.append((time.time(), kind, p))
                    self.lock.notify_all()

    def wait(self, kind, seconds, start=0, where=lambda p: True):
        until = time.time() + seconds
        with self.lock:
            while True:
                for e in self.events[start:]:
                    if e[1] == kind and where(e[2]):
                        return e
                left = until - time.time()
                if left <= 0:
                    raise AssertionError(f"no event {kind} in {seconds} s")
                self.lock.wait(left)

    def since(self, start, *kinds):
        with self.lock:
            return [e for e in self.events[start:] if e[1] in kinds]

    def count(self):
        with self.lock:
            return len(self.events)

    # ---- a window, its frames
    def window(self, full):
        self.full = full
        w, h = (self.width, self.height) if full else (800, 600)
        self.w, self.h = w, h
        self.send(2, struct.pack("<IIII", 1, w, h, 16 if full else 1 | 2 | 8) + b"pointer check")
        if not full:
            self.send(17, struct.pack("<IIiiII", 1, 3, 200, 160, w, h))
        stride = (w * 4 + 255) // 256 * 256
        size = (stride * h + 16383) // 16384 * 16384
        f = tempfile.TemporaryFile()
        f.truncate(size)
        m = mmap.mmap(f.fileno(), size)
        m[:] = b"\x30\x28\x20\xff" * (size // 4)
        self.buffer = f, m
        self.send(9, struct.pack("<IIIIIIQQ", 1, w, h, stride, 1, 0, 0, stride * h), f.fileno())
        if full:
            self.send(5, struct.pack("<II", 1, 1))
        self.send(4, struct.pack("<II", 1, 1))
        self.showing = True
        threading.Thread(target=self.frames, daemon=True).start()
        self.wait(107, 5, where=lambda p: p[4] == 1)
        time.sleep(1.2)
        # the content in display points, from what AppKit made of it
        if not full:
            fr = [e for e in self.since(0, 114)]
            x, y = (struct.unpack("<IIiiII", fr[-1][2])[2:4]) if fr else (200, 160)
            self.x0, self.y0 = x / self.scale, y / self.scale
        else:
            self.x0 = self.y0 = 0.0

    def frames(self):
        serial = 1
        while self.showing is not None:
            if self.showing:
                try:
                    self.send(11, struct.pack("<IIQQ", 1, 1, serial, time.clock_gettime_ns(time.CLOCK_UPTIME_RAW)))
                except OSError:
                    return
                serial += 1
            time.sleep(1 / 30)

    def clip(self, x=None, y=None, w=1, h=1):
        if x is None:
            x, y, w, h = 0, 0, self.w, self.h
        self.send(7, struct.pack("<IIiiII", 1, 1, x, y, w, h))

    def relative(self, on):
        self.send(8, struct.pack("<II", 1, int(on)))

    def visible(self, on):
        self.send(6, struct.pack("<II", 0, int(on)))

    def debug(self, kind, a, b):
        self.send(19, struct.pack("<IIII", kind, a, b, 0))

    def point(self, px, py):
        """The display point of the middle of client pixel px, py."""
        return self.x0 + (px + 0.5) / self.scale, self.y0 + (py + 0.5) / self.scale

    def end(self):
        self.showing = None
        try:
            self.sock.close()
        except OSError:
            pass
        try:
            os.kill(self.pid, 15)
        except ProcessLookupError:
            pass
        for _ in range(60):
            try:
                os.kill(self.pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        cg.CGAssociateMouseAndMouseCursorPosition(1)
        shutil.rmtree(self.tmp, ignore_errors=True)


class Reader:
    """A reader of the pointer channel."""

    def __init__(self, path):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(str(path))
        self.got, self.ended = [], False
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        buf = b""
        while True:
            try:
                data = self.sock.recv(65536)
            except OSError:
                data = b""
            if not data:
                self.ended = True
                return
            buf += data
            while len(buf) >= 8:
                kind, n = struct.unpack_from("<II", buf)
                if len(buf) < 8 + n:
                    break
                self.got.append((kind, buf[8:8 + n]))
                buf = buf[8 + n:]

    def states(self):
        return [struct.unpack("<IIII6diiIIQ", p) for k, p in self.got if k == 2]

    def moves(self):
        return [struct.unpack("<ffQ", p) for k, p in self.got if k == 3]


class Panel:
    def __init__(self, tmp):
        self.program = tmp / "panel"
        subprocess.run(["clang", "-fobjc-arc", "-O1", "-Wno-deprecated-declarations", "-framework", "Cocoa", "-o", str(self.program), str(HERE / "pointer_panel.m")], check=True)
        self.p = subprocess.Popen([str(self.program)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        self.lines = queue.Queue()
        threading.Thread(target=lambda: [self.lines.put(l.strip()) for l in self.p.stdout], daemon=True).start()
        self.hear("ready")

    def say(self, line):
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()

    def hear(self, what, seconds=5):
        until = time.time() + seconds
        while time.time() < until:
            try:
                if self.lines.get(timeout=0.1) == what:
                    return True
            except queue.Empty:
                pass
        return False

    def end(self):
        self.p.kill()
        self.p.wait()


failed, passed = [], 0


def ok(name, good, why=""):
    global passed
    if good:
        passed += 1
    else:
        failed.append(name)
    print(("PASS  " if good else "FAIL  ") + name + (f"  ({why})" if why and (not good or why.startswith("!")) else ""), flush=True)
    return good


def settle(s=0.15):
    time.sleep(s)


def positions(w, start):
    return [struct.unpack("<IIffQ", e[2]) for e in w.since(start, 104)]


def relatives(w, start):
    return [struct.unpack("<IIffQ", e[2]) for e in w.since(start, 105)]


def with_option(a, percent, full):
    tag = f"{'full' if full else 'win'} {percent} %: "
    w = Wsd(a.wsd, percent, ["--free-unconfined-pointer"], channel=True)
    panel = None
    try:
        sock = w.host / "pointer.sock"
        ok(tag + "the channel's socket is the user's alone", (os.lstat(sock).st_mode & 0o777) == 0o600)
        reader = Reader(sock)
        w.window(full)
        panel = Panel(w.tmp)
        cx, cy = w.w // 2, w.h // 2
        # a menu before any lock: the driver's whole-window clip and relative mode
        m = w.mark()
        w.visible(False)
        w.clip()
        w.relative(True)
        w.logged(r"relative mouse on, the pointer stays free", 2, m)
        mid = w.point(cx, cy)
        n = w.count()
        post(MOVED, *mid, 1, 1)
        settle()
        for px, py in ((10, 20), (w.w - 9, w.h - 12), (cx, cy), (w.w // 3, w.h // 4)):
            n = w.count()
            post(MOVED, *w.point(px, py), 5, 5)
            settle()
            got = positions(w, n)
            ok(tag + f"free: the place {px},{py} reaches the client as that pixel", bool(got) and (int(got[-1][2]), int(got[-1][3])) == (px, py), str(got[-2:]))
        ok(tag + "free: no raw delta reaches the client", not relatives(w, 0))
        st = reader.states()[-1]
        ok(tag + "the channel tells free, the window and its scale", st[0] == 1 and abs(st[4] - w.x0) < 1.5 and abs(st[5] - w.y0) < 1.5 and abs(st[8] - w.scale) < 0.01 and st[2] > 0, str(st))
        ok(tag + "the cursor is hidden over the game", not cg.CGCursorIsVisible())

        # the game locks
        m, n = w.mark(), w.count()
        w.clip(cx, cy)
        w.logged(r"pointer held by the game \(it clipped, clip 1x1 at %d,%d\)" % (cx, cy), 2, m)
        settle()
        k = len(reader.moves())
        p0 = where()
        for d in ((3, 0), (0, 4), (-7, 2), (100, -50)):
            post(MOVED, *p0, *d)
            time.sleep(0.02)
        settle()
        got = [(r[2], r[3]) for r in relatives(w, n)]
        ok(tag + "held: the client is sent the deltas, each once", got == [(3, 0), (0, 4), (-7, 2), (100, -50)], str(got))
        ok(tag + "held: no place is sent", not positions(w, n))
        ok(tag + "held: the channel gives the same deltas", [(x[0], x[1]) for x in reader.moves()[k:]] == got)
        ok(tag + "the channel tells held", reader.states()[-1][0] == 2)

        # freed: where the client's cursor is, and no jump
        m, n = w.mark(), w.count()
        w.clip()
        w.logged(r"pointer freed by the game \(it clipped, clip %dx%d at 0,0\), it is at %d,%d" % (w.w, w.h, cx, cy), 2, m)
        settle()
        want = w.point(cx, cy)
        at = where()
        ok(tag + "freed: macOS's pointer is on the client's pixel", abs(at[0] - want[0]) <= 1 and abs(at[1] - want[1]) <= 1, f"{at} for {want}")
        post(MOVED, at[0], at[1], 0, 0)
        settle()
        got = positions(w, n)
        ok(tag + "freed: the first place is the client's own cursor (no jump)", bool(got) and abs(int(got[0][2]) - cx) <= 1 and abs(int(got[0][3]) - cy) <= 1, str(got[:2]))
        ok(tag + "freed: exactly the pixel it was locked on", bool(got) and (int(got[0][2]), int(got[0][3])) == (cx, cy), str(got[:1]))
        ok(tag + "freed: no delta", not relatives(w, n))

        # moves queued before the lock do not turn the camera
        n = w.count()
        for i in range(60):
            post(MOVED, at[0] + i, at[1], 1, 0)
        w.clip(cx, cy)
        settle(0.4)
        got = relatives(w, n)
        ok(tag + "locked while moving: what came before the lock is no delta", sum(abs(r[2]) for r in got) <= 60 and all(abs(r[2]) <= 1 for r in got), f"{len(got)} of 60")
        late = len(got)

        # a button held across both transitions, and a key
        w.clip()
        settle()
        n = w.count()
        x, y = w.point(cx + 30, cy + 20)
        post(MOVED, x, y, 1, 1)
        post(DOWN, x, y)
        settle()
        w.clip(cx, cy)
        settle()
        w.clip()
        settle()
        x2, y2 = where()
        post(UP, x2, y2)
        settle()
        b = [struct.unpack("<IIIIffQ", e[2]) for e in w.since(n, 103)]
        ok(tag + "a button pressed free, held through a lock, released free: one down, one up", [(e[1], e[2]) for e in b] == [(0, 1), (0, 0)], str(b))
        ev = [e[1] for e in w.since(n, 103, 104)]
        ok(tag + "a place comes with each button while free", ev and 103 in ev and all(ev[i - 1] == 104 for i, e in enumerate(ev) if e == 103), str(ev))
        n = w.count()
        w.debug(1, 0, 1)
        w.clip(cx, cy)
        settle()
        w.clip()
        w.debug(1, 0, 0)
        settle()
        kk = [struct.unpack("<IIIIQ", e[2][:24]) for e in w.since(n, 102)]
        ok(tag + "a key held across both transitions: one down, one up", [k[1] & 1 for k in kk if k[2] == 0] == [1, 0], str(kk))

        # rapid toggling with moves in between
        n, m = w.count(), w.mark()
        stop = False

        def shake():
            while not stop:
                x, y = where()
                post(MOVED, x, y, random.choice((-2, -1, 1, 2)), 0)
                time.sleep(0.003)
        t = threading.Thread(target=shake)
        t.start()
        for i in range(150):
            w.clip(cx, cy)
            if i % 3 == 0:
                time.sleep(0.004)
            w.clip()
            if i % 5 == 0:
                time.sleep(0.006)
        w.clip(cx, cy)
        stop = True
        t.join()
        settle(0.5)
        got = relatives(w, n)
        ok(tag + "150 quick toggles: no jump in any delta", all(abs(r[2]) <= 2 and abs(r[3]) <= 2 for r in got), str([r for r in got if abs(r[2]) > 2][:4]))
        ok(tag + "150 quick toggles: no place far from the locked pixel", all(abs(p[2] - cx) < 40 and abs(p[3] - cy) < 40 for p in positions(w, n)), str([p[2:4] for p in positions(w, n) if abs(p[2] - cx) >= 40][:4]))
        lines = w.log()[m:]
        ok(tag + "150 quick toggles: each one logged, the last one held", lines.count("pointer held by the game") == 151 and lines.count("pointer freed by the game") == 150, f"{lines.count('pointer held')} {lines.count('pointer freed')}")
        ok(tag + "150 quick toggles: the channel ends on held", reader.states()[-1][0] == 2)

        # another small clip, moved inside: the place it is freed at follows the client's arithmetic
        w.clip(cx - 20, cy - 20, 41, 41)
        settle()
        p = where()
        post(MOVED, *p, 9, -8)
        post(MOVED, *p, 30, 0)
        settle()
        m = w.mark()
        w.clip()
        w.logged(r"pointer freed by the game .*, it is at %d,%d" % (cx + 20, cy - 8), 2, m)
        ok(tag + "a wider clip: freed where the moves led inside it", True)

        # a panel above the game
        settle()
        bx, by = w.point(cx, cy)
        panel.say(f"panel {bx + 40} {by + 40} 200 150")
        panel.hear("panel")
        settle(0.4)
        ok(tag + "free, over the game: the cursor is hidden", not cg.CGCursorIsVisible())
        post(MOVED, bx + 100, by + 100, 3, 3)
        settle(0.5)
        ok(tag + "free, over a panel above the game: macOS's cursor shows", bool(cg.CGCursorIsVisible()))
        m = w.mark()
        post(DOWN, bx + 100, by + 100)
        post(UP, bx + 100, by + 100)
        ok(tag + "free: the panel gets a click", panel.hear("click"))
        settle(0.3)
        ok(tag + "free: the click takes no focus from the game", "focus lost" not in w.log()[m:] and "given back" not in w.log()[m:])
        # the game locks while the pointer is over the panel: the pointer leaves it
        n, m = w.count(), w.mark()
        w.clip(cx, cy)
        w.logged("pointer held by the game", 2, m)
        settle(0.3)
        p = where()
        ok(tag + "locked with the pointer over the panel: it is over the game again", abs(p[0] - bx) < 2 and abs(p[1] - by) < 2, str(p))
        post(MOVED, *p, 2, 1)
        settle()
        got = [(r[2], r[3]) for r in relatives(w, n)]
        ok(tag + "... and the first delta is small", all(abs(x) <= 2 and abs(y) <= 2 for x, y in got) and len(got) >= 1, str(got))
        panel.say("hide")
        panel.hear("hidden")

        # focus lost while held, and back; then the same while free
        m = w.mark()
        panel.say("active")
        ok(tag + "another app takes the focus", panel.hear("key"))
        w.logged(r"pointer given back \(focus lost\)", 3, m)
        settle(0.4)
        ok(tag + "focus lost while held: the channel tells away", reader.states()[-1][0] == 3, str(reader.states()[-1]))
        ok(tag + "focus lost: the cursor shows", bool(cg.CGCursorIsVisible()))
        w.clip()  # the game frees the pointer behind another app, as the driver does on APP_DEACTIVATED, then locks it again
        w.clip(cx, cy)
        settle()
        ok(tag + "behind another app the game takes nothing", "held by the game" not in w.log()[m:])
        panel.say("hide")
        panel.hear("hidden")
        m = w.mark()
        subprocess.run(["/usr/bin/open", str(w.tmp / "PointerCheck.app")], check=True)
        w.logged(r"pointer held by the game \(focus back", 5, m)
        ok(tag + "focus back: held again", True)
        w.clip()
        settle()
        m = w.mark()
        panel.say("active")
        panel.hear("key")
        settle(0.4)
        panel.say("hide")
        panel.hear("hidden")
        subprocess.run(["/usr/bin/open", str(w.tmp / "PointerCheck.app")], check=True)
        w.wait(107, 5, where=lambda p: p[4] == 1)
        settle(0.6)
        ok(tag + "focus lost and back while free: free all along", "held by the game" not in w.log()[m:])

        # frames stop while held
        w.clip(cx, cy)
        settle()
        m = w.mark()
        w.showing = False
        w.logged(r"pointer given back \(no frame shown\)", 9, m)
        settle(0.3)
        ok(tag + "no frame for 5 s: the pointer and the cursor are given back", bool(cg.CGCursorIsVisible()) and reader.states()[-1][0] == 3)
        w.showing = True
        w.logged(r"pointer held by the game \(frames shown again", 4, m)
        ok(tag + "frames again: held again", True)
        # the same while free: nothing to take
        w.clip()
        settle()
        m = w.mark()
        w.showing = False
        w.logged(r"no frame shown for", 9, m)
        w.showing = True
        w.logged(r"frames shown again", 4, m)
        settle(0.3)
        ok(tag + "no frame for 5 s while free, then frames: still free", "held by the game" not in w.log()[m:])

        # leaving relative mode, as when the game shows its cursor: the driver frees the clip, shows the cursor, warps
        w.clip(cx, cy)
        settle()
        m, n = w.mark(), w.count()
        w.visible(True)
        w.relative(False)
        w.send(29, struct.pack("<ii", round(w.x0 * w.scale) + cx + 25, round(w.y0 * w.scale) + cy + 15))
        settle(0.3)
        at = where()
        want = w.point(cx + 25, cy + 15)
        ok(tag + "the game shows its cursor: free, where the driver put it, and shown", abs(at[0] - want[0]) < 1.6 and abs(at[1] - want[1]) < 1.6 and bool(cg.CGCursorIsVisible()), f"{at} {want}")
        ok(tag + "the channel tells none", reader.states()[-1][0] == 0)

        # a reader that speaks is sent away; the server and the other reader go on
        loud = Reader(sock)
        settle()
        loud.sock.sendall(b"x")
        settle()
        ok(tag + "a reader that sends anything is disconnected, the others stay", loud.ended and not reader.ended)
        quiet = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        quiet.connect(str(sock))
        w.visible(False)
        w.clip(cx, cy)
        w.relative(True)
        settle()
        t0 = time.time()
        for i in range(30000):  # raw moves through the view; the quiet reader reads none of them
            w.debug(3, 10001, 10000)
        w.send(14, struct.pack("<QQ", 77, 0))
        w.wait(112, 30)
        settle(0.3)
        ok(tag + f"30000 moves with a reader that does not read: it is dropped, the game has every move ({time.time() - t0:.1f} s)",
           "does not read, dropping it" in w.log() and len(relatives(w, 0)) >= 30000 and not reader.ended)
        quiet.close()
        # its window goes while held
        m = w.mark()
        w.send(3, struct.pack("<I", 1))
        settle(0.4)
        p = where()
        post(MOVED, p[0] + 30, p[1] + 10, 30, 10)
        settle()
        q = where()
        ok(tag + "the window is gone while held: the pointer moves, the cursor shows", abs(q[0] - p[0] - 30) < 1.5 and bool(cg.CGCursorIsVisible()), f"{p} {q}")
        print(f"      {tag}moves of before the lock that still came as deltas: {late} of 60 (posted after it was read)")
    finally:
        if a.keep_log:
            pathlib.Path(a.keep_log).mkdir(parents=True, exist_ok=True)
            shutil.copy(w.log_path, pathlib.Path(a.keep_log) / f"{'full' if full else 'win'}-{percent}.log")
        if panel:
            panel.end()
        w.end()


def sequence(program, percent, full):
    """One run of requests and test input without the option: the events the client was sent, and the log, without what is
    another at each run (times, process numbers, folders)."""
    w = Wsd(program, percent)
    try:
        w.window(full)
        cx, cy = w.w // 2, w.h // 2
        n, m = w.count(), w.mark()
        steps = [lambda: w.visible(False), lambda: w.clip(), lambda: w.relative(True), lambda: w.debug(3, 10005, 9995), lambda: w.debug(5, 40, 50),
                 lambda: w.clip(cx, cy), lambda: w.debug(3, 10050, 10001), lambda: w.debug(5, 41, 51), lambda: w.debug(2, 60, 70),
                 lambda: w.clip(), lambda: w.debug(3, 9990, 10000), lambda: w.debug(5, 80, 90), lambda: w.debug(2, 61, 71), lambda: w.debug(1, 53, 1),
                 lambda: w.debug(1, 53, 0), lambda: w.relative(True), lambda: w.relative(False), lambda: w.debug(5, 100, 110), lambda: w.debug(3, 10004, 10004),
                 lambda: w.clip(10, 10, 100, 100), lambda: w.debug(5, 300, 300), lambda: w.send(29, struct.pack("<ii", 300, 260)), lambda: w.debug(5, 50, 50),
                 lambda: w.visible(True), lambda: w.clip(cx, cy), lambda: w.relative(True), lambda: w.debug(3, 10007, 10000)]
        for s in steps:
            s()
            time.sleep(0.06)
        w.showing = False
        w.logged("no frame shown for", 9, m)
        w.debug(3, 10007, 10000)
        w.showing = True
        w.logged("frames shown again", 4, m)
        w.debug(3, 10009, 10000)
        time.sleep(0.3)
        ev = []
        for _, kind, p in w.since(n, 102, 103, 104, 105, 106, 107, 108, 113, 114):
            tail = {102: 8, 103: 8, 104: 8, 105: 8}.get(kind, 0)
            at = 16 if kind == 102 else len(p) - tail
            ev.append((kind, p[:at].hex()))
        w.send(3, struct.pack("<I", 1))
        time.sleep(0.4)
        log = w.log()
    finally:
        w.end()
    keep = []
    for line in log.splitlines():
        if "120 frames shown" in line or "frame held" in line or "listening on" in line or "request 11 failed" in line:
            continue
        line = re.sub(r"client (pid )?\d+", "client P", line)
        line = re.sub(r"\d+\.\d s", "T s", line)
        line = re.sub(r"noise [\d.]+|at \d{6,}|probe: .*", "X", line)
        line = re.sub(r"presented(_zero)?=\d+", "presented", line)
        line = re.sub(r"overlay_(presented|zero)=\d+", "overlay", line)
        keep.append(line)
    return ev, [l for l in keep if "shown by macOS" not in l]


def without_option(a, percent, full):
    tag = f"{'full' if full else 'win'} {percent} %, without the option: "
    old, new = sequence(a.released, percent, full), sequence(a.wsd, percent, full)
    ok(tag + f"the client's {len(old[0])} events are the released program's, one for one", old[0] == new[0], str([x for x in zip(old[0], new[0]) if x[0] != x[1]][:3]) + f" {len(old[0])} {len(new[0])}")
    diff = [(x, y) for x, y in zip(old[1], new[1]) if x != y]
    ok(tag + f"the log's {len(old[1])} lines are the released program's", old[1] == new[1], str(diff[:3]) + f" {len(old[1])} {len(new[1])}")
    if a.keep_log:
        pathlib.Path(a.keep_log).mkdir(parents=True, exist_ok=True)
        for name, lines in (("released", old[1]), ("new", new[1])):
            (pathlib.Path(a.keep_log) / f"off-{'full' if full else 'win'}-{percent}.{name}").write_text("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wsd")
    ap.add_argument("--released")
    ap.add_argument("--percent", nargs="*", type=int, default=[100, 45])
    ap.add_argument("--window", nargs="*", default=["full", "win"])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only-off", action="store_true")
    ap.add_argument("--keep-log")
    a = ap.parse_args()
    if re.search(r'"CGSSessionScreenIsLocked"\s*=\s*Yes', root()):
        sys.exit("the screen is locked")
    if not cg.CGPreflightPostEventAccess():
        sys.exit("this program may not post events")
    if not a.force and idle() < 60:
        sys.exit("this Mac is in use")
    awake = subprocess.Popen(["/usr/bin/caffeinate", "-d", "-u", "-t", "600"])
    try:
        for percent in a.percent:
            for kind in a.window:
                try:
                    if not a.only_off:
                        with_option(a, percent, kind == "full")
                except AssertionError as e:
                    ok(f"{kind} {percent} %: ended early", False, str(e))
                if a.released:
                    without_option(a, percent, kind == "full")
    finally:
        awake.kill()
    print(f"{passed} passed, {len(failed)} failed" + "".join("\n  " + f for f in failed))
    sys.exit(bool(failed))


if __name__ == "__main__":
    main()
