#!/usr/bin/env python3
"""verify.py <generation folder> released|timeline [library]: whether every engine file in the library is that generation's. Reads only."""
import hashlib, json, os, sys
folder, which = sys.argv[1:3]
library = sys.argv[3] if len(sys.argv) > 3 else os.path.expanduser("~/Library/Application Support/cc.orbiters.obelisk-cli")
with open(os.path.join(folder, "timeline.json")) as f: voile = json.load(f)["voile"]
with open(os.path.join(folder, "engine-files.json")) as f: files = json.load(f)[which]
wrong = [p for p, d in files.items() if hashlib.sha256(open(os.path.join(library, "Voile", voile, "linux", p), "rb").read()).hexdigest() != d]
print(f"not the {which} generation's: {wrong}" if wrong else f"{len(files)} files, every one the {which} generation's")
sys.exit(bool(wrong))
