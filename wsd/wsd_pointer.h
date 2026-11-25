/*
 * wsd_pointer.h - the pointer channel: what wsd tells any program of the same user about the pointer, on a socket of its
 * own (wsd --pointer-socket PATH; PROTOCOL.md, "Pointer channel"). It is apart from wsd_protocol.h, which wsd and the Wine
 * driver share. The server speaks, the reader listens: a reader that sends a single byte is disconnected. Framing as
 * wsd_protocol.h: struct wsd_pointer_hdr, then len payload bytes; little-endian, naturally aligned. A reader skips the
 * types it does not know, and what a longer payload holds after the fields it knows.
 */
#ifndef WSD_POINTER_H
#define WSD_POINTER_H

#include <stdint.h>

#define WSD_POINTER_VERSION 1

enum {
  WSD_POINTER_HELLO = 1, /* wsd_pointer_hello: once, first */
  WSD_POINTER_STATE = 2, /* wsd_pointer_state: after the hello, then at each change of any of its fields */
  WSD_POINTER_MOVE = 3,  /* wsd_pointer_move: a relative move the game was sent, only while the pointer is held */
};

struct wsd_pointer_hdr { uint32_t type, len; };

struct wsd_pointer_hello { uint32_t version, server_pid; };

enum {
  WSD_POINTER_NONE = 0, /* no game window, or its game does not capture the mouse (it shows the cursor) */
  WSD_POINTER_FREE = 1, /* the game captures the mouse but does not confine the pointer: it is the person's, over the game
                         * and over any window above it; the game is sent places */
  WSD_POINTER_HELD = 2, /* the game confines the pointer and wsd holds it: macOS's pointer stands still, hidden; the game is
                         * sent relative moves */
  WSD_POINTER_AWAY = 3, /* the game confines the pointer but does not have it now: its window is not the key window, or it
                         * shows no frames; macOS's pointer is the person's */
};

enum {
  WSD_POINTER_WINDOW_KEY = 1,        /* the game's window has the keyboard */
  WSD_POINTER_WINDOW_FULLSCREEN = 2,
  WSD_POINTER_CURSOR_HIDDEN = 4,     /* the game asked for no cursor (it may draw its own) */
  WSD_POINTER_WINDOW_SHOWN = 8,      /* the window is on screen (not in the Dock, not hidden) */
  WSD_POINTER_STALLED = 16,          /* it has shown no frame for 5 s */
};

struct wsd_pointer_state {
  uint32_t state;         /* WSD_POINTER_NONE.. */
  uint32_t flags;         /* WSD_POINTER_WINDOW_KEY.. */
  uint32_t window_number; /* the game window's number at macOS's window server (CGWindowID), 0 without a window */
  uint32_t client_pid;    /* the engine process the window belongs to, 0 without a window */
  double x, y, width, height; /* the window's content in global display points (top-left origin, as CGEvent locations) */
  double scale_x, scale_y;    /* the game's pixels per point */
  int32_t clip_x, clip_y;     /* the rectangle the game confines the pointer to, in its pixels from the content's top */
  uint32_t clip_width, clip_height; /* left; 0 x 0 when it confines it to nothing */
  uint64_t time_ns;           /* CLOCK_UPTIME_RAW of the change */
};

struct wsd_pointer_move {
  float dx, dy;     /* as the game was sent them (points of raw motion, y down) */
  uint64_t time_ns; /* CLOCK_UPTIME_RAW of the move */
};

#endif
