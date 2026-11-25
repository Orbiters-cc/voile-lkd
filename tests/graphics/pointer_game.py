#!/usr/bin/env python3
"""pointer_game.exe (pointer_game.c), an owned Windows program that locks and frees the pointer as a Unity game, on an installed
release's engine and Wine driver, with a wsd given here, and the real pointer moved.
  pointer_game.py <wsd> <folder with pointer_game.exe> <a Wine prefix's home, written to> <full|win> <percent> [on|off]
Reads the library's release under its shared lock; leaves nothing behind. As wsd_pointer.py: an idle, unlocked Mac."""
import fcntl, os, pathlib, plistlib, re, shutil, signal, subprocess, sys, tempfile, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wsd_pointer as wp
from wsd_pointer import cg, ok, post, where, MOVED, DOWN, UP, DRAGGED

program, folder, home, kind, percent = sys.argv[1], *(pathlib.Path(p).resolve() for p in sys.argv[2:4]), sys.argv[4], int(sys.argv[5])
on = (sys.argv[6:] or ["on"])[0] == "on"
library = pathlib.Path.home() / "Library/Application Support/cc.orbiters.obelisk-cli"
runtime = library / "Voile/v26.3.0-27.beta1/linux"
F = {1: 122, 2: 120, 3: 99, 4: 118, 5: 96, 6: 97, 8: 100}
tag = f"guest {kind} {percent} % option {'on' if on else 'off'}: "


class Game:
    def __init__(self, tmp, w):
        self.w, self.out = w, tmp / "game.out"
        for d in ("t", "m", "hm"):
            (tmp / d).mkdir()
        env = dict(PATH="/usr/bin:/bin", HOME=str(home), TMPDIR=str(tmp / "hm"), FEXDARWIN_LKD="1", FEXDARWIN_ROOT=str(runtime / "root"), FEXDARWIN_ROOT_RO="1",
                   LKD_HOST_TMP=str(tmp / "t"), LKD_HOST_SHM=str(tmp / "m"), FEXDARWIN_SUPERVISOR_PID=str(os.getpid()),
                   FEXDARWIN_BIND=f"/opt/wine={runtime}/wine:ro;/home/user={home};/w={folder}:ro;/run/obelisk={w.dir}")
        args = [str(runtime / "engine/run-with-timeout.sh"), "120", str(runtime / "engine/fexdarwin-run")]
        for kv in ["HOME=/home/user", "USER=user", "LOGNAME=user", "PATH=/opt/wine/bin:/usr/bin:/bin", "LANG=en_US.UTF-8", "WINEPREFIX=/home/user/prefix",
                   "WINEARCH=win64", "WINEDEBUG=-all", "WINEDLLOVERRIDES=mscoree,mshtml=;winemenubuilder.exe=d"]:
            args += ["--env", kv]
        args += ["/bin/sh", "-c", f"/opt/wine/bin/wineserver -p0; /opt/wine/bin/wine /w/pointer_game.exe {kind}; s=$?; /opt/wine/bin/wineserver -k; exit $s"]
        self.p = subprocess.Popen(args, env=env, stdout=self.out.open("wb"), stderr=subprocess.STDOUT, start_new_session=True)

    def lines(self, start=0):
        return [l.split(None, 2)[2] for l in self.out.read_text(errors="replace")[start:].splitlines() if l.startswith("G ") and len(l.split(None, 2)) > 2]

    def mark(self):
        return len(self.out.read_text(errors="replace"))

    def hear(self, pattern, seconds=5, start=0):
        until = time.time() + seconds
        while time.time() < until:
            for l in self.lines(start):
                m = re.match(pattern, l)
                if m:
                    return m
            time.sleep(0.02)
        raise AssertionError(f"the game did not say {pattern!r}: {self.lines(start)[-6:]}")

    def key(self, n):
        self.w.debug(1, F[n], 1)
        time.sleep(0.05)
        self.w.debug(1, F[n], 0)

    def end(self):
        if self.p.poll() is None:
            os.killpg(self.p.pid, signal.SIGTERM)
        try:
            self.p.wait(8)
        except subprocess.TimeoutExpired:
            os.killpg(self.p.pid, signal.SIGKILL)
            self.p.wait()


def raws(g, m):
    return [tuple(int(x) for x in l.split()[1:3]) for l in g.lines(m) if l.startswith("raw ")]


def main():
    if re.search(r'"CGSSessionScreenIsLocked"\s*=\s*Yes', wp.root()):
        sys.exit("the screen is locked")
    awake = subprocess.Popen(["/usr/bin/caffeinate", "-d", "-u", "-t", "300"])
    with (library / "Voile.locks/library.lock").open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH)
        w = wp.Wsd(program, percent, ["--free-unconfined-pointer"] if on else [])
        w.showing = None
        g = Game(w.tmp, w)
        try:
            r = g.hear(r"ready screen (\d+)x(\d+) client (\d+)x(\d+) at (-?\d+),(-?\d+) mid (\d+),(\d+)", 60)
            sw, sh, cw, ch, ox, oy, mx, my = (int(x) for x in r.groups())
            # the window is key and shows frames
            w.logged(r"shown by macOS", 10)
            time.sleep(2)
            g.hear("active 1", 5)
            s = w.scale
            pt = lambda x, y: ((x + 0.5) / s, (y + 0.5) / s)  # of a pixel of the guest's screen
            # AppKit puts a window on whole points: at a scale that is none, a window's content is up to a point (two pixels) from the pixel the
            # client gave (wsd's released mapping, the same for a visible cursor); a full-screen one is exact.
            px_off = 0 if kind == "full" else 2
            near = lambda a, b, t=1 + px_off / s: abs(a[0] - b[0]) <= t and abs(a[1] - b[1]) <= t
            def at_pixel(line, at):
                c = re.search(r"cursor (-?\d+) (-?\d+)$", line)
                return bool(c) and abs(int(c[1]) - at[0]) <= px_off and abs(int(c[2]) - at[1]) <= px_off
            post(MOVED, *pt(mx, my), 1, 1)
            time.sleep(0.3)
            # 1 a menu before any lock, then a lock
            m, k = g.mark(), w.mark()
            g.key(1)
            g.hear("locked", 3, m)
            time.sleep(0.5)
            if on:
                w.logged("pointer held by the game", 3, k)
            p = where()
            m = g.mark()
            for d in ((4, 0), (0, 5), (-6, -2), (60, -30)):
                post(MOVED, *p, *d)
                time.sleep(0.03)
            time.sleep(0.3)
            ok(tag + "locked: the game's raw input has the deltas, each once", raws(g, m) == [(4, 0), (0, 5), (-6, -2), (60, -30)], str(raws(g, m)))
            # 2 freed (the Quick Menu)
            m, k = g.mark(), w.mark()
            g.key(2)
            free = g.hear(r"freed cursor (\d+),(\d+) clip (-?\d+),(-?\d+) (\d+)x(\d+)", 3, m)
            time.sleep(0.5)
            if not on:
                if kind == "full":
                    ok(tag + "freed: the released behaviour, still relative", "relative mouse off" not in w.log()[k:])
                    m = g.mark()
                    post(MOVED, *where(), 7, 3)
                    time.sleep(0.3)
                    ok(tag + "freed: a move is a raw delta", raws(g, m) == [(7, 3)], str(raws(g, m)))
                return
            w.logged("pointer freed by the game", 3, k)
            ok(tag + "freed: macOS's pointer is where the game's cursor is", near(where(), pt(mx, my)), f"{where()} {pt(mx, my)}")
            ok(tag + "freed: the cursor is hidden over the game", not cg.CGCursorIsVisible())
            m = g.mark()
            x, y = where()
            post(MOVED, x, y, 0, 0)
            time.sleep(0.2)
            post(MOVED, x + 10, y + 6, 10, 6)
            time.sleep(0.3)
            rr = raws(g, m)
            total = (sum(a for a, _ in rr), sum(b for _, b in rr))
            ok(tag + "freed: no camera jump, raw input is the move's own", abs(total[0] - 10 * s) <= 2 + px_off and abs(total[1] - 6 * s) <= 2 + px_off, str(rr))
            for px, py in ((ox + 20, oy + 30), (ox + cw - 30, oy + ch - 25), (mx + 100, my + 60)):
                m = g.mark()
                post(MOVED, *pt(px, py), 3, 3)
                time.sleep(0.3)
                got = [l for l in g.lines(m) if l.startswith("move ")]
                want = f"move {px - ox} {py - oy} cursor {px} {py}"
                # macOS may put a posted place on a whole point: the pixel under it
                ax, ay = where()
                at = (int(ax * s + 1e-6), int(ay * s + 1e-6))
                ok(tag + f"freed: the place {px},{py} is the guest's", bool(got) and at_pixel(got[-1], at) and near(at, (px, py)), f"{got[-1:]} want {want} at {at}")
            # a click there
            m = g.mark()
            x, y = where()
            post(DOWN, x, y); time.sleep(0.05); post(UP, x, y)
            time.sleep(0.4)
            at = (int(x * s + 1e-6), int(y * s + 1e-6))
            got = [l for l in g.lines(m) if l.startswith(("down", "up"))]
            ok(tag + "freed: a click lands under the pointer", len(got) == 2 and at_pixel(got[0], at), f"{got} {at}")
            # win32u clips the whole screen again on a click in a full-screen window: still free
            m = g.mark()
            post(MOVED, x + 8, y, 8, 0)
            time.sleep(0.3)
            ok(tag + "freed: still free after the click", any(l.startswith("move ") for l in g.lines(m)))
            # 3 locked again: the view does not jump
            m, k = g.mark(), w.mark()
            g.key(1)
            g.hear("locked", 3, m)
            w.logged("pointer held by the game", 3, k)
            time.sleep(0.4)
            post(MOVED, *where(), 2, 1)
            time.sleep(0.3)
            rr = raws(g, m)
            ok(tag + "locked again: no camera jump", rr == [(2, 1)], str(rr))
            # a button held across the transitions
            m = g.mark()
            x, y = where()
            post(DOWN, x, y); time.sleep(0.1)
            g.key(2); time.sleep(0.4)
            g.key(1); time.sleep(0.4)
            x, y = where()
            post(UP, x, y); time.sleep(0.3)
            got = [l.split()[0] for l in g.lines(m) if l.startswith(("down", "up"))]
            ok(tag + "a button held through freed and locked: one down, one up", got == ["down", "up"], str(got))
            # a key held across
            m = g.mark()
            w.debug(1, 0, 1); time.sleep(0.1)
            g.key(2); time.sleep(0.3); g.key(1); time.sleep(0.3)
            w.debug(1, 0, 0); time.sleep(0.2)
            got = [l for l in g.lines(m) if l.startswith("key") and not any(l.endswith(f" 7{i}") for i in range(10))]
            ok(tag + "a key held through both: one down, one up", [l.split()[0] for l in got] == ["keydown", "keyup"], str(got))
            # 60 toggles at once
            m, k = g.mark(), w.mark()
            g.key(5)
            g.hear("toggled", 5, m)
            time.sleep(0.6)
            post(MOVED, *where(), 3, 0)
            time.sleep(0.3)
            rr = raws(g, m)
            ok(tag + f"60 toggles at once: held, no jump ({w.log()[k:].count('pointer freed by the game')} reached wsd)", rr == [(3, 0)] or (sum(a for a, _ in rr), sum(b for _, b in rr)) == (3, 0), str(rr))
            # confined to a square
            m = g.mark()
            g.key(4)
            g.hear("confined", 3, m)
            time.sleep(0.3)
            post(MOVED, *where(), 7, -5)
            time.sleep(0.3)
            m = g.mark()
            g.key(2)
            f = g.hear(r"freed cursor (\d+),(\d+)", 3, m)
            time.sleep(0.4)
            at = where()
            ok(tag + "a square, moved inside, freed: macOS's pointer is on the game's cursor", near(at, pt(int(f[1]), int(f[2]))), f"{at} for {f[0]} {pt(int(f[1]), int(f[2]))}")
            # the cursor shown: absolute, visible
            g.key(3)
            time.sleep(0.6)
            ok(tag + "the game shows its cursor: it shows", bool(cg.CGCursorIsVisible()))
            m = g.mark()
            post(MOVED, *pt(mx - 40, my - 30), 1, 1)
            time.sleep(0.3)
            got = [l for l in g.lines(m) if l.startswith("move ")]
            ax, ay = where()
            ok(tag + "... and follows the pointer", bool(got) and at_pixel(got[-1], (int(ax * s + 1e-6), int(ay * s + 1e-6))), str(got[-1:]))
            m = g.mark()
            g.key(8)
            g.hear("done", 5, m)
            time.sleep(0.5)
            ok(tag + "ended: the pointer is macOS's", True)
        except AssertionError as e:
            ok(tag + "ended early", False, str(e))
        finally:
            g.end()
            keep = os.environ.get("KEEP")
            if keep:
                pathlib.Path(keep).mkdir(exist_ok=True)
                shutil.copy(w.log_path, f"{keep}/guest-{kind}-{percent}-{'on' if on else 'off'}.wsd.log")
                shutil.copy(g.out, f"{keep}/guest-{kind}-{percent}-{'on' if on else 'off'}.out")
            w.end()
            awake.kill()


main()
print(f"{wp.passed} passed, {len(wp.failed)} failed" + "".join("\n  " + f for f in wp.failed))
sys.exit(bool(wp.failed))
