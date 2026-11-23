# Host timeline

Where the time of a frame goes, between the render server's ring, DXMT, the GPU and wsd: the parts of the guest's "fence
wait" (its log line `neptune unixlib wsi (wsd): ... fence wait avg`) and what follows it, per frame.

**Off by default.** On when `OBELISK_TIMELINE` names a folder in the environment of wsd, `virgl_test_server` and
`virgl_render_server`. The game's process is never given it: `launch.sh` takes it away before the game starts (Obelisk,
branch `perf-timeline`), and the guest starts with an empty environment anyway. Off, the recorder (`wsd/otl.h`, the same
file in `neptune` as `virglrenderer/src/neptune/otl.h` and in `dxmt` as `src/util/otl.h`) is one `getenv()` per process and
one branch at each site: no thread, file, descriptor or memory (`tests/timeline/run-otl-test.sh` checks it).

| Variable | |
|---|---|
| `OBELISK_TIMELINE=<folder>` | on. `launch.sh` makes a folder of the start in it, `<date>-<time>-<pid>`, with `otl-npt-<pid>.bin` and `otl-dxmt-<pid>.bin` (one render server worker), `otl-vtest-<pid>.bin`, `otl-wsd-<pid>.bin` |
| `OBELISK_TIMELINE_MB=<n>` | each file's cap (256); past it only a summary every 10 s is written, with the count of records lost |
| `OBELISK_TIMELINE_PASSES=1` | also GPU timestamps at the stage boundaries of every encoder of DXMT (they become part of what Metal runs, so its times are for the split between passes, not for a total) |

```sh
# with obelisk-cli of the branch perf-timeline (its engine files must be the instrumented ones):
mkdir -p ~/Library/Logs/Obelisk/timeline
OBELISK_TIMELINE=~/Library/Logs/Obelisk/timeline obelisk-cli steam play <appid>
python3 tools/timeline/otl.py ~/Library/Logs/Obelisk/timeline/<start> --passes --cadence [--frames 20] [--csv out.csv]
```

## What it prints

The fence wait of a frame runs from the guest's stopwatch (as the host sees it: the later of the output fence's arrival and
the frame before's post-fence stamp) to the post-fence stamp the guest sends wsd. Its parts follow each other and sum to it;
what was over before the stopwatch began counts nothing: replay tail (the ring has not decoded the presentation yet), encode
queue, encode, pipeline wait, queue to GPU start, GPU execution, GPU end to notify (Metal's shared-event listener), notify to
retire, retire to vtest, vtest to guest wake. Beside it: how much of the wait, and of the interval between two frames, the GPU
was running this queue (`GPU idle per interval` is what overlapping more work could gain), decode, encode and pipeline time of
the frame. `GPU start to end` of one command buffer counts the neighbours it overlaps with: never add it up. Then, after the
fence: to wsd, to the display-link tick, in `nextDrawable`, to commit, wsd's own GPU time, to the display.

How the records are joined is at the top of `otl.py`; every frame of the owned workloads joined end to end.

## Owned workloads

- `tests/graphics/run-wsd-cadence.sh`, `run-low-power-session.sh`: what wsd shows of frames sent at a rate, full screen.
- `tests/graphics/run-pass-costs.sh` (`pass_costs.cpp`): Direct3D 11 frames through Wine, Neptune, the render server, DXMT.
- `tests/graphics/pass_bench.m`: what Metal alone takes for a pass by its load and store actions.
