// SPDX-License-Identifier: MIT
#pragma once

#include "Host.h"

#include <FEXCore/Core/SignalDelegator.h>
#include <csignal>

class DarwinSignalDelegator final : public FEXCore::SignalDelegator {
public:
  // Installs the process-wide handlers for the synchronous signals FEXCore depends on.
  void Install();
  // Per-thread setup: alternate signal stack. Call on the host thread that will run the guest thread.
  void RegisterThread(GuestThread* T);
  void UnregisterThread(GuestThread* T);

  // Copies the statically allocated registers and flags out of a host signal context into the thread state, so the guest
  // state in Thread->CurrentFrame->State is exact at the faulting instruction (port of SignalDelegator::SpillSRA).
  void SpillSRA(FEXCore::Core::InternalThreadState* Thread, ucontext_t* Uc, uint32_t IgnoreMask);
  // The same at a guest instruction whose address and whose form of the carry flag are known.
  void SpillSRAAt(FEXCore::Core::InternalThreadState* Thread, ucontext_t* Uc, uint32_t IgnoreMask, uint64_t Rip, bool CarryNotInverted);

  // Invalidate the translations of [Start, Start + Len) in every thread, then run After while the locks are held.
  void InvalidateGuestCodeRange(FEXCore::Core::InternalThreadState* CallingThread, uint64_t Start, uint64_t Len,
                                FEXCore::Context::CodeRangeInvalidationFn After = {});

  // A synchronous fault in guest code, expressed the way the Linux kernel reports it to the guest.
  struct GuestFault {
    int Signal;       // Linux signal number
    int SiCode;       // Linux si_code
    uint64_t Addr;    // si_addr
    uint64_t TrapNo;  // x86 trap number stored in sigcontext
    uint64_t Err;     // x86 error code stored in sigcontext
  };
  // Builds an x86-64 rt_sigframe on the guest stack and redirects the thread to the guest handler. The host thread is
  // resumed at the top of the FEX dispatcher loop with the host stack reset (synchronous faults never return to the
  // interrupted translated code). Returns false when the guest has no usable handler for the signal.
  bool DeliverGuestSignal(GuestThread* T, ucontext_t* Uc, const GuestFault& F, bool StateIsSpilled);

  // Asynchronous stops of a thread that runs translated code. RequestStop, from any thread for as long as T lives, makes it fault at
  // its next safe point (FEXCore::Context::SafepointAt): the entry of a unit, the head of a loop, the next part of a repeated string
  // instruction. The fault handler resumes it at the kick trampoline if a signal is pending. WithdrawStop, on the thread itself,
  // before it looks whether one is: what is queued after that look requests a stop again.
  void RequestStop(GuestThread* T);
  void WithdrawStop(GuestThread* T);
  bool StopRequested(const GuestThread* T) const;
  // Thread dump: the guest registers of a thread whose host thread is suspended in translated code. Best effort: RIP is the start of the
  // guest instruction the host instruction belongs to. False when it is somewhere else. Takes no lock, allocates nothing.
  bool PeekRegisters(const GuestThread* T, uint64_t HostPc, const uint64_t* HostGprs, uint64_t* Rip, uint64_t Gregs[16]) const;
  uint64_t LoopTopFillSRA() const {
    return Config.AbsoluteLoopTopAddressFillSRA;
  }

private:
  static void Handler(int Sig, siginfo_t* Info, void* Uc);
  bool HandleSafepoint(GuestThread* T, ucontext_t* Uc);
  bool HandleFault(GuestThread* T, int Sig, siginfo_t* Info, ucontext_t* Uc);
  bool HandleSmcWrite(GuestThread* T, int Sig, siginfo_t* Info, ucontext_t* Uc);
  bool HandleGuestFault(GuestThread* T, int Sig, siginfo_t* Info, ucontext_t* Uc);
  bool BeginGuardStep(GuestThread* T, ucontext_t* Uc, uint64_t Page);
  void EndGuardStep(GuestThread* T, ucontext_t* Uc);
  bool ResolveGuardedFault(GuestThread* T, ucontext_t* Uc, uint64_t Addr, bool Write, bool InJit);
  // What CpuStateFrame::SafepointPtr is while a stop is requested: one host page that nothing may access.
  uint64_t SafepointPage {};
  [[noreturn]] void Crash(GuestThread* T, int Sig, siginfo_t* Info, ucontext_t* Uc, const char* Why);
};

// Ends a guard step (DarwinSignalDelegator::BeginGuardStep) before its trap: closes the pages it opened and clears the
// trap flag it set. Run before a guest signal frame is built in the middle of a step, so the guest never sees that trap
// flag; the instruction faults again after the handler and is stepped anew. No-op when the thread is not stepping.
void CancelGuardStep(GuestThread* T);
