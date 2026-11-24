# The window server's developer switches

Two variables of `wsd`'s environment, both unset in every release and for every player. Unset, `wsd` does exactly what it did without
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

What a look may wait for: nothing. A query's End and looks see it whole under a leaf lock of its own. The one commit is made under the device's lock, taken only when it is
free, after the decision is made again under it; never when the queue is full (the commit would wait for the GPU); and never when resources' initial data are pending
or being uploaded (the uploads have a queue of two command buffers, which a commit takes one of). What could not be done for one of the three is owed: a thread of the
context's (`dxmt-rescue-thread`, asleep while nothing is) commits the uploads, the only step that can wait, without any lock but the initializer's, and then the chunk,
under the same rules, whether or not anybody looks again. Without the device's lock (no `SetMultithreadProtected`; the render server asks for it of every device) that thread
commits uploads alone, and the next look the chunk. Measured: `tests/timeline/results/2026-11-24-query-rescue.md`.

`tests/graphics/query_client.cpp` (`run-query-client.sh`) is what it was proven with; `otl.py --queries` tells what the looks of a recording flushed.
