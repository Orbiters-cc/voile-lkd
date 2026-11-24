/* Kernels of the sigstorm witness: self-checking x86-64 code that an asynchronous signal must never disturb.
 * Each k_*(struct wk *w) loops until w->stop, counts w->iters and returns 0, or a code telling what went wrong. */
#define W_STOP  0
#define W_ITERS 8
#define W_CELL  16
#define W_AUX   24

.text
/* ---- leaf_a: the epilogue of fault 3 (pop rdi; pop rsi; pop rbx; ret) ---------------------------------------------- */
#ifdef LEAFSPLIT
#define SEP movq %rax,%r10
#else
#define SEP
#endif
.globl leaf_a, leaf_b
leaf_a:
    pushq %rbx
    SEP
    pushq %rsi
    SEP
    pushq %rdi
    xorl %eax,%eax
    movq %rdx,%rbx
    movq %rcx,%r11
    movq (%rdx),%rcx
    addq $8,%rax
    xorq (%r8),%rcx
    movq %rcx,(%r11)
    movq 8(%rdx),%rcx
    addq $8,%rax
    xorq 8(%r8),%rcx
    movq %rcx,8(%r11)
    popq %rdi
    SEP
    popq %rsi
    SEP
    popq %rbx
    SEP
.globl leaf_a_ret, leaf_b_ret
#ifdef LEAFNOP
    nop
    nop
    nop
#endif
#ifdef LEAFJMP
    jmp 1f
    .skip 64, 0x90
1:
#endif
leaf_a_ret:
    retq
/* ---- leaf_b: the epilogue of fault 2 (mov rsp,rbp; pop rbp; ret), callee-saved registers kept in the caller's home ----- */
leaf_b:
    pushq %rbp
    subq $0x20,%rsp
    leaq 0x20(%rsp),%rbp
    movq %rbx,0x10(%rbp)
    movq %rdx,%rbx
    movq %rsi,0x18(%rbp)
    movq %r8,%rsi
    movq %rdi,0x20(%rbp)
    movq %rcx,%rdi
    movq %r14,0x28(%rbp)
    subq $0x10,%rsp
    leaq 0x20(%rsp),%rbx
    movl $7,(%rbx)
    movl $9,4(%rbx)
    movl (%rbx),%eax
    addl 4(%rbx),%eax
    movq 0x10(%rbp),%rbx
    movq 0x18(%rbp),%rsi
    movq 0x20(%rbp),%rdi
    movq 0x28(%rbp),%r14
    movq %rbp,%rsp
    popq %rbp
    SEP
leaf_b_ret:
    retq

#ifdef FARLEAF
    .skip 0x200000, 0xcc
#endif
/* ---- k_callret: calls the two leaves forever. The slot a second `ret` would pop holds the address of 9f. ------------- */
.globl k_callret
k_callret:
    pushq %rbx
    pushq %rbp
    pushq %r12
    pushq %r13
    pushq %r14
    pushq %r15
    subq $0x68,%rsp
    movq %rdi,%r15
1:
    leaq 9f(%rip),%rax
    movq %rax,(%rsp)                /* what a doubled ret pops */
    movq %rax,8(%rsp)
    movq $0x1111,%rbx
    movq $0x2222,%rsi
    movq $0x3333,%rdi
    movq $0x4444,%r14
    movq %rsp,%r12
    movq %rsp,W_AUX(%r15)
    movl $1,%r13d
    leaq 0x40(%rsp),%rcx
    leaq 0x50(%rsp),%rdx
    leaq 0x50(%rsp),%r8
    callq leaf_a
    cmpq %r12,%rsp
    jne 8f
    cmpq $0x1111,%rbx
    jne 7f
    cmpq $0x2222,%rsi
    jne 7f
    cmpq $0x3333,%rdi
    jne 7f
    cmpq $16,%rax
    jne 6f
    cmpq $0,0x40(%rsp)
    jne 6f
    movl $2,%r13d
    leaq 0x40(%rsp),%rcx
    leaq 0x50(%rsp),%rdx
    leaq 0x50(%rsp),%r8
    callq leaf_b
    cmpq %r12,%rsp
    jne 8f
    cmpq $0x1111,%rbx
    jne 7f
    cmpq $0x2222,%rsi
    jne 7f
    cmpq $0x3333,%rdi
    jne 7f
    cmpq $0x4444,%r14
    jne 7f
    cmpl $16,%eax
    jne 6f
    incq W_ITERS(%r15)
    cmpl $0,W_STOP(%r15)
    je 1b
    xorl %eax,%eax
2:
    addq $0x68,%rsp
    popq %r15
    popq %r14
    popq %r13
    popq %r12
    popq %rbp
    popq %rbx
    retq
6:  movl $6,%eax                    /* wrong result */
    jmp 2b
7:  movl $7,%eax                    /* callee-saved register lost */
    jmp 2b
8:  movq %r12,%rsp                  /* stack pointer moved */
    movl $8,%eax
    jmp 2b
9:  movq %r12,%rsp                  /* a ret ran twice */
    movl %r13d,W_AUX+8(%r15)
    movl $9,%eax
    jmp 2b

/* ---- k_rmw: instructions with two effects, or a memory read-modify-write, checked every round ----------------------- */
.globl k_rmw
k_rmw:
    pushq %rbx
    pushq %r12
    pushq %r13
    pushq %r14
    pushq %r15
    subq $0x80,%rsp
    movq %rdi,%r15
    movq W_CELL(%rdi),%r8
1:
    xorl %eax,%eax
    movl $0,(%r8)
    movq $0,8(%r8)
    movq $0,16(%r8)
    movq %rsp,%r12
.rept 16
    incl (%r8)
    addq $1,%rax
    pushq %rax
    addq $3,8(%r8)
    popq %rbx
    cmpq %rax,%rbx
    jne 6f
    lock xaddq %rbx,16(%r8)
.endr
    cmpq %r12,%rsp
    jne 8f
    cmpl $16,(%r8)
    jne 6f
    cmpq $48,8(%r8)
    jne 6f
    cmpq $16,%rax
    jne 6f
    cmpq $136,16(%r8)
    jne 6f
    cmpq $120,%rbx
    jne 6f
    movq $5,%rcx
    movq $6,%rdx
    xchgq %rcx,%rdx
    cmpq $6,%rcx
    jne 6f
    cmpq $5,%rdx
    jne 6f
    movq $77,24(%r8)
    movq $88,%rcx
    xchgq %rcx,24(%r8)
    cmpq $77,%rcx
    jne 6f
    cmpq $88,24(%r8)
    jne 6f
    /* a string copy of 64 bytes inside the cell page, then its check */
    leaq 64(%r8),%rsi
    leaq 192(%r8),%rdi
    movl $64,%ecx
    rep movsb
    leaq 64(%r8),%rsi
    leaq 192(%r8),%rdi
    movl $8,%ecx
    repe cmpsq
    jne 6f
    testq %rcx,%rcx
    jne 6f
    incq W_ITERS(%r15)
    cmpl $0,W_STOP(%r15)
    je 1b
    xorl %eax,%eax
2:
    addq $0x80,%rsp
    popq %r15
    popq %r14
    popq %r13
    popq %r12
    popq %rbx
    retq
6:  movq %r12,%rsp
    movl $6,%eax
    jmp 2b
8:  movq %r12,%rsp
    movl $8,%eax
    jmp 2b

/* ---- k_big / k_bigctl: one large function, thousands of instructions with one effect each ---------------------------
 * k_big holds a parity branch (jp, which the translator emits as a 32 KiB-range test-bit branch) from its end back to its
 * start, so its translation needs the far-branch form; k_bigctl is the same code without that branch. */
.macro BIGBODY par
    xorl %eax,%eax
    movl $0,(%r8)
    testb $1,%sil
    jz 3f
    nop
3:
.rept 1000
    addq $1,%rax
    addl $1,(%r8)
.if \par
    ucomiss %xmm1,%xmm0
    jp 4f
.else
    ucomiss %xmm1,%xmm0
    jb 4f
.endif
.endr
.endm

.globl k_big
k_big:
    pushq %r15
    pushq %r12
    subq $8,%rsp
    movq %rdi,%r15
    movq W_CELL(%rdi),%r8
    movl $1,%esi
    xorps %xmm0,%xmm0
    xorps %xmm1,%xmm1
k_big_top:
    BIGBODY 1
    movl $1,%ecx
    testl %ecx,%ecx                 /* PF = 0 (one bit set): never taken */
    jp k_big_top
    cmpq $1000,%rax
    jne 6f
    cmpl $1000,(%r8)
    jne 6f
    incq W_ITERS(%r15)
    cmpl $0,W_STOP(%r15)
    je k_big_top
    xorl %eax,%eax
2:  addq $8,%rsp
    popq %r12
    popq %r15
    retq
4:  movl $4,%eax                    /* the unordered branch was taken: flags wrong */
    jmp 2b
6:  movl (%r8),%ecx
    movq %rax,W_AUX(%r15)
    movl %ecx,W_AUX+8(%r15)
    movl $6,%eax
    jmp 2b

.globl k_bigctl
k_bigctl:
    pushq %r15
    pushq %r12
    subq $8,%rsp
    movq %rdi,%r15
    movq W_CELL(%rdi),%r8
    movl $1,%esi
    xorps %xmm0,%xmm0
    xorps %xmm1,%xmm1
k_bigctl_top:
    BIGBODY 0
    cmpq $1000,%rax
    jne 6f
    cmpl $1000,(%r8)
    jne 6f
    incq W_ITERS(%r15)
    cmpl $0,W_STOP(%r15)
    je k_bigctl_top
    xorl %eax,%eax
2:  addq $8,%rsp
    popq %r12
    popq %r15
    retq
4:  movl $4,%eax
    jmp 2b
6:  movl (%r8),%ecx
    movq %rax,W_AUX(%r15)
    movl %ecx,W_AUX+8(%r15)
    movl $6,%eax
    jmp 2b

#ifdef WIN
/* Windows entry points: rcx = w; rsi and rdi are callee-saved there. */
.globl k_callret_ms, k_rmw_ms
k_callret_ms:
    pushq %rsi
    pushq %rdi
    subq $0x28,%rsp
    movq %rcx,%rdi
    callq k_callret
    addq $0x28,%rsp
    popq %rdi
    popq %rsi
    retq
k_rmw_ms:
    pushq %rsi
    pushq %rdi
    subq $0x28,%rsp
    movq %rcx,%rdi
    callq k_rmw
    addq $0x28,%rsp
    popq %rdi
    popq %rsi
    retq
#endif
