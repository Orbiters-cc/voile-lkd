/*
 * otl_test.c - the timeline recorder (wsd/otl.h) by itself. Build and run: run-otl-test.sh.
 * Off (no OBELISK_TIMELINE): no thread, no file, no memory. On: whole records of every thread, in order, none lost while
 * the writer keeps up; a burst longer than a ring loses records and says how many and when; a thread that ends gives its
 * ring back; a first record allocates nothing; an exit writes the last records and the end; a session's recorders share
 * one budget, stop for good at it, and say so; a write that fails, or falls short, ends the recorder with whole records.
 */
#ifdef TEST_FREE
#define OTL_FREE TEST_FREE
#endif
#define OTL_IMPLEMENTATION
#include "../../wsd/otl.h"
#include <dirent.h>
#include <mach/mach.h>
#include <malloc/malloc.h>
#include <signal.h>
#include <sys/resource.h>
#include <sys/wait.h>

static int fails;
#define CHECK(c, ...) do { if (!(c)) { printf("FAIL " __VA_ARGS__); printf("\n"); fails++; } } while (0)

static int threads(void) {
  thread_act_array_t l;
  mach_msg_type_number_t n = 0;
  task_threads(mach_task_self(), &l, &n);
  vm_deallocate(mach_task_self(), (vm_address_t)l, n * sizeof(*l));
  return (int)n;
}
static int files(const char *dir) {
  int n = 0;
  DIR *d = opendir(dir);
  for (struct dirent *e; d && (e = readdir(d));) n += e->d_name[0] != '.';
  if (d) closedir(d);
  return n;
}
static int descriptors(void) { return proc_pidinfo(getpid(), PROC_PIDLISTFDS, 0, NULL, 0) / (int)sizeof(struct proc_fdinfo); }

static void *burst(void *p) {
  for (uint64_t i = 0; i < (uint64_t)(uintptr_t)p; i++) otl_put(otl_now(), OTL_W_RX, 7, i, 0, 0, 0, 0, 0);
  return NULL;
}
static void *paced(void *p) {
  for (uint64_t i = 0; i < 20000; i++) {
    otl_put(otl_now(), OTL_W_TICK, (uint32_t)(uintptr_t)p, i, 0, 0, 0, 0, 0);
    if (i % 1000 == 999) usleep(30000);
  }
  return NULL;
}
static void *first(void *p) {
  struct mstats before, after;
  (void)pthread_getspecific(otl_key);
  before = mstats();
  otl_put(otl_now(), OTL_W_RX, 7, 1, 0, 0, 0, 0, 0);
  after = mstats();
  *(long *)p = (long)(after.bytes_used - before.bytes_used);
  return NULL;
}

int main(int argc, char **argv) {
  const char *dir = argv[1], *mode = argc > 2 ? argv[2] : "";
  if (!strcmp(mode, "off")) {
    int t = threads(), f = descriptors();
    otl_init("test");
    otl_put(otl_now(), OTL_W_RX, 0, 0, 0, 0, 0, 0, 0);
    otl_hist(OTL_H_A, 1000);
    usleep(100000);
    CHECK(!otl_on, "on without the variable");
    CHECK(threads() == t, "a thread more");
    CHECK(descriptors() == f, "a descriptor more");
    CHECK(files(dir) == 0, "a file");
    for (int i = 0; i < OTL_THREADS; i++) CHECK(!otl_rings[i].records, "a ring's memory");
    return fails != 0;
  }
  if (!strcmp(mode, "refused")) { /* one recorder more than a session takes, or no room left: none, and no file */
    int f = descriptors();
    otl_init("test");
    CHECK(!otl_on, "on though refused");
    CHECK(descriptors() == f, "a descriptor more");
    char path[1024];
    snprintf(path, sizeof(path), "%s/otl-test-%d.bin", dir, getpid());
    CHECK(access(path, F_OK), "a file");
    return fails != 0;
  }
  if (!strcmp(mode, "short")) { /* a write that takes part of a record, then none */
    struct rlimit l = {1000 * 1000 + 33, RLIM_INFINITY};
    signal(SIGXFSZ, SIG_IGN);
    setrlimit(RLIMIT_FSIZE, &l);
  }
  otl_init("test");
  CHECK(otl_on, "off with the variable");
  if (!strcmp(mode, "paced")) {
    pthread_t t[4];
    for (uintptr_t i = 0; i < 4; i++) pthread_create(&t[i], NULL, paced, (void *)i);
    for (int i = 0; i < 4; i++) pthread_join(t[i], NULL);
    for (uintptr_t i = 4; i < 4 + 3 * OTL_THREADS; i++) { /* one after another: their rings come back */
      pthread_t one;
      pthread_create(&one, NULL, burst, (void *)(uintptr_t)10);
      pthread_join(one, NULL);
      if (i % 32 == 0) usleep(120000);
    }
    CHECK(otl_unslotted == 0, "%llu records without a ring", (unsigned long long)otl_unslotted);
  } else if (!strcmp(mode, "burst")) {
    pthread_t t;
    pthread_create(&t, NULL, burst, (void *)(uintptr_t)400000);
    pthread_join(t, NULL);
  } else if (!strcmp(mode, "first")) {
    long bytes = 0;
    pthread_t t;
    pthread_create(&t, NULL, first, &bytes);
    pthread_join(t, NULL);
    CHECK(bytes == 0, "a first record took %ld bytes", bytes);
  } else if (!strcmp(mode, "exit")) { /* the last records of an orderly exit are there, with the end */
    burst((void *)(uintptr_t)1000);
    exit(0);
  } else if (!strcmp(mode, "fill") || !strcmp(mode, "short")) { /* until the recorder ends: the budget, or a write that fails */
    for (int i = 0; i < 2000 && otl_active(); i++) {
      burst((void *)(uintptr_t)4000);
      usleep(10000);
    }
    CHECK(!otl_active(), "still recording");
    int f = descriptors();
    usleep(200000);
    CHECK(descriptors() <= f, "its descriptors are still open");
    CHECK(threads() == 1, "its writer still runs");
    char path[1024];
    struct stat a, b;
    snprintf(path, sizeof(path), "%s/otl-test-%d.bin", dir, getpid());
    stat(path, &a);
    burst((void *)(uintptr_t)4000);
    sleep(11); /* past a summary's turn */
    stat(path, &b);
    CHECK(a.st_size == b.st_size, "it wrote on");
  } else if (!strcmp(mode, "identity")) {
    char name[64];
    snprintf(name, sizeof(name), "/otl-test-%d", getpid());
    int fd = shm_open(name, O_CREAT | O_EXCL | O_RDWR, 0600);
    shm_unlink(name);
    ftruncate(fd, 65536);
    uint64_t a = otl_identity(fd, 0);
    void *p = mmap(NULL, 65536, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    CHECK(a && otl_identity(fd, 0) == a && p != MAP_FAILED, "a mapping changed it");
    CHECK(otl_identity(fd, 16384) != a, "another offset has it too");
    int other = shm_open("/otl-test-other", O_CREAT | O_RDWR, 0600);
    shm_unlink("/otl-test-other");
    CHECK(otl_identity(other, 0) != a, "another object has it too");
    pid_t pid = fork();
    if (!pid) _exit(otl_identity(dup(fd), 0) == a ? 0 : 1);
    int status = 0;
    waitpid(pid, &status, 0);
    CHECK(status == 0, "another process sees another identity");
  }
  usleep(300000);
  printf("%s %s\n", mode, fails ? "FAIL" : "ok");
  return fails != 0;
}
