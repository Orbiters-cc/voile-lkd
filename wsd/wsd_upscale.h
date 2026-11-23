/*
 * wsd_upscale.h - an optional sharper upscale of a frame smaller than the window's own pixels: MetalFX Spatial.
 *
 * Off unless OBELISK_WSD_UPSCALE=metalfx. Off, nothing of it is loaded, made or looked at, and wsd draws as it always did: a
 * drawable of the frame's size, which macOS stretches over the window (bilinear). On, such a frame is scaled to the window's
 * backing pixels here and the drawable has that size. MetalFX is loaded then, at the start, never linked.
 *
 * The pixels are sRGB-encoded values in UNORM textures from the client to the layer, which is tagged sRGB: perceptual on both
 * sides of the scaler, nothing converted.
 */
#ifndef WSD_UPSCALE_H
#define WSD_UPSCALE_H
#import <Metal/Metal.h>
#import <MetalFX/MetalFX.h> /* declarations only */
#include <dlfcn.h>

/* A frame less than this share of the window on both axes is scaled; nearer to it, macOS's own stretch is as good. */
#define UPSCALE_MOST 0.95
/* Frames of one size in a row before a scaler is made for it (a window being resized changes size at each). */
#define UPSCALE_SETTLED 8

/* One plane's. */
@interface WsdScaler : NSObject
@property(strong) id<MTLFXSpatialScaler> scaler; /* nil while it is being made, or when the sizes have none */
@property(strong) id<MTLTexture> output; /* the scaled picture */
@property NSUInteger inWidth, inHeight, outWidth, outHeight;
@property MTLPixelFormat format;
@end
@implementation WsdScaler
- (BOOL)isFor:(id<MTLTexture>)frame width:(NSUInteger)w height:(NSUInteger)h {
  return self.inWidth == frame.width && self.inHeight == frame.height && self.format == frame.pixelFormat &&
         self.outWidth == w && self.outHeight == h;
}
@end

static Class g_upscale_class; /* MTLFXSpatialScalerDescriptor, once MetalFX is loaded and does this GPU */

/* Whether `name` (OBELISK_WSD_UPSCALE) asks for it and this Mac has it. */
static BOOL upscale_init(id<MTLDevice> dev, const char *name) {
  if (!name || strcmp(name, "metalfx")) return NO;
  if (!dlopen("/System/Library/Frameworks/MetalFX.framework/MetalFX", RTLD_LAZY | RTLD_LOCAL)) return NO;
  Class c = NSClassFromString(@"MTLFXSpatialScalerDescriptor");
  if (!c || ![c supportsDevice:dev]) return NO;
  g_upscale_class = c;
  return YES;
}

/* Whether a frame of w x h over out_w x out_h pixels is one to scale. */
static BOOL upscale_wanted(NSUInteger w, NSUInteger h, NSUInteger out_w, NSUInteger out_h) {
  return g_upscale_class && w >= 320 && h >= 240 && out_w >= 640 && out_h >= 480 && out_w <= 16384 && out_h <= 16384 &&
         w <= out_w * UPSCALE_MOST && h <= out_h * UPSCALE_MOST;
}

/* Takes 190 ms the first time in a process, about 1 ms after: off the main thread. */
static WsdScaler *upscale_make(id<MTLDevice> dev, NSUInteger w, NSUInteger h, MTLPixelFormat format, NSUInteger out_w,
                               NSUInteger out_h) {
  WsdScaler *s = [WsdScaler new];
  s.inWidth = w; s.inHeight = h; s.format = format; s.outWidth = out_w; s.outHeight = out_h;
  MTLFXSpatialScalerDescriptor *d = [g_upscale_class new];
  d.colorTextureFormat = format; /* read from the client's own memory: a copy of it first costs more than it saves */
  d.outputTextureFormat = MTLPixelFormatBGRA8Unorm;
  d.inputWidth = w; d.inputHeight = h; d.outputWidth = out_w; d.outputHeight = out_h;
  d.colorProcessingMode = MTLFXSpatialScalerColorProcessingModePerceptual;
  id<MTLFXSpatialScaler> scaler = [d newSpatialScalerWithDevice:dev];
  if (!scaler) return s;
  MTLTextureDescriptor *t = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm width:out_w
                                                                              height:out_h mipmapped:NO];
  t.storageMode = MTLStorageModePrivate;
  t.usage = scaler.outputTextureUsage | MTLTextureUsageShaderRead;
  s.output = [dev newTextureWithDescriptor:t];
  if (s.output) s.scaler = scaler;
  return s;
}

/* Draws `from` over the whole of `to` with the pipeline `pipe` (wsd's full-screen triangle). */
static void upscale_blit(id<MTLCommandBuffer> cb, id<MTLRenderPipelineState> pipe, id<MTLTexture> from, id<MTLTexture> to) {
  MTLRenderPassDescriptor *rp = [MTLRenderPassDescriptor renderPassDescriptor];
  rp.colorAttachments[0].texture = to;
  rp.colorAttachments[0].loadAction = MTLLoadActionDontCare;
  rp.colorAttachments[0].storeAction = MTLStoreActionStore;
  id<MTLRenderCommandEncoder> enc = [cb renderCommandEncoderWithDescriptor:rp];
  [enc setRenderPipelineState:pipe];
  [enc setFragmentTexture:from atIndex:0];
  [enc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
  [enc endEncoding];
}

/* The frame, scaled, into `to` (BGRA8, the scaler's output size). The scaler writes a private texture, which a drawable is not. */
static void upscale_encode(WsdScaler *s, id<MTLCommandBuffer> cb, id<MTLRenderPipelineState> pipe, id<MTLTexture> frame,
                           id<MTLTexture> to) {
  s.scaler.colorTexture = frame;
  s.scaler.inputContentWidth = s.inWidth;
  s.scaler.inputContentHeight = s.inHeight;
  s.scaler.outputTexture = s.output;
  [s.scaler encodeToCommandBuffer:cb];
  s.scaler.colorTexture = nil; /* never keeps a client's buffer */
  upscale_blit(cb, pipe, s.output, to);
}
#endif
