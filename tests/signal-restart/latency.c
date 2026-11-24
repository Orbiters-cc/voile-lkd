/* How long a signal waits for a thread in each loop of bench_k.S: latency [NAME [COUNT]]  (one worker, one signal after the other) */
#include "nolibc.h"
#define L(X) X(callret) X(prologue) X(pushpop) X(fib) X(movalu) X(div) X(carry) X(avxcopy) X(avxmath) X(avxregs) X(sse) X(x87) X(x87copy)
#define D(n) void b_##n(u64, void *);
L(D)
static const struct { const char *n; void (*f)(u64, void *); } B[] = {
#define E(n) {#n, b_##n},
L(E) };
static volatile int cur, stop, done, tid; static volatile u64 got, seq; static struct thr T;
static void on_usr1(int s, void *i, void *u) { (void)s; (void)i; (void)u; got = now_ns(); seq++; }
static void worker(void *m) { tid = (int)SC(SYS_gettid); while (!stop) { for (int k = 0; k < 100 && !stop; k++) B[cur].f(1000, m); } done = 1; }
static u64 atou(const char *s) { u64 v = 0; while (*s >= '0' && *s <= '9') v = v * 10 + (u64)(*s++ - '0'); return v; }
int main(int argc, char **argv) {
    u8 *m = map(0, 65536, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS); u64 count = argc > 2 ? atou(argv[2]) : 200; int pid = (int)SC(SYS_getpid);
    for (int i = 0; i < 65536 / 8; i++) ((double *)m)[i] = 1.0 + 0.001 * i;
    sigact(SIGUSR1, on_usr1, SA_RESTART);
    for (u32 i = 0; i < sizeof B / sizeof *B; i++) {
        if (argc > 1) { const char *a = argv[1], *b = B[i].n; while (*a && *a == *b) a++, b++; if ((*a || *b) && argv[1][0] != '*') continue; }
        cur = (int)i; stop = done = tid = 0; if (thr_start(&T, worker, m)) return 2;
        while (!tid) sleep_us(100);
        sleep_us(20000);
        u64 sum = 0, worst = 0, n = 0, begin = now_ns();
        for (; n < count && now_ns() - begin < 5000000000ul; n++) {
            u64 s0 = seq, t0 = now_ns(); SC(SYS_tgkill, pid, tid, SIGUSR1);
            while (seq == s0 && now_ns() - t0 < 20000000000ul) SC(SYS_sched_yield);
            u64 d = (seq == s0 ? now_ns() : got) - t0; sum += d; if (d > worst) worst = d; sleep_us(137);
        }
        stop = 1; while (!done) sleep_us(100);
        pf("LATENCY %s mean_us=%lu worst_us=%lu n=%lu\n", B[i].n, sum / n / 1000, worst / 1000, n);
    }
    return 0;
}
