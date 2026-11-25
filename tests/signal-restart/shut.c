/* shut: threads the way a game has them, ended the ways a game ends them.          (mingw, x86-64)
 *   shut drv ROUNDS MODES TIMEOUT_MS     runs `shut child M` ROUNDS times, M taken in turn from MODES; a child that is not over after
 *                                        TIMEOUT_MS is a HANG: said, left alone for 60 s (to be looked at), then terminated
 *   shut child M
 *       E  ExitProcess with every thread running
 *       K  TerminateProcess(GetCurrentProcess())
 *       R  return from main with four threads suspended
 *       S  ExitProcess while a collector suspends and resumes all threads (stop-the-world rounds)
 *       T  TerminateThread on every worker, then wait for them all
 *       C  cooperative: stop flag, wake everything, wait for them all
 *       G  stop-the-world rounds (SuspendThread all, GetThreadContext all, ResumeThread all) for the whole run, then as C
 *       M  return from main with every thread running
 *       P  a thread pool drained (WaitForThreadpoolWorkCallbacks, CloseThreadpool), then as C
 *   shut lat SHAPE COUNT BUDGET_MS [P99_US MAX_US]   SuspendThread + GetThreadContext + ResumeThread on one thread in a loop shape: how long
 *                                        each took; exit status 0 when all were in the limits
 * Workers: pause spins (on a flag; long runs without one), event, semaphore and condition-variable waiters, call/ret work, heap work,
 * a user-space spinlock. A child's exit status says how it ended: 10..18 as meant, 5 a worker that did not end, 6 the collector. */
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <emmintrin.h>

#define NW 28
static volatile LONG stop, cstop, started, spinlock;
static volatile LONGLONG shared;
static HANDLE ev[4], sem;
static SRWLOCK srw = SRWLOCK_INIT;
static CONDITION_VARIABLE cv = CONDITION_VARIABLE_INIT;
struct w { HANDLE h; int id, kind; volatile LONGLONG iters; };
static struct w W[NW];
static int mode;
static volatile LONG c_rounds, c_ctxfail, c_hard, c_susfail; static double c_worst_us;

static __attribute__((noinline)) int fib(int n) { return n < 2 ? n : fib(n - 1) + fib(n - 2); }

static DWORD WINAPI worker(void *p) {
    struct w *w = p;
    InterlockedIncrement(&started);
    switch (w->kind) {
    case 0: while (!stop) { _mm_pause(); w->iters++; } break;
    case 1: while (!stop) { for (int i = 0; i < 200000; i++) _mm_pause(); w->iters++; } break;
    case 2: while (!stop) { WaitForSingleObject(ev[w->id & 3], INFINITE); w->iters++; } break;
    case 3: while (!stop) { w->iters += fib(18); } break;
    case 4: while (!stop) { void *a[16]; for (int i = 0; i < 16; i++) a[i] = HeapAlloc(GetProcessHeap(), 0, 24 + i * 40);
                            for (int i = 0; i < 16; i++) HeapFree(GetProcessHeap(), 0, a[i]); w->iters++; } break;
    case 5: while (!stop) { while (InterlockedExchange(&spinlock, 1)) { while (spinlock && !stop) _mm_pause(); if (stop) return 0; }
                            shared++; InterlockedExchange(&spinlock, 0); w->iters++; } break;
    case 6: AcquireSRWLockExclusive(&srw); while (!stop) { SleepConditionVariableSRW(&cv, &srw, INFINITE, 0); w->iters++; } ReleaseSRWLockExclusive(&srw); break;
    case 7: while (!stop) { WaitForSingleObject(sem, INFINITE); w->iters++; } break;
    }
    return 0;
}

static double us(LARGE_INTEGER a, LARGE_INTEGER b) { static LARGE_INTEGER f; if (!f.QuadPart) QueryPerformanceFrequency(&f); return (double)(b.QuadPart - a.QuadPart) * 1e6 / (double)f.QuadPart; }

/* What a stop-the-world collector does (bdwgc's GC_stop_world on Windows, with its retry of GetThreadContext). */
static DWORD WINAPI collector(void *p) {
    (void)p;
    while (!cstop) {
        LARGE_INTEGER a, b; QueryPerformanceCounter(&a);
        for (int i = 0; i < NW; i++) if (SuspendThread(W[i].h) == (DWORD)-1) InterlockedIncrement(&c_susfail);
        for (int i = 0; i < NW; i++) {
            CONTEXT c; c.ContextFlags = CONTEXT_INTEGER | CONTEXT_CONTROL; int tries = 0;
            while (!GetThreadContext(W[i].h, &c)) {
                InterlockedIncrement(&c_ctxfail);
                if (++tries > 20 || cstop) { InterlockedIncrement(&c_hard); break; }
                ResumeThread(W[i].h); Sleep(0); SuspendThread(W[i].h);
            }
        }
        QueryPerformanceCounter(&b); double d = us(a, b); if (d > c_worst_us) c_worst_us = d;
        for (int i = 0; i < NW; i++) ResumeThread(W[i].h);
        InterlockedIncrement(&c_rounds);
        Sleep(1);
    }
    return 0;
}

static void wake_all(void) {
    for (int i = 0; i < 4; i++) SetEvent(ev[i]);
    ReleaseSemaphore(sem, NW, NULL);
    WakeAllConditionVariable(&cv);
}

static int join_all(const char *what) {
    HANDLE h[NW]; for (int i = 0; i < NW; i++) h[i] = W[i].h;
    for (int t = 0; t < 300; t++) {
        if (mode != 'T') wake_all();
        if (WaitForMultipleObjects(NW, h, TRUE, 50) != WAIT_TIMEOUT) return 0;
    }
    char b[256]; int n = snprintf(b, sizeof b, "WITNESS stuck %s mode=%c:", what, mode);
    for (int i = 0; i < NW; i++) if (WaitForSingleObject(W[i].h, 0) == WAIT_TIMEOUT) n += snprintf(b + n, sizeof b - n, " %d/k%d", i, W[i].kind);
    puts(b); fflush(stdout);
    return 5;
}

static VOID CALLBACK pool_work(PTP_CALLBACK_INSTANCE inst, PVOID ctx, PTP_WORK work) {
    (void)inst; (void)work; volatile LONG *n = ctx; int v = fib(15); for (int i = 0; i < 300; i++) _mm_pause(); if (v) InterlockedIncrement(n); if ((*n & 7) == 0) Sleep(0);
}

static int child(int m) {
    mode = m;
    for (int i = 0; i < 4; i++) ev[i] = CreateEventA(NULL, FALSE, FALSE, NULL);
    sem = CreateSemaphoreA(NULL, 0, 1000000, NULL);
    for (int i = 0; i < NW; i++) {
        W[i].id = i; W[i].kind = i % 8;
        if (m == 'T' && W[i].kind == 4) W[i].kind = 3;      /* a thread ended inside the heap would leave its lock held: the program's own fault */
        if (m == 'T' && W[i].kind == 6) W[i].kind = 2;
        W[i].h = CreateThread(NULL, 0, worker, &W[i], 0, NULL);
        if (!W[i].h) { puts("WITNESS CreateThread failed"); return 4; }
    }
    while (started < NW) Sleep(1);
    HANDLE col = NULL;
    if (m == 'G' || m == 'S') col = CreateThread(NULL, 0, collector, NULL, 0, NULL);
    PTP_POOL pool = NULL; PTP_WORK work = NULL; TP_CALLBACK_ENVIRON env; volatile LONG ran = 0;
    if (m == 'P') {
        pool = CreateThreadpool(NULL); SetThreadpoolThreadMaximum(pool, 8); SetThreadpoolThreadMinimum(pool, 2);
        InitializeThreadpoolEnvironment(&env); SetThreadpoolCallbackPool(&env, pool);
        work = CreateThreadpoolWork(pool_work, (PVOID)&ran, &env);
    }
    LARGE_INTEGER t0, t; QueryPerformanceCounter(&t0);
    unsigned x = (unsigned)GetCurrentProcessId() * 2654435761u; x ^= x >> 15; int run_ms = 120 + (int)(x % 260);
    for (int k = 0;; k++) {
        SetEvent(ev[k & 3]); ReleaseSemaphore(sem, 1, NULL); WakeConditionVariable(&cv);
        if (work) for (int j = 0; j < 4; j++) SubmitThreadpoolWork(work);
        Sleep(1 + (k & 3));
        QueryPerformanceCounter(&t); if (us(t0, t) > run_ms * 1000.0) break;
    }
    switch (m) {
    case 'E': ExitProcess(10);
    case 'K': TerminateProcess(GetCurrentProcess(), 11); Sleep(INFINITE);
    case 'R': for (int i = 0; i < 4; i++) SuspendThread(W[i * 7].h); return 12;
    case 'S': ExitProcess(13);
    case 'M': return 18;
    case 'T':
        for (int i = 0; i < NW; i++) TerminateThread(W[i].h, 1);
        return join_all("after TerminateThread") ? 5 : 14;
    }
    int rc = 0;
    if (col) {
        cstop = 1;
        if (WaitForSingleObject(col, 15000) != WAIT_OBJECT_0) { printf("WITNESS collector stuck rounds=%ld ctxfail=%ld\n", (long)c_rounds, (long)c_ctxfail); fflush(stdout); return 6; }
        if (c_ctxfail || c_susfail || c_worst_us > 500000) { printf("WITNESS collector rounds=%ld ctxfail=%ld hard=%ld susfail=%ld worst_us=%.0f\n", (long)c_rounds, (long)c_ctxfail, (long)c_hard, (long)c_susfail, c_worst_us); fflush(stdout); }
    }
    if (work) { WaitForThreadpoolWorkCallbacks(work, FALSE); CloseThreadpoolWork(work); CloseThreadpool(pool); }
    stop = 1;
    rc = join_all("cooperative");
    return rc ? rc : m == 'C' ? 15 : m == 'G' ? 16 : 17;
}

static int expect(int m) { switch (m) { case 'E': return 10; case 'K': return 11; case 'R': return 12; case 'S': return 13; case 'T': return 14; case 'C': return 15; case 'G': return 16; case 'M': return 18; default: return 17; } }

static int hangwait_ms = 60000;
static int drv(int rounds, const char *modes, int timeout_ms) {
    char self[MAX_PATH]; GetModuleFileNameA(NULL, self, sizeof self);
    int hang = 0, bad = 0, unk = 0; double worst = 0, sum = 0; size_t nm = strlen(modes);
    for (int i = 0; i < rounds; i++) {
        int m = modes[i % nm]; char cmd[MAX_PATH + 32]; snprintf(cmd, sizeof cmd, "\"%s\" child %c", self, m);
        STARTUPINFOA si; PROCESS_INFORMATION pi; memset(&si, 0, sizeof si); si.cb = sizeof si;
        LARGE_INTEGER a, b; QueryPerformanceCounter(&a);
        if (!CreateProcessA(NULL, cmd, NULL, NULL, TRUE, 0, NULL, NULL, &si, &pi)) { printf("DRV CreateProcess failed %lu\n", GetLastError()); fflush(stdout); return 3; }
        DWORD r = WaitForSingleObject(pi.hProcess, (DWORD)timeout_ms);
        if (r == WAIT_TIMEOUT) {
            hang++; printf("HANG round=%d mode=%c pid=%lu\n", i, m, pi.dwProcessId); fflush(stdout);
            Sleep(hangwait_ms);
            TerminateProcess(pi.hProcess, 99);
            if (WaitForSingleObject(pi.hProcess, 15000) == WAIT_TIMEOUT) { unk++; printf("UNKILLABLE round=%d mode=%c\n", i, m); fflush(stdout); return 9; }
            printf("KILLED round=%d mode=%c\n", i, m); fflush(stdout);
        } else {
            DWORD code = 0; GetExitCodeProcess(pi.hProcess, &code); QueryPerformanceCounter(&b); double d = us(a, b) / 1000.0; sum += d; if (d > worst) worst = d;
            if ((int)code != expect(m)) { bad++; printf("BAD round=%d mode=%c exit=%lu (%#lx) ms=%.0f\n", i, m, code, code, d); fflush(stdout); }
            else if (d > 6000) { printf("SLOW round=%d mode=%c ms=%.0f\n", i, m, d); fflush(stdout); }
        }
        CloseHandle(pi.hProcess); CloseHandle(pi.hThread);
        if ((i + 1) % 20 == 0) { printf("DRV progress %d/%d hang=%d bad=%d mean_ms=%.0f worst_ms=%.0f\n", i + 1, rounds, hang, bad, sum / (i + 1 - hang), worst); fflush(stdout); }
    }
    printf("WITNESS shut rounds=%d modes=%s hang=%d bad=%d unkillable=%d mean_ms=%.0f worst_ms=%.0f\n", rounds, modes, hang, bad, unk, sum / (rounds - hang > 0 ? rounds - hang : 1), worst);
    fflush(stdout);
    return hang || bad;
}

/* ---- lat: the pause latency of one loop shape, through SuspendThread and GetThreadContext ---- */
void l_plain(void *), l_spinflag(void *), l_pairs(void *), l_callret(void *), l_x87copy(void *), l_x87sin(void *), l_x87(void *), l_rep1m(void *), l_sse(void *), l_jmp(void *),
    l_avx(void *), l_indirect(void *), l_stos1m(void *), l_scas1m(void *), l_retchain(void *), l_jcc(void *);
__asm__(
    ".text\n"
    ".globl l_plain\n.p2align 6\nl_plain: mov %rcx,%r14\n1: movq 0x1000(%r14),%rax\n addq $3,%rax\n movq %rax,0x1008(%r14)\n cmpq %rbx,%rax\n incl 0x1010(%r14)\n jmp 1b\n"
    ".globl l_jmp\n.p2align 6\nl_jmp: 1: jmp 1b\n"
    ".globl l_spinflag\n.p2align 6\nl_spinflag: mov %rcx,%r14\n1: pause\n cmpl $0,(%r14)\n jne 1b\n ud2\n"
    ".globl l_pairs\n.p2align 6\nl_pairs: 1: pushq %rax\n pushq %rcx\n popq %rdx\n popq %rsi\n jmp 1b\n"
    ".p2align 4\nll_a: pushq %rbx\n pushq %rsi\n pushq %rdi\n movq %rdx,%rbx\n leaq 1(%rbx),%rax\n popq %rdi\n popq %rsi\n popq %rbx\n retq\n"
    ".globl l_callret\n.p2align 6\nl_callret: mov %rcx,%r14\n sub $40,%rsp\n1: movq %r14,%rdx\n callq ll_a\n jmp 1b\n"
    ".globl l_x87copy\n.p2align 6\nl_x87copy: mov %rcx,%r14\n1: fldl 0x1000(%r14)\n fstpl 0x1018(%r14)\n fldl 0x1008(%r14)\n fstpl 0x1020(%r14)\n jmp 1b\n"
    ".globl l_x87\n.p2align 6\nl_x87: mov %rcx,%r14\n1: fldl 0x1000(%r14)\n fldl 0x1008(%r14)\n fmul %st(1),%st\n faddl 0x1010(%r14)\n fstpl 0x1018(%r14)\n fmull 0x1008(%r14)\n fstpl 0x1020(%r14)\n jmp 1b\n"
    ".globl l_x87sin\n.p2align 6\nl_x87sin: mov %rcx,%r14\n1: fldl 0x1000(%r14)\n fsin\n fstpl 0x1018(%r14)\n jmp 1b\n"
    ".globl l_rep1m\n.p2align 6\nl_rep1m: mov %rcx,%r14\n1: leaq 0x10000(%r14),%rsi\n leaq 0x210000(%r14),%rdi\n movl $0x100000,%ecx\n rep movsb\n jmp 1b\n"
    ".globl l_avx\n.p2align 6\nl_avx: mov %rcx,%r14\n vmovups 0x1000(%r14),%ymm0\n1: vmulps %ymm0,%ymm0,%ymm2\n vaddps %ymm2,%ymm0,%ymm3\n vsubps %ymm2,%ymm3,%ymm4\n vmaxps %ymm4,%ymm0,%ymm0\n jmp 1b\n"
    ".globl l_indirect\n.p2align 6\nl_indirect: leaq 2f(%rip),%r12\n leaq 1f(%rip),%r13\n1: jmpq *%r12\n .skip 0x8000\n2: jmpq *%r13\n"
    ".globl l_stos1m\n.p2align 6\nl_stos1m: mov %rcx,%r14\n1: leaq 0x10000(%r14),%rdi\n movl $0x100000,%ecx\n xorl %eax,%eax\n rep stosb\n jmp 1b\n"
    ".globl l_scas1m\n.p2align 6\nl_scas1m: mov %rcx,%r14\n1: leaq 0x10000(%r14),%rdi\n movl $0x100000,%ecx\n movb $1,%al\n repne scasb\n jmp 1b\n"
    ".globl l_retchain\n.p2align 6\nl_retchain: leaq 1f(%rip),%rbp\n leaq 2f(%rip),%rbx\n1: pushq %rbx\n retq\n2: pushq %rbp\n retq\n"
    ".globl l_jcc\n.p2align 6\nl_jcc: movl $1,%edx\n1: testl %edx,%edx\n jnz 1b\n ud2\n"
    ".globl l_sse\n.p2align 6\nl_sse: mov %rcx,%r14\n movups 0x1000(%r14),%xmm0\n movups 0x1010(%r14),%xmm1\n1: movaps %xmm0,%xmm2\n mulps %xmm1,%xmm2\n addps %xmm2,%xmm0\n shufps $0x1b,%xmm0,%xmm0\n subps %xmm1,%xmm0\n jmp 1b\n");
static volatile LONGLONG lsink;
static void l_fib(void *m) { (void)m; for (;;) lsink += fib(18); }
static void l_heap(void *m) { (void)m; for (;;) { void *a[16]; for (int i = 0; i < 16; i++) a[i] = HeapAlloc(GetProcessHeap(), 0, 24 + i * 40); for (int i = 0; i < 16; i++) HeapFree(GetProcessHeap(), 0, a[i]); } }
static void l_pausecount(void *m) { (void)m; for (;;) { for (int i = 0; i < 200000; i++) _mm_pause(); lsink++; } }
static void l_pauseflag(void *m) { (void)m; while (!stop) { _mm_pause(); lsink++; } }
static void l_spinlock(void *m) { (void)m; spinlock = 1; for (;;) { while (InterlockedExchange(&spinlock, 1)) { while (spinlock && !stop) _mm_pause(); } } }
static const struct { const char *n; void (*f)(void *); } LS[] = { {"fib", l_fib}, {"heap", l_heap}, {"pausecount", l_pausecount}, {"pauseflag", l_pauseflag}, {"spinlock", l_spinlock}, {"plain", l_plain}, {"jmp", l_jmp}, {"spinflag", l_spinflag}, {"pairs", l_pairs}, {"callret", l_callret},
    {"x87copy", l_x87copy}, {"x87", l_x87}, {"x87sin", l_x87sin}, {"rep1m", l_rep1m}, {"sse", l_sse},
    {"avx", l_avx}, {"indirect", l_indirect}, {"stos1m", l_stos1m}, {"scas1m", l_scas1m}, {"retchain", l_retchain}, {"jcc", l_jcc} };
static void (*lfn)(void *); static unsigned char *lmem; static volatile LONG lready;
static DWORD WINAPI lworker(void *p) { (void)p; lready = 1; lfn(lmem); return 0; }
static int cmpd(const void *a, const void *b) { double x = *(const double *)a, y = *(const double *)b; return x < y ? -1 : x > y; }
static int lat(const char *shape, int count, int budget_ms, double lim99, double limmax) {
    for (unsigned i = 0; i < sizeof LS / sizeof *LS; i++) if (!strcmp(LS[i].n, shape)) lfn = LS[i].f;
    if (!lfn) return 2;
    lmem = VirtualAlloc(NULL, 0x10000 + (5 << 20), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    for (int i = 0; i < 64; i++) ((double *)(lmem + 0x1000))[i] = 1.0 + 0.001 * i;
    *(unsigned *)lmem = 1;
    HANDLE h = CreateThread(NULL, 0, lworker, NULL, 0, NULL);
    while (!lready) Sleep(1);
    Sleep(50);
    static double v[4096], vs[4096]; int n = 0, fail = 0, susfail = 0; DWORD lasterr = 0; double failmax = 0;
    LARGE_INTEGER begin, a, b, c; QueryPerformanceCounter(&begin); unsigned jit = 103;
    if (count > 4096) count = 4096;
    while (n + fail < count) {
        CONTEXT ctx; ctx.ContextFlags = CONTEXT_INTEGER | CONTEXT_CONTROL;
        QueryPerformanceCounter(&a);
        if (SuspendThread(h) == (DWORD)-1) { susfail++; break; }
        QueryPerformanceCounter(&b);
        BOOL ok = GetThreadContext(h, &ctx); DWORD e = GetLastError();
        QueryPerformanceCounter(&c);
        ResumeThread(h);
        if (ok) { vs[n] = us(a, b); v[n++] = us(a, c); } else { fail++; lasterr = e; if (us(a, c) > failmax) failmax = us(a, c); }
        if (us(begin, c) > budget_ms * 1000.0) break;
        jit = jit * 1664525u + 1013904223u; QueryPerformanceCounter(&a);
        do QueryPerformanceCounter(&b); while (us(a, b) < 170 + jit % 850);
    }
    double sum = 0, ssum = 0; for (int i = 0; i < n; i++) { sum += v[i]; ssum += vs[i]; }
    qsort(v, n, sizeof *v, cmpd);
    double p99 = n ? v[n * 99 / 100] : failmax, max = n ? v[n - 1] : failmax; if (failmax > max) max = failmax;
    int ok = n >= 20 && !fail && !susfail && p99 <= lim99 && max <= limmax;
    printf("WITNESS suspend %s delivered=%d sent=%d context_refused=%d last_error=%lu suspend_call_mean_us=%.0f mean_us=%.0f median_us=%.0f p90_us=%.0f p99_us=%.0f max_us=%.0f\n", shape, n, n + fail, fail, lasterr,
           n ? ssum / n : 0, n ? sum / n : 0, n ? v[n / 2] : 0, n ? v[n * 9 / 10] : 0, p99, max);
    fflush(stdout);
    ExitProcess(ok ? 0 : 1);
}

int main(int argc, char **argv) {
    if (argc >= 3 && !strcmp(argv[1], "child")) return child(argv[2][0]);
    if (argc >= 6 && !strcmp(argv[1], "drv")) hangwait_ms = atoi(argv[5]);
    if (argc >= 5 && !strcmp(argv[1], "drv")) return drv(atoi(argv[2]), argv[3], atoi(argv[4]));
    if (argc >= 5 && !strcmp(argv[1], "lat")) return lat(argv[2], atoi(argv[3]), atoi(argv[4]), argc > 5 ? atof(argv[5]) : 1e9, argc > 6 ? atof(argv[6]) : 1e9);
    return 2;
}
