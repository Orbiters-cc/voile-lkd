/*
 * pass_bench.m - what Metal itself takes for one pass, by its load and store actions: the passes DXMT makes of a 2x scene,
 * and the same without what nobody reads again. Offscreen, no window. Command buffers run back to back, three in
 * flight; the price of one is the time from one's end to the next one's end (GPUEndTime less GPUStartTime of one counts
 * what it overlaps with).
 * Usage: pass_bench --sustain <seconds>: one GPU-bound frame (60 blended full-size triangles at 2x, 2940x1912) over and over, its
 * time and macOS's thermal state every 5 s: what the GPU still does once it is warm (powermetrics' clocks need root).
 *    or: pass_bench [--noise] [width height ...]   (--noise: every pixel differs, which lossless compression cannot help)
 */
#import <Metal/Metal.h>
#import <Foundation/Foundation.h>
#include <stdlib.h>

static id<MTLDevice> dev;
static id<MTLTexture> tex(MTLPixelFormat f, int w, int h, int samples, BOOL memoryless) {
  MTLTextureDescriptor *d = [MTLTextureDescriptor new];
  d.textureType = samples > 1 ? MTLTextureType2DMultisample : MTLTextureType2D;
  d.pixelFormat = f; d.width = w; d.height = h; d.sampleCount = samples;
  d.usage = MTLTextureUsageRenderTarget | (memoryless ? 0 : MTLTextureUsageShaderRead);
  d.storageMode = memoryless ? MTLStorageModeMemoryless : MTLStorageModePrivate;
  return [dev newTextureWithDescriptor:d];
}
static int cmp(const void *a, const void *b) { double x = *(double *)a, y = *(double *)b; return x < y ? -1 : x > y; }

int main(int argc, char **argv) {
  @autoreleasepool {
    BOOL noise = argc > 1 && !strcmp(argv[1], "--noise");
    if (noise) { argv++; argc--; }
    dev = MTLCreateSystemDefaultDevice();
    id<MTLCommandQueue> q = [dev newCommandQueue];
    NSError *e = nil;
    id<MTLLibrary> lib = [dev newLibraryWithSource:
        @"#include <metal_stdlib>\nusing namespace metal;\nstruct V { float4 p [[position]]; float2 u; };\n"
         "vertex V v(uint i [[vertex_id]]) { float2 p = float2((i << 1) & 2, i & 2); V o; o.p = float4(p * 2 - 1, .5, 1); o.u = p; return o; }\n"
         "fragment float4 f(V i [[stage_in]]) { return float4(i.u * .01, .02, 1); }\n"
         "fragment float4 n(V i [[stage_in]]) { uint2 p = uint2(i.p.xy); uint h = p.x * 73856093u ^ p.y * 19349663u; h ^= h >> 13; h *= "
         "0x5bd1e995u; h ^= h >> 15; return unpack_unorm4x8_to_float(h); }\n" options:nil error:&e];
    id<MTLRenderPipelineState> pso[3];
    for (int s = 1; s <= 2; s++) {
      MTLRenderPipelineDescriptor *d = [MTLRenderPipelineDescriptor new];
      d.vertexFunction = [lib newFunctionWithName:@"v"]; d.fragmentFunction = [lib newFunctionWithName:noise ? @"n" : @"f"];
      d.colorAttachments[0].pixelFormat = MTLPixelFormatRGBA8Unorm;
      d.colorAttachments[0].blendingEnabled = YES;
      d.colorAttachments[0].sourceRGBBlendFactor = d.colorAttachments[0].destinationRGBBlendFactor = MTLBlendFactorOne;
      d.depthAttachmentPixelFormat = d.stencilAttachmentPixelFormat = MTLPixelFormatDepth32Float_Stencil8;
      d.rasterSampleCount = s;
      pso[s] = [dev newRenderPipelineStateWithDescriptor:d error:&e];
      if (!pso[s]) { printf("pipeline: %s\n", e.description.UTF8String); return 1; }
    }
    struct { const char *name; int samples; MTLLoadAction l; MTLStoreAction s; MTLStoreAction ds; BOOL less; int splits; BOOL dsload; } kinds[] = {
      {"1x clear/store, depth store", 1, MTLLoadActionClear, MTLStoreActionStore, MTLStoreActionStore, NO, 1, NO},
      {"1x clear/store, depth dontcare", 1, MTLLoadActionClear, MTLStoreActionStore, MTLStoreActionDontCare, NO, 1, NO},
      {"2x clear/store+resolve, depth store (DXMT's)", 2, MTLLoadActionClear, MTLStoreActionStoreAndMultisampleResolve, MTLStoreActionStore, NO, 1, NO},
      {"2x clear/resolve, depth store", 2, MTLLoadActionClear, MTLStoreActionMultisampleResolve, MTLStoreActionStore, NO, 1, NO},
      {"2x clear/store+resolve, depth dontcare", 2, MTLLoadActionClear, MTLStoreActionStoreAndMultisampleResolve, MTLStoreActionDontCare, NO, 1, NO},
      {"2x clear/resolve, depth dontcare", 2, MTLLoadActionClear, MTLStoreActionMultisampleResolve, MTLStoreActionDontCare, NO, 1, NO},
      {"2x memoryless, resolve", 2, MTLLoadActionClear, MTLStoreActionMultisampleResolve, MTLStoreActionDontCare, YES, 1, NO},
      {"1x in 8 parts of one pass", 1, MTLLoadActionClear, MTLStoreActionStore, MTLStoreActionStore, NO, -8, NO},
      {"1x in 8 passes, colour and depth load/store", 1, MTLLoadActionClear, MTLStoreActionStore, MTLStoreActionStore, NO, 8, YES},
      {"2x in 8 parts of one pass, store+resolve", 2, MTLLoadActionClear, MTLStoreActionStoreAndMultisampleResolve, MTLStoreActionStore, NO, -8, NO},
      {"2x in 8 passes, colour and depth load/store", 2, MTLLoadActionClear, MTLStoreActionStore, MTLStoreActionStore, NO, 8, YES},
    };
    if (argc > 2 && !strcmp(argv[1], "--sustain")) {
      id<MTLTexture> c = tex(MTLPixelFormatRGBA8Unorm, 2940, 1912, 2, NO), r = tex(MTLPixelFormatRGBA8Unorm, 2940, 1912, 1, NO),
                     d = tex(MTLPixelFormatDepth32Float_Stencil8, 2940, 1912, 2, NO);
      dispatch_semaphore_t sem = dispatch_semaphore_create(2);
      __block int n = 0;
      double begin = CFAbsoluteTimeGetCurrent(), mark = begin;
      setvbuf(stdout, NULL, _IOLBF, 0);
      while (CFAbsoluteTimeGetCurrent() - begin < atof(argv[2])) {
        @autoreleasepool {
          dispatch_semaphore_wait(sem, DISPATCH_TIME_FOREVER);
          id<MTLCommandBuffer> cb = [q commandBuffer];
          MTLRenderPassDescriptor *rp = [MTLRenderPassDescriptor renderPassDescriptor];
          rp.colorAttachments[0].texture = c; rp.colorAttachments[0].resolveTexture = r;
          rp.colorAttachments[0].loadAction = MTLLoadActionClear;
          rp.colorAttachments[0].storeAction = MTLStoreActionStoreAndMultisampleResolve;
          rp.depthAttachment.texture = rp.stencilAttachment.texture = d;
          rp.depthAttachment.loadAction = rp.stencilAttachment.loadAction = MTLLoadActionClear;
          rp.depthAttachment.storeAction = rp.stencilAttachment.storeAction = MTLStoreActionStore;
          id<MTLRenderCommandEncoder> enc = [cb renderCommandEncoderWithDescriptor:rp];
          [enc setRenderPipelineState:pso[2]];
          for (int i = 0; i < 60; i++) [enc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
          [enc endEncoding];
          [cb addCompletedHandler:^(id<MTLCommandBuffer> b) { dispatch_semaphore_signal(sem); }];
          [cb commit];
          n++;
          double now = CFAbsoluteTimeGetCurrent();
          if (now - mark >= 5) {
            printf("SUSTAIN at %4.0f s: %.3f ms a frame, thermal state %ld\n", now - begin, (now - mark) * 1e3 / n,
                   (long)NSProcessInfo.processInfo.thermalState);
            mark = now; n = 0;
          }
        }
      }
      return 0;
    }
    for (int a = 1; a < (argc > 2 ? argc - 1 : 4); a += 2) {
      int w = argc > 2 ? atoi(argv[a]) : a == 1 ? 2940 : 1705, h = argc > 2 ? atoi(argv[a + 1]) : a == 1 ? 1912 : 1109;
      for (int k = 0; k < (int)(sizeof(kinds) / sizeof(kinds[0])); k++) {
        int S = kinds[k].samples, parts = abs(kinds[k].splits), passes = kinds[k].splits > 0 ? parts : 1;
        id<MTLTexture> c = tex(MTLPixelFormatRGBA8Unorm, w, h, S, kinds[k].less), r = tex(MTLPixelFormatRGBA8Unorm, w, h, 1, NO),
                       d = tex(MTLPixelFormatDepth32Float_Stencil8, w, h, S, kinds[k].less);
        enum { N = 600, SKIP = 200 };
        static double t[N], at[N];
        dispatch_semaphore_t sem = dispatch_semaphore_create(3);
        dispatch_group_t g = dispatch_group_create();
        double *out = t, *ends = at; /* three in flight, so that the GPU does not idle between them */
        for (int n = 0; n < N; n++) {
          @autoreleasepool {
            dispatch_semaphore_wait(sem, DISPATCH_TIME_FOREVER);
            dispatch_group_enter(g);
            id<MTLCommandBuffer> cb = [q commandBuffer];
            for (int p = 0; p < passes; p++) {
              MTLRenderPassDescriptor *rp = [MTLRenderPassDescriptor renderPassDescriptor];
              BOOL last = p == passes - 1;
              rp.colorAttachments[0].texture = c;
              rp.colorAttachments[0].loadAction = p ? MTLLoadActionLoad : kinds[k].l;
              rp.colorAttachments[0].storeAction = last && passes > 1 && S > 1 ? MTLStoreActionStoreAndMultisampleResolve : kinds[k].s;
              if (rp.colorAttachments[0].storeAction == MTLStoreActionMultisampleResolve ||
                  rp.colorAttachments[0].storeAction == MTLStoreActionStoreAndMultisampleResolve)
                rp.colorAttachments[0].resolveTexture = r;
              rp.depthAttachment.texture = rp.stencilAttachment.texture = d;
              rp.depthAttachment.loadAction = rp.stencilAttachment.loadAction = p ? MTLLoadActionLoad : MTLLoadActionClear;
              rp.depthAttachment.storeAction = rp.stencilAttachment.storeAction = kinds[k].ds;
              id<MTLRenderCommandEncoder> enc = [cb renderCommandEncoderWithDescriptor:rp];
              [enc setRenderPipelineState:pso[S]];
              for (int i = 0; i < parts / passes; i++) [enc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
              [enc endEncoding];
            }
            [cb addCompletedHandler:^(id<MTLCommandBuffer> b) {
              out[n] = (b.GPUEndTime - b.GPUStartTime) * 1e3; ends[n] = b.GPUEndTime * 1e3;
              dispatch_semaphore_signal(sem);
              dispatch_group_leave(g);
            }];
            [cb commit];
          }
        }
        dispatch_group_wait(g, DISPATCH_TIME_FOREVER);
        double each = (at[N - 1] - at[SKIP]) / (N - 1 - SKIP);
        qsort(t + SKIP, N - SKIP, sizeof(double), cmp);
        printf("PASS %dx%d %-46s %.3f ms each (start to end p50 %.3f)\n", w, h, kinds[k].name, each, t[SKIP + (N - SKIP) / 2]);
      }
    }
  }
  return 0;
}
