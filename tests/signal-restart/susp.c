/* susp: the game's path. Threads run self-checking code while the main thread does what a stop-the-world collector does:
 * SuspendThread, GetThreadContext, ResumeThread (and every eighth time SetThreadContext with what it got).
 *   c   the call/ret kernel of sigstorm_k.S (Windows epilogues: pop; pop; pop; ret and mov rsp,rbp; pop rbp; ret). It returns 9 when a
 *       ret ran twice, 7 for a lost callee-saved register, 8 for a moved stack pointer, 6 for a wrong result. A context that shows the
 *       thread at a ret with the stack pointer already past the return address is counted (badctx): the collector would be given that.
 *   r   the read-modify-write kernel (control)
 *   s   the programs of gen_soak.py, each returning a hash that must stay the same
 *   p x the 32-bit kernels of susp32_k.S (a 32-bit build)
 * Usage: susp KIND ROUNDS GAP_US [THREADS [SECONDS]]     the first of ROUNDS and SECONDS that is reached ends it
 * Exit status: 0 all right, 1 not, 3 a fault. */
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
static int kind; static volatile LONG stop;
#ifdef _WIN64
struct wk { volatile int stop; int pad; volatile unsigned long long iters; void *cell; unsigned long long aux[2]; volatile LONG rc; HANDLE h; int id; };
int k_callret_ms(struct wk *), k_rmw_ms(struct wk *);
extern char leaf_a[], k_callret[], leaf_a_ret[], leaf_b_ret[];
#ifdef SOAK
typedef __attribute__((sysv_abi)) uint64_t soak_fn(void *); extern soak_fn *soak_table[]; extern uint64_t soak_count;
#endif
#else
struct wk { volatile int stop; volatile unsigned iters; volatile LONG rc; HANDLE h; int id; };
int k32_pairs(struct wk *), k32_x87(struct wk *);
#endif
static struct wk W[16];
#if defined(_WIN64) && defined(SOAK)
static int soak(struct wk *w) {
    uint8_t *m = VirtualAlloc(NULL, 65536, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE); uint64_t *want = (uint64_t *)(m + 0x8000);
    for (uint64_t k = 0; k < soak_count; k++) { want[k] = soak_table[k](m); if (soak_table[k](m) != want[k]) want[k] = soak_table[k](m); }
    for (uint64_t n = (uint64_t)w->id * 7; !w->stop; n++) {
        uint64_t k = n % soak_count;
        for (int q = 0; q < 2000 && !w->stop; q++) if (soak_table[k](m) != want[k]) { printf("WITNESS program %d returned something else (thread %d)\n", (int)k, w->id); fflush(stdout); return 6; }
        w->iters++;
    }
    return 0;
}
#endif
static DWORD WINAPI worker(void *p) {
    struct wk *w = p;
#ifdef _WIN64
#ifdef SOAK
    w->rc = soak(w);
#else
    w->rc = kind == 'c' ? k_callret_ms(w) : k_rmw_ms(w);
#endif
#else
    w->rc = kind == 'p' ? k32_pairs(w) : k32_x87(w);
#endif
    return 0;
}
static LONG WINAPI on_fault(EXCEPTION_POINTERS *e) {
    printf("WITNESS fault code=%08lx rip=%llx rsp=%llx addr=%llx\n", (unsigned long)e->ExceptionRecord->ExceptionCode,
#ifdef _WIN64
           (unsigned long long)e->ContextRecord->Rip, (unsigned long long)e->ContextRecord->Rsp,
#else
           (unsigned long long)e->ContextRecord->Eip, (unsigned long long)e->ContextRecord->Esp,
#endif
           (unsigned long long)e->ExceptionRecord->ExceptionInformation[1]);
    fflush(stdout); ExitProcess(3);
}
int main(int argc, char **argv) {
    kind = argc > 1 ? argv[1][0] : 'c'; int rounds = argc > 2 ? atoi(argv[2]) : 2000, gap = argc > 3 ? atoi(argv[3]) : 200, n = argc > 4 ? atoi(argv[4]) : 1, secs = argc > 5 ? atoi(argv[5]) : 0;
    if (n > 16) n = 16;
    SetUnhandledExceptionFilter(on_fault);
    for (int j = 0; j < n; j++) {
        W[j].id = j; W[j].rc = -1;
#ifdef _WIN64
        W[j].cell = VirtualAlloc(NULL, 16384, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
        for (int i = 0; i < 16384; i++) ((unsigned char *)W[j].cell)[i] = (unsigned char)(i * 7);
#endif
        W[j].h = CreateThread(NULL, 0, worker, &W[j], 0, NULL);
    }
    for (int j = 0; j < n; j++) while (!W[j].iters && W[j].rc < 0) Sleep(1);
    LARGE_INTEGER f, t0, t, start; QueryPerformanceFrequency(&f); QueryPerformanceCounter(&start);
    int done = 0, badctx = 0, inleaf = 0, atret = 0, api = 0, finished = 0; unsigned x = 2463534242u; double worst = 0;
    for (; done < rounds && !finished; done++) {
        x ^= x << 13; x ^= x >> 17; x ^= x << 5;
        struct wk *w = &W[x % (unsigned)n];
        QueryPerformanceCounter(&t0);
        if (SuspendThread(w->h) == (DWORD)-1) { api++; break; }
        CONTEXT c; memset(&c, 0, sizeof c); c.ContextFlags = CONTEXT_CONTROL | CONTEXT_INTEGER;
        if (!GetThreadContext(w->h, &c)) api++;
        QueryPerformanceCounter(&t); double us = (double)(t.QuadPart - t0.QuadPart) * 1e6 / (double)f.QuadPart; if (us > worst) worst = us;
#if defined(_WIN64) && !defined(SOAK)
        if (kind == 'c') {
            uintptr_t ip = c.Rip;
            if (ip >= (uintptr_t)leaf_a && ip < (uintptr_t)k_callret) inleaf++;
            if (ip == (uintptr_t)leaf_a_ret || ip == (uintptr_t)leaf_b_ret) { atret++; if (c.Rsp == w->aux[0]) { badctx++; if (badctx <= 3) printf("WITNESS badctx round=%d rip=%s rsp=%llx (driver rsp %llx): at a ret, return address already popped\n", done, ip == (uintptr_t)leaf_a_ret ? "leaf_a ret" : "leaf_b ret", (unsigned long long)c.Rsp, w->aux[0]); } }
        }
#endif
        if ((done & 7) == 7 && !SetThreadContext(w->h, &c)) api++;
        if (ResumeThread(w->h) == (DWORD)-1) { api++; break; }
        QueryPerformanceCounter(&t0);
        do QueryPerformanceCounter(&t); while ((t.QuadPart - t0.QuadPart) * 1000000 / f.QuadPart < gap);
        if (secs && (t.QuadPart - start.QuadPart) / f.QuadPart >= secs) finished = 1;
        for (int j = 0; j < n; j++) if (W[j].rc >= 0) finished = 1;
    }
    int bad = 0; unsigned long long iters = 0;
    for (int j = 0; j < n; j++) W[j].stop = 1;
    for (int j = 0; j < n; j++) { DWORD s = WaitForSingleObject(W[j].h, 5000); if (s != WAIT_OBJECT_0 || W[j].rc) { bad++; printf("WITNESS thread %d rc=%ld joined=%d\n", j, (long)W[j].rc, s == WAIT_OBJECT_0); } iters += W[j].iters; }
    printf("WITNESS susp kind=%c threads=%d suspensions=%d iters=%llu inleaf=%d atret=%d badctx=%d api=%d worst_us=%.0f bad=%d\n", kind, n, done, iters, inleaf, atret, badctx, api, worst, bad + badctx + api);
    return bad || badctx || api;
}
