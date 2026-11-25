/* repstorm: string instructions of every length, direction and overlap, while another thread sends signals. Each is compared with the
 * same done one element at a time: memory, rcx, rsi, rdi, rax and the flags. Usage: repstorm SECONDS GAP_US|-   Exit status 0: all right. */
#include "nolibc.h"
enum { SZ = 1 << 20, OPS = 10 };
static u8 *A, *B; static volatile int tid, stop; static volatile u64 handled, sent; static volatile u64 inrep; static struct thr T;
static void on_usr1(int s, void *i, void *u) {
    (void)s; (void)i; struct uctx *c = u; handled++;
    { const u8 *p = (const u8 *)c->rip; if (*p == 0xf3 || *p == 0xf2) { p++; if (*p == 0x66) p++; if ((*p & 0xf0) == 0x40) p++; inrep += (*p & 0xfc) == 0xa4 || (*p & 0xf8) == 0xa8; } else if (*p == 0x66 && p[1] == 0xf3) inrep++; }
    u64 r; __asm__ volatile("std; mov $77,%%ecx; lea %1,%%rsi; lea %1,%%rdi; cld" : "=c"(r), "=m"(handled) :: "rsi", "rdi", "cc"); (void)r;
}
static void sender(void *p) {
    u64 gap = (u64)p; int pid = (int)SC(SYS_getpid);
    while (!tid) sleep_us(100);
    for (u64 n = 0; !stop; n++) { SC(SYS_tgkill, pid, tid, SIGUSR1); sent++; if (gap) { u64 t = now_ns() + (gap / 2 + (n * 37) % gap) * 1000; while (now_ns() < t) SC(SYS_sched_yield); } }
}
struct regs { u64 c, s, d, a, f; };
#define RUN(insn, pre, post) __asm__ volatile("push %%rbx; mov %%rcx,%%rbx; " pre "cmp $1,%%rbx; mov %%rbx,%%rcx; pop %%rbx; " insn "; pushfq; pop %%r8; " post "mov %%r8,%4" \
    : "+c"(r->c), "+S"(r->s), "+D"(r->d), "+a"(r->a), "=r"(r->f) :: "r8", "cc", "memory")
static void native(int op, int down, struct regs *r) {
#define EACH(i, insn) case i: if (down) RUN(insn, "std; ", "cld; "); else RUN(insn, "cld; ", "cld; "); break;
    switch (op) { EACH(0, "rep movsb") EACH(1, "rep movsw") EACH(2, "rep movsl") EACH(3, "rep movsq") EACH(4, "rep stosb") EACH(5, "rep stosl") EACH(6, "rep stosq") EACH(7, "repe cmpsb") EACH(8, "repne scasb") EACH(9, "rep lodsl") }
}
/* one element at a time; the flags of the last comparison by the same instruction on that element */
static void slow(int op, int down, struct regs *r) {
    static const int W[OPS] = { 1, 2, 4, 8, 1, 4, 8, 1, 1, 4 }; int w = W[op]; i64 st = down ? -w : w; r->f = r->c == 0 ? 0 : r->f; int cmpd = 0; u64 n = r->c;
    u8 x = 0, y = 0;
    while (n) {
        n--;
        if (op <= 3) { u64 v = 0; memcpy(&v, (void *)r->s, w); memcpy((void *)r->d, &v, w); r->s += st; r->d += st; }
        else if (op <= 6) { memcpy((void *)r->d, &r->a, w); r->d += st; }
        else if (op == 7) { x = *(u8 *)r->s; y = *(u8 *)r->d; r->s += st; r->d += st; cmpd = 1; if (x != y) break; }
        else if (op == 8) { x = (u8)r->a; y = *(u8 *)r->d; r->d += st; cmpd = 1; if (x == y) break; }
        else { u32 v; memcpy(&v, (void *)r->s, 4); r->a = v; r->s += st; }
    }
    /* what comes before it: cmp $1, count */
    u64 f, c0 = r->c; if (cmpd) __asm__ volatile("cmpb %2,%1; pushfq; pop %0" : "=r"(f) : "q"(x), "q"(y) : "cc"); else __asm__ volatile("cmp $1,%1; pushfq; pop %0" : "=r"(f) : "r"(c0) : "cc");
    r->f = f; r->c = n;
}
static u32 xs = 2463534242u; static u32 rnd(void) { xs ^= xs << 13; xs ^= xs >> 17; xs ^= xs << 5; return xs; }
static u64 atou(const char *s) { u64 v = 0; while (*s >= '0' && *s <= '9') v = v * 10 + (u64)(*s++ - '0'); return v; }
int main(int argc, char **argv) {
    u64 secs = argc > 1 ? atou(argv[1]) : 5; int storm = argc > 2 && argv[2][0] != '-'; u64 gap = storm ? atou(argv[2]) : 0;
    A = map(0, SZ, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS); B = map(0, SZ, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS);
    sigact(SIGUSR1, on_usr1, SA_RESTART); if (storm && thr_start(&T, sender, (void *)gap)) return 2;
    tid = (int)SC(SYS_gettid); u64 end = now_ns() + secs * 1000000000ul, n = 0; int bad = 0;
    for (int k = 0; k < SZ; k++) A[k] = B[k] = (u8)(k * 7 + (k >> 9));
    while (now_ns() < end && bad < 5) {
        static const int W[OPS] = { 1, 2, 4, 8, 1, 4, 8, 1, 1, 4 };
        int op = (int)(rnd() % OPS), down = (int)(rnd() & 1), w = W[op]; u64 lens[6] = { rnd() % 70, rnd() % 5000, 32768 / w, 32768 / w + 1 + rnd() % 3, rnd() % (200000 / w), 65536 / w + rnd() % (100000 / w) }, len = lens[rnd() % 6], bytes = len * w;
        if (bytes > 400000) bytes = 400000 - 400000 % w, len = bytes / w;
        u64 so = 2000 + rnd() % (SZ - 404000 - 2000), dof = rnd() % 3 == 0 ? so + (rnd() % 3 == 0 ? 0 : rnd() % 100) - (rnd() % 2 ? 0 : 50) : 2000 + rnd() % (SZ - 404000 - 2000);
        if (op == 7) for (u64 k = 0; k < bytes; k++) { u64 q = k + 8000 < bytes ? k + 8000 : bytes; for (; k < q; k++) B[so + k] = A[so + k] = A[dof + k] = B[dof + k]; if (rnd() % 3 == 0) break; }
        u64 sv = so + (down && bytes ? bytes - w : 0), dv = dof + (down && bytes ? bytes - w : 0), a = op == 8 ? 0x100 + (rnd() % 8 ? 0x55 : 0) : rnd() * 0x100000001ul;
        if (op == 8) { u8 miss = (u8)a; for (u64 k = 0; k < bytes; k++) if (A[dof + k] == miss && rnd() % 60) { A[dof + k] ^= 1; B[dof + k] = A[dof + k]; } }
        struct regs ra = { len, (u64)A + sv, (u64)A + dv, a, 0 }, rb = { len, (u64)B + sv, (u64)B + dv, a, 0 };
        native(op, down, &ra); slow(op, down, &rb); n++;
        ra.s -= (u64)A; ra.d -= (u64)A; rb.s -= (u64)B; rb.d -= (u64)B;
        u64 fm = 0x8d5; int wrong = ra.c != rb.c || ra.s != rb.s || ra.d != rb.d || ra.a != rb.a || ((ra.f ^ rb.f) & fm);
        u64 at = 0; for (u64 k = 0; k < SZ && n % 4 == 0; k += 8) if (*(u64 *)(A + k) != *(u64 *)(B + k)) { wrong = 1; at = k; break; }
        if (wrong) { bad++; pf("WITNESS rep op %d down %d len %lu from %lu to %lu: rcx %lx %lx rsi %lx %lx rdi %lx %lx ", op, down, len, sv, dv, ra.c, rb.c, ra.s, rb.s, ra.d, rb.d); pf("rax %lx %lx flags %lx %lx memory at %lx\n", ra.a, rb.a, ra.f & fm, rb.f & fm, at); memcpy(B, A, SZ); }
    }
    stop = 1; if (storm) thr_join(&T);
    pf("WITNESS repstorm instructions=%lu sent=%lu handled=%lu inside=%lu bad=%d\n", n, sent, handled, inrep, bad);
    return bad != 0;
}
