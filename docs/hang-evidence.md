# What a hung engine shows

Nothing here needs a debugger, entitlements or `sudo`, and nothing is sent to the guest.

## A process that hangs now

```sh
E=<the engine folder>/fexdarwin-run          # any copy that knows --dump (8f57d4f and later); the processes must be of such a one too
$E --dump                                    # every fexdarwin-run of this user; or: $E --dump <host pid>...
sleep 3; $E --dump                           # again: what moved between the two
for p in $(pgrep -x fexdarwin-run); do sample $p 3 -file sample-$p.txt; done   # the wineserver too
```

It prints where each process wrote its dump: `fexdarwin-dump-<host pid>-<n>.txt` in the user's temporary folder
(`getconf DARWIN_USER_TEMP_DIR`), whatever the environments are. It asks with the host signal SIGINFO, which an engine without this
ignores (it is then said to have written none); no handler runs in the process, its watch thread sees the signal in a kernel queue. The
dump takes about 0.1 s and never waits for a lock; a host thread is suspended for as long as its registers are copied.

A dump holds, in this order:

| | |
|---|---|
| host threads | name, state, backtrace of every host thread: who waits for an engine or LKD lock, who is past one |
| `locks held:` | the locks of the engine (`ThreadsLock`, `SigLock`, `DeadLock`, `KickLock`, `CodeInvalidationMutex`), the VMA table's and LKD's static mutexes that could not be taken at that moment. `none` on two dumps in a row: nobody holds one for ever |
| per guest thread | `== tid N in syscall nr ...` with its arguments (a futex: the word and its neighbours), `in translated code`, or `in the engine` (a helper, the compiler, the dispatcher: see its host backtrace) |
| | `STOP REQUESTED n ms ago`: a signal or a suspension the thread has not seen, whether its next safe point is armed, whether it runs before others for it. More than a few ms old: that is the defect. `NO safe point armed` with it: a lost request |
| | `signals:` whether LKD has one to deliver, the pending and blocked sets, the task's flags: to die, to stop with its group (a job-control stop), in a ptrace stop |
| | `rip` with module and offset, the registers (of a thread in translated code the host's, exact to the instruction), and the stack words that point into code |

## From the start of a session

- `FEXDARWIN_DUMP_DIR=<folder>` in the engine's environment: writing `<folder>/dump-request` makes every process of the family dump into
  that folder. Works on the engines before `--dump` too.
- `FEXDARWIN_KICK_LOG=<ms>`: a line on stderr for every stop that a thread came to later than that after it was asked for
  (`stopped 812 us after the kick`, `, boosted`: the scheduler had kept it off its core). 0: every one.
- The engine says on stderr `A loop without a safe point in the unit at <address>` when it translates one: no signal would reach a thread
  in it. It has never been seen; it is a defect of the translator when it is.
- lkd's log lines `signal 19 ... stops process` and `dropped the attach SIGSTOP` name the freeze of an attach that came too late.
