/*
 * query_client.cpp - owned Direct3D 11 client for queries: what an application that looks at its queries is promised, one case at
 * a time with oracles of its own, and a randomised soak. No window, no swapchain. Two builds of the one file
 * (build-query-client.sh): Windows x86-64, run through the engine's Wine, Neptune and the render server (run-query-client.sh),
 * and a Mac program on libdxmt-native itself, whose every look is the application's own (so that they can be counted).
 *
 * Usage: query_client [-d <dxmt-native>] [-once] [-order] cases [case ...]
 *        query_client [-d <dxmt-native>] [-once] soak <seed> <generations> [wide]
 *        query_client [-d <dxmt-native>] [-once] bench <gated|busy|rings|lists> <frames>   (frames as fast as they come: BENCH lines)
 *        query_client [-d <dxmt-native>] pending        (ends the process with queries pending)
 *
 * The pictures are solid rectangles: what each must be is also drawn by the CPU, and compared byte for byte.
 * -once, -order: the switch (OBELISK_DXMT_QUERY_RESCUE=once, OBELISK_DXMT_INIT_ORDER=1) is on (the Mac program sees it in its environment): what
 * only it promises is checked, and is otherwise told (KNOWN).
 * Lines: MODE <case> frames=1 begin=<ns> end=<ns> (tools/timeline/otl.py --modes cuts a recording by them), CHECK <case> <what>
 * ok|FAIL|UNSUPPORTED, HASH <case> <crc32>, NOTE. Ends with RESULT PASS or RESULT FAIL. A watchdog ends the process (exit 3) when
 * nothing has progressed for 20 s.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d11_4.h>
#include <dxgi.h>
#include <algorithm>
#include <atomic>
#include <chrono>
#include <mutex>
#include <string>
#include <thread>
#include <vector>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "dxbc/shaders_dxbc.h"
#ifndef _WIN32
#include <dlfcn.h>
#include <time.h>
#include <unistd.h>
typedef HRESULT (*CreateDevice)(IDXGIAdapter *, D3D_DRIVER_TYPE, HMODULE, UINT, const D3D_FEATURE_LEVEL *, UINT, UINT, ID3D11Device **,
                                D3D_FEATURE_LEVEL *, ID3D11DeviceContext **);
static CreateDevice create_device;
#else
#define create_device D3D11CreateDevice
#endif

static std::atomic<uint64_t> progress;
static std::atomic<const char *> doing{"start"};
static std::atomic<int> failures, checks;
static std::mutex out_lock;

static uint64_t ns() {
#ifdef _WIN32
  LARGE_INTEGER f, c;
  QueryPerformanceFrequency(&f);
  QueryPerformanceCounter(&c);
  return (uint64_t)c.QuadPart / f.QuadPart * 1000000000ull + (uint64_t)c.QuadPart % f.QuadPart * 1000000000ull / f.QuadPart;
#else
  return clock_gettime_nsec_np(CLOCK_MONOTONIC_RAW);
#endif
}
static void nap_us(unsigned us) { std::this_thread::sleep_for(std::chrono::microseconds(us)); }
static void say(const char *format, ...) {
  std::lock_guard<std::mutex> l(out_lock);
  va_list a;
  va_start(a, format);
  vprintf(format, a);
  va_end(a);
  fflush(stdout);
}
[[noreturn]] static void leave(int code) {
  fflush(stdout);
#ifdef _WIN32
  TerminateProcess(GetCurrentProcess(), (UINT)code);
#endif
  _exit(code);
}
#define HR(x) do { HRESULT hr_ = (x); if (FAILED(hr_)) { say("FAILED %s 0x%08lx in %s\nRESULT FAIL\n", #x, (unsigned long)hr_, doing.load()); leave(1); } } while (0)

static bool ordered; /* OBELISK_DXMT_INIT_ORDER=1, as far as this program is told */
static bool once; /* OBELISK_DXMT_QUERY_RESCUE=once, as far as this program is told */
/* On libdxmt-native itself every look is this program's; through Neptune a look reads what the render server's own looks published (and for
 * a query ended in a command list, nothing is published: the guest asks itself, 50 ms later at the earliest). */
#ifdef _WIN32
static const bool native = false;
#else
static const bool native = true;
#endif
static const char *current = "";
static bool check(bool good, const char *format, ...) {
  char text[400];
  va_list a;
  va_start(a, format);
  vsnprintf(text, sizeof(text), format, a);
  va_end(a);
  checks++;
  if (!good) failures++;
  say("CHECK %s %s: %s\n", current, text, good ? "ok" : "FAIL");
  return good;
}
static void note(const char *format, ...) {
  char text[400];
  va_list a;
  va_start(a, format);
  vsnprintf(text, sizeof(text), format, a);
  va_end(a);
  say("NOTE %s %s\n", current, text);
}

static uint32_t crc32_of(const void *data, size_t n, uint32_t c = 0) {
  static uint32_t table[256];
  if (!table[1])
    for (uint32_t i = 0; i < 256; i++) {
      uint32_t v = i;
      for (int k = 0; k < 8; k++) v = v & 1 ? 0xEDB88320u ^ v >> 1 : v >> 1;
      table[i] = v;
    }
  c = ~c;
  for (const uint8_t *p = (const uint8_t *)data; n--; p++) c = table[(c ^ *p) & 255] ^ c >> 8;
  return ~c;
}
struct Random {
  uint64_t s;
  explicit Random(uint64_t seed) : s(seed * 0x9E3779B97F4A7C15ull + 1) {}
  uint32_t next() { s ^= s << 13; s ^= s >> 7; s ^= s << 17; return (uint32_t)(s >> 32); }
  uint32_t below(uint32_t n) { return next() % n; }
  bool one_in(uint32_t n) { return below(n) == 0; }
};

enum { PX = 256 };
struct Vertex { float pos[2], uv[2], color[4]; };
static const Vertex kFull[3] = {{{-1, -1}, {0, 1}, {1, 1, 1, 1}}, {{-1, 3}, {0, -1}, {1, 1, 1, 1}}, {{3, -1}, {2, 1}, {1, 1, 1, 1}}};

struct Colour { uint8_t v[4]; };
static const UINT DONT = D3D11_ASYNC_GETDATA_DONOTFLUSH;

static bool immutable_as_host; /* natively: immutable textures are made without their data, and updated, as Neptune's host makes what the guest made with them */
/* A device, its immediate context, what a rectangle takes, two pictures, and the same two by the CPU. */
struct Gpu {
  ID3D11Device *dev = nullptr;
  ID3D11DeviceContext *ctx = nullptr;
  ID3D11DeviceContext4 *ctx4 = nullptr;
  ID3D11Buffer *vb = nullptr, *cb = nullptr;
  ID3D11VertexShader *vs = nullptr;
  ID3D11PixelShader *ps = nullptr, *ps_tex = nullptr;
  ID3D11InputLayout *layout = nullptr;
  ID3D11DepthStencilState *pass = nullptr, *never = nullptr;
  ID3D11BlendState *add = nullptr;
  ID3D11SamplerState *sampler = nullptr;
  struct Picture {
    ID3D11Texture2D *tex = nullptr, *staging = nullptr, *ds = nullptr;
    ID3D11RenderTargetView *rtv = nullptr;
    ID3D11DepthStencilView *dsv = nullptr;
    std::vector<uint8_t> model;
  } picture[2];
  ID3D11Texture2D *big = nullptr, *big_source = nullptr;
  ID3D11RenderTargetView *big_rtv = nullptr;
  ID3D11ShaderResourceView *big_srv = nullptr;
  int target = -1;

  void make() {
    D3D_FEATURE_LEVEL want = D3D_FEATURE_LEVEL_11_0, got;
    HR(create_device(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0, &want, 1, D3D11_SDK_VERSION, &dev, &got, &ctx));
    if (FAILED(ctx->QueryInterface(__uuidof(ID3D11DeviceContext4), (void **)&ctx4))) ctx4 = nullptr;
    HR(dev->CreateVertexShader(dxbc_vs_pass, sizeof(dxbc_vs_pass), nullptr, &vs));
    HR(dev->CreatePixelShader(dxbc_ps_cbuf, sizeof(dxbc_ps_cbuf), nullptr, &ps));
    HR(dev->CreatePixelShader(dxbc_ps_tex, sizeof(dxbc_ps_tex), nullptr, &ps_tex));
    D3D11_INPUT_ELEMENT_DESC il[] = {{"POSITION", 0, DXGI_FORMAT_R32G32_FLOAT, 0, 0, D3D11_INPUT_PER_VERTEX_DATA, 0},
                                     {"TEXCOORD", 0, DXGI_FORMAT_R32G32_FLOAT, 0, 8, D3D11_INPUT_PER_VERTEX_DATA, 0},
                                     {"COLOR", 0, DXGI_FORMAT_R32G32B32A32_FLOAT, 0, 16, D3D11_INPUT_PER_VERTEX_DATA, 0}};
    HR(dev->CreateInputLayout(il, 3, dxbc_vs_pass, sizeof(dxbc_vs_pass), &layout));
    D3D11_BUFFER_DESC bd = {sizeof(kFull), D3D11_USAGE_IMMUTABLE, D3D11_BIND_VERTEX_BUFFER, 0, 0, 0};
    D3D11_SUBRESOURCE_DATA init = {kFull, 0, 0};
    HR(dev->CreateBuffer(&bd, &init, &vb));
    bd = {16, D3D11_USAGE_DYNAMIC, D3D11_BIND_CONSTANT_BUFFER, D3D11_CPU_ACCESS_WRITE, 0, 0};
    HR(dev->CreateBuffer(&bd, nullptr, &cb));
    D3D11_DEPTH_STENCIL_DESC dd = {};
    dd.DepthEnable = TRUE;
    dd.DepthWriteMask = D3D11_DEPTH_WRITE_MASK_ZERO;
    dd.DepthFunc = D3D11_COMPARISON_LESS_EQUAL;
    HR(dev->CreateDepthStencilState(&dd, &pass));
    dd.DepthFunc = D3D11_COMPARISON_NEVER;
    HR(dev->CreateDepthStencilState(&dd, &never));
    D3D11_BLEND_DESC bl = {};
    bl.RenderTarget[0] = {TRUE, D3D11_BLEND_ONE, D3D11_BLEND_ONE, D3D11_BLEND_OP_ADD, D3D11_BLEND_ONE, D3D11_BLEND_ONE, D3D11_BLEND_OP_ADD, 15};
    HR(dev->CreateBlendState(&bl, &add));
    D3D11_SAMPLER_DESC sm = {};
    sm.Filter = D3D11_FILTER_MIN_MAG_MIP_LINEAR;
    sm.AddressU = sm.AddressV = sm.AddressW = D3D11_TEXTURE_ADDRESS_CLAMP;
    sm.MaxLOD = D3D11_FLOAT32_MAX;
    HR(dev->CreateSamplerState(&sm, &sampler));
    for (auto &p : picture) {
      D3D11_TEXTURE2D_DESC d = {PX, PX, 1, 1, DXGI_FORMAT_R8G8B8A8_UNORM, {1, 0}, D3D11_USAGE_DEFAULT, D3D11_BIND_RENDER_TARGET, 0, 0};
      HR(dev->CreateTexture2D(&d, nullptr, &p.tex));
      HR(dev->CreateRenderTargetView(p.tex, nullptr, &p.rtv));
      d.Usage = D3D11_USAGE_STAGING; d.BindFlags = 0; d.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
      HR(dev->CreateTexture2D(&d, nullptr, &p.staging));
      d = {PX, PX, 1, 1, DXGI_FORMAT_D24_UNORM_S8_UINT, {1, 0}, D3D11_USAGE_DEFAULT, D3D11_BIND_DEPTH_STENCIL, 0, 0};
      HR(dev->CreateTexture2D(&d, nullptr, &p.ds));
      HR(dev->CreateDepthStencilView(p.ds, nullptr, &p.dsv));
      p.model.assign(PX * PX * 4, 0);
    }
    for (int i = 0; i < 2; i++) {
      use(i);
      clear(i, {{0, 0, 0, 255}});
      ctx->ClearDepthStencilView(picture[i].dsv, D3D11_CLEAR_DEPTH, 1, 0);
    }
    /* Its pipelines, made here: a device let go of while one is still compiled ends libdxmt-native (the pool's threads), with the
     * switch and without, and that is not what is asked here. */
    for (int k = 0; k < 2; k++) { use(0); rect_on(ctx, 0, 0, 5, 5, {{0, 0, 0, 255}}, k); burn(1); }
    ID3D11Query *e = query(D3D11_QUERY_EVENT);
    ctx->End(e);
    BOOL there;
    for (const uint64_t began = ns(); ctx->GetData(e, &there, sizeof(there), 0) == S_FALSE && ns() - began < 5000000000ull;) {}
    e->Release();
  }
  void drop() {
    ctx->ClearState();
    for (auto &p : picture) { p.tex->Release(); p.staging->Release(); p.ds->Release(); p.rtv->Release(); p.dsv->Release(); p = {}; }
    for (IUnknown *u : std::initializer_list<IUnknown *>{big, big_source, big_rtv, big_srv, vb, cb, vs, ps, ps_tex, layout, pass, never, add, sampler, ctx4, ctx})
      if (u) u->Release();
    dev->Release();
    *this = Gpu();
  }
  static void use_on(ID3D11DeviceContext *c, Picture &p) { c->OMSetRenderTargets(1, &p.rtv, p.dsv); }
  void use(int i) { if (target != i) { use_on(ctx, picture[i]); target = i; } }
  void clear(int i, Colour k) {
    float f[4];
    for (int n = 0; n < 4; n++) f[n] = k.v[n] / 255.0f;
    ctx->ClearRenderTargetView(picture[i].rtv, f);
    for (size_t n = 0; n < picture[i].model.size(); n++) picture[i].model[n] = k.v[n & 3];
  }
  /* Only what is drawn: the model is the caller's, as a command list is drawn when it is executed. */
  void rect_on(ID3D11DeviceContext *c, int x, int y, int w, int h, Colour k, bool seen = true) {
    D3D11_MAPPED_SUBRESOURCE m;
    HR(c->Map(cb, 0, D3D11_MAP_WRITE_DISCARD, 0, &m));
    float f[4];
    for (int n = 0; n < 4; n++) f[n] = k.v[n] / 255.0f;
    memcpy(m.pData, f, sizeof(f));
    c->Unmap(cb, 0);
    D3D11_VIEWPORT vp = {(float)x, (float)y, (float)w, (float)h, 0, 1};
    UINT stride = sizeof(Vertex), off = 0;
    c->RSSetViewports(1, &vp);
    c->IASetVertexBuffers(0, 1, &vb, &stride, &off);
    c->IASetInputLayout(layout);
    c->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    c->VSSetShader(vs, nullptr, 0);
    c->PSSetShader(ps, nullptr, 0);
    c->PSSetConstantBuffers(0, 1, &cb);
    c->OMSetBlendState(nullptr, nullptr, ~0u);
    c->OMSetDepthStencilState(seen ? pass : never, 0);
    c->Draw(3, 0);
  }
  void drawn(int i, int x, int y, int w, int h, Colour k) {
    for (int yy = y; yy < y + h; yy++)
      for (int xx = x; xx < x + w; xx++) memcpy(&picture[i].model[(yy * PX + xx) * 4], k.v, 4);
  }
  void rect(int i, int x, int y, int w, int h, Colour k, bool seen = true) {
    use(i);
    rect_on(ctx, x, y, w, h, k, seen);
    if (seen) drawn(i, x, y, w, h, k);
  }
  /* A rectangle of a texture made for it, with its data: it is seen only once its upload was. */
  void fresh_rect(int i, int x, int y, int w, int h, Colour k, D3D11_USAGE usage = D3D11_USAGE_DEFAULT) {
    std::vector<uint8_t> data(64 * 64 * 4);
    for (size_t n = 0; n < data.size(); n++) data[n] = k.v[n & 3];
    D3D11_TEXTURE2D_DESC d = {64, 64, 1, 1, DXGI_FORMAT_R8G8B8A8_UNORM, {1, 0}, usage, D3D11_BIND_SHADER_RESOURCE, 0, 0};
    D3D11_SUBRESOURCE_DATA init = {data.data(), 64 * 4, 0};
    ID3D11Texture2D *t;
    ID3D11ShaderResourceView *v;
    const bool late = usage == D3D11_USAGE_IMMUTABLE && immutable_as_host;
    HR(dev->CreateTexture2D(&d, late ? nullptr : &init, &t));
    if (late) ctx->UpdateSubresource(t, 0, nullptr, data.data(), 64 * 4, 0);
    HR(dev->CreateShaderResourceView(t, nullptr, &v));
    use(i);
    D3D11_VIEWPORT vp = {(float)x, (float)y, (float)w, (float)h, 0, 1};
    UINT stride = sizeof(Vertex), off = 0;
    ctx->RSSetViewports(1, &vp);
    ctx->IASetVertexBuffers(0, 1, &vb, &stride, &off);
    ctx->IASetInputLayout(layout);
    ctx->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    ctx->VSSetShader(vs, nullptr, 0);
    ctx->PSSetShader(ps_tex, nullptr, 0);
    ctx->PSSetSamplers(0, 1, &sampler);
    ctx->PSSetShaderResources(0, 1, &v);
    ctx->OMSetBlendState(nullptr, nullptr, ~0u);
    ctx->OMSetDepthStencilState(pass, 0);
    ctx->Draw(3, 0);
    v->Release();
    t->Release();
    drawn(i, x, y, w, h, k);
  }
  void copy(int to, int from, int x, int y, int w, int h) {
    D3D11_BOX b = {(UINT)x, (UINT)y, 0, (UINT)(x + w), (UINT)(y + h), 1};
    ctx->CopySubresourceRegion(picture[to].tex, 0, x, y, 0, picture[from].tex, 0, &b);
    for (int yy = y; yy < y + h; yy++)
      memcpy(&picture[to].model[(yy * PX + x) * 4], &picture[from].model[(yy * PX + x) * 4], w * 4);
  }
  /* The picture as the GPU has it: 0 when it is the model's, else how many pixels differ; `crc` of it. */
  unsigned differs(int i, uint32_t *crc) {
    Picture &p = picture[i];
    ctx->CopyResource(p.staging, p.tex);
    D3D11_MAPPED_SUBRESOURCE m;
    HR(ctx->Map(p.staging, 0, D3D11_MAP_READ, 0, &m));
    unsigned bad = 0;
    uint32_t c = 0;
    for (int y = 0; y < PX; y++) {
      const uint8_t *row = (const uint8_t *)m.pData + y * m.RowPitch;
      c = crc32_of(row, PX * 4, c);
      if (memcmp(row, &p.model[y * PX * 4], PX * 4))
        for (int x = 0; x < PX; x++)
          if (memcmp(row + x * 4, &p.model[(y * PX + x) * 4], 4) && bad++ < 3) {
            uint32_t got, want;
            memcpy(&got, row + x * 4, 4);
            memcpy(&want, &p.model[(y * PX + x) * 4], 4);
            note("picture %d at %d, %d: %08x, wanted %08x", i, x, y, got, want);
          }
    }
    ctx->Unmap(p.staging, 0);
    if (crc) *crc = c;
    return bad;
  }
  /* GPU work of `layers` blended layers over 2048 x 2048. */
  void burn(unsigned layers) {
    make_big();
    target = -1;
    burn_on(ctx, layers);
  }
  void make_big() {
    if (!big) {
      D3D11_TEXTURE2D_DESC d = {2048, 2048, 1, 1, DXGI_FORMAT_R8G8B8A8_UNORM, {1, 0}, D3D11_USAGE_DEFAULT,
                                D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE, 0, 0};
      HR(dev->CreateTexture2D(&d, nullptr, &big));
      HR(dev->CreateRenderTargetView(big, nullptr, &big_rtv));
      HR(dev->CreateTexture2D(&d, nullptr, &big_source));
      HR(dev->CreateShaderResourceView(big_source, nullptr, &big_srv));
    }
  }
  void burn_on(ID3D11DeviceContext *c, unsigned layers) {
    c->OMSetRenderTargets(1, &big_rtv, nullptr);
    D3D11_VIEWPORT vp = {0, 0, 2048, 2048, 0, 1};
    UINT stride = sizeof(Vertex), off = 0;
    c->RSSetViewports(1, &vp);
    c->IASetVertexBuffers(0, 1, &vb, &stride, &off);
    c->IASetInputLayout(layout);
    c->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    c->VSSetShader(vs, nullptr, 0);
    c->PSSetShader(ps_tex, nullptr, 0);
    c->PSSetSamplers(0, 1, &sampler);
    c->PSSetShaderResources(0, 1, &big_srv);
    c->OMSetBlendState(add, nullptr, ~0u);
    c->OMSetDepthStencilState(pass, 0);
    for (unsigned i = 0; i < layers; i++) c->Draw(3, 0);
  }
  ID3D11Query *query(D3D11_QUERY type) {
    ID3D11Query *q;
    D3D11_QUERY_DESC d = {type, 0};
    HR(dev->CreateQuery(&d, &q));
    return q;
  }
};

static Gpu g;
static unsigned layers_40ms = 100; /* calibrated */

struct Looked { HRESULT hr; double ms; uint64_t looks; };
/* Looks until it is there, nothing else, at most `limit` ms. `pause` us between looks. */
static Looked look(ID3D11DeviceContext *c, ID3D11Query *q, UINT flags, void *out, UINT size, double limit = 4000, unsigned pause = 0) {
  const uint64_t begin = ns();
  Looked l = {S_FALSE, 0, 0};
  do {
    l.hr = c->GetData(q, out, size, flags);
    l.looks++;
    l.ms = (ns() - begin) / 1e6;
    if (l.hr == S_FALSE && pause) nap_us(pause);
  } while (l.hr == S_FALSE && l.ms < limit);
  progress++;
  return l;
}
static Looked look_event(ID3D11Query *q, UINT flags, double limit = 4000, unsigned pause = 0) {
  BOOL there = FALSE;
  Looked l = look(g.ctx, q, flags, &there, sizeof(there), limit, pause);
  if (l.hr == S_OK && !there) l.hr = E_FAIL;
  return l;
}
static void picture_good(const char *what = "the picture is the CPU's") {
  for (int i = 0; i < 2; i++) {
    uint32_t crc;
    unsigned bad = g.differs(i, &crc);
    check(!bad, "%s (%d, %u pixels differ)", what, i, bad);
    say("HASH %s.%d %08x\n", current, i, crc);
  }
}
static Colour shade(unsigned n) { return {{(uint8_t)(n * 37), (uint8_t)(n * 101 + 7), (uint8_t)(n * 59 + 31), 255}}; }

/* ---- the cases ---- */

/* Nothing but looks, with DONOTFLUSH, after each thing the End can follow: each must get there. */
static void noflush_spin() {
  ID3D11Query *e = g.query(D3D11_QUERY_EVENT), *e2 = g.query(D3D11_QUERY_EVENT), *d = g.query(D3D11_QUERY_TIMESTAMP_DISJOINT);
  for (int round = 0; round < 3; round++) {
    g.rect(0, 10, 10, 100, 50, shade(round));
    g.ctx->End(e);
    Looked l = look_event(e, DONT);
    check(l.hr == S_OK, "after a draw, DONOTFLUSH only: there (%.1f ms, %llu looks)", l.ms, (unsigned long long)l.looks);
    g.clear(1, shade(round + 9));
    g.ctx->End(e);
    l = look_event(e, DONT);
    check(l.hr == S_OK, "after a clear: there (%.1f ms)", l.ms);
    g.copy(1, 0, 0, 0, 64, 64);
    g.ctx->End(e);
    l = look_event(e, DONT);
    check(l.hr == S_OK, "after a copy: there (%.1f ms)", l.ms);
    g.ctx->End(e);
    l = look_event(e, DONT);
    check(l.hr == S_OK, "after nothing new: there (%.1f ms)", l.ms);
    g.rect(0, 10, 80, 30, 30, shade(round + 3));
    g.ctx->End(e);
    g.ctx->End(e2); /* nothing between: the same moment */
    g.ctx->End(e);
    l = look_event(e2, DONT);
    Looked l2 = look_event(e, DONT);
    check(l.hr == S_OK && l2.hr == S_OK, "three Ends of one moment: there (%.1f ms, %.1f ms)", l.ms, l2.ms);
    g.rect(0, 50, 80, 30, 30, shade(round + 4));
    g.ctx->Begin(d);
    g.rect(0, 90, 80, 30, 30, shade(round + 5));
    g.ctx->End(d);
    D3D11_QUERY_DATA_TIMESTAMP_DISJOINT data = {};
    l = look(g.ctx, d, DONT, &data, sizeof(data));
    check(l.hr == S_OK && data.Frequency == 1000000000 && !data.Disjoint, "a disjoint pair: there, %llu Hz, disjoint %d (%.1f ms)",
          (unsigned long long)data.Frequency, (int)data.Disjoint, l.ms);
    g.rect(0, 130, 80, 30, 30, shade(round + 6));
    g.ctx->End(e);
    g.rect(0, 170, 80, 30, 30, shade(round + 7)); /* recorded after it, and nothing else is ever called */
    l = look_event(e, DONT, 4000, 50);
    check(l.hr == S_OK, "with a draw recorded after it, 50 us between looks: there (%.1f ms, %llu looks)", l.ms, (unsigned long long)l.looks);
    g.rect(0, 10, 120, 30, 30, shade(round + 8));
    g.ctx->End(e);
    l = look(g.ctx, e, DONT, nullptr, 0);
    check(l.hr == S_OK, "GetData of no size: there (%.1f ms)", l.ms);
  }
  picture_good();
  e->Release(); e2->Release(); d->Release();
}

/* Without DONOTFLUSH a look flushes; alternating flags; the order of flags changes nothing. */
static void flags_zero() {
  ID3D11Query *e = g.query(D3D11_QUERY_EVENT);
  double worst = 0;
  bool good = true;
  for (int n = 0; n < 40; n++) {
    g.rect(0, n, n, 20, 20, shade(n));
    g.ctx->End(e);
    Looked l = look_event(e, 0);
    good &= l.hr == S_OK;
    if (l.ms > worst) worst = l.ms;
  }
  check(good, "flags 0: 40 of 40 there (the slowest %.1f ms)", worst);
  worst = 0;
  for (int n = 0; n < 40; n++) {
    g.rect(0, 100 + n, n, 20, 20, shade(n + 40));
    g.ctx->End(e);
    const uint64_t begin = ns();
    BOOL there = FALSE;
    HRESULT hr = S_FALSE;
    for (unsigned k = 0; hr == S_FALSE && ns() - begin < 4000000000ull; k++) hr = g.ctx->GetData(e, &there, sizeof(there), k % 3 ? DONT : 0);
    good &= hr == S_OK && there;
    worst = std::max(worst, (ns() - begin) / 1e6);
    progress++;
  }
  check(good, "flags in turn: 40 of 40 there (the slowest %.1f ms)", worst);
  for (int n = 0; n < 10; n++) { /* the first look that may flush must, however many that may not came before */
    g.rect(0, 5 * n, 200, 5, 20, shade(n + 80));
    g.ctx->End(e);
    BOOL there;
    for (int k = 0; k < 20; k++) g.ctx->GetData(e, &there, sizeof(there), DONT);
    Looked l = look_event(e, 0);
    good &= l.hr == S_OK;
  }
  check(good, "DONOTFLUSH twenty times, then flags 0: there");
  picture_good();
  e->Release();
}

/* The chunk of the query is handed over by an explicit Flush and the GPU is busy; the application goes on recording and looking:
 * nothing is owed, and (with the switch) nothing is committed for it. The recording shows how many were. */
static void covered() {
  ID3D11Query *e = g.query(D3D11_QUERY_EVENT);
  uint64_t early = 0;
  bool good = true;
  for (int n = 0; n < 8; n++) {
    g.burn(layers_40ms);
    g.ctx->End(e);
    g.ctx->Flush();
    const uint64_t begin = ns();
    BOOL there = FALSE;
    HRESULT hr = S_FALSE;
    unsigned draws = 0;
    g.use(0);
    while (hr == S_FALSE && ns() - begin < 4000000000ull) {
      g.rect(0, (draws * 7) % 200, (draws * 13) % 200, 20, 20, shade(draws));
      draws++;
      nap_us(100);
      hr = g.ctx->GetData(e, &there, sizeof(there), DONT);
      if (draws == 400) g.use(0);
    }
    const double ms = (ns() - begin) / 1e6;
    if (ms < 5) early++;
    good &= hr == S_OK && there;
    note("round %d: there after %.1f ms, %u draws recorded meanwhile", n, ms, draws);
    progress++;
  }
  check(good, "8 of 8 there");
  check(early <= 1, "the GPU was busy (%llu rounds under 5 ms)", (unsigned long long)early);
  /* (how many draws were recorded depends on the GPU: the picture is cleared so that its hash does not) */
  g.use(0);
  g.clear(0, shade(1));
  picture_good();
  e->Release();
}

/* Eight queries in one chunk that nothing submits, recorded slowly, all looked at: one rescue is all the chunk takes. */
static void one_rescue() {
  ID3D11Query *e[8];
  for (auto &q : e) q = g.query(D3D11_QUERY_EVENT);
  bool good = true;
  for (int round = 0; round < 4; round++) {
    g.use(0);
    for (int n = 0; n < 8; n++) {
      g.rect(0, n * 30, round * 30, 20, 20, shade(n + round * 8));
      g.ctx->End(e[n]);
    }
    for (int n = 0; n < 40; n++) {
      BOOL there;
      for (auto q : e) g.ctx->GetData(q, &there, sizeof(there), DONT);
      g.rect(0, 100 + n, 130 + round * 10, 5, 5, shade(n));
      nap_us(300);
    }
    for (auto q : e) good &= look_event(q, DONT).hr == S_OK;
  }
  check(good, "32 of 32 there");
  picture_good();
  for (auto q : e) q->Release();
}

/* One frame after another as an engine paces itself, several outstanding. */
static void pacing() {
  ID3D11Query *e[4];
  for (auto &q : e) q = g.query(D3D11_QUERY_EVENT);
  bool good = true;
  double worst = 0;
  for (int f = 0; f < 120; f++) {
    if (f >= 3) {
      Looked l = look_event(e[(f - 3) & 3], DONT, 4000, 100);
      good &= l.hr == S_OK;
      worst = std::max(worst, l.ms);
    }
    for (int n = 0; n < 20; n++) g.rect(n & 1, (f * 3 + n * 11) % 200, (n * 29) % 200, 30, 30, shade(f + n));
    g.burn(layers_40ms / 10);
    g.ctx->End(e[f & 3]);
    if (f % 10 == 9) g.ctx->Flush();
  }
  for (int f = 117; f < 120; f++) good &= look_event(e[f & 3], DONT).hr == S_OK;
  check(good, "120 of 120 there (the longest wait %.1f ms)", worst);
  picture_good();
  for (auto q : e) q->Release();
}

/* Queries ended again before they were read, read after, let go of unread. */
static void reuse() {
  ID3D11Query *e = g.query(D3D11_QUERY_EVENT);
  for (int n = 0; n < 500; n++) {
    g.rect(0, n % 200, (n * 7) % 200, 11, 11, shade(n));
    g.ctx->End(e);
    BOOL there;
    if (n % 5 == 0) g.ctx->GetData(e, &there, sizeof(there), DONT);
    if (n % 50 == 49) g.ctx->Flush();
  }
  Looked l = look_event(e, DONT);
  check(l.hr == S_OK, "ended 500 times, then read: there (%.1f ms)", l.ms);
  bool good = true;
  for (int n = 0; n < 60; n++) { /* the look is at this End: what came before it must be there, what it follows is the GPU's 4 ms */
    g.burn(layers_40ms / 10);
    g.ctx->End(e);
    l = look_event(e, n & 1 ? DONT : 0);
    good &= l.hr == S_OK;
  }
  check(good, "read and ended again 60 times: there");
  for (int n = 0; n < 200; n++) {
    ID3D11Query *q = g.query(n & 1 ? D3D11_QUERY_EVENT : D3D11_QUERY_TIMESTAMP_DISJOINT);
    g.rect(1, n % 200, (n * 3) % 200, 7, 7, shade(n));
    g.ctx->End(q);
    if (n % 3 == 0) { char b[16]; g.ctx->GetData(q, b, q->GetDataSize(), DONT); }
    q->Release();
  }
  g.ctx->End(e);
  check(look_event(e, DONT).hr == S_OK, "200 queries let go of unread, then one read: there");
  picture_good();
  e->Release();
}

/* Command lists. */
static void deferred() {
  ID3D11DeviceContext *dc;
  HR(g.dev->CreateDeferredContext(0, &dc));
  ID3D11Query *e = g.query(D3D11_QUERY_EVENT), *t = g.query(D3D11_QUERY_TIMESTAMP), *o = g.query(D3D11_QUERY_OCCLUSION),
              *now = g.query(D3D11_QUERY_EVENT);
  for (int round = 0; round < 6; round++) {
    Gpu::use_on(dc, g.picture[0]);
    dc->Begin(o);
    g.rect_on(dc, 3, 5, 40 + round, 50, shade(round));
    g.rect_on(dc, 60, 5, 10, 10, shade(round + 1), false);
    dc->End(o);
    g.rect_on(dc, 100, 100, 20, 20, shade(round + 2));
    dc->End(e);
    dc->End(t);
    ID3D11CommandList *list;
    HR(dc->FinishCommandList(round & 1, &list));
    BOOL there = FALSE;
    HRESULT before = g.ctx->GetData(e, &there, sizeof(there), DONT);
    if (round == 0) note("GetData before any execution: 0x%08lx", (unsigned long)before);
    for (int again = 0; again <= (round % 3 == 2); again++) {
      g.ctx->ExecuteCommandList(list, round & 1);
      g.target = -1;
      g.drawn(0, 3, 5, 40 + round, 50, shade(round));
      g.drawn(0, 100, 100, 20, 20, shade(round + 2));
      g.rect(1, 10 * round, 10, 8, 8, shade(round + 20 + again));
      g.ctx->End(now);
    }
    list->Release();
    Looked l = look_event(now, DONT);
    check(l.hr == S_OK, "round %d: a query of the immediate context after the list: there (%.1f ms)", round, l.ms);
    l = look_event(e, round & 2 ? 0 : DONT);
    check(l.hr == S_OK, "the list's event: there (%.1f ms)", l.ms);
    UINT64 samples = ~0ull, stamp = 0;
    l = look(g.ctx, o, 0, &samples, sizeof(samples));
    check(l.hr == S_OK && samples == (UINT64)(40 + round) * 50, "the list's occlusion query: %llu of %u samples (%.1f ms)", (unsigned long long)samples,
          (40 + round) * 50, l.ms);
    l = look(g.ctx, t, 0, &stamp, sizeof(stamp));
    check(l.hr == S_OK && stamp, "the list's timestamp: there (%.1f ms)", l.ms);
    /* not executed: nothing of it is ever there, and it keeps nothing else back */
    Gpu::use_on(dc, g.picture[0]);
    g.rect_on(dc, 0, 0, 10, 10, shade(99));
    dc->End(now);
    HR(dc->FinishCommandList(FALSE, &list));
    list->Release();
  }
  HRESULT hr = dc->GetData(e, nullptr, 0, 0);
  note("GetData of a deferred context: 0x%08lx", (unsigned long)hr);
  picture_good();
  dc->Release(); e->Release(); t->Release(); o->Release(); now->Release();
}

/* What an event or disjoint query ended in a command list is promised: there only once what comes before its End in the list is done,
 * at each execution. Without the switch it is ended as the list begins to be executed, so early (KNOWN: not touched). */
static void early_or(bool good, const char *format, ...) {
  char text[300];
  va_list a;
  va_start(a, format);
  vsnprintf(text, sizeof(text), format, a);
  va_end(a);
  if (good || once) check(good, "%s", text);
  else say("CHECK %s %s: KNOWN (without the switch a list's event is ended before the list)\n", current, text);
}
/* When each of the two is there, in ms, by looks with DONOTFLUSH and nothing else. */
static bool both_there(ID3D11Query *a, ID3D11Query *b, double &at, double &bt) {
  const uint64_t begin = ns();
  at = bt = -1;
  while ((at < 0 || bt < 0) && ns() - begin < 6000000000ull) {
    alignas(8) char data[16];
    if (at < 0 && g.ctx->GetData(a, data, a->GetDataSize(), DONT) == S_OK) at = (ns() - begin) / 1e6;
    if (bt < 0 && g.ctx->GetData(b, data, b->GetDataSize(), DONT) == S_OK) bt = (ns() - begin) / 1e6;
    nap_us(50);
  }
  progress++;
  return at >= 0 && bt >= 0;
}
/* A list's query whose End comes last, beside one of the immediate context ended right after the list: no earlier than it, but for what
 * GPU clocks and looks make of it. */
static bool not_before_its_work(double at, double after) { return at > after * 0.65 - 5; }
static void list_events() {
  ID3D11DeviceContext *dc;
  HR(g.dev->CreateDeferredContext(0, &dc));
  ID3D11Query *e = g.query(D3D11_QUERY_EVENT), *f = g.query(D3D11_QUERY_EVENT), *d = g.query(D3D11_QUERY_TIMESTAMP_DISJOINT), *after = g.query(D3D11_QUERY_EVENT);
  g.make_big();
  auto clean = [] { /* nothing new on the immediate context, and all of it done */
    ID3D11Query *q = g.query(D3D11_QUERY_EVENT);
    g.ctx->End(q);
    look_event(q, 0);
    q->Release();
  };
  auto list_of = [&] { ID3D11CommandList *l; HR(dc->FinishCommandList(FALSE, &l)); return l; };
  double te, ta;
  for (int round = 0; round < 4; round++) { /* its End follows 120 ms of GPU work in the list */
    ID3D11Query *q = round & 1 ? d : e;
    clean();
    if (round & 2) g.rect(1, round * 9, 3, 7, 7, shade(round)); /* something new on the immediate context, or nothing */
    if (q == d) dc->Begin(d);
    g.burn_on(dc, layers_40ms * 3);
    dc->End(q);
    ID3D11CommandList *list = list_of();
    g.ctx->ExecuteCommandList(list, FALSE);
    g.target = -1;
    list->Release();
    g.rect(1, round * 9, 30, 7, 7, shade(round + 40));
    g.ctx->End(after);
    const bool there = both_there(q, after, te, ta);
    check(there, "round %d: both there", round);
    early_or(there && not_before_its_work(te, ta), "round %d: the list's %s after its work (%.1f ms; the list's work and what follows it %.1f ms)", round, q == d ? "disjoint query" : "event", te, ta);
  }
  for (int round = 0; round < 3; round++) { /* two in one list, most of the work between them */
    clean();
    Gpu::use_on(dc, g.picture[0]);
    g.rect_on(dc, 3, 3 + round, 20, 20, shade(round + 7));
    dc->End(e);
    g.burn_on(dc, layers_40ms * 3);
    dc->End(f);
    ID3D11CommandList *list = list_of();
    g.ctx->ExecuteCommandList(list, round & 1);
    g.target = -1;
    g.drawn(0, 3, 3 + round, 20, 20, shade(round + 7));
    list->Release();
    g.ctx->End(after);
    double tl;
    const uint64_t begin = ns();
    const bool there = both_there(e, f, te, ta) && look_event(after, DONT).hr == S_OK;
    tl = (ns() - begin) / 1e6;
    check(there && te <= ta, "two in a list: the first %.1f ms, the second %.1f ms: in order", te, ta);
    early_or(there && not_before_its_work(ta, tl), "two in a list: the second after the work between them (%.1f of %.1f ms)", ta, tl);
    if (once && native) check(te < ta * 0.5, "two in a list: the first does not wait for the work after it (%.1f of %.1f ms)", te, ta);
  }
  { /* one list, executed again and again, the same query: of each execution */
    g.burn_on(dc, layers_40ms);
    Gpu::use_on(dc, g.picture[0]);
    g.rect_on(dc, 200, 10, 20, 20, shade(5));
    dc->End(e);
    ID3D11CommandList *list = list_of();
    for (int n = 0; n < 5; n++) {
      clean();
      g.ctx->ExecuteCommandList(list, n & 1);
      g.target = -1;
      g.drawn(0, 200, 10, 20, 20, shade(5));
      g.ctx->End(after);
      check(both_there(e, after, te, ta), "execution %d: there (%.1f ms)", n, te);
      early_or(not_before_its_work(te, ta), "execution %d: after its work (%.1f of %.1f ms)", n, te, ta);
    }
    clean(); /* twice in a row, and the query is the last one's */
    g.ctx->ExecuteCommandList(list, FALSE);
    g.ctx->ExecuteCommandList(list, FALSE);
    g.target = -1;
    g.ctx->End(after);
    const bool there = both_there(e, after, te, ta);
    early_or(there && not_before_its_work(te, ta), "executed twice in a row: after the second (%.1f of %.1f ms)", te, ta);
    g.rect(0, 220, 40, 9, 9, shade(9));
    g.ctx->End(e); /* then ended by the immediate context */
    Looked l = look_event(e, DONT);
    check(l.hr == S_OK, "then ended on the immediate context: there (%.1f ms)", l.ms);
    list->Release();
  }
  { /* ended twice in one list: the last End's */
    clean();
    Gpu::use_on(dc, g.picture[0]);
    g.rect_on(dc, 5, 200, 9, 9, shade(21));
    dc->End(e);
    g.burn_on(dc, layers_40ms * 2);
    dc->End(e);
    ID3D11CommandList *list = list_of();
    g.ctx->ExecuteCommandList(list, FALSE);
    g.target = -1;
    g.drawn(0, 5, 200, 9, 9, shade(21));
    list->Release();
    g.ctx->End(after);
    const bool there = both_there(e, after, te, ta);
    early_or(there && not_before_its_work(te, ta), "ended twice in a list: at the last (%.1f of %.1f ms)", te, ta);
  }
  if (g.ctx4) { /* held by a GPU wait before the list: not there until it is let go, whatever is looked at */
    Gpu other;
    other.make();
    ID3D11Device5 *dev5 = nullptr;
    ID3D11Fence *fence = nullptr;
    if (SUCCEEDED(other.dev->QueryInterface(__uuidof(ID3D11Device5), (void **)&dev5)) &&
        SUCCEEDED(dev5->CreateFence(0, D3D11_FENCE_FLAG_NONE, __uuidof(ID3D11Fence), (void **)&fence)))
      for (UINT64 v = 1; v <= 3; v++) {
        clean();
        Gpu::use_on(dc, g.picture[0]);
        g.rect_on(dc, (int)v * 20, 220, 9, 9, shade((unsigned)v + 60));
        dc->End(e);
        ID3D11CommandList *list = list_of();
        if (FAILED(g.ctx4->Wait(fence, v))) { list->Release(); say("CHECK list-events Wait: UNSUPPORTED\n"); break; }
        g.ctx->ExecuteCommandList(list, FALSE);
        g.target = -1;
        g.drawn(0, (int)v * 20, 220, 9, 9, shade((unsigned)v + 60));
        list->Release();
        if (v & 1) g.ctx->Flush();
        Looked l = look_event(e, DONT, 120);
        check(l.hr == S_FALSE, "held by a wait before the list: not there (%llu looks)", (unsigned long long)l.looks);
        HR(other.ctx4->Signal(fence, v));
        other.ctx->Flush();
        l = look_event(e, DONT);
        check(l.hr == S_OK, "let go: there (%.1f ms)", l.ms);
      }
    if (fence) fence->Release();
    if (dev5) dev5->Release();
    other.drop();
  }
  { /* hundreds of lists, each with a query of its own, looked at in any order */
    ID3D11Query *many[40];
    bool good = true;
    for (auto &q : many) q = g.query(D3D11_QUERY_EVENT);
    for (int n = 0; n < 400; n++) {
      const int k = n % 40;
      if (n >= 40) good &= look_event(many[(k + 7) % 40], DONT).hr == S_OK;
      Gpu::use_on(dc, g.picture[n & 1]);
      g.rect_on(dc, n % 200, (n * 7) % 200, 5, 5, shade(n));
      dc->End(many[k]);
      ID3D11CommandList *list = list_of();
      g.ctx->ExecuteCommandList(list, n & 2);
      g.target = -1;
      g.drawn(n & 1, n % 200, (n * 7) % 200, 5, 5, shade(n));
      list->Release();
    }
    for (auto q : many) { good &= look_event(q, DONT).hr == S_OK; q->Release(); }
    check(good, "400 lists with a query each: there");
  }
  picture_good();
  dc->Release(); e->Release(); f->Release(); d->Release(); after->Release();
}

/* Textures made with their data on another thread, all the time, while the GPU is busy and this thread ends events and only looks: how
 * long a look takes (the uploads have a queue of two command buffers of their own, which a commit may wait for), without the device's lock
 * and with it. */
static void uploads_of(bool locked, D3D11_USAGE small = D3D11_USAGE_DEFAULT) { /* small: of the textures that are drawn */
  ID3D11Multithread *mt = nullptr;
  if (locked && FAILED(g.ctx->QueryInterface(__uuidof(ID3D11Multithread), (void **)&mt))) return;
  if (mt) mt->SetMultithreadProtected(TRUE);
  const char *how = locked ? "the device's lock on" : "the device's lock off";
  std::atomic<bool> stop{false};
  std::atomic<uint64_t> made{0}, ahead{0}; /* at most 1 GiB made since the last event was there: the Mac's memory is not what is asked */
  std::vector<uint8_t> data(4096 * 4096 * 4, 0x55);
  std::thread uploader([&] {
    for (unsigned n = 0; !stop; n++) {
      const UINT px = n % 16 == 7 ? 4096 : n % 4 == 1 ? 2048 : 512;
      D3D11_TEXTURE2D_DESC d = {px, px, 1, 1, DXGI_FORMAT_R8G8B8A8_UNORM, {1, 0}, D3D11_USAGE_DEFAULT, D3D11_BIND_SHADER_RESOURCE, 0, 0};
      D3D11_SUBRESOURCE_DATA init = {data.data(), px * 4, 0};
      ID3D11Texture2D *t;
      HR(g.dev->CreateTexture2D(&d, &init, &t));
      t->Release();
      made++;
      nap_us(300);
      ahead += px * px * 4;
      while (!stop && ahead > 1ull << 30) nap_us(500);
    }
  });
  ID3D11Query *e = g.query(D3D11_QUERY_EVENT);
  std::vector<uint64_t> took, waits, rescues;
  unsigned slow_first = 0, slow_rescue = 0;
  bool good = true;
  for (int n = 0; n < 60; n++) {
    g.rect(0, n * 3, n * 2 + locked, 20, 20, shade(n));
    g.burn(layers_40ms / 2);
    for (int k = 0; k < 8; k++) g.fresh_rect(1, k * 30, n * 4 + locked, 20, 3, shade(n * 8 + k + locked), small); /* (its upload is of the chunk that only the looks commit) */
    g.ctx->End(e);
    const uint64_t began = ns();
    HRESULT hr = S_FALSE;
    BOOL there;
    for (unsigned n_look = 1; hr == S_FALSE && ns() - began < 6000000000ull; n_look++) {
      const uint64_t a = ns();
      hr = g.ctx->GetData(e, &there, sizeof(there), DONT);
      took.push_back(ns() - a);
      if (took.back() >= 500000) { slow_first += n_look <= 64; slow_rescue += n_look == 65; }
      if (n_look == 65) rescues.push_back(took.back());
      nap_us(60);
    }
    good &= hr == S_OK;
    waits.push_back(ns() - began);
    ahead = 0;
    progress++;
  }
  stop = true;
  uploader.join();
  std::sort(waits.begin(), waits.end());
  check(good, "%s: 60 of 60 there beside %llu textures made", how, (unsigned long long)made.load());
  check(waits.back() < 2000000000, "%s: each within two seconds", how);
  note("%s: an event was there after %.1f ms (p50), %.1f (p95), %.1f (the longest)", how, waits[30] / 1e6, waits[57] / 1e6, waits.back() / 1e6);
  std::sort(took.begin(), took.end());
  const double worst = took.back() / 1e6, p99 = took[took.size() * 99 / 100] / 1e6;
  const size_t slow = took.end() - std::lower_bound(took.begin(), took.end(), 500000);
  note("%s: a look: the longest %.3f ms, p99.9 %.3f, p99 %.3f, p50 %.4f ms of %zu; %zu of 0.5 ms or more (%u among the first 64, %u the 65th)", how, worst, took[took.size() * 999 / 1000] / 1e6, p99,
       took[took.size() / 2] / 1e6, took.size(), slow, slow_first, slow_rescue);
  std::sort(rescues.begin(), rescues.end());
  if (!rescues.empty()) note("%s: the 65th look: p50 %.4f ms, the longest %.3f ms of %zu", how, rescues[rescues.size() / 2] / 1e6, rescues.back() / 1e6, rescues.size());
  /* The 65th is the one that commits. (A look that does nothing may take long where this thread lost its core: macOS's, on a busy Mac.) */
  if (once && native) {
    const size_t slow_rescues = rescues.end() - std::lower_bound(rescues.begin(), rescues.end(), 500000);
    check(slow_rescues <= 1 && slow <= 8 && worst < 25, "%s: no look waited for an upload (%zu of the %zu that committed took 0.5 ms or more, the longest %.3f ms)", how,
          slow_rescues, rescues.size(), rescues.empty() ? 0 : rescues.back() / 1e6);
  }
  if (mt) { mt->Enter(); mt->Leave(); mt->SetMultithreadProtected(FALSE); mt->Release(); }
  e->Release();
}
static void uploads() {
  uploads_of(false);
  picture_good("the textures' uploads were seen");
  uploads_of(true);
  picture_good("the textures' uploads were seen");
  /* Textures that are immutable. Neptune's host makes them without their data and updates them, which DXMT takes for something that cannot
   * happen: an immutable texture's update and the draws that read it are not put in order (with the switch and without: not touched). */
  ID3D11Query *e = g.query(D3D11_QUERY_EVENT);
  for (int n = 0; n < 60; n++) {
    g.burn(layers_40ms / 4);
    for (int k = 0; k < 8; k++) g.fresh_rect(1, k * 30, n * 4, 20, 3, shade(n * 8 + k + 2), D3D11_USAGE_IMMUTABLE);
    g.ctx->End(e);
    look_event(e, DONT, 4000, 60);
  }
  e->Release();
  uint32_t crc;
  const unsigned bad = g.differs(1, &crc);
  if (bad && !native && !ordered) {
    say("CHECK uploads of immutable textures: %u pixels drawn before their texture's data: KNOWN (Neptune and DXMT, with the switch and without)\n", bad);
    g.use(1);
    g.clear(1, shade(2));
  } else {
    check(!bad, "immutable textures: their data were seen (%u pixels differ)", bad);
  }
}

/* Resources that are immutable, made with their data and read at once: what is drawn is their data, and nothing that was there before. Natively the data
 * come with the resource; through Neptune they are an update that follows it, which without OBELISK_DXMT_INIT_ORDER=1 is in no order with the draws
 * that read it (told, KNOWN: the number is what is compared). Beside another thread that makes and fills textures all the time. */
struct Immutable { /* a texture of one colour, immutable */
  ID3D11Texture2D *t = nullptr;
  ID3D11ShaderResourceView *v = nullptr;
  void make(Colour k, UINT px, UINT mips, D3D11_USAGE usage) {
    std::vector<uint8_t> data(px * px * 4);
    for (size_t n = 0; n < data.size(); n++) data[n] = k.v[n & 3];
    D3D11_TEXTURE2D_DESC d = {px, px, mips, 1, DXGI_FORMAT_R8G8B8A8_UNORM, {1, 0}, usage, D3D11_BIND_SHADER_RESOURCE, 0, 0};
    std::vector<D3D11_SUBRESOURCE_DATA> init(mips);
    for (UINT m = 0; m < mips; m++) init[m] = {data.data(), std::max(1u, px >> m) * 4, 0};
    HR(g.dev->CreateTexture2D(&d, immutable_as_host ? nullptr : init.data(), &t));
    for (UINT m = 0; immutable_as_host && m < mips; m++) g.ctx->UpdateSubresource(t, m, nullptr, init[m].pSysMem, init[m].SysMemPitch, 0);
    HR(g.dev->CreateShaderResourceView(t, nullptr, &v));
  }
  void draw(int x, int y, int w, int h) { /* on whatever the target is */
    D3D11_VIEWPORT vp = {(float)x, (float)y, (float)w, (float)h, 0, 1};
    UINT stride = sizeof(Vertex), off = 0;
    g.ctx->RSSetViewports(1, &vp);
    g.ctx->IASetVertexBuffers(0, 1, &g.vb, &stride, &off);
    g.ctx->IASetInputLayout(g.layout);
    g.ctx->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    g.ctx->VSSetShader(g.vs, nullptr, 0);
    g.ctx->PSSetShader(g.ps_tex, nullptr, 0);
    g.ctx->PSSetSamplers(0, 1, &g.sampler);
    g.ctx->PSSetShaderResources(0, 1, &v);
    g.ctx->OMSetBlendState(nullptr, nullptr, ~0u);
    g.ctx->OMSetDepthStencilState(g.pass, 0);
    g.ctx->Draw(3, 0);
  }
  void drop() { if (v) v->Release(); if (t) t->Release(); *this = {}; }
};
static void told(const char *what, int i) {
  const unsigned bad = g.differs(i, nullptr);
  note("COUNT %s: %u pixels differ", what, bad);
  if (bad && (!native || immutable_as_host) && !ordered) {
    say("CHECK immutables %s: %u pixels drawn before the data: KNOWN (Neptune and DXMT, as released)\n", what, bad);
  } else {
    check(!bad, "%s: the data were seen (%u pixels differ)", what, bad);
  }
  g.use(i);
  g.clear(i, {{0, 0, 0, 255}});
}
static void immutables_of() {
  for (int locked = 0; locked < 2; locked++) { /* (uploads()'s own streaming, its small textures immutable) */
    uploads_of(locked, D3D11_USAGE_IMMUTABLE);
    told(locked ? "streamed, the device's lock on" : "streamed", 1);
  }
  ID3D11Multithread *mt = nullptr; /* (as the host's: another thread updates what it makes) */
  if (immutable_as_host) { HR(g.ctx->QueryInterface(__uuidof(ID3D11Multithread), (void **)&mt)); mt->SetMultithreadProtected(TRUE); }
  ID3D11Query *e = g.query(D3D11_QUERY_EVENT);
  std::atomic<bool> stop{false};
  std::atomic<uint64_t> ahead{0};
  std::vector<uint8_t> bulk(4096 * 4096 * 4, 0x55);
  std::thread uploader([&] { /* a world that streams in */
    for (unsigned n = 0; !stop; n++) {
      const UINT px = n % 16 == 7 ? 4096 : n % 4 == 1 ? 2048 : 512;
      D3D11_TEXTURE2D_DESC d = {px, px, 1, 1, DXGI_FORMAT_R8G8B8A8_UNORM, {1, 0}, D3D11_USAGE_DEFAULT, D3D11_BIND_SHADER_RESOURCE, 0, 0};
      D3D11_SUBRESOURCE_DATA init = {bulk.data(), px * 4, 0};
      ID3D11Texture2D *t;
      HR(g.dev->CreateTexture2D(&d, &init, &t));
      t->Release();
      nap_us(300);
      ahead += px * px * 4;
      while (!stop && ahead > 1ull << 30) nap_us(500);
    }
  });
  auto frame_done = [&] { g.ctx->End(e); const HRESULT hr = look_event(e, DONT, 4000, 60).hr; if (hr != S_OK) check(false, "an event of it was there"); ahead = 0; progress++; };
  { /* first used in the middle of what is drawn already, of the same target; seen the next frame again */
    std::vector<Immutable> kept;
    for (int n = 0; n < 60; n++) {
      g.burn(layers_40ms / 4);
      g.rect(1, 0, n * 4, 8, 3, shade(n + 1));
      for (int k = 0; k < 6; k++) {
        Immutable m;
        m.make(shade(n * 8 + k + 3), 64, 7, D3D11_USAGE_IMMUTABLE);
        g.use(1);
        m.draw(10 + k * 30, n * 4, 20, 3);
        g.drawn(1, 10 + k * 30, n * 4, 20, 3, shade(n * 8 + k + 3));
        g.rect(1, 31 + k * 30, n * 4, 8, 3, shade(n + k));
        kept.push_back(m);
      }
      frame_done();
    }
    told("first used in a pass that draws", 1);
    g.use(1);
    for (size_t n = 0; n < kept.size(); n++) {
      g.use(1);
      kept[n].draw((int)(n % 24) * 10, (int)(n / 24) * 6, 8, 4);
      g.drawn(1, (int)(n % 24) * 10, (int)(n / 24) * 6, 8, 4, shade((unsigned)(n / 6) * 8 + n % 6 + 3));
    }
    frame_done();
    { /* (whatever was first seen of them, they are there now: in every arm) */
      const unsigned bad = g.differs(1, nullptr);
      check(!bad, "used again: the data were seen (%u pixels differ)", bad);
      g.use(1);
      g.clear(1, {{0, 0, 0, 255}});
    }
    for (auto &m : kept) m.drop();
  }
  { /* a target derived from the first use, which is kept: what it missed it misses as long as it is not drawn again */
    ID3D11Texture2D *atlas;
    ID3D11RenderTargetView *rtv;
    ID3D11ShaderResourceView *srv;
    D3D11_TEXTURE2D_DESC d = {PX, PX, 1, 1, DXGI_FORMAT_R8G8B8A8_UNORM, {1, 0}, D3D11_USAGE_DEFAULT, D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE, 0, 0};
    HR(g.dev->CreateTexture2D(&d, nullptr, &atlas));
    HR(g.dev->CreateRenderTargetView(atlas, nullptr, &rtv));
    HR(g.dev->CreateShaderResourceView(atlas, nullptr, &srv));
    const float black[4] = {0, 0, 0, 1};
    g.ctx->ClearRenderTargetView(rtv, black);
    for (int n = 0; n < 60; n++) {
      g.burn(layers_40ms / 4);
      g.ctx->OMSetRenderTargets(1, &rtv, nullptr);
      g.target = -1;
      for (int k = 0; k < 8; k++) {
        Immutable m;
        m.make(shade(n * 8 + k + 5), 32, 1, D3D11_USAGE_IMMUTABLE);
        m.draw(k * 30, n * 4, 20, 3);
        g.drawn(1, k * 30, n * 4, 20, 3, shade(n * 8 + k + 5));
        m.drop();
      }
      frame_done();
    }
    for (int n = 0; n < 8; n++) { g.burn(layers_40ms / 8); frame_done(); } /* (nothing of the sources is left, nothing is under way) */
    g.use(1);
    Immutable a;
    a.t = atlas; a.v = srv;
    a.draw(0, 0, PX, PX);
    told("a target derived from the first use, kept", 1);
    rtv->Release();
    a.drop();
  }
  { /* vertex buffers: a mesh that is missing */
    std::vector<uint8_t> pad(1 << 20);
    for (int n = 0; n < 60; n++) {
      g.burn(layers_40ms / 4);
      for (int k = 0; k < 8; k++) {
        const bool large = k == 7; /* the triangle at the end of a MiB */
        D3D11_BUFFER_DESC bd = {large ? (UINT)pad.size() : (UINT)sizeof(kFull), D3D11_USAGE_IMMUTABLE, D3D11_BIND_VERTEX_BUFFER, 0, 0, 0};
        memcpy(&pad[pad.size() / 32 * 32 - 32 * 3], kFull, sizeof(kFull));
        D3D11_SUBRESOURCE_DATA init = {large ? (const void *)pad.data() : kFull, 0, 0};
        ID3D11Buffer *vb;
        HR(g.dev->CreateBuffer(&bd, immutable_as_host ? nullptr : &init, &vb));
        if (immutable_as_host && large && (n & 1)) { /* in two parts */
          const D3D11_BOX first = {0, 0, 0, 1 << 19, 1, 1}, second = {1 << 19, 0, 0, 1 << 20, 1, 1};
          g.ctx->UpdateSubresource(vb, 0, &first, pad.data(), 0, 0);
          g.ctx->UpdateSubresource(vb, 0, &second, pad.data() + (1 << 19), 0, 0);
        } else if (immutable_as_host) {
          g.ctx->UpdateSubresource(vb, 0, nullptr, init.pSysMem, 0, 0);
        }
        g.use(1);
        g.rect_on(g.ctx, 0, 0, 0, 0, shade(n * 8 + k + 7), false); /* (its state, and the colour; nothing seen) */
        UINT stride = sizeof(Vertex), off = large ? (UINT)(pad.size() / 32 * 32 - 32 * 3) : 0;
        D3D11_VIEWPORT vp = {(float)(k * 30), (float)(n * 4), 20, 3, 0, 1};
        g.ctx->RSSetViewports(1, &vp);
        g.ctx->OMSetDepthStencilState(g.pass, 0);
        g.ctx->IASetVertexBuffers(0, 1, &vb, &stride, &off);
        g.ctx->Draw(3, 0);
        g.drawn(1, k * 30, n * 4, 20, 3, shade(n * 8 + k + 7));
        vb->Release();
      }
      frame_done();
    }
    told("vertex buffers", 1);
  }
  { /* made on another thread, handed over as soon as they are */
    for (int n = 0; n < 60; n++) {
      g.burn(layers_40ms / 4);
      Immutable m[8];
      std::atomic<int> ready{0};
      std::thread maker([&] { for (int k = 0; k < 8; k++) { m[k].make(shade(n * 8 + k + 9), 64, 1, D3D11_USAGE_IMMUTABLE); ready = k + 1; } });
      for (int k = 0; k < 8; k++) {
        while (ready <= k) std::this_thread::yield();
        g.use(1);
        m[k].draw(k * 30, n * 4, 20, 3);
        g.drawn(1, k * 30, n * 4, 20, 3, shade(n * 8 + k + 9));
      }
      maker.join();
      frame_done();
      for (auto &x : m) x.drop();
    }
    told("made on another thread", 1);
  }
  stop = true;
  uploader.join();
  if (mt) { mt->SetMultithreadProtected(FALSE); mt->Release(); }
  e->Release();
}

static void immutables() {
  immutables_of();
  if (!native) return;
  g.clear(0, {{0, 0, 0, 255}});
  immutable_as_host = true;
  note("as Neptune's host makes them");
  immutables_of();
  immutable_as_host = false;
}

/* An occlusion query whose draws are the last of their pass, and what is drawn after it on the same targets: exact counts. Its list executed once, twice,
 * beside another's, and in between what nobody counts. Without OBELISK_DXMT_INIT_ORDER=1 the passes are put together with the counting on (told, KNOWN). */
static void occlusion_join() {
  ID3D11DeviceContext *dc;
  HR(g.dev->CreateDeferredContext(0, &dc));
  ID3D11Query *a = g.query(D3D11_QUERY_OCCLUSION), *b = g.query(D3D11_QUERY_OCCLUSION);
  unsigned wrong = 0, rounds = 0;
  uint64_t over = 0;
  auto list = [&](ID3D11Query *q, int x, int w, int h, Colour k) {
    ID3D11CommandList *l;
    Gpu::use_on(dc, g.picture[0]);
    dc->Begin(q);
    g.rect_on(dc, x, 10, w, h, k);
    dc->End(q); /* (nothing is drawn after it in the list) */
    HR(dc->FinishCommandList(FALSE, &l));
    return l;
  };
  auto count = [&](ID3D11Query *q, uint64_t want, const char *what) {
    UINT64 got = ~0ull;
    const HRESULT hr = look(g.ctx, q, 0, &got, sizeof(got)).hr;
    rounds++;
    if (hr != S_OK || got != want) {
      wrong++;
      over += got > want ? got - want : 0;
      if (wrong <= 4) note("%s: 0x%08lx, %llu of %llu", what, (unsigned long)hr, (unsigned long long)got, (unsigned long long)want);
    }
  };
  /* In one list: the counted draws are the last of a pass, and another pass of the same targets follows that could be put together with it. */
  for (int n = 0; n < 200; n++) {
    const int w = 20 + n % 17, h = 10 + n % 11;
    const Colour k = shade(n);
    auto on = [&](int i) { Gpu::use_on(dc, g.picture[i]); };
    auto counted = [&](ID3D11Query *q, int x, int w, int h) { dc->Begin(q); g.rect_on(dc, x, 150, w, h, k); dc->End(q); };
    uint64_t want_a = (uint64_t)w * h, want_b = 0;
    on(0);
    switch (n % 5) {
    case 0: counted(a, 5, w, h); on(1); g.rect_on(dc, 5, 150, 30, 30, k); on(0); g.rect_on(dc, 100, 150, 40, 41, k); break;
    case 1: g.rect_on(dc, 150, 150, 9, 9, k); counted(a, 5, w, h); on(1); g.rect_on(dc, 5, 150, 30, 30, k); on(0); g.rect_on(dc, 100, 150, 40, 41, k); counted(b, 60, h, w); want_b = want_a; break;
    case 2: /* a query open across a target, ended there: the first pass ends counting, and the third is nobody's */
      dc->Begin(a); g.rect_on(dc, 5, 150, w, h, k); on(1); g.rect_on(dc, 5, 150, 7, 8, k); dc->End(a); want_a += 7 * 8;
      on(0); g.rect_on(dc, 100, 150, 40, 41, k);
      break;
    case 3: counted(a, 5, w, h); on(1); g.rect_on(dc, 5, 150, 30, 30, k); on(0); counted(b, 60, h, w); on(1); g.rect_on(dc, 50, 150, 30, 30, k); on(0); g.rect_on(dc, 100, 150, 40, 41, k); want_b = want_a; break;
    case 4: /* two open at once, one ended */
      dc->Begin(a); dc->Begin(b); g.rect_on(dc, 5, 150, w, h, k); dc->End(b); want_b = want_a; g.rect_on(dc, 60, 150, 11, 3, k); dc->End(a); want_a += 33;
      on(1); g.rect_on(dc, 5, 150, 30, 30, k); on(0); g.rect_on(dc, 100, 150, 40, 41, k);
      break;
    }
    ID3D11CommandList *l;
    HR(dc->FinishCommandList(FALSE, &l));
    g.ctx->ExecuteCommandList(l, FALSE);
    if (n % 7 == 3) g.ctx->ExecuteCommandList(l, FALSE); /* (again: what it counts is the same) */
    g.target = -1;
    const char *what[] = {"in a list: its target, another, its own", "in a list: the second query after", "in a list: open across a target", "in a list: twice, and nobody's", "in a list: two open"};
    count(a, want_a, what[n % 5]);
    if (want_b) count(b, want_b, what[n % 5]);
    l->Release();
    progress++;
  }
  for (int i = 0; i < 2; i++) { g.use(i); g.clear(i, {{0, 0, 0, 255}}); }
  for (int n = 0; n < 200; n++) {
    const int w = 20 + n % 17, h = 10 + n % 11;
    ID3D11CommandList *la = list(a, 5, w, h, shade(n)), *lb = list(b, 60, h, w, shade(n + 1));
    g.use(0);
    switch (n % 5) {
    case 0: /* the list, then draws of the same targets */
      g.ctx->ExecuteCommandList(la, FALSE);
      g.target = -1;
      g.rect(0, 100, 50, 40, 41, shade(n + 2));
      g.drawn(0, 5, 10, w, h, shade(n));
      count(a, (uint64_t)w * h, "a list, then draws");
      break;
    case 1: /* draws, the list, draws */
      g.rect(0, 100, 50, 40, 41, shade(n + 2));
      g.ctx->ExecuteCommandList(la, TRUE);
      g.rect(0, 100, 100, 40, 41, shade(n + 3));
      g.drawn(0, 5, 10, w, h, shade(n));
      count(a, (uint64_t)w * h, "draws, a list, draws");
      break;
    case 2: /* two lists, each with its own, and draws */
      g.ctx->ExecuteCommandList(la, FALSE);
      g.ctx->ExecuteCommandList(lb, FALSE);
      g.target = -1;
      g.rect(0, 100, 50, 40, 41, shade(n + 2));
      g.drawn(0, 5, 10, w, h, shade(n));
      g.drawn(0, 60, 10, h, w, shade(n + 1));
      count(a, (uint64_t)w * h, "two lists, the first");
      count(b, (uint64_t)w * h, "two lists, the second");
      break;
    case 3: /* the same list twice: the second execution's count */
      g.ctx->ExecuteCommandList(la, FALSE);
      g.ctx->ExecuteCommandList(la, FALSE);
      g.target = -1;
      g.rect(0, 100, 50, 40, 41, shade(n + 2));
      g.drawn(0, 5, 10, w, h, shade(n));
      count(a, (uint64_t)w * h, "a list twice");
      break;
    case 4: /* the immediate context's own: its last draws counted, then another target, then the first again */
      g.ctx->Begin(a);
      g.rect(0, 5, 10, w, h, shade(n));
      g.ctx->End(a);
      g.rect(1, 5, 10, 30, 30, shade(n + 5));
      g.rect(0, 100, 50, 40, 41, shade(n + 2));
      count(a, (uint64_t)w * h, "its own, another target, the first");
      break;
    }
    la->Release();
    lb->Release();
    progress++;
  }
  note("COUNT occlusion: %u of %u wrong, %llu samples too many", wrong, rounds, (unsigned long long)over);
  if (wrong && !ordered) {
    say("CHECK occlusion-join %u of %u counts wrong: KNOWN (passes put together with the counting on, as released)\n", wrong, rounds);
  } else {
    check(!wrong, "%u counts, each exact (%u wrong)", rounds, wrong);
  }
  picture_good();
  a->Release(); b->Release(); dc->Release();
}

/* Exact counts, no draws, hidden draws, across target changes and chunks; predicates. */
static void occlusion() {
  ID3D11Query *o = g.query(D3D11_QUERY_OCCLUSION), *p = g.query(D3D11_QUERY_OCCLUSION_PREDICATE), *e = g.query(D3D11_QUERY_EVENT);
  ID3D11Texture2D *ms, *ms_ds;
  ID3D11RenderTargetView *ms_rtv;
  ID3D11DepthStencilView *ms_dsv;
  D3D11_TEXTURE2D_DESC d = {PX, PX, 1, 1, DXGI_FORMAT_R8G8B8A8_UNORM, {2, 0}, D3D11_USAGE_DEFAULT, D3D11_BIND_RENDER_TARGET, 0, 0};
  HR(g.dev->CreateTexture2D(&d, nullptr, &ms));
  HR(g.dev->CreateRenderTargetView(ms, nullptr, &ms_rtv));
  d.Format = DXGI_FORMAT_D24_UNORM_S8_UINT; d.BindFlags = D3D11_BIND_DEPTH_STENCIL;
  HR(g.dev->CreateTexture2D(&d, nullptr, &ms_ds));
  HR(g.dev->CreateDepthStencilView(ms_ds, nullptr, &ms_dsv));
  for (int round = 0; round < 12; round++) {
    UINT64 want = 0, got = ~0ull;
    const char *what = "";
    g.use(0);
    g.ctx->Begin(o);
    switch (round % 6) {
    case 0: what = "nothing drawn"; break;
    case 1: what = "drawn"; g.rect(0, 10, 10, 60, 31, shade(round)); want = 60 * 31; break;
    case 2: what = "hidden"; g.rect(0, 10, 10, 60, 31, shade(round), false); break;
    case 3:
      what = "across a target change";
      g.rect(0, 10, 50, 20, 20, shade(round));
      g.rect(1, 10, 50, 33, 20, shade(round + 1));
      g.rect(0, 10, 90, 10, 20, shade(round + 2));
      want = 20 * 20 + 33 * 20 + 10 * 20;
      break;
    case 4:
      what = "across a Flush and an event";
      g.rect(0, 100, 10, 20, 20, shade(round));
      g.ctx->Flush();
      g.rect(0, 130, 10, 20, 21, shade(round + 1), false);
      g.ctx->End(e);
      g.rect(0, 160, 10, 20, 22, shade(round + 2));
      want = 20 * 20 + 20 * 22;
      break;
    case 5:
      what = "2x";
      g.ctx->OMSetRenderTargets(1, &ms_rtv, ms_dsv);
      g.target = -1;
      g.ctx->ClearDepthStencilView(ms_dsv, D3D11_CLEAR_DEPTH, 1, 0);
      g.rect_on(g.ctx, 5, 5, 40, 41, shade(round));
      want = 2 * 40 * 41;
      break;
    }
    g.ctx->End(o);
    Looked l;
    if (round >= 6) { /* looked at without flushing for a while first */
      l = look(g.ctx, o, DONT, &got, sizeof(got), 20);
      if (l.hr == S_FALSE) l = look(g.ctx, o, 0, &got, sizeof(got));
    } else {
      l = look(g.ctx, o, 0, &got, sizeof(got));
    }
    check(l.hr == S_OK && got == want, "%s: %llu of %llu samples (%.1f ms)", what, (unsigned long long)got, (unsigned long long)want, l.ms);
    g.use(0);
    g.ctx->Begin(p);
    if (round & 1) g.rect(0, 200, 200, 3, 3, shade(round), round & 2);
    g.ctx->End(p);
    BOOL seen = 2;
    l = look(g.ctx, p, 0, &seen, sizeof(seen));
    check(l.hr == S_OK && seen == ((round & 3) == 3), "predicate: %d", (int)seen);
  }
  /* many at once, read later */
  ID3D11Query *many[32];
  for (int n = 0; n < 32; n++) {
    many[n] = g.query(D3D11_QUERY_OCCLUSION);
    g.ctx->Begin(many[n]);
    g.rect(n & 1, n * 4, n * 3, n + 1, 5, shade(n), n % 4 != 3);
    g.ctx->End(many[n]);
  }
  bool good = true;
  for (int n = 31; n >= 0; n--) {
    UINT64 got = ~0ull;
    good &= look(g.ctx, many[n], 0, &got, sizeof(got)).hr == S_OK && got == (n % 4 != 3 ? (UINT64)(n + 1) * 5 : 0);
    many[n]->Release();
  }
  check(good, "32 in one chunk: every count");
  picture_good();
  for (IUnknown *u : std::initializer_list<IUnknown *>{o, p, e, ms, ms_ds, ms_rtv, ms_dsv}) u->Release();
}

/* Four timestamps in order inside a disjoint pair that says nothing was disjoint. */
static void timestamps() {
  ID3D11Query *d = g.query(D3D11_QUERY_TIMESTAMP_DISJOINT), *t[4];
  for (auto &q : t) q = g.query(D3D11_QUERY_TIMESTAMP);
  for (int round = 0; round < 6; round++) {
    const uint64_t began = ns();
    g.ctx->Begin(d);
    for (int n = 0; n < 4; n++) {
      if (n) { g.rect(0, n * 20, round * 20, 10, 10, shade(n + round)); g.burn(layers_40ms / 8); }
      g.ctx->End(t[n]);
    }
    g.ctx->End(d);
    UINT64 v[4] = {};
    D3D11_QUERY_DATA_TIMESTAMP_DISJOINT data = {0, TRUE};
    bool there = look(g.ctx, d, round & 1 ? DONT : 0, &data, sizeof(data)).hr == S_OK;
    for (int n = 0; n < 4; n++) there &= look(g.ctx, t[n], 0, &v[n], 8).hr == S_OK;
    const double wall = (ns() - began) / 1e6;
    check(there && data.Frequency == 1000000000 && !data.Disjoint && v[0] <= v[1] && v[1] <= v[2] && v[2] <= v[3], "there, in order, %llu Hz, disjoint %d",
          (unsigned long long)data.Frequency, (int)data.Disjoint);
    check((v[3] - v[0]) / 1e6 <= wall + 1, "they span no more than the wall clock");
    note("they span %.1f ms of %.1f", (v[3] - v[0]) / 1e6, wall);
  }
  picture_good();
  d->Release();
  for (auto q : t) q->Release();
}

/* Copies to staging, mapped with and without waiting, between queries. */
static void readback() {
  ID3D11Query *e = g.query(D3D11_QUERY_EVENT);
  bool good = true, waited = false;
  for (int n = 0; n < 30; n++) {
    g.rect(0, 0, 0, PX, PX, shade(n));
    if (n % 3 == 0) g.burn(layers_40ms / 4);
    g.ctx->CopyResource(g.picture[0].staging, g.picture[0].tex);
    g.ctx->End(e);
    g.rect(1, n, n, 30, 30, shade(n)); /* recorded after */
    D3D11_MAPPED_SUBRESOURCE m;
    HRESULT hr = DXGI_ERROR_WAS_STILL_DRAWING;
    if (n & 1) {
      BOOL there;
      const uint64_t begin = ns();
      while (hr == DXGI_ERROR_WAS_STILL_DRAWING && ns() - begin < 4000000000ull) {
        g.ctx->GetData(e, &there, sizeof(there), DONT);
        hr = g.ctx->Map(g.picture[0].staging, 0, D3D11_MAP_READ, D3D11_MAP_FLAG_DO_NOT_WAIT, &m);
        waited |= hr == DXGI_ERROR_WAS_STILL_DRAWING;
        nap_us(50);
      }
    } else {
      hr = g.ctx->Map(g.picture[0].staging, 0, D3D11_MAP_READ, 0, &m);
    }
    if (hr == S_OK) {
      Colour k = shade(n);
      for (int y = 0; y < PX; y += 51) good &= !memcmp((uint8_t *)m.pData + y * m.RowPitch + y * 4, k.v, 4);
      g.ctx->Unmap(g.picture[0].staging, 0);
    } else {
      good = false;
    }
    good &= look_event(e, DONT).hr == S_OK;
  }
  check(good, "30 of 30 hold what was copied, and their queries are there (some had to wait: %s)", waited ? "yes" : "no");
  picture_good();
  e->Release();
}

/* SetPredication: what this stack does of it, the same in both arms (DXMT draws whatever the predicate says). */
static void predication() {
  ID3D11Predicate *p;
  D3D11_QUERY_DESC d = {D3D11_QUERY_OCCLUSION_PREDICATE, 0};
  HRESULT hr = g.dev->CreatePredicate(&d, &p);
  if (FAILED(hr)) { say("CHECK predication CreatePredicate 0x%08lx: UNSUPPORTED\n", (unsigned long)hr); return; }
  uint32_t crc;
  for (int seen = 0; seen < 2; seen++)
    for (int value = 0; value < 2; value++) {
      g.use(0);
      g.ctx->Begin(p);
      g.rect(0, 0, 0, 10, 10, shade(3), seen);
      g.ctx->End(p);
      const int at = 20 + (seen * 2 + value) * 40;
      g.ctx->SetPredication(p, value);
      g.rect_on(g.ctx, at, 100, 20, 20, shade(40 + at));
      g.ctx->SetPredication(nullptr, FALSE);
      const bool drawn = seen != value; /* D3D11: skipped when the predicate's result is the value */
      BOOL got = 2;
      look(g.ctx, p, 0, &got, sizeof(got));
      check(got == seen, "the predicate's own result: %d", (int)got);
      std::vector<uint8_t> before = g.picture[0].model;
      if (drawn) g.drawn(0, at, 100, 20, 20, shade(40 + at));
      unsigned bad = g.differs(0, &crc);
      if (bad) {
        say("CHECK predication seen %d value %d: %s: UNSUPPORTED\n", seen, value, drawn ? "not drawn, D3D11 draws" : "drawn, D3D11 does not");
        g.picture[0].model = before;
        if (!drawn) g.drawn(0, at, 100, 20, 20, shade(40 + at));
        check(!g.differs(0, &crc), "the picture is the one that ignores the predicate");
      }
    }
  say("HASH predication.0 %08x\n", crc);
  p->Release();
}

/* Waits that come after the query and are over only when somebody who waits for the query lets them be. */
static void waits() {
  if (!g.ctx4) { say("CHECK waits ID3D11DeviceContext4: UNSUPPORTED\n"); return; }
  ID3D11Device5 *dev5;
  Gpu other;
  other.make();
  ID3D11Fence *f = nullptr;
  if (FAILED(other.dev->QueryInterface(__uuidof(ID3D11Device5), (void **)&dev5)) || FAILED(dev5->CreateFence(0, D3D11_FENCE_FLAG_NONE, __uuidof(ID3D11Fence), (void **)&f))) {
    say("CHECK waits CreateFence: UNSUPPORTED\n");
    other.drop();
    return;
  }
  ID3D11Query *first = g.query(D3D11_QUERY_EVENT), *later = g.query(D3D11_QUERY_EVENT);
  for (UINT64 v = 1; v <= 5; v++) {
    g.rect(0, (int)v * 20, 20, 15, 15, shade((unsigned)v));
    g.ctx->End(first);
    HRESULT hr = g.ctx4->Wait(f, v);
    if (FAILED(hr)) { say("CHECK waits Wait 0x%08lx: UNSUPPORTED\n", (unsigned long)hr); break; }
    g.rect(0, (int)v * 20, 60, 15, 15, shade((unsigned)v + 9));
    g.ctx->End(later);
    if (v & 1) g.ctx->Flush(); /* else nobody submits it but the looks */
    Looked l = look_event(first, DONT);
    check(l.hr == S_OK, "the query before the wait: there (%.1f ms)", l.ms);
    l = look_event(later, DONT, 150);
    const bool held = check(l.hr == S_FALSE, "the query after the wait, not let go: not there (%llu looks in %.0f ms)", (unsigned long long)l.looks, l.ms);
    for (int n = 0; n < 30; n++) { g.rect(1, n, (int)v * 10, 5, 5, shade(n)); BOOL b; g.ctx->GetData(later, &b, sizeof(b), DONT); nap_us(200); }
    HR(other.ctx4->Signal(f, v));
    other.ctx->Flush();
    l = look_event(later, DONT);
    check(l.hr == S_OK, "let go: there (%.1f ms)%s", l.ms, held ? "" : " [was early]");
  }
  picture_good();
  first->Release(); later->Release(); f->Release(); dev5->Release();
  other.drop();
}

/* The same with a keyed mutex (the wait of AcquireSync), between two devices. */
static void keyed() {
  Gpu other;
  other.make();
  D3D11_TEXTURE2D_DESC d = {64, 64, 1, 1, DXGI_FORMAT_R8G8B8A8_UNORM, {1, 0}, D3D11_USAGE_DEFAULT, D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE, 0,
                            D3D11_RESOURCE_MISC_SHARED_KEYEDMUTEX};
  ID3D11Texture2D *mine = nullptr, *theirs = nullptr;
  IDXGIResource *res = nullptr;
  IDXGIKeyedMutex *a = nullptr, *b = nullptr;
  HANDLE handle = nullptr;
  HRESULT hr = g.dev->CreateTexture2D(&d, nullptr, &mine);
  if (SUCCEEDED(hr)) hr = mine->QueryInterface(__uuidof(IDXGIKeyedMutex), (void **)&a);
  if (SUCCEEDED(hr)) hr = mine->QueryInterface(__uuidof(IDXGIResource), (void **)&res);
  if (SUCCEEDED(hr)) hr = res->GetSharedHandle(&handle);
  if (SUCCEEDED(hr)) hr = other.dev->OpenSharedResource(handle, __uuidof(ID3D11Texture2D), (void **)&theirs);
  if (SUCCEEDED(hr)) hr = theirs->QueryInterface(__uuidof(IDXGIKeyedMutex), (void **)&b);
  if (FAILED(hr)) {
    say("CHECK keyed a keyed mutex between two devices 0x%08lx: UNSUPPORTED\n", (unsigned long)hr);
  } else if (FAILED(hr = b->AcquireSync(0, 1000)) || hr != S_OK) {
    say("CHECK keyed AcquireSync 0x%08lx: UNSUPPORTED\n", (unsigned long)hr); /* (the native build has no keyed mutexes) */
  } else {
    ID3D11Query *first = g.query(D3D11_QUERY_EVENT), *later = g.query(D3D11_QUERY_EVENT);
    bool good = true;
    for (int n = 0; n < 8 && good; n++) {
      other.ctx->Flush();
      if (n) good &= b->AcquireSync(0, 1000) == S_OK;
      other.burn(layers_40ms / 2);
      good &= b->ReleaseSync(1) == S_OK;
      g.rect(0, n * 10, 10, 9, 9, shade(n));
      g.ctx->End(first);
      good &= a->AcquireSync(1, 1000) == S_OK;
      g.rect(0, n * 10, 30, 9, 9, shade(n + 5));
      g.ctx->End(later);
      good &= a->ReleaseSync(0) == S_OK;
      good &= look_event(first, DONT).hr == S_OK && look_event(later, DONT).hr == S_OK;
    }
    check(good, "8 hand-overs: both queries there each time");
    picture_good();
    first->Release(); later->Release();
  }
  for (IUnknown *u : std::initializer_list<IUnknown *>{a, b, res, mine, theirs}) if (u) u->Release();
  other.drop();
}

/* A device let go of with queries pending: handed over and the GPU at them, not handed over, held by a wait. */
static void teardown() {
  double worst = 0;
  const uint64_t all = ns();
  for (int n = 0; n < 12; n++) {
    Gpu t;
    t.make();
    ID3D11Query *q[6];
    for (int k = 0; k < 6; k++) q[k] = t.query(k % 3 == 2 ? D3D11_QUERY_TIMESTAMP_DISJOINT : D3D11_QUERY_EVENT);
    if (n % 3) t.burn(layers_40ms * 2);
    for (int k = 0; k < 3; k++) { t.rect(0, k * 10, 0, 5, 5, shade(k)); t.ctx->End(q[k]); }
    if (n & 1) t.ctx->Flush();
    for (int k = 3; k < 6; k++) { t.rect(0, k * 10, 0, 5, 5, shade(k)); t.ctx->End(q[k]); }
    BOOL b[4];
    for (int k = 0; k < (n % 4) * 70; k++) { t.ctx->GetData(q[k % 6], b, q[k % 6]->GetDataSize(), DONT); if (k % 16 == 0) nap_us(200); }
    /* What was handed over is encoded (the GPU is still at it): a device let go of before that ends libdxmt-native too, with the
     * switch and without (its encoder uses the pipelines the device has just freed). */
    nap_us(15000);
    const uint64_t begin = ns();
    for (auto x : q) x->Release();
    t.drop();
    worst = std::max(worst, (ns() - begin) / 1e6);
    progress++;
  }
  check(worst < 3000, "12 devices let go of: the longest %.1f ms", worst);
#ifndef _WIN32
  /* (Through Neptune the Signal below is decoded after the release before it, which waits for the GPU that waits for the Signal: the
   * GPU's own time limit ends it, with the switch and without.) */
  if (g.ctx4) {
    Gpu t, other;
    t.make();
    other.make();
    ID3D11Device5 *dev5;
    ID3D11Fence *f = nullptr;
    if (SUCCEEDED(other.dev->QueryInterface(__uuidof(ID3D11Device5), (void **)&dev5)) &&
        SUCCEEDED(dev5->CreateFence(0, D3D11_FENCE_FLAG_NONE, __uuidof(ID3D11Fence), (void **)&f)) && SUCCEEDED(t.ctx4->Wait(f, 1))) {
      ID3D11Query *q = t.query(D3D11_QUERY_EVENT);
      t.rect(0, 0, 0, 5, 5, shade(1));
      t.ctx->End(q);
      t.ctx->Flush();
      BOOL b;
      for (int k = 0; k < 300; k++) { t.ctx->GetData(q, &b, sizeof(b), DONT); nap_us(100); }
      std::atomic<bool> gone{false};
      std::thread ender([&] { q->Release(); t.drop(); gone = true; });
      nap_us(200000);
      const bool early = gone;
      HR(other.ctx4->Signal(f, 1));
      other.ctx->Flush();
      const uint64_t begin = ns();
      while (!gone && ns() - begin < 5000000000ull) nap_us(1000);
      check(gone, "held by a wait: gone %s (%.1f ms after it was let go)", early ? "before" : "after", (ns() - begin) / 1e6);
      ender.join();
    } else {
      say("CHECK teardown a wait across devices: UNSUPPORTED\n");
      t.drop();
    }
    if (f) f->Release();
    dev5->Release();
    other.drop();
  }
#endif
  note("%.1f ms in all", (ns() - all) / 1e6);
  ID3D11Query *e = g.query(D3D11_QUERY_EVENT);
  g.rect(0, 1, 1, 5, 5, shade(1));
  g.ctx->End(e);
  Looked l = look_event(e, DONT);
  check(l.hr == S_OK, "the other device goes on: 0x%08lx (%.1f ms, %llu looks)", (unsigned long)l.hr, l.ms, (unsigned long long)l.looks);
  if (l.hr != S_OK) { l = look_event(e, 0); note("then with flags 0: 0x%08lx (%.1f ms)", (unsigned long)l.hr, l.ms); }
  picture_good();
  e->Release();
}

/* Two threads take turns on the context under a lock of the application's (two rings): one records and ends, one only looks. */
static void two_threads() {
  std::mutex turn;
  ID3D11Query *e[4];
  for (auto &q : e) q = g.query(D3D11_QUERY_EVENT);
  std::atomic<int> ended[4] = {}, seen[4] = {};
  std::atomic<bool> stop{false};
  std::atomic<uint64_t> looks{0};
  std::thread looker([&] {
    while (!stop) {
      for (int k = 0; k < 4; k++) {
        std::lock_guard<std::mutex> l(turn);
        const int at = ended[k];
        BOOL there;
        if (at && seen[k] != at && g.ctx->GetData(e[k], &there, sizeof(there), DONT) == S_OK) seen[k] = at;
        looks++;
      }
      nap_us(50);
    }
  });
  bool good = true;
  for (int f = 1; f <= 400; f++) {
    for (int n = 0; n < 10; n++) {
      std::lock_guard<std::mutex> l(turn);
      g.rect(n & 1, (f + n * 11) % 200, (n * 29 + f) % 200, 30, 30, shade(f + n));
    }
    const int k = f & 3;
    { std::lock_guard<std::mutex> l(turn); if (f % 8 == 0) g.burn(layers_40ms / 5); g.ctx->End(e[k]); ended[k] = f; }
    const int wait = (f + 2) & 3;
    const uint64_t begin = ns();
    while (ended[wait] && seen[wait] != ended[wait] && ns() - begin < 4000000000ull) nap_us(100);
    good &= !ended[wait] || seen[wait] == ended[wait];
    progress++;
  }
  stop = true;
  looker.join();
  check(good, "400 of 400 there (%llu looks by the other thread)", (unsigned long long)looks.load());
  picture_good();
  for (auto q : e) q->Release();
}

#ifndef _WIN32
/* Counted looks at DXMT itself: none of the first 64 submits, the 65th does, once; and a chunk that was handed over is not
 * touched again. The wait and its release are fences of a second device. (The recording says the same of the commits.) */
static void sixty_four() {
  ID3D11Query *e = g.query(D3D11_QUERY_EVENT);
  BOOL b;
  for (int looks = 60; looks <= 70; looks++) {
    g.rect(0, looks, looks, 9, 9, shade(looks));
    g.ctx->End(e);
    for (int n = 0; n < looks; n++)
      if (g.ctx->GetData(e, &b, sizeof(b), DONT) == S_OK && n <= 64) { check(false, "%d looks: there after %d (nothing had submitted it)", looks, n + 1); goto next; }
    nap_us(30000);
    { const HRESULT hr = g.ctx->GetData(e, &b, sizeof(b), DONT);
      check((hr == S_OK) == (looks >= 65), "%d looks and 30 ms: %s", looks, hr == S_OK ? "there" : "not there"); }
  next:
    g.ctx->Flush();
    check(look_event(e, DONT).hr == S_OK, "after Flush: there");
  }
  g.ctx->End(e);
  for (int n = 0; n < 2; n++) { g.ctx->Flush(); check(look_event(e, DONT).hr == S_OK, "an End of nothing new is there"); g.ctx->End(e); }
  picture_good();
  e->Release();
}
/* As Neptune's host: a thread that looks at every pending query under a lock of its own while another records and ends, and
 * looks of flags 0 by a third; the context's own lock asked for (SetMultithreadProtected). */
static void host_threads() {
  ID3D11Multithread *mt;
  HR(g.ctx->QueryInterface(__uuidof(ID3D11Multithread), (void **)&mt));
  mt->SetMultithreadProtected(TRUE);
  ID3D11Query *e[16];
  for (auto &q : e) q = g.query(D3D11_QUERY_EVENT);
  std::mutex feedback;
  std::atomic<uint32_t> ended[16] = {}, published[16] = {};
  std::atomic<bool> stop{false};
  std::atomic<uint64_t> looks{0};
  auto sweep = [&] {
    std::lock_guard<std::mutex> l(feedback);
    for (int k = 0; k < 16; k++) {
      const uint32_t at = ended[k];
      BOOL there;
      if (at != published[k] && g.ctx->GetData(e[k], &there, sizeof(there), DONT) == S_OK) published[k] = at;
      looks++;
    }
  };
  std::thread ring([&] { while (!stop) { sweep(); nap_us(100); } });
  std::thread retire([&] { while (!stop) { sweep(); nap_us(370); } });
  std::thread third([&] { Random r(7); while (!stop) { BOOL b; const int k = (int)r.below(16); if (ended[k]) g.ctx->GetData(e[k], &b, sizeof(b), 0); nap_us(5000); } });
  Random r(11);
  bool good = true;
  const uint64_t all = ns();
  for (uint32_t f = 1; f <= 20000 && good; f++) {
    for (unsigned n = r.below(6); n--;) g.rect(r.below(2), r.below(200), r.below(200), 30, 30, shade(r.next()));
    const int k = (int)(f & 15);
    { std::lock_guard<std::mutex> l(feedback); g.ctx->End(e[k]); ended[k] = f; } /* (so that a look is of one End) */
    if (r.one_in(50)) g.ctx->Flush();
    if (r.one_in(200)) g.burn(layers_40ms / 20);
    if (r.one_in(40)) nap_us(r.below(9000));
    const int wait = (int)((f + 5) & 15);
    const uint64_t begin = ns();
    while (published[wait] != ended[wait] && ns() - begin < 4000000000ull) nap_us(20);
    good &= published[wait] == ended[wait];
    progress++;
  }
  stop = true;
  ring.join(); retire.join(); third.join();
  check(good, "20000 Ends beside three lookers: each there (%llu looks, %.1f s)", (unsigned long long)looks.load(), (ns() - all) / 1e9);
  picture_good();
  mt->SetMultithreadProtected(FALSE);
  mt->Release();
  for (auto q : e) q->Release();
}
/* With the switch: what a look could not do for the device's lock, or for pending uploads, is done without another look; and no look waits. */
static void owed() {
  if (!once) { note("not asked without the switch: a look there waits for the device's lock"); return; }
  ID3D11Multithread *mt;
  HR(g.ctx->QueryInterface(__uuidof(ID3D11Multithread), (void **)&mt));
  mt->SetMultithreadProtected(TRUE);
  ID3D11Query *e = g.query(D3D11_QUERY_EVENT);
  std::vector<uint8_t> data(1024 * 1024 * 4, 0x33);
  auto upload = [&](UINT px) {
    D3D11_TEXTURE2D_DESC d = {px, px, 1, 1, DXGI_FORMAT_R8G8B8A8_UNORM, {1, 0}, D3D11_USAGE_DEFAULT, D3D11_BIND_SHADER_RESOURCE, 0, 0};
    D3D11_SUBRESOURCE_DATA init = {data.data(), px * 4, 0};
    ID3D11Texture2D *t;
    HR(g.dev->CreateTexture2D(&d, &init, &t));
    t->Release();
  };
  for (int round = 0; round < 12; round++) {
    const bool lock = round % 3 != 1, pending = round % 3 != 0; /* the lock, uploads, both */
    g.rect(0, round * 10, 10, 9, 9, shade(round));
    g.ctx->End(e);
    if (pending) upload(256 << (round & 1));
    std::atomic<int> phase{0};
    std::thread owner([&] { if (lock) mt->Enter(); phase = 1; while (phase != 2) nap_us(100); if (lock) mt->Leave(); });
    while (phase != 1) nap_us(50);
    uint64_t worst = 0;
    BOOL there;
    HRESULT hr = S_FALSE;
    for (int n = 0; n < 70; n++) {
      const uint64_t a = ns();
      hr = g.ctx->GetData(e, &there, sizeof(there), DONT);
      worst = std::max(worst, ns() - a);
    }
    if (lock) {
      nap_us(20000);
      check(hr == S_FALSE && g.ctx->GetData(e, &there, sizeof(there), DONT) == S_FALSE, "round %d: the lock is another's: not there, and no look waited (the longest %.3f ms)", round, worst / 1e6);
    }
    check(worst < 25000000, "round %d: no look waited (the longest %.3f ms)", round, worst / 1e6);
    phase = 2;
    owner.join();
    nap_us(60000); /* (nobody looks) */
    hr = g.ctx->GetData(e, &there, sizeof(there), DONT);
    check(hr == S_OK, "round %d (%s%s): done without another look: 0x%08lx", round, lock ? "lock " : "", pending ? "uploads" : "", (unsigned long)hr);
    if (hr != S_OK) look_event(e, 0);
    progress++;
  }
  if (g.ctx4) { /* the queue is full of what waits for a Signal of this very thread: a look that waited for it would wait for good */
    Gpu other;
    other.make();
    ID3D11Device5 *dev5 = nullptr;
    ID3D11Fence *f = nullptr;
    if (SUCCEEDED(other.dev->QueryInterface(__uuidof(ID3D11Device5), (void **)&dev5)) &&
        SUCCEEDED(dev5->CreateFence(0, D3D11_FENCE_FLAG_NONE, __uuidof(ID3D11Fence), (void **)&f)))
      for (UINT64 v = 1; v <= 3; v++) {
        ID3D11Query *q = g.query(D3D11_QUERY_EVENT);
        g.ctx->End(q);
        look_event(q, 0);
        q->Release();
        HR(g.ctx4->Wait(f, v));
        for (int n = 0; n < 31; n++) { g.rect(0, n, 60 + (int)v * 10, 5, 5, shade(n)); g.ctx->Flush(); }
        g.rect(0, 40 + (int)v * 10, 100, 5, 5, shade(77));
        g.ctx->End(e);
        uint64_t worst = 0;
        BOOL there;
        HRESULT hr = S_FALSE;
        for (int n = 0; n < 90 && hr == S_FALSE; n++) {
          const uint64_t a = ns();
          hr = g.ctx->GetData(e, &there, sizeof(there), DONT);
          worst = std::max(worst, ns() - a);
        }
        check(hr == S_FALSE && worst < 25000000, "a full queue: not there, and no look waited (the longest %.3f ms)", worst / 1e6);
        if (v == 2) { /* (the protection taken back while the rescue is owed for the queue) */
          mt->SetMultithreadProtected(FALSE);
          nap_us(10000);
        }
        HR(other.ctx4->Signal(f, v));
        other.ctx->Flush();
        nap_us(60000);
        hr = g.ctx->GetData(e, &there, sizeof(there), DONT);
        check(hr == S_OK, "a full queue let go: done without another look: 0x%08lx", (unsigned long)hr);
        if (hr != S_OK) look_event(e, 0);
        if (v == 2) mt->SetMultithreadProtected(TRUE);
        progress++;
      }
    if (f) f->Release();
    if (dev5) dev5->Release();
    other.drop();
  }
  mt->Enter(); /* (whoever was on the device is done with it, as seen from here) */
  mt->Leave();
  mt->SetMultithreadProtected(FALSE);
  for (int round = 0; round < 6; round++) { /* not protected: the next looks do it */
    g.rect(0, round * 10, 30, 9, 9, shade(round + 30));
    g.ctx->End(e);
    upload(512);
    Looked l = look_event(e, DONT, 4000, 50);
    check(l.hr == S_OK, "no lock asked for, uploads pending: there (%.1f ms, %llu looks)", l.ms, (unsigned long long)l.looks);
  }
  picture_good();
  mt->Release(); e->Release();
}

/* What the application sets of ID3D11Multithread, at any moment and from any thread: what it is told back, what Enter holds by it, and,
 * with the switch, that a rescue that is owed stays owed and that nothing is recorded beside the rescue thread. (Without the switch nothing is
 * owed, and the lock is taken away from whoever is in it: only what is told back is asked.) */
static void protection() {
  ID3D11Multithread *mt;
  HR(g.ctx->QueryInterface(__uuidof(ID3D11Multithread), (void **)&mt));
  {
    ID3D11Multithread *of_device;
    HR(g.dev->QueryInterface(__uuidof(ID3D11Multithread), (void **)&of_device));
    const BOOL first = mt->SetMultithreadProtected(FALSE);
    bool good = !first && !mt->GetMultithreadProtected() && !of_device->GetMultithreadProtected();
    good &= !of_device->SetMultithreadProtected(TRUE) && mt->GetMultithreadProtected() && of_device->GetMultithreadProtected();
    good &= mt->SetMultithreadProtected(TRUE) && mt->SetMultithreadProtected(FALSE) && !of_device->GetMultithreadProtected();
    check(good, "what was set is what is told, by the device's and the context's");
    of_device->Release();
  }
  ID3D11Query *e = g.query(D3D11_QUERY_EVENT);
  auto there = [&] { BOOL b; return g.ctx->GetData(e, &b, sizeof(b), DONT); };
  /* Another thread draws and ends the event; whether it came through within `ms`. Waited for in the end. */
  auto other_records = [&](int ms, auto &&meanwhile) {
    std::atomic<bool> came{false};
    std::thread t([&] { g.rect(0, 3, 3, 4, 4, shade(5)); g.ctx->End(e); came = true; });
    for (int n = 0; n < ms && !came; n++) nap_us(1000);
    const bool in_time = came;
    meanwhile();
    t.join();
    return in_time;
  };
  check(other_records(2000, [] {}), "not protected: another thread records");
  mt->Enter(); /* (holds nothing: it is off) */
  check(other_records(2000, [] {}), "not protected, entered: another thread records");
  mt->Leave();
  mt->Leave();
  mt->SetMultithreadProtected(TRUE);
  mt->Enter();
  mt->Enter();
  mt->Leave();
  check(!other_records(60, [&] { mt->Leave(); }), "protected, entered twice, left once: another thread waits");
  mt->Enter();
  mt->SetMultithreadProtected(FALSE);
  check(other_records(2000, [] {}), "entered, then not protected any more: another thread records");
  mt->Leave(); /* (left already) */
  mt->SetMultithreadProtected(TRUE);
  check(other_records(2000, [] {}), "protected again, nothing entered: another thread records");
  mt->Enter();
  check(!other_records(60, [&] { mt->Leave(); }), "and entered: it waits");
  check(look_event(e, 0).hr == S_OK, "the event of it is there");
  if (!once) { mt->SetMultithreadProtected(FALSE); mt->Release(); e->Release(); picture_good(); return; }

  /* The rescue thread at work while the protection goes on and off: every event is there without another look. */
  enum { SAME, FROM_ANOTHER, ON_AND_OFF, HOWS };
  for (int how = 0; how < HOWS; how++)
    for (int round = 0; round < 40; round++) {
      mt->SetMultithreadProtected(TRUE);
      g.rect(0, round * 5, 40 + how * 10, 4, 4, shade(round + how));
      g.ctx->End(e);
      std::atomic<int> phase{0};
      std::thread owner([&] {
        mt->Enter();
        phase = 1;
        while (phase < 2) nap_us(50);
        if (how == FROM_ANOTHER) { mt->SetMultithreadProtected(FALSE); nap_us(round * 20); }
        mt->Leave();
      });
      while (phase < 1) nap_us(20);
      HRESULT hr = S_FALSE;
      for (int n = 0; n < 70; n++) hr = there();
      bool stop_it = false;
      std::atomic<bool> stop{false};
      std::thread toggler;
      if (how == SAME) mt->SetMultithreadProtected(FALSE);
      if (how == ON_AND_OFF) { stop_it = true; toggler = std::thread([&] { for (unsigned n = 0; !stop; n++) { mt->SetMultithreadProtected(n & 1); if (n % 64 == 0) nap_us(1); } }); }
      const bool held = hr == S_FALSE;
      phase = 2;
      owner.join();
      for (int n = 0; n < 60 && (n < 4 || hr != S_OK); n++) { nap_us(1000); if (n >= 30) hr = there(); } /* (nobody looks for 30 ms) */
      if (stop_it) { stop = true; toggler.join(); }
      if (!held || hr != S_OK) check(false, "how %d, round %d: not before it was let go, and then without another look: %d 0x%08lx", how, round, (int)held, (unsigned long)hr);
      if (hr != S_OK) look_event(e, 0);
      progress++;
    }
  check(true, "%d x 40 events owed while the protection went", (int)HOWS);

  /* Recording, ending and looking beside two lookers, with the protection going on and off all along. */
  {
    std::atomic<bool> stop{false};
    ID3D11Query *q[8];
    std::mutex feedback;
    uint32_t seen[8] = {}, ended[8] = {};
    for (auto &x : q) x = g.query(D3D11_QUERY_EVENT);
    std::thread toggler([&] { Random r(3); while (!stop) { mt->SetMultithreadProtected(r.one_in(2)); if (r.one_in(3)) { mt->Enter(); nap_us(r.below(200)); mt->Leave(); } nap_us(r.below(60)); } });
    auto sweep = [&] {
      std::lock_guard<std::mutex> l(feedback);
      for (int k = 0; k < 8; k++) { BOOL b; if (seen[k] != ended[k] && g.ctx->GetData(q[k], &b, sizeof(b), DONT) == S_OK) seen[k] = ended[k]; }
    };
    std::thread a([&] { while (!stop) { sweep(); nap_us(100); } }), b([&] { while (!stop) { sweep(); nap_us(330); } });
    Random r(17);
    bool good = true;
    for (uint32_t f = 1; f <= 6000 && good; f++) {
      for (unsigned n = r.below(4); n--;) g.rect(r.below(2), r.below(200), r.below(200), 30, 30, shade(r.next()));
      const int k = (int)(f & 7);
      { std::lock_guard<std::mutex> l(feedback); g.ctx->End(q[k]); ended[k] = f; }
      if (r.one_in(120)) g.burn(layers_40ms / 20);
      if (r.one_in(60)) nap_us(r.below(9000));
      const int wait = (int)((f + 3) & 7);
      const uint64_t begin = ns();
      for (;;) {
        { std::lock_guard<std::mutex> l(feedback); if (seen[wait] == ended[wait]) break; }
        if (ns() - begin > 4000000000ull) { good = false; break; }
        nap_us(20);
      }
      progress++;
    }
    stop = true;
    toggler.join(); a.join(); b.join();
    check(good, "6000 Ends beside two lookers and one who sets the protection: each there");
    for (auto x : q) x->Release();
  }

  /* A full queue, and the protection taken back while the rescue is owed for it: from this thread, from another, and not. */
  if (g.ctx4) {
    Gpu other;
    other.make();
    ID3D11Device5 *dev5 = nullptr;
    ID3D11Fence *f = nullptr;
    if (SUCCEEDED(other.dev->QueryInterface(__uuidof(ID3D11Device5), (void **)&dev5)) &&
        SUCCEEDED(dev5->CreateFence(0, D3D11_FENCE_FLAG_NONE, __uuidof(ID3D11Fence), (void **)&f)))
      for (UINT64 v = 1; v <= 6; v++) {
        mt->SetMultithreadProtected(TRUE);
        look_event(e, 0);
        HR(g.ctx4->Wait(f, v));
        for (int n = 0; n < 31; n++) { g.rect(1, n, 60 + (int)v * 10, 5, 5, shade(n)); g.ctx->Flush(); }
        g.rect(1, 40 + (int)v * 10, 100, 5, 5, shade(77));
        g.ctx->End(e);
        uint64_t worst = 0;
        HRESULT hr = S_FALSE;
        for (int n = 0; n < 90 && hr == S_FALSE; n++) { const uint64_t a = ns(); hr = there(); worst = std::max(worst, ns() - a); }
        check(hr == S_FALSE && worst < 25000000, "a full queue, %llu: not there, and no look waited (the longest %.3f ms)", (unsigned long long)v, worst / 1e6);
        const uint64_t a = ns();
        if (v == 2 || v == 5) mt->SetMultithreadProtected(FALSE);
        if (v == 3) std::thread([&] { mt->SetMultithreadProtected(FALSE); }).join();
        if (v == 5 || v == 6) { mt->SetMultithreadProtected(FALSE); mt->SetMultithreadProtected(TRUE); }
        check(ns() - a < 25000000, "a full queue, %llu: what is set waits for nothing (%.3f ms)", (unsigned long long)v, (ns() - a) / 1e6);
        nap_us(10000);
        HR(other.ctx4->Signal(f, v));
        other.ctx->Flush();
        nap_us(60000);
        hr = there();
        check(hr == S_OK, "a full queue let go, %llu, protected %d: done without another look: 0x%08lx", (unsigned long long)v, (int)mt->GetMultithreadProtected(), (unsigned long)hr);
        if (hr != S_OK) look_event(e, 0);
        progress++;
      }
    if (f) f->Release();
    if (dev5) dev5->Release();
    other.drop();
  }

  /* A device let go of with a rescue owed, the protection going meanwhile. */
  {
    double worst = 0;
    for (int n = 0; n < 24; n++) {
      Gpu t;
      t.make();
      ID3D11Multithread *m;
      HR(t.ctx->QueryInterface(__uuidof(ID3D11Multithread), (void **)&m));
      m->SetMultithreadProtected(TRUE);
      ID3D11Query *q = t.query(D3D11_QUERY_EVENT);
      t.rect(0, 1, 1, 5, 5, shade(n));
      t.ctx->End(q);
      std::atomic<int> phase{0};
      std::thread owner([&] { m->Enter(); phase = 1; while (phase < 2) nap_us(50); if (n & 1) m->SetMultithreadProtected(FALSE); m->Leave(); phase = 3; });
      while (phase < 1) nap_us(20);
      BOOL b;
      for (int k = 0; k < 70; k++) t.ctx->GetData(q, &b, sizeof(b), DONT);
      std::atomic<bool> stop{false};
      std::thread toggler([&] { for (unsigned k = 0; !stop; k++) { m->SetMultithreadProtected(k & 1); nap_us(5); } });
      phase = 2;
      owner.join();
      if (n % 3 == 2) nap_us(n * 10); /* (the rescue thread at it) */
      else nap_us(15000);             /* (as teardown() says) */
      if (n % 3 == 2) nap_us(15000);
      stop = true;
      toggler.join();
      m->Release();
      const uint64_t begin = ns();
      q->Release();
      t.drop();
      worst = std::max(worst, (ns() - begin) / 1e6);
      progress++;
    }
    check(worst < 3000, "24 devices let go of: the longest %.1f ms", worst);
  }
  mt->SetMultithreadProtected(FALSE);
  mt->Release();
  e->Release();
  picture_good();
}
#endif

struct Case { const char *name; void (*run)(); };
static const Case kCases[] = {
    {"noflush-spin", noflush_spin}, {"flags-zero", flags_zero}, {"covered", covered}, {"one-rescue", one_rescue}, {"pacing", pacing}, {"reuse", reuse},
    {"deferred", deferred}, {"list-events", list_events}, {"uploads", uploads}, {"immutables", immutables}, {"occlusion", occlusion}, {"occlusion-join", occlusion_join}, {"timestamps", timestamps}, {"readback", readback}, {"predication", predication}, {"waits", waits},
    {"keyed", keyed}, {"teardown", teardown}, {"two-threads", two_threads},
#ifndef _WIN32
    {"sixty-four", sixty_four}, {"host-threads", host_threads}, {"owed", owed}, {"protection", protection},
#endif
};

/* ---- frames, as fast as they come ---- */

/* `frames` frames of 12 passes, a copy and one or two event queries, off screen; the engine waits for the event of three frames ago, by
 * looks as Neptune's host makes them: another thread's, every 100 us, under a lock of its own, the device's lock asked for.
 *   gated: nothing else. busy: the CPU has 6 ms of its own work spread over the frame, and the GPU is behind it. rings: two more lookers,
 *   one of them without DONOTFLUSH now and then. lists: half of the passes in a command list with an event of its own.
 * What is drawn is the same whatever the timing: HASH. */
static int bench(const char *mode, unsigned frames) {
  current = mode;
  const bool busy = !strcmp(mode, "busy"), rings = !strcmp(mode, "rings"), lists = !strcmp(mode, "lists");
  ID3D11Multithread *mt = nullptr;
  if (SUCCEEDED(g.ctx->QueryInterface(__uuidof(ID3D11Multithread), (void **)&mt))) mt->SetMultithreadProtected(TRUE);
  ID3D11DeviceContext *dc;
  HR(g.dev->CreateDeferredContext(0, &dc));
  g.make_big();
  ID3D11Query *e[8], *mid[8], *in_list[8];
  for (int k = 0; k < 8; k++) { e[k] = g.query(D3D11_QUERY_EVENT); mid[k] = g.query(D3D11_QUERY_EVENT); in_list[k] = g.query(D3D11_QUERY_EVENT); }
  std::mutex feedback;
  std::atomic<uint32_t> ended[8] = {}, published[8] = {};
  std::atomic<bool> stop{false};
  std::atomic<uint64_t> looks{0}, longest{0};
  auto sweep = [&] {
    std::lock_guard<std::mutex> l(feedback);
    for (int k = 0; k < 8; k++) {
      const uint32_t at = ended[k];
      BOOL there;
      if (at == published[k]) continue;
      const uint64_t a = ns();
      const HRESULT hr = g.ctx->GetData(e[k], &there, sizeof(there), DONT);
      const uint64_t took = ns() - a;
      if (took > longest) longest = took;
      if (hr == S_OK) published[k] = at;
      looks++;
    }
  };
  std::vector<std::thread> lookers;
  lookers.emplace_back([&] { while (!stop) { sweep(); nap_us(100); } });
  if (rings) {
    lookers.emplace_back([&] { while (!stop) { sweep(); nap_us(370); } });
    lookers.emplace_back([&] { Random r(7); while (!stop) { BOOL b; const int k = (int)r.below(8); if (ended[k]) g.ctx->GetData(mid[k], &b, sizeof(b), r.below(8) ? DONT : 0); nap_us(2000); } });
  }
  std::vector<uint64_t> took;
  const unsigned layers = 100; /* (not calibrated: the same work in every run) */
  uint64_t last = ns();
  const uint64_t begin = last;
  for (unsigned f = 1; f <= frames; f++) {
    const int k = (int)(f & 7);
    if (f > 3) {
      const int w = (int)((f - 3) & 7);
      for (const uint64_t from = ns(); published[w] != f - 3 && ns() - from < 4000000000ull;) nap_us(20);
      if (published[w] != f - 3) { check(false, "frame %u: the event of three frames ago is not there", f); break; }
    }
    auto passes = [&](ID3D11DeviceContext *c, unsigned from, unsigned to) {
      for (unsigned n = from; n < to; n++) {
        Gpu::use_on(c, g.picture[n & 1]);
        for (unsigned i = 0; i < 8; i++) {
          const int x = (int)((f * 3 + n * 17 + i * 29) % 200), y = (int)((f * 5 + n * 23 + i * 41) % 200);
          g.rect_on(c, x, y, 31, 27, shade(f + n * 8 + i));
          g.drawn(n & 1, x, y, 31, 27, shade(f + n * 8 + i));
        }
        if (busy) for (const uint64_t from2 = ns(); ns() - from2 < 500000;) {}
      }
    };
    g.target = -1;
    passes(g.ctx, 0, 6);
    if (lists) {
      passes(dc, 6, 9);
      dc->End(in_list[k]);
      passes(dc, 9, 12);
      ID3D11CommandList *l;
      HR(dc->FinishCommandList(FALSE, &l));
      g.ctx->ExecuteCommandList(l, FALSE);
      l->Release();
    } else {
      g.ctx->End(mid[k]);
      passes(g.ctx, 6, 12);
    }
    g.target = -1;
    g.copy(1, 0, 10, 10, 20, 20);
    g.burn(layers);
    { std::lock_guard<std::mutex> l(feedback); g.ctx->End(e[k]); ended[k] = f; }
    if (f % 2) g.ctx->Flush(); /* (a frame's end hands it over, every other time: else the looks must) */
    const uint64_t now = ns();
    took.push_back(now - last);
    last = now;
    progress++;
  }
  const double all = (ns() - begin) / 1e9;
  for (int k = 0; k < 8; k++) for (const uint64_t from = ns(); published[k] != ended[k] && ns() - from < 4000000000ull;) nap_us(100);
  stop = true;
  for (auto &t : lookers) t.join();
  std::sort(took.begin(), took.end());
  auto at = [&](double p) { return took.empty() ? 0.0 : took[std::min(took.size() - 1, (size_t)(took.size() * p))] / 1e6; };
  say("BENCH %s frames=%zu fps=%.2f ms p50=%.3f p95=%.3f p99=%.3f looks=%llu longest_look=%.3f\n", mode, took.size(), took.size() / all, at(.5), at(.95), at(.99),
      (unsigned long long)looks.load(), longest / 1e6);
  picture_good();
  if (mt) { mt->SetMultithreadProtected(FALSE); mt->Release(); }
  dc->Release();
  for (int k = 0; k < 8; k++) { e[k]->Release(); mid[k]->Release(); in_list[k]->Release(); }
  return 0;
}

/* ---- the soak ---- */
static int soak(uint64_t seed, uint64_t generations, bool wide) {
  current = "soak";
  Random r(seed); /* what is drawn: the same for a seed, whatever the results and when they come */
  Random q(seed + 77); /* how and when it is looked at */
  struct Slot { ID3D11Query *q; D3D11_QUERY type; uint64_t serial; bool out; UINT64 want; std::string how; };
  std::vector<Slot> slots;
  static const D3D11_QUERY kTypes[] = {D3D11_QUERY_EVENT, D3D11_QUERY_EVENT, D3D11_QUERY_EVENT, D3D11_QUERY_TIMESTAMP_DISJOINT,
                                       D3D11_QUERY_TIMESTAMP, D3D11_QUERY_OCCLUSION, D3D11_QUERY_OCCLUSION_PREDICATE, D3D11_QUERY_EVENT};
  for (int n = 0; n < 48; n++) slots.push_back({g.query(kTypes[n % 8]), kTypes[n % 8], 0, false, 0, ""});
  ID3D11DeviceContext *dc;
  HR(g.dev->CreateDeferredContext(0, &dc));
  ID3D11Fence *fence = nullptr;
  ID3D11Device5 *dev5 = nullptr;
  if (g.ctx4 && SUCCEEDED(g.dev->QueryInterface(__uuidof(ID3D11Device5), (void **)&dev5)))
    if (FAILED(dev5->CreateFence(0, D3D11_FENCE_FLAG_NONE, __uuidof(ID3D11Fence), (void **)&fence))) fence = nullptr;
  UINT64 fence_value = 0;
  uint64_t done = 0, serial = 0, looks = 0, there = 0, early = 0, wrong = 0, hung = 0, epoch = 0, next_epoch = 5000, lists = 0;
  uint64_t stamp_serial = 0;
  UINT64 stamp = 0;
  const uint64_t began = ns();
  auto random_rect = [&](int &x, int &y, int &w, int &h) { w = 1 + r.below(90); h = 1 + r.below(90); x = r.below(PX - w); y = r.below(PX - h); };
  /* `stay`: on the target there is. An occlusion query whose draws are on two targets is counted wrong once in some 2,500 by this DXMT,
   * with the switch and without (a part missing, or memory nobody wrote): `wide` has them. */
  auto draw = [&](bool seen, bool stay) -> UINT64 {
    int x, y, w, h;
    random_rect(x, y, w, h);
    int i = g.target >= 0 && !r.one_in(5) ? g.target : (int)r.below(2);
    if (stay && !wide && g.target >= 0) i = g.target;
    g.rect(i, x, y, w, h, shade(r.next()), seen);
    return seen ? (UINT64)w * h : 0;
  };
  /* what a result must be */
  auto judge = [&](Slot &s, const void *data) {
    bool good = true;
    switch (s.type) {
    case D3D11_QUERY_EVENT: good = *(const BOOL *)data == TRUE; break;
    case D3D11_QUERY_TIMESTAMP_DISJOINT: {
      auto d = (const D3D11_QUERY_DATA_TIMESTAMP_DISJOINT *)data;
      good = d->Frequency == 1000000000 && !d->Disjoint;
      break;
    }
    case D3D11_QUERY_TIMESTAMP: {
      UINT64 v = *(const UINT64 *)data;
      /* a later End is at a later time */
      good = v != 0 && (s.serial > stamp_serial ? v >= stamp : v <= stamp || !stamp);
      if (s.serial > stamp_serial) { stamp = v; stamp_serial = s.serial; }
      break;
    }
    case D3D11_QUERY_OCCLUSION: good = *(const UINT64 *)data == s.want; break;
    default: good = *(const BOOL *)data == (s.want != 0); break;
    }
    if (!good) {
      wrong++;
      UINT64 v[2];
      memcpy(v, data, s.q->GetDataSize() > 8 ? 16 : s.q->GetDataSize());
      if (wrong < 20) say("CHECK soak type %d serial %llu: %llu, wanted %llu (stamp %llu of %llu; %s): FAIL\n", (int)s.type, (unsigned long long)s.serial,
                          (unsigned long long)v[0], (unsigned long long)s.want, (unsigned long long)stamp, (unsigned long long)stamp_serial, s.how.c_str());
    }
  };
  auto wait_for = [&](Slot &s) {
    alignas(8) char data[16] = {};
    const bool quiet = s.type == D3D11_QUERY_EVENT || s.type == D3D11_QUERY_TIMESTAMP_DISJOINT;
    Looked l = look(g.ctx, s.q, quiet && q.below(4) ? DONT : 0, data, s.q->GetDataSize(), 8000);
    looks += l.looks;
    if (l.hr != S_OK) { hung++; say("CHECK soak type %d serial %llu: 0x%08lx after %.0f ms: FAIL\n", (int)s.type, (unsigned long long)s.serial, (unsigned long)l.hr, l.ms); return; }
    there++;
    judge(s, data);
    s.out = false;
  };
  g.use(0);
  while (done < generations && hung < 3) {
    Slot &s = slots[r.below((uint32_t)slots.size())];
    switch (r.below(16)) {
    case 0: case 1: case 2: case 3: case 4: { /* an End, after some work */
      for (uint32_t n = r.below(4); n--;) draw(!r.one_in(8), false);
      s.want = 0;
      s.how = s.out ? "ended unread, immediate" : "immediate";
      if (s.type == D3D11_QUERY_OCCLUSION || s.type == D3D11_QUERY_OCCLUSION_PREDICATE) {
        if (g.target < 0) g.use(0);
        g.ctx->Begin(s.q);
        for (uint32_t n = r.below(3); n--;) { const int on = g.target; s.want += draw(!r.one_in(3), true); s.how += on == g.target ? ", draw" : ", target, draw"; }
        if (r.one_in(20)) { g.ctx->Flush(); s.how += ", flush"; }
      } else if (s.type == D3D11_QUERY_TIMESTAMP_DISJOINT) {
        g.ctx->Begin(s.q);
        draw(true, false);
      }
      g.ctx->End(s.q);
      s.serial = ++serial;
      s.out = true;
      done++;
      break;
    }
    case 5: case 6: case 7: case 8: { /* looks */
      if (!s.out) break;
      alignas(8) char data[16] = {};
      const UINT flags = q.below(5) ? DONT : 0;
      HRESULT hr = S_FALSE;
      for (uint32_t n = q.one_in(10) ? 100 : 1 + q.below(8); n-- && hr == S_FALSE; looks++) hr = g.ctx->GetData(s.q, q.one_in(10) ? nullptr : data, s.q->GetDataSize(), flags);
      /* (a look without a place says only that it is there: looked at again) */
      if (hr == E_INVALIDARG) break;
      if (hr == S_OK && (hr = g.ctx->GetData(s.q, data, s.q->GetDataSize(), DONT)) == S_OK) {
        /* Timing dependent: nothing of what is drawn may follow from it. */
        there++;
        judge(s, data);
        s.out = false;
      } else if (hr != S_FALSE && hr != S_OK) {
        wrong++;
      }
      break;
    }
    case 9: /* wait for one */
      if (s.out && q.one_in(3)) wait_for(s);
      break;
    case 10:
      if (r.one_in(3)) g.ctx->Flush();
      else g.use(1 - std::max(g.target, 0));
      break;
    case 11: {
      int x, y, w, h;
      random_rect(x, y, w, h);
      const int to = r.below(2);
      if (r.one_in(6)) g.clear(to, shade(r.next()));
      else { g.copy(to, 1 - to, x, y, w, h); }
      break;
    }
    case 12: /* let go of, looked at or not */
      if (r.one_in(3)) { s.q->Release(); s.q = g.query(s.type); s.out = false; }
      break;
    case 13:
      if (fence && r.one_in(4)) HR(g.ctx4->Signal(fence, ++fence_value));
      if (r.one_in(60)) g.burn(layers_40ms / 10);
      break;
    case 14: /* a command list */
      if (r.one_in(40)) {
        int x, y, w, h;
        random_rect(x, y, w, h);
        Colour k = shade(r.next());
        const int i = r.below(2);
        Gpu::use_on(dc, g.picture[i]);
        const bool counts = s.type == D3D11_QUERY_OCCLUSION || s.type == D3D11_QUERY_OCCLUSION_PREDICATE;
        if (counts) dc->Begin(s.q);
        g.rect_on(dc, x, y, w, h, k);
        dc->End(s.q);
        ID3D11CommandList *list;
        HR(dc->FinishCommandList(FALSE, &list));
        s.how = s.out ? "ended unread, list" : "list";
        for (uint32_t n = 1 + r.below(2); n--;) { s.how += " executed"; g.ctx->ExecuteCommandList(list, r.below(2)); g.target = -1; }
        list->Release();
        g.drawn(i, x, y, w, h, k);
        s.want = (UINT64)w * h;
        s.serial = ++serial;
        done++;
        lists++;
        wait_for(s); /* (its result comes by a call that waits: not left out) */
        s.out = false;
      }
      break;
    case 15: /* time passes */
      if (q.one_in(30)) nap_us(q.below(9000));
      if (r.one_in(120)) {
        const int i = r.below(2);
        unsigned bad = g.differs(i, nullptr);
        if (bad) { wrong++; say("CHECK soak picture %d at %llu: %u pixels differ: FAIL\n", i, (unsigned long long)done, bad); }
      }
      break;
    }
    progress++;
    if (done >= next_epoch) {
      next_epoch += 5000;
      for (Slot &x : slots) if (x.out) wait_for(x);
      for (int i = 0; i < 2; i++) {
        uint32_t crc;
        unsigned bad = g.differs(i, &crc);
        if (bad) { wrong++; say("CHECK soak picture %d at %llu: %u pixels differ: FAIL\n", i, (unsigned long long)done, bad); }
        say("HASH soak.%llu.%d %08x\n", (unsigned long long)epoch, i, crc);
      }
      epoch++;
      if (epoch % 4 == 0)
        say("NOTE soak %llu generations, %.0f s, %llu looks, %llu there, %llu lists, %llu wrong\n", (unsigned long long)done, (ns() - began) / 1e9,
            (unsigned long long)looks, (unsigned long long)there, (unsigned long long)lists, (unsigned long long)wrong);
    }
  }
  for (Slot &x : slots) if (x.out && hung < 3) wait_for(x);
  for (Slot &x : slots) x.q->Release();
  dc->Release();
  if (fence) fence->Release();
  if (dev5) dev5->Release();
  check(!hung && !wrong && !early, "%llu generations (%llu in lists), %llu looks, %llu there, %llu wrong, %llu hung, %.0f s", (unsigned long long)done,
        (unsigned long long)lists, (unsigned long long)looks, (unsigned long long)there, (unsigned long long)wrong, (unsigned long long)hung, (ns() - began) / 1e9);
  return 0;
}

int main(int argc, char **argv) {
  setvbuf(stdout, nullptr, _IONBF, 0);
  int at = 1;
#ifndef _WIN32
  if (argc > 2 && !strcmp(argv[1], "-d")) {
    void *lib = dlopen(argv[2], RTLD_NOW | RTLD_LOCAL);
    if (!lib) { printf("%s\n", dlerror()); return 2; }
    create_device = (CreateDevice)dlsym(lib, "D3D11CreateDevice");
    at = 3;
  }
  if (!create_device) { printf("-d <dxmt-native> is needed\n"); return 2; }
  if (const char *rescue = getenv("OBELISK_DXMT_QUERY_RESCUE")) once = !strcmp(rescue, "once");
#endif
  if (const char *order = getenv("OBELISK_DXMT_INIT_ORDER")) ordered = ordered || !strcmp(order, "1");
  for (; argc > at && (!strcmp(argv[at], "-once") || !strcmp(argv[at], "-order")); at++) (argv[at][2] == 'n' ? once : ordered) = true;
  const std::string what = argc > at ? argv[at++] : "cases";
  std::thread([] {
    uint64_t last = ~0ull;
    for (int still = 0;;) {
      std::this_thread::sleep_for(std::chrono::seconds(1));
      const uint64_t p = progress;
      still = p == last ? still + 1 : 0;
      last = p;
      if (still >= 20) { say("WATCHDOG nothing progressed for 20 s in %s\nRESULT FAIL\n", doing.load()); leave(3); }
    }
  }).detach();
  g.make();
  { /* how many layers are 40 ms of GPU here */
    ID3D11Query *e = g.query(D3D11_QUERY_EVENT);
    for (int n = 0; n < 3; n++) { g.burn(20); g.ctx->End(e); look_event(e, 0); }
    const uint64_t begin = ns();
    g.burn(200);
    g.ctx->End(e);
    look_event(e, 0);
    const double ms = (ns() - begin) / 1e6;
    layers_40ms = std::max(20u, (unsigned)(200 * 40 / std::max(ms, 1.0)));
    say("QUERYCLIENT 200 layers took %.1f ms: %u for 40 ms\n", ms, layers_40ms);
    e->Release();
  }
  if (what == "soak") {
    doing = "soak";
    const uint64_t seed = argc > at ? strtoull(argv[at++], nullptr, 10) : 1, generations = argc > at ? strtoull(argv[at++], nullptr, 10) : 100000;
    const uint64_t begin = ns();
    soak(seed, generations, argc > at && !strcmp(argv[at], "wide"));
    say("MODE soak frames=1 begin=%llu end=%llu\n", (unsigned long long)begin, (unsigned long long)ns());
  } else if (what == "bench") {
    doing = "bench";
    const char *mode = argc > at ? argv[at++] : "gated";
    const unsigned frames = argc > at ? (unsigned)atoi(argv[at++]) : 300;
    g.use(0);
    g.clear(0, {{0, 0, 0, 255}});
    g.clear(1, {{0, 0, 0, 255}});
    nap_us(50000);
    const uint64_t begin = ns();
    bench(mode, frames);
    say("MODE %s frames=%u begin=%llu end=%llu\n", mode, frames, (unsigned long long)begin, (unsigned long long)ns());
  } else if (what == "pending") {
    doing = current = "pending";
    g.burn(layers_40ms);
    ID3D11Query *a = g.query(D3D11_QUERY_EVENT), *b = g.query(D3D11_QUERY_EVENT);
    g.ctx->End(a);
    g.ctx->Flush();
    g.rect(0, 1, 1, 5, 5, shade(1));
    g.ctx->End(b);
    BOOL t;
    for (int n = 0; n < 200; n++) { g.ctx->GetData(a, &t, sizeof(t), DONT); g.ctx->GetData(b, &t, sizeof(t), DONT); nap_us(50); }
    say("CHECK pending the process ends with queries pending: ok\nRESULT PASS\n");
    leave(0);
  } else {
    for (const Case &c : kCases) {
      bool wanted = argc <= at;
      for (int i = at; i < argc; i++) wanted |= !strcmp(argv[i], c.name);
      if (!wanted) continue;
      doing = current = c.name;
      g.use(0);
      g.clear(0, {{0, 0, 0, 255}});
      g.clear(1, {{0, 0, 0, 255}});
      nap_us(50000);
      const uint64_t begin = ns();
      c.run();
      g.ctx->Flush();
      say("MODE %s frames=1 begin=%llu end=%llu\n", c.name, (unsigned long long)begin, (unsigned long long)ns());
      progress++;
    }
  }
  g.drop();
  say("%d checks, %d failed\nRESULT %s\nDONE\n", checks.load(), failures.load(), failures ? "FAIL" : "PASS");
  leave(failures ? 1 : 0);
}
