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

`real_session.py` takes pictures of the game's window alone, 100 s after the arrival (`window_picture.m`, built by `build-window-picture.sh`); `compare_pictures.py <start>
<start>` tells what differs between two starts from what moves by itself in each.

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

`--queries`: what the looks at event queries flushed, whether anything was owed, and every commit by its reason. Per window (what is
between `--from` and `--to`; the counts are told at each Signal, and by a look 200 ms after the last, so a window's ends are that exact)
the looks at event and disjoint queries, the `S_FALSE` and `S_OK` answers, the rescues and why one was put off, the longest look and the
longest rescue on a looking thread; `per_second` in the JSON. And one by one, for a sample of the Ends (at most 128 in any 100 ms of a
render server worker): issue, first look, hand-over of its chunk, rescue, the GPU's end of its chunk, the last look that did not
find it and the first that did, looks until then; joined by the query's own id and which of its Ends it is, and by queue and chunk.
*Signalled* is known from the looks alone: after the one, before the other. A clean End (nothing new recorded: an older marker) has no chunk of
its own, so no hand-over is said of it. Both arms are recorded alike, around what they do, never in it. The looks are the **host's**
(the render server's, every 100 us): how often Unity looks in the guest, or how long it waits there, is in none of these numbers.

`--cadence`: per plane of wsd (a window's base or overlay; a new one is a new plane), what its display link gave and what became of
what it received. A frame counts as shown only with a positive time, once, redisplays apart.

## The A/B/A of `queries=once` (the owner's three starts)

It answers one question: at 45 %, in the same private instance, does DXMT's `queries=once` make VRChat's shown rate better, and is
nothing worse for it? Three starts, each said yes to by the owner beforehand; **A** baseline, **B** `queries=once`, **A** again:

```sh
L='vrchat://launch?...~private(usr_...)...'   # the same private instance for all three
tools/timeline/real_session.py "$L" --plan 45
tools/timeline/real_session.py "$L" --plan 45 --switch queries=once
tools/timeline/real_session.py "$L" --plan 45
```

All three run one generation: A is the same DXMT with the switch unset, whose query paths are the released bodies
(`dxmt/tests/timeline/check-off-arm.py`). No earlier session is averaged in: the 45 % session of 2026-11-23 had no window in front.
The first two alone are a paired observation, not a result: the third is what tells the switch from the Mac getting warmer. Never a
replacement for a start that failed; **an anti-cheat warning, a crash, a loss of the picture or a hang ends the series** (the runner quits by session
and puts the release back; if it says it could not, recover with the line it prints, before anything is played, never by hand).

**The same for all three, settled before any result is looked at.** The same generation (`manifest.json`: `generation`, `cli`, `bench_sha256`
equal in the three), 45 %, the same private instance with nobody else in it, account, avatar, camera, world state and place; AC, brightness and
display settings, `--passes 8`; the screen unlocked, VRChat in front, nobody at the Mac; no build, download, video or other agent's work.
The same thermal pressure at the start of each (`notifyutil -g com.apple.system.thermalpressurelevel` as in `conditions.jsonl`; 0, and
wait for it) and at least 90 s since the last start ended (the runner's own gate). Warm 120 s from the arrival, then three windows of 60 s.
W1 is reported and decides nothing; what is compared is **W2 with W2 and W3 with W3**.

**A start is inconclusive** (not a result either way, and said so) when a window is not `valid` or VRChat was not in front; pressure changed in one
arm alone (level 2 above all); a role is missing or `foreign_images` is not empty; records were `lost` in a window, or under 95 % of its
frames are whole; the workload is another (`ended` events a frame, draws, command buffers of an unaffected kind); `queries.locked` is not
`[true]` (the device's lock was not on: B's rescue then excludes nobody) or `queries.once` is not the arm's; no matching pictures.

**The mechanism first** (`result.json`, each window's `queries`; B against both As):

| | must be in B | A |
|---|---|---|
| `handed_over_and_committed` (a commit for a marker already handed over) | **0** | above 0, or there is nothing for the switch to take away: say so and stop reading the outcome as its work |
| `most_rescues_of_a_chunk` | at most **1** | |
| `left_not_handed_over` | **0** | |
| `one_by_one.not_seen`: not seen by the end of the recording | none older than the window's last second | the same |
| `longest.rescue_ns`, `longest.look_ns` | under 0.5 ms typically; a look over 5 ms is looked into, more than one a window is a failure of the bound | told |
| `window`: `s_false` / (`ended` event + disjoint), `rescues`, put off for the lock / a full queue, uploads left to the rescue thread | told | told |
| `one_by_one.ns`: `issue_to_hand_over`, `issue_to_gpu_end`, `gpu_end_to_seen` p50, p95, p99 | told: no longer hand-over tail than A's | told |
| `commits` by reason; `splits`: encoders and cuts of the main colour target a frame | told | told |

**Then the outcome**, of the game's plane (`cadence`, W2 and W3): distinct shown frames a second (new serials with a positive presented time, over the whole window), the
interval between them p50 / p95 / p99 and the largest gap, holds of three refreshes or more, frames replaced, zero times and redisplays;
the production interval (guest stamp to guest stamp) mean and p50; `fence_wait_ms`; client stamp to shown p50 / p95 / p99 (not input latency);
the GPU's union of work a frame and the gaps between ready, encode and GPU start (`--passes`, the CSV).

**Pictures**: `compare_pictures.py` of the starts: the nine pairs of two starts beside the three within each. Flag B when its mean SSIM to the As is more
than 0.01 below the worse within-start mean, or its share of pixels more than 32 levels off is more than 1 point above it, or anything fixed (UI, geometry,
textures, black areas) is missing in two of its three. A repeatable defect of a static scene is a rejection whatever the numbers are; a
difference with no static region to compare is inconclusive.

**What counts as a result**
- **Provisional keep**: B beats **both** As in W2 and in W3: distinct shown rate up by at least 2 % and by more than the two As differ from
  each other in that window, mean production interval at least 0.5 ms shorter; the mechanism's column B as above; nothing of latency, gaps or pictures
  materially worse. Said separately: whether both of B's windows hold 40 distinct shown frames a second. (To ship it takes independent repeats in another
  order, not the three windows of one start counted as three.)
- **Reject**: any failure of correctness, progress or the mechanism; shown rate more than 3 % below both As in W2 and W3; or shown p95/p99, or client stamp to
  shown p95, more than one refresh (16.7 ms) worse than both As beyond the As' own difference. A smaller worsening in both windows is said, not accepted in silence.
- **Inconclusive, leave it off**: everything between: below those bands, W2 and W3 disagreeing, A without redundant commits, unmatched heat, a second
  A that could not be made.

## Tests

- `tests/timeline/run-otl-test.sh`: the recorder (off, bounds, one budget, a full disk, a short write, an exit, a 65th recorder).
- `tests/timeline/test_otl.py`: the reader's joins, refusals, counts, cuts, clocks.
- `tests/timeline/samples_test.m` of dxmt (`run-samples-test.sh`): the encoders' GPU times with concurrent queues, queues ended and
  made again with work in flight, failures and exhaustion, under ThreadSanitizer.
- `tests/timeline/run-guest-probe.sh`: what the process that becomes the game is given.

## Owned workloads

- `tests/graphics/run-wsd-cadence.sh`, `run-low-power-session.sh`: what wsd shows of frames sent at a rate, full screen.
- `tests/graphics/run-pass-costs.sh` (`pass_costs.cpp`): Direct3D 11 frames through Wine, Neptune, the render server, DXMT.
- `tests/graphics/run-query-client.sh` (`query_client.cpp`): queries, one promise at a time, with oracles (command lists' queries, looks beside
  streamed uploads and a held device lock among them); a randomised soak; `bench`: frames off screen at a fixed work, to compare two builds. No window.
- `tests/graphics/pass_bench.m`: what Metal alone takes for a pass by its load and store actions.
