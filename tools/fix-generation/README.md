# The fix generation

The released engine files with another `fexdarwin-run`, in place for one start by the developer's obelisk-cli, the way of the timeline
generation (Obelisk, branch `perf-timeline`, `docs/CLI.md`, "The timeline generation"; whose name it has there: `timeline`). Nothing of it
is in a release, and a released obelisk-cli starts no game while it is in place.

```sh
./make.py <Voile release folder> <Obelisk>/crates/game-runtime/engine-patch <fexdarwin-run> ~/.orbiters-forks/fix-generation voile-lkd=<commit>
# the CLI that knows it: perf-timeline's, with this timeline.json in crates/game-runtime/engine-patch
cargo build --locked -p obelisk-cli --release --features developer-timeline --target aarch64-apple-darwin
scripts/package-timeline-cli.sh <obelisk-cli-<version>-arm64.tar.gz> <built obelisk-cli> ~/.orbiters-forks/fix-cli
```

A start, with nothing of the engine running (each refuses otherwise):

```sh
G=~/.orbiters-forks/fix-generation C=~/.orbiters-forks/fix-cli/obelisk-cli
OBELISK_DEVELOPER_ENGINE=timeline OBELISK_DEVELOPER_ENGINE_FILES=$G $C engine generation      # in: tells every file's digest
OBELISK_DEVELOPER_ENGINE=timeline OBELISK_DEVELOPER_ENGINE_FILES=$G $C steam play ...         # the start, by the same program
OBELISK_DEVELOPER_ENGINE=released OBELISK_DEVELOPER_ENGINE_FILES=$G $C engine generation      # back, whatever happened
./verify.py $G released                                                                       # every digest is the released one's
```

`voile-lkd-perf/tools/timeline/real_session.py <link> --generation $G --cli $C` does the same around a whole session (and `--restore` what
a start that was cut off still owes); it has no recorders to read in this generation and calls every start inconclusive.
