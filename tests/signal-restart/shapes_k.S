/* Loop shapes for the latency of a stop. Each s_*(void *mem) never returns (sysv: mem in rdi).
 * mem: 64 KiB, mem[0] = 1 (a lock that is held), mem[8] = 0 (a flag that never comes), 0x1000.. scratch. */
.text
.macro SHAPE name
.globl \name
.p2align 6
\name:
    movq %rdi,%r14
    leaq 0x8000(%rdi),%rsp      /* a stack of its own inside mem, so pushes are harmless */
    xorl %eax,%eax
    xorl %ebx,%ebx
    movl $1,%ecx
    movl $7,%edx
.p2align 5
.endm

/* 1 host instruction: a jump to itself */
SHAPE s_jmp
1:  jmp 1b

/* pause; jmp */
SHAPE s_pause
1:  pause
    jmp 1b

/* the waiting loop of a spinlock: pause; cmp [mem],0; jne */
SHAPE s_spinflag
1:  pause
    cmpl $0,(%r14)
    jne 1b
    ud2

/* a job system's spin on a register copy, no memory at all */
SHAPE s_spinreg
1:  pause
    testl %eax,%eax
    jz 1b
    ud2

/* test-and-set spinlock, lock held for ever: xchg; test; jnz inner wait */
SHAPE s_tas
1:  movl $1,%eax
    xchgl %eax,(%r14)
    testl %eax,%eax
    jz 9f
2:  pause
    cmpl $0,(%r14)
    jne 2b
    jmp 1b
9:  ud2

/* lock cmpxchg that always fails */
SHAPE s_cas
1:  xorl %eax,%eax
    movl $2,%esi
    lock cmpxchgl %esi,(%r14)
    jz 9f
    pause
    jmp 1b
9:  ud2

/* spin N times with pause, then sched_yield: the usual hybrid */
SHAPE s_spinyield
1:  movl $2000,%ebx
2:  pause
    cmpl $0,(%r14)
    je 9f
    decl %ebx
    jnz 2b
    movl $24,%eax
    syscall
    jmp 1b
9:  ud2

/* merged pairs back to back and nothing else but the jump */
SHAPE s_pairs
1:  pushq %rax
    pushq %rcx
    popq %rdx
    popq %rsi
    jmp 1b

SHAPE s_pairs8
1:
.rept 8
    pushq %rax
    pushq %rcx
    popq %rdx
    popq %rsi
.endr
    jmp 1b

/* only pushes and pops, pair after pair, the loop closed by a ret (push of the address; pop; ret merged) */
SHAPE s_pushret
    leaq 1f(%rip),%rbp
1:  pushq %rbp
    pushq %rax
    popq %rcx
    retq

/* call/ret with Windows epilogues */
sh_leaf_a:
    pushq %rbx
    pushq %rsi
    pushq %rdi
    movq %rdx,%rbx
    leaq 1(%rbx),%rax
    popq %rdi
    popq %rsi
    popq %rbx
    retq
sh_leaf_b:
    pushq %rbp
    movq %rsp,%rbp
    subq $0x20,%rsp
    movq %rdx,8(%rsp)
    movq 8(%rsp),%rax
    movq %rbp,%rsp
    popq %rbp
    retq
SHAPE s_callret
1:  movq %r14,%rdx
    callq sh_leaf_a
    movq %r14,%rdx
    callq sh_leaf_b
    jmp 1b

/* an empty function called for ever */
sh_empty:
    retq
SHAPE s_callempty
1:  callq sh_empty
    jmp 1b

/* moves merged into the next operation, all of them */
SHAPE s_movalu
1:
.rept 8
    movl %eax,%ecx
    andl $255,%ecx
    movq %rax,%rdx
    subq %rcx,%rdx
    movl %edx,%esi
    shrl $3,%esi
    movq %rdx,%rdi
    xorq %rsi,%rdi
    movq %rdi,%rax
    addq $7,%rax
.endr
    jmp 1b

/* carry chains in registers: the form of the host carry changes all the time */
SHAPE s_carry
1:
.rept 4
    addq %rcx,%rax
    adcq %rdx,%rbx
    sbbq %rcx,%rsi
    rclq $1,%rdi
    cmc
    adcq $0,%rax
    stc
    sbbq $0,%rbx
    clc
.endr
    jmp 1b

/* instructions without operands (no entry of their own), then the jump */
SHAPE s_noops
1:
.rept 8
    cltq
    cqto
    lahf
    sahf
    cmc
    nop
.endr
    jmp 1b

/* SSE in registers */
SHAPE s_sse
    movups 0x1000(%r14),%xmm0
    movups 0x1010(%r14),%xmm1
1:
.rept 4
    movaps %xmm0,%xmm2
    mulps %xmm1,%xmm2
    addps %xmm2,%xmm0
    shufps $0x1b,%xmm0,%xmm0
    subps %xmm1,%xmm0
.endr
    jmp 1b

/* x87 with memory */
SHAPE s_x87
1:  fldl 0x1000(%r14)
    fldl 0x1008(%r14)
    fmul %st(1),%st
    faddl 0x1010(%r14)
    fstpl 0x1018(%r14)
    fmull 0x1008(%r14)
    fstpl 0x1020(%r14)
    jmp 1b

/* x87 copies */
SHAPE s_x87copy
1:  fldl 0x1000(%r14)
    fstpl 0x1018(%r14)
    fldl 0x1008(%r14)
    fstpl 0x1020(%r14)
    jmp 1b

/* x87 on its stack alone */
SHAPE s_x87reg
    fld1
    fld1
1:
.rept 4
    fld %st(0)
    fmul %st(2),%st
    faddp %st,%st(1)
    fxch %st(1)
.endr
    jmp 1b

/* x87 transcendental: all of it in a helper */
SHAPE s_x87sin
1:  fldl 0x1000(%r14)
    fsin
    fstpl 0x1018(%r14)
    jmp 1b

/* MMX */
SHAPE s_mmx
    movq 0x1000(%r14),%mm0
    movq 0x1008(%r14),%mm1
1:
.rept 4
    paddw %mm1,%mm0
    pmullw %mm0,%mm1
    pxor %mm1,%mm0
.endr
    jmp 1b

/* AVX in registers */
SHAPE s_avx
    vmovups 0x1000(%r14),%ymm0
1:
.rept 4
    vmulps %ymm0,%ymm0,%ymm2
    vaddps %ymm2,%ymm0,%ymm3
    vsubps %ymm2,%ymm3,%ymm4
    vmaxps %ymm4,%ymm0,%ymm0
.endr
    jmp 1b

/* rep movsb, 16 bytes / 4 KiB / 1 MiB at a time (mem2 = mem + 0x10000 is 4 MiB) */
SHAPE s_rep16
1:  leaq 0x1000(%r14),%rsi
    leaq 0x2000(%r14),%rdi
    movl $16,%ecx
    rep movsb
    jmp 1b
SHAPE s_rep4k
1:  leaq 0x10000(%r14),%rsi
    leaq 0x20000(%r14),%rdi
    movl $4096,%ecx
    rep movsb
    jmp 1b
SHAPE s_rep1m
1:  leaq 0x10000(%r14),%rsi
    leaq 0x210000(%r14),%rdi
    movl $0x100000,%ecx
    rep movsb
    jmp 1b
SHAPE s_stos1m
1:  leaq 0x10000(%r14),%rdi
    movl $0x100000,%ecx
    xorl %eax,%eax
    rep stosb
    jmp 1b
/* repne scasb over 1 MiB of zeros looking for 1: a strlen/memchr */
SHAPE s_scas1m
1:  leaq 0x10000(%r14),%rdi
    movl $0x100000,%ecx
    movb $1,%al
    repne scasb
    jmp 1b

/* division: 64/32 inline, 128/64 through a helper */
SHAPE s_div
1:
.rept 4
    leaq 12345(%rbx),%rax
    movl $77,%ecx
    cqto
    idivq %rcx
    movl %eax,%eax
    xorl %edx,%edx
    divl %ecx
.endr
    incq %rbx
    jmp 1b

/* a loop across units: indirect jumps between two places 1 MiB apart */
SHAPE s_indirect
    leaq sh_far(%rip),%r12
    leaq 1f(%rip),%r13
1:  jmpq *%r12
.section .text.far,"ax"
.skip 0x200000
.p2align 6
sh_far:
    jmpq *%r13
.text

/* a loop across linked units: direct jumps to a place too far for one translation unit */
SHAPE s_linked
1:  addl $1,%eax
    jmp sh_far2
.section .text.far2,"ax"
.skip 0x200000
.p2align 6
sh_far2:
    subl $1,%eax
    jmp 1b
.text

/* a loop of calls through a table (virtual calls) */
SHAPE s_vcall
    leaq sh_empty(%rip),%rax
    movq %rax,0x1800(%r14)
1:  callq *0x1800(%r14)
    jmp 1b

/* cpuid, rdtsc: helpers or host instructions */
SHAPE s_rdtsc
1:  rdtsc
    jmp 1b

/* an ordinary loop, the control: loads, stores, compare, branch */
SHAPE s_plain
1:  movq 0x1000(%r14),%rax
    addq $3,%rax
    movq %rax,0x1008(%r14)
    cmpq %rbx,%rax
    je 9f
    incl 0x1010(%r14)
    jmp 1b
9:  ud2

/* a conditional branch closes the loop, nothing else in it */
SHAPE s_jcc
1:  testl %edx,%edx
    jnz 1b
    ud2
/* the loop instruction, which the frontend takes for no branch of the unit, and jrcxz */
SHAPE s_loop
1:  movl $-1,%ecx
2:  addl $1,%eax
    loop 2b
    jmp 1b
SHAPE s_jrcxz
    xorl %ecx,%ecx
1:  addl $1,%eax
    jrcxz 1b
    ud2
/* loops in loops, an exit in the middle, a head in the middle of a block */
SHAPE s_nest
1:  movl $3,%ecx
2:  addl $3,%eax
    testl $0x40000000,%ebx
    jnz 9f
3:  subl $1,%eax
    testl $1,%eax
    jz 4f
    decl %ecx
    jnz 2b
    jmp 1b
4:  decl %ecx
    jg 3b
    jmp 1b
9:  ud2

/* recursion, and a chain of returns that were never called */
sh_fib:
    pushq %rbp
    pushq %rbx
    subq $8,%rsp
    movl %edi,%ebx
    cmpl $2,%edi
    jl 2f
    leal -1(%rbx),%edi
    callq sh_fib
    movl %eax,%ebp
    leal -2(%rbx),%edi
    callq sh_fib
    addl %ebp,%eax
    jmp 3f
2:  movl %ebx,%eax
3:  addq $8,%rsp
    popq %rbx
    popq %rbp
    retq
SHAPE s_fib
1:  movl $18,%edi
    callq sh_fib
    jmp 1b
/* deep recursion: 60000 frames down and up again (mem2 is 5 MiB) */
sh_deep:
    decl %edi
    jz 1f
    callq sh_deep
1:  retq
SHAPE s_deep
    leaq 0x500000(%r14),%rsp
1:  movl $60000,%edi
    callq sh_deep
    jmp 1b
SHAPE s_retchain
    leaq 1f(%rip),%rbp
    leaq 2f(%rip),%rbx
1:  pushq %rbx
    retq
2:  pushq %rbp
    retq
/* one leaf in a loop, as compilers write it */
SHAPE s_leaf
1:  movq %r14,%rdx
    callq sh_leaf_a
    jmp 1b
/* a jump table inside a unit */
SHAPE s_table
    leaq 2f(%rip),%rax
    movq %rax,0x1800(%r14)
    leaq 3f(%rip),%rax
    movq %rax,0x1808(%r14)
    xorl %ebx,%ebx
1:  xorl $1,%ebx
    jmpq *0x1800(%r14,%rbx,8)
2:  addl $1,%eax
    jmp 1b
3:  addl $2,%eax
    jmp 1b
/* eight indirect jumps in a row between eight units */
.macro CHAIN n next
.section .text.chain\n,"ax"
.skip 0x8000
sh_chain\n:
    leaq sh_chain\next(%rip),%rax
    jmpq *%rax
.text
.endm
CHAIN 0 1
CHAIN 1 2
CHAIN 2 3
CHAIN 3 4
CHAIN 4 5
CHAIN 5 6
CHAIN 6 7
CHAIN 7 0
SHAPE s_chain
    jmp sh_chain0

/* 4000 instructions without a branch */
SHAPE s_long
1:
.rept 500
    movq 0x1000(%r14),%rax
    addq %rbx,%rax
    imulq $13,%rax,%rcx
    movq %rcx,0x1008(%r14)
    xorq %rax,%rbx
    rolq $3,%rbx
    movups 0x1000(%r14),%xmm0
    movups %xmm0,0x1010(%r14)
.endr
    jmp 1b
/* 100 x87 operations without a branch, each in a helper */
SHAPE s_x87long
    fld1
    fldl 0x1000(%r14)
1:
.rept 100
    fadd %st(1),%st
    fmul %st(1),%st
.endr
    jmp 1b
SHAPE s_x87atan
1:  fldl 0x1000(%r14)
    fldl 0x1008(%r14)
    fpatan
    fyl2xp1
    fstpl 0x1018(%r14)
    fninit
    jmp 1b
/* fild; fistp: the copy of old 32-bit code */
SHAPE s_x87int
1:  fildll 0x1000(%r14)
    fistpll 0x1018(%r14)
    jmp 1b

SHAPE s_movsq1m
1:  leaq 0x10000(%r14),%rsi
    leaq 0x210000(%r14),%rdi
    movl $0x20000,%ecx
    rep movsq
    jmp 1b
/* over itself, one byte ahead: element by element */
SHAPE s_over1m
1:  leaq 0x10000(%r14),%rsi
    leaq 0x10001(%r14),%rdi
    movl $0x100000,%ecx
    rep movsb
    jmp 1b
SHAPE s_back1m
1:  std
    leaq 0x10fff8(%r14),%rsi
    leaq 0x30fff8(%r14),%rdi
    movl $0x20000,%ecx
    rep movsq
    cld
    jmp 1b
SHAPE s_stosd4m
1:  leaq 0x10000(%r14),%rdi
    movl $0x100000,%ecx
    xorl %eax,%eax
    rep stosl
    jmp 1b
SHAPE s_cmps1m
1:  leaq 0x10000(%r14),%rsi
    leaq 0x210000(%r14),%rdi
    movl $0x100000,%ecx
    repe cmpsb
    jmp 1b
SHAPE s_lods1m
1:  leaq 0x10000(%r14),%rsi
    movl $0x100000,%ecx
    rep lodsb
    jmp 1b

/* AVX copies through registers and memory */
SHAPE s_avxmem
1:
.rept 4
    vmovups 0x1000(%r14),%ymm1
    vaddps %ymm1,%ymm2,%ymm2
    vmovups %ymm2,0x1100(%r14)
.endr
    jmp 1b
SHAPE s_cpuid
1:  xorl %eax,%eax
    cpuid
    jmp 1b
/* system calls, one after the other */
SHAPE s_getpid
1:  movl $39,%eax
    syscall
    jmp 1b
/* blocked in one: nanosleep for 10 s; futex for ever */
SHAPE s_sleep
    movq $10,0x1100(%r14)
    movq $0,0x1108(%r14)
1:  movl $35,%eax
    leaq 0x1100(%r14),%rdi
    xorl %esi,%esi
    syscall
    jmp 1b
SHAPE s_futex
    movl $7,0x1100(%r14)
1:  movl $202,%eax
    leaq 0x1100(%r14),%rdi
    xorl %esi,%esi
    movl $7,%edx
    xorl %r10d,%r10d
    syscall
    jmp 1b
/* code that rewrites itself all the time */
SHAPE s_smc
    leaq sh_smc(%rip),%r12
1:  incl %eax
    movb %al,1(%r12)
    callq sh_smc
    jmp 1b
.section .text.smc,"awx"
.p2align 14
sh_smc:
    movb $1,%dl
    retq
.p2align 14
.text
.section .note.GNU-stack,"",@progbits
