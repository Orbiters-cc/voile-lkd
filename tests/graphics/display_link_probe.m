/*
 * display_link_probe.m - what each of macOS's display links gives in the power state of the moment, full screen, one
 * after another, 5 s each: NSView's CADisplayLink with the default range (wsd's), the same asking for the display's
 * rate, CVDisplayLink, and CAMetalDisplayLink (default, and asking for the rate). Each callback that can presents one
 * moving frame, so that what was shown is counted too. Prints one line per link.
 * Build and run: run-low-power-session.sh. Covers the screen for about 30 s.
 */
#import <Cocoa/Cocoa.h>
#import <CoreVideo/CoreVideo.h>
#import <Metal/Metal.h>
#import <QuartzCore/QuartzCore.h>
#include <stdatomic.h>

#define EACH 5.0
static id<MTLDevice> g_dev;
static id<MTLCommandQueue> g_queue;
static CAMetalLayer *g_layer;
static NSView *g_view;
static _Atomic int g_frame;

static uint64_t now(void) { return clock_gettime_nsec_np(CLOCK_UPTIME_RAW); }

typedef struct { int ticks, shown, zero, nodrawable; uint64_t first, last, shown_first, shown_last, wait_max; int refreshes[9]; } Stat;
static Stat g_stat;
static dispatch_queue_t g_lock;

static void shown(double t) {
  dispatch_async(g_lock, ^{
    uint64_t ns = (uint64_t)(t * 1e9);
    if (!ns) { g_stat.zero++; return; }
    if (g_stat.shown_last && ns > g_stat.shown_last) {
      int n = (int)((ns - g_stat.shown_last) / (1e9 / 60) + 0.5);
      g_stat.refreshes[n > 8 ? 8 : n]++;
    } else if (!g_stat.shown_last) g_stat.shown_first = ns;
    g_stat.shown_last = ns;
    g_stat.shown++;
  });
}
static void tick(id<CAMetalDrawable> d) {
  uint64_t t = now();
  if (!d) {
    d = [g_layer nextDrawable];
    uint64_t w = now() - t;
    dispatch_async(g_lock, ^{ if (w > g_stat.wait_max) g_stat.wait_max = w; });
  }
  int have = d != nil;
  dispatch_async(g_lock, ^{
    if (!g_stat.ticks++) g_stat.first = t;
    g_stat.last = t;
    if (!have) g_stat.nodrawable++;
  });
  if (!d) return;
  int f = atomic_fetch_add(&g_frame, 1);
  MTLRenderPassDescriptor *rp = [MTLRenderPassDescriptor renderPassDescriptor];
  rp.colorAttachments[0].texture = d.texture;
  rp.colorAttachments[0].loadAction = MTLLoadActionClear;
  rp.colorAttachments[0].clearColor = MTLClearColorMake(0.1, (f % 60) / 60.0, 0.2, 1);
  rp.colorAttachments[0].storeAction = MTLStoreActionStore;
  id<MTLCommandBuffer> cb = [g_queue commandBuffer];
  [[cb renderCommandEncoderWithDescriptor:rp] endEncoding];
  [d addPresentedHandler:^(id<MTLDrawable> dr) { shown(dr.presentedTime); }];
  [cb presentDrawable:d];
  [cb commit];
}

@interface Probe : NSObject <CAMetalDisplayLinkDelegate>
@end
@implementation Probe
- (void)link:(CADisplayLink *)l { tick(nil); }
- (void)metalDisplayLink:(CAMetalDisplayLink *)l needsUpdate:(CAMetalDisplayLinkUpdate *)u { tick(u.drawable); }
@end
static CVReturn cv(CVDisplayLinkRef l, const CVTimeStamp *a, const CVTimeStamp *b, CVOptionFlags c, CVOptionFlags *d, void *e) {
  @autoreleasepool { tick(nil); }
  return kCVReturnSuccess;
}

static void spin(double s) {
  NSDate *end = [NSDate dateWithTimeIntervalSinceNow:s];
  while ([end timeIntervalSinceNow] > 0) {
    NSEvent *e = [NSApp nextEventMatchingMask:NSEventMaskAny untilDate:end inMode:NSDefaultRunLoopMode dequeue:YES];
    if (e) [NSApp sendEvent:e];
  }
}
static void begin(void) { dispatch_sync(g_lock, ^{ memset(&g_stat, 0, sizeof(g_stat)); }); }
static void end(const char *name) {
  spin(0.3);
  dispatch_sync(g_lock, ^{
    double s = (g_stat.last - g_stat.first) / 1e9, v = (g_stat.shown_last - g_stat.shown_first) / 1e9;
    printf("LINK %-28s ticks/s %6.2f shown/s %6.2f zero %d no-drawable %d longest nextDrawable %.2f ms refreshes", name,
           s > 0 ? (g_stat.ticks - 1) / s : 0, v > 0 ? (g_stat.shown - 1) / v : 0, g_stat.zero, g_stat.nodrawable,
           g_stat.wait_max / 1e6);
    for (int i = 0; i < 9; i++) if (g_stat.refreshes[i]) printf(" %d%s:%d", i, i == 8 ? "+" : "", g_stat.refreshes[i]);
    printf("\n");
  });
}

int main(void) {
  @autoreleasepool {
    setvbuf(stdout, NULL, _IOLBF, 0);
    [NSApplication sharedApplication];
    [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];
    id<NSObject> awake = [NSProcessInfo.processInfo beginActivityWithOptions:NSActivityUserInitiated | NSActivityLatencyCritical
                                                                       reason:@"display link probe"];
    g_lock = dispatch_queue_create("probe", DISPATCH_QUEUE_SERIAL);
    g_dev = MTLCreateSystemDefaultDevice();
    g_queue = [g_dev newCommandQueue];
    NSScreen *screen = NSScreen.mainScreen;
    NSWindow *w = [[NSWindow alloc] initWithContentRect:screen.frame styleMask:NSWindowStyleMaskBorderless
                                                backing:NSBackingStoreBuffered defer:NO];
    g_layer = [CAMetalLayer layer];
    g_layer.device = g_dev;
    g_layer.pixelFormat = MTLPixelFormatBGRA8Unorm;
    g_layer.opaque = YES;
    g_layer.maximumDrawableCount = 3;
    g_layer.drawableSize = CGSizeMake(screen.frame.size.width * screen.backingScaleFactor, screen.frame.size.height * screen.backingScaleFactor);
    g_view = [[NSView alloc] initWithFrame:screen.frame];
    g_view.wantsLayer = YES;
    g_view.layer = g_layer;
    w.contentView = g_view;
    w.level = NSMainMenuWindowLevel + 1;
    [w makeKeyAndOrderFront:nil];
    [NSApp activateIgnoringOtherApps:YES];
    [NSApp setPresentationOptions:NSApplicationPresentationHideDock | NSApplicationPresentationHideMenuBar];
    spin(1.0);
    float hz = (float)screen.maximumFramesPerSecond;
    printf("PROBE display %.0f Hz, low power mode %s, thermal state %ld\n", hz,
           NSProcessInfo.processInfo.lowPowerModeEnabled ? "on" : "off", (long)NSProcessInfo.processInfo.thermalState);
    Probe *p = [Probe new];
    for (int rate = 0; rate < 2; rate++) {
      begin();
      CADisplayLink *l = [g_view displayLinkWithTarget:p selector:@selector(link:)];
      if (rate) l.preferredFrameRateRange = CAFrameRateRangeMake(hz, hz, hz);
      [l addToRunLoop:NSRunLoop.mainRunLoop forMode:NSRunLoopCommonModes];
      spin(EACH);
      [l invalidate];
      end(rate ? "CADisplayLink (asks rate)" : "CADisplayLink (default, wsd)");
    }
    begin();
    CVDisplayLinkRef c;
    CVDisplayLinkCreateWithActiveCGDisplays(&c);
    CVDisplayLinkSetOutputCallback(c, cv, NULL);
    CVDisplayLinkStart(c);
    spin(EACH);
    CVDisplayLinkStop(c);
    end("CVDisplayLink");
    for (int rate = 0; rate < 2; rate++) {
      begin();
      CAMetalDisplayLink *m = [[CAMetalDisplayLink alloc] initWithMetalLayer:g_layer];
      m.delegate = p;
      if (rate) m.preferredFrameRateRange = CAFrameRateRangeMake(hz, hz, hz);
      [m addToRunLoop:NSRunLoop.mainRunLoop forMode:NSRunLoopCommonModes];
      spin(EACH);
      [m invalidate];
      end(rate ? "CAMetalDisplayLink (asks rate)" : "CAMetalDisplayLink (default)");
    }
    [NSProcessInfo.processInfo endActivity:awake];
  }
  return 0;
}
