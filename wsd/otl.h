/*
 * otl.h - host timeline recorder: where a frame's time goes, across the render server, DXMT and wsd.
 * SPDX-License-Identifier: MIT
 *
 * One file, the same in three repositories (Orbiters-cc/neptune, dxmt and voile-lkd): tools/timeline/otl.py of
 * Orbiters-cc/voile-lkd reads what it writes and knows the kinds below.
 *
 * Off by default. It is on when OBELISK_TIMELINE names a folder, which only the host programs are given: launch.sh
 * takes the variables away before it starts anything else. Off, otl_init() is one getenv(), every other use is one load
 * of otl_on and a branch, and there is no thread, file, descriptor or memory of it.
 *
 * On: each thread that records has a ring of OTL_RING records of 64 bytes, numbers only (all rings are one mapping made by
 * otl_init(); a thread's first record allocates nothing), which one writer thread takes every 50 ms into
 * <folder>/otl-<role>-<pid>.bin. A full ring loses its thread's record and counts it: OTL_LOST says in which interval.
 * Every 10 s the writer adds a summary and the histograms of that window.
 *
 * Bounds. All recorders of one folder (one start of a game) share one budget, OBELISK_TIMELINE_MB (1024 by default), kept
 * in <folder>/otl-session: nothing is written that was not taken from it first, the last record included, so the folder
 * never holds more; at most OTL_FILES recorders write in it; none takes more once the disk has less than 2 GiB free. A
 * recorder that gets no more, or whose write fails, ends for good: its file is cut to its last whole record, ends with
 * OTL_END where that can be written (its room is taken with the header), and otl_on is 0 from then on. Nothing
 * of it ever blocks, ends or fails the program it is in.
 * OBELISK_TIMELINE_PASSES=N (1 to 1000) adds the encoders and their GPU times for every Nth frame of DXMT (dxmt_otl.h).
 *
 * Times are CLOCK_UPTIME_RAW nanoseconds, the clock of Metal's GPU times, of CAMetalDrawable.presentedTime and of
 * the guest's CLOCK_MONOTONIC under LKD.
 *
 * Exactly one translation unit of each image defines OTL_IMPLEMENTATION before including this.
 */
#ifndef ORBITERS_OTL_H
#define ORBITERS_OTL_H

#include <stdint.h>
#include <time.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Record kinds (format 2). v[] in order; what is not named is 0. An id (of an export, event, arm, frame, queue, client,
 * plane) is a count of its process: never reused, unlike a pointer or a handle. */
enum otl_kind {
  OTL_THREAD = 1,   /* a: slot; v: thread id, then up to 32 bytes of its name */
  OTL_SUMMARY = 2,  /* a: window; v: start, end, records kept, lost in the window, lost in all, file bytes */
  OTL_HIST = 3,     /* a: histogram | part << 8 (three parts); v: 12 counts of 32 bits: see otl_bucket() */
  OTL_LOST = 4,     /* records were lost; v: not before, not after, how many, lost in all */
  OTL_END = 5,      /* the last record; a: enum otl_end; v: records kept, lost in all, file bytes, errno, recorders refused */

  /* the render server's ring (role npt) */
  OTL_N_EXPORT = 16,      /* a: context; v: the image's pointer, its memory's identity, width<<32|height, format, export id */
  OTL_N_SIGNAL = 18,      /* a: context; v: start, fence pointer, value, decode ns since the last Signal of this ring,
                             time of the first work since it, commands since it (t is the end) */
  OTL_N_COUNTS = 19,      /* follows OTL_N_SIGNAL; v: draws, maps, unmaps, updates, flushes, copies<<32|target changes */
  OTL_N_FENCE = 20,       /* a fence of an event ring arrived; a: ring; v: fence id, context */
  OTL_N_PAIR = 21,        /* a fence paired with its arm; a: ring; v: fence id, event id, context, arm id */
  OTL_N_RETIRE = 22,      /* a: ring; v: fence id, time the wait returned, time the poll began, context, what poll said
                             (1 signalled, 0 timed out, below 0 failed) (t: after publishing) */
  OTL_N_FLUSH = 23,       /* ID3D11DeviceContext::Flush decoded; v: start (t is the end) */
  OTL_V_RETIRE = 24,      /* virgl_test_server (role vtest); a: ring; v: fence id, its own id, context (t: before it wakes the
                             client) */
  OTL_N_GONE = 26,        /* the guest let go of an exported image; v: pointer, export id */
  OTL_N_FRAME = 27,       /* follows OTL_N_SIGNAL after CopyResource into an exported image since the last Signal of this
                             ring; a: such copies; v: fence pointer, value, export id of the last, its start, its end, frame id */
  OTL_N_EVENT = 28,       /* an event was made; v: event id, its HANDLE, context */
  OTL_N_ARM = 29,         /* a: ring; v: arm id, event id, context */

  /* DXMT (role dxmt); key: queue id << 48 | chunk */
  OTL_D_READY = 32,       /* a chunk was handed to the encode thread; a: 1 when its encoders are recorded; v: queue id, chunk,
                             initializer event it waits for, frame group (ended by each Signal) */
  OTL_D_ENCODE = 33,      /* v: chunk, woken, executed, flushed, pipeline wait ns, queue id (t: committed) */
  OTL_D_DONE = 34,        /* a: status; v: chunk, GPU start, GPU end, kernel start, kernel end, queue id (t: seen done) */
  OTL_D_SIGNAL = 35,      /* ID3D11DeviceContext4::Signal; v: chunk, fence pointer, value, Metal event, queue id, frame group */
  OTL_D_SEOC = 36,        /* SetEventOnCompletion; v: fence pointer, value, HANDLE, Metal event */
  OTL_D_NOTIFY = 37,      /* the shared event's listener ran; v: Metal event, value, HANDLE (t: before it wakes the waiter) */
  OTL_D_PIPELINE = 38,    /* the encode thread waited for a pipeline; a: 0 graphics, 1 geometry, 2 tessellation,
                             3 compute; v: start, chunk (t is the end) */
  OTL_D_INIT = 39,        /* the initializer queue committed; v: event value */
  OTL_D_INIT_DONE = 40,   /* a: status; v: event value, GPU start, GPU end */
  OTL_D_PASS = 41,        /* a render pass as encoded; a: index in the command buffer | colours << 16 | depth << 24 |
                             stencil << 25; v: key, width<<32|height, colours 0 to 3 as otl_attachment() */
  OTL_D_PASS_DS = 42,     /* follows OTL_D_PASS that has depth or stencil; v: key, depth, stencil, target array length */
  OTL_D_BLIT = 43,        /* a: index; v: key */
  OTL_D_COMPUTE = 44,     /* a: index; v: key */
  OTL_D_OPS = 45,         /* what an encoder held, at its end; a: index | type << 16 (0 render, 1 compute, 2 blit); v: key,
                             draws or dispatches or copies, pixels copied between textures, commands */
  OTL_D_PASS_TIME = 46,   /* GPU timestamps of an encoder; a: index | type << 16 | status << 24; v: key, then for a render
                             encoder start and end of the vertex stage, start and end of the fragment stage, else start
                             and end (0, 0): in the GPU's clock (OTL_D_CLOCK); ~0 or 0 is no time */
  OTL_D_QUEUE = 47,       /* a: 1 made, 0 ended; v: queue id */
  OTL_D_PASS_SKIP = 48,   /* encoders without GPU times; a: enum otl_skip; v: key, how many */
  OTL_D_CLOCK = 49,       /* v: the device's CPU and GPU timestamps of one moment, uptime before and after it, queue id */
  OTL_D_COMMIT = 50,      /* follows OTL_D_READY of its chunk; a: the call that committed it | what had asked for a commit before
                             it << 8 (enum otl_why, 0: nothing had) | a render pass was open << 16; v: queue id, chunk, frame group,
                             when it was asked for, what the commit waited for a free chunk in ns, the open pass's colour 0 */
  OTL_D_PASS_ENDED = 51,  /* a render pass ended in the context, before the optimiser; a: enum otl_why; v: queue id, chunk, frame
                             group, colour 0 as otl_attachment(), its texture, depth's texture (DXMT's pointers) */
  OTL_D_PASS_ID = 52,     /* follows OTL_D_PASS; a: as it; v: key, colour 0's texture, depth's texture (Metal's, of a view the
                             texture it is of), what kept it from joining a later encoder (enum otl_stop) */
  OTL_D_STALL = 53,       /* GetData(DONOTFLUSH) of an event query not there the 64 times before flushed something, or should have; a: 1 its event had been
                             handed to the encoder (nothing to rescue) | 2 a chunk was committed | 4 and the event still was
                             not | 8 OBELISK_DXMT_QUERY_RESCUE=once | 16 by the rescue thread, for a look that could not;
                             v: queue id, chunk, the event, the last event handed over before, after, frame group */
  OTL_D_QUERIES = 54,     /* follows OTL_D_SIGNAL, or a look 200 ms after the one before: since that one, one snapshot with OTL_D_LOOKS after
                             it; a: 1 as OTL_D_STALL's 8 | 2 the device's lock is on | 4 at a look, not at a Signal; v: queue id,
                             frame group, queries ended (16 bits each: event, disjoint, timestamp, occlusion), events ended with
                             nothing new recorded | rescues left to the next look << 32, looks at event and disjoint queries not
                             there (first 64 | the others << 32), of those others flags DONOTFLUSH and nothing to rescue, so nothing
                             done | looks that found them there << 32 */
  OTL_D_QUERY = 55,       /* an event or disjoint query was ended (at most 128 of these in 100 ms); a: 1 disjoint | 2 with nothing new
                             recorded, so at a moment that was already marked | 4 in a command list, as it was executed; v: queue id,
                             query id << 32 | which End of it, its event, the chunk its marker is in (with 2: at the latest), frame group */
  OTL_D_QUERY_SEEN = 56,  /* a look found it there (t: after the look); a: 1 ended again, never seen; v: queue id, as OTL_D_QUERY, the
                             start of the first look, the end of the last look that did not find it (0: none), looks, its event */
  OTL_D_LOOKS = 57,       /* follows OTL_D_QUERIES; a: as it; v: queue id, frame group, looks at event and disjoint queries | S_FALSE
                             answers << 32, S_OK answers | rescues << 32 (with the switch: chunks a look or the rescue thread committed;
                             without: command buffers committed by a look after the first 64), 16 bits each: rescues not
                             made at once for the device's lock, for a full queue, rescues whose uploads the rescue thread commits,
                             chunks the rescue thread committed; the longest look in ns | the longest rescue on a looking thread in ns << 32, both with DONOTFLUSH */

  /* wsd (role wsd) */
  OTL_W_ATTACH = 64,      /* a buffer was attached; a: buffer; v: memory identity, width<<32|height, format, client id */
  OTL_W_RX = 65,          /* PRESENT or PRESENT_REGION; a: window | replaced << 31 | region << 30; v: buffer, serial,
                             client time, receive time, serial replaced, client id << 32 | plane id */
  OTL_W_TICK = 66,        /* a: window | state << 16 (enum otl_tick); v: the link's timestamp, its target timestamp,
                             its duration, plane id (t: when the callback ran) */
  OTL_W_DRAW = 67,        /* a: window | scaled << 28 | on arrival << 29 | region << 30 | redisplay << 31; v: buffer, serial, nextDrawable entry, exit, drawable
                             id (~0: none), plane id (t: committed) */
  OTL_W_GPU = 68,         /* a: as OTL_W_DRAW; v: serial, GPU start, GPU end, kernel start, kernel end, plane id (t: the callback) */
  OTL_W_SHOWN = 69,       /* a: as OTL_W_DRAW; v: serial, presented time or 0, drawable id, plane id (t: the callback) */
  OTL_W_RELEASE = 70,     /* a: buffer | shown << 31; v: serial, plane id */
  OTL_W_DETACH = 71,      /* a: buffer; v: client id */
};

enum otl_end { OTL_END_EXIT = 0, OTL_END_BUDGET = 1, OTL_END_WRITE = 2, OTL_END_SPACE = 3 };
enum otl_skip { OTL_SKIP_SLOT = 1, OTL_SKIP_MANY = 2, OTL_SKIP_UNSUPPORTED = 3, OTL_SKIP_FAILED = 4, OTL_SKIP_RESOLVE = 5 };
/* Why a pass ended or a command buffer was committed: the Direct3D 11 call. */
enum otl_why {
  OTL_WHY_OTHER = 0, OTL_WHY_TARGETS = 1, OTL_WHY_HAZARD = 2, OTL_WHY_CLEAR_COLOUR = 3, OTL_WHY_CLEAR_DEPTH = 4,
  OTL_WHY_CLEAR_VIEW = 5, OTL_WHY_CLEAR_UAV = 6, OTL_WHY_DRAW = 7, OTL_WHY_DISPATCH = 8, OTL_WHY_COPY = 9,
  OTL_WHY_UPLOAD = 10, OTL_WHY_READBACK = 11, OTL_WHY_RESOLVE = 12, OTL_WHY_END_EVENT = 13, OTL_WHY_END_TIMESTAMP = 14,
  OTL_WHY_END_OCCLUSION = 15, OTL_WHY_GETDATA = 16, /* GetData that may flush, its query not there */
  OTL_WHY_GETDATA_STALL = 17, /* GetData(DONOTFLUSH) of an event query that was not there the 64 times before */
  OTL_WHY_FLUSH = 18, OTL_WHY_SIGNAL = 19, OTL_WHY_WAIT = 20, OTL_WHY_MAP_STAGING = 21, OTL_WHY_KEYED_MUTEX = 22,
  OTL_WHY_COMMAND_LIST = 23, OTL_WHY_IDLE = 24, OTL_WHY_PRESENT = 25, OTL_WHY_STATE = 26, OTL_WHY_STAGING_WRITE = 27,
  OTL_WHY_UPSCALE = 28,
};
/* What an encoder could not be put beyond, so that it was not put together with a later one. */
enum otl_stop {
  OTL_STOP_END = 0, /* nothing: the command buffer's end */
  OTL_STOP_RENDER = 1, OTL_STOP_COMPUTE = 2, OTL_STOP_BLIT = 3, OTL_STOP_CLEAR = 4, OTL_STOP_RESOLVE = 5, /* needs what it made */
  OTL_STOP_EVENT = 6, OTL_STOP_TIMESTAMP = 7, OTL_STOP_OTHER = 8,
  OTL_STOP_SAME = 16, /* added: a render pass of the same targets that could not be joined to it */
};
enum otl_tick { OTL_TICK_EMPTY = 0, OTL_TICK_PENDING = 1, OTL_TICK_HIDDEN = 2, OTL_TICK_REDISPLAY = 3 };

/* Histograms of a window, per process; 36 buckets, two per octave from 8 us (bucket 0 is below it). */
enum otl_hist_id {
  OTL_H_A = 0, /* npt: decode time per frame; dxmt: encode per chunk; wsd: nextDrawable */
  OTL_H_B = 1, /* npt: retire after the wake; dxmt: commit to GPU start; wsd: receive to tick */
  OTL_H_C = 2, /* dxmt: GPU time of a chunk; wsd: commit to shown */
  OTL_H_D = 3, /* dxmt: pipeline wait; wsd: interval between shown frames */
  OTL_HISTS = 4,
};
#define OTL_BUCKETS 36

extern int otl_on;
/* OBELISK_TIMELINE_PASSES while the timeline is on: the encoders of every Nth frame, 0 for none. */
extern int otl_passes;

#ifdef __APPLE__
static inline int otl_active(void) { return __builtin_expect(otl_on, 0); }
static inline uint64_t otl_now(void) { return clock_gettime_nsec_np(CLOCK_UPTIME_RAW); }

/* Reads OBELISK_TIMELINE once per process; role names the file. Call it after the last fork. */
void otl_init(const char *role);
void otl_put(uint64_t t, uint16_t kind, uint32_t a, uint64_t v0, uint64_t v1, uint64_t v2, uint64_t v3, uint64_t v4,
             uint64_t v5);
void otl_hist(int id, uint64_t ns);
/* What names the memory at `offset` behind a descriptor in every process that holds it: 0 when it cannot be told. */
uint64_t otl_identity(int fd, uint64_t offset);
/* A new id of this process. */
uint64_t otl_id(void);
#else /* macOS alone records */
static inline int otl_active(void) { return 0; }
static inline uint64_t otl_now(void) { return 0; }
static inline void otl_init(const char *role) { (void)role; }
static inline void otl_put(uint64_t t, uint16_t kind, uint32_t a, uint64_t v0, uint64_t v1, uint64_t v2, uint64_t v3,
                           uint64_t v4, uint64_t v5) {
  (void)t; (void)kind; (void)a; (void)v0; (void)v1; (void)v2; (void)v3; (void)v4; (void)v5;
}
static inline void otl_hist(int id, uint64_t ns) { (void)id; (void)ns; }
static inline uint64_t otl_identity(int fd, uint64_t offset) { (void)fd; (void)offset; return 0; }
static inline uint64_t otl_id(void) { return 0; }
#endif

/* One attachment in a word: format 16 | samples 8 | load 4 | store 4 | resolved 1 | memoryless 1 | width 15 | height 15 */
static inline uint64_t otl_attachment(uint32_t format, uint32_t samples, uint32_t load, uint32_t store, int resolved,
                                      int memoryless, uint32_t width, uint32_t height) {
  return (uint64_t)(format & 0xffff) | (uint64_t)(samples & 0xff) << 16 | (uint64_t)(load & 0xf) << 24 |
         (uint64_t)(store & 0xf) << 28 | (uint64_t)(resolved != 0) << 32 | (uint64_t)(memoryless != 0) << 33 |
         (uint64_t)(width & 0x7fff) << 34 | (uint64_t)(height & 0x7fff) << 49;
}

#ifdef __cplusplus
}
#endif

#if defined(OTL_IMPLEMENTATION) && defined(__APPLE__)

#include <errno.h>
#include <fcntl.h>
#include <libproc.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/mman.h>
#include <sys/mount.h>
#include <sys/proc_info.h>
#include <sys/qos.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <unistd.h>

struct otl_record { uint64_t t; uint16_t kind, thread; uint32_t a; uint64_t v[6]; };
_Static_assert(sizeof(struct otl_record) == 64, "a record is 64 bytes");

#define OTL_VERSION 2
#define OTL_RING 32768u /* records, a power of two: 2 MiB */
#define OTL_THREADS 64
#define OTL_READY 8 /* rings whose pages are made at the start */
#define OTL_TICK_US 50000
#define OTL_WINDOW_NS 10000000000ull
#define OTL_TAIL 4096u       /* taken with the header: the last summary and OTL_END */
#define OTL_GRANT (2u << 20) /* taken from the session's budget at a time */
#define OTL_FILES 64
#ifndef OTL_FREE
#define OTL_FREE (2ull << 30)
#endif

struct otl_ring {
  _Atomic(uint64_t) head, tail; /* head: written by the thread; tail: by the writer */
  _Atomic(uint64_t) lost;
  _Atomic(int) state; /* 0 free, 1 a thread's, 2 left by its thread and not yet drained */
  uint64_t thread;
  char name[32];
  struct otl_record *records;
};

/* <folder>/otl-session, changed under flock(): what is left of the session's budget. */
struct otl_session { char magic[4]; uint32_t version; uint64_t limit, used; uint32_t files, refused; };

int otl_on, otl_passes;
static struct otl_ring otl_rings[OTL_THREADS];
static _Atomic(uint64_t) otl_unslotted; /* records of threads beyond OTL_THREADS */
static _Atomic(uint64_t) otl_ids;
static _Atomic(uint32_t) otl_hists[OTL_HISTS][OTL_BUCKETS];
static int otl_leaving, otl_left; /* the process ends: the writer is asked to, and has, finished (under otl_turn) */
static pthread_mutex_t otl_turn = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t otl_turns = PTHREAD_COND_INITIALIZER;
static pthread_key_t otl_key;
static pthread_once_t otl_once = PTHREAD_ONCE_INIT;
static const char *otl_role;
static int otl_fd = -1, otl_session_fd = -1, otl_errno;
static uint64_t otl_bytes, otl_granted, otl_limit, otl_refused; /* the writer's alone */

static void otl_leave(void *p) {
  struct otl_ring *r = (struct otl_ring *)p;
  if (r) atomic_store_explicit(&r->state, 2, memory_order_release);
}

enum otl_take { OTL_TAKEN, OTL_LATER, OTL_NO_BUDGET, OTL_NO_SPACE };

/* Takes up to `want` bytes of the session's budget, at least `least`; `file`: for one recorder more. */
static enum otl_take otl_take(uint64_t want, uint64_t least, int file) {
  struct otl_session s;
  struct statfs fs;
  if (flock(otl_session_fd, LOCK_EX | LOCK_NB)) return OTL_LATER; /* held for microseconds: at the next tick */
  enum otl_take got = OTL_NO_BUDGET;
  ssize_t n = pread(otl_session_fd, &s, sizeof(s), 0);
  if (n == 0) { /* the first of the session */
    memset(&s, 0, sizeof(s));
    memcpy(s.magic, "OTLS", 4);
    s.version = OTL_VERSION;
    s.limit = otl_limit;
    s.used = sizeof(s);
  }
  if ((n == 0 || n == (ssize_t)sizeof(s)) && !memcmp(s.magic, "OTLS", 4) && s.version == OTL_VERSION) {
    uint64_t left = s.limit > s.used ? s.limit - s.used : 0;
    if (want > left) want = left;
    if (fstatfs(otl_session_fd, &fs) || (uint64_t)fs.f_bavail * fs.f_bsize < OTL_FREE) got = OTL_NO_SPACE;
    else if (want >= least && want && (!file || s.files < OTL_FILES)) got = OTL_TAKEN;
    if (got == OTL_TAKEN) { s.used += want; s.files += file != 0; }
    else if (file) s.refused++;
    otl_refused = s.refused;
    if (pwrite(otl_session_fd, &s, sizeof(s), 0) != (ssize_t)sizeof(s) && got == OTL_TAKEN) got = OTL_NO_SPACE;
    if (got == OTL_TAKEN) otl_granted += want;
  }
  flock(otl_session_fd, LOCK_UN);
  return got;
}

/* All of it, or the file as it was: a record is never split. */
static int otl_write(const void *p, size_t n) {
  const char *at = (const char *)p;
  size_t left = n;
  while (left) {
    ssize_t w = write(otl_fd, at, left);
    if (w < 0 && errno == EINTR) continue;
    if (w <= 0) {
      otl_errno = w < 0 ? errno : EIO;
      if (ftruncate(otl_fd, (off_t)otl_bytes) == 0) lseek(otl_fd, (off_t)otl_bytes, SEEK_SET);
      return 0;
    }
    at += w;
    left -= (size_t)w;
  }
  otl_bytes += n;
  return 1;
}

static int otl_write_record(uint16_t kind, uint32_t a, const void *v, size_t n) {
  struct otl_record r;
  memset(&r, 0, sizeof(r));
  r.t = otl_now();
  r.kind = kind;
  r.thread = 0xffff;
  r.a = a;
  memcpy(r.v, v, n < sizeof(r.v) ? n : sizeof(r.v));
  return otl_write(&r, sizeof(r));
}

/* Whether `n` bytes more may be written, the tail's room aside. */
static enum otl_take otl_room(uint64_t n) {
  if (otl_bytes + n + OTL_TAIL <= otl_granted) return OTL_TAKEN;
  return otl_take(n > OTL_GRANT ? n : OTL_GRANT, sizeof(struct otl_record) * 16, 0);
}

struct otl_counts { uint64_t kept, lost; int end; };

/* What the rings hold goes to the file; what there is no room for now stays in them. */
static void otl_drain(struct otl_counts *c) {
  uint64_t lost = atomic_load_explicit(&otl_unslotted, memory_order_relaxed);
  for (int i = 0; i < OTL_THREADS; i++) {
    struct otl_ring *r = &otl_rings[i];
    int state = atomic_load_explicit(&r->state, memory_order_acquire);
    if (state) {
      uint64_t head = atomic_load_explicit(&r->head, memory_order_acquire);
      uint64_t tail = atomic_load_explicit(&r->tail, memory_order_relaxed);
      while (tail != head && !c->end) {
        uint64_t at = tail & (OTL_RING - 1), n = head - tail, bytes;
        if (n > OTL_RING - at) n = OTL_RING - at;
        enum otl_take room = otl_room((n + 1) * sizeof(struct otl_record));
        if (room == OTL_LATER) break;
        if (room != OTL_TAKEN) { c->end = room == OTL_NO_SPACE ? OTL_END_SPACE : OTL_END_BUDGET; break; }
        if (!r->thread) { /* announced with its first record */
          uint64_t v[6] = {0};
          r->thread = 1;
          memcpy(&v[1], r->name, sizeof(r->name));
          if (!otl_write_record(OTL_THREAD, (uint32_t)i, v, sizeof(v))) { c->end = OTL_END_WRITE; break; }
        }
        bytes = (otl_granted - OTL_TAIL - otl_bytes) / sizeof(struct otl_record);
        if (n > bytes) n = bytes; /* (a grant smaller than asked for, the budget's last) */
        if (!n) continue;
        if (!otl_write(&r->records[at], (size_t)n * sizeof(struct otl_record))) { c->end = OTL_END_WRITE; break; }
        c->kept += n;
        tail += n;
      }
      atomic_store_explicit(&r->tail, tail, memory_order_release);
      if (state == 2 && tail == head) {
        r->thread = 0;
        atomic_store_explicit(&r->state, 0, memory_order_release);
      }
    }
    lost += atomic_load_explicit(&r->lost, memory_order_relaxed);
  }
  c->lost = lost;
}

static void *otl_writer(void *unused) {
  (void)unused;
  pthread_setname_np("otl-writer");
  pthread_set_qos_class_self_np(QOS_CLASS_DEFAULT, 0); /* utility sleeps far beyond what a ring holds on a busy Mac */
  struct otl_counts c = {0, 0, 0};
  uint64_t start = otl_now(), drained = start, kept = 0, before = 0, told = 0;
  uint32_t window = 0;
  for (int leaving = 0; !leaving && !c.end;) {
    const struct timespec tick = {0, OTL_TICK_US * 1000};
    pthread_mutex_lock(&otl_turn);
    if (!otl_leaving) pthread_cond_timedwait_relative_np(&otl_turns, &otl_turn, &tick);
    leaving = otl_leaving;
    pthread_mutex_unlock(&otl_turn);
    uint64_t now = otl_now();
    otl_drain(&c);
    if (!c.end && c.lost != told) {
      uint64_t v[6] = {drained, otl_now(), c.lost - told, c.lost, 0, 0};
      enum otl_take room = otl_room(sizeof(struct otl_record));
      if (room == OTL_TAKEN && otl_write_record(OTL_LOST, 0, v, sizeof(v))) told = c.lost;
    }
    drained = now;
    if (now - start < OTL_WINDOW_NS && !leaving) continue;
    if (c.end) break;
    uint64_t v[6] = {start, now, c.kept - kept, c.lost - before, c.lost, otl_bytes};
    if (otl_room(sizeof(struct otl_record) * (1 + OTL_HISTS * 3)) == OTL_TAKEN) {
      int whole = otl_write_record(OTL_SUMMARY, window, v, sizeof(v));
      for (uint32_t h = 0; h < OTL_HISTS && whole; h++)
        for (uint32_t part = 0; part < 3 && whole; part++) {
          uint32_t n[12];
          for (int i = 0; i < 12; i++)
            n[i] = atomic_exchange_explicit(&otl_hists[h][part * 12 + (uint32_t)i], 0, memory_order_relaxed);
          whole = otl_write_record(OTL_HIST, h | part << 8, n, sizeof(n));
        }
      if (!whole) c.end = OTL_END_WRITE;
    }
    window++;
    start = now;
    before = c.lost;
    kept = c.kept;
  }
  /* The end: nothing records from here on, and what the rings still hold is lost and said. */
  __atomic_store_n(&otl_on, 0, __ATOMIC_RELEASE);
  if (!c.end) otl_drain(&c);
  for (int i = 0; i < OTL_THREADS; i++)
    c.lost += atomic_load(&otl_rings[i].head) - atomic_load(&otl_rings[i].tail);
  uint64_t v[6] = {drained, otl_now(), c.lost - told, c.lost, 0, 0};
  uint64_t end[6] = {c.kept, c.lost, otl_bytes, (uint64_t)otl_errno, otl_refused, 0};
  if (c.lost != told) otl_write_record(OTL_LOST, 0, v, sizeof(v));
  otl_write_record(OTL_END, (uint32_t)c.end, end, sizeof(end));
  close(otl_fd);
  close(otl_session_fd);
  pthread_mutex_lock(&otl_turn);
  otl_left = 1;
  pthread_cond_broadcast(&otl_turns);
  pthread_mutex_unlock(&otl_turn);
  return NULL;
}

/* An orderly exit gives the writer its last turn, for a tenth of a second at most. */
static void otl_finish(void) {
  const struct timespec most = {0, 100000000};
  pthread_mutex_lock(&otl_turn);
  otl_leaving = 1;
  pthread_cond_broadcast(&otl_turns);
  if (!otl_left) pthread_cond_timedwait_relative_np(&otl_turns, &otl_turn, &most);
  pthread_mutex_unlock(&otl_turn);
}

static long otl_number(const char *name, long least, long most, long otherwise) {
  const char *text = getenv(name);
  char *end = NULL;
  long n = text && *text ? strtol(text, &end, 10) : otherwise;
  return (end && *end) || n < least || n > most ? otherwise : n;
}

static void otl_start(void) {
  const char *folder = getenv("OBELISK_TIMELINE");
  if (!folder || *folder != '/') return;
  otl_limit = (uint64_t)otl_number("OBELISK_TIMELINE_MB", 1, 8192, 1024) << 20;
  const int passes = (int)otl_number("OBELISK_TIMELINE_PASSES", 0, 1000, 0);
  char path[1024];
  if (snprintf(path, sizeof(path), "%s/otl-session", folder) >= (int)sizeof(path)) return;
  otl_session_fd = open(path, O_RDWR | O_CREAT | O_CLOEXEC | O_NOFOLLOW, 0600);
  if (otl_session_fd < 0) return;
  enum otl_take took = OTL_LATER;
  for (int i = 0; i < 100 && took == OTL_LATER; i++) {
    took = otl_take(64 + OTL_TAIL + OTL_GRANT, 64 + OTL_TAIL + sizeof(struct otl_record) * 16, 1);
    if (took == OTL_LATER) usleep(500);
  }
  snprintf(path, sizeof(path), "%s/otl-%s-%d.bin", folder, otl_role, (int)getpid());
  if (took == OTL_TAKEN) otl_fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
  struct timeval tv;
  gettimeofday(&tv, NULL);
  struct { char magic[4]; uint32_t version, pid, passes; char role[16]; uint64_t uptime, wall_us, continuous, limit; } head;
  memset(&head, 0, sizeof(head));
  _Static_assert(sizeof(head) == 64, "the header is one record long");
  memcpy(head.magic, "OTL1", 4);
  head.version = OTL_VERSION;
  head.pid = (uint32_t)getpid();
  head.passes = (uint32_t)passes;
  strncpy(head.role, otl_role, sizeof(head.role) - 1);
  head.uptime = otl_now();
  head.continuous = clock_gettime_nsec_np(CLOCK_MONOTONIC_RAW); /* the guest's QueryPerformanceCounter */
  head.wall_us = (uint64_t)tv.tv_sec * 1000000u + (uint64_t)tv.tv_usec;
  head.limit = otl_limit;
  pthread_t t;
  const size_t ring = OTL_RING * sizeof(struct otl_record);
  char *rings = MAP_FAILED;
  if (otl_fd >= 0) rings = (char *)mmap(NULL, OTL_THREADS * ring, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0);
  int ready = rings != MAP_FAILED && otl_write(&head, sizeof(head)) && !pthread_key_create(&otl_key, otl_leave);
  if (ready) {
    for (int i = 0; i < OTL_THREADS; i++) otl_rings[i].records = (struct otl_record *)(rings + (size_t)i * ring);
    memset(rings, 0, OTL_READY * ring);
    otl_passes = passes;
    ready = !pthread_create(&t, NULL, otl_writer, NULL);
  }
  if (!ready) { /* not a recorder: no file without one */
    if (otl_fd >= 0) { unlink(path); close(otl_fd); }
    if (rings != MAP_FAILED) munmap(rings, OTL_THREADS * ring);
    close(otl_session_fd);
    otl_passes = 0;
    return;
  }
  pthread_detach(t);
  atexit(otl_finish);
  __atomic_store_n(&otl_on, 1, __ATOMIC_RELEASE);
}

void otl_init(const char *role) {
  /* the once belongs to the process that calls it: the render server forks one worker per client, then this */
  otl_role = role;
  pthread_once(&otl_once, otl_start);
}

uint64_t otl_id(void) { return atomic_fetch_add_explicit(&otl_ids, 1, memory_order_relaxed) + 1; }

static struct otl_ring *otl_ring_of_thread(void) {
  struct otl_ring *r = (struct otl_ring *)pthread_getspecific(otl_key);
  if (r) return r;
  for (int i = 0; i < OTL_THREADS; i++) {
    int none = 0;
    r = &otl_rings[i];
    if (!atomic_compare_exchange_strong_explicit(&r->state, &none, 1, memory_order_acq_rel, memory_order_relaxed)) continue;
    memset(r->name, 0, sizeof(r->name));
    pthread_getname_np(pthread_self(), r->name, sizeof(r->name));
    pthread_setspecific(otl_key, r);
    return r;
  }
  return NULL;
}

void otl_put(uint64_t t, uint16_t kind, uint32_t a, uint64_t v0, uint64_t v1, uint64_t v2, uint64_t v3, uint64_t v4,
             uint64_t v5) {
  if (!otl_active()) return;
  struct otl_ring *r = otl_ring_of_thread();
  if (!r) { atomic_fetch_add_explicit(&otl_unslotted, 1, memory_order_relaxed); return; }
  uint64_t head = atomic_load_explicit(&r->head, memory_order_relaxed);
  if (head - atomic_load_explicit(&r->tail, memory_order_acquire) >= OTL_RING) {
    atomic_fetch_add_explicit(&r->lost, 1, memory_order_relaxed);
    return;
  }
  struct otl_record *e = &r->records[head & (OTL_RING - 1)];
  e->t = t;
  e->kind = kind;
  e->thread = (uint16_t)(r - otl_rings);
  e->a = a;
  e->v[0] = v0; e->v[1] = v1; e->v[2] = v2; e->v[3] = v3; e->v[4] = v4; e->v[5] = v5;
  atomic_store_explicit(&r->head, head + 1, memory_order_release);
}

void otl_hist(int id, uint64_t ns) {
  if (!otl_active()) return;
  int b = 0;
  if (ns >= 8000) {
    uint64_t q = ns / 8000;
    int octave = 63 - __builtin_clzll(q);
    /* the half octave: whether q is at or above 1.5 times its octave's start */
    b = 1 + octave * 2 + (q * 2 >= (3ull << octave) ? 1 : 0);
    if (b >= OTL_BUCKETS) b = OTL_BUCKETS - 1;
  }
  atomic_fetch_add_explicit(&otl_hists[id][b], 1, memory_order_relaxed);
}

static uint64_t otl_fnv(uint64_t h, const void *p, size_t n) {
  for (const unsigned char *c = (const unsigned char *)p; n; n--, c++) h = (h ^ *c) * 0x100000001b3ull;
  return h;
}

uint64_t otl_identity(int fd, uint64_t offset) {
  struct stat st;
  uint64_t h = 0xcbf29ce484222325ull;
  struct pshm_fdinfo info;
  h = otl_fnv(h, &offset, sizeof(offset));
  /* POSIX shared memory has no inode; the kernel keeps the name it was made under (DXMT's is random), unlinked or not */
  if (proc_pidfdinfo(getpid(), fd, PROC_PIDFDPSHMINFO, &info, sizeof(info)) == (int)sizeof(info))
    return otl_fnv(h, info.pshminfo.pshm_name, strnlen(info.pshminfo.pshm_name, sizeof(info.pshminfo.pshm_name)));
  if (fstat(fd, &st)) return 0;
  h = otl_fnv(h, &st.st_dev, sizeof(st.st_dev));
  return otl_fnv(h, &st.st_ino, sizeof(st.st_ino));
}

#endif /* OTL_IMPLEMENTATION */
#endif /* ORBITERS_OTL_H */
