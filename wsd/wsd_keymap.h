/*
 * wsd_keymap.h - reads a Mac keyboard layout into the blob of WSD_EV_KEYMAP (struct wsd_keymap, wsd_protocol.h).
 *
 * The blob holds facts only: the character each key types at each modifier level, which of them are dead keys, and
 * what a dead key followed by another key composes. What Windows makes of them (virtual keys, AltGr, ToUnicodeEx)
 * is the client's business (wineobelisk.drv). Wine's Mac driver reads the same facts the same way
 * (winemac.drv/keyboard.c, macdrv_compute_keyboard_layout and macdrv_ToUnicodeEx), with UCKeyTranslate.
 *
 * Included by wsd.m and by tests/keyboard/keymap-dump.c. Needs Carbon.
 */
#ifndef WSD_KEYMAP_H
#define WSD_KEYMAP_H

#include <Carbon/Carbon.h>
#include <stdlib.h>
#include <string.h>
#include "wsd_protocol.h"

#define WSD_KEYMAP_MAX_COMPOSITIONS 8192u

/* the Mac modifiers of a level, as UCKeyTranslate takes them */
static inline UInt32 wsd_keymap_level_modifiers(unsigned level) {
  UInt32 mods = 0;
  if (level == WSD_KEYMAP_COMMAND || level == WSD_KEYMAP_COMMAND_SHIFT) {
    mods |= cmdKey >> 8;
    if (level == WSD_KEYMAP_COMMAND_SHIFT) mods |= shiftKey >> 8;
    return mods;
  }
  if (level & WSD_KEYMAP_SHIFT) mods |= shiftKey >> 8;
  if (level & WSD_KEYMAP_OPTION) mods |= optionKey >> 8;
  if (level & WSD_KEYMAP_CAPS) mods |= alphaLock >> 8;
  return mods;
}

/* One UTF-16 unit a text field would take: not the private characters macOS gives the arrows and the function
 * keys, and nothing for a key that types several units. */
static inline uint16_t wsd_keymap_unit(const UniChar *text, UniCharCount len) {
  if (len != 1) return 0;
  if (text[0] >= 0xF700 && text[0] <= 0xF8FF) return 0;
  return text[0];
}

/* Reads `source` (a keyboard layout input source) for the keyboard type `keyboard_type` into a malloc'ed blob of
 * *size bytes. NULL when the source has no Unicode layout data. */
static inline void *wsd_keymap_build(TISInputSourceRef source, UInt32 keyboard_type, size_t *size) {
  CFDataRef data = source ? TISGetInputSourceProperty(source, kTISPropertyUnicodeKeyLayoutData) : NULL;
  if (!data) return NULL;
  const UCKeyboardLayout *uchr = (const UCKeyboardLayout *)CFDataGetBytePtr(data);
  static uint16_t chars[WSD_KEYMAP_KEYS][WSD_KEYMAP_LEVELS];
  static UInt32 dead_state[WSD_KEYMAP_KEYS][WSD_KEYMAP_LEVELS];
  uint16_t dead[WSD_KEYMAP_KEYS];
  struct wsd_keymap_composition *comp = NULL;
  uint32_t ncomp = 0, comp_room = 0;
  memset(chars, 0, sizeof(chars));
  memset(dead_state, 0, sizeof(dead_state));
  memset(dead, 0, sizeof(dead));

  for (unsigned key = 0; key < WSD_KEYMAP_KEYS; key++)
    for (unsigned level = 0; level < WSD_KEYMAP_LEVELS; level++) {
      UInt32 mods = wsd_keymap_level_modifiers(level), state = 0;
      UniChar text[8];
      UniCharCount len = 0;
      /* what the key stands for, a dead key's accent included */
      if (UCKeyTranslate(uchr, (UInt16)key, kUCKeyActionDown, mods, keyboard_type, kUCKeyTranslateNoDeadKeysMask,
                         &state, 8, &len, text) != noErr)
        continue;
      chars[key][level] = wsd_keymap_unit(text, len);
      /* and whether it is a dead key: it types nothing and leaves a state */
      state = 0;
      len = 0;
      if (UCKeyTranslate(uchr, (UInt16)key, kUCKeyActionDown, mods, keyboard_type, 0, &state, 8, &len, text) == noErr &&
          len == 0 && state != 0 && level < 8) {
        dead[key] |= (uint16_t)(1u << level);
        dead_state[key][level] = state;
      }
    }

  /* what each dead key composes with every key typed after it, at the levels text is typed with */
  for (unsigned key = 0; key < WSD_KEYMAP_KEYS; key++)
    for (unsigned level = 0; level < 8; level++) {
      uint16_t accent = chars[key][level];
      if (!(dead[key] & (1u << level)) || !accent) continue;
      /* another key that stands for the same accent composes the same: once is enough */
      int seen = 0;
      for (uint32_t i = 0; i < ncomp && !seen; i++) seen = comp[i].dead == accent;
      if (seen) continue;
      for (unsigned key2 = 0; key2 < WSD_KEYMAP_KEYS; key2++)
        for (unsigned level2 = 0; level2 < 8; level2++) {
          uint16_t base = chars[key2][level2];
          if (!base || (dead[key2] & (1u << level2))) continue;
          UInt32 state = dead_state[key][level];
          UniChar text[8];
          UniCharCount len = 0;
          if (UCKeyTranslate(uchr, (UInt16)key2, kUCKeyActionDown, wsd_keymap_level_modifiers(level2), keyboard_type,
                             0, &state, 8, &len, text) != noErr)
            continue;
          uint16_t composed = wsd_keymap_unit(text, len);
          /* no composition: macOS types the accent then the key (two units), or the key alone. The state left
           * tells nothing: it is not zero after a composition either. */
          if (!composed || composed == base) continue;
          int known = 0;
          for (uint32_t i = 0; i < ncomp && !known; i++) known = comp[i].dead == accent && comp[i].base == base;
          if (known || ncomp >= WSD_KEYMAP_MAX_COMPOSITIONS) continue;
          if (ncomp == comp_room) {
            comp_room = comp_room ? comp_room * 2 : 256;
            comp = realloc(comp, comp_room * sizeof(*comp));
          }
          comp[ncomp++] = (struct wsd_keymap_composition){accent, base, composed};
        }
    }

  struct wsd_keymap header = {WSD_KEYMAP_VERSION, KBGetLayoutType((SInt16)keyboard_type) == kKeyboardISO ? WSD_KEYMAP_ISO : 0,
                              keyboard_type, WSD_KEYMAP_KEYS, WSD_KEYMAP_LEVELS, ncomp, {0}};
  CFStringRef id = TISGetInputSourceProperty(source, kTISPropertyInputSourceID);
  if (id) CFStringGetCString(id, header.source, sizeof(header.source), kCFStringEncodingUTF8);
  header.source[sizeof(header.source) - 1] = 0;

  *size = sizeof(header) + sizeof(chars) + sizeof(dead) + ncomp * sizeof(*comp);
  uint8_t *blob = malloc(*size), *at = blob;
  memcpy(at, &header, sizeof(header)); at += sizeof(header);
  memcpy(at, chars, sizeof(chars)); at += sizeof(chars);
  memcpy(at, dead, sizeof(dead)); at += sizeof(dead);
  if (ncomp) memcpy(at, comp, ncomp * sizeof(*comp));
  free(comp);
  return blob;
}

#endif
