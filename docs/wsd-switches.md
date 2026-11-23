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
