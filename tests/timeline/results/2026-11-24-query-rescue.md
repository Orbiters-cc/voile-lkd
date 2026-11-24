# DXMT: a look at an event query flushes once, not at each look (`OBELISK_DXMT_QUERY_RESCUE=once`): 2026-11-24, 00:15 to 06:30 (no VRChat start)

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
