/* How long a signal waits for a thread that runs one loop shape of shapes_k.S for ever.
 *   shapes NAME [COUNT [BUDGET_MS [P99_US [MAX_US]]]]
 * One worker in the loop; the main thread sends SIGUSR1 (tgkill) COUNT times, each after the one before was handled, and stops after
 * BUDGET_MS in all. A sender that the scheduler took off its core while it sent says nothing about the thread (sender_off). What a signal that is still waiting then has waited counts for the maximum.
 * Exit status 0: every signal sent was handled, the 99th percentile and the maximum are under their limits. */
#include "nolibc.h"
#define L(X) X(jmp) X(pause) X(spinflag) X(spinreg) X(tas) X(cas) X(spinyield) X(pairs) X(pairs8) X(pushret) X(callret) \
    X(callempty) X(movalu) X(carry) X(noops) X(sse) X(x87) X(x87copy) X(x87reg) X(x87sin) X(mmx) X(avx) X(rep16) X(rep4k) \
    X(rep1m) X(stos1m) X(scas1m) X(div) X(indirect) X(linked) X(vcall) X(rdtsc) X(plain) X(jcc) X(loop) X(jrcxz) X(nest) \
    X(fib) X(deep) X(retchain) X(leaf) X(table) X(chain) X(long) X(x87long) X(x87atan) X(x87int) X(movsq1m) X(over1m) \
    X(back1m) X(stosd4m) X(cmps1m) X(lods1m) X(avxmem) X(cpuid) X(getpid) X(sleep) X(futex) X(smc)
#define D(n) void s_##n(void *);
L(D)
static const struct { const char *n; void (*f)(void *); } B[] = {
#define E(n) {#n, s_##n},
L(E) };
static volatile int tid; static volatile u64 got, seq; static struct thr T; static void (*fn)(void *);
static void on_usr1(int s, void *i, void *u) { (void)s; (void)i; (void)u; got = now_ns(); seq++; }
static void worker(void *m) { tid = (int)SC(SYS_gettid); fn(m); }
static u64 atou(const char *s) { u64 v = 0; while (*s >= '0' && *s <= '9') v = v * 10 + (u64)(*s++ - '0'); return v; }
static u64 lat[4096];
int main(int argc, char **argv) {
    if (argc < 2) return 2;
    u64 count = argc > 2 ? atou(argv[2]) : 200, budget = (argc > 3 ? atou(argv[3]) : 5000) * 1000000ul, lim99 = argc > 4 ? atou(argv[4]) : ~0ul, limmax = argc > 5 ? atou(argv[5]) : ~0ul;
    if (count > 4096) count = 4096;
    u64 sz = 0x10000 + (5ul << 20); u8 *m = map(0, sz, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS); int pid = (int)SC(SYS_getpid);
    if (is_err(m)) return 3;
    for (u64 i = 0x10000; i < sz; i += 4096) m[i] = 0;       /* touch */
    for (int i = 0; i < 64; i++) ((double *)(m + 0x1000))[i] = 1.0 + 0.001 * i;
    for (int i = 0; i < 16; i++) ((float *)(m + 0x1000))[i] = 1.0f + 0.01f * (float)i;
    *(u32 *)m = 1;
    const char *name = argv[1]; fn = 0;
    for (u32 i = 0; i < sizeof B / sizeof *B; i++) { const char *a = name, *b = B[i].n; while (*a && *a == *b) a++, b++; if (!*a && !*b) fn = B[i].f; }
    if (!fn) return 2;
    sigact(SIGUSR1, on_usr1, SA_RESTART);
    if (thr_start(&T, worker, m)) return 2;
    while (!tid) sleep_us(100);
    sleep_us(50000);
    u64 n = 0, done = 0, off = 0, sent = 0, begin = now_ns(), waits = 0;
    for (; n < count && now_ns() - begin < budget; ) {
        u64 s0 = seq, t0 = now_ns(); SC(SYS_tgkill, pid, tid, SIGUSR1); sent++; u64 t1 = now_ns();
        while (seq == s0 && now_ns() - begin < budget) SC(SYS_sched_yield);
        if (seq == s0) { waits = now_ns() - t0; break; }
        done++;
        if (t1 - t0 > 100000) off++; else lat[n++] = got - t0;      /* (the sender itself was off its core, before or after the kick: says nothing) */
        sleep_us(137 + (n * 61) % 400);
    }
    for (u64 i = 1; i < n; i++) { u64 v = lat[i], j = i; while (j && lat[j - 1] > v) { lat[j] = lat[j - 1]; j--; } lat[j] = v; }
    u64 sum = 0; for (u64 i = 0; i < n; i++) sum += lat[i];
    u64 p99 = n ? lat[n * 99 / 100] / 1000 : waits / 1000, max = n ? lat[n - 1] : 0; if (waits > max) max = waits; max /= 1000;
    int ok = done == sent && n >= 20 && off * 4 < sent && p99 <= lim99 && max <= limmax;
    pf("WITNESS latency %s delivered=%lu sent=%lu sender_off=%lu mean_us=%lu median_us=%lu p99_us=%lu max_us=%lu%s\n", name, done, sent, off, n ? sum / n / 1000 : 0, n ? lat[n / 2] / 1000 : 0, p99, max,
       waits ? " (the last one was still waiting)" : "");
    die(!ok); return 0;
}
