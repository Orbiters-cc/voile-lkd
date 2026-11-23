/* trace.c: logging and syscall tracing. Owner: core.
 * Lines are formatted into a stack buffer and written with one write(2), so they never interleave and
 * the code needs no lock. Guest memory is never read here: pointers print as hex values. */
#include <fcntl.h>
#include <stdarg.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

#include "lkd_internal.h"
#include "task.h"

static _Atomic int g_trace;     /* 0 off, 1 completion lines, 2 entry and completion lines */
static _Atomic int g_log_enosys;

int lkd_trace_level(void) { return atomic_load_explicit(&g_trace, memory_order_relaxed); }
int lkd_enosys_logging(void) { return atomic_load_explicit(&g_log_enosys, memory_order_relaxed); }
void lkd_trace_enable(int on) { atomic_store(&g_trace, on); }
void lkd_trace_set_enosys_logging(int on) { atomic_store(&g_log_enosys, on); }

void lkd_trace_init_from_env(void)
{
    const char *v = getenv("LKD_TRACE");
    if (v && *v && strcmp(v, "0")) atomic_store(&g_trace, atoi(v) >= 2 ? 2 : 1);
    v = getenv("LKD_LOG_ENOSYS");
    if (v && *v && strcmp(v, "0")) atomic_store(&g_log_enosys, 1);
}

static void emit(const char *buf, int n)
{
    if (n <= 0) return;
    if (n > 1000) n = 1000;
    ssize_t r;
    do { r = write(2, buf, (size_t)n); } while (r < 0 && errno == EINTR);
}

void lkd_log(const char *fmt, ...)
{
    char buf[1024];
    int n = snprintf(buf, sizeof buf, "lkd: ");
    va_list ap;
    va_start(ap, fmt);
    n += vsnprintf(buf + n, sizeof buf - (size_t)n - 1, fmt, ap);
    va_end(ap);
    if (n > (int)sizeof buf - 2) n = (int)sizeof buf - 2;
    buf[n++] = '\n';
    emit(buf, n);
}

/* ---- the recent-event ring (lkd_internal.h) ------------------------------------------------------- */

#define RING_BYTES ((size_t)(LKD_EVENT_RING_LINES + 1) * LKD_EVENT_LINE)

static char *g_ring;                       /* line 0: 8-byte counter, then the header text; a host fork
                                            * keeps the mapping (MAP_SHARED): one ring for the family */
static _Atomic int g_ring_state;           /* 0 not yet, 1 being set up, 2 ready (g_ring may still be NULL) */

static char *ring_map(void)
{
    const char *path = getenv("LKD_EVENT_RING");
    if (path && *path) {
        int fd = open(path, O_RDWR | O_CREAT | O_CLOEXEC, 0600);
        if (fd >= 0) {
            struct stat st;
            if (fstat(fd, &st) == 0 && S_ISREG(st.st_mode) &&
                ((size_t)st.st_size == RING_BYTES || (st.st_size == 0 && ftruncate(fd, (off_t)RING_BYTES) == 0))) {
                void *m = mmap(NULL, RING_BYTES, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
                close(fd);
                if (m != MAP_FAILED) return m;
            } else {
                close(fd);
            }
        }
    }
    void *m = mmap(NULL, RING_BYTES, PROT_READ | PROT_WRITE, MAP_SHARED | MAP_ANON, -1, 0);
    return m == MAP_FAILED ? NULL : m;
}

static char *ring(void)
{
    int s = atomic_load_explicit(&g_ring_state, memory_order_acquire);
    if (s == 2) return g_ring;
    int zero = 0;
    if (atomic_compare_exchange_strong(&g_ring_state, &zero, 1)) {
        char *m = ring_map();
        if (m) {
            char *h = m + 8;
            if (h[0] != 'l') {
                int n = snprintf(h, LKD_EVENT_LINE - 8, "lkd event ring v1: %d lines of %d bytes; sort lines 2+",
                                 LKD_EVENT_RING_LINES, LKD_EVENT_LINE);
                memset(h + n, ' ', (size_t)(LKD_EVENT_LINE - 8 - n - 1));
                h[LKD_EVENT_LINE - 8 - 1] = '\n';
            }
        }
        g_ring = m;
        atomic_store_explicit(&g_ring_state, 2, memory_order_release);
        return m;
    }
    return NULL; /* another thread is mapping it: this event is only lost while the ring is being created */
}

const char *lkd_event_ring(size_t *lines)
{
    if (lines) *lines = LKD_EVENT_RING_LINES;
    return ring();
}

void lkd_event(const char *fmt, ...)
{
    char *m = ring();
    if (!m) return;
    _Atomic uint64_t *head = (_Atomic uint64_t *)(void *)m;
    uint64_t k = atomic_fetch_add(head, 1);
    char line[LKD_EVENT_LINE + 1];
    int n = snprintf(line, sizeof line, "%012llu %012lld %6d ", (unsigned long long)k,
                     (long long)(lkd_host_mono_ns() / 1000000), (int)getpid());
    va_list ap;
    va_start(ap, fmt);
    int w = vsnprintf(line + n, sizeof line - (size_t)n, fmt, ap);
    va_end(ap);
    n = w < 0 ? n : n + w;
    if (n > LKD_EVENT_LINE - 1) n = LKD_EVENT_LINE - 1;
    for (int i = 0; i < n; i++) if (line[i] == '\n') line[i] = ' ';
    memset(line + n, ' ', (size_t)(LKD_EVENT_LINE - 1 - n));
    line[LKD_EVENT_LINE - 1] = '\n';
    memcpy(m + (size_t)(1 + k % LKD_EVENT_RING_LINES) * LKD_EVENT_LINE, line, LKD_EVENT_LINE);
}

static int fmt_args(char *buf, size_t cap, const lkd_sysreq *rq)
{
    int last = -1;
    for (int i = 0; i < 6; i++) if (rq->a[i]) last = i;
    int n = 0;
    buf[0] = 0;
    for (int i = 0; i <= last; i++)
        n += snprintf(buf + n, cap - (size_t)n, "%s0x%llx", i ? ", " : "", (unsigned long long)rq->a[i]);
    return n;
}

void lkd_trace_entry(lkd_task *t, const lkd_sysreq *rq)
{
    char args[200], line[320];
    fmt_args(args, sizeof args, rq);
    const char *name = lkd_syscall_name(rq->nr);
    int n = snprintf(line, sizeof line, "[%d] -> %s(%s)\n", t ? t->tid : 0, name ? name : "?", args);
    emit(line, n);
}

void lkd_trace_exit(lkd_task *t, const lkd_sysreq *rq, int64_t ret)
{
    char args[200], res[64], line[360];
    fmt_args(args, sizeof args, rq);
    const char *name = lkd_syscall_name(rq->nr);
    if (ret < 0 && ret >= -LX_MAX_ERRNO) {
        const char *en = lkd_errno_name((int)-ret);
        snprintf(res, sizeof res, "%lld (%s)", (long long)ret, en ? en : "?");
    } else if (ret >= 0 && ret < (1ll << 32)) {
        snprintf(res, sizeof res, "%lld", (long long)ret);
    } else {
        snprintf(res, sizeof res, "0x%llx", (unsigned long long)ret);
    }
    char nm[24];
    if (!name) { snprintf(nm, sizeof nm, "syscall_%llu", (unsigned long long)rq->nr); name = nm; }
    int n = snprintf(line, sizeof line, "[%d] %s(%s) = %s\n", t ? t->tid : 0, name, args, res);
    emit(line, n);
}
