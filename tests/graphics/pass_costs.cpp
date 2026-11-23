/*
 * pass_costs.cpp - owned Direct3D 11 client (Windows x86-64, run through the engine's own Wine): what a frame's passes
 * cost through Neptune, the render server and DXMT. Full screen, borderless, flip-discard swapchain of two RGBA8
 * buffers, as VRChat's. Each mode runs for a few seconds and says when it began and ended, in nanoseconds of
 * QueryPerformanceCounter (CLOCK_MONOTONIC, the host's uptime clock under LKD), so that the host timeline
 * (tools/timeline/otl.py) can be cut by mode.
 *
 * Usage: pass_costs.exe <seconds per mode> <sync interval> [mode ...]      (no mode: all of them)
 * Build: build-pass-costs.sh. Run: run-pass-costs.sh.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d11_4.h>
#include <dxgi1_3.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "dxbc/shaders_dxbc.h"

static ID3D11Device *dev;
static ID3D11DeviceContext *ctx;
static ID3D11DeviceContext1 *ctx1;
static IDXGISwapChain1 *swap;
static UINT W, H;
static ID3D11RenderTargetView *back;
static ID3D11Texture2D *back_tex;

#define HR(x) do { HRESULT hr_ = (x); if (FAILED(hr_)) { printf("FAILED %s 0x%08lx\n", #x, (unsigned long)hr_); fflush(stdout); exit(1); } } while (0)

static unsigned long long ns() {
  LARGE_INTEGER f, c;
  QueryPerformanceFrequency(&f);
  QueryPerformanceCounter(&c);
  return (unsigned long long)c.QuadPart / f.QuadPart * 1000000000ull + (unsigned long long)c.QuadPart % f.QuadPart * 1000000000ull / f.QuadPart;
}

struct Vertex { float pos[2], uv[2], color[4]; };
static const Vertex kFull[3] = {{{-1, -1}, {0, 1}, {.2f, .3f, .4f, 1}}, {{-1, 3}, {0, -1}, {.6f, .3f, .4f, 1}}, {{3, -1}, {2, 1}, {.2f, .7f, .4f, 1}}};
static const Vertex kSmall[3] = {{{0.0f, 0.1f}, {.5f, 0}, {1, 0, 0, 1}}, {{0.1f, -0.1f}, {1, 1}, {0, 0, 1, 1}}, {{-0.1f, -0.1f}, {0, 1}, {0, 1, 0, 1}}};

struct Target {
  ID3D11Texture2D *tex; ID3D11RenderTargetView *rtv; ID3D11ShaderResourceView *srv;
  ID3D11Texture2D *ds; ID3D11DepthStencilView *dsv;
};
static Target target(UINT w, UINT h, UINT samples, bool depth) {
  Target t = {};
  D3D11_TEXTURE2D_DESC d = {w, h, 1, 1, DXGI_FORMAT_R8G8B8A8_UNORM, {samples, 0}, D3D11_USAGE_DEFAULT,
                            D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE, 0, 0};
  HR(dev->CreateTexture2D(&d, nullptr, &t.tex));
  HR(dev->CreateRenderTargetView(t.tex, nullptr, &t.rtv));
  HR(dev->CreateShaderResourceView(t.tex, nullptr, &t.srv));
  if (depth) {
    d.Format = DXGI_FORMAT_D24_UNORM_S8_UINT;
    d.BindFlags = D3D11_BIND_DEPTH_STENCIL;
    HR(dev->CreateTexture2D(&d, nullptr, &t.ds));
    HR(dev->CreateDepthStencilView(t.ds, nullptr, &t.dsv));
  }
  return t;
}

static ID3D11Buffer *vb_full, *vb_small, *cb;
static ID3D11VertexShader *vs;
static ID3D11PixelShader *ps_color, *ps_tex, *ps_cbuf;
static ID3D11InputLayout *layout;
static ID3D11SamplerState *samp;


static void use(ID3D11RenderTargetView *r, ID3D11DepthStencilView *d, UINT w, UINT h) {
  ID3D11ShaderResourceView *none = nullptr;
  ctx->PSSetShaderResources(0, 1, &none);
  ctx->OMSetRenderTargets(r ? 1 : 0, r ? &r : nullptr, d);
  D3D11_VIEWPORT vp = {0, 0, (float)w, (float)h, 0, 1};
  ctx->RSSetViewports(1, &vp);
}
static void tri(ID3D11Buffer *vb, ID3D11PixelShader *ps, ID3D11ShaderResourceView *srv) {
  UINT stride = sizeof(Vertex), off = 0;
  ctx->IASetVertexBuffers(0, 1, &vb, &stride, &off);
  ctx->IASetInputLayout(layout);
  ctx->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
  ctx->VSSetShader(vs, nullptr, 0);
  ctx->PSSetShader(ps, nullptr, 0);
  ctx->PSSetSamplers(0, 1, &samp);
  if (srv) ctx->PSSetShaderResources(0, 1, &srv);
  ctx->Draw(3, 0);
}
static void clear(ID3D11RenderTargetView *r, ID3D11DepthStencilView *d, unsigned f) {
  float c[4] = {0.1f, 0.1f, (f % 60) / 60.0f, 1};
  if (r) ctx->ClearRenderTargetView(r, c);
  if (d) ctx->ClearDepthStencilView(d, D3D11_CLEAR_DEPTH | D3D11_CLEAR_STENCIL, 1, 0);
}

static Target one, two, ms, tiny[8], copy[2];
static ID3D11BlendState *add;
static ID3D11DepthStencilState *less_equal; /* every triangle here has the same depth: the default LESS would draw one */


/* ---- the modes ---- */
static void trivial(unsigned f) { use(back, nullptr, W, H); clear(back, nullptr, f); tri(vb_small, ps_color, nullptr); }
/* four copies of a full-size texture beside the trivial frame: the price of one is a quarter of the difference */
static void copies(unsigned f) {
  trivial(f);
  for (int i = 0; i < 4; i++) ctx->CopyResource(copy[i & 1].tex, copy[~i & 1].tex);
}
/* one full-size colour and depth target drawn once, then drawn to the back buffer */
static void offscreen(unsigned f) {
  use(one.rtv, one.dsv, W, H); clear(one.rtv, one.dsv, f); tri(vb_full, ps_color, nullptr); tri(vb_small, ps_color, nullptr);
  use(back, nullptr, W, H); tri(vb_full, ps_tex, one.srv);
}
static void msaa_scene(unsigned f) {
  use(ms.rtv, ms.dsv, W, H); clear(ms.rtv, ms.dsv, f); tri(vb_full, ps_color, nullptr); tri(vb_small, ps_color, nullptr);
}
/* Unity's: 2x scene, resolve right after it, then the resolved picture to the back buffer */
static void msaa_resolve(unsigned f) {
  msaa_scene(f);
  ctx->ResolveSubresource(one.tex, 0, ms.tex, 0, DXGI_FORMAT_R8G8B8A8_UNORM);
  use(back, nullptr, W, H); tri(vb_full, ps_tex, one.srv);
}
/* the same, and the application says it needs neither the 2x colour nor the depth again */
static void msaa_resolve_discard(unsigned f) {
  msaa_scene(f);
  ctx->ResolveSubresource(one.tex, 0, ms.tex, 0, DXGI_FORMAT_R8G8B8A8_UNORM);
  ctx1->DiscardView(ms.rtv); ctx1->DiscardView(ms.dsv);
  use(back, nullptr, W, H); tri(vb_full, ps_tex, one.srv);
}
static void msaa_discard_first(unsigned f) {
  ctx1->DiscardView(ms.rtv); ctx1->DiscardView(ms.dsv);
  msaa_resolve(f);
}
/* a Flush between the scene and its resolve: the resolve cannot join the pass */
static void msaa_flush_resolve(unsigned f) {
  msaa_scene(f);
  ctx->Flush();
  ctx->ResolveSubresource(one.tex, 0, ms.tex, 0, DXGI_FORMAT_R8G8B8A8_UNORM);
  use(back, nullptr, W, H); tri(vb_full, ps_tex, one.srv);
}
/* a grab in the middle: scene, resolve, sample it while the scene goes on, resolve again */
static void msaa_grab(unsigned f) {
  msaa_scene(f);
  ctx->ResolveSubresource(two.tex, 0, ms.tex, 0, DXGI_FORMAT_R8G8B8A8_UNORM);
  use(ms.rtv, ms.dsv, W, H); tri(vb_small, ps_tex, two.srv);
  ctx->ResolveSubresource(one.tex, 0, ms.tex, 0, DXGI_FORMAT_R8G8B8A8_UNORM);
  use(back, nullptr, W, H); tri(vb_full, ps_tex, one.srv);
}
/* eight small targets drawn between parts of one full-size pass, nothing read: the optimiser can put the parts together */
static void switch_free(unsigned f) {
  use(one.rtv, one.dsv, W, H); clear(one.rtv, one.dsv, f); tri(vb_full, ps_color, nullptr);
  for (int i = 0; i < 8; i++) {
    use(tiny[i].rtv, nullptr, 256, 256); clear(tiny[i].rtv, nullptr, f); tri(vb_small, ps_color, nullptr);
    use(one.rtv, one.dsv, W, H); tri(vb_small, ps_color, nullptr);
  }
  use(back, nullptr, W, H); tri(vb_full, ps_tex, one.srv);
}
/* the same, and each part reads the small target just drawn, and the small target the part before: every switch splits
 * the pass (a full-size store and reload of colour and depth) */
static void switch_bound(unsigned f) {
  use(one.rtv, one.dsv, W, H); clear(one.rtv, one.dsv, f); tri(vb_full, ps_color, nullptr);
  for (int i = 0; i < 8; i++) {
    use(tiny[i].rtv, nullptr, 256, 256); tri(vb_small, ps_tex, one.srv);
    use(one.rtv, one.dsv, W, H); tri(vb_small, ps_tex, tiny[i].srv);
  }
  use(back, nullptr, W, H); tri(vb_full, ps_tex, one.srv);
}
/* each part reads the small target, which reads nothing: only the order small-then-part binds */
static void switch_read(unsigned f) {
  use(one.rtv, one.dsv, W, H); clear(one.rtv, one.dsv, f); tri(vb_full, ps_color, nullptr);
  for (int i = 0; i < 8; i++) {
    use(tiny[i].rtv, nullptr, 256, 256); clear(tiny[i].rtv, nullptr, f); tri(vb_small, ps_color, nullptr);
    use(one.rtv, one.dsv, W, H); tri(vb_small, ps_tex, tiny[i].srv);
  }
  use(back, nullptr, W, H); tri(vb_full, ps_tex, one.srv);
}
/* the two above where every part covers the whole picture (blended, so that none is hidden): the parts shade the same
 * pixels in both, and only the second has to store and load them between */
static void parts_full(Target &t, unsigned f) {
  use(t.rtv, t.dsv, W, H); clear(t.rtv, t.dsv, f); tri(vb_full, ps_color, nullptr);
  ctx->OMSetBlendState(add, nullptr, ~0u);
  for (int i = 0; i < 8; i++) {
    use(tiny[i].rtv, nullptr, 256, 256);
    tri(vb_small, ps_color, nullptr);
    use(t.rtv, t.dsv, W, H); tri(vb_full, ps_tex, tiny[i].srv);
  }
  ctx->OMSetBlendState(nullptr, nullptr, ~0u);
}
static void full_free(unsigned f) {
  parts_full(one, f);
  use(back, nullptr, W, H); tri(vb_full, ps_tex, one.srv);
}
/* eight parts of the picture, each covering it, with a target in between that reads the picture so far */
static void full_bound(unsigned f) {
  use(one.rtv, one.dsv, W, H); clear(one.rtv, one.dsv, f); tri(vb_full, ps_color, nullptr);
  for (int i = 0; i < 8; i++) {
    use(tiny[i].rtv, nullptr, 256, 256); tri(vb_small, ps_tex, one.srv);
    ctx->OMSetBlendState(add, nullptr, ~0u);
    use(one.rtv, one.dsv, W, H); tri(vb_full, ps_tex, tiny[i].srv);
    ctx->OMSetBlendState(nullptr, nullptr, ~0u);
  }
  use(back, nullptr, W, H); tri(vb_full, ps_tex, one.srv);
}
/* the same at 2x: the picture cannot be read while it is 2x, so a resolve (a grab pass) is what splits it */
static void msaa_full_free(unsigned f) {
  parts_full(ms, f);
  ctx->ResolveSubresource(one.tex, 0, ms.tex, 0, DXGI_FORMAT_R8G8B8A8_UNORM);
  use(back, nullptr, W, H); tri(vb_full, ps_tex, one.srv);
}
static void msaa_full_bound(unsigned f) {
  use(ms.rtv, ms.dsv, W, H); clear(ms.rtv, ms.dsv, f); tri(vb_full, ps_color, nullptr);
  for (int i = 0; i < 8; i++) {
    ctx->ResolveSubresource(two.tex, 0, ms.tex, 0, DXGI_FORMAT_R8G8B8A8_UNORM);
    use(tiny[i].rtv, nullptr, 256, 256); tri(vb_small, ps_tex, two.srv);
    ctx->OMSetBlendState(add, nullptr, ~0u);
    use(ms.rtv, ms.dsv, W, H); tri(vb_full, ps_tex, tiny[i].srv);
    ctx->OMSetBlendState(nullptr, nullptr, ~0u);
  }
  ctx->ResolveSubresource(one.tex, 0, ms.tex, 0, DXGI_FORMAT_R8G8B8A8_UNORM);
  use(back, nullptr, W, H); tri(vb_full, ps_tex, one.srv);
}
/* an upload (UpdateSubresource of a small texture: a blit) between parts of one full-size pass */
static unsigned char pixels[64 * 64 * 4];
static ID3D11Texture2D *upload_tex;
static ID3D11ShaderResourceView *upload_srv;
static void upload_mid(unsigned f) {
  use(one.rtv, one.dsv, W, H); clear(one.rtv, one.dsv, f); tri(vb_full, ps_color, nullptr);
  for (int i = 0; i < 8; i++) {
    pixels[f % sizeof(pixels)] ^= 255;
    ctx->UpdateSubresource(upload_tex, 0, nullptr, pixels, 256, 0);
    tri(vb_small, ps_tex, upload_srv);
  }
  use(back, nullptr, W, H); tri(vb_full, ps_tex, one.srv);
}
/* a 2x scene with the depth read back by a later pass is left out: D3D11 depth reads are a copy or a resolve */
/* the decode and encode side: 2000 draws with a mapped constant buffer each, 100 target switches */
static void draws(unsigned f) {
  for (int s = 0; s < 100; s++) {
    Target &t = tiny[s & 7];
    use(t.rtv, nullptr, 256, 256);
    for (int i = 0; i < 20; i++) {
      D3D11_MAPPED_SUBRESOURCE m;
      HR(ctx->Map(cb, 0, D3D11_MAP_WRITE_DISCARD, 0, &m));
      float c[4] = {i / 20.0f, (f % 30) / 30.0f, s / 100.0f, 1};
      memcpy(m.pData, c, sizeof(c));
      ctx->Unmap(cb, 0);
      ctx->PSSetConstantBuffers(0, 1, &cb);
      tri(vb_small, ps_cbuf, nullptr);
    }
  }
  trivial(f);
}
/* the GPU's side: 60 full-screen textured triangles on a 2x target, blended, so that the GPU shades them all */
static void heavy(unsigned f) {
  use(ms.rtv, ms.dsv, W, H); clear(ms.rtv, ms.dsv, f);
  ctx->OMSetBlendState(add, nullptr, ~0u);
  for (int i = 0; i < 60; i++) tri(vb_full, ps_tex, copy[i & 1].srv);
  ctx->OMSetBlendState(nullptr, nullptr, ~0u);
  ctx->ResolveSubresource(one.tex, 0, ms.tex, 0, DXGI_FORMAT_R8G8B8A8_UNORM);
  use(back, nullptr, W, H); tri(vb_full, ps_tex, one.srv);
}

/* ---- what a game does in the middle of a scene, and whether the renderer pays for it with a split of the pass ----
 * The scene of all of these is VRChat's shape: one full-size 2x colour and depth, 266 draws with a constant buffer each, half of
 * them covering the picture (so that the GPU is the limiter and frames overlap), a 256 x 256 target drawn after every 40; then
 * the resolve and the back buffer. `at` is called before draw number n. */
static ID3D11Buffer *vb_dyn, *default_buf;
static ID3D11Texture2D *staging_tex, *dyn_tex;
static ID3D11Query *occ[4], *stamps[4], *disjoint[4], *events[4];
static unsigned long long polls, polled_ready;

static void constant(float a, float b, float c) {
  D3D11_MAPPED_SUBRESOURCE m;
  HR(ctx->Map(cb, 0, D3D11_MAP_WRITE_DISCARD, 0, &m));
  float v[4] = {a, b, c, 1};
  memcpy(m.pData, v, sizeof(v));
  ctx->Unmap(cb, 0);
  ctx->PSSetConstantBuffers(0, 1, &cb);
}
static void scene_with(unsigned f, void (*at)(unsigned f, int n), bool between = true) {
  use(ms.rtv, ms.dsv, W, H); clear(ms.rtv, ms.dsv, f);
  ctx->OMSetBlendState(add, nullptr, ~0u);
  for (int n = 0; n < 266; n++) {
    if (at) at(f, n);
    if (between && n % 40 == 39) {
      Target &t = tiny[n / 40 % 8];
      use(t.rtv, nullptr, 256, 256); clear(t.rtv, nullptr, f); tri(vb_small, ps_color, nullptr);
      use(ms.rtv, ms.dsv, W, H);
    }
    constant(n / 266.0f, (f % 30) / 30.0f, .2f);
    if (n % 2 == 0) tri(vb_full, ps_tex, copy[n >> 1 & 1].srv);
    else tri(vb_small, ps_cbuf, nullptr);
  }
  ctx->OMSetBlendState(nullptr, nullptr, ~0u);
  ctx->ResolveSubresource(one.tex, 0, ms.tex, 0, DXGI_FORMAT_R8G8B8A8_UNORM);
  use(back, nullptr, W, H); tri(vb_full, ps_tex, one.srv);
}
static void poll(ID3D11Query *q, UINT flags) {
  UINT64 out[4];
  polls++;
  if (ctx->GetData(q, out, q->GetDataSize(), flags) == S_OK) polled_ready++;
}
/* nothing of it */
static void q_none(unsigned f) { scene_with(f, nullptr); }
/* an event query ended once a frame, after the picture, and looked at (DONOTFLUSH) as the next frame begins: what an engine's
 * frame pacing does. The host polls it every 100 us from then on. */
static void q_event_frame(unsigned f) {
  if (f > 3) poll(events[(f + 1) & 3], D3D11_ASYNC_GETDATA_DONOTFLUSH);
  scene_with(f, nullptr);
  ctx->End(events[f & 3]);
}
/* the same, the host told to look at nothing: the query is never ended (as q_none) but a timestamp disjoint pair is */
static void q_disjoint_frame(unsigned f) {
  if (f > 3) poll(disjoint[(f + 1) & 3], D3D11_ASYNC_GETDATA_DONOTFLUSH);
  ctx->Begin(disjoint[f & 3]);
  ctx->End(stamps[f & 3]);
  scene_with(f, nullptr);
  ctx->End(disjoint[f & 3]);
}
/* an event query ended in the middle of the scene (a fence an engine puts after its uploads) */
static void at_event(unsigned f, int n) { if (n == 133) ctx->End(events[f & 3]); }
static void q_event_mid(unsigned f) { scene_with(f, at_event); }
/* four timestamps in the scene (a GPU profiler's) */
static void at_stamp(unsigned f, int n) { if (n % 66 == 33) ctx->End(stamps[n / 66 & 3]); (void)f; }
static void q_stamp_mid(unsigned f) { scene_with(f, at_stamp); }
/* four occlusion queries in the scene (lens flares, visibility), the results of the frame before looked at first */
static void at_occ(unsigned f, int n) {
  if (n == 0 && f > 3) for (auto q : occ) poll(q, D3D11_ASYNC_GETDATA_DONOTFLUSH);
  if (n % 66 == 30) ctx->Begin(occ[n / 66 & 3]);
  if (n % 66 == 34) ctx->End(occ[n / 66 & 3]);
}
static void q_occ_mid(unsigned f) { scene_with(f, at_occ); }
/* the same queries around draws, and no target drawn between the parts of the scene */
static void q_occ_alone(unsigned f) { scene_with(f, at_occ, false); }
/* a query looked at without DONOTFLUSH while the scene is recorded */
static void at_poll_flush(unsigned f, int n) { if (n % 66 == 33 && f > 3) poll(events[(f + 3) & 3], 0); }
static void q_event_pollflush(unsigned f) { scene_with(f, at_poll_flush); ctx->End(events[f & 3]); }
/* a dynamic vertex buffer written before each draw: discarded, or appended to */
static void at_discard(unsigned, int n) {
  D3D11_MAPPED_SUBRESOURCE m;
  if (n % 4) return;
  HR(ctx->Map(vb_dyn, 0, D3D11_MAP_WRITE_DISCARD, 0, &m));
  memcpy(m.pData, kSmall, sizeof(kSmall));
  ctx->Unmap(vb_dyn, 0);
  tri(vb_dyn, ps_color, nullptr);
}
static void m_discard(unsigned f) { scene_with(f, at_discard); }
static void at_nooverwrite(unsigned, int n) {
  D3D11_MAPPED_SUBRESOURCE m;
  if (n % 4) return;
  HR(ctx->Map(vb_dyn, 0, n ? D3D11_MAP_WRITE_NO_OVERWRITE : D3D11_MAP_WRITE_DISCARD, 0, &m));
  memcpy((char *)m.pData + n / 4 * sizeof(kSmall), kSmall, sizeof(kSmall));
  ctx->Unmap(vb_dyn, 0);
  UINT stride = sizeof(Vertex), off = n / 4 * (UINT)sizeof(kSmall);
  tri(vb_dyn, ps_color, nullptr);
  ctx->IASetVertexBuffers(0, 1, &vb_dyn, &stride, &off);
}
static void m_nooverwrite(unsigned f) { scene_with(f, at_nooverwrite); }
/* a dynamic texture written (a blit into it, which ends the pass) */
static void at_dyntex(unsigned f, int n) {
  if (n % 66 != 33) return;
  D3D11_MAPPED_SUBRESOURCE m;
  HR(ctx->Map(dyn_tex, 0, D3D11_MAP_WRITE_DISCARD, 0, &m));
  for (int y = 0; y < 64; y++) memset((char *)m.pData + y * m.RowPitch, (int)(f + y), 256);
  ctx->Unmap(dyn_tex, 0);
}
static void m_dyntex(unsigned f) { scene_with(f, at_dyntex); }
/* UpdateSubresource of a default buffer nobody reads in this frame */
static void at_update(unsigned f, int n) {
  if (n % 66 == 33) { float v[4] = {(float)f, (float)n, 0, 1}; ctx->UpdateSubresource(default_buf, 0, nullptr, v, 0, 0); }
}
static void m_update(unsigned f) { scene_with(f, at_update); }
/* a small readback: a copy to a staging texture in the middle of the scene, mapped (DO_NOT_WAIT) frames later */
static void at_readback(unsigned f, int n) {
  if (n == 133) ctx->CopySubresourceRegion(staging_tex, 0, 0, 0, 0, tiny[0].tex, 0, nullptr);
  if (n == 0 && f > 3) {
    D3D11_MAPPED_SUBRESOURCE m;
    if (ctx->Map(staging_tex, 0, D3D11_MAP_READ, D3D11_MAP_FLAG_DO_NOT_WAIT, &m) == S_OK) ctx->Unmap(staging_tex, 0);
  }
}
static void m_readback(unsigned f) { scene_with(f, at_readback); }
/* the same once a frame, after the picture: an engine's asynchronous readback */
static void m_readback_end(unsigned f) {
  scene_with(f, nullptr);
  ctx->CopySubresourceRegion(staging_tex, 0, 0, 0, 0, tiny[0].tex, 0, nullptr);
  ctx->End(events[f & 3]);
}
/* Flush in the middle */
static void at_flush(unsigned, int n) { if (n == 133) ctx->Flush(); }
static void m_flush(unsigned f) { scene_with(f, at_flush); }

struct Mode { const char *name; void (*frame)(unsigned); };
static const Mode kModes[] = {
    {"trivial", trivial}, {"copies4", copies}, {"offscreen", offscreen}, {"msaa-resolve", msaa_resolve},
    {"msaa-resolve-discard", msaa_resolve_discard}, {"msaa-discard-first", msaa_discard_first},
    {"msaa-flush-resolve", msaa_flush_resolve}, {"msaa-grab", msaa_grab}, {"switch8-free", switch_free},
    {"switch8-read", switch_read}, {"switch8-bound", switch_bound}, {"full8-free", full_free}, {"full8-bound", full_bound},
    {"msaa-full8-free", msaa_full_free}, {"msaa-full8-bound", msaa_full_bound}, {"upload8", upload_mid}, {"draws2000", draws},
    {"heavy60", heavy},
    {"q-none", q_none}, {"q-event-frame", q_event_frame}, {"q-disjoint-frame", q_disjoint_frame}, {"q-event-mid", q_event_mid},
    {"q-stamp-mid", q_stamp_mid}, {"q-occ-mid", q_occ_mid}, {"q-occ-alone", q_occ_alone}, {"q-event-pollflush", q_event_pollflush},
    {"m-discard", m_discard}, {"m-nooverwrite", m_nooverwrite}, {"m-dyntex", m_dyntex}, {"m-update", m_update},
    {"m-readback", m_readback}, {"m-readback-end", m_readback_end}, {"m-flush", m_flush},
};

static LRESULT CALLBACK proc(HWND h, UINT m, WPARAM w, LPARAM l) { return DefWindowProcA(h, m, w, l); }
static void pump() {
  MSG m;
  while (PeekMessageA(&m, nullptr, 0, 0, PM_REMOVE)) { TranslateMessage(&m); DispatchMessageA(&m); }
}

int main(int argc, char **argv) {
  setvbuf(stdout, nullptr, _IONBF, 0);
  double seconds = argc > 1 ? atof(argv[1]) : 3;
  UINT interval = argc > 2 ? (UINT)atoi(argv[2]) : 0;
  W = (UINT)GetSystemMetrics(SM_CXSCREEN);
  H = (UINT)GetSystemMetrics(SM_CYSCREEN);
  WNDCLASSA wc = {};
  wc.lpfnWndProc = proc;
  wc.hInstance = GetModuleHandleA(nullptr);
  wc.lpszClassName = "pass_costs";
  RegisterClassA(&wc);
  HWND win = CreateWindowExA(0, "pass_costs", "pass_costs", WS_POPUP | WS_VISIBLE, 0, 0, (int)W, (int)H, nullptr, nullptr, wc.hInstance, nullptr);
  ShowWindow(win, SW_SHOW);
  SetForegroundWindow(win);
  pump();

  D3D_FEATURE_LEVEL want = D3D_FEATURE_LEVEL_11_0, got;
  HR(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0, &want, 1, D3D11_SDK_VERSION, &dev, &got, &ctx));
  HR(ctx->QueryInterface(__uuidof(ID3D11DeviceContext1), (void **)&ctx1));
  IDXGIDevice1 *dd; IDXGIAdapter *ad; IDXGIFactory2 *fac;
  HR(dev->QueryInterface(__uuidof(IDXGIDevice1), (void **)&dd));
  HR(dd->GetAdapter(&ad));
  HR(ad->GetParent(__uuidof(IDXGIFactory2), (void **)&fac));
  DXGI_SWAP_CHAIN_DESC1 sd = {};
  sd.Width = W; sd.Height = H; sd.Format = DXGI_FORMAT_R8G8B8A8_UNORM; sd.SampleDesc.Count = 1;
  sd.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT; sd.BufferCount = 2; sd.SwapEffect = DXGI_SWAP_EFFECT_FLIP_DISCARD;
  HR(fac->CreateSwapChainForHwnd(dev, win, &sd, nullptr, nullptr, &swap));
  HR(swap->GetBuffer(0, __uuidof(ID3D11Texture2D), (void **)&back_tex));
  HR(dev->CreateRenderTargetView(back_tex, nullptr, &back));

  HR(dev->CreateVertexShader(dxbc_vs_pass, sizeof(dxbc_vs_pass), nullptr, &vs));
  HR(dev->CreatePixelShader(dxbc_ps_color, sizeof(dxbc_ps_color), nullptr, &ps_color));
  HR(dev->CreatePixelShader(dxbc_ps_tex, sizeof(dxbc_ps_tex), nullptr, &ps_tex));
  HR(dev->CreatePixelShader(dxbc_ps_cbuf, sizeof(dxbc_ps_cbuf), nullptr, &ps_cbuf));
  D3D11_INPUT_ELEMENT_DESC il[] = {{"POSITION", 0, DXGI_FORMAT_R32G32_FLOAT, 0, 0, D3D11_INPUT_PER_VERTEX_DATA, 0},
                                   {"TEXCOORD", 0, DXGI_FORMAT_R32G32_FLOAT, 0, 8, D3D11_INPUT_PER_VERTEX_DATA, 0},
                                   {"COLOR", 0, DXGI_FORMAT_R32G32B32A32_FLOAT, 0, 16, D3D11_INPUT_PER_VERTEX_DATA, 0}};
  HR(dev->CreateInputLayout(il, 3, dxbc_vs_pass, sizeof(dxbc_vs_pass), &layout));
  D3D11_BUFFER_DESC bd = {sizeof(kFull), D3D11_USAGE_IMMUTABLE, D3D11_BIND_VERTEX_BUFFER, 0, 0, 0};
  D3D11_SUBRESOURCE_DATA init = {kFull, 0, 0};
  HR(dev->CreateBuffer(&bd, &init, &vb_full));
  init.pSysMem = kSmall;
  HR(dev->CreateBuffer(&bd, &init, &vb_small));
  bd = {16, D3D11_USAGE_DYNAMIC, D3D11_BIND_CONSTANT_BUFFER, D3D11_CPU_ACCESS_WRITE, 0, 0};
  HR(dev->CreateBuffer(&bd, nullptr, &cb));
  D3D11_SAMPLER_DESC sm = {};
  sm.Filter = D3D11_FILTER_MIN_MAG_MIP_LINEAR;
  sm.AddressU = sm.AddressV = sm.AddressW = D3D11_TEXTURE_ADDRESS_CLAMP;
  sm.MaxLOD = D3D11_FLOAT32_MAX;
  HR(dev->CreateSamplerState(&sm, &samp));
  D3D11_BLEND_DESC bl = {};
  bl.RenderTarget[0].BlendEnable = TRUE;
  bl.RenderTarget[0].SrcBlend = bl.RenderTarget[0].DestBlend = D3D11_BLEND_ONE;
  bl.RenderTarget[0].SrcBlendAlpha = bl.RenderTarget[0].DestBlendAlpha = D3D11_BLEND_ONE;
  bl.RenderTarget[0].BlendOp = bl.RenderTarget[0].BlendOpAlpha = D3D11_BLEND_OP_ADD;
  bl.RenderTarget[0].RenderTargetWriteMask = 15;
  HR(dev->CreateBlendState(&bl, &add));
  D3D11_DEPTH_STENCIL_DESC dd2 = {};
  dd2.DepthEnable = TRUE;
  dd2.DepthWriteMask = D3D11_DEPTH_WRITE_MASK_ALL;
  dd2.DepthFunc = D3D11_COMPARISON_LESS_EQUAL;
  HR(dev->CreateDepthStencilState(&dd2, &less_equal));
  ctx->OMSetDepthStencilState(less_equal, 0);
  D3D11_TEXTURE2D_DESC ud = {64, 64, 1, 1, DXGI_FORMAT_R8G8B8A8_UNORM, {1, 0}, D3D11_USAGE_DEFAULT, D3D11_BIND_SHADER_RESOURCE, 0, 0};
  HR(dev->CreateTexture2D(&ud, nullptr, &upload_tex));
  HR(dev->CreateShaderResourceView(upload_tex, nullptr, &upload_srv));
  one = target(W, H, 1, true);
  two = target(W, H, 1, false);
  ms = target(W, H, 2, true);
  for (auto &t : copy) t = target(W, H, 1, false);
  for (auto &t : tiny) t = target(256, 256, 1, false);
  bd = {(UINT)(sizeof(kSmall) * 67), D3D11_USAGE_DYNAMIC, D3D11_BIND_VERTEX_BUFFER, D3D11_CPU_ACCESS_WRITE, 0, 0};
  HR(dev->CreateBuffer(&bd, nullptr, &vb_dyn));
  bd = {16, D3D11_USAGE_DEFAULT, D3D11_BIND_CONSTANT_BUFFER, 0, 0, 0};
  HR(dev->CreateBuffer(&bd, nullptr, &default_buf));
  D3D11_TEXTURE2D_DESC sd2 = {256, 256, 1, 1, DXGI_FORMAT_R8G8B8A8_UNORM, {1, 0}, D3D11_USAGE_STAGING, 0, D3D11_CPU_ACCESS_READ, 0};
  HR(dev->CreateTexture2D(&sd2, nullptr, &staging_tex));
  D3D11_TEXTURE2D_DESC td2 = {64, 64, 1, 1, DXGI_FORMAT_R8G8B8A8_UNORM, {1, 0}, D3D11_USAGE_DYNAMIC, D3D11_BIND_SHADER_RESOURCE, D3D11_CPU_ACCESS_WRITE, 0};
  HR(dev->CreateTexture2D(&td2, nullptr, &dyn_tex));
  for (int i = 0; i < 4; i++) {
    D3D11_QUERY_DESC q = {D3D11_QUERY_OCCLUSION, 0};
    HR(dev->CreateQuery(&q, &occ[i]));
    q.Query = D3D11_QUERY_TIMESTAMP; HR(dev->CreateQuery(&q, &stamps[i]));
    q.Query = D3D11_QUERY_TIMESTAMP_DISJOINT; HR(dev->CreateQuery(&q, &disjoint[i]));
    q.Query = D3D11_QUERY_EVENT; HR(dev->CreateQuery(&q, &events[i]));
  }
  printf("PASSCOSTS size=%ux%u seconds=%.1f interval=%u\n", W, H, seconds, interval);

  for (const Mode &m : kModes) {
    bool wanted = argc <= 3;
    for (int i = 3; i < argc; i++) wanted |= !strcmp(argv[i], m.name);
    if (!wanted) continue;
    for (unsigned f = 0; f < 10; f++) { m.frame(f); HR(swap->Present(interval, 0)); pump(); } /* pipelines, first use */
    Sleep(200);
    unsigned f = 0;
    polls = polled_ready = 0;
    unsigned long long begin = ns(), record = 0, present = 0, now = begin;
    while (now - begin < (unsigned long long)(seconds * 1e9)) {
      unsigned long long a = ns();
      m.frame(f++);
      unsigned long long b = ns();
      HRESULT hr = swap->Present(interval, 0);
      now = ns();
      record += b - a; present += now - b;
      if (FAILED(hr)) { printf("FAILED Present 0x%08lx\n", (unsigned long)hr); return 1; }
      pump();
    }
    printf("MODE %s frames=%u begin=%llu end=%llu fps=%.2f record_ms=%.3f present_ms=%.3f polls=%llu ready=%llu\n", m.name, f, begin, now,
           f * 1e9 / (double)(now - begin), record / 1e6 / f, present / 1e6 / f, polls, polled_ready);
    Sleep(150);
  }
  printf("DONE\n");
  return 0;
}
