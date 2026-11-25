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
| `repstorm` | string instructions of random lengths, directions and overlaps under signals, against the same done one element at a time; how many stops came inside one |
| `syncfault` | 76 instructions that fault on an inaccessible or a read-only page; the handler gives the access back and returns. Compared with the same without a fault: registers, flags, memory, and the address the handler was given |
| `soak` | random programs (`gen_soak.py`): each must return the same hash for ever |
| `susp` | the same through the guest Wine: `SuspendThread`, `GetThreadContext`, now and then `SetThreadContext`, `ResumeThread`, as a stop-the-world collector does. `susp_split`: control; `susp_soak`: the random programs; `susp32`: 32-bit code |
| `x87fault` | random x87 programs (`gen_x87.py`) with one instruction that faults: what is on the stack and not in the context yet |
| `shapes` | how long a signal takes to stop a thread in each of 59 loop shapes (`shapes_k.S`): every one sent is handled, p99 under 1 ms, the longest under 50 ms (100 ms with `--load`) |
| `shut lat` | the same through Wine's `SuspendThread` and `GetThreadContext`, 21 shapes (p99 under 10 ms with `--load`: the wineserver waits for its core too) |
| `stw` | a collector: one thread suspends 20 or 40 others of 14 kinds, reads and checks every context, resumes them; rounds, slowest round, wrong contexts |
| `shut drv` | the ways a program ends with 28 threads in it: `ExitProcess`, `TerminateProcess`, return from main with threads running or suspended, `TerminateThread` on all, cooperative, a thread pool drained, `ExitProcess` in the middle of stop-the-world rounds; and after such rounds (`G`, where lkd's late attach SIGSTOP freezes the older engines: its lines are counted) |
| `bench`, `latency` | what the checks cost; how long a signal waits for a thread in the cost kernels (measurements, no checks) |

```sh
./run.py <fexdarwin-run> --group latency --load 8     # on a busy machine
./run.py <fexdarwin-run> --group quit --rounds 400
```

A sample of `shapes` in which the sender itself lost its core while it sent says nothing about the thread and is left out
(`sender_off`); a test fails when that is a quarter of them. With `--load`, a latency test that is late is tried once more: after its stop
a thread may lose its core before it runs a line of its handler, and wait for the next turn like any other.

On the engine of obelisk-cli 0.1.8 to 0.1.13 (`ff158513`) all of `correct` but the controls fail, most of them within a second. (Moves and exchanges are a
control: that a move merged into the next instruction is lost was read in the translator and never seen.) With code beside data
the released engine delivers so few signals that the test says it could not look. Of `latency`, the loops of loads, indirect jumps, calls,
helpers and string instructions fail on it and on the first round's engine (`d9230810`), and `world` does not complete on either.
