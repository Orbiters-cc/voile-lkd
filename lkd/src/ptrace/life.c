/* life.c: links between tracer and tracee, wait4 reports, death of either side, access rules and the
 * module hooks. Owner: ptrace.
 *
 * Models kernel/ptrace.c (ptrace_link, __ptrace_detach, exit_ptrace, __ptrace_may_access) and
 * kernel/exit.c (wait_task_stopped with ptrace=1, wait_task_zombie) of Linux v6.12.
 * imported from HL proc_ptrace.c: proc_trace_wait() (stop sequence versus consumed sequence, WNOWAIT keeps
 * the event) and proc_trace_tracer_exit()/detach_link() (tracer death detaches and resumes with the signal
 * suppressed).
 */
#include <unistd.h>

#include "pt_priv.h"
#include "sig.h"

#define CAP_SYS_PTRACE 19

int pt_wait_status(const struct pt_slot *s) { return (s->code << 8) | 0x7f; }

int pt_resolve_tid(int32_t tid, int32_t *tgid, int32_t *host, uint32_t *uid, char *state)
{
    lkd_tid_info ti;
    if (tid <= 0 || lkd_tid_lookup(tid, &ti) < 0) return -LX_ESRCH;
    lkd_proc_info *pi = malloc(sizeof *pi);
    if (!pi) return -LX_ENOMEM;
    int r = lkd_proc_lookup(ti.tgid, pi);
    if (r == 0) {
        if (tgid) *tgid = ti.tgid;
        if (host) *host = pi->host_pid;
        if (uid) *uid = pi->uid;
        if (state) *state = ti.state;
    }
    free(pi);
    return r < 0 ? -LX_ESRCH : 0;
}

int pt_link_locked(int32_t tid, int32_t tgid, int32_t tracee_host, uint32_t uid, int32_t tracer_pid,
                   int32_t tracer_tid, int32_t tracer_host, uint32_t options, int seized, int with_stop,
                   int astop_code)
{
    if (pt_find_tracee(tid) >= 0) return -LX_EPERM;
    int i = pt_alloc_locked();
    if (i < 0) return -LX_EAGAIN;
    struct pt_slot *s = pt_slot_at(i);
    s->tgid = tgid;
    s->tracee_host = tracee_host;
    s->tracer_host = tracer_host;
    s->uid = uid;
    s->options = options;
    s->seized = (uint32_t)seized;
    s->astop = with_stop != 0;      /* reserved with the link: nothing can fail between the two */
    s->astop_code = astop_code;
    atomic_store(&s->tracer_pid, tracer_pid);
    atomic_store(&s->tracer_tid, tracer_tid);
    atomic_store(&s->tid, tid);
    return i;
}

int pt_link(int32_t tid, int32_t tgid, int32_t tracee_host, uint32_t uid, int32_t tracer_pid,
            int32_t tracer_tid, int32_t tracer_host, uint32_t options, int seized)
{
    pt_lock();
    int i = pt_link_locked(tid, tgid, tracee_host, uid, tracer_pid, tracer_tid, tracer_host, options, seized, 0, 0);
    pt_unlock();
    return i;
}

void pt_cancel_link_locked(int i, int *kill, int32_t *tgid, int32_t *tid)
{
    struct pt_slot *s = pt_slot_at(i);
    *tgid = s->tgid;
    *tid = atomic_load(&s->tid);
    *kill = (s->options & LX_PTRACE_O_EXITKILL) != 0;
    s->resume_sig = 0; /* a tracer that disappears resumes its tracee with the signal suppressed */
    s->mode = PM_CONT;
    s->step = 0;
    s->trap = 0;
    s->astop = 0;      /* the attach stop goes with its link */
    s->regs_dirty = s->fx_dirty = s->xs_dirty = s->si_dirty = s->mask_dirty = 0;
    if (s->stopped) {
        s->stopped = 0;
        atomic_store(&s->link, PL_DETACHED); /* the parked tracee frees the slot */
    } else {
        pt_free_locked(i);
    }
}

int pt_exec_rename_locked(int32_t old, int32_t now, int32_t tgid, int32_t ended[4])
{
    int n = 0;
    int mine = -1;
    for (int i = 0; i < PT_SLOTS; i++) {
        struct pt_slot *s = pt_slot_at(i);
        if (atomic_load(&s->link) == PL_ATTACHED && atomic_load(&s->tid) == old && s->tgid == tgid) mine = i;
    }
    for (int i = 0; i < PT_SLOTS; i++) {
        struct pt_slot *s = pt_slot_at(i);
        uint32_t l = atomic_load(&s->link);
        if (l != PL_ATTACHED && l != PL_EXITED) continue;
        if (old != now && mine >= 0 && i != mine && l == PL_ATTACHED && atomic_load(&s->tid) == now &&
            s->tgid == tgid) {
            /* Made by an ATTACH to the leader's tid in the window where the leader had died and this thread
             * had not yet been renamed. In Linux that attach finds the leader's exit_state and fails; here it
             * has returned 0 already, so its tracer sees what happened to the thread it attached: it died. */
            if (n < 4) ended[n] = atomic_load(&s->tracer_pid);
            n++;
            s->stopped = 0;
            s->astop = 0;
            s->trap = 0;
            s->exit_status = LX_SIGKILL;
            atomic_store(&s->link, PL_EXITED);
            continue;
        }
        /* only links of this thread group: tid_seen may still be the parent's tid in a fork child (the
         * ptrace fork hook runs before task switches the identity), and the parent's tid must not be
         * mistaken for an old tid of this process (the EAC exec probes: the tracer lost its tracee) */
        if (atomic_load(&s->tid) == old && l == PL_ATTACHED && s->tgid == tgid) atomic_store(&s->tid, now);
        if (atomic_load(&s->tracer_tid) == old && atomic_load(&s->tracer_pid) == tgid)
            atomic_store(&s->tracer_tid, now);
    }
    return n;
}

/* ---- wait4 / waitid -------------------------------------------------------------------------------- */

int lkd_ptrace_has_tracees(lkd_task *waiter)
{
    if (!pt_table_ready()) return 0;
    int32_t me = waiter->proc->pid;
    for (int i = 0; i < PT_SLOTS; i++) {
        struct pt_slot *s = pt_slot_at(i);
        uint32_t l = atomic_load(&s->link);
        if ((l == PL_ATTACHED || l == PL_EXITED) && atomic_load(&s->tracer_pid) == me) return 1;
    }
    return 0;
}

/* Does the waiter's process trace something that the wait selector could name? (do_wait() says ECHILD
 * when no child, traced or not, satisfies the selector.) */
int lkd_ptrace_wait_has(lkd_task *waiter, int32_t sel_pid, unsigned options)
{
    if (!pt_table_ready()) return 0;
    int32_t me = waiter->proc->pid;
    int32_t pgrp_want = 0;
    if (sel_pid == 0) { lkd_proc_refresh_ids(waiter->proc); pgrp_want = waiter->proc->pgid; }
    else if (sel_pid < -1) pgrp_want = -sel_pid;
    int found = 0;
    for (int i = 0; i < PT_SLOTS && !found; i++) {
        struct pt_slot *s = pt_slot_at(i);
        uint32_t l = atomic_load(&s->link);
        if ((l != PL_ATTACHED && l != PL_EXITED) || atomic_load(&s->tracer_pid) != me) continue;
        if ((options & LX_WNOTHREAD) && atomic_load(&s->tracer_tid) != waiter->tid) continue;
        int32_t tid = atomic_load(&s->tid);
        if (sel_pid > 0 && tid != sel_pid) continue;
        if (sel_pid <= 0 && sel_pid != -1) {
            lkd_proc_info *pi = malloc(sizeof *pi);
            int ok = pi && lkd_proc_lookup(s->tgid, pi) == 0 && pi->pgid == pgrp_want;
            free(pi);
            if (!ok) continue;
        }
        if (!(options & LX_WALL) && ((tid != s->tgid) != !!(options & LX_WCLONE))) continue;
        found = 1;
    }
    return found;
}

static int cld_of_status(int st)
{
    if (LX_WIFEXITED(st)) return LX_CLD_EXITED;
    return (st & 0x80) ? LX_CLD_DUMPED : LX_CLD_KILLED;
}

/* A tracee whose host process vanished without running its exit path (killed from outside, engine crash)
 * would keep its tracer waiting for ever. Its end is reported as death by SIGKILL, the only thing known;
 * the task module does the same for host children. */
static void reap_dead_tracees(lkd_task *waiter)
{
    int32_t me = waiter->proc->pid;
    int idx[PT_SLOTS], n = 0;
    for (int i = 0; i < PT_SLOTS; i++) {
        struct pt_slot *s = pt_slot_at(i);
        int32_t h = s->tracee_host;
        if (atomic_load(&s->link) != PL_ATTACHED || atomic_load(&s->tracer_pid) != me) continue;
        if (h > 0 && h != getpid() && !pt_host_alive(h)) idx[n++] = i;
    }
    for (int k = 0; k < n; k++) {
        struct pt_slot *s = pt_slot_at(idx[k]);
        int32_t tgid = s->tgid, tid = atomic_load(&s->tid);
        lkd_proc_info *pi = malloc(sizeof *pi);
        int32_t ppid = pi && lkd_proc_lookup(tgid, pi) == 0 ? pi->ppid : -1;
        free(pi);
        pt_lock();
        if (atomic_load(&s->link) == PL_ATTACHED && atomic_load(&s->tid) == tid) {
            s->stopped = 0;
            if (ppid == me && tid == tgid) {
                pt_free_locked(idx[k]); /* the task module reports the death of its own child */
            } else {
                s->exit_status = LX_SIGKILL;
                atomic_store(&s->link, PL_EXITED);
            }
        }
        pt_unlock();
    }
}

int lkd_ptrace_wait_event(lkd_task *waiter, int32_t sel_pid, unsigned options, struct lkd_wait_event *ev)
{
    if (!pt_table_ready()) return 0;
    reap_dead_tracees(waiter);
    int32_t me = waiter->proc->pid;
    int32_t pgrp_want = 0;
    int32_t pgids[PT_SLOTS];
    int use_pg = sel_pid <= 0 && sel_pid != -1;
    if (sel_pid == 0) { lkd_proc_refresh_ids(waiter->proc); pgrp_want = waiter->proc->pgid; }
    else if (sel_pid < -1) pgrp_want = -sel_pid;
    if (use_pg) {
        /* the process group is in the registry: look it up before taking the ptrace lock */
        for (int i = 0; i < PT_SLOTS; i++) {
            struct pt_slot *s = pt_slot_at(i);
            pgids[i] = -1;
            uint32_t l = atomic_load(&s->link);
            if ((l != PL_ATTACHED && l != PL_EXITED) || atomic_load(&s->tracer_pid) != me) continue;
            lkd_proc_info *pi = malloc(sizeof *pi);
            if (pi && lkd_proc_lookup(s->tgid, pi) == 0) pgids[i] = pi->pgid;
            free(pi);
        }
    }
    int found = 0;
    int32_t notify_tracer_pid = 0;
    pt_lock();
    for (int i = 0; i < PT_SLOTS && !found; i++) {
        struct pt_slot *s = pt_slot_at(i);
        uint32_t l = atomic_load(&s->link);
        if ((l != PL_ATTACHED && l != PL_EXITED) || atomic_load(&s->tracer_pid) != me) continue;
        if ((options & LX_WNOTHREAD) && atomic_load(&s->tracer_tid) != waiter->tid) continue;
        int32_t tid = atomic_load(&s->tid);
        if (sel_pid > 0 && tid != sel_pid) continue;
        if (use_pg && pgids[i] != pgrp_want) continue;
        /* A traced thread that is not a thread-group leader is a "clone" child: it needs __WALL or
         * __WCLONE, like eligible_child() (kernel/exit.c) says. */
        if (!(options & LX_WALL)) {
            int clone_child = tid != s->tgid;
            if (clone_child != !!(options & LX_WCLONE)) continue;
        }
        memset(ev, 0, sizeof *ev);
        ev->pid = tid;
        ev->uid = s->uid;
        if (l == PL_ATTACHED) {
            /* wait_task_stopped(ptrace = 1): a ptrace stop is reported whatever WUNTRACED says */
            if (!s->stopped || s->reported) continue;
            ev->status = pt_wait_status(s);
            ev->code = LX_CLD_TRAPPED; /* wait_task_stopped(): why = ptrace ? CLD_TRAPPED : CLD_STOPPED */
            if (!(options & LX_WNOWAIT)) s->reported = 1;
            found = 1;
        } else {
            if (!(options & LX_WEXITED)) continue;
            ev->status = s->exit_status;
            ev->code = cld_of_status(s->exit_status);
            if (!(options & LX_WNOWAIT)) pt_free_locked(i);
            found = 1;
        }
    }
    pt_unlock();
    (void)notify_tracer_pid;
    return found;
}

int lkd_ptrace_attach_stop_pending(lkd_task *t)
{
    if (!pt_table_ready()) return 0;
    pt_lock();
    int i = pt_find_tracee(t->tid);
    int r = i >= 0 && pt_slot_at(i)->astop;
    pt_unlock();
    return r;
}

int32_t lkd_ptrace_tracer_of(int32_t tid)
{
    int i = pt_table_ready() ? pt_find_tracee(tid) : -1;
    return i < 0 ? 0 : atomic_load(&pt_slot_at(i)->tracer_tid);
}

/* ---- access rules ---------------------------------------------------------------------------------- */

/* __ptrace_may_access(): the caller's real ids must equal every id of the target, or the caller has
 * CAP_SYS_PTRACE; then a target that is not dumpable needs the capability too. The modeled kernel has no
 * Yama LSM: kernel.yama.ptrace_scope does not exist, so the classic rules above are the only ones (the
 * task module answers EINVAL to PR_SET_PTRACER for the same reason). The registry does not keep the saved
 * ids of a target: euid and egid stand for them. */
int lkd_ptrace_check_access(lkd_task *caller, int32_t pid, unsigned mode)
{
    (void)mode;
    if (!caller || !caller->proc) return -LX_EPERM;
    int32_t tgid = pid;
    lkd_proc_info *pi = malloc(sizeof *pi);
    if (!pi) return -LX_ENOMEM;
    int r = lkd_proc_lookup(pid, pi);
    if (r < 0) {
        lkd_tid_info ti;
        if (lkd_tid_lookup(pid, &ti) < 0 || lkd_proc_lookup(ti.tgid, pi) < 0) { free(pi); return -LX_ESRCH; }
        tgid = ti.tgid;
    }
    if (tgid == caller->proc->pid) { free(pi); return 0; } /* same_thread_group() */
    const struct lkd_creds *c = &caller->proc->cred;
    int cap = (c->cap_eff >> CAP_SYS_PTRACE) & 1;
    int ok = (c->uid == pi->euid && c->uid == pi->uid && c->gid == pi->egid && c->gid == pi->gid);
    int dumpable = pi->dumpable == 1;
    free(pi);
    if (!ok && !cap) return -LX_EPERM;
    if (!dumpable && !cap) return -LX_EPERM;
    return 0;
}

/* ---- death of a tracer ------------------------------------------------------------------------------ */

void pt_tracer_gone(lkd_task *t, int whole_process)
{
    if (!pt_table_ready()) return;
    struct { int32_t tgid, tid; int kill; } act[PT_SLOTS];
    int n = 0;
    int32_t me_pid = t->proc->pid, me_tid = t->tid;
    pt_lock();
    for (int i = 0; i < PT_SLOTS; i++) {
        struct pt_slot *s = pt_slot_at(i);
        uint32_t l = atomic_load(&s->link);
        if (l != PL_ATTACHED && l != PL_EXITED) continue;
        if (whole_process ? atomic_load(&s->tracer_pid) != me_pid : atomic_load(&s->tracer_tid) != me_tid) continue;
        if (l == PL_EXITED) { pt_free_locked(i); continue; }
        /* exit_ptrace(): __ptrace_unlink() each tracee; EXITKILL ones are killed */
        pt_cancel_link_locked(i, &act[n].kill, &act[n].tgid, &act[n].tid);
        n++;
    }
    pt_unlock();
    for (int k = 0; k < n; k++) {
        lkd_event("ptrace: tracer %d (pid %d) gone: link of tid %d cancelled%s", (int)me_tid, (int)me_pid,
                  (int)act[k].tid, act[k].kill ? ", EXITKILL" : "");
        if (act[k].kill) {
            struct lx_siginfo si;
            memset(&si, 0, sizeof si);
            si.si_signo = LX_SIGKILL;
            si.si_code = LX_SI_KERNEL;
            (void)lkd_sig_send_pid(NULL, act[k].tgid, LX_SIGKILL, &si);
        }
        (void)pt_wake_tracee(act[k].tgid, act[k].tid, PT_WAKE_SYNC, -1, 0);
    }
    if (!whole_process) {
        uint32_t f = atomic_load(&t->ptrace.flags);
        if (f & LKD_PT_TRACER) atomic_fetch_and(&t->ptrace.flags, ~LKD_PT_TRACER);
    }
}

/* ---- module hooks ----------------------------------------------------------------------------------- */

void lkd_ptrace_init(void)
{
    pt_transport_init();
    pt_request_register();
}

void lkd_ptrace_fork_prepare(lkd_task *t, uint64_t clone_flags) { (void)t; (void)clone_flags; pt_transport_fork_prepare(); }
void lkd_ptrace_fork_parent(lkd_task *t, pid_t host_child) { (void)t; (void)host_child; pt_transport_fork_parent(); }

/* In the child, before the task module switches the identity (core/hooks.c: reverse order): t is still the
 * parent thread. Capture who traces the parent, for the auto-attach decision of lkd_ptrace_task_init(), and
 * remember which thread created this process: it is the tracer of a later PTRACE_TRACEME. */
void lkd_ptrace_fork_child(lkd_task *t)
{
    pt_transport_fork_child();
    struct pt_local *L = pt_local_of(t, 1);
    if (!L) return;
    int i = pt_my_slot(t);
    memset(&L->inherit, 0, sizeof L->inherit);
    if (i >= 0) {
        /* traced at fork: lkd_ptrace_task_init reads the parent's link again, under the lock, when it makes
         * the child's (the tracer may have left in between) */
        L->inherit.valid = 1;
        L->inherit.slot = i;
        L->inherit.gen = L->gen;
        L->inherit.parent_tid = t->tid;
    }
    L->slot = -1;
    L->emu = 0;
    L->step_on = 0;
    L->exited = 0;
    L->creator_tid = t->tid;
    L->creator_pid = t->proc->pid;
    const uint32_t mine = LKD_PT_TRACED | LKD_PT_SYSCALL_TRACE | LKD_PT_SEIZED | LKD_PT_SINGLESTEP |
                          LKD_PT_STOPPED | LKD_PT_TRACER;
    atomic_fetch_and(&t->ptrace.flags, ~mine);
    t->ptrace.tracer_tid = 0;
}

static int event_of_clone(uint64_t flags)
{
    if (flags & LX_CLONE_VFORK) return LX_PTRACE_EVENT_VFORK;
    if ((flags & 0xff) != LX_SIGCHLD) return LX_PTRACE_EVENT_CLONE;
    return LX_PTRACE_EVENT_FORK;
}

/* kernel_clone() / ptrace_init_task(): the child is traced by its parent's tracer when the parent is traced
 * and either CLONE_PTRACE is given or the matching PTRACE_O_TRACE* option is on (CLONE_UNTRACED turns the
 * option off). A non-seized child starts with a pending SIGSTOP, a seized one with a trap. */
void lkd_ptrace_task_init(lkd_task *child, lkd_task *parent, uint64_t clone_flags)
{
    struct pt_local *LC = pt_local_of(child, 1);
    if (!LC) return;
    int32_t ptid, ptgid;
    int was_traced;
    if (child == parent) {
        /* host fork child: the parent thread is in the other process now */
        was_traced = LC->inherit.valid;
        ptid = LC->inherit.parent_tid;
        ptgid = LC->creator_pid;
        LC->inherit.valid = 0;
    } else {
        LC->creator_tid = parent->tid;
        LC->creator_pid = parent->proc->pid;
        ptid = parent->tid;
        ptgid = parent->proc->pid;
        was_traced = pt_table_ready() && pt_find_tracee(ptid) >= 0;
    }
    if (!was_traced || !pt_table_ready()) return;
    int ev = event_of_clone(clone_flags);
    int i = -1, seized = 0;
    int32_t tracer_tid = 0;
    uint64_t gen = 0;
    /* The parent's link is read and the child's made in one critical section: a tracer that detaches or
     * dies meanwhile is either before (no child link) or after (it cancels the child's link with its own). */
    pt_lock();
    int pi = pt_find_tracee(ptid);
    if (pi >= 0 && pt_slot_at(pi)->tgid == ptgid) {
        struct pt_slot *ps = pt_slot_at(pi);
        uint32_t opts = ps->options;
        int traced_event = !(clone_flags & LX_CLONE_UNTRACED) && (opts & (1u << ev));
        if ((clone_flags & LX_CLONE_PTRACE) || traced_event) {
            seized = (int)ps->seized;
            tracer_tid = atomic_load(&ps->tracer_tid);
            i = pt_link_locked(child->tid, child->proc->pid, getpid(), child->proc->cred.uid,
                               atomic_load(&ps->tracer_pid), tracer_tid, ps->tracer_host, opts, seized,
                               !seized, LX_SI_USER);
            if (i >= 0) {
                if (seized) pt_slot_at(i)->trap = 1;
                gen = pt_gen(pt_slot_at(i));
            }
        }
    }
    pt_unlock();
    if (i < 0) return;
    LC->slot = -1;
    lkd_event("ptrace: tid %d auto-attached to tracer %d (link %d gen %llu%s)", (int)child->tid, (int)tracer_tid, i,
              (unsigned long long)gen, seized ? ", seized" : "");
    atomic_fetch_or(&child->flags, LKD_TF_TRACE_STOP);
    pt_sync_flags(child);
}

void lkd_ptrace_exec_commit(lkd_task *t)
{
    /* A non-leader thread that execs takes the leader's tid (de_thread()): follow it in the table. */
    struct pt_local *L = pt_local_of(t, 0);
    if (!L || L->tid_seen == t->tid || !pt_table_ready()) return;
    int32_t old = L->tid_seen;
    int32_t ended[4];
    pt_lock();
    int n = pt_exec_rename_locked(old, t->tid, t->proc->pid, ended);
    pt_unlock();
    for (int k = 0; k < n && k < 4; k++) {
        lkd_event("ptrace: exec of tid %d -> %d ended a link made to %d meanwhile (tracer pid %d)", (int)old,
                  (int)t->tid, (int)t->tid, (int)ended[k]);
        pt_notify_tracer(ended[k], t->tid, t->proc->cred.uid, LX_CLD_KILLED, LX_SIGKILL);
    }
    L->tid_seen = t->tid;
    L->slot = -1;
    pt_sync_flags(t);
}

/* A tracee thread leaves: PTRACE_EVENT_EXIT stop first (do_exit(): ptrace_event(PTRACE_EVENT_EXIT, code)),
 * then the death is published to the tracer. A tracer thread leaves: its tracees are detached. */
void lkd_ptrace_task_exit(lkd_task *t)
{
    struct pt_local *L = pt_local_of(t, 0);
    if (L && L->exited) return;
    int i = pt_table_ready() ? pt_find_tracee(t->tid) : -1;
    if (L) L->exited = 1;
    if (i >= 0) {
        struct lkd_proc *p = t->proc;
        int status = p->exiting ? (int)p->exit_code : t->exit_code;
        int64_t nr = atomic_load(&t->cur_nr);
        int voluntary = nr == LKD_NR_exit || nr == LKD_NR_exit_group;
        int signalled = (status & 0x7f) && (status & 0x7f) != LX_SIGKILL;
        uint32_t opts = pt_slot_at(i)->options;
        if ((opts & LX_PTRACE_O_TRACEEXIT) && (voluntary || signalled)) {
            struct pt_stop_req q;
            memset(&q, 0, sizeof q);
            q.kind = PK_EVENT;
            q.code = (LX_PTRACE_EVENT_EXIT << 8) | LX_SIGTRAP;
            q.msg = (uint64_t)(uint32_t)status;
            q.nr = -1;
            q.ignore_fatal = 1;
            struct pt_resume rs;
            (void)pt_do_stop(t, &q, &rs);
        }
        lkd_proc_refresh_ids(p);
        int32_t ppid = p->ppid;
        int32_t tracer_pid = 0, tgid = p->pid;
        uint32_t uid = p->cred.uid;
        int report = 0;
        pt_lock();
        struct pt_slot *s = pt_slot_at(i);
        if (atomic_load(&s->link) == PL_ATTACHED && atomic_load(&s->tid) == t->tid) {
            tracer_pid = atomic_load(&s->tracer_pid);
            s->stopped = 0;
            /* The real parent learns of the death from the task module; a tracer that is not the parent
             * (or that traces a non-leader thread) is told here and collects the status with wait4. */
            report = tracer_pid != ppid || t->tid != tgid;
            if (report) {
                s->exit_status = status;
                s->uid = uid;
                atomic_store(&s->link, PL_EXITED);
            } else {
                pt_free_locked(i);
            }
        }
        pt_unlock();
        if (tracer_pid) {
            if (report) pt_notify_tracer(tracer_pid, t->tid, uid, cld_of_status(status), LX_WIFEXITED(status) ? LX_WEXITSTATUS(status) : LX_WTERMSIG(status));
        }
        atomic_fetch_and(&t->ptrace.flags, ~(LKD_PT_TRACED | LKD_PT_SYSCALL_TRACE | LKD_PT_STOPPED));
    }
    pt_tracer_gone(t, 0);
}

void lkd_ptrace_task_dead(lkd_task *t) { lkd_ptrace_task_exit(t); }

void lkd_ptrace_proc_exit(lkd_task *t)
{
    if (!pt_table_ready()) return;
    /* the last thread left: whatever is still linked to this process as tracer goes */
    pt_tracer_gone(t, 1);
}
