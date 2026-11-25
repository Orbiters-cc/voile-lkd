/* schedwatch_run ENGINE ARGS...: runs it with schedwatch.dylib inserted (beside this program; the shells and the perl of run-with-timeout.sh
 * would drop the variable). What it says goes to sched-log in the current folder. */
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
int main(int c, char **v) {
    char p[4096], d[4096], cwd[2048]; uint32_t n = sizeof p;
    if (c < 2 || _NSGetExecutablePath(p, &n) || !getcwd(cwd, sizeof cwd)) return 2;
    snprintf(d, sizeof d, "%.*s/schedwatch.dylib", (int)(strrchr(p, '/') - p), p); setenv("DYLD_INSERT_LIBRARIES", d, 1);
    snprintf(d, sizeof d, "%s/sched-log", cwd); setenv("SCHEDWATCH_DIR", d, 1);
    execv(v[1], v + 1); perror(v[1]); return 127;
}
