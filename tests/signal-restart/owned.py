"""Runs one witness on an engine, reading the installed release's other files in place (read-only) under the library's
shared lock, as the crash research's run-owned.py did. Nothing under the library is written."""
from pathlib import Path
import fcntl, os, subprocess

LIBRARY = Path(os.environ.get('OBELISK_LIBRARY', Path.home() / 'Library/Application Support/cc.orbiters.obelisk-cli'))
RELEASE = os.environ.get('VOILE_RELEASE', 'v26.3.0-27.beta1')

def linux():
    return LIBRARY / 'Voile' / RELEASE / 'linux'

def released_engine():
    return linux() / 'engine/fexdarwin-run'

def run(engine, work, bins, argv, wine=False, timeout=85, options=(), env=(), out=None):
    """argv: the program's name in `bins` (a Windows one without its .exe when `wine`) and its arguments. Returns (exit status, output)."""
    work = Path(work); rt = linux()
    for d in ('host-tmp', 'tmp', 'shm', 'home'):
        (work / d).mkdir(parents=True, exist_ok=True)
    with (LIBRARY / 'Voile.locks/library.lock').open('rb') as lock:
        fcntl.flock(lock, fcntl.LOCK_SH)
        e = dict(PATH='/usr/bin:/bin', HOME=str(work / 'home'), TMPDIR=str(work / 'host-tmp'), FEXDARWIN_LKD='1', FEXDARWIN_ROOT=str(rt / 'root'),
                 FEXDARWIN_ROOT_RO='1', LKD_HOST_TMP=str(work / 'tmp'), LKD_HOST_SHM=str(work / 'shm'),
                 FEXDARWIN_BIND=f'/opt/wine={rt}/wine:ro;/home/user={work}/home;/w={bins}:ro')
        args = [str(rt / 'engine/run-with-timeout.sh'), str(timeout), str(engine), *options]
        for kv in ['HOME=/home/user', 'USER=user', 'PATH=/opt/wine/bin:/usr/bin:/bin', 'WINEPREFIX=/home/user/prefix', 'WINEDEBUG=-all',
                   'WINEDLLOVERRIDES=mscoree,mshtml=;winemenubuilder.exe=d', *env]:
            args += ['--env', kv]
        args += (['/opt/wine/bin/wine', f'/w/{argv[0]}.exe'] if wine else [f'/w/{argv[0]}']) + [str(a) for a in argv[1:]]
        p = subprocess.run(args, env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=work)
    text = p.stdout.decode(errors='replace')
    if out:
        Path(out).write_text(text)
    return p.returncode, text
