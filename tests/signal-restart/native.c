/* What the scheduler alone makes a signal wait on this machine now: from pthread_kill to the handler of a native thread that computes, with
 * the pace and the waiting sender of shapes.c. No emulator is in it: an engine that changes no thread's scheduling cannot do better.
 *   native [COUNT [BUDGET_MS]] */
#include <pthread.h>
#include <sched.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>
static volatile unsigned long flag, got, sink; static volatile int ready;
static unsigned long now(void) { return clock_gettime_nsec_np(CLOCK_UPTIME_RAW); }
static void on_sig(int s) { (void)s; got = now(); flag = 0; }
static void *worker(void *p) { ready = 1; for (;;) sink++; return p; }
static int cmp(const void *a, const void *b) { double x = *(const double *)a, y = *(const double *)b; return x < y ? -1 : x > y; }
int main(int c, char **v) {
    int count = c > 1 ? atoi(v[1]) : 1000, n = 0; unsigned long budget = (c > 2 ? strtoul(v[2], 0, 10) : 8000) * 1000000ul; static double lat[10000];
    if (count > 10000) count = 10000;
    pthread_t t; signal(SIGUSR2, on_sig); if (pthread_create(&t, 0, worker, 0)) return 2;
    while (!ready) usleep(100);
    usleep(50000);
    for (unsigned long begin = now(); n < count && now() - begin < budget;) {
        unsigned long t0 = now(); flag = 1; pthread_kill(t, SIGUSR2); unsigned long t1 = now();
        while (flag) sched_yield();
        if (t1 - t0 <= 100000) lat[n++] = (double)(got - t0) / 1000;
        usleep(137 + (n * 61) % 400);
    }
    if (!n) return 1;
    qsort(lat, (size_t)n, sizeof *lat, cmp); double sum = 0; for (int i = 0; i < n; i++) sum += lat[i];
    printf("samples=%d mean_us=%.0f median_us=%.0f p90_us=%.0f p99_us=%.0f max_us=%.0f\n", n, sum / n, lat[n / 2], lat[n * 9 / 10], lat[n * 99 / 100], lat[n - 1]);
    return 0;
}
