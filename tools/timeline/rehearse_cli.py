#!/usr/bin/env python3
"""obelisk-cli's place in the rehearsal (rehearse.py): `steam play` starts the owned Direct3D 11 client through the developer's
obelisk-cli (`engine rehearse`: the engine's own preparation, launcher and Wine) and says the events a game's start says, with a
session record and a VRChat log like the ones bench.py reads; `steam quit` ends it; everything else is the real program's."""
import datetime, glob, json, os, signal, subprocess, sys, time, uuid

HOME = os.path.expanduser("~")
LIBRARY = f"{HOME}/Library/Application Support/cc.orbiters.obelisk-cli"
RECORDS = f"{LIBRARY}/SteamSessions"
with open(os.path.join(HOME, "rehearsal.json")) as f:
    CONFIG = json.load(f)


def tell(**event):
    print(json.dumps(event), flush=True)


def record(session, phase, pid, **more):
    os.makedirs(RECORDS, exist_ok=True)
    path = f"{RECORDS}/{session}.v2.json"
    with open(path + ".new", "w") as f:
        json.dump(dict(id=session, store=dict(app_id=438100), phase=phase, game=dict(pid=pid) if pid else None, rehearsal=True) | more, f)
    os.rename(path + ".new", path)


def play(words):
    percent = int(words[words.index("--render-percent") + 1]) if "--render-percent" in words else 100
    link = words[-1]
    session = str(uuid.uuid4())
    logs = f"{HOME}/Library/Logs/Obelisk/Steam"
    vrchat = f"{LIBRARY}/Prefixes/steam-438100-windows-linux/prefix/drive_c/users/crossover/AppData/LocalLow/VRChat/VRChat"
    for folder in (logs, vrchat):
        os.makedirs(folder, exist_ok=True)
    child = subprocess.Popen([CONFIG["cli"], "engine", "rehearse", CONFIG["install"], f"{CONFIG['install']}/pass_costs.exe", str(percent),
                              f"{logs}/wine-438100.log", "--", str(CONFIG["seconds"]), "0", CONFIG["mode"]], stdout=subprocess.PIPE, text=True)
    tell(event="starting", app_id=438100, session_id=session)
    pid = None
    for line in child.stdout:
        event = json.loads(line)
        if event["event"] == "rehearsal_running":
            pid = event["pid"]
            record(session, "Running", pid)
            with open(os.path.join(HOME, "running.json"), "w") as f:
                json.dump(dict(session=session, pid=pid), f)
            tell(event="running", app_id=438100, pid=pid, session_id=session)
            # (a program of no app of its own is not brought to the front by itself, as a game's is)
            subprocess.Popen("sleep 4; /usr/bin/open \"${TMPDIR:-/tmp}/obelisk-apps/Rehearsal/Rehearsal.app\"", shell=True, stdout=subprocess.DEVNULL)
            now = f"{datetime.datetime.now():%Y.%m.%d %H:%M:%S} Debug      -  "
            place = link.split("id=")[1]
            with open(f"{vrchat}/output_log_{datetime.datetime.now():%Y-%m-%d_%H-%M-%S}.txt", "w") as f:
                f.write(f"{now}Arg: {link}\n{now}[Behaviour] Joining {place}\n{now}[Behaviour] Initialized PlayerAPI \"rehearsal\" is local\n")
        elif event["event"] == "error":
            print(line, end="", flush=True)
            return 1
        elif event["event"] == "rehearsal_exited":
            record(session, "Finished", None, exit_code=event["exit_code"], played=dict(seconds=1))
            tell(event="exited", app_id=438100, session_id=session, frames=None, exit_code=event["exit_code"], exit_signal=None, seconds=1, ended_by_request=True)
    return child.wait()


def quit_(words):
    with open(os.path.join(HOME, "running.json")) as f:
        running = json.load(f)
    assert words[words.index("--session") + 1] == running["session"], "another session was asked to quit"
    os.kill(running["pid"], signal.SIGTERM)
    tell(event="quit_requested", app_id=438100, forced=False)
    for _ in range(600):
        with open(f"{RECORDS}/{running['session']}.v2.json") as f:
            if json.load(f)["phase"] == "Finished":
                return 0
        time.sleep(0.1)
    return 1


def main():
    words = sys.argv[1:]
    if words[:2] == ["steam", "play"]:
        return play(words)
    if words[:2] == ["steam", "quit"]:
        return quit_(words)
    for path in glob.glob(f"{RECORDS}/*.v2.json"):  # (the real program does not know these records)
        with open(path) as f:
            if json.load(f).get("rehearsal"):
                os.remove(path)
    os.execv(CONFIG["cli"], [CONFIG["cli"], *words])


sys.exit(main())
