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
python3 tools/timeline/otl.py <folder of the start> [--from NS --to NS] [--plane ID|game] --passes --cadence [--csv out.csv] [--json out.json]
tools/timeline/real_session.py '<private instance link>' --plan 45 --series NAME ...   # the three real starts, for the owner (read its head first)
tools/timeline/score_series.py <folder of the series>       # what the three say, by the criteria below
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

What a look committed is judged by the event it was made for and the last event handed over before and after it, never by what the record
says of itself; a rescue's chunk must have been handed to the encoder, by it, and be the one its `End`'s marker is in (of the Ends recorded one by
one). What is owed to the rescue thread is followed from the record that it was accepted to the one that it was handed over, or that its context
ended: the highest that is outstanding, and for how long the oldest is. Looks of 0.5 ms and of 5 ms or more are counted.

`--cadence`: per plane of wsd (a window's base or overlay; a new one is a new plane), what its display link gave and what became of
what it received. A frame counts as shown only with a positive time, once, redisplays apart, **in the window (half open) that time is in, whenever its
callback ran; the rate is over the whole of the window**, and so are the gaps (to the first frame, from the last).

`--plane`: that plane's frames, and of the queues they were made on; a frame of those queues whose presentation is not told is one that is not whole. With a
window: whether it is recorded whole (`trace_not_complete`: roles, losses, recorders that ended), what the guest sent of the plane (`production`) and what a frame took (`work`).

## The A/B/A of `queries=once` (the owner's three starts)

It answers one question: at 45 %, in the same private instance, does DXMT's `queries=once` make VRChat's shown rate better, and is
nothing worse for it? Three starts, each said yes to by the owner beforehand; **A** baseline, **B** `queries=once`, **A** again:

```sh
L='vrchat://launch?...~private(usr_...)...'   # the same private instance for all three
tools/timeline/real_session.py "$L" --plan 45 --series aba-1
tools/timeline/real_session.py "$L" --plan 45 --series aba-1 --switch queries=once --nothing-wrong-seen
tools/timeline/real_session.py "$L" --plan 45 --series aba-1 --nothing-wrong-seen
tools/timeline/score_series.py ~/Library/Logs/Obelisk/timeline-sessions/aba-1
```

All three run one generation: A is the same DXMT with the switch unset, whose query paths are the released bodies
(`dxmt/tests/timeline/check-off-arm.py`). No earlier session is averaged in: the 45 % session of 2026-11-23 had no window in front.
The first two alone are a paired observation, not a result: the third is what tells the switch from the Mac getting warmer. Never a
replacement for a start that failed; **an anti-cheat warning, a crash, a loss of the picture or a hang ends the series** (the runner quits by session
and puts the release back; if it says it could not, recover with the line it prints, before anything is played, never by hand). What only an eye sees
the runner asks for: the second and third starts are made with `--nothing-wrong-seen` alone.

**B is the whole switch, not the rescue alone.** With it a command list's event and disjoint queries are signalled where they were ended in the list, at each of its
executions (unset: as the list begins), which is another meaning of them and other render passes around them. Where the game ends many queries in lists
(`one_by_one.in_lists`), what B gains or loses is the switch's as a whole until the two are told apart.

**How a start is made.** As Home of Orbiters - N4N0 makes it: `steam play 438100 --no-saved-arguments --render-percent 45 -- -screen-fullscreen 1 -window-mode borderless <link>`,
nothing that is saved for the game added, on the default profile. A computer that uses several VRChat profiles (a nonzero one on Home's choice) is refused, with why: which
profile Home would start is Home's to know, and a private place may not ride with a cold start there (`vrchat_launch::way`). So is a start while N4N0 makes one,
or in its wait after an early end; the runner holds N4N0's one slot for a start until the released generation is back. At most three starts in a series, at least 90 s after
the end of the last, the session quit by its own name, the released generation verified by every digest after each.

**The same for all three, settled before any result is looked at.** The same generation, developer's CLI, bench, reader, scale, tracing options, warm-up, windows and place (the runner
refuses a start of a series that has others; the place is kept as a salted hash), the same private instance with nobody else in it, account, viewpoint, avatar, window dimensions, display refresh, world
state and place; AC, brightness and display settings, `--passes 8`; the screen unlocked, VRChat in front, nobody at the Mac; no build, download, video or other agent's work.
Thermal pressure 0 at the start of each (the runner waits for nobody: it refuses) and the same course of it during them. Warm 120 s from the arrival, then three windows of 60 s. W1 is reported and decides nothing;
what is compared is **W2 with W2 and W3 with W3**, never an average over windows or starts. Settling may lengthen the warm-up: how long after the arrival each window really began is told (`warmup`).

**A start is inconclusive, and authorizes no other** (the runner's `judge()`; `result.json`'s `why_not`), when a window is not `valid` or VRChat was not in front, its ends are not stamped on the trace's clock, it is not
recorded whole (a role missing, records lost, a recorder that ended) or under **95 %** of its frames are whole; a role is missing in all or `foreign_images` is not empty; which plane is the
game's is not known; `queries.locked` is not `[true]` or `queries.once` is not the arm's; it was not on AC or the pressure is not known; one of the three pictures is missing; its session did not end as it was
asked to; pressure reached level 2 in one start alone; or, in B, the mechanism below fails. **A pair of windows is inconclusive** (the scorer) when the work is another (draws a frame more than 5 % apart, Ends of event and
disjoint queries a frame more than 10 %), the pressure is (level 2 in one alone), or an A has no redundant commit to take away. **A window in which the scene streams (textures or meshes still arriving) or in which the work is not the same says nothing of
performance**, whatever it shows: neither for B nor against it.

**The mechanism first** (`result.json`, each window's `queries_of_every_queue`; B against both As):

| | must be in B | A |
|---|---|---|
| `handed_over_and_committed` (a commit for a marker already handed over, by its watermarks) | **0** | above 0, or there is nothing for the switch to take away: inconclusive |
| `said_otherwise_than_its_watermarks` | **0** | **0** |
| `most_rescues_of_a_chunk` | at most **1** | |
| `left_not_handed_over` | **0** | |
| `rescues_whose_chunk_was_not_handed_over`, `rescues_of_a_chunk_something_else_committed`, `rescues_of_another_chunk_than_its_end_s` | **0** | |
| `debts`: `cancelled`; `oldest_outstanding_ns` at the window's end | **0**; under a second | |
| `debts.longest_ns`, `highest_outstanding`, `tries` (of looks and of the rescue thread, that could not hand over) | told | |
| `one_by_one.not_seen_though_looked_at_of_more_than_a_second` (an End looked at 65 times and never found; one that was ended again, or that nobody looked at, is told apart) | **0** | told |
| `tries.looks_of_5_ms_or_more` | at most **1** a window (0.5 ms and more: told) | told |
| `longest.rescue_ns`, `longest.look_ns` | told | told |
| `window`: `s_false` / (`ended` event + disjoint), `rescues`, put off for the lock / a full queue, uploads left to the rescue thread | told | told |
| `one_by_one.ns`: `issue_to_hand_over`, `issue_to_gpu_end`, `gpu_end_to_seen` p50, p95, p99 | told: no longer hand-over tail than A's | told |
| `commits` by reason; `splits`: encoders and cuts of the main colour target a frame | told | told |

No wall-clock bound is claimed of a look: what it takes of locks it takes by trying, and what macOS does with the thread is not bounded.

**Then the outcome**, of the game's plane and its queues alone (`shown_per_s`, `production`, `work`, `cadence`; W2 and W3): distinct shown frames a second (new serials with a positive presented time inside the window,
over its **whole stamped length**, the gaps at its ends included), the interval between them p50 / p95 / p99 and the largest gap, holds of three refreshes or more, frames replaced, zero times and redisplays;
the production interval (guest stamp to guest stamp) mean and p50; `fence_wait_ms`; client stamp to shown p50 / p95 / p99 (not input latency);
the GPU's union of work a frame and the gaps between ready, encode and GPU start (`--passes`, the CSV). (`hud_per_s` is the Metal HUD's, for the record: nothing is decided by it.)

**Pictures**: `compare_pictures.py` of the starts: the nine pairs of two starts beside the three within each. Flag B when its mean SSIM to the As is more
than 0.01 below the worse within-start mean, or its share of pixels more than 32 levels off is more than 1 point above it, or anything fixed (UI, geometry,
textures, black areas) is missing in two of its three. A repeatable defect of a static scene is a rejection whatever the numbers are; a
difference with no static region to compare is inconclusive.
And by eye, in all three starts: a texture that is black, or a mesh that is missing, for a frame when it first appears (arrival, avatars loading). The released stack has that (immutable resources: the results of
2026-11-24), the switch can make it more frequent, and the pictures are too late to show it. A higher rate beside missing content supports nothing; where a defect was seen on arrival alone, the matched, loaded scene after it is an observation of
steady timing and no more.

**What counts as a result** (`score_series.py`)
- **Provisional keep**: B beats **both** As in **both** W2 and W3: distinct shown rate over the whole window up by at least 2 % and by more than the two As differ from
  each other in that window, and mean production interval at least 0.5 ms shorter than both; the mechanism's column B as above; latency tails acceptable (below), pictures too.
  **Said separately: whether B sustained 40** distinct shown frames a second in both windows. (To ship it takes independent repeats in another
  order, not the three windows of one start counted as three: one B in the middle cannot be told from a cache of its own, another clock at the same pressure, or any drift that is not a line.)
- **Reject**: any failure of correctness, progress or the mechanism; shown rate more than 3 % below both As in W2 and W3; or shown p95/p99, or client stamp to
  shown p95, more than one refresh (16.7 ms) worse than both As beyond the As' own difference. A smaller worsening is said, not accepted in silence. (Found in the rehearsals of 2026-11-24: for a whole start
  wsd may have one drawable more on its way, 32.8 or 49.5 ms from its tick to the screen, with the switch and without. Where that part alone is half a refresh off, client stamp to shown is **inconclusive**: no rejection, and no keep.)
- **Inconclusive, leave it off**: everything between: mixed results, W2 and W3 disagreeing, effects below those bands, A without redundant commits, unmatched work or heat, a second
  A that could not be made.

## Tests

- `tests/timeline/run-otl-test.sh`: the recorder (off, bounds, one budget, a full disk, a short write, an exit, a 65th recorder).
- `tests/timeline/test_otl.py`: the reader's joins, refusals, counts, cuts, clocks, rates over a whole window, the mechanism by its watermarks.
- `tests/timeline/test_bench.py`: the bench's scoring, arrival and cleanup; the launch's arguments, profiles, slot and refusals (a program that answers as obelisk-cli does).
- `tests/timeline/test_session.py`: what authorizes a series' next start, what starts nothing, what three starts say.
- `tests/timeline/samples_test.m` of dxmt (`run-samples-test.sh`): the encoders' GPU times with concurrent queues, queues ended and
  made again with work in flight, failures and exhaustion, under ThreadSanitizer.
- `tests/timeline/run-guest-probe.sh`: what the process that becomes the game is given.

## Owned workloads

- `tests/graphics/run-wsd-cadence.sh`, `run-low-power-session.sh`: what wsd shows of frames sent at a rate, full screen.
- `tests/graphics/run-pass-costs.sh` (`pass_costs.cpp`): Direct3D 11 frames through Wine, Neptune, the render server, DXMT.
- `tests/graphics/run-query-client.sh` (`query_client.cpp`): queries, one promise at a time, with oracles (command lists' queries, looks beside
  streamed uploads and a held device lock among them); a randomised soak; `bench`: frames off screen at a fixed work, to compare two builds. No window.
- `tests/graphics/pass_bench.m`: what Metal alone takes for a pass by its load and store actions.
