/* keymap-dump: what wsd tells its clients of a keyboard layout (WSD_EV_KEYMAP), and what wineobelisk.drv makes of it.
 *
 *   keymap-dump                         the selected input source, for this Mac's keyboard type
 *   keymap-dump SOURCE [KEYBOARD_TYPE]  an installed one, selected or not, such as com.apple.keylayout.French;
 *                                       40 is an ANSI keyboard and 41 an ISO one
 *   keymap-dump --blob FILE ...         also writes the blob to FILE
 *
 * Prints one line per character key: mac keycode, scan code, virtual key, and the characters without modifier, with
 * Shift, AltGr, Shift+AltGr and Caps Lock (a dead key in brackets). Selects nothing on the Mac.
 * Built by run.sh with wineobelisk.drv's keymap.c (voile-wine). */
#include <stdio.h>
#include "../../wsd/wsd_keymap.h"
#include "keymap.h"

TISInputSourceRef keymap_test_source(const char *id) {
  if (!id) return TISCopyCurrentKeyboardLayoutInputSource();
  CFStringRef name = CFStringCreateWithCString(NULL, id, kCFStringEncodingUTF8);
  CFDictionaryRef filter = CFDictionaryCreate(NULL, (const void **)&kTISPropertyInputSourceID, (const void **)&name, 1,
                                              &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
  CFArrayRef list = TISCreateInputSourceList(filter, true);
  TISInputSourceRef source = list && CFArrayGetCount(list) ? (TISInputSourceRef)CFRetain(CFArrayGetValueAtIndex(list, 0)) : NULL;
  if (list) CFRelease(list);
  CFRelease(filter);
  CFRelease(name);
  return source;
}

#ifndef KEYMAP_NO_MAIN
static void put(unsigned short c, int dead) {
  char utf8[8] = {0};
  if (!c) { printf("  %-6s", "."); return; }
  if (c < 0x80) utf8[0] = (char)c;
  else if (c < 0x800) { utf8[0] = (char)(0xc0 | (c >> 6)); utf8[1] = (char)(0x80 | (c & 0x3f)); }
  else { utf8[0] = (char)(0xe0 | (c >> 12)); utf8[1] = (char)(0x80 | ((c >> 6) & 0x3f)); utf8[2] = (char)(0x80 | (c & 0x3f)); }
  printf(dead ? " [%s]%*s" : "  %s%*s", utf8, dead ? 3 : 5, "");
}

int main(int argc, char **argv) {
  const char *blob_path = NULL, *id = NULL;
  UInt32 type = LMGetKbdType();
  int arg = 1;
  if (arg + 1 < argc && !strcmp(argv[arg], "--blob")) { blob_path = argv[arg + 1]; arg += 2; }
  if (arg < argc) id = argv[arg++];
  if (arg < argc) type = (UInt32)atoi(argv[arg++]);
  TISInputSourceRef source = keymap_test_source(id);
  size_t size = 0;
  void *blob = wsd_keymap_build(source, type, &size);
  if (!blob) { fprintf(stderr, "no such keyboard layout: %s\n", id ? id : "(selected)"); return 1; }
  if (blob_path) {
    FILE *f = fopen(blob_path, "wb");
    if (!f || fwrite(blob, 1, size, f) != size) { perror(blob_path); return 1; }
    fclose(f);
  }
  struct obelisk_keymap *k = obelisk_keymap_create(blob, size, 1);
  if (!k) { fprintf(stderr, "wineobelisk.drv refuses the blob\n"); return 1; }
  printf("%s, keyboard type %u (%s), %zu bytes, AltGr %s, %u compositions\n", k->source, (unsigned)type,
         k->iso ? "ISO" : "ANSI or JIS", size, k->altgr ? "yes" : "no", k->composition_count);
  printf("key  scan  vkey  plain  Shift  AltGr  Sh+AGr Caps\n");
  for (unsigned key = 0; key < OBELISK_KEYS; key++) {
    if (k->key_of_vkey[k->vkey[key] & 0xff] != key) continue;
    printf("%3u  %03x   %02x  ", key, k->scan[key], k->vkey[key]);
    for (unsigned level = 0; level < 5; level++) put(k->chars[key][level], k->dead[key] & (1u << level));
    printf("\n");
  }
  return 0;
}
#endif
