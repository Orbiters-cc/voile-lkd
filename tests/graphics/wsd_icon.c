/*
 * wsd_icon.c - the Dock icon stays the game's (wsd's apply_app_icon).
 *
 * Every Wine program sends its own icon as it attaches, a game's helpers too: on 2026-11-23 VRChat's yt-dlp.exe,
 * started by a world's video player, took the Dock from the game. Two synthetic clients of one wsd, each with its own
 * icon (A 64x64, B 32x32), interleave what a game and its helpers do: icons before and after windows, windows shown
 * and hidden, an overlay plane (a swapchain) created, removed and created again, a second icon, a disconnection.
 * After each step the icon wsd shows is read from its log ("application icon shown: client <pid>'s <w>x<h>").
 *
 * Build: clang -O2 -Wall -o wsd_icon wsd_icon.c
 * Run:   run-wsd-icon.sh   (starts a private wsd, runs this with the socket and the log, under timeouts)
 * Ends with "RESULT PASS|FAIL".
 */
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

#include "../../wsd/wsd_protocol.h"

#define WIN 1u
static const uint32_t W = 320, H = 180;
static const char *g_log;
static int g_fail;

static void die(const char *m)
{
    printf("FATAL: %s (errno %d)\nRESULT FAIL\n", m, errno);
    exit(1);
}

static void send_msg(int sock, uint32_t type, const void *p, uint32_t n, int fd)
{
    uint8_t buf[sizeof(struct wsd_hdr) + WSD_MAX_PAYLOAD];
    struct wsd_hdr h = {type, n};
    memcpy(buf, &h, sizeof h);
    if (n) memcpy(buf + sizeof h, p, n);
    struct iovec iov = {buf, sizeof h + n};
    struct msghdr m = {0};
    char ctl[CMSG_SPACE(sizeof(int))];
    m.msg_iov = &iov;
    m.msg_iovlen = 1;
    if (fd >= 0) {
        m.msg_control = ctl;
        m.msg_controllen = sizeof ctl;
        struct cmsghdr *c = CMSG_FIRSTHDR(&m);
        c->cmsg_level = SOL_SOCKET;
        c->cmsg_type = SCM_RIGHTS;
        c->cmsg_len = CMSG_LEN(sizeof(int));
        memcpy(CMSG_DATA(c), &fd, sizeof(int));
    }
    if (sendmsg(sock, &m, 0) != (ssize_t)(sizeof h + n)) die("sendmsg");
}

/* Reads and drops what the server sent within ms. */
static void drain(int sock, int ms)
{
    static uint8_t b[1 << 16];
    struct pollfd p = {sock, POLLIN, 0};
    while (poll(&p, 1, ms) > 0) {
        ssize_t n = read(sock, b, sizeof b);
        if (n <= 0) return;
        /* events whole in one read in practice; report server errors */
        for (ssize_t o = 0; o + (ssize_t)sizeof(struct wsd_hdr) <= n;) {
            struct wsd_hdr h;
            memcpy(&h, b + o, sizeof h);
            if (h.type == WSD_EV_ERROR && o + (ssize_t)(sizeof h + sizeof(struct wsd_ev_error)) <= n) {
                struct wsd_ev_error e;
                memcpy(&e, b + o + sizeof h, sizeof e);
                printf("server error: request %u code %d\n", e.request_type, e.code);
            }
            o += (ssize_t)(sizeof h + h.len);
        }
        ms = 1;
    }
}

static int shm_buffer(size_t len, uint32_t fill)
{
    char name[64];
    static int k;
    snprintf(name, sizeof name, "/wsdicon.%d.%d", (int)getpid(), k++);
    int fd = shm_open(name, O_RDWR | O_CREAT | O_EXCL, 0600);
    if (fd < 0) die("shm_open");
    shm_unlink(name);
    if (ftruncate(fd, (off_t)len) != 0) die("ftruncate");
    uint32_t *px = mmap(NULL, len, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (px == MAP_FAILED) die("mmap");
    for (size_t i = 0; i < len / 4; i++) px[i] = fill;
    munmap(px, len);
    return fd;
}

static int client(void)
{
    int s = socket(AF_UNIX, SOCK_STREAM, 0);
    return s;
}

static void connect_to(int s, const char *path)
{
    struct sockaddr_un sa = {.sun_family = AF_UNIX};
    if (strlen(path) >= sizeof sa.sun_path) die("socket path too long");
    strcpy(sa.sun_path, path);
    if (connect(s, (struct sockaddr *)&sa, sizeof sa) != 0) die("connect");
    struct wsd_hello hello = {WSD_PROTOCOL_VERSION, (uint32_t)getpid()};
    send_msg(s, WSD_HELLO, &hello, sizeof hello, -1);
}

static void icon(int s, uint32_t side, uint32_t color)
{
    size_t len = (size_t)side * side * 4;
    /* wsd preads an icon: a file, as the driver sends (a POSIX shm object cannot be read with pread) */
    char path[] = "/tmp/wsdicon.XXXXXX";
    int fd = mkstemp(path);
    if (fd < 0) die("mkstemp");
    unlink(path);
    for (size_t i = 0; i < len / 4; i++) if (write(fd, &color, 4) != 4) die("write");
    struct wsd_app_icon a = {side, side, side * 4, 0, 0, (uint64_t)len};
    send_msg(s, WSD_APP_ICON, &a, sizeof a, fd);
    close(fd);
}

static void window(int s, int show)
{
    struct wsd_window_create wc = {WIN, W, H, 0};
    send_msg(s, WSD_WINDOW_CREATE, &wc, sizeof wc, -1);
    struct wsd_window_flag f = {WIN, show ? 2u : 0u}; /* shown without activation */
    if (show) send_msg(s, WSD_WINDOW_SHOW, &f, sizeof f, -1);
}

static void show(int s, int on)
{
    struct wsd_window_flag f = {WIN, on ? 2u : 0u};
    send_msg(s, WSD_WINDOW_SHOW, &f, sizeof f, -1);
}

static uint64_t g_serial;
static void attach(int s)
{
    size_t len = (size_t)W * H * 4;
    int fd = shm_buffer(len, 0xFF208040u);
    struct wsd_buffer_attach ba = {1, W, H, W * 4, WSD_FMT_BGRA8, 0, 0, (uint64_t)len};
    send_msg(s, WSD_BUFFER_ATTACH, &ba, sizeof ba, fd);
    close(fd);
}

static void present_plane(int s, int on)
{
    struct wsd_present_region r = {{WIN, on ? 1u : 0u, ++g_serial, 0}, 0, 0, on ? W : 0, on ? H : 0};
    send_msg(s, WSD_PRESENT_REGION, &r, sizeof r, -1);
}

/* The size of the icon wsd shows now, from the last "application icon shown" line of its log; 0 if none. */
static unsigned shown_now(void)
{
    FILE *f = fopen(g_log, "r");
    if (!f) return 0;
    char line[512];
    unsigned side = 0;
    while (fgets(line, sizeof line, f)) {
        char *p = strstr(line, "application icon shown: client ");
        if (!p) continue;
        p = strstr(p, "'s ");
        unsigned w = 0, h = 0;
        if (p && sscanf(p + 3, "%ux%u", &w, &h) == 2) side = w;
    }
    fclose(f);
    return side;
}

static void expect(const char *step, unsigned side, int a, int b)
{
    drain(a, 150);
    if (b >= 0) drain(b, 150);
    unsigned got = shown_now();
    for (int i = 0; i < 20 && got != side; i++) { drain(a, 50); got = shown_now(); } /* the log may lag a moment */
    printf("%-58s icon %ux%u%s\n", step, got, got, got == side ? "" : "   <-- wrong");
    if (got != side) {
        printf("CHECK FAILED: %s: want %ux%u\n", step, side, side);
        g_fail = 1;
    }
}

int main(int argc, char **argv)
{
    if (argc < 3) { fprintf(stderr, "usage: %s <socket> <wsd log>\n", argv[0]); return 2; }
    g_log = argv[2];
    int a = client(), b = client();
    connect_to(a, argv[1]);
    icon(a, 64, 0xFFC02020u);
    expect("A (no window yet) sends its icon: the first one shows", 64, a, -1);
    connect_to(b, argv[1]);
    icon(b, 32, 0xFF2020C0u);
    expect("B, a helper without a window, sends its icon: A's stays", 64, a, b);
    window(a, 1);
    expect("A shows a window", 64, a, b);
    window(b, 1);
    attach(b);
    expect("B shows a window after A: A's stays", 64, a, b);
    present_plane(b, 1);
    expect("B's window gets an overlay plane (the game): B's", 32, a, b);
    present_plane(b, 0);
    expect("B removes its plane (swapchain rebuild): B's stays", 32, a, b);
    present_plane(b, 1);
    expect("B presents again: B's", 32, a, b);
    icon(a, 48, 0xFF20C020u);
    expect("A sends another icon (a helper started again): B's stays", 32, a, b);
    attach(a);
    present_plane(a, 1);
    expect("A's window gets a plane too: the first game, B, keeps it", 32, a, b);
    show(b, 0);
    expect("B hides its window: B's stays", 32, a, b);
    close(b);
    expect("B disconnects: A's latest", 48, a, -1);
    close(a);
    printf("RESULT %s\n", g_fail ? "FAIL" : "PASS");
    return g_fail;
}
