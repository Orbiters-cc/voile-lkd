#!/usr/bin/env python3
"""The three starts rehearsed end to end without the game, its account or the owner's library: the runner (real_session.py), the
bench (bench.py of Orbiters-N4N0) and the developer's obelisk-cli are the real ones; the library, the home folder and the prefix
are temporary, and the owned Direct3D 11 client (tests/graphics/pass_costs.cpp) stands in VRChat's place (rehearse_cli.py).

Usage: rehearse.py --cli <developer's obelisk-cli> --generation <folder> --release <Voile release folder, as Voile ships it>
                   --client <pass_costs.exe> --out <folder> [--bench <folder of bench.py>] [--mode heavy60] [--plan 58,100,45]
                   [--switch NAME=VALUE ...] [--aba]

--aba: a whole series instead, three invocations of the runner as the owner makes them: without a switch, with --switch (queries=once), without.

The client covers the screen for less than a minute per start. Refuses while the screen is locked."""
import argparse, json, os, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("--cli", "--generation", "--release", "--client", "--out"):
        p.add_argument(name, required=True)
    p.add_argument("--bench", default=HERE)
    p.add_argument("--switch", action="append", default=[])
    p.add_argument("--mode", default="heavy60")
    p.add_argument("--plan", default="58,100,45")
    p.add_argument("--seconds", type=int, default=45)
    p.add_argument("--windows", type=int, default=3)
    p.add_argument("--window", type=int, default=8)
    p.add_argument("--passes", default="8")
    p.add_argument("--keep", action="store_true")
    p.add_argument("--aba", action="store_true")
    a = p.parse_args()
    out = os.path.abspath(a.out)
    home = os.path.join(out, "home")
    library = os.path.join(home, "Library/Application Support/cc.orbiters.obelisk-cli")
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(os.path.join(library, "Voile"))
    with open(os.path.join(a.release, "runtime.json")) as f:
        version = json.load(f)["version"]
    subprocess.run(["/bin/cp", "-Rc", os.path.abspath(a.release), os.path.join(library, "Voile", version)], check=True)
    open(os.path.join(library, "Voile", "prereleases"), "w").close()  # (the release is a beta: as `settings prereleases on`)
    install = os.path.join(library, "Games", "rehearsal")
    os.makedirs(install)
    shutil.copy(a.client, os.path.join(install, "pass_costs.exe"))
    with open(os.path.join(home, "rehearsal.json"), "w") as f:
        json.dump(dict(cli=os.path.abspath(a.cli), install=install, seconds=a.seconds, mode=a.mode), f)
    stub = os.path.join(home, "obelisk-cli")
    shutil.copy(os.path.join(HERE, "rehearse_cli.py"), stub)
    os.chmod(stub, 0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("OBELISK_")} | {"HOME": home}
    engine = lambda which: subprocess.run([a.cli, "engine", "generation"], env=env | {"OBELISK_DEVELOPER_ENGINE": which,
                                          "OBELISK_DEVELOPER_ENGINE_FILES": os.path.abspath(a.generation)}, capture_output=True, text=True).stdout
    first = engine("released")
    print("the released generation first:", first.strip()[:160])
    command = ["/usr/bin/python3", "-I", os.path.join(HERE, "real_session.py"), "vrchat://launch?ref=orbiters.cc&id=wrld_00000000-0000-0000-0000-000000000000:12345~private(usr_rehearsal)~region(eu)",
               "--rehearse", "--cli", stub, "--generation", os.path.abspath(a.generation), "--bench", os.path.abspath(a.bench), "--out", os.path.join(out, "evidence"),
               "--plan", a.plan.split(",")[-1] if a.aba else a.plan, "--warm", "4", "--window", str(a.window), "--windows", str(a.windows), "--between", "5", "--passes", a.passes]
    asked = [["--series", "rehearsal"] + (["--nothing-wrong-seen"] if n else []) + (["--switch", (a.switch or ["queries=once"])[0]] if n == 1 else []) for n in range(3)] if a.aba else \
        [[x for switch in a.switch for x in ("--switch", switch)]]
    status = 0
    for n, more in enumerate(asked):
        if n:  # (the real runner refuses to start on a Mac that is warm: it is waited for here)
            time.sleep(30)
            for _ in range(60):
                if subprocess.run(["/usr/bin/notifyutil", "-g", "com.apple.system.thermalpressurelevel"], capture_output=True, text=True).stdout.split()[-1:] == ["0"]:
                    break
                time.sleep(10)
        runner = subprocess.Popen(command + more, env=env)
        while True:
            try:
                status = runner.wait() or status
                break
            except KeyboardInterrupt:
                pass  # (the runner's to handle)
        if status:
            break
    last = json.loads((engine("released").strip() or "{}").splitlines()[-1])
    print("the released generation last:", last.get("event"), last.get("generation"))
    before = json.loads(first.strip().splitlines()[-1]).get("engine_files")
    same = before is not None and before == last.get("engine_files")
    print("the library's engine files are", "the same as before" if same else "NOT THE SAME AS BEFORE")
    return status or (0 if same else 1)


sys.exit(main())
