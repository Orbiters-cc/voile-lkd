"""Whether the threads that run the guest are scheduled as they are on the released engine, always: what schedwatch.c saw of both.
  sched.py <fexdarwin-run> <released fexdarwin-run> <work folder> <folder of the built programs>   (run.py's group `sched` does it all)"""
import os, re, shutil, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import owned
HERE = Path(__file__).resolve().parent
ENGINES_OWN = ('fexdarwin-', 'lkd-')  # threads of the engine's own, which run no guest code
CHANGES = re.compile(r'^_(thread_policy|thread_policy_set|thread_set_policy|task_policy_set|task_set_policy|task_policy|pthread_setschedparam|pthread_set_qos\w*|pthread_override_qos\w*|'
                     r'pthread_attr_set_?qos\w*|pthread_attr_setsched\w*|pthread_attr_set_(relative|cpu)\w*|pthread_attr_setinheritsched|setpriority|nice|thread_switch|os_workgroup\w*|work_interval\w*|'
                     r'pthread_set_fixedpriority\w*|proc_setpcontrol|thread_assign\w*|mach_msg\w*|syscall|__syscall|dlsym|dlopen|posix_spawnattr_set_qos\w*|dispatch_\w+)$')

def imports(engine):
    """What a binary imports that could change how a thread is scheduled, or could reach such a call without naming it."""
    out = subprocess.run(['/usr/bin/nm', '-u', str(engine)], check=True, capture_output=True, text=True).stdout
    return sorted(s for s in out.split() if CHANGES.match(s))

def build(bins):
    subprocess.run(['/usr/bin/cc', '-O1', '-Wall', '-Wno-deprecated-declarations', '-dynamiclib', '-o', str(bins / 'schedwatch.dylib'), str(HERE / 'schedwatch.c')], check=True)
    subprocess.run(['/usr/bin/cc', '-O1', '-Wall', '-o', str(bins / 'schedwatch_run'), str(HERE / 'schedwatch_run.c')], check=True)

def run(engine, work, bins, argv, wine, timeout):
    """(exit status, what the program said, per process what was seen)"""
    log = work / 'sched-log'; shutil.rmtree(log, ignore_errors=True); log.mkdir(parents=True)
    rc, out = owned.run(bins / 'schedwatch_run', work, bins, argv, wine=wine, timeout=timeout, options=[str(engine)])
    seen = {}
    for f in log.iterdir():
        threads, calls, samples = {}, [], 0
        for l in f.read_text(errors='replace').splitlines():
            k, _, r = l.partition(' ')
            if k == 'T':
                t, _, r = r.partition(' '); name, _, how = r.rpartition('|'); e = threads.setdefault(t, dict(name='', how=[], top=0))
                e['name'] = name or e['name']
                if how not in e['how'][-1:]: e['how'].append(how)
            elif k == 'P': t, top, base = r.split(); threads[t]['top'] = int(top) - int(base)
            elif k == 'CALL': calls.append(r)
            elif k == 'S': samples = int(r)
        seen[f.name] = dict(threads=threads, calls=calls, samples=samples)
    return rc, out, seen

def guests(seen):
    """Per process, the first one's host thread that only waits and the threads that run the guest, in the order they began."""
    out = []
    for p in seen.values():
        G = [t for k, t in sorted(p['threads'].items(), key=lambda i: int(i[0])) if not t['name'].startswith(ENGINES_OWN)]
        for i, t in enumerate(G): t['first'] = i == 0
        out.append(G)
    return out

def check(engine, released, work, bins, argv, wine=False, timeout=200, least=2000):
    """Compares a program on both engines. Returns (passed, what was seen, what is wrong, the ways threads are scheduled on the released one)."""
    ways, tops, counts, report, bad = {}, {}, {}, [], []
    for which, e in (('released', released), ('this', engine)):
        rc, out, seen = run(e, work, bins, argv, wine, timeout)
        said = [l for l in out.splitlines() if l.startswith('WITNESS')]; P = guests(seen); G = [t for p in P for t in p]
        calls = [c for p in seen.values() for c in p['calls']]; changed = [t for t in G if len(t['how']) > 1]; looks = sum(p['samples'] for p in seen.values())
        # The first host thread of a process (the main one, or the one that forked) and the others are not started alike.
        ways[which] = {(t['first'], t['how'][0]) for t in G}; tops[which] = max([t['top'] for t in G], default=0); counts[which] = len(G)
        report.append(f"{which}: {len(seen)} processes, {len(G)} threads, {looks} looks, {len(changed)} threads changed, {len(calls)} calls, current priority over the base one by {tops[which]}; "
                      f"{said[-1][8:] if said else '(said nothing)'}")
        if rc or not said: bad.append(f'{which}: exit {rc}')
        n = re.search(r'(?:handled|suspensions)=(\d+)', said[-1] if said else '')
        want = least if which == 'this' else least // 4  # (the released one needs many times as long for each)
        if not n or int(n[1]) < want: bad.append(f'{which}: fewer than {want} stops')
        if len(G) < 4 or looks < 1000: bad.append(f'{which}: nothing was seen')
        for t in changed[:3]: bad.append(f"{which}: a thread changed: {' -> '.join(t['how'][:4])}")
        for c in sorted(set(re.sub(r'\d{2,}', 'N', c) for c in calls))[:5]: bad.append(f'{which}: called {c} ({len(calls)} calls)')
    for first, how in sorted(ways['this'] - ways['released'])[:3]:
        bad.append(f"this: {how}; released: {' or '.join(sorted(h for f, h in ways['released'] if f == first))}")
    if counts['this'] != counts['released'] and not wine: bad.append(f"{counts['this']} guest threads, {counts['released']} on the released")
    # The kernel itself lifts whoever holds certain of its locks to 46, on every engine; what is above is not its doing.
    if tops['this'] > max(tops['released'], 15): bad.append(f"a current priority {tops['this']} over the base one, {tops['released']} on the released")
    if imports(engine): bad.append(f'imports {imports(engine)}')
    return not bad, report, bad, sorted(h for f, h in ways['released'])

if __name__ == '__main__':
    e, r, w, b = (Path(p).resolve() for p in sys.argv[1:5]); build(b)
    ok, report, bad, ways = check(e, r, w, b, ['sched', sys.argv[5] if len(sys.argv) > 5 else 4000])
    print('\n'.join(report + ['WRONG ' + b for b in bad] + ways)); sys.exit(not ok)
