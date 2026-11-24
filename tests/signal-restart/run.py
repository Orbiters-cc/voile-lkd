#!/usr/bin/env python3
"""Whether a signal, a suspension or a fault that is restarted leaves the interrupted program as it was, on a given engine.
  run.py <fexdarwin-run | released> [--only TEXT] [--soak SECONDS] [--seeds N] [--work FOLDER] [--no-wine]
Reads the other files of the installed release in place, under the library's shared lock (owned.py); writes to the work folder
alone (a scratch folder by default). The last column is what is to be known: `pass` or `FAIL`. Exit status 0: everything passed.
Controls are marked so: they pass on an engine that has the defects too."""
import argparse, os, re, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import owned
HERE = Path(__file__).resolve().parent
p = argparse.ArgumentParser()
p.add_argument('engine'); p.add_argument('--only', default=''); p.add_argument('--soak', type=int, default=20); p.add_argument('--seeds', type=int, default=1)
p.add_argument('--work', default=None); p.add_argument('--no-wine', action='store_true')
a = p.parse_args()
engine = owned.released_engine() if a.engine == 'released' else Path(a.engine).resolve()
work = Path(a.work or tempfile.mkdtemp(prefix='signal-restart.')).resolve(); bins = work / 'bin'

def build(seed):
    subprocess.run([str(HERE / 'build.sh'), str(bins)], check=True, env=os.environ | {'SOAK_SEED': str(seed)}, stdout=subprocess.DEVNULL)

# (name, control, wine, program and arguments, engine options, least number of signals handled)
KERNELS = dict(c='call/ret epilogues', p='pairs of stack operations', b='a large function with far branches', k='moves and exchanges', a='carry and flags',
               v='256-bit registers', x='x87', m='MMX', d='direction flag', i='SSE, shifts, bit tests, jcc')
T = []
T.append(('kernels 1, no signals', True, False, ['sigstorm', 'crbBkavx', 3, '-'], [], 0))
T.append(('kernels 2, no signals', True, False, ['sigstorm', 'mdpi', 3, '-'], [], 0))
T.append(('signals: read-modify-write', True, False, ['sigstorm', 'rr', 6, 100], [], 100))
T.append(('signals: a large function, no far branch', True, False, ['sigstorm', 'BB', 6, 100], [], 100))
T.append(('signals: call/ret, no adjacent stack ops', True, False, ['sigstorm_split', 'cc', 8, 100], [], 100))
for k, what in KERNELS.items():
    T.append((f'signals: {what}', k == 'k', False, ['sigstorm', k + k, 8, 100], [], 10))
T.append(('signals: call/ret, leaves 2 MiB away', False, False, ['sigstorm_far', 'cc', 8, 100], [], 100))
T.append(('signals: call/ret, nops before the ret', False, False, ['sigstorm_nop', 'cc', 8, 100], [], 100))
T.append(('signals: call/ret, the ret in its own block', False, False, ['sigstorm_jmp', 'cc', 8, 100], [], 100))
T.append(('signals: call/ret, MULTIBLOCK=0', False, False, ['sigstorm', 'cc', 8, 100], ['--fex-config', 'MULTIBLOCK=0'], 1))
T.append(('signals: a large function, MULTIBLOCK=0', True, False, ['sigstorm', 'bb', 6, 100], ['--fex-config', 'MULTIBLOCK=0'], 10))
T.append(('signals: call/ret, carry, code beside data', False, False, ['sigstorm_val', 'ca', 8, 100], [], 20))
T.append(('signals: AVX, pairs, code beside data', False, False, ['sigstorm_val', 'vp', 8, 100], [], 20))
T.append(('faults that are restarted: 76 cases', False, False, ['syncfault'], [], 0))
T.append(('faults, control: without carry, pairs, AVX...', True, False, ['syncfault', 'push_mem', 'mov_load', 'xchg_store', 'add_mem', 'neg_mem', 'shl_mem', 'xchg_mem', 'xadd_mem',
          'lock_xadd_mem', 'lock_add_mem', 'cmpxchg_mem', 'mul_mem', 'rep_lodsb', 'rep_stosb', 'rep_movsb', 'sse_load', 'bigctl'], [], 0))
for s in range(a.seeds):
    T.append((f'soak {s + 1}: programs, no signals', True, False, ['soak', 4, 4, '-'], [], 0, s + 1))
    T.append((f'soak {s + 1}: programs, signals, {a.soak} s', False, False, ['soak', 4, a.soak, 150], [], 50, s + 1))
if not a.no_wine:
    T.append(('SuspendThread: call/ret, no adjacent stack ops', True, True, ['susp_split', 'c', 1500, 300], [], 0))
    T.append(('SuspendThread: read-modify-write', True, True, ['susp', 'r', 1500, 300], [], 0))
    T.append(('SuspendThread: call/ret', False, True, ['susp', 'c', 3000, 300], [], 0))
    T.append(('SuspendThread: 32-bit stack operations', False, True, ['susp32', 'p', 1500, 300, 2, 30], [], 0))
    for s in range(a.seeds):
        T.append((f'SuspendThread: soak {s + 1}, {a.soak} s', False, True, ['susp_soak', 's', 1000000, 300, 4, a.soak], [], 0, s + 1))

print(f'engine {engine}\nwork   {work}')
seed, bad = None, 0
for t in T:
    name, control, wine, argv, options, least = t[:6]; want = t[6] if len(t) > 6 else 1
    if a.only and a.only not in name: continue
    if seed != want: build(want); seed = want
    limit = (a.soak + 60) if 'soak' in name else 90
    for again in (0, 1):  # a first Windows program makes its prefix
        rc, out = owned.run(engine, work, bins, argv, wine=wine, timeout=limit, options=options, out=work / (re.sub(r'\W+', '-', name) + '.log'))
        if not (wine and rc in (142, 124) and not 'WITNESS' in out and not again): break
    said = [l for l in out.splitlines() if l.startswith('WITNESS')]
    n = re.search(r'handled=(\d+)', said[-1] if said else '')
    ok = rc == 0 and bool(said) and (not least or (n and int(n[1]) >= least))
    bad += not ok
    print(f"{'pass' if ok else 'FAIL'}  {'control ' if control else '        '}{name:48} exit {rc:3}  {said[-1][8:150] if said else '(said nothing)'}", flush=True)
print(f'{bad} failed')
sys.exit(1 if bad else 0)
