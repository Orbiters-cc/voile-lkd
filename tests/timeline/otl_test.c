/*
 * otl_test.c - the timeline recorder (wsd/otl.h) by itself. Build and run: run-otl-test.sh.
 * Off (no OBELISK_TIMELINE): no thread, no file, no memory. On: whole records of every thread, in order, none lost while
 * the writer keeps up; a burst longer than a ring loses records and says how many; the file stops at its cap and the
 * summaries go on; a thread that ends gives its ring back; the identity of shared memory is the same in another process.
 */
#define OTL_IMPLEMENTATION
#include "../../wsd/otl.h"
#include <dirent.h>
#include <mach/mach.h>
#include <sys/mman.h>
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
      if (i % 64 == 0) usleep(60000);
    }
    CHECK(otl_unslotted == 0, "%llu records without a ring", (unsigned long long)otl_unslotted);
  } else if (!strcmp(mode, "burst")) {
    pthread_t t;
    pthread_create(&t, NULL, burst, (void *)(uintptr_t)200000);
    pthread_join(t, NULL);
  } else if (!strcmp(mode, "identity")) {
    char name[64];
    snprintf(name, sizeof(name), "/otl-test-%d", getpid());
    int fd = shm_open(name, O_CREAT | O_EXCL | O_RDWR, 0600);
    shm_unlink(name);
    ftruncate(fd, 65536);
    uint64_t a = otl_identity(fd);
    void *p = mmap(NULL, 65536, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    CHECK(a && otl_identity(fd) == a && p != MAP_FAILED, "a mapping changed it");
    int other = shm_open("/otl-test-other", O_CREAT | O_RDWR, 0600);
    shm_unlink("/otl-test-other");
    CHECK(otl_identity(other) != a, "another object has it too");
    pid_t pid = fork();
    if (!pid) _exit(otl_identity(dup(fd)) == a ? 0 : 1);
    int status = 0;
    waitpid(pid, &status, 0);
    CHECK(status == 0, "another process sees another identity");
  }
  usleep(300000);
  printf("%s %s\n", mode, fails ? "FAIL" : "ok");
  return fails != 0;
}
