/*
 * guest_probe.c - in the place of the engine (engine/fexdarwin-run): writes down everything the launcher gave the process that
 * becomes the game, then ends. run-guest-probe.sh compares it between the released generation and the timeline's.
 */
#include <errno.h>
#include <fcntl.h>
#include <libproc.h>
#include <mach/mach.h>
#include <mach/thread_policy.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/sysctl.h>
#include <sys/un.h>
#include <sys/socket.h>
#include <unistd.h>
extern char **environ;

int main(int argc, char **argv) {
  const char *root = getenv("FEXDARWIN_ROOT");
  char out[1024];
  snprintf(out, sizeof(out), "%s/../probe.txt", root ? root : ".");
  FILE *f = fopen(out, "w");
  if (!f) return 1;
  fcntl(fileno(f), F_SETFD, FD_CLOEXEC);
  for (int i = 0; i < argc; i++) fprintf(f, "arg %d %s\n", i, argv[i]);
  for (char **e = environ; *e; e++) fprintf(f, "env %s\n", *e);
  for (int fd = 0; fd < 256; fd++) {
    if (fd == fileno(f)) continue;
    int flags = fcntl(fd, F_GETFD), status = fcntl(fd, F_GETFL);
    if (flags < 0) continue;
    struct stat st;
    char path[1024] = "";
    fcntl(fd, F_GETPATH, path);
    fstat(fd, &st);
    fprintf(f, "fd %d type %o mode %o fdflags %d flflags 0x%x %s\n", fd, st.st_mode & S_IFMT, st.st_mode & 07777, flags, status, path);
  }
  sigset_t mask;
  sigprocmask(SIG_BLOCK, NULL, &mask);
  for (int s = 1; s < NSIG; s++) {
    struct sigaction a;
    if (sigaction(s, NULL, &a)) continue;
    fprintf(f, "signal %d %s blocked %d flags %d\n", s, a.sa_handler == SIG_DFL ? "default" : a.sa_handler == SIG_IGN ? "ignored" : "handler",
            sigismember(&mask, s), a.sa_flags);
  }
  fprintf(f, "group own %d parent's %d session parent's %d\n", getpgrp() == getpid(), getpgrp() == getpgid(getppid()), getsid(0) == getsid(getppid()));
  char name[256] = "";
  proc_name(getppid(), name, sizeof(name));
  fprintf(f, "parent %s is the supervisor %d\n", name, getenv("FEXDARWIN_SUPERVISOR_PID") && atoi(getenv("FEXDARWIN_SUPERVISOR_PID")) == getppid());
  for (int r = 0; r < RLIM_NLIMITS; r++) {
    struct rlimit l;
    if (!getrlimit(r, &l)) fprintf(f, "limit %d %llu %llu\n", r, (unsigned long long)l.rlim_cur, (unsigned long long)l.rlim_max);
  }
  mode_t m = umask(0);
  umask(m);
  char cwd[1024];
  fprintf(f, "umask %o cwd %s nice %d tty %s\n", m, getcwd(cwd, sizeof(cwd)) ? cwd : "?", getpriority(PRIO_PROCESS, 0), ttyname(0) ? ttyname(0) : "none");
  int role = 0;
  struct task_category_policy category;
  mach_msg_type_number_t n = TASK_CATEGORY_POLICY_COUNT;
  boolean_t dflt = FALSE;
  if (!task_policy_get(mach_task_self(), TASK_CATEGORY_POLICY, (task_policy_t)&category, &n, &dflt)) role = category.role;
  fprintf(f, "task role %d qos %d\n", role, (int)qos_class_self());
  exception_mask_t masks[EXC_TYPES_COUNT];
  mach_msg_type_number_t count = EXC_TYPES_COUNT;
  mach_port_t ports[EXC_TYPES_COUNT];
  exception_behavior_t behaviours[EXC_TYPES_COUNT];
  thread_state_flavor_t flavours[EXC_TYPES_COUNT];
  if (!task_get_exception_ports(mach_task_self(), EXC_MASK_ALL, masks, &count, ports, behaviours, flavours))
    for (unsigned i = 0; i < count; i++) fprintf(f, "exception 0x%x port %d behaviour 0x%x\n", masks[i], ports[i] != 0, behaviours[i]);
  struct kinfo_proc kp;
  size_t size = sizeof(kp);
  int mib[4] = {CTL_KERN, KERN_PROC, KERN_PROC_PID, getpid()};
  if (!sysctl(mib, 4, &kp, &size, NULL, 0)) fprintf(f, "traced %d flags 0x%x\n", (kp.kp_proc.p_flag & P_TRACED) != 0, kp.kp_proc.p_flag & ~0x4);
  uint32_t cs = 0;
  extern int csops(pid_t, unsigned, void *, size_t);
  if (!csops(getpid(), 0, &cs, sizeof(cs))) fprintf(f, "codesign 0x%x\n", cs);
  fclose(f);
  return 0;
}
