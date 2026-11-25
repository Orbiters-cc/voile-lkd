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
| `shapes` | how long a signal takes to stop a thread in each of 59 loop shapes (`shapes_k.S`): every one sent is handled, p99 under 1 ms, the longest under 50 ms (with `--load`: below) |
| `shut lat` | the same through Wine's `SuspendThread` and `GetThreadContext`, 21 shapes |
| `stw` | a collector: one thread suspends 20 or 40 others of 14 kinds, reads and checks every context, resumes them; rounds, slowest round, wrong contexts |
| `shut drv` | the ways a program ends with 28 threads in it: `ExitProcess`, `TerminateProcess`, return from main with threads running or suspended, `TerminateThread` on all, cooperative, a thread pool drained, `ExitProcess` in the middle of stop-the-world rounds; and after such rounds (`G`, where lkd's late attach SIGSTOP freezes the older engines: its lines are counted) |
| `sched` | no thread that runs the guest is ever scheduled otherwise than on the released engine (below): thousands of signals, and of suspensions through Wine, on a busy machine |
| `bench`, `latency` | what the checks cost; how long a signal waits for a thread in the cost kernels (measurements, no checks) |

```sh
./run.py <fexdarwin-run> --group latency --load 8     # on a busy machine
./run.py <fexdarwin-run> --group quit --rounds 400
```

A sample of `shapes` in which the sender itself lost its core while it sent says nothing about the thread and is left out
(`sender_off`); a test fails when that is a quarter of them.

## The guest's threads are scheduled as on the released engine

They are the game's threads, to the game and to its anti-cheat. The engine sets no priority, policy or QoS of theirs, not for a moment
(nor of one that a stop waits for), and nothing in the binary could. `run.py --group sched` checks it on both engines:

- `schedwatch.c`, inserted into the engine, reads of every thread, all the time, every policy flavor that `thread_policy_get` gives, the base
  and the maximal priority, the POSIX policy and priority and the QoS class, and records every call of a function that sets one. Each guest
  thread must have one way to be scheduled from its first look to its last, one that the released engine's have, and there must be no call.
  The current priority, which the scheduler computes, may not go over the base one by more than on the released engine (15: the
  kernel's own doing, on both alike).
- The binary may import none of those functions, nor what could reach one without its name (`dlsym`, `syscall`, `mach_msg`...).

The engine of round 2 (`88554305`), which boosted a thread that was late for its stop, fails both.

## A busy machine

With `--load N` a thread that has lost its core waits for its turn, as a native one does, and for every turn it needs: one to come to its safe
point, sometimes one more for its handler. So the limits are what a signal to a native thread (`native.c`, no emulator in it) needs on the
same machine at the same time: twice its p99 and 1 ms, three times its longest. Measured on an M3 (8 cores), in ms:

| busy threads | | mean | median | p90 | p99 | longest |
|---|---|---|---|---|---|---|
| 0 | a signal, this engine | 0.007 / 0.06 | 0.007 / 0.06 | 0.008 / 0.11 | 0.014 / 0.15 | 0.06 / 6.9 |
| 0 | `SuspendThread`, this engine | 0.13 / 0.16 | 0.13 / 0.13 | 0.14 / 0.14 | 0.18 / 0.49 | 1.4 / 11.5 |
| 8 | a signal, native thread (5 runs) | 0.88 to 0.94 | 0.05 to 0.10 | 2.5 to 3.0 | 9.3 to 9.8 | 14 to 21 |
| 8 | a signal, this engine | 0.67 / 1.4 | 0.06 / 0.10 | 2.2 / 4.8 | 8.9 / 11.3 | 17 / 58 |
| 8 | `SuspendThread`, this engine | 0.48 / 0.56 | 0.37 / 0.48 | 0.68 / 0.87 | 2.5 / 3.7 | 5.7 / 11 |
| 16 | a signal, native thread (5 runs) | 5.7 to 6.1 | 0.15 to 0.67 | 18 to 19 | 34 to 39 | 48 to 88 |
| 16 | a signal, this engine | 5.6 / 6.2 | 0.08 / 0.13 | 20 / 23 | 38 / 46 | 56 / 89 |
| 16 | `SuspendThread`, this engine | 0.70 / 0.81 | 0.35 / 0.46 | 0.67 / 1.0 | 7.8 / 23 | 49 / 57 |

(Of this engine's 59 shapes, 21 through `SuspendThread`: the median of the shapes / the worst one.) The released engine, in the shapes it stops
at once, has the same tail (`jmp`, `pause`, `movalu`: p99 8 to 11 ms with 8, 41 to 48 ms with 16). `SuspendThread` waits less than a signal
does, since its sender sleeps while it waits and leaves its core; `shapes` and `native` spin with `sched_yield`.
A test that is late is tried once more.

On the engine of obelisk-cli 0.1.8 to 0.1.13 (`ff158513`) all of `correct` but the controls fail, most of them within a second. (Moves and exchanges are a
control: that a move merged into the next instruction is lost was read in the translator and never seen.) With code beside data
the released engine delivers so few signals that the test says it could not look. Of `latency`, the loops of loads, indirect jumps, calls,
helpers and string instructions fail on it and on the first round's engine (`d9230810`), and `world` does not complete on either.
