/* pointer_game.exe full|win: what a Unity game does with the pointer, told key by key (pointer_game.py presses them through wsd's
 * test input): F1 locks it (cursor hidden, ClipCursor to one pixel at the window's middle), F2 frees it (cursor still hidden,
 * ClipCursor(NULL)), F3 shows the cursor and frees it, F4 hides it and confines it to a 41x41 square at the middle, F5 locks and
 * frees it 60 times at once. F8 ends. It takes raw input as Unity does. Each line: the time in ms since 1970, then what happened. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdarg.h>
static BOOL hidden = TRUE, locked;
static HCURSOR arrow;
static HWND hwnd;
static POINT mid;
static void say(const char *f, ...)
{
    FILETIME ft; ULARGE_INTEGER u; va_list v;
    GetSystemTimeAsFileTime(&ft); u.LowPart = ft.dwLowDateTime; u.HighPart = ft.dwHighDateTime;
    printf("G %llu ", (unsigned long long)(u.QuadPart / 10000 - 11644473600000ULL));
    va_start(v, f); vprintf(f, v); va_end(v); printf("\n"); fflush(stdout);
}
static void confine(int half)
{
    RECT r = { mid.x - half, mid.y - half, mid.x + half + 1, mid.y + half + 1 };
    ClipCursor(&r);
}
static void state(const char *what)
{
    POINT p; RECT c; GetCursorPos(&p); GetClipCursor(&c);
    say("%s cursor %ld,%ld clip %ld,%ld %ldx%ld", what, p.x, p.y, c.left, c.top, c.right - c.left, c.bottom - c.top);
}
static LRESULT CALLBACK proc(HWND h, UINT msg, WPARAM wp, LPARAM lp)
{
    POINT p;
    switch (msg) {
    case WM_SETCURSOR: if (LOWORD(lp) == HTCLIENT) { SetCursor(hidden ? NULL : arrow); return TRUE; } break;
    case WM_INPUT: {
        RAWINPUT r; UINT n = sizeof r;
        GetRawInputData((HRAWINPUT)lp, RID_INPUT, &r, &n, sizeof r.header);
        if (r.header.dwType == RIM_TYPEMOUSE) say("raw %ld %ld flags %x buttons %x", r.data.mouse.lLastX, r.data.mouse.lLastY, r.data.mouse.usFlags, r.data.mouse.usButtonFlags);
        break; }
    case WM_MOUSEMOVE: GetCursorPos(&p); say("move %d %d cursor %ld %ld", (short)LOWORD(lp), (short)HIWORD(lp), p.x, p.y); return 0;
    case WM_LBUTTONDOWN: SetCapture(h); GetCursorPos(&p); say("down %d %d cursor %ld %ld", (short)LOWORD(lp), (short)HIWORD(lp), p.x, p.y); return 0;
    case WM_LBUTTONUP: ReleaseCapture(); say("up %d %d", (short)LOWORD(lp), (short)HIWORD(lp)); return 0;
    case WM_ACTIVATE: say("active %d", LOWORD(wp)); if (LOWORD(wp) && locked) confine(0); break;
    case WM_KEYUP: say("keyup %x", (unsigned)wp); return 0;
    case WM_KEYDOWN:
        say("keydown %x", (unsigned)wp);
        if (wp == VK_F1) { locked = TRUE; hidden = TRUE; SetCursor(NULL); confine(0); state("locked"); }
        if (wp == VK_F2) { locked = FALSE; ClipCursor(NULL); state("freed"); }
        if (wp == VK_F3) { locked = FALSE; hidden = FALSE; ClipCursor(NULL); SetCursor(arrow); state("shown"); }
        if (wp == VK_F4) { locked = FALSE; hidden = TRUE; SetCursor(NULL); confine(20); state("confined"); }
        if (wp == VK_F5) { for (int i = 0; i < 60; i++) { confine(0); ClipCursor(NULL); } confine(0); locked = TRUE; state("toggled"); }
        if (wp == VK_F6) state("state");
        if (wp == VK_F8) DestroyWindow(h);
        return 0;
    case WM_PAINT: { PAINTSTRUCT ps; BeginPaint(h, &ps); EndPaint(h, &ps); return 0; }
    case WM_TIMER: { static int n; HDC dc = GetDC(h); RECT r = { 10, 10, 60 + (n++ % 2), 60 }; FillRect(dc, &r, (HBRUSH)GetStockObject(GRAY_BRUSH)); ReleaseDC(h, dc); return 0; }
    case WM_DESTROY: PostQuitMessage(0); return 0;
    }
    return DefWindowProcA(h, msg, wp, lp);
}
int main(int argc, char **argv)
{
    BOOL full = argc < 2 || argv[1][0] == 'f';
    WNDCLASSA wc = { 0 };
    arrow = LoadCursorA(NULL, (LPCSTR)IDC_ARROW);
    wc.lpfnWndProc = proc; wc.hInstance = GetModuleHandleA(NULL); wc.lpszClassName = "pointergame"; wc.hCursor = arrow;
    wc.hbrBackground = (HBRUSH)GetStockObject(BLACK_BRUSH);
    RegisterClassA(&wc);
    int sw = GetSystemMetrics(SM_CXSCREEN), sh = GetSystemMetrics(SM_CYSCREEN);
    hwnd = full ? CreateWindowExA(0, "pointergame", "pointer game", WS_POPUP, 0, 0, sw, sh, NULL, NULL, wc.hInstance, NULL)
                : CreateWindowExA(0, "pointergame", "pointer game", WS_OVERLAPPEDWINDOW, 160, 200, 640, 480, NULL, NULL, wc.hInstance, NULL);
    ShowWindow(hwnd, SW_SHOW); UpdateWindow(hwnd); SetForegroundWindow(hwnd); SetFocus(hwnd);
    RAWINPUTDEVICE d = { 1, 2, 0, hwnd };
    RegisterRawInputDevices(&d, 1, sizeof d);
    RECT r; GetClientRect(hwnd, &r); mid.x = (r.right - r.left) / 2; mid.y = (r.bottom - r.top) / 2; ClientToScreen(hwnd, &mid);
    POINT o = { 0, 0 }; ClientToScreen(hwnd, &o);
    SetTimer(hwnd, 1, 40, NULL);
    say("ready screen %dx%d client %ldx%ld at %ld,%ld mid %ld,%ld", sw, sh, r.right, r.bottom, o.x, o.y, mid.x, mid.y);
    MSG m;
    while (GetMessageA(&m, NULL, 0, 0) > 0) { TranslateMessage(&m); DispatchMessageA(&m); }
    ClipCursor(NULL);
    say("done");
    return 0;
}
