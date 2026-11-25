#!/usr/bin/env python3
"""Whether a signal, a suspension or a fault that is restarted leaves the interrupted program as it was, on a given engine.
  run.py <fexdarwin-run | released> [--only TEXT] [--group correct|sched|latency|world|quit] [--soak SECONDS] [--seeds N] [--rounds N] [--load N]
         [--work FOLDER] [--no-wine]
Groups: correct (nothing is lost or done twice), sched (every thread is scheduled as on the released engine, always), latency (how
long a stop takes: every loop shape of shapes_k.S, and through Wine's SuspendThread), world (a collector's stop-the-world rounds), quit
(the ways a program ends, with threads running). --load N keeps N threads busy meanwhile: the limits of `latency` are then those of a
native thread at the same load (native.c), and a round that is late is tried once more.
Reads the other files of the installed release in place, under the library's shared lock (owned.py); writes to the work folder
alone (a scratch folder by default). The last column is what is to be known: `pass` or `FAIL`. Exit status 0: everything passed.
Controls are marked so: they pass on an engine that has the defects too."""
import argparse, os, re, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import owned, sched
HERE = Path(__file__).resolve().parent
p = argparse.ArgumentParser()
p.add_argument('engine'); p.add_argument('--only', default=''); p.add_argument('--soak', type=int, default=20); p.add_argument('--seeds', type=int, default=1)
p.add_argument('--work', default=None); p.add_argument('--no-wine', action='store_true'); p.add_argument('--group', default='')
p.add_argument('--rounds', type=int, default=200); p.add_argument('--load', type=int, default=0)
a = p.parse_args()
engine = owned.released_engine() if a.engine == 'released' else Path(a.engine).resolve()
work = Path(a.work or tempfile.mkdtemp(prefix='signal-restart.')).resolve(); bins = work / 'bin'

def build(seed):
    subprocess.run([str(HERE / 'build.sh'), str(bins)], check=True, env=os.environ | {'SOAK_SEED': str(seed)}, stdout=subprocess.DEVNULL)

# (name, control, wine, program and arguments, engine options, least number of signals handled, seed, group, time limit)
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
T.append(('string instructions, no signals', True, False, ['repstorm', 6, '-'], [], 0))
T.append(('signals: string instructions', False, False, ['repstorm', 12, 100], [], 100))
T.append(('faults that are restarted: 76 cases', False, False, ['syncfault'], [], 0))
T.append(('faults, control: without carry, pairs, AVX...', True, False, ['syncfault', 'push_mem', 'mov_load', 'xchg_store', 'add_mem', 'neg_mem', 'shl_mem', 'xchg_mem', 'xadd_mem',
          'lock_xadd_mem', 'lock_add_mem', 'cmpxchg_mem', 'mul_mem', 'rep_lodsb', 'rep_stosb', 'rep_movsb', 'sse_load', 'bigctl'], [], 0))
for s in range(a.seeds):
    T.append((f'x87 stacks at a fault: 1000 programs, seed {s + 1}', False, False, ['x87fault'], [], 0, s + 1))
    T.append((f'soak {s + 1}: programs, no signals', True, False, ['soak', 4, 4, '-'], [], 0, s + 1))
    T.append((f'soak {s + 1}: programs, signals, {a.soak} s', False, False, ['soak', 4, a.soak, 150], [], 50, s + 1))
if not a.no_wine:
    T.append(('SuspendThread: call/ret, no adjacent stack ops', True, True, ['susp_split', 'c', 1500, 300], [], 0))
    T.append(('SuspendThread: read-modify-write', True, True, ['susp', 'r', 1500, 300], [], 0))
    T.append(('SuspendThread: call/ret', False, True, ['susp', 'c', 3000, 300], [], 0))
    T.append(('SuspendThread: 32-bit stack operations', False, True, ['susp32', 'p', 1500, 300, 2, 30], [], 0))
    for s in range(a.seeds):
        T.append((f'SuspendThread: soak {s + 1}, {a.soak} s', False, True, ['susp_soak', 's', 1000000, 300, 4, a.soak], [], 0, s + 1))
def burn(n):
    """n host threads that compute for as long as this script runs"""
    src = work / 'burn.c'; src.write_text('#include <stdlib.h>\n#include <unistd.h>\n#include <pthread.h>\nstatic volatile double x; static void *w(void *p) { for (;;) x += 1; return p; }\n'
        'int main(int c, char **v) { pid_t p = getppid(); for (int i = atoi(v[1]); i--;) { pthread_t t; pthread_create(&t, 0, w, 0); } while (getppid() == p) sleep(1); return 0; }\n')
    subprocess.run(['/usr/bin/cc', '-O1', '-o', str(work / 'burn'), str(src)], check=True)
    return subprocess.Popen([str(work / 'burn'), str(n)])

def native():
    """The slowest p99 and the longest, in us, of five runs of native.c: what the scheduler makes a signal to a native thread wait."""
    subprocess.run(['/usr/bin/cc', '-O1', '-o', str(work / 'native'), str(HERE / 'native.c')], check=True)
    out = [subprocess.run([str(work / 'native'), '1000', '8000'], check=True, capture_output=True, text=True).stdout.strip() for _ in range(5)]
    for l in out: print('native        ' + l, flush=True)
    return tuple(max(float(re.search(rf'{k}=(\d+)', l)[1]) for l in out) for k in ('p99_us', 'max_us'))

work.mkdir(parents=True, exist_ok=True)
burner = burn(a.load) if a.load else None
# The limits of p99 and of the longest, in us. Idle, a thread runs: a stop is a matter of microseconds. On a busy machine it waits for its turn
# on a core as every other thread does, native ones too, and what is asked of the engine is that it adds nothing to that: no more than
# twice (p99, and 1 ms) and three times (the longest one) what a signal to a native thread needs at the same time.
LIMITS = [1000, 50000]
if a.load and a.group in ('', 'latency'):
    p99, longest = native(); LIMITS = [int(2 * p99 + 1000), int(max(3 * longest, 50000))]
    print(f'limits        p99_us={LIMITS[0]} max_us={LIMITS[1]}', flush=True)
names = re.findall(r'^SHAPE s_(\w+)', (HERE / 'shapes_k.S').read_text(), re.M)
for n in names:
    T.append((f'latency: {n}', n in ('getpid', 'sleep', 'futex'), False, ['shapes', n, 1000, 8000, *LIMITS], [], 0, 1, 'latency', 40))
if not a.no_wine:
    for n in re.findall(r'\{"(\w+)", l_', (HERE / 'shut.c').read_text()):
        T.append((f'SuspendThread latency: {n}', False, True, ['shut', 'lat', n, 500, 8000, *LIMITS], [], 0, 1, 'latency', 50))
    for n in (20, 40):
        T.append((f'stop the world: {n} threads, {a.rounds * 2} rounds', False, True, ['stw', a.rounds * 2, n, 1000, 120], [], 0, 1, 'world', 150))
    T.append((f'quit: {a.rounds} times, 8 ways', False, True, ['shut', 'drv', a.rounds, 'EKRMTCPS', 20000, 2000], [], 0, 1, 'quit', a.rounds * 4 + 400))
    T.append((f'quit after stop-the-world rounds: {a.rounds // 4} times', False, True, ['shut', 'drv', a.rounds // 4, 'G', 20000, 2000], [], 0, 1, 'quit', a.rounds * 2 + 400))

print(f'engine {engine}\nwork   {work}')
seed, bad = None, 0
for t in T:
    name, control, wine, argv, options, least = t[:6]; want = t[6] if len(t) > 6 else 1; group = t[7] if len(t) > 7 else 'correct'
    if (a.only and a.only not in name) or (a.group and a.group != group): continue
    if seed != want: build(want); seed = want
    limit = t[8] if len(t) > 8 else (a.soak + 60) if 'soak' in name else 90
    for again in (0, 1):  # a first Windows program makes its prefix
        rc, out = owned.run(engine, work, bins, argv, wine=wine, timeout=limit, options=options, out=work / (re.sub(r'\W+', '-', name) + '.log'))
        late = a.load and group == 'latency' and rc == 1
        if not ((wine and rc in (142, 124) and not 'WITNESS' in out or late) and not again): break
    said = [l for l in out.splitlines() if l.startswith('WITNESS')]
    if 'A loop without a safe point' in out: said, rc = ['WITNESS a loop without a safe point was compiled'], 1
    n = re.search(r'handled=(\d+)', said[-1] if said else '')
    ok = rc == 0 and bool(said) and (not least or (n and int(n[1]) >= least))
    bad += not ok
    if group == 'quit':
        for l in out.splitlines():
            if l.startswith(('HANG', 'BAD', 'UNKILLABLE')): print('      ' + l, flush=True)
        frozen = len(re.findall(r'lkd: sig: signal 19 .* stops process', out))
        if frozen: print(f'      processes stopped by a late attach SIGSTOP (lkd): {frozen}', flush=True)
    print(f"{'pass' if ok else 'FAIL'}  {'control ' if control else '        '}{name:48} exit {rc:3}  {said[-1][8:260] if said else '(said nothing)'}", flush=True)

def scheduling():
    """The guest's threads are the game's: no priority, policy or QoS of theirs is ever another than on the released engine (sched.py). On a busy
    machine, where an engine would be tempted to."""
    global bad
    build(1); sched.build(bins)
    for name, argv, wine in (('how threads are scheduled: 14 threads, signals', ['sched', 4000, 9], False),  # busy by themselves
                             ('how threads are scheduled: SuspendThread', ['susp', 'r', 2000, 300, 4, 60], True)):
        if a.only not in name or (wine and a.no_wine): continue
        if wine: owned.run(engine, work, bins, ['susp', 'r', 1, 300], wine=True, timeout=90)  # a first Windows program makes its prefix
        own = burn(8) if wine and not a.load else None
        ok, report, wrong, ways = sched.check(engine, owned.released_engine(), work, bins, argv, wine=wine)
        if own: own.kill(); own.wait()
        bad += not ok
        print(f"{'pass' if ok else 'FAIL'}          {name}", *report, *('WRONG ' + w for w in wrong), *('as released: ' + w for w in ways), sep='\n        ', flush=True)

if a.group in ('', 'sched'): scheduling()
if burner: burner.kill()
print(f'{bad} failed')
sys.exit(1 if bad else 0)
