# Host timeline

Where the time of a frame goes, between the render server's ring, DXMT, the GPU and wsd: the parts of the guest's "fence
wait" (its log line `neptune unixlib wsi (wsd): ... fence wait avg`) and what follows it, per frame, and how much of it is known.

**Off by default, and in no release.** On when `OBELISK_TIMELINE` names a folder in the environment of wsd, `virgl_test_server` and
`virgl_render_server`, which only a developer's obelisk-cli asked for the timeline generation gives them (Obelisk, branch
`perf-timeline`, `docs/CLI.md`, "The timeline generation"; `scripts/build-timeline-generation.sh` there builds it). The game's
process never has any of the variables: `launch.sh` takes them away, whoever set them, before it starts anything else, and
`tests/timeline/run-guest-probe.sh` compares everything the launcher gives it. Off, the recorder (`wsd/otl.h`, the same file in
`neptune` as `virglrenderer/src/neptune/otl.h` and in `dxmt` as `src/util/otl.h`) is one `getenv()` per process and one branch at
each site: no thread, file, descriptor or memory.

| Variable | |
|---|---|
| `OBELISK_TIMELINE=<folder>` | on. `launch.sh` makes a folder of the start in it, `<date>-<time>-<pid>`, with `otl-npt-<pid>.bin` and `otl-dxmt-<pid>.bin` (one of each per render server worker), `otl-vtest-<pid>.bin`, `otl-wsd-<pid>.bin` and `otl-session` |
| `OBELISK_TIMELINE_MB=<n>` | what all recorders of one start may write together (1024). Taken from `otl-session` before it is written; a recorder that gets no more, or whose write fails, ends for good with an end record; none writes with less than 2 GiB free; 64 recorders at most |
| `OBELISK_TIMELINE_PASSES=<n>` | also the encoders of every nth frame (a frame ends at each Signal of its queue), with GPU timestamps at their stage boundaries (they become part of what Metal runs: for the split between passes, not for a total). 0: none |

```sh
python3 tools/timeline/otl.py <folder of the start> [--from NS --to NS] [--plane ID] --passes --cadence [--csv out.csv] [--json out.json]
tools/timeline/real_session.py '<private instance link>'    # the three real starts, for the owner (read its head first)
tools/timeline/rehearse.py ...                              # the same without the game, the account or the owner's library
```

## What it prints

First what is missing: records lost per role and when, how each recorder ended, the session's budget, the presentations and frames
that could not be joined and why. **A frame is whole only when every boundary of it is recorded, in order, with a status that
means it, and nothing was lost while it was made; no boundary is ever filled in from another, and nothing is joined by being the
nearest in time** (`otl.py`'s head says by what; ids are never reused, pointers and handles are). Only whole frames are in the
table; the rest are counted by reason.

The fence wait of a frame runs from the guest's stopwatch as the host sees it (the later of the output fence's arrival and the
guest's stamp of the presentation before it on the same plane) to the stamp the guest sends wsd. Its parts follow each other and sum
to it; what was over before the stopwatch began counts nothing: replay tail (the ring has not decoded the presentation yet), encode
queue, encode, commit to GPU start, GPU execution, GPU end to notify (Metal's shared-event listener), notify to worker awake, worker
awake to proxy, proxy to guest stamp. They are host proxies, not a stopwatch inside the guest. Beside it: the GPU work of the whole
session in the wait and in the interval between two presentations. **"GPU idle of this session" is said only when every queue's GPU
intervals are there** (every worker's, its uploads', wsd's; nothing lost, nothing committed and not seen done); else the line is "not
covered by this queue", with why. Other programs' GPU work is never seen. Then, after the fence: to wsd, to the display-link tick, in
`nextDrawable`, to commit, wsd's own GPU time, to the display.

`--passes`: the commonest frame by its encoders, and over all its frames what each stage the GPU wrote a time for took (in uptime,
by the two clocks of the recording; a time outside its command buffer's own GPU time, or left from an earlier encoder, is refused and
counted). Nominal traffic is not a measurement, and stages overlap: their union is given, never their sum.

`--cadence`: per plane of wsd (a window's base or overlay; a new one is a new plane), what its display link gave and what became of
what it received. A frame counts as shown only with a positive time, once, redisplays apart.

## Tests

- `tests/timeline/run-otl-test.sh`: the recorder (off, bounds, one budget, a full disk, a short write, an exit, a 65th recorder).
- `tests/timeline/test_otl.py`: the reader's joins, refusals, counts, cuts, clocks.
- `tests/timeline/samples_test.m` of dxmt (`run-samples-test.sh`): the encoders' GPU times with concurrent queues, queues ended and
  made again with work in flight, failures and exhaustion, under ThreadSanitizer.
- `tests/timeline/run-guest-probe.sh`: what the process that becomes the game is given.

## Owned workloads

- `tests/graphics/run-wsd-cadence.sh`, `run-low-power-session.sh`: what wsd shows of frames sent at a rate, full screen.
- `tests/graphics/run-pass-costs.sh` (`pass_costs.cpp`): Direct3D 11 frames through Wine, Neptune, the render server, DXMT.
- `tests/graphics/pass_bench.m`: what Metal alone takes for a pass by its load and store actions.
