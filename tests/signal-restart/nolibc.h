/* Minimal freestanding x86-64 Linux runtime for the witnesses: raw system calls, threads through clone, tiny printf. */
#ifndef NOLIBC_H
#define NOLIBC_H
typedef unsigned long u64; typedef long i64; typedef unsigned int u32; typedef unsigned char u8; typedef unsigned short u16;
#define NULL ((void*)0)
static inline i64 sc6(i64 n, i64 a, i64 b, i64 c, i64 d, i64 e, i64 f) {
    register i64 r10 __asm__("r10") = d; register i64 r8 __asm__("r8") = e; register i64 r9 __asm__("r9") = f; i64 r;
    __asm__ volatile("syscall" : "=a"(r) : "a"(n), "D"(a), "S"(b), "d"(c), "r"(r10), "r"(r8), "r"(r9) : "rcx", "r11", "memory");
    return r;
}
#define SC(n, ...) SC_(n, ##__VA_ARGS__, 0, 0, 0, 0, 0, 0)
#define SC_(n, a, b, c, d, e, f, ...) sc6(n, (i64)(a), (i64)(b), (i64)(c), (i64)(d), (i64)(e), (i64)(f))
enum { SYS_read = 0, SYS_write = 1, SYS_open = 2, SYS_close = 3, SYS_mmap = 9, SYS_mprotect = 10, SYS_munmap = 11, SYS_rt_sigaction = 13,
       SYS_rt_sigprocmask = 14, SYS_madvise = 28, SYS_nanosleep = 35, SYS_getpid = 39, SYS_clone = 56, SYS_exit = 60, SYS_gettid = 186,
       SYS_futex = 202, SYS_clock_gettime = 228, SYS_exit_group = 231, SYS_tgkill = 234, SYS_sched_yield = 24, SYS_mremap = 25,
       SYS_memfd_create = 319, SYS_ftruncate = 77 };
#define PROT_NONE 0
#define PROT_READ 1
#define PROT_WRITE 2
#define PROT_EXEC 4
#define MAP_SHARED 1
#define MAP_PRIVATE 2
#define MAP_FIXED 0x10
#define MAP_ANONYMOUS 0x20
#define MAP_NORESERVE 0x4000
#define MAP_FIXED_NOREPLACE 0x100000
#define MADV_DONTNEED 4
#define MADV_FREE 8
#define SIGUSR1 10
#define SIGSEGV 11
#define SIGBUS 7
#define SIGILL 4
#define SA_SIGINFO 4
#define SA_RESTORER 0x04000000
#define SA_RESTART 0x10000000
#define SA_NODEFER 0x40000000
#define SA_ONSTACK 0x08000000
struct ksigaction { void (*handler)(int, void *, void *); u64 flags; void (*restorer)(void); u64 mask; };
struct timespec { i64 tv_sec, tv_nsec; };
/* x86-64 Linux ucontext: uc_flags, uc_link, uc_stack (3 words), then sigcontext gregs. */
struct uctx { u64 flags, link, ss_sp; u64 ss_flags_pad, ss_size;
              u64 r8, r9, r10, r11, r12, r13, r14, r15, rdi, rsi, rbp, rbx, rdx, rax, rcx, rsp, rip, eflags, csgsfs, err, trapno, oldmask, cr2; };
struct siginfo { int signo, err, code, pad; u64 addr; };

static inline void *memset(void *d, int c, u64 n) { u8 *p = d; while (n--) *p++ = (u8)c; return d; }
static inline void *memcpy(void *d, const void *s, u64 n) { u8 *p = d; const u8 *q = s; while (n--) *p++ = *q++; return d; }
static inline u64 strlen_(const char *s) { u64 n = 0; while (s[n]) n++; return n; }
static inline void wr(const char *s, u64 n) { while (n) { i64 r = SC(SYS_write, 1, s, n); if (r <= 0) return; s += r; n -= r; } }
/* %s %d %u %x %lx %lu %ld %p; enough for the witnesses. One write per call so lines of several threads do not mix. */
static void pf(const char *f, ...) {
    char b[512]; u64 n = 0; __builtin_va_list ap; __builtin_va_start(ap, f);
    for (; *f && n < sizeof b - 40; f++) {
        if (*f != '%') { b[n++] = *f; continue; }
        f++; int l = 0; if (*f == 'l') { l = 1; f++; }
        if (*f == 's') { const char *s = __builtin_va_arg(ap, const char *); while (*s && n < sizeof b - 40) b[n++] = *s++; continue; }
        u64 v; int neg = 0, base = 10;
        if (*f == 'd') { i64 x = l ? __builtin_va_arg(ap, i64) : __builtin_va_arg(ap, int); if (x < 0) { neg = 1; x = -x; } v = (u64)x; }
        else if (*f == 'p') { v = __builtin_va_arg(ap, u64); base = 16; }
        else { v = l ? __builtin_va_arg(ap, u64) : __builtin_va_arg(ap, u32); if (*f == 'x') base = 16; }
        char t[24]; int k = 0; do { t[k++] = "0123456789abcdef"[v % base]; v /= base; } while (v);
        if (neg) b[n++] = '-';
        while (k) b[n++] = t[--k];
    }
    __builtin_va_end(ap); wr(b, n);
}
static inline void die(int code) { SC(SYS_exit_group, code); for (;;) {} }
static inline u64 now_ns(void) { struct timespec t; SC(SYS_clock_gettime, 1, &t); return (u64)t.tv_sec * 1000000000ull + (u64)t.tv_nsec; }
static inline void sleep_us(u64 us) { struct timespec t = { (i64)(us / 1000000), (i64)(us % 1000000) * 1000 }; SC(SYS_nanosleep, &t, 0); }
static inline void *map(void *a, u64 n, int prot, int flags) { return (void *)SC(SYS_mmap, a, n, prot, flags, -1, 0); }
static inline int is_err(void *p) { return (u64)p > (u64)-4096; }
void rt_restorer(void);
__asm__(".text\n.globl rt_restorer\nrt_restorer:\n mov $15,%eax\n syscall\n");
static inline void sigact(int sig, void (*h)(int, void *, void *), u64 flags) {
    struct ksigaction a = { h, flags | SA_RESTORER | SA_SIGINFO, rt_restorer, 0 };
    SC(SYS_rt_sigaction, sig, &a, 0, 8);
}
/* Threads: clone with a fresh stack; the child pops fn and arg, calls fn(arg), and exits. tid[0] is cleared and woken at exit. */
i64 clone_raw(u64 flags, void *stack_top, int *ptid, int *ctid);
__asm__(".text\n.globl clone_raw\nclone_raw:\n mov %rcx,%r10\n xor %r8d,%r8d\n mov $56,%eax\n syscall\n test %rax,%rax\n jnz 1f\n"
        " xor %ebp,%ebp\n pop %rax\n pop %rdi\n call *%rax\n mov $60,%eax\n xor %edi,%edi\n syscall\n1: ret\n");
struct thr { volatile int tid; void *stack; };
static int thr_start(struct thr *t, void (*fn)(void *), void *arg) {
    u64 sz = 1 << 20; u8 *st = map(0, sz, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS);
    if (is_err(st)) return -1;
    u64 *top = (u64 *)(st + sz - 64); top[0] = (u64)fn; top[1] = (u64)arg; t->stack = st; t->tid = 1;
    /* CLONE_VM|FS|FILES|SIGHAND|THREAD|SYSVSEM|PARENT_SETTID|CHILD_CLEARTID */
    i64 r = clone_raw(0x100 | 0x200 | 0x400 | 0x800 | 0x10000 | 0x40000 | 0x100000 | 0x200000, top, (int *)&t->tid, (int *)&t->tid);
    return r < 0 ? (int)r : 0;
}
static void thr_join(struct thr *t) { int v; while ((v = t->tid) != 0) SC(SYS_futex, &t->tid, 0 /*FUTEX_WAIT*/, v, 0); }
int main(int, char **);
__asm__(".text\n.globl _start\n_start:\n xor %ebp,%ebp\n mov (%rsp),%rdi\n lea 8(%rsp),%rsi\n and $-16,%rsp\n call main\n mov %eax,%edi\n mov $231,%eax\n syscall\n");
#endif
