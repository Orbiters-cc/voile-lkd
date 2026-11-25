/* pointer_panel: the other program of the pointer tests (wsd_pointer.py): a panel above the game, as an overlay's, that does
 * not take the keyboard, and an app to go to and come back from. Commands on stdin, one a line: "panel X Y W H" (display
 * points from the top left), "hide", "active" (this app becomes the active one, with a window of its own), "quit". Says what
 * it gets: "click", "entered", "key" (its window is the key window), "lost". */
#import <Cocoa/Cocoa.h>
static void say(const char *what) { printf("%s\n", what); fflush(stdout); }
@interface V : NSView @end
@implementation V
- (BOOL)acceptsFirstMouse:(NSEvent *)e { return YES; }
- (void)mouseDown:(NSEvent *)e { say("click"); }
- (void)drawRect:(NSRect)r { [NSColor.systemTealColor setFill]; NSRectFill(r); }
@end
@interface D : NSObject <NSApplicationDelegate, NSWindowDelegate> @end
@implementation D
- (void)windowDidBecomeKey:(NSNotification *)n { say("key"); }
- (void)windowDidResignKey:(NSNotification *)n { say("lost"); }
@end
int main(void) {
  @autoreleasepool {
    [NSApplication sharedApplication];
    D *d = [D new];
    NSApp.delegate = d;
    [NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
    NSPanel *p = [[NSPanel alloc] initWithContentRect:NSMakeRect(0, 0, 100, 100)
                                            styleMask:NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
                                              backing:NSBackingStoreBuffered defer:NO];
    p.level = NSMainMenuWindowLevel + 2;
    p.hidesOnDeactivate = NO;
    p.becomesKeyOnlyIfNeeded = YES;
    p.contentView = [V new];
    NSWindow *w = [[NSWindow alloc] initWithContentRect:NSMakeRect(200, 200, 260, 120) styleMask:NSWindowStyleMaskTitled
                                                backing:NSBackingStoreBuffered defer:NO];
    w.title = @"pointer test";
    w.delegate = d;
    w.releasedWhenClosed = NO;
    NSFileHandle *in = NSFileHandle.fileHandleWithStandardInput;
    NSMutableString *rest = [NSMutableString string];
    in.readabilityHandler = ^(NSFileHandle *h) {
      NSData *data = h.availableData;
      if (!data.length) exit(0);
      NSString *s = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
      dispatch_async(dispatch_get_main_queue(), ^{
        [rest appendString:s];
        for (NSRange r; (r = [rest rangeOfString:@"\n"]).length;) {
          NSString *line = [rest substringToIndex:r.location];
          [rest deleteCharactersInRange:NSMakeRange(0, r.location + 1)];
          double x, y, ww, hh;
          if (sscanf(line.UTF8String, "panel %lf %lf %lf %lf", &x, &y, &ww, &hh) == 4) {
            [p setFrame:NSMakeRect(x, NSMaxY(NSScreen.screens[0].frame) - y - hh, ww, hh) display:YES];
            [p orderFrontRegardless];
            say("panel");
          } else if ([line isEqualToString:@"hide"]) {
            [p orderOut:nil]; [w orderOut:nil];
            say("hidden");
          } else if ([line isEqualToString:@"active"]) {
            [NSApp activateIgnoringOtherApps:YES];
            [w makeKeyAndOrderFront:nil];
            [w orderFrontRegardless];
          } else if ([line isEqualToString:@"quit"]) exit(0);
        }
      });
    };
    say("ready");
    [NSApp run];
  }
}
