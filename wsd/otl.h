/*
 * otl.h - host timeline recorder: where a frame's time goes, across the render server, DXMT and wsd.
 * SPDX-License-Identifier: MIT
 *
 * One file, the same in three repositories (Orbiters-cc/neptune, dxmt and voile-lkd): tools/timeline/otl.py of
 * Orbiters-cc/voile-lkd reads what it writes and knows the kinds below.
 *
 * Off by default. It is on when OBELISK_TIMELINE names a folder, which only the host programs are given: launch.sh
 * takes the variable away before it starts the game. Off, otl_init() is one getenv(), every other use is one load of
 * otl_on and a branch, and there is no thread, file, descriptor or memory of it.
 *
 * On: each thread that records has a fixed ring of 8192 records of 64 bytes, numbers only, which one writer thread
 * takes every 20 ms into <folder>/otl-<role>-<pid>.bin. A full ring loses its thread's record
 * and counts it; a file at its cap (OBELISK_TIMELINE_MB, 256 by default) takes summaries alone, and what it did not
 * take is counted. Every 10 s the writer adds one summary (records, records lost) and the histograms of that window.
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

/* Record kinds. v[] in order; what is not named is 0. */
enum otl_kind {
  OTL_THREAD = 1,   /* a: slot; v: thread id, then up to 32 bytes of its name */
  OTL_SUMMARY = 2,  /* a: window; v: start, end, records kept, lost in the window, lost in all, file bytes */
  OTL_HIST = 3,     /* a: histogram | part << 8 (three parts); v: 12 counts of 32 bits: see otl_bucket() */
  OTL_LOST = 4,     /* v: records lost in all so far, when that grew */

  /* the render server's ring (role npt) */
  OTL_N_EXPORT = 16,      /* a: context; v: the image's pointer, its memory's identity, width<<32|height, format */
  OTL_N_COPY = 17,        /* CopyResource; v: start, destination pointer, source pointer (t is the end) */
  OTL_N_SIGNAL = 18,      /* a: context; v: start, fence pointer, value, decode ns since the last Signal of this ring,
                             time of the first work since it, commands since it (t is the end) */
  OTL_N_COUNTS = 19,      /* follows OTL_N_SIGNAL; v: draws, maps, unmaps, updates, flushes, copies<<32|target changes */
  OTL_N_FENCE = 20,       /* a fence of an event ring arrived; a: ring; v: fence id */
  OTL_N_PAIR = 21,        /* a fence paired with its event; a: ring; v: fence id, event handle */
  OTL_N_RETIRE = 22,      /* a: ring; v: fence id, time the wait returned, time the poll began (t: after publishing) */
  OTL_N_FLUSH = 23,       /* ID3D11DeviceContext::Flush decoded; v: start (t is the end) */
  OTL_V_RETIRE = 24,      /* virgl_test_server (role vtest); a: ring; v: fence id (t: before it wakes the client) */

  /* DXMT (role dxmt) */
  OTL_D_READY = 32,       /* a chunk was handed to the encode thread; v: queue, chunk, initializer event it waits for */
  OTL_D_ENCODE = 33,      /* a: encoders; v: chunk, woken, executed, flushed, pipeline wait ns, queue (t: committed) */
  OTL_D_DONE = 34,        /* a: status; v: chunk, GPU start, GPU end, kernel start, kernel end, queue (t: seen done) */
  OTL_D_SIGNAL = 35,      /* ID3D11DeviceContext4::Signal; v: chunk, fence pointer, value, Metal event, queue */
  OTL_D_SEOC = 36,        /* SetEventOnCompletion; v: fence pointer, value, HANDLE, Metal event */
  OTL_D_NOTIFY = 37,      /* the shared event's listener ran; v: Metal event, value (t: before it wakes the waiter) */
  OTL_D_PIPELINE = 38,    /* the encode thread waited for a pipeline; a: 0 graphics, 1 geometry, 2 tessellation,
                             3 compute; v: start (t is the end) */
  OTL_D_INIT = 39,        /* the initializer queue committed; v: event value */
  OTL_D_INIT_DONE = 40,   /* v: event value, GPU start, GPU end */
  OTL_D_PASS = 41,        /* a render pass as encoded; a: index in the command buffer | colours << 16 | depth << 24 |
                             stencil << 25; v: chunk, width<<32|height, colours 0 to 3 as otl_attachment() */
  OTL_D_PASS_DS = 42,     /* follows OTL_D_PASS that has depth or stencil; v: chunk, depth, stencil, target array length */
  OTL_D_BLIT = 43,        /* a: index; v: chunk */
  OTL_D_COMPUTE = 44,     /* a: index; v: chunk */
  OTL_D_OPS = 45,         /* what an encoder held, at its end; a: index | type << 16 (0 render, 1 compute, 2 blit); v: chunk,
                             draws or dispatches or copies, pixels copied between textures, commands */
  OTL_D_PASS_TIME = 46,   /* with OBELISK_TIMELINE_PASSES=1 (GPU timestamps at the stage boundaries of each encoder, which
                             are part of what Metal then runs); a: index | type << 16; v: chunk, start and end of the vertex
                             stage, start and end of the fragment stage (blit, compute: start and end) */

  /* wsd (role wsd) */
  OTL_W_ATTACH = 64,      /* a: buffer; v: memory identity, width<<32|height, format */
  OTL_W_RX = 65,          /* PRESENT or PRESENT_REGION; a: window | replaced << 31 | region << 30; v: buffer, serial,
                             client time, receive time, serial replaced */
  OTL_W_TICK = 66,        /* a: window | state << 16 (enum otl_tick); v: the link's timestamp, its target timestamp,
                             its duration (t: when the callback ran) */
  OTL_W_DRAW = 67,        /* a: window | region << 30 | redisplay << 31; v: buffer, serial, nextDrawable entry, exit, drawable id
                             (t: committed) */
  OTL_W_GPU = 68,         /* a: window; v: serial, GPU start, GPU end, kernel start, kernel end (t: the callback) */
  OTL_W_SHOWN = 69,       /* a: window | redisplay << 31; v: serial, presented time or 0, drawable id (t: the callback) */
  OTL_W_RELEASE = 70,     /* a: buffer | shown << 31; v: serial */
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

static inline int otl_active(void) { return __builtin_expect(otl_on, 0); }
static inline uint64_t otl_now(void) { return clock_gettime_nsec_np(CLOCK_UPTIME_RAW); }

/* Reads OBELISK_TIMELINE once per process; role names the file. Call it after the last fork. */
void otl_init(const char *role);
void otl_put(uint64_t t, uint16_t kind, uint32_t a, uint64_t v0, uint64_t v1, uint64_t v2, uint64_t v3, uint64_t v4,
             uint64_t v5);
void otl_hist(int id, uint64_t ns);
/* What names the memory behind a descriptor in every process that holds it: 0 when it cannot be told. */
uint64_t otl_identity(int fd);

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

#ifdef OTL_IMPLEMENTATION

#include <errno.h>
#include <fcntl.h>
#include <libproc.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/proc_info.h>
#include <sys/qos.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <unistd.h>

struct otl_record { uint64_t t; uint16_t kind, thread; uint32_t a; uint64_t v[6]; };
_Static_assert(sizeof(struct otl_record) == 64, "a record is 64 bytes");

#define OTL_RING 8192u /* records, a power of two */
#define OTL_THREADS 96
#define OTL_TICK_US 20000
#define OTL_WINDOW_NS 10000000000ull

struct otl_ring {
  _Atomic(uint64_t) head, tail; /* head: written by the thread; tail: by the writer */
  _Atomic(uint64_t) lost;
  _Atomic(int) state; /* 0 free, 1 a thread's, 2 left by its thread and not yet drained */
  uint64_t thread;
  char name[32];
  struct otl_record *records;
};

int otl_on;
static struct otl_ring otl_rings[OTL_THREADS];
static _Atomic(uint64_t) otl_unslotted; /* records of threads beyond OTL_THREADS */
static _Atomic(uint32_t) otl_hists[OTL_HISTS][OTL_BUCKETS];
static pthread_key_t otl_key;
static pthread_once_t otl_once = PTHREAD_ONCE_INIT;
static const char *otl_role;
static int otl_fd = -1;
static uint64_t otl_bytes, otl_cap;

static void otl_leave(void *p) {
  struct otl_ring *r = (struct otl_ring *)p;
  if (r) atomic_store_explicit(&r->state, 2, memory_order_release);
}

/* All of it or nothing: a record is never split, a short file is never read past its last whole record. */
static void otl_write(const void *p, size_t n) {
  const char *at = (const char *)p;
  otl_bytes += n;
  while (n) {
    ssize_t w = write(otl_fd, at, n);
    if (w < 0 && errno == EINTR) continue;
    if (w <= 0) return;
    at += w;
    n -= (size_t)w;
  }
}

static void otl_write_record(uint16_t kind, uint32_t a, const void *v, size_t n) {
  struct otl_record r;
  memset(&r, 0, sizeof(r));
  r.t = otl_now();
  r.kind = kind;
  r.thread = 0xffff;
  r.a = a;
  memcpy(r.v, v, n < sizeof(r.v) ? n : sizeof(r.v));
  otl_write(&r, sizeof(r));
}

static uint64_t otl_drain(uint64_t *kept, uint64_t *capped) {
  uint64_t lost = atomic_load_explicit(&otl_unslotted, memory_order_relaxed);
  for (int i = 0; i < OTL_THREADS; i++) {
    struct otl_ring *r = &otl_rings[i];
    int state = atomic_load_explicit(&r->state, memory_order_acquire);
    if (state) {
      uint64_t head = atomic_load_explicit(&r->head, memory_order_acquire);
      uint64_t tail = atomic_load_explicit(&r->tail, memory_order_relaxed);
      if (head != tail && !r->thread && otl_bytes < otl_cap) { /* announced with its first record */
        uint64_t v[6] = {0};
        r->thread = 1;
        memcpy(&v[1], r->name, sizeof(r->name));
        otl_write_record(OTL_THREAD, (uint32_t)i, v, sizeof(v));
      }
      while (tail != head) {
        uint64_t at = tail & (OTL_RING - 1), n = head - tail;
        if (n > OTL_RING - at) n = OTL_RING - at;
        if (otl_bytes + n * sizeof(struct otl_record) > otl_cap) {
          *capped += n;
        } else {
          otl_write(&r->records[at], (size_t)n * sizeof(struct otl_record));
          *kept += n;
        }
        tail += n;
      }
      atomic_store_explicit(&r->tail, tail, memory_order_release);
      if (state == 2) {
        r->thread = 0;
        atomic_store_explicit(&r->state, 0, memory_order_release);
      }
    }
    lost += atomic_load_explicit(&r->lost, memory_order_relaxed);
  }
  return lost;
}

static void *otl_writer(void *unused) {
  (void)unused;
  pthread_setname_np("otl-writer");
  pthread_set_qos_class_self_np(QOS_CLASS_DEFAULT, 0); /* utility sleeps far beyond what a ring holds on a busy Mac */
  uint64_t start = otl_now(), kept = 0, capped = 0, before = 0, told = 0;
  uint32_t window = 0;
  for (;;) {
    usleep(OTL_TICK_US);
    uint64_t lost = otl_drain(&kept, &capped) + capped, now = otl_now();
    if (lost != told && otl_bytes < otl_cap) { /* past the cap, the summaries alone say it */
      otl_write_record(OTL_LOST, 0, &lost, sizeof(lost));
      told = lost;
    }
    if (now - start < OTL_WINDOW_NS) continue;
    uint64_t v[6] = {start, now, kept, lost - before, lost, otl_bytes};
    otl_write_record(OTL_SUMMARY, window, v, sizeof(v));
    for (uint32_t h = 0; h < OTL_HISTS; h++)
      for (uint32_t part = 0; part < 3; part++) {
        uint32_t c[12];
        for (int i = 0; i < 12; i++)
          c[i] = atomic_exchange_explicit(&otl_hists[h][part * 12 + (uint32_t)i], 0, memory_order_relaxed);
        otl_write_record(OTL_HIST, h | part << 8, c, sizeof(c));
      }
    window++;
    start = now;
    before = lost;
    kept = 0;
  }
  return NULL;
}

static void otl_start(void) {
  const char *folder = getenv("OBELISK_TIMELINE"), *cap = getenv("OBELISK_TIMELINE_MB");
  if (!folder || !*folder) return;
  long mb = cap ? strtol(cap, NULL, 10) : 256;
  if (mb < 1 || mb > 4096) mb = 256;
  otl_cap = (uint64_t)mb << 20;
  char path[1024];
  if (snprintf(path, sizeof(path), "%s/otl-%s-%d.bin", folder, otl_role, (int)getpid()) >= (int)sizeof(path)) return;
  otl_fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
  if (otl_fd < 0) return;
  struct timeval tv;
  gettimeofday(&tv, NULL);
  struct { char magic[4]; uint32_t version, pid, reserved; char role[16]; uint64_t uptime, wall_us, continuous, pad; } head;
  memset(&head, 0, sizeof(head));
  _Static_assert(sizeof(head) == 64, "the header is one record long");
  memcpy(head.magic, "OTL1", 4);
  head.version = 1;
  head.pid = (uint32_t)getpid();
  strncpy(head.role, otl_role, sizeof(head.role) - 1);
  head.uptime = otl_now();
  head.continuous = clock_gettime_nsec_np(CLOCK_MONOTONIC_RAW); /* the guest's QueryPerformanceCounter */
  head.wall_us = (uint64_t)tv.tv_sec * 1000000u + (uint64_t)tv.tv_usec;
  otl_write(&head, sizeof(head));
  pthread_t t;
  if (pthread_key_create(&otl_key, otl_leave)) return;
  if (pthread_create(&t, NULL, otl_writer, NULL)) return;
  pthread_detach(t);
  __atomic_store_n(&otl_on, 1, __ATOMIC_RELEASE);
}

void otl_init(const char *role) {
  /* the once belongs to the process that calls it: the render server forks one worker per client, then this */
  otl_role = role;
  pthread_once(&otl_once, otl_start);
}

static struct otl_ring *otl_ring_of_thread(void) {
  struct otl_ring *r = (struct otl_ring *)pthread_getspecific(otl_key);
  if (r) return r;
  for (int i = 0; i < OTL_THREADS; i++) {
    int none = 0;
    r = &otl_rings[i];
    if (!atomic_compare_exchange_strong_explicit(&r->state, &none, 1, memory_order_acquire, memory_order_relaxed)) continue;
    if (!r->records) r->records = (struct otl_record *)calloc(OTL_RING, sizeof(struct otl_record));
    if (!r->records) { atomic_store(&r->state, 0); return NULL; }
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

uint64_t otl_identity(int fd) {
  struct stat st;
  uint64_t h = 0xcbf29ce484222325ull;
  struct pshm_fdinfo info;
  /* POSIX shared memory has no inode; the kernel keeps the name it was made under (DXMT's is random), unlinked or not */
  if (proc_pidfdinfo(getpid(), fd, PROC_PIDFDPSHMINFO, &info, sizeof(info)) == (int)sizeof(info))
    return otl_fnv(h, info.pshminfo.pshm_name, strnlen(info.pshminfo.pshm_name, sizeof(info.pshminfo.pshm_name)));
  if (fstat(fd, &st)) return 0;
  h = otl_fnv(h, &st.st_dev, sizeof(st.st_dev));
  return otl_fnv(h, &st.st_ino, sizeof(st.st_ino));
}

#endif /* OTL_IMPLEMENTATION */
#endif /* ORBITERS_OTL_H */
