/* Threads of every kind that are stopped by signals, thousands of times, while the host looks at how they are scheduled (schedwatch.c).
 *   sched STOPS TENS_OF_SECONDS
 * 14 threads: loops that compute, spin with and without a pause, yield, sleep, wait on a futex (shapes that the released engine stops,
 * too). One signal after the other, in turn, none after that time; 0.5 s of quiet before the first and after the last. Exit status 0: every
 * one was handled. */
#include "nolibc.h"
#define N 14
static struct thr T[N]; static volatile int tid[N], word, sink[N]; static volatile u64 seq;
static void on_usr1(int s, void *i, void *u) { (void)s; (void)i; (void)u; seq++; }
static void worker(void *p) {
    int n = (int)(u64)p; tid[n] = (int)SC(SYS_gettid);
    for (u64 x = 1;;) switch (n % 7) {
    case 0: __asm__ volatile("1: inc %0\n cmp $1000000,%0\n jb 1b" : "+r"(x)); x = 1; break;
    case 1: for (int k = 0; k < 10000; k++) __asm__ volatile("pause"); break;
    case 2: SC(SYS_sched_yield); break;
    case 3: sleep_us(500); break;
    case 4: { struct timespec t = { 0, 2000000 }; SC(SYS_futex, &word, 0, 0, &t); break; }
    case 5: for (int k = 0; k < 1000; k++) sink[n] += k; SC(SYS_getpid); break;
    case 6: __asm__ volatile("1: imul $3,%0,%0\n add $7,%0\n test $0x3ff,%0\n jnz 1b" : "+r"(x)); break;
    }
}
int main(int argc, char **argv) {
    u64 stops = 0; for (const char *s = argc > 1 ? argv[1] : "4000"; *s; s++) stops = stops * 10 + (u64)(*s - '0');
    u64 budget = (argc > 2 ? (u64)(argv[2][0] - '0') * 10 : 90) * 1000000000ul; int pid = (int)SC(SYS_getpid);
    sigact(SIGUSR1, on_usr1, SA_RESTART);
    for (u64 i = 0; i < N; i++) if (thr_start(&T[i], worker, (void *)i)) return 2;
    for (int i = 0; i < N; i++) while (!tid[i]) sleep_us(100);
    sleep_us(500000);
    u64 sent = 0, handled = 0, begin = now_ns(), late = 0;
    for (; sent < stops; sent++) {
        u64 s0 = seq, t0 = now_ns(); SC(SYS_tgkill, pid, tid[sent % N], SIGUSR1);
        while (seq == s0 && now_ns() - t0 < 20000000000ul) SC(SYS_sched_yield);
        if (seq != s0) handled++;
        if (now_ns() - t0 > 250000) late++;
        sleep_us(50);
        if (now_ns() - begin > budget) { sent++; break; }
    }
    sleep_us(500000);
    pf("WITNESS sched stops=%lu handled=%lu later_than_250us=%lu ms=%lu\n", sent, handled, late, (now_ns() - begin) / 1000000);
    die(handled != sent); return 0;
}
