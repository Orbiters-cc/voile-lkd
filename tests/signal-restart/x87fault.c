/* x87fault: an x87 stack that is not in the context yet when an instruction faults. The random programs of gen_x87.py run with the page
 * accessible, and with it inaccessible or read-only, where the handler clobbers the x87 state, gives the access back and returns. The
 * state at the end must be the same, and the state the handler finds in its frame the one before the instruction.
 * Exit status 0: all right. */
#include "nolibc.h"
extern struct { void (*x)(void *, void *, void *), (*y)(void *, void *, void *); char *f; u64 mmx, image; } x87_table[]; extern u64 x87_count;
enum { HP = 16384 };
static u8 *M; static volatile u64 nfault, frip; static u8 seen[512] __attribute__((aligned(16)));
static void on_segv(int s, void *i, void *u) {
    (void)s; struct uctx *c = u; u64 a = ((struct siginfo *)i)->addr; u8 *fx = *(u8 **)(&c->cr2 + 1);
    if (a < (u64)M || a >= (u64)M + HP || ++nfault > 9) { pf("WITNESS fault rip=%lx rsp=%lx addr=%lx\n", c->rip, c->rsp, a); die(3); }
    frip = c->rip; memcpy(seen, fx, 512);
    __asm__ volatile("fninit; fldpi; fldpi; fldpi; fldl2e; fld1; fldz; fldpi; fldpi; fincstp" ::);
    SC(SYS_mprotect, M, HP, PROT_READ | PROT_WRITE);
}
/* fcw, fsw, abridged ftw, and of each register in the stack its 10 bytes. Without the invalid flag: the translator drops an operation
 * whose result nothing uses, with the flag it would raise, and does not when the same code is entered in its middle. */
static int differs(const u8 *a, const u8 *b, const char **what) {
    if (*(u16 *)a != *(u16 *)b) { *what = "fcw"; return 1; }
    if ((*(u16 *)(a + 2) ^ *(u16 *)(b + 2)) & 0xfffe) { *what = "fsw"; return 1; }
    if (a[4] != b[4]) { *what = "ftw"; return 1; }
    int top = (a[3] >> 3) & 7;
    for (int i = 0; i < 8; i++) if (a[4] >> ((top + i) & 7) & 1) for (int k = 0; k < 10; k++) if (a[32 + 16 * i + k] != b[32 + 16 * i + k]) { static const char *n[8] = { "st0", "st1", "st2", "st3", "st4", "st5", "st6", "st7" }; *what = n[i]; return 1; }
    return 0;
}
int main(int argc, char **argv) {
    (void)argc; (void)argv;
    static const u64 D[16] = { 0x3ff8000000000000ul, 0xc004000000000000ul, 0x4059000000000000ul, 0x3fb999999999999aul, 0xbff0000000000000ul, 0x4000000000000000ul, 0, 0x8000000000000000ul,
        1, 0x000fffffffffffffull, 0x7ff0000000000000ul, 0xfff0000000000000ul, 0x7ff8000000001234ul, 0x7fefffffffffffffull, 0x0010000000000000ul, 0x3ca0000000000000ul };
    static const u32 F[16] = { 0x3fc00000, 0xc0200000, 0x42c80000, 0x3dcccccd, 0xbf800000, 0x40000000, 0, 0x80000000, 1, 0x7fffff, 0x7f800000, 0xff800000, 0x7fc00123, 0x7f7fffff, 0x800000, 0x3f000001 };
    M = map(0, 2 * HP, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS); M = (u8 *)(((u64)M + HP - 1) & ~(u64)(HP - 1));
    u8 *v = map(0, 4 * HP, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS), *img = v + HP, *want = img + 512, *end = want + 512;
    u8 *alt = map(0, 1 << 18, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS); u64 ss[3] = { (u64)alt, 0, 1 << 18 }; SC(131, ss, 0);
    sigact(SIGSEGV, on_segv, SA_ONSTACK); sigact(SIGBUS, on_segv, SA_ONSTACK);
    int bad = 0, faults = 0;
    for (u64 n = 0; n < x87_count; n++) for (int round = 0; round < 3; round++) {
#define INIT for (int i = 0; i < 16; i++) { *(u64 *)(v + 16 * i) = D[i]; *(u32 *)(v + 16 * i + 8) = F[i]; *(u64 *)(v + 0x100 + 16 * i) = 0x8000000000000000ul | D[i] << 3 | i; *(u16 *)(v + 0x108 + 16 * i) = (u16)(0x3ff0 + i * 3 + (i & 1) * 0x8000); \
        *(u64 *)(v + 0x200 + 8 * i) = (u64)(i - 7) * 0x10101; } for (int k = 0x400; k < 0x800; k++) v[k] = (u8)(k * 3); memset(M, 0, 512); *(u64 *)M = round ? 0x4008000000000000ul : 0x3ff0cccccccccccdul; *(u64 *)(M + 8) = 0x4001;
        const char *what = ""; int wrong = 0;
        INIT x87_table[n].y(M, want, v);
        INIT nfault = 0; x87_table[n].x(M, end, v); static u8 mend[512]; memcpy(mend, M, 512); static u8 keep[0x400]; memcpy(keep, v + 0x400, 0x400);
        INIT nfault = 0; SC(SYS_mprotect, M, HP, round == 1 ? PROT_READ : PROT_NONE);
        x87_table[n].x(M, img, v); SC(SYS_mprotect, M, HP, PROT_READ | PROT_WRITE);
        faults += (int)nfault;
        if (differs(end, img, &what)) { pf("WITNESS x87 program %lu round %d: %s at the end differs from a run without a fault\n", n, round, what); wrong = 1; }
        int other = 0; /* (an image of the state holds registers that are empty too, where a value that was popped may or may not be) */
        if (x87_table[n].image == 1) other = differs(mend, M, &what); else for (int k = 0; k < (x87_table[n].image ? 12 : 512); k++) other |= mend[k] != M[k] && !(x87_table[n].image && k == 4);
        if (other) { pf("WITNESS x87 program %lu round %d: what it stored on the page differs\n", n, round); wrong = 1; }
        for (int k = 0; k < 0x400; k++) if (keep[k] != v[0x400 + k]) { pf("WITNESS x87 program %lu round %d: what it stored at +%x differs\n", n, round, 0x400 + k); wrong = 1; break; }
        if (nfault) {
            if (frip != (u64)x87_table[n].f) { pf("WITNESS x87 program %lu: the fault was reported at %lx, not at %lx\n", n, frip, (u64)x87_table[n].f); wrong = 1; }
            /* (the engine has changed to the MMX state when an MMX instruction faults: the top and the tags are those after it) */
            if (!x87_table[n].mmx && differs(want, seen, &what)) { pf("WITNESS x87 program %lu round %d: %s in the handler's frame is not the one before the instruction\n", n, round, what); wrong = 1; }
        } else if (round != 1) { pf("WITNESS x87 program %lu did not fault\n", n); wrong = 1; }
        bad += wrong; if (bad > 8) goto out;
    }
out:
    pf("WITNESS x87fault programs=%lu faults=%d bad=%d\n", x87_count, faults, bad);
    return bad != 0;
}
