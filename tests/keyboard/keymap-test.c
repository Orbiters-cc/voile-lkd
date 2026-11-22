/* keymap-test: the Windows layout wineobelisk.drv makes of the Mac's own input sources, checked against what a PC
 * keyboard of the same layout gives Windows: scan codes by the key's place, virtual keys by the layout (kbdfr.dll,
 * kbdgr.dll, kbddv.dll), and the characters a key types, with Shift, AltGr and dead keys. It reads the installed
 * layouts by their id and selects nothing on the Mac. Built and run by run.sh. */
#define KEYMAP_NO_MAIN
#include "keymap-dump.c"

static int failures, checks;
static const char *context;

static void check(int ok, const char *what, unsigned key, long got, long want) {
  checks++;
  if (ok) return;
  failures++;
  printf("FAIL %s: %s, key %u: got %#lx, want %#lx\n", context, what, key, got, want);
}

/* one key: its scan code, its virtual key, and what it types without modifier, with Shift, with AltGr, with both
 * (0: not checked) */
struct key_case { unsigned key, scan, vkey; unsigned short plain, shift, altgr, shift_altgr; };

/* keys typed one after the other (virtual key, level), and what they must have typed in all */
struct typing_case { struct { unsigned vkey, level; } keys[4]; const unsigned short *text; };

static struct obelisk_keymap *load(const char *id, UInt32 type) {
  TISInputSourceRef source = keymap_test_source(id);
  size_t size = 0;
  void *blob = wsd_keymap_build(source, type, &size);
  struct obelisk_keymap *k = blob ? obelisk_keymap_create(blob, size, 1) : NULL;
  free(blob);
  if (!k) printf("SKIP %s: not installed on this Mac\n", id);
  return k;
}

static void check_keys(const struct obelisk_keymap *k, const struct key_case *cases, unsigned count) {
  for (unsigned i = 0; i < count; i++) {
    const struct key_case *c = &cases[i];
    unsigned short pending = 0, out[4];
    check(k->scan[c->key] == c->scan, "scan code", c->key, k->scan[c->key], c->scan);
    check(k->vkey[c->key] == c->vkey, "virtual key", c->key, k->vkey[c->key], c->vkey);
    const unsigned short want[4] = {c->plain, c->shift, c->altgr, c->shift_altgr};
    for (unsigned level = 0; level < 4; level++) {
      if (!want[level]) continue;
      int n = obelisk_keymap_to_unicode(k, c->vkey, level, 1, &pending, out, 4);
      check((n == 1 || n == -1) && out[0] == want[level], "character", c->key * 10 + level, n ? out[0] : 0, want[level]);
    }
  }
}

static void check_typing(const struct obelisk_keymap *k, const struct typing_case *cases, unsigned count) {
  for (unsigned i = 0; i < count; i++) {
    unsigned short pending = 0, text[16];
    int len = 0, want = 0;
    for (unsigned j = 0; j < 4 && cases[i].keys[j].vkey; j++) {
      int n = obelisk_keymap_to_unicode(k, cases[i].keys[j].vkey, cases[i].keys[j].level, 0, &pending, text + len, 4);
      if (n > 0) len += n;
    }
    while (cases[i].text[want]) want++;
    int same = len == want && !memcmp(text, cases[i].text, (size_t)len * sizeof(*text));
    check(same, "typed text", i, len ? text[0] : 0, cases[i].text[0]);
  }
}

enum { SHIFT = OBELISK_LEVEL_SHIFT, ALTGR = OBELISK_LEVEL_ALTGR, CAPS = OBELISK_LEVEL_CAPS };
enum { ANSI = 40, ISO = 41 };  /* gestaltThirdPartyANSIKbd, gestaltThirdPartyISOKbd */

int main(void) {
  struct obelisk_keymap *k;

  context = "US, ANSI keyboard";
  if ((k = load("com.apple.keylayout.US", ANSI))) {
    static const struct key_case keys[] = {
      {0, 0x1e, 'A', 'a', 'A'}, {12, 0x10, 'Q', 'q', 'Q'}, {13, 0x11, 'W', 'w', 'W'}, {6, 0x2c, 'Z', 'z', 'Z'},
      {16, 0x15, 'Y', 'y', 'Y'}, {46, 0x32, 'M', 'm', 'M'}, {18, 0x02, '1', '1', '!'}, {19, 0x03, '2', '2', '@'},
      {29, 0x0b, '0', '0', ')'}, {27, 0x0c, 0xbd, '-', '_'}, {24, 0x0d, 0xbb, '=', '+'}, {33, 0x1a, 0xdb, '[', '{'},
      {30, 0x1b, 0xdd, ']', '}'}, {41, 0x27, 0xba, ';', ':'}, {39, 0x28, 0xde, '\'', '"'}, {42, 0x2b, 0xdc, '\\', '|'},
      {43, 0x33, 0xbc, ',', '<'}, {47, 0x34, 0xbe, '.', '>'}, {44, 0x35, 0xbf, '/', '?'}, {50, 0x29, 0xc0, '`', '~'},
    };
    /* no AltGr on a US keyboard: Ctrl+Alt+E types nothing more than E does, and Option's dead keys are not Windows' */
    static const unsigned short e[] = {'e', 0}, capital[] = {'E', 0};
    static const struct typing_case typing[] = {
      {{{'E', ALTGR}}, e}, {{{'E', CAPS}}, capital}, {{{'E', CAPS | SHIFT}}, capital},
    };
    check(!k->altgr, "AltGr", 0, k->altgr, 0);
    check(!k->iso, "ISO", 0, k->iso, 0);
    check_keys(k, keys, sizeof(keys) / sizeof(*keys));
    check_typing(k, typing, sizeof(typing) / sizeof(*typing));
    /* the key an ANSI keyboard does not have keeps the virtual key of its place and takes none from a real key */
    check(k->vkey[10] == 0xe2, "virtual key", 10, k->vkey[10], 0xe2);
    free(k);
  }

  context = "French (Mac AZERTY), ISO keyboard";
  if ((k = load("com.apple.keylayout.French", ISO))) {
    static const struct key_case keys[] = {
      /* the letters that move: A and Q, Z and W, M */
      {12, 0x10, 'A', 'a', 'A'}, {0, 0x1e, 'Q', 'q', 'Q'}, {13, 0x11, 'Z', 'z', 'Z'}, {6, 0x2c, 'W', 'w', 'W'},
      {41, 0x27, 'M', 'm', 'M'}, {16, 0x15, 'Y', 'y', 'Y'},
      /* the digits are typed with Shift, and keep the digits' virtual keys as on kbdfr */
      {18, 0x02, '1', '&', '1'}, {19, 0x03, '2', 0xe9, '2'}, {20, 0x04, '3', '"', '3'}, {21, 0x05, '4', '\'', '4'},
      {23, 0x06, '5', '(', '5', '{', '['}, {26, 0x08, '7', 0xe8, '7'}, {25, 0x0a, '9', 0xe7, '9'},
      {29, 0x0b, '0', 0xe0, '0'},
      /* punctuation, with kbdfr's virtual keys */
      {27, 0x0c, 0xdb, ')', 0xb0, '}', ']'}, {33, 0x1a, 0xdd, '^', 0xa8}, {30, 0x1b, 0xba, '$', '*', 0x20ac},
      {39, 0x28, 0xc0, 0xf9, '%'}, {46, 0x32, 0xbc, ',', '?'}, {43, 0x33, 0xbe, ';', '.'}, {47, 0x34, 0xbf, ':', '/', 0, '\\'},
      {44, 0x35, 0xdf, '=', '+'}, {37, 0x26, 'L', 'l', 'L', 0, '|'},
      /* an ISO keyboard: the key left of 1 has the scan code 0x29, the one right of the left Shift 0x56 */
      {10, 0x29, 0xbd, '@', '#'}, {50, 0x56, 0xe2, '<', '>'},
    };
    static const unsigned short e_circ[] = {0xea, 0}, circ[] = {'^', 0}, circ_x[] = {'^', 'x', 0}, u_uml[] = {0xfc, 0},
                                n_tilde[] = {0xf1, 0}, two_circ[] = {'^', '^', 0}, E_acute[] = {0xc9, 0},
                                O_circ[] = {0xd4, 0};
    static const struct typing_case typing[] = {
      {{{0xdd, 0}, {'E', 0}}, e_circ},          /* ^ then e */
      {{{0xdd, 0}, {' ', 0}}, circ},            /* ^ then the space bar */
      {{{0xdd, 0}, {'X', 0}}, circ_x},          /* ^ then a letter that takes none */
      {{{0xdd, SHIFT}, {'U', 0}}, u_uml},       /* the diaeresis is Shift+^ */
      {{{'N', ALTGR}, {'N', 0}}, n_tilde},      /* the tilde is AltGr+n */
      {{{0xdd, 0}, {0xdd, 0}}, two_circ},
      {{{0xdd, 0}, {'O', SHIFT}}, O_circ},
      {{{'2', CAPS}}, E_acute},                 /* Caps Lock is the Mac's: capital accented letters */
    };
    check(k->altgr, "AltGr", 0, k->altgr, 1);
    check(k->iso, "ISO", 0, k->iso, 1);
    check_keys(k, keys, sizeof(keys) / sizeof(*keys));
    check_typing(k, typing, sizeof(typing) / sizeof(*typing));
    /* a dead key says so, and leaves its accent waiting */
    unsigned short pending = 0, out[4];
    int n = obelisk_keymap_to_unicode(k, 0xdd, 0, 0, &pending, out, 4);
    check(n == -1 && out[0] == '^' && pending == '^', "dead key", 33, n, -1);
    /* a key that is not the layout's is the caller's */
    n = obelisk_keymap_to_unicode(k, 0x0d, 0, 0, &pending, out, 4);
    check(n == -2 && pending == '^', "Return", 36, n, -2);
    free(k);
  }

  context = "French - PC, ISO keyboard";
  if ((k = load("com.apple.keylayout.French-PC", ISO))) {
    static const struct key_case keys[] = {
      {12, 0x10, 'A', 'a', 'A'}, {0, 0x1e, 'Q', 'q', 'Q'}, {13, 0x11, 'Z', 'z', 'Z'}, {6, 0x2c, 'W', 'w', 'W'},
      {41, 0x27, 'M', 'm', 'M'},
      /* kbdfr's AltGr characters: ~ # { [ | ` \ ^ @ ] } and the euro */
      {18, 0x02, '1', '&', '1'}, {19, 0x03, '2', 0xe9, '2', '~'}, {20, 0x04, '3', '"', '3', '#'},
      {21, 0x05, '4', '\'', '4', '{'}, {23, 0x06, '5', '(', '5', '['}, {22, 0x07, '6', '-', '6', '|'},
      {26, 0x08, '7', 0xe8, '7', '`'}, {28, 0x09, '8', '_', '8', '\\'}, {25, 0x0a, '9', 0xe7, '9', '^'},
      {29, 0x0b, '0', 0xe0, '0', '@'}, {27, 0x0c, 0xdb, ')', 0xb0, ']'}, {24, 0x0d, 0xbb, '=', '+', '}'},
      {14, 0x12, 'E', 'e', 'E', 0x20ac},
      {33, 0x1a, 0xdd, '^', 0xa8}, {30, 0x1b, 0xba, '$', 0xa3, 0xa4}, {39, 0x28, 0xc0, 0xf9, '%'},
      {42, 0x2b, 0xdc, '*', 0x3bc}, {46, 0x32, 0xbc, ',', '?'}, {43, 0x33, 0xbe, ';', '.'}, {47, 0x34, 0xbf, ':', '/'},
      {44, 0x35, 0xdf, '!', 0xa7}, {10, 0x29, 0xde, 0xb2}, {50, 0x56, 0xe2, '<', '>'},
    };
    static const unsigned short e_circ[] = {0xea, 0}, a_grave[] = {0xe0, 0}, n_tilde[] = {0xf1, 0};
    static const struct typing_case typing[] = {
      {{{0xdd, 0}, {'E', 0}}, e_circ},
      {{{'7', ALTGR}, {'A', 0}}, a_grave},      /* AltGr+7 is the dead grave accent */
      {{{'2', ALTGR}, {'N', 0}}, n_tilde},      /* AltGr+2 the dead tilde */
    };
    check(k->altgr, "AltGr", 0, k->altgr, 1);
    check_keys(k, keys, sizeof(keys) / sizeof(*keys));
    check_typing(k, typing, sizeof(typing) / sizeof(*typing));
    free(k);
  }

  context = "German (QWERTZ), ISO keyboard";
  if ((k = load("com.apple.keylayout.German", ISO))) {
    static const struct key_case keys[] = {
      {16, 0x15, 'Z', 'z', 'Z'}, {6, 0x2c, 'Y', 'y', 'Y'}, {12, 0x10, 'Q', 'q', 'Q', 0xab}, {0, 0x1e, 'A', 'a', 'A'},
      {18, 0x02, '1', '1', '!'}, {19, 0x03, '2', '2', '"'}, {20, 0x04, '3', '3', 0xa7}, {26, 0x08, '7', '7', '/', '|', '\\'},
      {28, 0x09, '8', '8', '(', '{'}, {25, 0x0a, '9', '9', ')', '}'}, {23, 0x06, '5', '5', '%', '['},
      {22, 0x07, '6', '6', '&', ']'}, {37, 0x26, 'L', 'l', 'L', '@'},
      /* kbdgr's virtual keys */
      {27, 0x0c, 0xdb, 0xdf, '?'}, {24, 0x0d, 0xdd, 0xb4, '`'}, {33, 0x1a, 0xba, 0xfc, 0xdc}, {30, 0x1b, 0xbb, '+', '*'},
      {41, 0x27, 0xc0, 0xf6, 0xd6}, {39, 0x28, 0xde, 0xe4, 0xc4}, {42, 0x2b, 0xbf, '#', '\''},
      {43, 0x33, 0xbc, ',', ';'}, {47, 0x34, 0xbe, '.', ':'}, {44, 0x35, 0xbd, '-', '_'},
      {10, 0x29, 0xdc, '^', 0xb0}, {50, 0x56, 0xe2, '<', '>'},
    };
    static const unsigned short e_acute[] = {0xe9, 0}, a_circ[] = {0xe2, 0}, U_uml[] = {0xdc, 0};
    static const struct typing_case typing[] = {
      {{{0xdd, 0}, {'E', 0}}, e_acute}, {{{0xdc, 0}, {'A', 0}}, a_circ}, {{{0xba, CAPS}}, U_uml},
    };
    check(k->altgr, "AltGr", 0, k->altgr, 1);
    check_keys(k, keys, sizeof(keys) / sizeof(*keys));
    check_typing(k, typing, sizeof(typing) / sizeof(*typing));
    free(k);
  }

  context = "Dvorak, ANSI keyboard";
  if ((k = load("com.apple.keylayout.Dvorak", ANSI))) {
    static const struct key_case keys[] = {
      /* kbddv: the virtual key follows the letter, the scan code the place */
      {0, 0x1e, 'A', 'a', 'A'}, {1, 0x1f, 'O', 'o', 'O'}, {2, 0x20, 'E', 'e', 'E'}, {3, 0x21, 'U', 'u', 'U'},
      {12, 0x10, 0xde, '\'', '"'}, {13, 0x11, 0xbc, ',', '<'}, {14, 0x12, 0xbe, '.', '>'}, {15, 0x13, 'P', 'p', 'P'},
      {6, 0x2c, 0xba, ';', ':'}, {7, 0x2d, 'Q', 'q', 'Q'}, {46, 0x32, 'M', 'm', 'M'}, {41, 0x27, 'S', 's', 'S'},
      {27, 0x0c, 0xdb, '[', '{'}, {24, 0x0d, 0xdd, ']', '}'}, {33, 0x1a, 0xbf, '/', '?'}, {30, 0x1b, 0xbb, '=', '+'},
      {39, 0x28, 0xbd, '-', '_'}, {18, 0x02, '1', '1', '!'},
    };
    check(!k->altgr, "AltGr", 0, k->altgr, 0);
    check_keys(k, keys, sizeof(keys) / sizeof(*keys));
    free(k);
  }

  context = "ABC - AZERTY, ISO keyboard";
  if ((k = load("com.apple.keylayout.ABC-AZERTY", ISO))) {
    static const struct key_case keys[] = {
      {12, 0x10, 'A', 'a', 'A'}, {0, 0x1e, 'Q', 'q', 'Q'}, {13, 0x11, 'Z', 'z', 'Z'}, {6, 0x2c, 'W', 'w', 'W'},
      {41, 0x27, 'M', 'm', 'M'}, {18, 0x02, '1', '&', '1'}, {29, 0x0b, '0', 0xe0, '0'},
    };
    check_keys(k, keys, sizeof(keys) / sizeof(*keys));
    free(k);
  }

  context = "Russian, ANSI keyboard";
  if ((k = load("com.apple.keylayout.Russian", ANSI))) {
    /* a layout without Latin letters keeps the virtual keys of a US keyboard, as kbdru does */
    static const struct key_case keys[] = {
      {0, 0x1e, 'A', 0x444, 0x424}, {12, 0x10, 'Q', 0x439, 0x419}, {13, 0x11, 'W', 0x446, 0x426},
      {6, 0x2c, 'Z', 0x44f, 0x42f}, {18, 0x02, '1', '1', '!'},
    };
    check_keys(k, keys, sizeof(keys) / sizeof(*keys));
    free(k);
  }

  /* what is not a keyboard layout is refused */
  context = "bad blobs";
  {
    struct wsd_keymap bad = {WSD_KEYMAP_VERSION, 0, 0, WSD_KEYMAP_KEYS, WSD_KEYMAP_LEVELS, 100000, {0}};
    check(!obelisk_keymap_create(&bad, sizeof(bad), 1), "truncated", 0, 1, 0);
    check(!obelisk_keymap_create(&bad, 10, 1), "too short", 0, 1, 0);
    bad.version = 99;
    check(!obelisk_keymap_create(&bad, sizeof(bad), 1), "version", 0, 1, 0);
  }

  printf("%d checks, %d failed\n", checks, failures);
  return failures != 0;
}
