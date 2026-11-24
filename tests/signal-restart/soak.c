/* soak: the random programs of gen_soak.py, in several threads, while another thread sends them signals.
 * Usage: soak THREADS SECONDS INTERVAL_US ("-": no signals)     Exit status: 0 all the same, 1 a program returned something else, 3 a fault. */
#include "nolibc.h"
extern u64 (*soak_table[])(void *); extern u64 soak_count;
struct wk { volatile int tid, done, ready; u64 rounds; struct thr th; u8 *mem; u64 *want; int id; } __attribute__((aligned(64)));
static struct wk W[16]; static int NW; static volatile int stop, go, bad; static volatile u64 handled;
static u64 atou(const char *s) { u64 v = 0; while (*s >= '0' && *s <= '9') v = v * 10 + (u64)(*s++ - '0'); return v; }
static void on_usr1(int s, void *i, void *u) {
    (void)s; (void)i; (void)u;
    __asm__ volatile("fninit; vzeroall; std; cld" ::: "xmm0", "xmm1", "xmm2", "xmm3", "xmm4", "xmm5", "xmm6", "xmm7", "xmm8", "xmm9", "xmm10", "xmm11", "xmm12", "xmm13", "xmm14", "xmm15");
    __sync_fetch_and_add(&handled, 1);
}
static void on_fault(int s, void *i, void *u) {
    struct uctx *c = u; struct siginfo *si = i; u64 k = 0, b = 0;
    for (u64 j = 0; j < soak_count; j++) if (c->rip >= (u64)soak_table[j] && (u64)soak_table[j] > b) { b = (u64)soak_table[j]; k = j; }
    pf("WITNESS fault sig=%d program=%lu+0x%lx rip=%lx rsp=%lx addr=%lx handled=%lu\n", s, k, c->rip - b, c->rip, c->rsp, si->addr, handled); die(3);
}
static void worker(void *a) {
    struct wk *w = a; w->tid = (int)SC(SYS_gettid);
    for (u64 k = 0; k < soak_count; k++) { /* the programs keep addresses of their thread's memory */
        w->want[k] = soak_table[k](w->mem);
        u64 first[81]; memcpy(first, w->mem, sizeof first);
        for (int q = 0; q < 20; q++) if (soak_table[k](w->mem) != w->want[k]) {
            for (int j = 0; j < 81; j++) if (first[j] != ((u64 *)w->mem)[j]) pf("WITNESS program %lu: slot %d is %lx, was %lx\n", k, j, ((u64 *)w->mem)[j], first[j]);
            pf("WITNESS program %lu differs without any signal\n", k); die(2);
        }
    }
    w->ready = 1; while (!go) sleep_us(1000);
    for (u64 n = (u64)w->id * 7; !stop; n++) {
        u64 k = n % soak_count;
        for (int q = 0; q < 2000 && !stop; q++) { u64 h = soak_table[k](w->mem); if (h != w->want[k]) { pf("WITNESS program %lu returned %lx, not %lx (thread %d)\n", k, h, w->want[k], w->id); bad = 1; stop = 1; } }
        w->rounds++;
    }
    w->done = 1;
}
int main(int argc, char **argv) {
    NW = argc > 1 ? (int)atou(argv[1]) : 4; u64 secs = argc > 2 ? atou(argv[2]) : 10; int nosig = argc > 3 && argv[3][0] == '-'; u64 ival = argc > 3 && !nosig ? atou(argv[3]) : 150;
    if (NW > 16) NW = 16;
    sigact(SIGUSR1, on_usr1, SA_RESTART); sigact(SIGSEGV, on_fault, 0); sigact(SIGBUS, on_fault, 0); sigact(SIGILL, on_fault, 0); sigact(8, on_fault, 0);
    int pid = (int)SC(SYS_getpid);
    for (int j = 0; j < NW; j++) { W[j].id = j; W[j].mem = map(0, 65536, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS); W[j].want = (u64 *)(W[j].mem + 0x8000); if (thr_start(&W[j].th, worker, &W[j])) return 2; }
    for (int j = 0; j < NW; j++) while (!W[j].ready) sleep_us(1000);
    go = 1; u64 t0 = now_ns(), sent = 0, x = 88172645463325252ul;
    while (!stop && now_ns() - t0 < secs * 1000000000ul) {
        if (nosig) { sleep_us(2000); continue; }
        x ^= x << 13; x ^= x >> 7; x ^= x << 17;
        SC(SYS_tgkill, pid, W[x % (u64)NW].tid, SIGUSR1); sent++; sleep_us(ival / 2 + x / 1024 % (ival + 1));
    }
    stop = 1; u64 rounds = 0;
    for (int j = 0; j < NW; j++) { u64 t1 = now_ns(); while (!W[j].done && now_ns() - t1 < 5000000000ul) sleep_us(1000); if (!W[j].done) { pf("WITNESS thread %d never stopped\n", j); bad = 1; } rounds += W[j].rounds; }
    pf("WITNESS soak threads=%d secs=%lu rounds=%lu sent=%lu handled=%lu bad=%d\n", NW, secs, rounds, sent, handled, bad);
    return bad;
}
