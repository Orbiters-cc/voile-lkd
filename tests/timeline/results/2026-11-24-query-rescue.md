# DXMT: a look at an event query flushes once, not at each look (`OBELISK_DXMT_QUERY_RESCUE=once`): 2026-11-24, second round, 11:00 to 13:30 (no VRChat start)

After an independent review (verdict: no-go as built) of the first round, below. DXMT `aa13aa3` (first round: `ed73857`), Neptune `f78698a`, voile-lkd `bad17a2`; wsd, the
render server and the proxy's library byte for byte as in the first round's generation, DXMT alone is new: `59629c4e674dff21` -> `6b66e0f10cc63d03`. MacBook Air M3, macOS 27, AC.
**The screen was locked at first, then somebody's video played in Safari: no window was put over it, so nothing here is of frames shown.** The client draws off screen (no window),
natively on libdxmt-native and through the whole chain. Pressure 0 to 2 (said per table), the load of the rest of the Mac 1.4 to 5.5.

## What was wrong, and what is now

| the review | now |
|---|---|
| OFF was not the measured code: its stall flush had lost the device's lock (since `30a5086`) | the immediate and deferred contexts, the event queries, the device's lock, the queue's commit and the initializer's flush are the **text of `4e3a952`**, checked by `dxmt/tests/timeline/check-off-arm.py` (21 comparisons, all the same; the only differences it allows are two access specifiers, and in the contexts' shared base class the timeline's arguments). The switch, and the timeline, are other classes, chosen once as the device is made. `4e3a952` is the released `b7d97ee` with the recorder's first two commits. (One member of the initializer, its sequence number, became atomic, so that a rescue can read it.) |
| a rescue could wait for the uploads' queue | it does not: the chunk is committed at once with the id of the uploads it waits for on the GPU, and a thread of the context's commits them. Nor for the device's lock or a full queue: what was put off for them that thread does, whether or not anybody looks again |
| a list's event or disjoint query is there before its work | with the switch it is signalled where it was ended in the list, at each execution. Unset: as it was (told, not touched) |
| counters only | each query, sampled; windows of looks, `S_FALSE` and rescues; the same in both arms, recorded around what they do |

## OFF is `4e3a952`

Both built here, the same flags; the switch unset. Off screen, 12 passes, two event queries and a copy a frame, the engine waiting for the event of three frames ago; a thread looks every 100 us under a lock
of its own with the device's lock on, as Neptune's host does. `gated`: as fast as that goes; `busy`: 6 ms of CPU work spread over the recording; `rings`: two lookers more, one of them flushing now and then;
`lists`: half of it in a command list.

| natively, no recorder, 6 rounds in turn, 9 s of rest before each, pressure 0 | `4e3a952` fps | OFF fps | paired | `once` fps | paired |
|---|---|---|---|---|---|
| gated | 125.99 (125.7-127.0) | 126.00 (125.4-126.8) | -0.06 % (-1.2 to +0.3) | 126.68 | +0.07 % |
| busy | 120.72 (119.5-123.4) | 120.34 (119.9-121.2) | +0.03 % (-2.8 to +0.5) | 125.91 | **+4.42 %** (+2.5 to +4.7) |
| rings | 126.67 (125.2-126.8) | 125.88 (125.4-126.8) | -0.33 % (-1.0 to +0.8) | 125.28 | -0.94 % |
| lists | 126.20 (125.1-128.0) | 125.47 (125.1-127.7) | -0.06 % (-2.2 to +0.9) | 126.15 | -0.42 % |

Frame p50 `4e3a952` / OFF: 7.862 / 7.861, 8.155 / 8.158, 7.872 / 7.873, 7.889 / 7.885 ms. A hot set before it (8 rounds, no rest, pressure to 2, 81 to 128 fps): OFF to `4e3a952` +0.43, -0.10, -0.01, +0.12 %, rounds between
-6 and +6 %. All pictures identical in the 72 and 96 runs.

| per frame, every encoder recorded | `4e3a952`: command buffers, render passes | OFF | `once` |
|---|---|---|---|
| natively (3 runs): gated | 2.04 (2.01-2.08), 5.05 | 2.03 (2.00-2.08), 5.03 | 2.00, 4.99 |
| busy | 13.22 (13.16-13.35), 13.30 | 13.19 (13.00-13.47), 13.24 | 2.00, 5.00 |
| rings | 2.29 (2.23-2.39), 5.38 | 2.24 (2.21-2.29), 5.33 | 2.00, 4.99 |
| lists | 1.99, 4.97 | 2.02, 4.99 | 1.99, 6.98 |
| through the render server (3 runs; rings 8 and 8): gated | 3.34 (3.31-3.38), 6.69 | 3.38 (3.32-3.47), 6.78 | 2.00, 5.00 |
| busy | 14.89 (14.81-15.02), 14.92 | 14.85 (14.83-14.89), 14.92 | 2.00, 4.99 |
| rings | 3.40 (3.34-3.47), 6.80 | 3.44 (3.34-3.61), 6.88 | 1.99, 4.98 |
| lists | 3.20 (3.16-3.27), 5.75 | 3.17 (3.15-3.20), 5.76 | 2.00, 6.98 |

Blits 1.00 a frame in all. (The two passes more of `lists` with the switch are its event's place in the middle of the list, and the one before it. How many stall flushes there are depends on when the looks fall, hence the spreads.) Through the server, with the recorder: 125.9 / 125.6, 120.6 / 120.7, 125.6 / 122.7, 126.2 / 125.7 fps
`4e3a952` / OFF; in two of OFF's eight `rings` runs (107.3 and 121.9) something else ran: the other six are 124.98 to 125.66 (`4e3a952`: 124.95 to 125.96). `once` 126.6, 126.4, 126.6, 126.0.

## The rescue's bound

`query_client cases uploads`: another thread makes textures with their data all the time (to 64 MiB each), the GPU is busy, this thread ends 60 events and only looks; with the device's lock and without.
6 rounds in turn, pressure 0 to 2, looks with DONOTFLUSH (all of them; the 65th is the one that commits):

| | looks | the longest, of any | of 0.5 ms or more | an event was there after (p50 of the rounds; the rounds' longest) |
|---|---|---|---|---|
| `4e3a952` | 422,320 | 5.94 ms (the runs' median 4.1 to 4.8) | 255 (in a run that says which: 65 of 65 the 65th) | 54 ms; 56 to 91 |
| `once` | 425,017 | **0.102 ms** | **0** | 54 ms; 61 to 96 |

The look that commits (`once`, 1,440 of them in another 12 runs beside a load of 5): p50 0.006 to 0.015 ms, the longest **0.143 ms**; looks of 0.5 ms or more were 7 of some 1.1 million there, none of them one that commits (a thread
that lost its core). `ed73857` with the switch: 3.4 to 9.9 ms, 19 to 36 of 60. Through the render server, all cases: the longest rescue on a looking thread 0.026 ms, in the soak 0.051 ms; 178 rescues left their uploads to
the thread, and what had been uploaded was seen. The bound is by construction, not by the clock: a try of the device's lock, a look at a counter, a try of the initializer's lock, then the commit's own queueing. What macOS does with the thread is not bounded.

With the device's lock held by another thread, uploads pending, or a queue full of work that waits for a Signal of the looking thread itself (where `4e3a952` waits for good), no look takes more than 0.02 ms, and the event is there 60 ms later
**without another look** (`owed`: 12 + 3 rounds; `ed73857` fails 8 of them).

A first version of this round put the rescue off while uploads were pending. Its events came 188 ms late (p50) beside streamed uploads: seen by `uploads`, replaced.

## Command lists

`list-events`: lists whose event or disjoint query follows 40 to 120 ms of GPU work, two in a list, twice in one, executed again and again, twice in a row, held by a GPU wait, 400 lists with a query each. With the switch: each there when its
work is, 39 checks of 39, natively; the first of two in a list does not wait for the second's work (4.9 of 128 ms). Unset, as `4e3a952`: 14 of 14 of these early (0.0 ms for 120 ms of work); told as KNOWN, and nothing hangs.
Not changed with the switch: a **timestamp** ended in a list is sampled as the list begins; **`Begin` of a disjoint query** does nothing (a read between a new `Begin` and its `End` sees the former pair).
Through Neptune a list's query is published to nobody: the guest asks itself, 50 ms after its first look at the earliest (both arms; 58 ms here for what was there at once).

A list's marker first made up to seven occlusion results in 40,000 wrong (soak, natively; unset none): it took away the signal before the list, and what the list drew was put together with the pass before it. **That is the cause of the wrong occlusion counts of the first round,
in both arms: DXMT joins render passes of the same targets by joining their commands, and the first one's visibility mode, if an occlusion query was open or just ended in it, counts the second one's draws too**
(`dxmt_context.cpp`, where `use_visibility_result` is joined; nothing sets the mode back at a pass's end). With the switch the signal before a list is there as without it. The joining itself is not touched: it is in the released DXMT.

## Checks

- `query_client cases`: natively 208 of 208 unset (twice), 272 of 272 with the switch (twice); through the render server 180 of 180 unset (11 KNOWN), 191 of 191 with it. The pictures' hashes are the same in both arms (but `uploads.1` through the
  render server: the immutable textures below), and `4e3a952`'s as OFF's.
- The recordings of all cases through the render server: with the switch 281 rescues, at most one a chunk, **0** commits for a marker that was handed over (unset: 1,754), 0 left; nothing lost.
- Soaks: natively 8 seeds of 40,000 an arm: 0 wrong. Through the render server 120,000 an arm recorded: 0 wrong, 354 rescues, hashes identical. Long, not recorded, 1,400,000 each: seed 101 with the switch 0 wrong, 102 1 wrong, 101 unset 1 wrong;
  both the known kind (an occlusion query in a list executed twice; the first round: 4 in 5.6 million and 2 in 1.4 million); no event, disjoint or timestamp result wrong, no hang, 560 hashes of seed 101 identical in the two arms. `pending`: both.
- ThreadSanitizer (libdxmt-native and the client; not in the first round): `list-events uploads host-threads owed two-threads teardown covered pacing` and `bench rings`, the recorder off and on: with the switch 0 reports, 0, 0 and 1 (the historical
  `event_stall++` of a look that may flush, outside the lock: a statistic). Unset 27 (the queries' own state, as released). `soak`: occlusion and timestamp read-backs, both arms.
- The reader 37 of 37, `test_bench` 24 of 24, the recorder (`run-otl-test.sh`), the samples (0 reports), the guest probe (7 of 7 identical), the Obelisk fork's `game-runtime` 1100 of 1100 and `obelisk-cli` 63 of 63 (a first run, beside a render server of these tests, failed one
  of the 1100: a library test that refuses while anything of an engine runs), its script tests 5 of 5, Neptune's resource update test.
- The generation: 10,238 entries of both; every guest group identical (`comparison.json`, the rest `0a954bfbe6fc2b68`, the same as the first round's).
- The runner, nothing started: its checks, the generation in, every digest, out, every digest, three times (unset, `queries=once`, unset) in a temporary library; on the owner's library its checks and digests alone: no problem, and every one of the released
  10,238 entries is there (and nothing else but two lock files).

## Not covered, or not known

- **No window, no fps shown, no rehearsal with the client on the screen** (the video). The first round's windowed tables are of `ed73857`'s two arms; that its OFF had no lock does not change what they say of `once`, and OFF's rows are not `4e3a952`'s.
- VRChat. A device lost; a command buffer that fails. An application that takes `SetMultithreadProtected` back while a rescue is owed (nobody here does).
- A thread that keeps the device's lock while it waits for a query only another thread looks at is never rescued (unset, the looking thread waits for that lock too).
- **Immutable resources (both arms, released): a texture made immutable with its data, through Neptune, is made without them and updated, and DXMT does not order an immutable texture's update with the draws that read it: drawn black when first used
  in the same frame.** Found here by a look at pixels: 1,000 to 3,300 of some 29,000 wrong unset (`4e3a952` the same), **3,700 to 9,100 with the switch** beside streamed uploads (5 runs each): fewer command buffers are in between. Natively, where
  the data come with the texture: none. With `D3D11_USAGE_DEFAULT`: none, in any arm. Not touched (the fix is Neptune's host or DXMT's, and changes the released behaviour); but **it can make the switch show a black texture or a missing mesh for a frame
  more often than today**: look for it in the A/B/A, whose pictures are taken later than that.
- The Windows build of this DXMT was not made.

# The first round: 00:15 to 06:30 (`ed73857`)

MacBook Air M3, macOS 27, 2940 x 1912, 60 Hz, AC, Low Power Mode off, screen unlocked, nobody at it (idle more than a minute before each visible run). Another agent
compiled now and then: a run beside which a compiler was seen in any second was thrown away and made again (said in the logs); the load of the rest of the
Mac (40 to 110 % of a core, once 190, once 280 before a run), `pmset -g therm` (nothing recorded, ever) and macOS's thermal pressure are in each run's `conditions.txt`.
Binaries: the timeline generation of this day: DXMT `ed73857`, Neptune `7179ac6`, wsd and the render server byte for byte as in the generation before. Both arms are one build:
the switch is a variable of the render server.

## Frames a second, owned client through the whole chain, no recorder, off and once in turn, 35 s of rest and pressure 0 before each run

Median (least to most) of the rounds; paired: the median of the rounds' own differences.

| 2940 x 1912 (5 rounds) | off | once | paired |
|---|---|---|---|
| nothing | 46.6 (45.9-46.6) | 46.5 (46.5-46.7) | +0.2 % |
| **one event query a frame** | 35.6 (35.5-35.7) | **46.5 (46.3-46.5)** | **+30.4 %** (29.6 to 31.0) |
| **event query mid-scene** | 34.6 (34.4-34.7) | **39.5 (39.3-39.5)** | **+14.3 %** (13.3 to 14.9) |
| four timestamps | 35.2 (35.0-35.3) | 35.3 (35.3-35.3) | +0.3 % |
| four occlusion queries, targets drawn between | 35.3 (35.1-35.3) | 35.3 (35.3-35.3) | +0.1 % |
| *(3 rounds)* disjoint pair a frame | 35.9 (35.6-36.0) | **46.5 (46.5-46.8)** | +30.3 % |
| event query and four `GetData(0)` | 34.0 (34.0-34.3) | 35.2 (35.2-35.4) | +3.7 % |
| four occlusion queries, no targets between | 46.9 (46.8-47.2) | 47.4 (47.4-47.4) | +1.1 % |
| a readback; a `Flush`, mid-scene | 39.2; 39.2 | 39.5; 39.6 | +0.9 %; +1.0 % |

| 58 % (4 rounds) | off | once | paired | 45 % (5 rounds) | off | once | paired |
|---|---|---|---|---|---|---|---|
| nothing | 135.5 | 135.1 | -0.5 % | | 224.1 | 223.4 | +0.3 % |
| one event query a frame | 128.7 (123.0-131.7) | 135.4 (132.4-136.6) | **+5.5 %** | | 226.1 | 223.9 | -1.0 % |
| event query mid-scene | 101.2 (100.1-101.8) | 113.7 (110.9-114.5) | **+12.2 %** | | 187.2 | 185.8 | -0.3 % |
| four timestamps | 102.0 | 100.7 | -1.4 % (-2.7 to +0.8) | | 169.0 | 167.9 | -0.6 % |
| four occlusion queries | 100.4 | 100.4 | 0.0 % | | 164.6 | 163.6 | -0.5 % |

At 45 % this client's frame is over in 4.4 ms of GPU: an event is there before the 65th look, nothing is there to take away, and the five rows are within their noise (1 to 2 %).
A hot first set at 100 % without rest (6 rounds, pressure 0 to 2, a run's modes one behind the other): event +27.9 %, mid-scene +15.6 %, the others -2.3 to -1.0 % with rounds
between -12 and +18 %: kept in the logs, for nothing but to say that the size of it holds when the Mac is hot.

**A slow recording** (8, 16, 30 ms of the CPU's own work spread over the 266 draws, with an event query a frame and without). It was the question whether the needless flushes are of use, as they
submit what is recorded before the frame is: they are not.

| | 100 % (4 rounds): off | once | paired | 58 % (3 rounds): off | once | paired |
|---|---|---|---|---|---|---|
| 8 ms, no query | 46.3 | 46.1 | +0.1 % | 119.0 | 119.2 | +0.2 % |
| **8 ms, event query** | 32.6 (30.1-32.9) | **45.8 (45.7-46.3)** | **+41.0 %** | 94.0 (91.2-94.3) | **119.3** | **+26.9 %** |
| 16 ms, no query | 46.0 | 45.8 | 0.0 % | 61.5 | 61.3 | -0.3 % |
| **16 ms, event query** | 29.6 (28.9-29.7) | **45.6 (44.9-46.2)** | **+55.2 %** | 61.2 | 61.2 | 0.0 % |
| 30 ms, no query | 32.9 | 32.9 | -0.1 % | 33.0 | 33.0 | 0.0 % |
| **30 ms, event query** | 24.3 (24.0-24.4) | **32.9** | **+35.0 %** | 31.5 (31.1-31.8) | **33.0** | **+4.7 %** |

(A first set of it at 100 % ran beside another program at four cores and is thrown away, kept as `slow-100-disturbed`. In this one Steam's own client took one core in five of the eight runs, in both arms.)

## What cuts the main colour target's passes, every frame's encoders recorded, 2940 x 1912 (two recordings an arm; 0 records lost)

| a frame | off: command buffers, encoders of the target, cuts | by what | once | by what |
|---|---|---|---|---|
| nothing | 1.0, 1.0, 0 | | 1.0, 1.0, 0 | |
| event query a frame | 4.5 to 4.7, 3.6, **2.6** | the stall flush 2.55 to 2.66 | 2.0, 1.0, **0.01** | a render pass that needs it, once |
| event query mid-scene | 4.6 to 4.9, 4.6 to 4.8, **3.6 to 3.8** | the stall flush 2.6 to 2.9, the `End` 1.0 | 2.0, 2.0, **1.0** | the `End` 1.0 |
| four timestamps | 1.0, 5.0, 4.0 | a timestamp 4.0 | 1.0, 5.0, 4.0 | a timestamp 4.0 |
| four occlusion queries | 5.0, 5.0, 4.0 | `End` of an occlusion query, at the next target 4.0 | 5.0, 5.0, 4.0 | the same 4.0 |
| disjoint pair | 4.6, 3.6, **2.6** | the stall flush 2.6 | 2.0, 1.0, **0** | |
| event query, four `GetData(0)` | 5.8, 4.8, 3.8 | the stall flush 2.9, `Flush` 0.9 | 3.0, 2.0, 0.95 | `Flush` 0.95 (the guest driver's, one a query cycle) |
| occlusion alone; readback; `Flush` | 1.0; 1.0; 1.0 | | 1.0; 1.0; 1.0 | as off |

Command buffers committed by a look although the query's chunk had been handed over: off 2.6 to 3.0 a frame in the event cases (1,465 in the recordings), **once 0 in every case, of every client, in
every recording** (games' shapes, cases, soaks). Once made no rescue at all in these frames: `Present` hands the chunk over first. The device's lock was on in the render server in every one
(`OTL_D_QUERIES`). GPU work of the session a frame, event case: 28.8 ms off, 22.0 once; client stamp to shown p50 / p95 / p99: 42.4 / 52.8 / 55.5 off, 41.2 / 48.8 / 49.4 once.

## `query_client` (no window): cases, hashes, soaks

- Cases: through the render server 146 checks, 0 failed, off and once; on libdxmt-native itself 176, 0 failed, off and once (every look the application's own, and 20,000 Ends beside three looking
  threads as Neptune has them). The pictures of every case are compared with one the CPU drew, and their hashes are identical off and once: 27 through the render server, 31 natively.
- No look at all but `GetData(DONOTFLUSH)`, no `Present`, no `Flush`: there (after a draw, a clear, a copy, nothing; a disjoint pair; three Ends of one moment; with draws recorded after it; no data).
- Natively, counted: 60 to 64 looks and nothing is submitted; the 65th submits it. The same off and once.
- Handed over, GPU busy, application recording and looking: off 131 to 248 commits for nothing in the case, once 0. Unsubmitted: at most one rescue a chunk, everywhere; none left unsubmitted.
- A query before a GPU wait that only its own result lets go is there; one after it is not, in 400,000 looks of 150 ms, until it is let go, then in 0.6 ms (`Wait` of a fence of a second device).
- Deferred contexts (executed once, twice, not at all), reuse, occlusion (exact sample counts: nothing, drawn, hidden, across targets, across a Flush and an event, 2x, 32 in a chunk), predicates'
  results, timestamps in order, disjoint data, readbacks, two threads taking turns, devices let go of and a process ended with queries pending (the longest 0.1 ms through the render server, 29 ms natively).
- Soaks (a seed draws the same whatever the timing): natively 8 seeds x 40,000 an arm; through the render server 120,000 an arm recorded (once: 323 rescues, at most one a chunk, 0 for nothing; off: 324 and
  49 for nothing), 48 hashes identical.
- The long one, through the render server, not recorded, a watchdog of 20 s: seeds 101 to 104 of 1,400,000 Ends with once (5.6 million, 6.6 thousand million looks, 40 minutes) and seed 101 off: no hang, no
  watchdog, no event, disjoint or timestamp result wrong, the pictures the CPU's throughout, 560 hashes of seed 101 identical. **Wrong: six occlusion results, four of once's 5.6 million and two of off's 1.4
  million**, every one of a query ended in a command list and executed (below): the defect is there without the switch, and oftener.

## What this stack does wrong, with the switch and without (not touched)

- An occlusion query whose draws are on two targets is counted wrong about once in 2,500 (a part missing, or a number from memory nobody wrote: 1642374019153920 of 3726): `soak <seed> <n> wide`.
  In a command list on one target it is too, once in some thousand lists (`list executed`, the six above; 139633681760256 of 585).
  Release/acquire on the readback's own sequence number changed nothing. Worth a look of its own: it is culling.
- `SetPredication` is ignored (known). A timestamp is its command buffer's end: four in one buffer are the same (known, the fork's own choice).
- A device let go of while its pipelines compile, or before its last chunk is encoded, ends libdxmt-native (natively; through the render server not seen).
- No keyed mutex: the native build has none, and the guest refuses to share one (`E_INVALIDARG`): `AcquireSync`'s wait cannot be reached.

## Not covered

VRChat (no start). What of this is in its frames is not known: its recordings have the wall at 100 us but no reasons. Clean and coalesced Ends, and which of reason 13 is the event's, are told by
`OTL_D_QUERIES` from now on. A device lost, a command buffer that fails. ThreadSanitizer. Queries of a device the render server was not told to protect (every one is).
