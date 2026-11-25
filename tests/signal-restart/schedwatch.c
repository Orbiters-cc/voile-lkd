/* Says how every thread of a fexdarwin-run is scheduled for as long as it runs, and every call that would change it. Not part of the engine:
 * a library that is inserted into it (sched.py), of one that is released as of one that is not.
 * Into <SCHEDWATCH_DIR>/<pid>.txt, a line each:
 *   T <thread> <name>|<how it is scheduled>      when it is first seen and whenever that changes
 *   P <thread> <current priority> <base>         its highest current priority so far, when that is over the base one
 *   CALL <function> <thread> by <thread>         a call that sets a priority, a policy or a QoS, in any process of the family
 *   S <samples>
 * The priority that the scheduler computes of a thread's use (it decays below the base one) is not part of it. */
#include <fcntl.h>
#include <mach/mach.h>
#include <mach/thread_policy.h>
#include <pthread.h>
#include <pthread/qos.h>
#include <sched.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <unistd.h>

static int log_fd = -1;
static void out(const char *f, ...) {
    char b[1024]; va_list a; va_start(a, f); int n = vsnprintf(b, sizeof b, f, a); va_end(a);
    if (n > (int)sizeof b - 1) n = sizeof b - 1;
    if (log_fd >= 0 && n > 0) (void)!write(log_fd, b, (size_t)n);
}
static uint64_t id_of(thread_t t) {
    thread_identifier_info_data_t i; mach_msg_type_number_t n = THREAD_IDENTIFIER_INFO_COUNT;
    return thread_info(t, THREAD_IDENTIFIER_INFO, (thread_info_t)&i, &n) == KERN_SUCCESS ? i.thread_id : 0;
}
static uint64_t self_id(void) { uint64_t i = 0; pthread_threadid_np(NULL, &i); return i; }
#define CALLED(name, thread) out("CALL %s %llu by %llu\n", name, (unsigned long long)(thread), (unsigned long long)self_id())
static __thread int own; /* the watch thread's own calls */

static kern_return_t w_thread_policy_set(thread_act_t t, thread_policy_flavor_t f, thread_policy_t p, mach_msg_type_number_t n) { if (!own) CALLED("thread_policy_set", id_of(t)); return thread_policy_set(t, f, p, n); }
static kern_return_t w_thread_policy(thread_act_t t, policy_t p, policy_base_t b, mach_msg_type_number_t n, boolean_t l) { CALLED("thread_policy", id_of(t)); return thread_policy(t, p, b, n, l); }
static kern_return_t w_thread_set_policy(thread_act_t t, processor_set_t s, policy_t p, policy_base_t b, mach_msg_type_number_t n, policy_limit_t l, mach_msg_type_number_t m) { CALLED("thread_set_policy", id_of(t)); return thread_set_policy(t, s, p, b, n, l, m); }
static kern_return_t w_task_policy_set(task_policy_set_t t, task_policy_flavor_t f, task_policy_t p, mach_msg_type_number_t n) { CALLED("task_policy_set", 0); return task_policy_set(t, f, p, n); }
static int w_pthread_setschedparam(pthread_t t, int p, const struct sched_param *s) { CALLED("pthread_setschedparam", id_of(pthread_mach_thread_np(t))); return pthread_setschedparam(t, p, s); }
static int w_pthread_set_qos(qos_class_t q, int r) { CALLED("pthread_set_qos_class_self_np", self_id()); return pthread_set_qos_class_self_np(q, r); }
static pthread_override_t w_override(pthread_t t, qos_class_t q, int r) { CALLED("pthread_override_qos_class_start_np", id_of(pthread_mach_thread_np(t))); return pthread_override_qos_class_start_np(t, q, r); }
static int w_attr_qos(pthread_attr_t *a, qos_class_t q, int r) { CALLED("pthread_attr_set_qos_class_np", 0); return pthread_attr_set_qos_class_np(a, q, r); }
static int w_attr_param(pthread_attr_t *a, const struct sched_param *s) { CALLED("pthread_attr_setschedparam", 0); return pthread_attr_setschedparam(a, s); }
static int w_attr_policy(pthread_attr_t *a, int p) { CALLED("pthread_attr_setschedpolicy", 0); return pthread_attr_setschedpolicy(a, p); }
static int w_setpriority(int w, id_t i, int p) { CALLED("setpriority", 0); return setpriority(w, i, p); }
static int w_nice(int n) { CALLED("nice", 0); return nice(n); }
#define I(mine, theirs) __attribute__((used, section("__DATA,__interpose"))) static const struct { const void *a, *b; } i_##theirs = { (const void *)mine, (const void *)theirs }
I(w_thread_policy_set, thread_policy_set); I(w_thread_policy, thread_policy); I(w_thread_set_policy, thread_set_policy); I(w_task_policy_set, task_policy_set);
I(w_pthread_setschedparam, pthread_setschedparam); I(w_pthread_set_qos, pthread_set_qos_class_self_np); I(w_override, pthread_override_qos_class_start_np);
I(w_attr_qos, pthread_attr_set_qos_class_np); I(w_attr_param, pthread_attr_setschedparam); I(w_attr_policy, pthread_attr_setschedpolicy);
I(w_setpriority, setpriority); I(w_nice, nice);

/* Every flavor of policy that may be read, with the priorities; "" when the thread is gone. And the POSIX policy and the QoS class as libpthread
 * has them; "" when it does not know the thread yet, or no more (it is ending). */
static void describe(thread_t t, char *b, size_t size, char posix[100], int *cur, int *base, char name[64]) {
    b[0] = posix[0] = 0; *cur = *base = 0;
    thread_extended_info_data_t e; mach_msg_type_number_t n = THREAD_EXTENDED_INFO_COUNT;
    if (thread_info(t, THREAD_EXTENDED_INFO, (thread_info_t)&e, &n) != KERN_SUCCESS) return;
    thread_basic_info_data_t bi; n = THREAD_BASIC_INFO_COUNT;
    if (thread_info(t, THREAD_BASIC_INFO, (thread_info_t)&bi, &n) != KERN_SUCCESS) return;
    *cur = e.pth_curpri; *base = e.pth_priority; memcpy(name, e.pth_name, 63); name[63] = 0;
    size_t k = (size_t)snprintf(b, size, "policy %d/%d base %d max %d", e.pth_policy, bi.policy, e.pth_priority, e.pth_maxpriority);
    static const struct { int f; const char *n; unsigned c; } F[] = { {THREAD_EXTENDED_POLICY, "timeshare", 1}, {THREAD_TIME_CONSTRAINT_POLICY, "realtime", 4}, {THREAD_PRECEDENCE_POLICY, "importance", 1},
        {THREAD_AFFINITY_POLICY, "affinity", 1}, {THREAD_BACKGROUND_POLICY, "background", 1}, {THREAD_LATENCY_QOS_POLICY, "latency", 1}, {THREAD_THROUGHPUT_QOS_POLICY, "throughput", 1}, {9, "qos", 2} };
    for (size_t i = 0; i < sizeof F / sizeof *F && k < size; i++) {
        integer_t d[16] = {0}; mach_msg_type_number_t c = F[i].c; boolean_t def = 0;
        kern_return_t r = thread_policy_get(t, (thread_policy_flavor_t)F[i].f, d, &c, &def);
        /* Of a thread that is ending nothing can be read any more; of one that lives everything but the background policy. */
        if (r == MACH_SEND_INVALID_DEST || r == KERN_TERMINATED || (r == KERN_INVALID_ARGUMENT && F[i].f != THREAD_BACKGROUND_POLICY)) { b[0] = 0; return; }
        k += (size_t)snprintf(b + k, size - k, " %s", F[i].n);
        if (r) k += (size_t)snprintf(b + k, size - k, " (%d)", r); else { if (def) k += (size_t)snprintf(b + k, size - k, " default"); for (unsigned j = 0; j < c && k < size; j++) k += (size_t)snprintf(b + k, size - k, " %d", d[j]); }
    }
    pthread_t p = pthread_from_mach_thread_np(t); struct sched_param sp = {0}; int pol = -1, rel = 0; qos_class_t q = 0;
    if (p && !pthread_getschedparam(p, &pol, &sp) && !pthread_get_qos_class_np(p, &q, &rel)) snprintf(posix, 100, " posix %d %d class %#x %d", pol, sp.sched_priority, q, rel);
}
#define MAXT 512
static struct { uint64_t id; char was[600], posix[100]; int top; } S[MAXT]; static int ns;
static void *watch(void *arg) {
    (void)arg; own = 1; pthread_setname_np("sched-watch"); const uint64_t me = self_id(); unsigned long samples = 0;
    for (;;) {
        thread_act_array_t L; mach_msg_type_number_t n;
        if (task_threads(mach_task_self(), &L, &n) == KERN_SUCCESS) {
            for (mach_msg_type_number_t i = 0; i < n; i++) {
                uint64_t id = id_of(L[i]); char b[500], posix[100], name[64]; int cur, base;
                if (id && id != me) {
                    describe(L[i], b, sizeof b, posix, &cur, &base, name);
                    int s = 0; while (s < ns && S[s].id != id) s++;
                    if (b[0] && s < MAXT && (posix[0] || s < ns)) {
                        if (s == ns) { ns++; S[s].id = id; S[s].was[0] = 0; S[s].top = 0; }
                        if (posix[0]) snprintf(S[s].posix, sizeof S[s].posix, "%s", posix);
                        char full[700]; snprintf(full, sizeof full, "%s|%s%s", name, b, S[s].posix);
                        if (strncmp(full, S[s].was, sizeof S[s].was - 1)) { snprintf(S[s].was, sizeof S[s].was, "%s", full); out("T %llu %s\n", (unsigned long long)id, full); }
                        if (cur > base && cur > S[s].top) { S[s].top = cur; out("P %llu %d %d\n", (unsigned long long)id, cur, base); }
                    }
                }
                mach_port_deallocate(mach_task_self(), L[i]);
            }
            vm_deallocate(mach_task_self(), (vm_address_t)L, n * sizeof *L);
        }
        if (++samples % 200 == 0) out("S %lu\n", samples);
        usleep(200);
    }
    return NULL;
}
static void begin(void) {
    const char *d = getenv("SCHEDWATCH_DIR"); if (!d) return;
    char p[1024]; snprintf(p, sizeof p, "%s/%d.txt", d, getpid());
    if (log_fd >= 0) close(log_fd);
    int fd = open(p, O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0644);
    log_fd = fcntl(fd, F_DUPFD_CLOEXEC, 220); /* out of the way of the guest's, under the usual limit */
    close(fd);
    ns = 0; pthread_t t; if (pthread_create(&t, NULL, watch, NULL) == 0) pthread_detach(t);
}
__attribute__((constructor)) static void start(void) { pthread_atfork(NULL, NULL, begin); begin(); }
