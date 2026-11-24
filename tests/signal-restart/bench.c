/* The price of the fixes on code they touch: ns per round, the least of 15 runs. bench [NAME] */
#include "nolibc.h"
#define L(X) X(callret) X(prologue) X(pushpop) X(fib) X(movalu) X(div) X(carry) X(avxcopy) X(avxmath) X(avxregs) X(sse) X(x87) X(x87copy)
#define D(n) void b_##n(u64, void *);
L(D)
static const struct { const char *n; void (*f)(u64, void *); } B[] = {
#define E(n) {#n, b_##n},
L(E) };
int main(int argc, char **argv) {
    u8 *m = map(0, 65536, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS);
    for (int i = 0; i < 65536 / 8; i++) ((double *)m)[i] = 1.0 + 0.001 * i;
    for (u32 i = 0; i < sizeof B / sizeof *B; i++) {
        if (argc > 1) { const char *a = argv[1], *b = B[i].n; while (*a && *a == *b) a++, b++; if (*a || *b) continue; }
        u64 n = 1000, t = 0; B[i].f(n, m);
        do { n *= 2; u64 t0 = now_ns(); B[i].f(n, m); t = now_ns() - t0; } while (t < 8000000);
        u64 best = ~0ul; for (int r = 0; r < 15; r++) { u64 t0 = now_ns(); B[i].f(n, m); t = now_ns() - t0; if (t < best) best = t; }
        u64 ps = best * 1000 / n; pf("BENCH %s %lu.%lu%lu%lu\n", B[i].n, ps / 1000, ps / 100 % 10, ps / 10 % 10, ps % 10);
    }
    return 0;
}
