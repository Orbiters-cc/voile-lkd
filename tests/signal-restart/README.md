# Signals, suspensions and faults that are restarted

A thread stopped in translated code (Wine's `SuspendThread`, a signal) or whose fault the guest resolves (a guard page, a write watch) starts
again at a guest instruction, from the registers and the context alone. These programs check that this is invisible to it.

```sh
./run.py <fexdarwin-run>      # every test and its control; `released` for the installed release's own
./run.py <fexdarwin-run> --soak 120 --seeds 3     # longer, with other random programs
```

It reads the other files of the installed release in place, under the library's shared lock, and writes to a work folder alone.
`build.sh` needs an x86-64 clang with ld.lld (`LLVM_BIN`) and the mingw compilers.

| | |
|---|---|
| `sigstorm` | threads in self-checking loops (`sigstorm_k.S`, `audit_k.S`) while another sends them signals. `_far`, `_nop`, `_jmp`: other shapes of the same epilogues; `_split`: no two stack operations beside each other (a control); `_val`: code in a page that is written, whose instructions check their bytes |
| `syncfault` | 76 instructions that fault on an inaccessible or a read-only page; the handler gives the access back and returns. Compared with the same without a fault: registers, flags, memory, and the address the handler was given |
| `soak` | random programs (`gen_soak.py`): each must return the same hash for ever |
| `susp` | the same through the guest Wine: `SuspendThread`, `GetThreadContext`, now and then `SetThreadContext`, `ResumeThread`, as a stop-the-world collector does. `susp_split`: control; `susp_soak`: the random programs; `susp32`: 32-bit code |
| `bench`, `latency` | what the fixes cost; how long a signal waits for a thread in a tight loop (measurements, no checks) |

On the engine of obelisk-cli 0.1.8 to 0.1.13 (`ff158513`) all but the controls fail, most of them within a second. (Moves and exchanges are a
control: that a move merged into the next instruction is lost was read in the translator and never seen.) With code beside data
the released engine delivers so few signals that the test says it could not look.
