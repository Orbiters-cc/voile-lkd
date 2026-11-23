#!/usr/bin/env python3
"""The three starts rehearsed end to end without the game, its account or the owner's library: the runner (real_session.py), the
bench (bench.py of Orbiters-N4N0) and the developer's obelisk-cli are the real ones; the library, the home folder and the prefix
are temporary, and the owned Direct3D 11 client (tests/graphics/pass_costs.cpp) stands in VRChat's place (rehearse_cli.py).

Usage: rehearse.py --cli <developer's obelisk-cli> --generation <folder> --release <Voile release folder, as Voile ships it>
                   --bench <tools/mac-bench> --client <pass_costs.exe> --out <folder> [--mode heavy60] [--plan 58,100,45]

The client covers the screen for less than a minute per start. Refuses while the screen is locked."""
import argparse, json, os, re, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("--cli", "--generation", "--release", "--bench", "--client", "--out"):
        p.add_argument(name, required=True)
    p.add_argument("--mode", default="heavy60")
    p.add_argument("--plan", default="58,100,45")
    p.add_argument("--seconds", type=int, default=45)
    p.add_argument("--windows", type=int, default=3)
    p.add_argument("--window", type=int, default=8)
    p.add_argument("--passes", default="8")
    p.add_argument("--keep", action="store_true")
    a = p.parse_args()
    out = os.path.abspath(a.out)
    home = os.path.join(out, "home")
    library = os.path.join(home, "Library/Application Support/cc.orbiters.obelisk-cli")
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(os.path.join(library, "Voile"))
    subprocess.run(["/bin/cp", "-Rc", os.path.abspath(a.release), os.path.join(library, "Voile", json.load(open(os.path.join(a.release, "runtime.json")))["version"])], check=True)
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
               "--plan", a.plan, "--warm", "4", "--window", str(a.window), "--windows", str(a.windows), "--between", "5", "--passes", a.passes]
    status = subprocess.run(command, env=env).returncode
    last = json.loads((engine("released").strip() or "{}").splitlines()[-1])
    print("the released generation last:", last.get("event"), last.get("generation"))
    same = [f for f in json.loads(first.strip().splitlines()[-1])["engine_files"]] == last.get("engine_files")
    print("the library's engine files are", "the same as before" if same else "NOT THE SAME AS BEFORE")
    return status or (0 if same else 1)


sys.exit(main())
