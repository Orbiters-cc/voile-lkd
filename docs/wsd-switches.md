# The window server's developer switches

Two variables of `wsd`'s environment (and, below, two of the render server's), all unset in every release and for every player. Unset, `wsd` does exactly what it did without
them: the same drawables, the same shader, the same calls, nothing more loaded (MetalFX is never linked). `launch.sh` of the developer's
obelisk-cli (Obelisk, branch `perf-timeline`, feature `developer-timeline`) takes them out of the environment, whoever set them, and
gives them to `wsd` alone; no other engine file and nothing of the emulated game knows them.

## `OBELISK_WSD_UPSCALE=metalfx`

A frame smaller than its window's pixels on both axes (at most 95 % of them) is scaled by `MTLFXSpatialScaler` (perceptual: the
client's pixels are sRGB-encoded UNORM, the layer is tagged sRGB, nothing is converted) to the window's backing pixels, and the
drawable has that size; without it the drawable has the frame's size and macOS stretches it (bilinear). `wsd/wsd_upscale.h`.

| What | With it |
|---|---|
| A frame as large as the window (100 %) | today's draw, pixel for pixel: no scaler is made |
| The scaler is not there yet (its size must have held for 8 frames; it is made off the main thread, 190 ms the first time), MetalFX or the size is not supported | today's draw |
| Pointer mapping (`-pointerScale`, `warp_point`, clip, relative) | unchanged: it goes by the client's buffer and the view, never by the drawable |
| What the clients hear (HELLO, RESIZE, FRAME, DISPLAY; the 640 x 480 least desktop) | unchanged: by `scale_at()` alone |
| The base plane, and a game's overlay plane | each plane by its own size in points times its window's backing scale; a plane of at least 640 x 480 pixels only |
| `PRESENT_REGION` rectangles | unchanged: the layer's frame; the scaler's output follows its size |
| Resizing, a display mode, full screen on or off | another size has no scaler until it held for 8 frames: today's draw meanwhile |
| A second display | the backing scale of the display the window is on, looked up at each draw; a frame that is not smaller there is drawn as today |
| A capture of the window (`screencapture -l`, the N4N0 bridge) | the window's backing pixels, as before: macOS composes the window whatever its drawable's size |
| Buffer lifetime | the client's buffer is released when the command buffer completed, as before: later by the scaler's time |
| Memory | three drawables and one private texture of the window's pixels: 90 MB at 2940 x 1912 against 14 MB of drawables at 45 % |
| RGBA8, BGRA8, RGB10A2 | read as they are (MetalFX reads the client's linear memory itself) |

## `OBELISK_WSD_PRESENT=<list>`

Any of, separated by commas:

- `arrival`: a frame is drawn and presented as it arrives, as long as a drawable is sure to be free (one on the screen, the others on
  their way to it); else the next display-link tick takes it, as without it. The mailbox, the occlusion rules and the releases stay.
- `attime`: presented with `presentDrawable:atTime:` for the next refresh the display link names.
- `nosync`: `displaySyncEnabled` off. `two`: two drawables instead of three. For measurements.

What each gives: `tests/timeline/results/2026-11-23-switches.md`.

## `OBELISK_DXMT_QUERY_RESCUE=once` (the render server's)

Not `wsd`'s: DXMT's (branch `perf-timeline`, `src/d3d11/d3d11_query_rescue.hpp` and the end of `d3d11_context_imm.cpp`), given by the same `launch.sh` to the
render server alone. Unset, DXMT's query paths are the function bodies that were measured (`4e3a952`; released, but for the recorder), text for text
(`dxmt/tests/timeline/check-off-arm.py`): the switch picks, once per device, other classes for the immediate context, the deferred contexts and the event queries.

With it, a look with `D3D11_ASYNC_GETDATA_DONOTFLUSH` at an event or timestamp-disjoint query that was not there 64 looks in a row
commits what has been recorded only while the query's marker has not been handed to the encoder (then once), and says `S_FALSE` from there on; unset, each such look
commits whatever has been recorded since the one before, every 100 us, until the GPU gets to the query.
And an event or disjoint query ended in a **command list** is signalled where it was ended in the list, at each execution of it; unset, it is ended as the list begins to be
executed (early: before the list's work, and at once where the immediate context has nothing new). A list's timestamps are sampled as it begins in both.
`GetData` with flags 0, `Flush`, the immediate context's `End`s, occlusion queries and readbacks are as they were.

What a look waits for: for nobody who holds a lock or the GPU. A query's End and looks see it whole under a leaf lock of its own. The one commit is made under the device's lock, taken only when it is
free, after the decision is made again under it, and never when the queue is full (the commit would wait for the GPU). Uploads that are pending hold nothing up: the chunk is
committed at once with the id of what it waits for on the GPU. What could not be done for the lock or a full queue, and the uploads, are owed: a thread of the
context's (`dxmt-rescue-thread`, asleep while nothing is) commits the uploads, the only step that can wait, without any lock but the initializer's, and the chunk,
under the same rules, whether or not anybody looks again. **What is owed stays owed until its chunk was handed to the encoder, or the context ends.** It is no bound of wall-clock time
(leaf locks, allocations and scheduling remain), and a thread that keeps the device's lock while it waits for what only another thread looks at is never rescued.

**The device's lock is on for as long as the device is there** (`D3D11MultithreadOnce`), from before its context is made, whatever the application sets with `ID3D11Multithread::SetMultithreadProtected`: whoever
records is in it, and nothing takes it from the rescue thread or from a call. `GetMultithreadProtected` and `SetMultithreadProtected` say what the application set; `Enter` holds the lock while it is set, and nothing
while it is not; `Leave` lets go of what its own thread entered; setting it to FALSE lets go of what the thread that sets it has entered, and waits for nobody. (What another thread has entered by then it keeps until its own `Leave`:
unset, the lock is taken from it.) Measured: `tests/timeline/results/2026-11-24-query-rescue.md`.

## `OBELISK_DXMT_INIT_ORDER=1` (the render server's)

DXMT's too (`src/dxmt/dxmt_init_order.hpp`), given the same way, apart from the other: the A/B/A of `queries=once` is made without it. Unset, every flag, command and encoder is as released.

- A resource that is **immutable and made without its data** (none is, in Direct3D; every one Neptune's guest makes is, and its data are the update that follows) is not taken for one the GPU only
  reads: what it is written by is put in order with what reads it, as any other resource's, for the GPU and for the optimiser. Unset, a draw of the same frame may see what was there before.
- A render pass whose last draws were counted by an **occlusion query** ends with the counting off. DXMT puts two passes of the same targets together by putting their commands together; unset, the first one's last
  query goes on counting the second one's draws, until one of them begins to be counted itself.

What it costs: the draws that read such a resource look its last write up, as they do for every other resource. Measured: `tests/timeline/results/2026-11-24-query-rescue.md`.

## What they were proven with

`tests/graphics/query_client.cpp` (`run-query-client.sh`) is what the render server's two were proven with; `otl.py --queries` tells what the looks of a recording flushed.
