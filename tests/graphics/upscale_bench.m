/*
 * upscale_bench.m - wsd's optional MetalFX upscale (wsd/wsd_upscale.h, the very code wsd runs) against what it does without it:
 * GPU time per frame, and the two pictures of one synthetic frame. Nothing is shown and no screen is read: everything is drawn
 * into textures of this process.
 *
 * Usage: upscale_bench cost <out w> <out h> <frames> <ms between frames, 0: one behind the other> <w>x<h> ...
 *        upscale_bench pictures <out w> <out h> <folder> <w>x<h> ...
 *
 * Paths: "copy" today's draw (a drawable of the frame's size: macOS's window server scales it, which costs its GPU time, not
 * wsd's, and is not in this number); "bilinear" the same triangle over the full output (what the window server's own stretch
 * looks like); "metalfx" wsd_upscale.h; "metalfx-copied" the same from a private copy of the
 * client's linear memory; "metalfx-direct" the scaler's output is the target itself (a drawable cannot be: it is not private).
 * Pictures: the synthetic frame drawn at each size, then each path's picture, and the frame drawn at the output size (the
 * reference); the mean squared error against the reference in the three channels, as PSNR.
 * Build: build-upscale-bench.sh.
 */
#import <Cocoa/Cocoa.h>
#import <Metal/Metal.h>
#import <QuartzCore/QuartzCore.h>
#include "../../wsd/wsd_upscale.h"
#include <time.h>

static NSString *const kShader = /* wsd's */
    @"#include <metal_stdlib>\n"
     "using namespace metal;\n"
     "struct VO { float4 pos [[position]]; float2 uv; };\n"
     "vertex VO vmain(uint vid [[vertex_id]]) {\n"
     "  float2 p = float2((vid << 1) & 2, vid & 2);\n"
     "  VO o; o.pos = float4(p * 2.0 - 1.0, 0.0, 1.0); o.uv = float2(p.x, 1.0 - p.y); return o; }\n"
     "fragment float4 fmain(VO in [[stage_in]], texture2d<float> t [[texture(0)]]) {\n"
     "  constexpr sampler s(filter::linear, address::clamp_to_edge);\n"
     "  return t.sample(s, in.uv); }\n";

static id<MTLDevice> g_dev;
static id<MTLCommandQueue> g_queue;
static id<MTLRenderPipelineState> g_pipe;
static uint64_t now_ns(void) { return clock_gettime_nsec_np(CLOCK_UPTIME_RAW); }

/* The synthetic frame: gradients, thin lines at many angles, a one-pixel grid, small text, a 1-in-2 checker. RGBA8, sRGB. */
static NSMutableData *synthetic(NSUInteger w, NSUInteger h) {
  NSMutableData *d = [NSMutableData dataWithLength:w * h * 4];
  CGColorSpaceRef srgb = CGColorSpaceCreateWithName(kCGColorSpaceSRGB);
  CGContextRef c = CGBitmapContextCreate(d.mutableBytes, w, h, 8, w * 4, srgb, kCGImageAlphaNoneSkipLast | kCGBitmapByteOrder32Big);
  const CGFloat k = (CGFloat)w / 2940.0; /* everything has one size on the window, whatever the frame's */
  CGContextScaleCTM(c, k, (CGFloat)h / 1912.0);
  CGFloat stops[] = {.10, .16, .26, 1, .46, .34, .30, 1};
  CGGradientRef g = CGGradientCreateWithColorComponents(srgb, stops, NULL, 2);
  CGContextDrawLinearGradient(c, g, CGPointMake(0, 0), CGPointMake(2940, 1912), 0);
  CGGradientRelease(g);
  CGContextSetRGBStrokeColor(c, .95, .95, .9, 1);
  for (int i = 0; i < 60; i++) { /* a fan of thin lines */
    CGContextSetLineWidth(c, 1.0 + (i % 4));
    CGContextMoveToPoint(c, 1500, 1800);
    CGContextAddLineToPoint(c, 1500 + 1300 * cos(i * M_PI / 60), 1800 - 900 * sin(i * M_PI / 60));
    CGContextStrokePath(c);
  }
  CGContextSetRGBStrokeColor(c, .2, .9, .6, .8); /* wire mesh */
  CGContextSetLineWidth(c, 2);
  for (int i = 0; i <= 40; i++) {
    CGContextMoveToPoint(c, 80 + i * 16, 80); CGContextAddLineToPoint(c, 80 + i * 18, 720); CGContextStrokePath(c);
    CGContextMoveToPoint(c, 80, 80 + i * 16); CGContextAddLineToPoint(c, 720, 80 + i * 17); CGContextStrokePath(c);
  }
  for (int i = 0; i < 12; i++) { /* discs with hard edges */
    CGContextSetRGBFillColor(c, (i % 3) / 2.0, .5, 1 - (i % 4) / 3.0, 1);
    CGContextFillEllipseInRect(c, CGRectMake(850 + i * 160, 620, 20 + i * 9, 20 + i * 9));
  }
  NSGraphicsContext.currentContext = [NSGraphicsContext graphicsContextWithCGContext:c flipped:NO];
  CGFloat y = 560;
  for (int size = 14; size <= 48; size += 6) {
    NSString *s = [NSString stringWithFormat:@"%d px: Orbiters N4N0 0123456789 The quick brown fox jumps over the lazy dog; ilI1|Il oO0 {}[]", size];
    [s drawAtPoint:NSMakePoint(850, y) withAttributes:@{NSFontAttributeName : [NSFont systemFontOfSize:size],
                                                        NSForegroundColorAttributeName : NSColor.whiteColor}];
    y -= size * 1.5;
  }
  NSGraphicsContext.currentContext = nil;
  CGContextRelease(c);
  CGColorSpaceRelease(srgb);
  return d;
}

/* The frame as a client of wsd gives it: linear memory. */
static id<MTLTexture> client_texture(NSData *pixels, NSUInteger w, NSUInteger h) {
  NSUInteger align = [g_dev minimumLinearTextureAlignmentForPixelFormat:MTLPixelFormatRGBA8Unorm], stride = (w * 4 + align - 1) / align * align;
  id<MTLBuffer> b = [g_dev newBufferWithLength:stride * h options:MTLResourceStorageModeShared];
  for (NSUInteger y = 0; y < h; y++) memcpy((uint8_t *)b.contents + y * stride, (const uint8_t *)pixels.bytes + y * w * 4, w * 4);
  MTLTextureDescriptor *t = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:w height:h mipmapped:NO];
  t.usage = MTLTextureUsageShaderRead;
  t.storageMode = MTLStorageModeShared;
  return [b newTextureWithDescriptor:t offset:0 bytesPerRow:stride];
}
static id<MTLTexture> target(NSUInteger w, NSUInteger h) {
  MTLTextureDescriptor *t = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm width:w height:h mipmapped:NO];
  t.usage = MTLTextureUsageRenderTarget | MTLTextureUsageShaderRead;
  t.storageMode = MTLStorageModePrivate;
  return [g_dev newTextureWithDescriptor:t];
}

enum { COPY, BILINEAR, FX, FX_COPIED, FX_DIRECT, PATHS };
static const char *const kPath[PATHS] = {"copy", "bilinear", "metalfx", "metalfx-copied", "metalfx-direct"};

static void encode(int path, id<MTLCommandBuffer> cb, WsdScaler *s, WsdScaler *copied, id<MTLTexture> frame, id<MTLTexture> small, id<MTLTexture> big) {
  switch (path) {
  case COPY: upscale_blit(cb, g_pipe, frame, small); break;
  case BILINEAR: upscale_blit(cb, g_pipe, frame, big); break;
  case FX: upscale_encode(s, cb, g_pipe, frame, big); break;
  case FX_COPIED:
    upscale_blit(cb, g_pipe, frame, small);
    upscale_encode(copied, cb, g_pipe, small, big);
    break;
  case FX_DIRECT:
    s.scaler.colorTexture = frame;
    s.scaler.inputContentWidth = frame.width; s.scaler.inputContentHeight = frame.height;
    s.scaler.outputTexture = big;
    [s.scaler encodeToCommandBuffer:cb];
    break;
  }
}
static int by(const void *a, const void *b) { double x = *(const double *)a, y = *(const double *)b; return x < y ? -1 : x > y; }

static void save(id<MTLTexture> t, NSString *path, NSMutableData *keep) {
  NSUInteger w = t.width, h = t.height, stride = (w * 4 + 255) / 256 * 256;
  id<MTLBuffer> b = [g_dev newBufferWithLength:stride * h options:MTLResourceStorageModeShared];
  id<MTLCommandBuffer> cb = [g_queue commandBuffer];
  id<MTLBlitCommandEncoder> e = [cb blitCommandEncoder];
  [e copyFromTexture:t sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0, 0, 0) sourceSize:MTLSizeMake(w, h, 1) toBuffer:b
      destinationOffset:0 destinationBytesPerRow:stride destinationBytesPerImage:stride * h];
  [e endEncoding];
  [cb commit];
  [cb waitUntilCompleted];
  CGColorSpaceRef srgb = CGColorSpaceCreateWithName(kCGColorSpaceSRGB);
  CGContextRef c = CGBitmapContextCreate(b.contents, w, h, 8, stride, srgb, kCGImageAlphaNoneSkipFirst | kCGBitmapByteOrder32Little);
  CGImageRef image = CGBitmapContextCreateImage(c);
  NSBitmapImageRep *rep = [[NSBitmapImageRep alloc] initWithCGImage:image];
  [[rep representationUsingType:NSBitmapImageFileTypePNG properties:@{}] writeToFile:path atomically:YES];
  CGImageRelease(image);
  CGContextRelease(c);
  CGColorSpaceRelease(srgb);
  if (keep) {
    [keep setLength:w * h * 4];
    for (NSUInteger y = 0; y < h; y++) memcpy((uint8_t *)keep.mutableBytes + y * w * 4, (uint8_t *)b.contents + y * stride, w * 4);
  }
}
static double psnr(NSData *a, NSData *b) {
  const uint8_t *x = a.bytes, *y = b.bytes;
  double s = 0;
  NSUInteger n = 0;
  for (NSUInteger i = 0; i < a.length; i++)
    if (i % 4 != 3) { double d = (double)x[i] - y[i]; s += d * d; n++; }
  return s ? 10 * log10(255 * 255 * n / s) : INFINITY;
}

int main(int argc, char **argv) {
  @autoreleasepool {
    if (argc < 6) return 2;
    g_dev = MTLCreateSystemDefaultDevice();
    g_queue = [g_dev newCommandQueue];
    id<MTLLibrary> lib = [g_dev newLibraryWithSource:kShader options:nil error:NULL];
    MTLRenderPipelineDescriptor *pd = [MTLRenderPipelineDescriptor new];
    pd.vertexFunction = [lib newFunctionWithName:@"vmain"];
    pd.fragmentFunction = [lib newFunctionWithName:@"fmain"];
    pd.colorAttachments[0].pixelFormat = MTLPixelFormatBGRA8Unorm;
    g_pipe = [g_dev newRenderPipelineStateWithDescriptor:pd error:NULL];
    if (!g_pipe || !upscale_init(g_dev, "metalfx")) { printf("no MetalFX here\n"); return 1; }
    const NSUInteger ow = (NSUInteger)atoi(argv[2]), oh = (NSUInteger)atoi(argv[3]);
    const BOOL cost = !strcmp(argv[1], "cost");
    NSString *folder = cost ? nil : @(argv[4]);
    for (int i = cost ? 6 : 5; i < argc; i++) {
      unsigned w = 0, h = 0;
      if (sscanf(argv[i], "%ux%u", &w, &h) != 2) return 2;
      id<MTLTexture> frame = client_texture(synthetic(w, h), w, h), small = target(w, h), big = target(ow, oh);
      uint64_t t0 = now_ns();
      WsdScaler *s = upscale_make(g_dev, w, h, MTLPixelFormatRGBA8Unorm, ow, oh), *l = upscale_make(g_dev, w, h, MTLPixelFormatBGRA8Unorm, ow, oh);
      printf("%ux%u to %lux%lu: wanted %d, scaler %s (made in %.1f ms)\n", w, h, ow, oh, upscale_wanted(w, h, ow, oh), s.scaler ? "yes" : "none", (now_ns() - t0) / 1e6);
      if (!s.scaler) continue;
      if (cost) {
        const int frames = atoi(argv[4]);
        const double gap = atof(argv[5]);
        double *gpu = calloc((size_t)frames, sizeof(double));
        for (int round = 0; round < 3; round++) /* interleaved: the GPU's clock is not a constant */
          for (int path = 0; path < PATHS; path++) {
            dispatch_semaphore_t sem = dispatch_semaphore_create(0);
            for (int f = -5; f < frames; f++) {
              @autoreleasepool {
                id<MTLCommandBuffer> cb = [g_queue commandBuffer];
                encode(path, cb, s, l, frame, small, big);
                [cb addCompletedHandler:^(id<MTLCommandBuffer> c) {
                  if (f >= 0) gpu[f] = (c.GPUEndTime - c.GPUStartTime) * 1e3;
                  dispatch_semaphore_signal(sem);
                }];
                [cb commit];
                dispatch_semaphore_wait(sem, DISPATCH_TIME_FOREVER);
                if (gap > 0) usleep((useconds_t)(gap * 1000));
              }
            }
            qsort(gpu, (size_t)frames, sizeof(double), by);
            printf("  round %d %-15s GPU ms p50 %.3f p10 %.3f p90 %.3f\n", round + 1, kPath[path], gpu[frames / 2], gpu[frames / 10], gpu[frames * 9 / 10]);
          }
        free(gpu);
      } else {
        NSMutableData *ref = [NSMutableData data], *got = [NSMutableData data];
        id<MTLTexture> whole = client_texture(synthetic(ow, oh), ow, oh), reference = target(ow, oh);
        id<MTLCommandBuffer> cb = [g_queue commandBuffer];
        upscale_blit(cb, g_pipe, whole, reference);
        [cb commit];
        save(reference, [folder stringByAppendingFormat:@"/reference-%lux%lu.png", ow, oh], ref);
        for (int path = BILINEAR; path < PATHS; path++) {
          cb = [g_queue commandBuffer];
          encode(path, cb, s, l, frame, small, big);
          [cb commit];
          [cb waitUntilCompleted];
          if (cb.error) printf("  %s: %s\n", kPath[path], cb.error.localizedDescription.UTF8String);
          NSString *p = [folder stringByAppendingFormat:@"/%ux%u-%s.png", w, h, kPath[path]];
          save(big, p, got);
          printf("  %-15s PSNR against the frame drawn at %lux%lu: %.2f dB\n", kPath[path], ow, oh, psnr(got, ref));
        }
      }
    }
  }
  return 0;
}
