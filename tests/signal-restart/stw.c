/* stw: what a stop-the-world collector does, for many rounds, and whether what it is told is true.                  (mingw, x86-64)
 * One thread suspends all the others, reads the context of each, checks it, resumes them all. The others do mixed work; what can be
 * said of their registers at each of their instructions is checked: a pair of counters, the return address on the stack of a leaf, the
 * depth of pushes, what is left of a rep movs or stos, SSE and x87 registers, a lock word against who says to hold it.
 *   stw ROUNDS THREADS [GAP_US [BUDGET_S]]
 * Exit status: 0 all right, 1 wrong contexts or results, 2 not all the rounds in time, 3 a fault. */
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <emmintrin.h>
typedef unsigned long long u64;
#define MAXT 64
enum { COUNT, LEAF, DEPTH, REPM, REPS, SSE, X87, FIB, HEAP, LOCK, PAUSE, EVENT, YIELD, MEMC, NKINDS };
static const char *const NAME[] = { "count", "leaf", "depth", "repmovs", "repstos", "sse", "x87", "fib", "heap", "lock", "pause", "event", "yield", "memcpy" };
struct w { u64 *mem; volatile LONG *stop; volatile u64 iters, err; HANDLE h; int id, kind; };
static struct w W[MAXT]; static volatile LONG stop, started, lockword, lockshared[2]; static HANDLE ev;
static int nt; static volatile LONG faults;

/* r12, r13, r14: at c0 r13 == r12 and r14 == 2 * r12; at c1 r12 is one ahead; at c2 r13 is too */
void kn_count(struct w *), kn_leaf(struct w *), kn_depth(struct w *), kn_repm(struct w *), kn_reps(struct w *), kn_sse(struct w *), kn_x87(struct w *);
extern char c0[], c1[], c2[], c3[], lf0[], lf1[], lf2[], lf3[], lfr[], lfe[], dp0[], dpe[], rm0[], rm1[], rs0[], rs1[], ss0[], ss1[], sse_e[], x0[], xe[];
#define SAVE "pushq %rbx\npushq %rbp\npushq %rsi\npushq %rdi\npushq %r12\npushq %r13\npushq %r14\npushq %r15\nsubq $0x108,%rsp\nmovq %rcx,%r15\nmovdqu %xmm6,(%rsp)\nmovdqu %xmm7,16(%rsp)\nmovdqu %xmm8,32(%rsp)\n"
#define REST "movdqu (%rsp),%xmm6\nmovdqu 16(%rsp),%xmm7\nmovdqu 32(%rsp),%xmm8\naddq $0x108,%rsp\npopq %r15\npopq %r14\npopq %r13\npopq %r12\npopq %rdi\npopq %rsi\npopq %rbp\npopq %rbx\nretq\n"
#define LOOP "movq 8(%r15),%rax\ncmpl $0,(%rax)\nje 1b\n"   /* until *w->stop */
__asm__(".text\n"
    ".globl kn_count\nkn_count:\n" SAVE "xorl %r12d,%r12d\nxorl %r13d,%r13d\nxorl %r14d,%r14d\n1:\n"
    ".globl c0\nc0: incq %r12\n.globl c1\nc1: incq %r13\n.globl c2\nc2: leaq (%r12,%r13),%r14\n.globl c3\nc3: movq %r12,16(%r15)\n" LOOP REST
    /* a leaf called with the stack pointer in rbp: in it rsp == rbp - 8, the return address is there */
    ".globl kn_leaf\nkn_leaf:\n" SAVE "movq %rsp,%rbp\nxorl %r12d,%r12d\n1: movq %r12,%rdx\ncall lf0\n.globl lfr\nlfr: incq %r12\ncmpq %r12,%rax\njne 2f\nmovq %r12,16(%r15)\n" LOOP "jmp 3f\n2: movq $1,24(%r15)\n3:\n" REST
    ".p2align 4\n.globl lf0\nlf0: pushq %rbx\n.globl lf1\nlf1: pushq %rsi\npushq %rdi\n.globl lf2\nlf2: movq %rdx,%rbx\nleaq 1(%rbx),%rax\npopq %rdi\npopq %rsi\npopq %rbx\n.globl lf3\nlf3: retq\n.globl lfe\nlfe: nop\n"
    /* r12 says how deep the stack is, before and after each push and pop of a loop: rsp == rbp - 8 * r12 at the loop heads */
    ".globl kn_depth\nkn_depth:\n" SAVE "movq %rsp,%rbp\n1: xorl %r12d,%r12d\n.globl dp0\ndp0: leaq 1(%r12),%r12\npushq %r12\ncmpq $8,%r12\njl dp0\n4: popq %rax\ncmpq %r12,%rax\njne 2f\ndecq %r12\njnz 4b\nincq %r13\nmovq %r13,16(%r15)\n" LOOP "jmp 3f\n2: movq $1,24(%r15)\n3: movq %rbp,%rsp\n.globl dpe\ndpe:\n" REST
    /* rep movsb of 1 MiB: at it rsi - src == rdi - dst == 1 MiB - rcx */
    ".globl kn_repm\nkn_repm:\n" SAVE "movq (%r15),%r12\nleaq 0x200000(%r12),%r13\nmovl $0x100000,%r14d\n1: movq %r12,%rsi\nmovq %r13,%rdi\nmovl %r14d,%ecx\n.globl rm0\nrm0: rep movsb\n.globl rm1\nrm1: testq %rcx,%rcx\njnz 2f\nleaq 0x100000(%r13),%rax\ncmpq %rax,%rdi\njne 2f\nincq %rbx\nmovq %rbx,16(%r15)\n" LOOP "jmp 3f\n2: movq $1,24(%r15)\n3:\n" REST
    ".globl kn_reps\nkn_reps:\n" SAVE "movq (%r15),%r12\nmovl $0x40000,%r14d\n1: movq %r12,%rdi\nmovl %r14d,%ecx\nmovl $0x5a5a5a5a,%eax\n.globl rs0\nrs0: rep stosl\n.globl rs1\nrs1: testq %rcx,%rcx\njnz 2f\nincq %rbx\nmovq %rbx,16(%r15)\n" LOOP "jmp 3f\n2: movq $1,24(%r15)\n3:\n" REST
    /* xmm6 == xmm7 at the head, xmm8 twice as much (integers) */
    ".globl kn_sse\nkn_sse:\n" SAVE "pxor %xmm6,%xmm6\npxor %xmm7,%xmm7\npxor %xmm8,%xmm8\npcmpeqd %xmm5,%xmm5\n1:\n.globl ss0\nss0: psubd %xmm5,%xmm6\n.globl ss1\nss1: movdqa %xmm6,%xmm7\nmovdqa %xmm6,%xmm8\npaddd %xmm7,%xmm8\nmovd %xmm6,%eax\nmovq %rax,16(%r15)\n.globl sse_e\nsse_e:\n" LOOP REST
    /* st(1) == 3 and st(0) == 5 for ever at the head */
    ".globl kn_x87\nkn_x87:\n" SAVE "fninit\nfld1\nfld1\nfadd %st(0),%st\nfaddp %st,%st(1)\nfld1\nfadd %st(1),%st\nfld1\nfaddp %st,%st(1)\n1:\n.globl x0\nx0: fld %st(1)\nfmul %st(1),%st\nfstpl 0x40(%rsp)\nmovabsq $0x402e000000000000,%rax\ncmpq %rax,0x40(%rsp)\njne 2f\nfldl 0x40(%rsp)\nfstpl 0x48(%rsp)\ncmpq %rax,0x48(%rsp)\njne 2f\nincq %rbx\nmovq %rbx,16(%r15)\n" LOOP "jmp 3f\n2: movq $1,24(%r15)\n3: fninit\n.globl xe\nxe:\n" REST);

static __attribute__((noinline)) int fib(int n) { return n < 2 ? n : fib(n - 1) + fib(n - 2); }
static DWORD WINAPI worker(void *p) {
    struct w *w = p; InterlockedIncrement(&started);
    switch (w->kind) {
    case COUNT: kn_count(w); break;
    case LEAF: kn_leaf(w); break;
    case DEPTH: kn_depth(w); break;
    case REPM: kn_repm(w); break;
    case REPS: kn_reps(w); break;
    case SSE: kn_sse(w); break;
    case X87: kn_x87(w); break;
    case FIB: while (!stop) { if (fib(18) != 2584) w->err++; w->iters++; } break;
    case HEAP: while (!stop) { char *a[16]; for (int i = 0; i < 16; i++) { a[i] = HeapAlloc(GetProcessHeap(), 0, 24 + i * 40); memset(a[i], i, 24); }
                               for (int i = 0; i < 16; i++) { if (a[i][23] != i) w->err++; HeapFree(GetProcessHeap(), 0, a[i]); } w->iters++; } break;
    case LOCK: while (!stop) { while (InterlockedExchange(&lockword, 1)) while (lockword && !stop) _mm_pause();
                               lockshared[0]++; lockshared[1]++; if (lockshared[0] != lockshared[1]) w->err++; InterlockedExchange(&lockword, 0); w->iters++; } break;
    case PAUSE: while (!stop) { for (int i = 0; i < 20000 && !stop; i++) _mm_pause(); w->iters++; } break;
    case EVENT: while (!stop) { WaitForSingleObject(ev, 3); w->iters++; } break;
    case YIELD: while (!stop) { SwitchToThread(); w->iters++; } break;
    case MEMC: { char *d = (char *)w->mem; while (!stop) { memcpy(d + 0x200000, d, 0x40000 + (w->iters & 63)); memset(d + 0x300000, (int)w->iters, 0x1000); w->iters++; } break; }
    }
    return 0;
}
static double us(LARGE_INTEGER a, LARGE_INTEGER b) { static LARGE_INTEGER f; if (!f.QuadPart) QueryPerformanceFrequency(&f); return (double)(b.QuadPart - a.QuadPart) * 1e6 / (double)f.QuadPart; }
static LONG WINAPI on_fault(EXCEPTION_POINTERS *e) {
    printf("WITNESS stw fault code=%08lx rip=%llx rsp=%llx addr=%llx\n", (unsigned long)e->ExceptionRecord->ExceptionCode, (u64)e->ContextRecord->Rip, (u64)e->ContextRecord->Rsp, (u64)e->ExceptionRecord->ExceptionInformation[1]);
    fflush(stdout); ExitProcess(3);
}
static int said;
static int wrong(struct w *w, CONTEXT *c, const char *what, u64 a, u64 b) {
    if (said++ < 6) { printf("WITNESS wrong context: thread %d %s: %s (rip %llx rsp %llx: %llx, %llx)\n", w->id, NAME[w->kind], what, (u64)c->Rip, (u64)c->Rsp, a, b); fflush(stdout); }
    return 1;
}
#define AT(s) ((uintptr_t)(s))
/* What is wrong with the context of a stopped thread; seen: how many were at an instruction that says something. */
static int check(struct w *w, CONTEXT *c, int *seen) {
    uintptr_t ip = c->Rip;
    switch (w->kind) {
    case COUNT:
        if (ip < AT(c0) || ip > AT(c3)) return 0;
        ++*seen;
        if (ip == AT(c0) && (c->R13 != c->R12 || c->R14 != 2 * c->R12)) return wrong(w, c, "c0", c->R12, c->R13);
        if (ip == AT(c1) && c->R12 != c->R13 + 1) return wrong(w, c, "c1", c->R12, c->R13);
        if (ip == AT(c2) && c->R12 != c->R13) return wrong(w, c, "c2", c->R12, c->R13);
        if (ip == AT(c3) && c->R14 != 2 * c->R12) return wrong(w, c, "c3", c->R12, c->R14);
        return 0;
    case LEAF:
        if (ip < AT(lf0) || ip >= AT(lfe)) { if (ip == AT(lfr)) { ++*seen; if (c->Rsp != c->Rbp) return wrong(w, c, "after the ret", c->Rsp, c->Rbp); if (c->Rax != c->R12 + 1) return wrong(w, c, "result", c->Rax, c->R12); } return 0; }
        ++*seen;
        if ((ip == AT(lf0) || ip == AT(lf3)) && (c->Rsp != c->Rbp - 8 || *(u64 *)c->Rsp != AT(lfr))) return wrong(w, c, "the return address", c->Rsp, c->Rbp);
        if (ip == AT(lf1) && c->Rsp != c->Rbp - 16) return wrong(w, c, "one push", c->Rsp, c->Rbp);
        if (ip == AT(lf2) && c->Rsp != c->Rbp - 32) return wrong(w, c, "three pushes", c->Rsp, c->Rbp);
        return 0;
    case DEPTH:
        if (ip != AT(dp0)) return 0;
        ++*seen; return c->Rsp != c->Rbp - 8 * c->R12 ? wrong(w, c, "the depth", c->Rsp, c->R12) : 0;
    case REPM:
        if (ip != AT(rm0)) return 0;
        ++*seen;
        if (c->Rsi - c->R12 != c->Rdi - c->R13 || c->Rsi - c->R12 != 0x100000 - c->Rcx) return wrong(w, c, "rep movsb", c->Rsi - c->R12, c->Rcx);
        return 0;
    case REPS:
        if (ip != AT(rs0)) return 0;
        ++*seen; return c->Rdi - c->R12 != 4 * (0x40000 - c->Rcx) ? wrong(w, c, "rep stosl", c->Rdi - c->R12, c->Rcx) : 0;
    case SSE: {
        if (ip < AT(ss0) || ip >= AT(sse_e)) return 0;
        ++*seen; u64 a = c->FltSave.XmmRegisters[6].Low, b = c->FltSave.XmmRegisters[7].Low, d = c->FltSave.XmmRegisters[8].Low;
        if (ip == AT(ss0) && (a != b || (uint32_t)d != 2 * (uint32_t)a)) return wrong(w, c, "xmm6, xmm7, xmm8", a, b);
        if (ip == AT(ss1) && (uint32_t)a != (uint32_t)b + 1) return wrong(w, c, "xmm6 one ahead", a, b);
        return 0; }
    case X87: {
        if (ip != AT(x0)) return 0;
        ++*seen; u64 a = c->FltSave.FloatRegisters[0].Low, b = c->FltSave.FloatRegisters[1].Low;
        return a != 0xa000000000000000ull || b != 0xc000000000000000ull ? wrong(w, c, "st(0), st(1)", a, b) : 0; }
    }
    return 0;
}
int main(int argc, char **argv) {
    int rounds = argc > 1 ? atoi(argv[1]) : 300; nt = argc > 2 ? atoi(argv[2]) : 20; int gap = argc > 3 ? atoi(argv[3]) : 1000, budget = argc > 4 ? atoi(argv[4]) : 60;
    if (nt > MAXT) nt = MAXT;
    SetUnhandledExceptionFilter(on_fault);
    ev = CreateEventA(NULL, FALSE, FALSE, NULL);
    for (int i = 0; i < nt; i++) {
        W[i].id = i; W[i].kind = i % NKINDS; W[i].stop = &stop;
        if (W[i].kind == REPM || W[i].kind == REPS || W[i].kind == MEMC) W[i].mem = VirtualAlloc(NULL, 4 << 20, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
        W[i].h = CreateThread(NULL, 0, worker, &W[i], 0, NULL);
        if (!W[i].h) { puts("WITNESS stw CreateThread failed"); return 3; }
    }
    while (started < nt) Sleep(1);
    Sleep(20);
    static double v[100000]; int done = 0, bad = 0, refused = 0, failed = 0, seen = 0; LARGE_INTEGER begin, a, b; QueryPerformanceCounter(&begin);
    if (rounds > 100000) rounds = 100000;
    for (; done < rounds; done++) {
        QueryPerformanceCounter(&a); if (us(begin, a) > budget * 1e6) break;
        for (int i = 0; i < nt; i++) if (SuspendThread(W[i].h) == (DWORD)-1) failed++;
        for (int i = 0; i < nt; i++) {
            CONTEXT c; memset(&c, 0, sizeof c); c.ContextFlags = CONTEXT_FULL; int tries = 0, ok;
            while (!(ok = GetThreadContext(W[i].h, &c)) && ++tries < 5) { refused++; ResumeThread(W[i].h); Sleep(0); SuspendThread(W[i].h); }
            if (!ok) { failed++; continue; }
            bad += check(&W[i], &c, &seen) != 0;
        }
        QueryPerformanceCounter(&b); v[done] = us(a, b);
        for (int i = 0; i < nt; i++) ResumeThread(W[i].h);
        SetEvent(ev);
        QueryPerformanceCounter(&a); do { if (gap > 500) Sleep(0); QueryPerformanceCounter(&b); } while (us(a, b) < gap);
    }
    stop = 1; int stuck = 0; u64 errs = 0, idle = 0;
    for (int i = 0; i < nt; i++) { SetEvent(ev); if (WaitForSingleObject(W[i].h, 5000) != WAIT_OBJECT_0) stuck++; errs += W[i].err; if (!W[i].iters) idle++; }
    for (int i = 1; i < done; i++) { double x = v[i]; int j = i; while (j && v[j - 1] > x) { v[j] = v[j - 1]; j--; } v[j] = x; }
    double sum = 0; for (int i = 0; i < done; i++) sum += v[i];
    printf("WITNESS stw rounds=%d of %d threads=%d contexts=%d mean_us=%.0f median_us=%.0f p99_us=%.0f slowest_us=%.0f refused=%d failed=%d wrong_contexts=%d wrong_results=%llu stuck=%d idle=%llu\n", done, rounds, nt, seen,
           done ? sum / done : 0, done ? v[done / 2] : 0, done ? v[done * 99 / 100] : 0, done ? v[done - 1] : 0, refused, failed, bad, errs, stuck, idle);
    fflush(stdout);
    return bad || errs || stuck || failed ? 1 : done < rounds ? 2 : 0;
}
