/* test_ptrace_reattach.c: wineserver's debug-register sequence, repeated at speed, against a tracee in
 * another host process. Owner: ptrace.
 *
 * voile-wine's server reads and writes a thread's debug registers through ptrace (server/ptrace.c
 * suspend_for_ptrace, get_thread_context, set_thread_context): PTRACE_ATTACH, waitpid(tid, WUNTRACED |
 * __WALL) for the attach's SIGSTOP, PEEKUSER/POKEUSER of DR0..DR7, PTRACE_DETACH(0). Once a thread's debug
 * registers were set, every GetThreadContext of that thread by another one does it again, so a garbage
 * collector that suspends and inspects every thread runs this back to back, the next ATTACH arriving
 * while the tracee is still leaving the previous stop.
 *
 * In Linux the SIGSTOP an ATTACH queues is always seen by a traced task (ptrace_attach links before it
 * sends; get_signal checks current->ptrace). If the tracee takes it as untraced, its default action
 * stops the whole process (a group stop): the tracer's waitpid never sees an attach stop, its DETACH fails
 * (ESRCH, the task is not in a ptrace stop), and the process stays stopped for good, every thread parked.
 * That is what a VRChat start on 2026-11-23 showed (all guest threads in the untraced group-stop loop of
 * park()). This test fails when any round's stop is not reported to the tracer in 3 s (wine's watchdog),
 * or when the tracee stops making progress after the last DETACH.
 *
 * The tracee is the grandchild of the tracer's process, like a game is not wineserver's child: an
 * untraced group stop is then reported to nobody. */
#include "test_ptrace_util.h"
#include <sys/mman.h>

#define DR7_OFF (848ull + 7 * 8) /* offsetof(struct user, u_debugreg[7]) on x86-64 */

struct shared {
    volatile int64_t progress;   /* loops the tracee made */
    volatile int quit;
    volatile int32_t tid;
    volatile int32_t host;
};
static struct shared *g_sh;

static void spinner_body(lkd_task *t)
{
    int died = 0;
    cpu_init(t);
    int64_t r = gsys(t, LKD_NR_fork, 0, 0, 0, 0, 0, 0, &died);
    if (r == 0) {
        alarm(90);
        g_sh->host = (int32_t)getpid();
        g_sh->tid = t->tid;
        /* A busy guest thread: one syscall, then the engine's safe point, in a loop. */
        while (!g_sh->quit && !died) {
            (void)gsys(t, LKD_NR_getpid, 0, 0, 0, 0, 0, 0, &died);
            __atomic_add_fetch(&g_sh->progress, 1, __ATOMIC_RELAXED);
            if ((g_sh->progress & 63) == 0) usleep(20);
        }
        _exit(0);
    }
    while (!g_sh->quit) usleep(10000);
    _exit(0);
}

/* waitpid with wine's 3 s watchdog: the pid and status, or 0 when nothing was reported in time. */
static int64_t wait_stop(int32_t tid, int *st, int ms)
{
    int64_t deadline = mono_ns() + (int64_t)ms * 1000000;
    for (;;) {
        int64_t r = wait_pid(tid, st, LX_WUNTRACED | LX_WALL | LX_WNOHANG);
        if (r != 0) return r;
        if (mono_ns() > deadline) return 0;
        usleep(50);
    }
}

LT_TEST(attach_detach_at_speed_never_stops_the_process)
{
    g_sh = mmap(NULL, sizeof *g_sh, PROT_READ | PROT_WRITE, MAP_SHARED | MAP_ANON, -1, 0);
    LT_CHECK(g_sh != MAP_FAILED);
    memset((void *)g_sh, 0, sizeof *g_sh);
    fflush(NULL);
    int64_t pid = sct(TR, LKD_NR_fork, 0, 0, 0, 0, 0, 0);
    if (pid == 0) { alarm(90); spinner_body(lkd_current()); _exit(93); }
    LT_CHECK(pid > 0);
    for (int i = 0; i < 4000 && g_sh->progress < 100; i++) usleep(1000);
    int32_t tid = g_sh->tid;
    LT_CHECK(tid > 0 && g_sh->progress >= 100);

    const char *env = getenv("LKD_REATTACH_ROUNDS");
    int rounds = env ? atoi(env) : 60000;
    int64_t budget_ns = (int64_t)(env ? 600 : 40) * 1000000000ll;
    int64_t t0 = mono_ns();
    int done = 0, lost = -1, odd = 0;
    int64_t worst_ns = 0;
    for (int k = 0; k < rounds && mono_ns() - t0 < budget_ns; k++) {
        int64_t a = mono_ns();
        if (PT(LX_PTRACE_ATTACH, tid, 0, 0) != 0) { odd++; break; }
        int st = 0;
        int64_t r = wait_stop(tid, &st, 3000);
        if (r != tid) {
            /* wine: the watchdog aborts the wait, resume_after_ptrace detaches (and fails) */
            lost = k;
            (void)PT(LX_PTRACE_DETACH, tid, 0, 0);
            break;
        }
        if (st != 0x137f) odd++;
        uint64_t dr7 = 1;
        if (PT(LX_PTRACE_PEEKUSER, tid, DR7_OFF, P(&dr7)) != 0) odd++;
        if (PT(LX_PTRACE_DETACH, tid, 0, 0) != 0) odd++;
        int64_t d = mono_ns() - a;
        if (d > worst_ns) worst_ns = d;
        done++;
    }
    /* After the last DETACH the tracee runs on. */
    int64_t before = g_sh->progress;
    usleep(300000);
    int64_t after = g_sh->progress;
    fprintf(stderr, "reattach: %d rounds in %lld ms, worst %lld us, lost at round %d, odd results %d, "
            "progress after the last detach %lld\n", done, (long long)((mono_ns() - t0) / 1000000),
            (long long)(worst_ns / 1000), lost, odd, (long long)(after - before));
    LT_EQ(lost, -1);
    LT_EQ(odd, 0);
    LT_CHECK(after > before);
    g_sh->quit = 1;
    if (lost >= 0 && g_sh->host > 0) kill((pid_t)g_sh->host, SIGKILL); /* a stopped process never quits */
    int st2;
    wait_pid((int32_t)pid, &st2, 0);
    munmap((void *)g_sh, sizeof *g_sh);
}

int main(int argc, char **argv)
{
    if (argc > 1) g_filter = argv[1];
    test_setup(1);
    alarm(0);
    alarm(700);
    RUN(attach_detach_at_speed_never_stops_the_process);
    return lt_finish();
}
