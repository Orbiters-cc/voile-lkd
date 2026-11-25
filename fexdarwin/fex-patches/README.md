# Changes to FEX

`scripts/build.sh` applies these patches, in their order, to a copy of the `fex` submodule (`build/fex`) and builds FEXCore from
it; the submodule stays the commit of Zagrios/FEX it names. They are for this engine alone and are not contributions to FEX
(FEX-Emu takes no code written with an AI's help: `fex/AGENTS.md`).

| Patch | |
|---|---|
| 0001 | A unit whose emission starts again (a branch out of range, a full buffer) keeps no instruction entries of the abandoned attempt. They pointed into the middle of other instructions, and a signal there skipped dozens of them. |
| 0002 | `pop [mem]`, and `adc`, `sbb`, `inc`, `dec`, `rcl`, `rcr` to memory, change the stack pointer or the carry after their store, which can fault and be started again. |
| 0003 | The RIP table says which entries are exact boundaries, where a thread can be stopped and started again, and in which form the host's carry is there. Merges of neighbouring instructions (push/push, pop/pop, pop/ret, moves) take the mark away and are made only where no fault is reported; AVX high halves, MMX, x87 and the direction flag are written to the context before an instruction that can fault. |
| 0004 | Asynchronous stops happen at safe points alone, which every unit's entry, every loop and every long string instruction has, and which cost nothing but an access through a pointer until a stop is asked for; 0003's marks for them are gone. The x87 stack is not written to the context before every instruction any more, but kept for the fault handler before those that can fault. |

`tests/signal-restart` holds what fails without them.
