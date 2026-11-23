/*
 * window_picture.m - a picture of one window of one program, and how far two pictures are from each other.
 *
 *   window_picture find <pid>              the largest window of that process that is on the screen: "<id> <width> <height> <layer>"
 *   window_picture shot <pid> <out.png>    its picture by its window id (macOS's own screencapture -l: never the screen), as "<id> <w> <h>"
 *   window_picture diff <a.png> <b.png> [<heat.png>]   JSON: mean difference, PSNR, SSIM, the share of pixels that differ; where
 *
 * Nothing of the program is touched, and nothing but that window is seen. exit 1: no such window, or no picture of it.
 */
#import <AppKit/AppKit.h>
#include <math.h>

static NSDictionary *window_of(pid_t pid) {
  NSArray *all = CFBridgingRelease(CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements, kCGNullWindowID));
  NSDictionary *best = nil;
  double area = 0;
  for (NSDictionary *w in all) {
    if ([w[(id)kCGWindowOwnerPID] intValue] != pid || [w[(id)kCGWindowAlpha] doubleValue] <= 0) continue;
    CGRect r;
    if (!CGRectMakeWithDictionaryRepresentation((CFDictionaryRef)w[(id)kCGWindowBounds], &r)) continue;
    if (r.size.width * r.size.height > area) { area = r.size.width * r.size.height; best = w; }
  }
  return best;
}
static int told(NSDictionary *w) {
  if (!w) { fprintf(stderr, "no window of it is on the screen\n"); return 1; }
  CGRect r;
  CGRectMakeWithDictionaryRepresentation((CFDictionaryRef)w[(id)kCGWindowBounds], &r);
  printf("%d %.0f %.0f %d\n", [w[(id)kCGWindowNumber] intValue], r.size.width, r.size.height, [w[(id)kCGWindowLayer] intValue]);
  return 0;
}
typedef struct { size_t w, h; uint8_t *px; } Image;
static Image load(const char *path) {
  Image i = {0};
  NSBitmapImageRep *rep = [NSBitmapImageRep imageRepWithData:[NSData dataWithContentsOfFile:@(path)]];
  if (!rep) return i;
  CGImageRef image = rep.CGImage;
  i.w = CGImageGetWidth(image); i.h = CGImageGetHeight(image);
  i.px = calloc(i.w * i.h, 4);
  CGColorSpaceRef space = CGImageGetColorSpace(image); /* (its own: nothing is converted, when it can be drawn into) */
  CGColorSpaceRef srgb = CGColorSpaceCreateWithName(kCGColorSpaceSRGB);
  if (!space || CGColorSpaceGetModel(space) != kCGColorSpaceModelRGB) space = srgb;
  CGContextRef c = CGBitmapContextCreate(i.px, i.w, i.h, 8, i.w * 4, space, (CGBitmapInfo)kCGImageAlphaNoneSkipLast);
  CGContextDrawImage(c, CGRectMake(0, 0, i.w, i.h), image);
  CGContextRelease(c);
  CGColorSpaceRelease(srgb);
  return i;
}
static double luma(const uint8_t *p) { return 0.2126 * p[0] + 0.7152 * p[1] + 0.0722 * p[2]; }
static int diff(const char *pa, const char *pb, const char *heat) {
  Image a = load(pa), b = load(pb);
  if (!a.px || !b.px) { fprintf(stderr, "not a picture\n"); return 1; }
  if (a.w != b.w || a.h != b.h) { printf("{\"same_size\": false, \"a\": [%zu, %zu], \"b\": [%zu, %zu]}\n", a.w, a.h, b.w, b.h); return 1; }
  double sum = 0, squares = 0, black[2] = {0, 0};
  size_t over[3] = {0}, cells[16][9] = {{0}}, in[16][9] = {{0}};
  uint8_t *out = heat ? calloc(a.w * a.h, 4) : NULL;
  for (size_t y = 0; y < a.h; y++)
    for (size_t x = 0; x < a.w; x++) {
      const uint8_t *p = a.px + (y * a.w + x) * 4, *q = b.px + (y * a.w + x) * 4;
      int most = 0;
      for (int c = 0; c < 3; c++) { int d = abs(p[c] - q[c]); sum += d; squares += d * d; if (d > most) most = d; }
      over[0] += most > 0; over[1] += most > 8; over[2] += most > 32;
      black[0] += p[0] + p[1] + p[2] == 0; black[1] += q[0] + q[1] + q[2] == 0;
      size_t cx = x * 16 / a.w, cy = y * 9 / a.h;
      cells[cx][cy] += most > 8; in[cx][cy]++;
      if (out) { uint8_t *o = out + (y * a.w + x) * 4; o[0] = (uint8_t)MIN(255, most * 4); o[1] = p[1] / 4; o[2] = p[2] / 4; o[3] = 255; }
    }
  /* SSIM of the luminance over 8 x 8 blocks, every 4 pixels */
  double ssim = 0;
  size_t blocks = 0, low = 0;
  for (size_t y = 0; y + 8 <= a.h; y += 4)
    for (size_t x = 0; x + 8 <= a.w; x += 4) {
      double ma = 0, mb = 0, va = 0, vb = 0, cov = 0;
      for (int k = 0; k < 64; k++) { size_t at = ((y + k / 8) * a.w + x + k % 8) * 4; ma += luma(a.px + at); mb += luma(b.px + at); }
      ma /= 64; mb /= 64;
      for (int k = 0; k < 64; k++) {
        size_t at = ((y + k / 8) * a.w + x + k % 8) * 4;
        double da = luma(a.px + at) - ma, db = luma(b.px + at) - mb;
        va += da * da; vb += db * db; cov += da * db;
      }
      va /= 63; vb /= 63; cov /= 63;
      double s = (2 * ma * mb + 6.5025) * (2 * cov + 58.5225) / ((ma * ma + mb * mb + 6.5025) * (va + vb + 58.5225));
      ssim += s; blocks++; low += s < 0.9;
    }
  const double n = (double)a.w * a.h, mse = squares / (3 * n);
  printf("{\"same_size\": true, \"width\": %zu, \"height\": %zu, \"mean_difference\": %.4f, \"psnr_db\": %.2f, \"ssim\": %.5f, \"blocks_below_0.9\": %.5f, "
         "\"pixels_differ\": %.5f, \"pixels_over_8\": %.5f, \"pixels_over_32\": %.5f, \"black_a\": %.5f, \"black_b\": %.5f, \"over_8_by_cell_16x9\": [",
         a.w, a.h, sum / (3 * n), mse ? 10 * log10(255 * 255 / mse) : 99.0, ssim / blocks, (double)low / blocks, over[0] / n, over[1] / n, over[2] / n,
         black[0] / n, black[1] / n);
  for (int cy = 0; cy < 9; cy++) {
    printf("%s[", cy ? ", " : "");
    for (int cx = 0; cx < 16; cx++) printf("%s%.2f", cx ? ", " : "", in[cx][cy] ? (double)cells[cx][cy] / in[cx][cy] : 0);
    printf("]");
  }
  printf("]}\n");
  if (heat) {
    CGColorSpaceRef srgb = CGColorSpaceCreateWithName(kCGColorSpaceSRGB);
    CGContextRef c = CGBitmapContextCreate(out, a.w, a.h, 8, a.w * 4, srgb, (CGBitmapInfo)kCGImageAlphaNoneSkipLast);
    CGImageRef image = CGBitmapContextCreateImage(c);
    NSData *png = [[[NSBitmapImageRep alloc] initWithCGImage:image] representationUsingType:NSBitmapImageFileTypePNG properties:@{}];
    [png writeToFile:@(heat) atomically:YES];
  }
  return 0;
}

int main(int argc, char **argv) {
  @autoreleasepool {
    if (argc == 3 && !strcmp(argv[1], "find")) return told(window_of(atoi(argv[2])));
    if (argc == 4 && !strcmp(argv[1], "shot")) {
      NSDictionary *w = window_of(atoi(argv[2]));
      if (!w) return told(w);
      NSTask *t = [NSTask new];
      t.executableURL = [NSURL fileURLWithPath:@"/usr/sbin/screencapture"];
      t.arguments = @[ @"-x", @"-o", @"-t", @"png", [NSString stringWithFormat:@"-l%d", [w[(id)kCGWindowNumber] intValue]], @(argv[3]) ];
      if (![t launchAndReturnError:nil]) return 1;
      [t waitUntilExit];
      if (t.terminationStatus || ![NSFileManager.defaultManager fileExistsAtPath:@(argv[3])]) { fprintf(stderr, "no picture of it\n"); return 1; }
      return told(w);
    }
    if ((argc == 4 || argc == 5) && !strcmp(argv[1], "diff")) return diff(argv[2], argv[3], argc == 5 ? argv[4] : NULL);
    fprintf(stderr, "window_picture find <pid> | shot <pid> <out.png> | diff <a.png> <b.png> [<heat.png>]\n");
    return 2;
  }
}
