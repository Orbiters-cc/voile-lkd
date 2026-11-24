#!/usr/bin/env python3
"""A developer generation that is the released one with another fexdarwin-run, for a start by hand before it is released.
  make.py <Voile release folder, as Voile ships it> <engine-patch folder of the Obelisk checkout> <fexdarwin-run> <out folder> [<sources>=<commit> ...]
Writes into <out>: released/ and timeline/ (whole trees, clones; timeline is the other generation's name in the developer's obelisk-cli),
fexdarwin-run, original/ (empty: no file that only this generation changes), comparison.json (every entry of the two trees), timeline.json
(what the developer's obelisk-cli is built with), engine-files.json (the digests that prove which is in place) and sources.json.
Nothing is written when anything but engine/fexdarwin-run differs. Reads nothing of the library and writes nothing to it."""
import hashlib, json, os, shutil, stat, subprocess, sys
ENGINE = "engine/fexdarwin-run"

def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()

def tree(root):
    out = {}
    for folder, names, files in os.walk(root):
        for name in names + files:
            path = os.path.join(folder, name); st = os.lstat(path); rel = os.path.relpath(path, root)
            if stat.S_ISLNK(st.st_mode): out[rel] = ("link", "", os.readlink(path))
            elif stat.S_ISDIR(st.st_mode): out[rel] = ("folder", oct(st.st_mode & 0o777), "")
            elif stat.S_ISREG(st.st_mode): out[rel] = ("file", oct(st.st_mode & 0o777), sha(path))
            else: out[rel] = ("other", oct(st.st_mode), "")
    return out

def put(source, to):  # (the mode of the file there stays)
    with open(source, "rb") as f, open(to, "wb") as t:
        t.write(f.read())

def main():
    release, patch, engine, out = (os.path.abspath(p) for p in sys.argv[1:5])
    with open(os.path.join(release, "runtime.json")) as f: voile = json.load(f)["version"]
    with open(os.path.join(patch, "manifest.json")) as f: manifest = json.load(f)
    if manifest["voile"] != voile: sys.exit(f"the engine files are for {manifest['voile']}")
    if subprocess.run(["/usr/bin/codesign", "--verify", "--strict", engine]).returncode: sys.exit("not signed")
    os.makedirs(out, exist_ok=True)
    for name in ("released", "timeline", "original"):
        shutil.rmtree(os.path.join(out, name), ignore_errors=True)
    linux, released, other = os.path.join(release, "linux"), os.path.join(out, "released"), os.path.join(out, "timeline")
    subprocess.run(["/bin/cp", "-Rc", linux, released], check=True)
    for f in manifest["files"]:
        put(os.path.join(patch, f["source"]), os.path.join(released, f["path"]))
        if sha(os.path.join(released, f["path"])) != f["patched"]: sys.exit(f"{f['source']} is not the manifest's")
    subprocess.run(["/bin/cp", "-Rc", released, other], check=True)
    put(engine, os.path.join(other, ENGINE))
    os.mkdir(os.path.join(out, "original"))
    shutil.copy(engine, os.path.join(out, "fexdarwin-run"))
    a, b = tree(released), tree(other)
    differing = sorted(p for p in set(a) | set(b) if a.get(p) != b.get(p))
    if differing != [ENGINE] or a[ENGINE][1] != b[ENGINE][1]: sys.exit(f"these differ: {differing}")
    rest = hashlib.sha256("\n".join(f"{p} {' '.join(e)}" for p, e in sorted(a.items()) if p != ENGINE).encode()).hexdigest()
    entry = next(f for f in manifest["files"] if f["path"] == ENGINE)
    paths = sorted(f["path"] for f in manifest["files"])
    graphics = {p: e[2] for p, e in b.items() if e[0] == "file" and (p.startswith("graphics/") or p == "engine/wsd")}
    sources = dict(s.split("=", 1) for s in sys.argv[5:])
    def write(name, what):
        with open(os.path.join(out, name), "w") as f: json.dump(what, f, indent=1)
    write("comparison.json", dict(entries=len(a), differing=[dict(path=ENGINE, released=a[ENGINE][2], timeline=b[ENGINE][2])], rest_sha256=rest))
    write("sources.json", sources)
    write("timeline.json", dict(voile=voile, sources=sources, files=[dict(path=ENGINE, source="fexdarwin-run", original=entry["original"], released=entry["patched"],
                                timeline=b[ENGINE][2])], guest={}, rest_sha256=rest))
    write("engine-files.json", dict(released={p: a[p][2] for p in paths}, timeline={p: b[p][2] for p in paths}, timeline_graphics=graphics))
    print(f"{len(a)} entries; differs: {ENGINE} {a[ENGINE][2][:16]} -> {b[ENGINE][2][:16]}; everything else identical: {rest[:16]}")

main()
