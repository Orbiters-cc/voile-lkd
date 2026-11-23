/* test_ptrace_transport.c: the shared table, its lock, the cross-process wake and the cost of a stop and a
 * resume. The table is the module's own design (no Linux counterpart): its cases check the contract written
 * in src/ptrace/transport.c. The round-trip cases print MESURE lines and assert only generous bounds. */
#include "test_ptrace_util.h"
#include "../src/ptrace/pt_priv.h"

/* The table holds PT_SLOTS links; the 513th fails visibly with EAGAIN, a duplicate tid with EPERM (already
 * traced, like ptrace_attach()). Freed slots are reused with a new generation. */
LT_TEST(table_capacity)
{
    int idx[PT_SLOTS + 4];
    int n = 0;
    for (; n < PT_SLOTS + 4; n++) {
        int i = pt_link(0x20000 + n, 0x20000 + n, getpid(), 1000, 1, 1, getpid(), 0, 0);
        if (i < 0) { LT_EQ(i, -LX_EAGAIN); break; }
        idx[n] = i;
    }
    LT_EQ(n, PT_SLOTS);
    LT_EQ(pt_link(0x20003, 5, getpid(), 1000, 1, 1, getpid(), 0, 0), -LX_EPERM);
    LT_EQ(pt_find_tracee(0x20005), idx[5]);
    LT_EQ(pt_find_tracee(0x2ffff), -1);
    uint32_t gen = pt_slot_at(idx[7])->gen;
    pt_lock();
    pt_free_locked(idx[7]);
    pt_unlock();
    LT_EQ(pt_find_tracee(0x20007), -1);
    int j = pt_link(0x30000, 0x30000, getpid(), 1000, 1, 1, getpid(), 0, 0);
    LT_EQ(j, idx[7]);
    LT_EQ(pt_slot_at(j)->gen, gen + 1);
    LT_EQ(lkd_ptrace_tracer_of(0x30000), 1);
    pt_lock();
    for (int k = 0; k < n; k++) pt_free_locked(idx[k]);
    pt_unlock();
    LT_EQ(lkd_ptrace_tracer_of(0x20005), 0);
}

static void *lock_thread(void *arg)
{
    pt_lock();
    *(volatile int *)arg = 1;
    pt_unlock();
    return NULL;
}

/* A process that dies holding the table lock does not block the others: the byte-range lock is dropped by
 * the host kernel (CONVENTIONS 3, rule 4). */
LT_TEST(lock_is_released_when_the_holder_dies)
{
    int up[2];
    LT_EQ(pipe(up), 0);
    fflush(NULL);
    pid_t c = fork();
    if (c == 0) {
        alarm(20);
        pt_lock();
        char b = 1;
        (void)!write(up[1], &b, 1);
        sleep(15);
        _exit(0);
    }
    char b;
    LT_EQ(read(up[0], &b, 1), 1);
    volatile int got = 0;
    pthread_t th;
    LT_EQ(pthread_create(&th, NULL, lock_thread, (void *)&got), 0);
    usleep(150000);
    LT_EQ(got, 0);                                               /* blocked while the child holds it */
    kill(c, SIGKILL);
    int st;
    waitpid(c, &st, 0);
    for (int i = 0; i < 400 && !got; i++) usleep(5000);
    LT_EQ(got, 1);
    pthread_join(th, NULL);
    close(up[0]); close(up[1]);
}

/* The table is shared memory: what a forked process writes under the lock is seen by the parent, and the
 * parent's links are visible in the child. */
LT_TEST(table_is_shared_between_processes)
{
    int i = pt_link(0x40000, 0x40000, getpid(), 1000, 7, 7, getpid(), 0x11, 0);
    LT_CHECK(i >= 0);
    int fd[2];
    LT_EQ(pipe(fd), 0);
    fflush(NULL);
    pid_t c = fork();
    if (c == 0) {
        alarm(20);
        int ok = pt_find_tracee(0x40000) == i && pt_slot_at(i)->options == 0x11;
        pt_lock();
        pt_slot_at(i)->options = 0x22;
        pt_slot_at(i)->msg = 0x1234567890ull;
        pt_unlock();
        _exit(ok ? 0 : 1);
    }
    int st;
    waitpid(c, &st, 0);
    LT_CHECK(WIFEXITED(st) && WEXITSTATUS(st) == 0);
    LT_EQ(pt_slot_at(i)->options, 0x22);
    LT_EQ(pt_slot_at(i)->msg, 0x1234567890ull);
    pt_lock();
    pt_free_locked(i);
    pt_unlock();
    close(fd[0]); close(fd[1]);
}

/* pt_wake_tracee() reaches a task of another host process through the family service and ends its wait on
 * the wake pipe. */
LT_TEST(wake_crosses_processes)
{
    int up[2], ack[2];
    LT_EQ(pipe(up), 0);
    LT_EQ(pipe(ack), 0);
    fflush(NULL);
    int64_t pid = sct(TR, LKD_NR_fork, 0, 0, 0, 0, 0, 0);
    if (pid == 0) {
        alarm(30);
        lkd_task *t = lkd_current();
        char b = 1;
        (void)!write(up[1], &b, 1);
        struct pollfd p = { .fd = t->wake_rd, .events = POLLIN };
        int r = poll(&p, 1, 10000);
        int64_t v = r > 0 ? 1 : 0;
        (void)!write(ack[1], &v, sizeof v);
        int st;
        (void)sct(t, LKD_NR_exit_group, 0, 0, 0, 0, 0, 0);
        if (lkd_task_release(t, &st)) _exit(st);
        _exit(90);
    }
    LT_CHECK(pid > 0);
    char b;
    LT_EQ(read(up[0], &b, 1), 1);
    usleep(50000);
    LT_EQ(pt_wake_tracee((int32_t)pid, (int32_t)pid, 0, -1, 0), 0);
    LT_EQ(get64(ack[0]), 1);
    int st;
    LT_EQ(wait_pid((int32_t)pid, &st, 0), pid);
    /* a process that does not exist */
    LT_ERRNO(pt_wake_tracee(0x3ffffff0, 0x3ffffff0, 0, -1, 0), LX_ESRCH);
    close(up[0]); close(up[1]); close(ack[0]); close(ack[1]);
}

/* ---- the cost of a stop and a resume -------------------------------------------------------------- */

#define N_ROUNDS 1500

static void report(const char *what, int64_t *v, int n)
{
    qsort(v, (size_t)n, sizeof *v, cmp_i64);
    printf("MESURE %s: n=%d p50=%.1f us p90=%.1f us p99=%.1f us max=%.1f us\n", what, n, (double)v[n / 2] / 1000.0,
           (double)v[n * 9 / 10] / 1000.0, (double)v[n * 99 / 100] / 1000.0, (double)v[n - 1] / 1000.0);
}

/* wait4 with WNOHANG in a loop: the latency of the transport alone, without the 10 ms tick of the blocking
 * wait4 in the task module (src/task/wait.c: lkd_block_sleep does not return on a plain wake-up). */
static int64_t wait_polled(int32_t pid, int *st)
{
    for (int i = 0; i < 20000000; i++) {
        int64_t r = wait_pid(pid, st, LX_WNOHANG);
        if (r != 0) return r;
        if (i > 2000) usleep(20);
    }
    return 0;
}

/* Resume a tracee that makes getpid() calls and wait for its next stop: PTRACE_SYSCALL + wait4, then also
 * with a GETREGSET after each stop, as EAC does. Tracee in a thread of this process. */
LT_TEST(round_trip_thread_tracee)
{
    struct tracee *e = tracee_start(body_loop, NULL);
    for (int i = 0; i < 4000 && e->calls < 3; i++) usleep(500);
    LT_EQ(PT(LX_PTRACE_ATTACH, e->tid, 0, 0), 0);
    LT_CHECK(expect_stop(e->tid, 0x137f));
    static int64_t v[N_ROUNDS];
    int bad = 0;
    for (int i = 0; i < N_ROUNDS; i++) {
        int64_t t0 = mono_ns();
        if (PT(LX_PTRACE_SYSCALL, e->tid, 0, 0) != 0) bad++;
        int st;
        if (wait_pid(e->tid, &st, 0) != e->tid || st != 0x57f) bad++;
        v[i] = mono_ns() - t0;
    }
    LT_EQ(bad, 0);
    report("stop+resume, blocking wait4, tracee in a thread", v, N_ROUNDS);
    LT_CHECK(v[N_ROUNDS / 2] < 30000000);
    for (int i = 0; i < N_ROUNDS; i++) {
        int64_t t0 = mono_ns();
        if (PT(LX_PTRACE_SYSCALL, e->tid, 0, 0) != 0) bad++;
        int st;
        if (wait_polled(e->tid, &st) != e->tid || st != 0x57f) bad++;
        v[i] = mono_ns() - t0;
    }
    LT_EQ(bad, 0);
    report("stop+resume, polled wait4, tracee in a thread", v, N_ROUNDS);
    LT_CHECK(v[N_ROUNDS / 2] < 2000000);
    struct lx_user_regs r;
    for (int i = 0; i < N_ROUNDS; i++) {
        int64_t t0 = mono_ns();
        int64_t n;
        get_regs216(e->tid, &r, &n);
        if (n != 216) bad++;
        v[i] = mono_ns() - t0;
    }
    LT_EQ(bad, 0);
    report("GETREGSET 216 bytes (no round trip: slot read)", v, N_ROUNDS);
    LT_CHECK(v[N_ROUNDS / 2] < 2000000);
    (void)PT(LX_PTRACE_DETACH, e->tid, 0, 0);
    tracee_quit(e);
    get64(e->wr[0]);
    pthread_join(e->th, NULL);
}

static void spin_child(lkd_task *t)
{
    int died = 0;
    cpu_init(t);
    (void)gsys(t, LKD_NR_ptrace, LX_PTRACE_TRACEME, 0, 0, 0, 0, 0, &died);
    died = self_signal(t, LX_SIGSTOP);
    for (int i = 0; i < 100000 && !died; i++) (void)gsys(t, LKD_NR_getpid, 0, 0, 0, 0, 0, 0, &died);
    int st;
    (void)gsys(t, LKD_NR_exit_group, 0, 0, 0, 0, 0, 0, &died);
    if (lkd_task_release(t, &st)) _exit(st);
    _exit(91);
}

/* The same between two host processes: the resume wakes the tracee through the family service (a socket
 * round trip) and the stop notifies the tracer's process the same way. */
LT_TEST(round_trip_process_tracee)
{
    fflush(NULL);
    int64_t pid = sct(TR, LKD_NR_fork, 0, 0, 0, 0, 0, 0);
    if (pid == 0) { alarm(60); spin_child(lkd_current()); _exit(92); }
    LT_CHECK(pid > 0);
    int32_t c = (int32_t)pid;
    LT_CHECK(expect_stop(c, 0x137f));
    static int64_t v[N_ROUNDS];
    int bad = 0;
    for (int i = 0; i < N_ROUNDS; i++) {
        int64_t t0 = mono_ns();
        if (PT(LX_PTRACE_SYSCALL, c, 0, 0) != 0) bad++;
        int st;
        if (wait_pid(c, &st, 0) != c || st != 0x57f) bad++;
        v[i] = mono_ns() - t0;
    }
    LT_EQ(bad, 0);
    report("stop+resume, blocking wait4, tracee in another host process", v, N_ROUNDS);
    LT_CHECK(v[N_ROUNDS / 2] < 30000000);
    for (int i = 0; i < N_ROUNDS; i++) {
        int64_t t0 = mono_ns();
        if (PT(LX_PTRACE_SYSCALL, c, 0, 0) != 0) bad++;
        int st;
        if (wait_polled(c, &st) != c || st != 0x57f) bad++;
        v[i] = mono_ns() - t0;
    }
    LT_EQ(bad, 0);
    report("stop+resume, polled wait4, tracee in another host process", v, N_ROUNDS);
    LT_CHECK(v[N_ROUNDS / 2] < 3000000);
    struct pt_stats s;
    pt_get_stats(&s);
    printf("MESURE stops=%llu resumes=%llu wakes=%llu notifies=%llu (this process)\n", (unsigned long long)s.stops,
           (unsigned long long)s.resumes, (unsigned long long)s.wakes, (unsigned long long)s.notifies);
    LT_EQ(PT(LX_PTRACE_KILL, c, 0, 0), 0);
    int st = 0;
    LT_EQ(wait_pid(c, &st, 0), c);
    LT_EQ(st, 9);
}

/* ---- the attach stop belongs to its trace link (the 2026-11-23 VRChat hang) ------------------------------
 * A guest process with two threads: A is the target of PTRACE_ATTACH and is held between system calls so
 * that its attach SIGSTOP stays pending while the test arranges the order; B only beats. Heartbeats and
 * the hold live in shared memory. */
#include <sys/mman.h>

struct two {
    volatile int64_t beat_a, beat_b;
    volatile int hold_a, quit, skip_sync, fail_local, killed;
    volatile int32_t tid_a, tid_b, pid, host;
};
static struct two *g_two;

static void two_loop(lkd_task *t, volatile int64_t *beat, int held)
{
    int died = 0;
    while (!g_two->quit && !died) {
        while (held && g_two->hold_a && !g_two->quit) usleep(200);
        (void)gsys(t, LKD_NR_getpid, 0, 0, 0, 0, 0, 0, &died);
        __atomic_add_fetch(beat, 1, __ATOMIC_RELAXED);
        usleep(200);
    }
    if (died) g_two->killed = 1;              /* the fixture's own exit is 0 whatever killed it: say so */
}

static void *two_b_main(void *a)
{
    lkd_task *t = a;
    lkd_set_current(t);
    two_loop(t, &g_two->beat_b, 0);
    return NULL;
}

static void two_child(lkd_task *a)
{
    alarm(60);
    cpu_init(a);
    pt_test_hold_wake_sync = g_two->skip_sync;
    pt_test_fail_local = g_two->fail_local;     /* b's first pt_local allocations fail (b has none yet) */
    const uint64_t thr = LX_CLONE_VM | LX_CLONE_FS | LX_CLONE_FILES | LX_CLONE_SIGHAND | LX_CLONE_THREAD;
    lkd_task *b = lkd_task_alloc(a, thr);
    lkd_task_publish(b);
    cpu_init(b);
    pthread_t th;
    if (pthread_create(&th, NULL, two_b_main, b)) _exit(91);
    g_two->tid_a = a->tid;
    g_two->tid_b = b->tid;
    g_two->pid = a->proc->pid;
    g_two->host = (int32_t)getpid();
    two_loop(a, &g_two->beat_a, 1);
    _exit(0);
}

static int64_t two_start(int skip_sync)
{
    g_two = mmap(NULL, sizeof *g_two, PROT_READ | PROT_WRITE, MAP_SHARED | MAP_ANON, -1, 0);
    if (g_two == MAP_FAILED) return -1;
    memset((void *)g_two, 0, sizeof *g_two);
    g_two->skip_sync = skip_sync;
    fflush(NULL);
    int64_t pid = sct(TR, LKD_NR_fork, 0, 0, 0, 0, 0, 0);
    if (pid == 0) { two_child(lkd_current()); _exit(92); }
    for (int i = 0; i < 4000 && (g_two->beat_a < 20 || g_two->beat_b < 20); i++) usleep(1000);
    return pid;
}

static void two_end(int64_t pid)
{
    g_two->quit = 1;
    g_two->hold_a = 0;
    usleep(20000);
    if (g_two->host > 0) kill((pid_t)g_two->host, SIGKILL);
    int st;
    (void)wait_pid((int32_t)pid, &st, LX_WALL);
    munmap((void *)g_two, sizeof *g_two);
}

/* How far a heartbeat moves in ms milliseconds. */
static int64_t beats_in(volatile int64_t *beat, int ms)
{
    int64_t b0 = *beat;
    usleep((useconds_t)ms * 1000);
    return *beat - b0;
}

/* A stop reported for tid within ms (wait4 __WALL polled, like wine's 3 s watchdog), its status in *st. */
static int64_t two_wait(int32_t tid, int *st, int ms)
{
    int64_t deadline = mono_ns() + (int64_t)ms * 1000000;
    for (;;) {
        int64_t r = wait_pid(tid, st, LX_WALL | LX_WNOHANG);
        if (r != 0 || mono_ns() > deadline) return r;
        usleep(200);
    }
}

/* The tracee takes the attach SIGSTOP before its flags say it is traced (the wake's sync is withheld): the
 * stop must still be the tracer's, for the target's tid alone; the sibling beats on; DETACH(0) resumes. */
LT_TEST(attach_stop_before_the_flag_update)
{
    int64_t pid = two_start(1);
    LT_CHECK(pid > 0 && g_two->beat_a >= 20);
    int32_t a = g_two->tid_a;
    g_two->hold_a = 1;
    usleep(5000);
    LT_EQ(PT(LX_PTRACE_ATTACH, a, 0, 0), 0);
    g_two->hold_a = 0;                                 /* A reaches its safe point with stale flags */
    int st = 0;
    LT_EQ(two_wait(a, &st, 3000), a);
    LT_EQ(st, 0x137f);
    LT_CHECK(beats_in(&g_two->beat_b, 200) > 0);       /* only A is stopped */
    int64_t a0 = g_two->beat_a;
    usleep(100000);
    LT_EQ(g_two->beat_a, a0);
    LT_EQ(PT(LX_PTRACE_DETACH, a, 0, 0), 0);
    LT_CHECK(beats_in(&g_two->beat_a, 300) > 0);
    LT_CHECK(beats_in(&g_two->beat_b, 100) > 0);
    two_end(pid);
}

/* The tracer exits after queuing the attach SIGSTOP and before the tracee takes it: the link is freed with
 * the tracer, and its stop with it. The process must not stop. */
LT_TEST(tracer_exits_before_the_attach_stop)
{
    int64_t pid = two_start(0);
    LT_CHECK(pid > 0 && g_two->beat_a >= 20);
    int32_t a = g_two->tid_a;
    g_two->hold_a = 1;
    usleep(5000);
    int rp[2];
    LT_EQ(pipe(rp), 0);
    fflush(NULL);
    int64_t x = sct(TR, LKD_NR_fork, 0, 0, 0, 0, 0, 0);
    if (x == 0) {
        lkd_task *t = lkd_current();
        alarm(30);
        int64_t r = sct(t, LKD_NR_ptrace, LX_PTRACE_ATTACH, (uint64_t)a, 0, 0, 0, 0);
        put64(rp[1], r);
        int sx;
        (void)sct(t, LKD_NR_exit_group, 0, 0, 0, 0, 0, 0);
        if (lkd_task_release(t, &sx)) _exit(sx);
        _exit(90);
    }
    LT_CHECK(x > 0);
    LT_EQ(get64(rp[0]), 0);
    int sx;
    LT_EQ(wait_pid((int32_t)x, &sx, 0), x);              /* the tracer is gone, its links freed */
    LT_EQ(lkd_ptrace_tracer_of(a), 0);
    g_two->hold_a = 0;
    LT_CHECK(beats_in(&g_two->beat_a, 400) > 0);
    LT_CHECK(beats_in(&g_two->beat_b, 200) > 0);
    close(rp[0]); close(rp[1]);
    two_end(pid);
}

/* Control: an ordinary SIGSTOP from another process still stops every thread, until SIGCONT. */
LT_TEST(an_ordinary_stop_still_stops_the_process)
{
    int64_t pid = two_start(0);
    LT_CHECK(pid > 0 && g_two->beat_a >= 20);
    LT_EQ(sct(TR, LKD_NR_kill, (uint64_t)pid, LX_SIGSTOP, 0, 0, 0, 0), 0);
    usleep(100000);
    LT_EQ(beats_in(&g_two->beat_a, 300), 0);
    LT_EQ(beats_in(&g_two->beat_b, 1), 0);
    LT_EQ(sct(TR, LKD_NR_kill, (uint64_t)pid, LX_SIGCONT, 0, 0, 0, 0), 0);
    LT_CHECK(beats_in(&g_two->beat_a, 300) > 0);
    LT_CHECK(beats_in(&g_two->beat_b, 100) > 0);
    two_end(pid);
}


/* ---- the attach stop is the link's, never a queued signal (fourth verification, findings 1, 5, 6) ------ */

/* A forked guest process that attaches to `tid` (ATTACH, or SEIZE with `opts`), reports the result, then
 * either exits at once (mode 0), or waits for the attach stop, reports it, sets `opts` with SETOPTIONS and
 * sleeps until its host process is killed (mode 1). hook: pt_test_exit_after_link in that process. */
static int64_t tracer_fork(int32_t tid, int mode, uint32_t opts, int hook, int rp[2])
{
    if (pipe(rp) != 0) return -1;
    fflush(NULL);
    int64_t x = sct(TR, LKD_NR_fork, 0, 0, 0, 0, 0, 0);
    if (x == 0) {
        lkd_task *t = lkd_current();
        alarm(30);
        pt_test_exit_after_link = hook;
        int64_t r = sct(t, LKD_NR_ptrace, LX_PTRACE_ATTACH, (uint64_t)tid, 0, 0, 0, 0);
        put64(rp[1], r);
        if (mode == 1 && r == 0) {
            int st = 0;
            int64_t w = -1;
            for (int i = 0; i < 6000 && w <= 0; i++) {
                w = sct(t, LKD_NR_wait4, (uint64_t)tid, P(&st), LX_WALL | LX_WNOHANG, 0, 0, 0);
                if (w <= 0) usleep(500);
            }
            put64(rp[1], w == tid ? st : -1);
            put64(rp[1], sct(t, LKD_NR_ptrace, LX_PTRACE_SETOPTIONS, (uint64_t)tid, 0, opts, 0, 0));
            put64(rp[1], (int64_t)getpid());
            sleep(25);
            _exit(0);
        }
        int sx;
        (void)sct(t, LKD_NR_exit_group, 0, 0, 0, 0, 0, 0);
        if (lkd_task_release(t, &sx)) _exit(sx);
        _exit(90);
    }
    return x;
}

/* Verifier's cross1: tracer A attaches and exits while the target is held, tracer B attaches before the
 * release. Before: both attaches succeeded, the queue coalesced B's SIGSTOP with A's, the target discarded
 * A's obsolete generation and B waited for ever while the target ran. Now B's link has its own stop. */
LT_TEST(a_second_tracer_gets_its_own_attach_stop)
{
    int64_t pid = two_start(0);
    LT_CHECK(pid > 0 && g_two->beat_a >= 20);
    int32_t a = g_two->tid_a;
    g_two->hold_a = 1;
    usleep(5000);
    int rp[2];
    int64_t x = tracer_fork(a, 0, 0, 0, rp);
    LT_CHECK(x > 0);
    LT_EQ(get64(rp[0]), 0);
    int sx;
    LT_EQ(wait_pid((int32_t)x, &sx, 0), x);
    LT_EQ(lkd_ptrace_tracer_of(a), 0);
    LT_EQ(PT(LX_PTRACE_ATTACH, a, 0, 0), 0);
    g_two->hold_a = 0;
    int st = 0;
    LT_EQ(two_wait(a, &st, 3000), a);
    LT_EQ(st, 0x137f);
    LT_CHECK(beats_in(&g_two->beat_b, 200) > 0);       /* only A is stopped */
    int64_t a0 = g_two->beat_a;
    usleep(100000);
    LT_EQ(g_two->beat_a, a0);
    LT_EQ(PT(LX_PTRACE_DETACH, a, 0, 0), 0);
    LT_CHECK(beats_in(&g_two->beat_a, 300) > 0);
    close(rp[0]); close(rp[1]);
    two_end(pid);
}

/* Verifier's cross2: an ordinary thread-directed SIGSTOP sent after a departed tracer's attach must stop the
 * process as job control says (it used to be coalesced with the obsolete attach stop and dropped: the
 * sibling ran 700 heartbeats in 200 ms). */
LT_TEST(an_ordinary_stop_after_a_departed_attach_still_stops)
{
    int64_t pid = two_start(0);
    LT_CHECK(pid > 0 && g_two->beat_a >= 20);
    int32_t a = g_two->tid_a;
    g_two->hold_a = 1;
    usleep(5000);
    int rp[2];
    int64_t x = tracer_fork(a, 0, 0, 0, rp);
    LT_CHECK(x > 0);
    LT_EQ(get64(rp[0]), 0);
    int sx;
    LT_EQ(wait_pid((int32_t)x, &sx, 0), x);
    LT_EQ(sct(TR, LKD_NR_tgkill, (uint64_t)pid, (uint64_t)a, LX_SIGSTOP, 0, 0, 0), 0);
    g_two->hold_a = 0;
    usleep(100000);
    LT_EQ(beats_in(&g_two->beat_b, 200), 0);
    LT_EQ(beats_in(&g_two->beat_a, 1), 0);
    LT_EQ(sct(TR, LKD_NR_kill, (uint64_t)pid, LX_SIGCONT, 0, 0, 0, 0), 0);
    LT_CHECK(beats_in(&g_two->beat_a, 300) > 0);
    LT_CHECK(beats_in(&g_two->beat_b, 200) > 0);
    close(rp[0]); close(rp[1]);
    two_end(pid);
}

/* Verifier's cont: a SIGCONT (to a sibling) flushes pending stop signals; it must not flush a live attach's
 * stop. Both with the flag sync withheld (the stop is taken before the cache says traced) and without. */
static void sigcont_case(int skip_sync)
{
    int64_t pid = two_start(skip_sync);
    LT_CHECK(pid > 0 && g_two->beat_a >= 20);
    int32_t a = g_two->tid_a;
    g_two->hold_a = 1;
    usleep(5000);
    LT_EQ(PT(LX_PTRACE_ATTACH, a, 0, 0), 0);
    LT_EQ(sct(TR, LKD_NR_tgkill, (uint64_t)pid, (uint64_t)g_two->tid_b, LX_SIGCONT, 0, 0, 0), 0);
    LT_EQ(sct(TR, LKD_NR_kill, (uint64_t)pid, LX_SIGCONT, 0, 0, 0, 0), 0);
    g_two->hold_a = 0;
    int st = 0;
    LT_EQ(two_wait(a, &st, 3000), a);
    LT_EQ(st, 0x137f);
    int64_t a0 = g_two->beat_a;
    LT_CHECK(beats_in(&g_two->beat_b, 200) > 0);
    LT_EQ(g_two->beat_a, a0);
    LT_EQ(PT(LX_PTRACE_DETACH, a, 0, 0), 0);
    LT_CHECK(beats_in(&g_two->beat_a, 300) > 0);
    two_end(pid);
}
LT_TEST(sigcont_does_not_flush_an_attach_stop) { sigcont_case(0); sigcont_case(1); }

/* The tracer's host process dies between linking and waking its tracee (no exit path runs): the target
 * goes on running, and the next ATTACH is not refused for ever with EPERM: it reclaims the dead link and
 * gets its own stop. */
LT_TEST(tracer_killed_between_link_and_wake)
{
    int64_t pid = two_start(0);
    LT_CHECK(pid > 0 && g_two->beat_a >= 20);
    int32_t a = g_two->tid_a;
    int rp[2];
    int64_t x = tracer_fork(a, 0, 0, 1, rp);
    LT_CHECK(x > 0);
    int sx;
    LT_EQ(wait_pid((int32_t)x, &sx, 0), x);           /* _exit(77) right after pt_link: nothing was sent */
    LT_CHECK(beats_in(&g_two->beat_a, 300) > 0);       /* the target was not stopped by a lost stop */
    LT_CHECK(beats_in(&g_two->beat_b, 100) > 0);
    LT_EQ(PT(LX_PTRACE_ATTACH, a, 0, 0), 0);           /* not EPERM: the dead tracer's link was reclaimed */
    int st = 0;
    LT_EQ(two_wait(a, &st, 3000), a);
    LT_EQ(st, 0x137f);
    LT_CHECK(beats_in(&g_two->beat_b, 200) > 0);
    LT_EQ(PT(LX_PTRACE_DETACH, a, 0, 0), 0);
    LT_CHECK(beats_in(&g_two->beat_a, 300) > 0);
    close(rp[0]); close(rp[1]);
    two_end(pid);
}

/* The wake of an ATTACH cannot be delivered: the attach fails (ESRCH) and its link is undone by generation,
 * so no stop is left behind for a tracer that was told it has none; a later ATTACH works. */
LT_TEST(an_undelivered_attach_is_undone)
{
    int64_t pid = two_start(0);
    LT_CHECK(pid > 0 && g_two->beat_a >= 20);
    int32_t a = g_two->tid_a;
    pt_test_fail_wake = 1;
    LT_ERRNO(PT(LX_PTRACE_ATTACH, a, 0, 0), LX_ESRCH);
    LT_EQ(pt_test_fail_wake, 0);
    LT_EQ(lkd_ptrace_tracer_of(a), 0);
    LT_CHECK(beats_in(&g_two->beat_a, 300) > 0);
    LT_EQ(PT(LX_PTRACE_ATTACH, a, 0, 0), 0);
    int st = 0;
    LT_EQ(two_wait(a, &st, 3000), a);
    LT_EQ(st, 0x137f);
    LT_EQ(PT(LX_PTRACE_DETACH, a, 0, 0), 0);
    LT_CHECK(beats_in(&g_two->beat_a, 300) > 0);
    two_end(pid);
}

/* The tracee cannot allocate its ptrace state when it reaches the attach stop (injected: its first three
 * pt_local allocations fail): the stop is not consumed as "link gone", it is retried and reported. */
LT_TEST(attach_stop_survives_an_allocation_failure)
{
    int64_t pid;
    {
        /* two_start with b's allocations failing */
        g_two = mmap(NULL, sizeof *g_two, PROT_READ | PROT_WRITE, MAP_SHARED | MAP_ANON, -1, 0);
        LT_CHECK(g_two != MAP_FAILED);
        memset((void *)g_two, 0, sizeof *g_two);
        g_two->fail_local = 3;
        fflush(NULL);
        pid = sct(TR, LKD_NR_fork, 0, 0, 0, 0, 0, 0);
        if (pid == 0) { two_child(lkd_current()); _exit(92); }
        for (int i = 0; i < 4000 && (g_two->beat_a < 20 || g_two->beat_b < 20); i++) usleep(1000);
    }
    LT_CHECK(pid > 0 && g_two->beat_b >= 20);
    int32_t b = g_two->tid_b;
    LT_EQ(PT(LX_PTRACE_ATTACH, b, 0, 0), 0);
    int st = 0;
    LT_EQ(two_wait(b, &st, 3000), b);
    LT_EQ(st, 0x137f);
    LT_CHECK(beats_in(&g_two->beat_a, 200) > 0);       /* the process was not stopped */
    LT_EQ(PT(LX_PTRACE_DETACH, b, 0, 0), 0);
    LT_CHECK(beats_in(&g_two->beat_b, 300) > 0);
    two_end(pid);
}

/* EXITKILL while parked: the tracer's host process is killed while its tracee sits in the attach stop. The
 * parked tracee detaches itself and, because of EXITKILL, dies (it used to take the detach exit first and
 * run on). The control without EXITKILL runs on. */
static void exitkill_case(uint32_t opts)
{
    int64_t pid = two_start(0);
    LT_CHECK(pid > 0 && g_two->beat_a >= 20);
    int32_t a = g_two->tid_a;
    int rp[2];
    int64_t x = tracer_fork(a, 1, opts, 0, rp);
    LT_CHECK(x > 0);
    LT_EQ(get64(rp[0]), 0);
    LT_EQ(get64(rp[0]), 0x137f);
    LT_EQ(get64(rp[0]), 0);                             /* SETOPTIONS */
    int64_t host = get64(rp[0]);
    LT_CHECK(host > 0);
    LT_EQ(kill((pid_t)host, SIGKILL), 0);
    int sx;
    (void)wait_pid((int32_t)x, &sx, 0);
    if (opts & LX_PTRACE_O_EXITKILL) {
        int st = 0;
        int64_t t0 = mono_ns();
        LT_EQ(wait_pid((int32_t)pid, &st, 0), pid);     /* the tracee's process ended ... */
        LT_EQ(g_two->killed, 1);                       /* ... killed (SIGKILL), not run on */
        LT_CHECK(mono_ns() - t0 < 5000000000ll);
        g_two->host = 0;
        munmap((void *)g_two, sizeof *g_two);
    } else {
        int64_t t0 = mono_ns();
        while (mono_ns() - t0 < 5000000000ll && beats_in(&g_two->beat_a, 100) == 0) { }
        LT_CHECK(beats_in(&g_two->beat_a, 300) > 0);
        LT_EQ(g_two->killed, 0);
        two_end(pid);
    }
    close(rp[0]); close(rp[1]);
}
LT_TEST(exitkill_while_parked_kills) { exitkill_case(LX_PTRACE_O_EXITKILL); exitkill_case(0); }

/* A tracer attaching to a process already in a group stop gets the attach stop reported (it used to wait
 * until SIGCONT); SIGCONT afterwards resumes the rest. */
LT_TEST(attach_to_a_group_stopped_process)
{
    int64_t pid = two_start(0);
    LT_CHECK(pid > 0 && g_two->beat_a >= 20);
    int32_t a = g_two->tid_a;
    LT_EQ(sct(TR, LKD_NR_kill, (uint64_t)pid, LX_SIGSTOP, 0, 0, 0, 0), 0);
    usleep(100000);
    LT_EQ(beats_in(&g_two->beat_b, 200), 0);
    LT_EQ(PT(LX_PTRACE_ATTACH, a, 0, 0), 0);
    int st = 0;
    LT_EQ(two_wait(a, &st, 3000), a);
    LT_EQ(st, 0x137f);
    LT_EQ(PT(LX_PTRACE_DETACH, a, 0, 0), 0);
    LT_EQ(sct(TR, LKD_NR_kill, (uint64_t)pid, LX_SIGCONT, 0, 0, 0, 0), 0);
    LT_CHECK(beats_in(&g_two->beat_a, 300) > 0);
    LT_CHECK(beats_in(&g_two->beat_b, 200) > 0);
    two_end(pid);
}

/* The recent-event ring keeps every attach and group stop (the capped logs could hide the one that matters):
 * 9000 events, the ring keeps the newest LKD_EVENT_RING_LINES, each a full line. */
LT_TEST(event_ring_keeps_the_recent_events)
{
    size_t lines = 0;
    const char *m = lkd_event_ring(&lines);
    LT_CHECK(m != NULL);
    LT_EQ(lines, LKD_EVENT_RING_LINES);
    for (int i = 0; i < 9000; i++) lkd_event("test event %d", i);
    int found_last = 0, found_old = 0;
    for (size_t k = 1; k <= lines; k++) {
        const char *l = m + k * LKD_EVENT_LINE;
        LT_EQ(l[LKD_EVENT_LINE - 1], '\n');
        if (strstr(l, "test event 8999 ") && memchr(l, '\n', LKD_EVENT_LINE) == l + LKD_EVENT_LINE - 1) found_last = 1;
        if (strstr(l, "test event 0 ")) found_old = 1;
    }
    LT_EQ(found_last, 1);
    LT_EQ(found_old, 0);
    LT_EQ(memcmp(m + 8, "lkd event ring v1", 17), 0);
}

int main(int argc, char **argv)
{
    if (argc > 1) g_filter = argv[1];
    test_setup(1);
    RUN(table_capacity);
    RUN(lock_is_released_when_the_holder_dies);
    RUN(table_is_shared_between_processes);
    RUN(wake_crosses_processes);
    RUN(round_trip_thread_tracee);
    RUN(round_trip_process_tracee);
    RUN(attach_stop_before_the_flag_update);
    RUN(tracer_exits_before_the_attach_stop);
    RUN(an_ordinary_stop_still_stops_the_process);
    RUN(a_second_tracer_gets_its_own_attach_stop);
    RUN(an_ordinary_stop_after_a_departed_attach_still_stops);
    RUN(sigcont_does_not_flush_an_attach_stop);
    RUN(tracer_killed_between_link_and_wake);
    RUN(an_undelivered_attach_is_undone);
    RUN(attach_stop_survives_an_allocation_failure);
    RUN(exitkill_while_parked_kills);
    RUN(attach_to_a_group_stopped_process);
    RUN(event_ring_keeps_the_recent_events);
    return lt_finish();
}
