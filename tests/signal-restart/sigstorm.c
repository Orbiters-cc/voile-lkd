/* sigstorm: threads run self-checking code (sigstorm_k.S) while another thread sends them signals whose handler does
 * nothing. A signal must be invisible to the interrupted code; any wrong result, lost register, moved stack pointer or
 * fault is a defect of asynchronous delivery (state reconstruction at the interruption, or resumption).
 * Usage: sigstorm KINDS SECONDS INTERVAL_US      KINDS: one letter per worker (the table below), eight at most
 *        INTERVAL_US 0: as fast as possible; "-" as INTERVAL: no signals at all (control).
 * Exit status: 0 nothing wrong, 1 a worker saw a wrong result, 3 a fault, 2 the test could not run. */
#include "nolibc.h"
struct wk { volatile int stop; int pad; volatile u64 iters; void *cell; u64 aux[2]; int kind; volatile int rc; struct thr th; volatile int tid; volatile int done; };
int k_callret(struct wk *), k_rmw(struct wk *), k_big(struct wk *), k_bigctl(struct wk *), k_merge(struct wk *), k_carry(struct wk *), k_avx(struct wk *),
    k_x87(struct wk *), k_mmx(struct wk *), k_df(struct wk *), k_pairs(struct wk *), k_mixed(struct wk *);
static const struct { char c; const char *name; int (*fn)(struct wk *); } K[] = {
    {'c', "callret", k_callret}, {'r', "rmw", k_rmw}, {'b', "big", k_big}, {'B', "bigctl", k_bigctl}, {'k', "merge", k_merge}, {'a', "carry", k_carry},
    {'v', "avx", k_avx}, {'x', "x87", k_x87}, {'m', "mmx", k_mmx}, {'d', "df", k_df}, {'p', "pairs", k_pairs}, {'i', "mixed", k_mixed} };
static int kindex(int c) { for (int j = 0; j < (int)(sizeof K / sizeof *K); j++) if (K[j].c == c) return j; return -1; }
static struct wk W[8]; static int NW; static volatile u64 handled; static volatile int quit;

/* The last interrupted states of each worker, for the report of a failure. */
struct tr { u64 rip, rsp, rax, rbx, rsi, rdi; }; static struct tr TR[8][8]; static volatile u32 TRN[8];
extern char leaf_a[], leaf_b[];
static void on_usr1(int s, void *i, void *u) {
    (void)s; (void)i; struct uctx *c = u; int tid = (int)SC(SYS_gettid);
    for (int j = 0; j < NW; j++) if (W[j].tid == tid) { struct tr *t = &TR[j][TRN[j]++ & 7]; t->rip = c->rip; t->rsp = c->rsp; t->rax = c->rax; t->rbx = c->rbx; t->rsi = c->rsi; t->rdi = c->rdi; }
    /* The handler's own registers are the handler's: nothing of them may reach the interrupted code. */
    __asm__ volatile("fninit; vzeroall; std; cld" ::: "xmm0", "xmm1", "xmm2", "xmm3", "xmm4", "xmm5", "xmm6", "xmm7", "xmm8", "xmm9", "xmm10", "xmm11", "xmm12", "xmm13", "xmm14", "xmm15");
    __sync_fetch_and_add(&handled, 1);
}
static void show_trace(int j) {
    for (u32 k = 0; k < 8 && k < TRN[j]; k++) { struct tr *t = &TR[j][(TRN[j] - 1 - k) & 7];
        const char *n = "?"; u64 b = 0;
        if (t->rip >= (u64)leaf_a && t->rip < (u64)leaf_b) { n = "leaf_a"; b = (u64)leaf_a; }
        else if (t->rip >= (u64)leaf_b) { n = "leaf_b"; b = (u64)leaf_b; }
        for (int q = 0; q < (int)(sizeof K / sizeof *K); q++) if (t->rip >= (u64)K[q].fn && (u64)K[q].fn > b) { b = (u64)K[q].fn; n = K[q].name; }
        pf("WITNESS   worker %d signal -%d interrupted %s+0x%lx rsp=%lx rax=%lx rbx=%lx rsi=%lx rdi=%lx\n", j, k, n, t->rip - b, t->rsp, t->rax, t->rbx, t->rsi, t->rdi); }
}
static void on_fault(int s, void *i, void *u) {
    struct uctx *c = u; struct siginfo *si = i; int tid = (int)SC(SYS_gettid), k = -1;
    for (int j = 0; j < NW; j++) if (W[j].tid == tid) k = W[j].kind;
    pf("WITNESS fault sig=%d kind=%s rip=%lx rsp=%lx addr=%lx rax=%lx rbx=%lx rcx=%lx rdx=%lx rsi=%lx rdi=%lx r8=%lx r12=%lx handled=%lu\n", s,
       kindex(k) < 0 ? "?" : K[kindex(k)].name, c->rip, c->rsp, si->addr, c->rax, c->rbx, c->rcx,
       c->rdx, c->rsi, c->rdi, c->r8, c->r12, handled);
    die(3);
}
static void worker(void *a) {
    struct wk *w = a; w->tid = (int)SC(SYS_gettid);
    int rc = K[kindex(w->kind)].fn(w);
    w->rc = rc; w->done = 1;
    if (rc) quit = 1;
}
static u64 atou(const char *s) { u64 v = 0; while (*s >= '0' && *s <= '9') v = v * 10 + (u64)(*s++ - '0'); return v; }
int main(int argc, char **argv) {
    const char *kinds = argc > 1 ? argv[1] : "crb"; u64 secs = argc > 2 ? atou(argv[2]) : 10;
    int nosig = argc > 3 && argv[3][0] == '-'; u64 ival = argc > 3 && !nosig ? atou(argv[3]) : 200;
    sigact(SIGUSR1, on_usr1, SA_RESTART); sigact(SIGSEGV, on_fault, 0); sigact(SIGBUS, on_fault, 0); sigact(SIGILL, on_fault, 0);
    int pid = (int)SC(SYS_getpid);
    for (NW = 0; kinds[NW] && NW < 8; NW++) {
        struct wk *w = &W[NW]; w->kind = kinds[NW]; if (kindex(w->kind) < 0) { pf("WITNESS no kernel %d\n", w->kind); return 2; }
        u8 *cell = map(0, 16384, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS);
        for (int i = 0; i < 16384; i++) cell[i] = (u8)(i * 7 + NW);
        w->cell = cell;
        if (thr_start(&w->th, worker, w)) { pf("WITNESS clone failed\n"); return 2; }
    }
    for (int j = 0; j < NW; j++) while (!W[j].tid) sleep_us(100);
    u64 t0 = now_ns(), sent = 0;
    while (!quit && now_ns() - t0 < secs * 1000000000ull) {
        if (nosig) { sleep_us(1000); continue; }
        for (int j = 0; j < NW; j++) if (!W[j].done) { SC(SYS_tgkill, pid, W[j].tid, SIGUSR1); sent++; }
        if (ival) sleep_us(ival); else SC(SYS_sched_yield);
    }
    for (int j = 0; j < NW; j++) W[j].stop = 1;
    int bad = 0;
    for (int j = 0; j < NW; j++) {
        u64 t1 = now_ns(); while (!W[j].done && now_ns() - t1 < 3000000000ull) sleep_us(1000);
        if (!W[j].done) { pf("WITNESS worker %d kind=%d never stopped\n", j, W[j].kind); bad++; continue; }
        if (W[j].rc) { bad++; show_trace(j); }
        pf("WITNESS worker %d kind=%s iters=%lu rc=%d aux=%lu,%lu\n", j, K[kindex(W[j].kind)].name, W[j].iters, W[j].rc, W[j].aux[0], W[j].aux[1] & 0xffffffff);
    }
    pf("WITNESS sigstorm kinds=%s secs=%lu sent=%lu handled=%lu bad=%d\n", kinds, secs, sent, handled, bad);
    return bad ? 1 : 0;
}
