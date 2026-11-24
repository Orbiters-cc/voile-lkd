/* syncfault: a fault the guest resolves and restarts (a guard page, a write-protected page: what Wine does for write watches,
 * guard pages and copy on write). Every case of syncfault_k.S runs on a page that is accessible, then on one that is not
 * accessible and on one that is read-only, where the handler makes it accessible and returns. The results must be the same, and
 * the handler must be given the address of the instruction that faults, with the registers x86 has there.
 * Usage: syncfault [CASE]...   Exit status: 0 all right, 1 something differs. */
#include "nolibc.h"
#define CASES(X) X(pop_pair) X(pop_ret) X(push_pair) X(push_call) X(push_mem) X(pop_mem) X(pop_mem_rsp) X(pop_mem16) X(pop_pop_mem) X(leave_ret) X(push_flags) \
    X(mov_load) X(mov_add_mem) X(xchg_store) X(cqo_idiv_mem) X(add_store_adc) X(add_load_adc) X(sub_store_sbb) X(cmp_store_jcc) X(adc_mem1) X(adc_mem0) X(adc_mem_b) \
    X(sbb_mem1) X(sbb_mem_b) X(adcb_mem) X(adcw_mem) X(rcl_mem) X(rcr_mem) X(rcr_mem_a) X(rcl_mem_a) X(rclb_mem_a) X(rep_lodsb) X(adcx_mem) X(cmov_mem) X(sahf_push) X(inc_mem) X(add_mem) X(neg_mem) X(shl_mem) X(shl0_mem) X(setc_mem) X(bts_mem) X(xchg_mem) X(xadd_mem) \
    X(lock_xadd_mem) X(lock_add_mem) X(lock_adc_mem) X(cmpxchg_mem) X(lock_cmpxchg_mem) X(cmpxchg16b_mem) X(mul_mem) X(movsq_) X(movsq_std) X(stosq_std) X(rep_movsb) \
    X(rep_movsb_down) X(rep_movsq_down) X(rep_movsb_fill) X(rep_movsb_up) X(rep_stosb) X(rep_cmpsb) X(rep_scasb) X(sse_load) X(avx_store) X(avx_load) X(avx_load_cross) \
    X(avx_store_cross) X(avx_scalar_store) X(avx_gather) X(avx_maskstore) X(x87_store) X(x87_load) X(x87_scalar_store) X(mmx_store) X(big) X(bigctl)
#define D(n) void t_##n(u64, u64 *, u64 *); extern char t_##n##_f[]; extern char t_##n##_g[] __attribute__((weak));
CASES(D)
#define E(n) {#n, t_##n, t_##n##_f, t_##n##_g},
static const struct { const char *n; void (*f)(u64, u64 *, u64 *); char *fault, *alt; } C[] = { CASES(E) };
enum { HP = 16384, N = 8 };
static u8 *M; static volatile u64 nfault, frip;
static void on_segv(int s, void *i, void *u) {
    (void)s; struct uctx *c = u; struct siginfo *si = i; u64 a = si->addr;
    if (a < (u64)M || a >= (u64)M + N * HP) { pf("WITNESS fault outside the page: rip=%lx rsp=%lx addr=%lx\n", c->rip, c->rsp, a); die(3); }
    if (!nfault) frip = c->rip;
    if (++nfault > 50) { pf("WITNESS the same fault again and again: rip=%lx addr=%lx\n", c->rip, a); die(3); }
    __asm__ volatile("fninit; vzeroall; std; cld" ::: "xmm0", "xmm1", "xmm2", "xmm3", "xmm4", "xmm5", "xmm6", "xmm7");
    SC(SYS_mprotect, a & ~(u64)(HP - 1), HP, PROT_READ | PROT_WRITE);
}
static void fill(u64 v) { for (u64 k = 0; k < N * HP; k++) M[k] = (u8)(k * 37 + (k >> 8) + v); M[2 * HP + 0x50] = 7; for (int k = 1; k < 8; k++) M[2 * HP + 0x50 + k] = 0; M[2 * HP + 0x68 + 1] = 0x12; }
int main(int argc, char **argv) {
    M = map(0, (N + 1) * HP, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS); M = (u8 *)(((u64)M + HP - 1) & ~(u64)(HP - 1));
    u8 *keep = map(0, N * HP, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS), *alt = map(0, 1 << 18, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS);
    u64 ss[3] = { (u64)alt, 0, 1 << 18 }; SC(131 /* sigaltstack */, ss, 0);
    sigact(SIGSEGV, on_segv, SA_ONSTACK); sigact(SIGBUS, on_segv, SA_ONSTACK);
    u64 page = (u64)M + 2 * HP; int bad = 0, ran = 0, faults = 0;
    for (u32 k = 0; k < sizeof C / sizeof *C; k++) {
        if (argc > 1) { int hit = 0; for (int q = 1; q < argc; q++) { const char *a = argv[q], *b = C[k].n; while (*a && *a == *b) a++, b++; hit |= !*a && !*b; } if (!hit) continue; }
        ran++;
        for (int round = 0; round < 12; round++) {
            u64 in[1] = { 0x1000 + (u64)round * 0x111 }, want[10] = {0}, got[10] = {0};
            int prot = round % 3 == 0 ? PROT_READ : round % 3 == 1 ? PROT_NONE : PROT_READ;
            /* what the second stack page holds: the return address of pop_ret */
            fill(in[0]); extern char t_pop_ret_9[]; u64 *ret = (u64 *)page;
            if (C[k].f == t_pop_ret || C[k].f == t_leave_ret) ret[0] = (u64)t_pop_ret_9;
            nfault = 0; C[k].f(page, want, in); memcpy(keep, M, N * HP);
            fill(in[0]); if (C[k].f == t_pop_ret || C[k].f == t_leave_ret) ret[0] = (u64)t_pop_ret_9;
            nfault = 0; SC(SYS_mprotect, page, HP, prot);
            C[k].f(page, got, in);
            u64 n = nfault; SC(SYS_mprotect, page, HP, PROT_READ | PROT_WRITE); faults += (int)n;
            int wrong = 0; for (int q = 0; q < 10; q++) if (want[q] != got[q]) { pf("WITNESS %s prot=%d out[%d] = %lx, without a fault %lx\n", C[k].n, prot, q, got[q], want[q]); wrong = 1; }
            for (u64 q = 0; q < N * HP; q++) if (keep[q] != M[q]) { pf("WITNESS %s prot=%d memory at page%s%lx differs: %x, without a fault %x\n", C[k].n, prot, q < 2 * HP ? "-" : "+", q < 2 * HP ? 2 * HP - q : q - 2 * HP, M[q], keep[q]); wrong = 1; break; }
            if (n && frip != (u64)C[k].fault && !(C[k].alt && frip == (u64)C[k].alt)) { pf("WITNESS %s prot=%d the fault was reported at %lx, not at %lx\n", C[k].n, prot, frip, (u64)C[k].fault); wrong = 1; }
            if (prot == PROT_NONE && !n) { pf("WITNESS %s did not fault\n", C[k].n); wrong = 1; }
            if (wrong) { pf("WITNESS case %s WRONG\n", C[k].n); bad++; break; }
        }
    }
    pf("WITNESS syncfault cases=%d faults=%d bad=%d\n", ran, faults, bad);
    return bad != 0;
}
