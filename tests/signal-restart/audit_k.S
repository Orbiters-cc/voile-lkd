/* Kernels of the audit: every other place where the translator may make the state at a guest instruction boundary differ
 * from x86's. Each k_*(struct wk *w) loops until w->stop and checks itself every round: 0, or 100 + the number of the
 * failed check. All of them change their values every round (%r13 counts), so that a stale register is seen. */
#define W_STOP  0
#define W_ITERS 8
#define W_CELL  16
#define W_AUX   24
.text
.macro ENTER_K
    pushq %rbx
    pushq %rbp
    pushq %r12
    pushq %r13
    pushq %r14
    pushq %r15
    subq $0x108,%rsp
    movq %rdi,%r15
    movq W_CELL(%rdi),%r8
    xorl %r13d,%r13d
.endm
.macro LEAVE_K name
    incq W_ITERS(%r15)
    incq %r13
    cmpl $0,W_STOP(%r15)
    je \name\()_top
    xorl %eax,%eax
\name\()_out:
    cld
    addq $0x108,%rsp
    popq %r15
    popq %r14
    popq %r13
    popq %r12
    popq %rbp
    popq %rbx
    retq
.endm
.macro CHECK name, reg, want, code
    cmpq \want,\reg
    je 77f
    movq \reg,%r9
    movq %r9,W_AUX(%r15)
    movl $(100+\code),%eax
    jmp \name\()_out
77:
.endm
/* instructions that change nothing the kernels look at, each one a boundary */
.macro FILL n
.rept \n
    leaq 1(%r13),%r9
    movq %r9,%r10
    leaq 3(%r10),%r11
.endr
.endm

/* ---- k: effects of one instruction the allocator lets the next one make (moves, cdq/idiv), or drops ------------- */
.globl k_merge
k_merge:
    ENTER_K
k_merge_top:
.rept 6
    leaq 0x1111(%r13),%rax
    leaq 0x2222(%r13),%rcx
    xchgq %rax,%rcx
    addq $1,%rcx                    /* 0x1112 + r13 */
    xchgq %rcx,%rdx
    subq $2,%rdx
    movq %rdx,%rbx
    subq $0x1110,%rbx               /* r13 */
    CHECK k_merge, %rbx, %r13, 1
    leaq 0x7777(%r13),%rax
    movl %eax,%ecx
    andl $0xfff,%ecx
    movl %eax,%edx
    shrl $12,%edx
    shll $12,%edx
    orl %ecx,%edx
    movl %eax,%ebx
    CHECK k_merge, %rdx, %rbx, 2
    leaq 0x100(%r13),%rax
    leaq 0x200(%r13),%rsi
    xaddq %rax,%rsi                 /* rax = 0x200 + r13, rsi = 0x300 + 2 r13 */
    subq $0x200,%rax
    CHECK k_merge, %rax, %r13, 3
    subq $0x300,%rsi
    subq %r13,%rsi
    CHECK k_merge, %rsi, %r13, 4
    movq $0xdead,%rdx
    movl %r13d,%eax
    andl $0xffff,%eax
    negq %rax
    cqto
    movq $7,%rcx
    idivq %rcx
    imulq $7,%rax,%rsi
    addq %rdx,%rsi
    negq %rsi
    movl %r13d,%ebx
    andl $0xffff,%ebx
    CHECK k_merge, %rsi, %rbx, 5
    movl $0xbeef,%edx
    movl %ebx,%eax
    xorl %edx,%edx
    movl $9,%ecx
    divl %ecx
    imull $9,%eax,%esi
    addl %edx,%esi
    CHECK k_merge, %rsi, %rbx, 6
    movq %r8,%rax
    movq %r13,0x40(%r8)
    leaq 0x40(%r8),%rdx
    movq %rdx,%rax
    movq (%rax),%rax
    CHECK k_merge, %rax, %r13, 7
    movq %r13,%rbx
    movq %rbx,%rcx
    xorq %rbx,%rcx
    CHECK k_merge, %rcx, $0, 8
    movq $0x55,%rcx
    bswapq %rbx
    movq %rbx,%rcx
    bswapq %rcx
    CHECK k_merge, %rcx, %r13, 9
.endr
    LEAVE_K k_merge

/* ---- a: carry and the other flags alive over instructions that leave them alone ------------------------------------ */
.globl k_carry
k_carry:
    ENTER_K
k_carry_top:
.rept 4
    movq $-1,%rax
    xorl %ecx,%ecx
    addq $1,%rax                    /* CF = 1 (an addition's carry) */
    FILL 4
    adcq $0,%rcx
    CHECK k_carry, %rcx, $1, 1
    xorl %eax,%eax
    addq $1,%rax                    /* CF = 0 */
    FILL 4
    adcq $0,%rcx
    CHECK k_carry, %rcx, $1, 2
    xorl %eax,%eax
    subq $1,%rax                    /* CF = 1 (a borrow) */
    FILL 4
    sbbq $0,%rcx
    CHECK k_carry, %rcx, $0, 3
    movq $-1,%rax
    movq %r13,%rbx
    movq %r13,%rdx
    addq $1,%rax
    FILL 2
    adcq %rbx,%rbx
    FILL 2
    adcq %rdx,%rdx
    leaq 1(%r13,%r13),%rsi
    CHECK k_carry, %rbx, %rsi, 4
    leaq (%r13,%r13),%rsi
    CHECK k_carry, %rdx, %rsi, 5
    stc
    FILL 3
    setc %al
    movzbl %al,%eax
    CHECK k_carry, %rax, $1, 6
    movq $-1,%rax
    addq $1,%rax
    FILL 3
    incq %rcx                       /* keeps CF */
    FILL 3
    setc %al
    movzbl %al,%eax
    CHECK k_carry, %rax, $1, 7
    movl $1,%ecx
    movl $3,%edx
    movq $-1,%rax
    addq $1,%rax                    /* CF ZF */
    FILL 3
    cmovbq %rdx,%rcx
    CHECK k_carry, %rcx, $3, 8
    xorl %ecx,%ecx
    xorl %eax,%eax
    addq $1,%rax
    FILL 3
    cmovbq %rdx,%rcx
    CHECK k_carry, %rcx, $0, 9
    btq $0,%rdx
    FILL 3
    jnc 5f
    movq $-1,%rax
    addq $1,%rax
    FILL 3
    jnc 5f
    xorl %eax,%eax
    addq $1,%rax
    FILL 3
    jc 5f
    xorl %ecx,%ecx
    testq %rcx,%rcx
    FILL 2
    jnz 5f
    testq %rdx,%rdx
    FILL 2
    jz 5f
    cmpq $4,%rdx
    FILL 2
    jge 5f
    movb $0x7f,%al
    addb $1,%al                     /* OF SF */
    FILL 2
    jno 5f
    movb $0x7f,%al
    addb $1,%al
    FILL 2
    jns 5f
    movb $3,%al
    testb %al,%al                   /* PF = 1 */
    FILL 2
    jnp 5f
    movb $1,%al
    testb %al,%al
    FILL 2
    jp 5f
    movq $-1,%rax
    addq $1,%rax
    pushfq
    FILL 2
    addq $5,%r9
    popfq
    FILL 2
    jnc 5f
    movq $-1,%rax
    addq $1,%rax
    lahf
    FILL 2
    movb %ah,%bl
    xorl %ecx,%ecx
    addq $1,%rcx
    movb %bl,%ah
    sahf
    FILL 2
    jnc 5f
.endr
    LEAVE_K k_carry
5:  movl $150,%eax
    jmp k_carry_out

/* ---- v: 256-bit registers (their high halves live outside the host registers) ------------------------------------- */
.globl k_avx
k_avx:
    ENTER_K
    leaq 0x100(%r8),%rbx
k_avx_top:
.rept 3
    leaq 0x12340000(%r13),%rax
    vmovq %rax,%xmm0
    vpbroadcastq %xmm0,%ymm0        /* four copies of rax */
    FILL 3
    vpaddq %ymm0,%ymm0,%ymm1        /* 2 rax */
    FILL 3
    vpaddq %ymm1,%ymm0,%ymm2        /* 3 rax */
    FILL 3
    vmovdqu %ymm2,(%rbx)
    FILL 2
    leaq (%rax,%rax,2),%rcx
    CHECK k_avx, (%rbx), %rcx, 1
    CHECK k_avx, 8(%rbx), %rcx, 2
    CHECK k_avx, 16(%rbx), %rcx, 3
    CHECK k_avx, 24(%rbx), %rcx, 4
    /* a copy as a memcpy makes it: four loads, then four stores */
    movq %rcx,0(%rbx)
    movq %rax,16(%rbx)
    movq %r13,40(%rbx)
    movq %rcx,56(%rbx)
    vmovdqu (%rbx),%ymm4
    vmovdqu 32(%rbx),%ymm5
    FILL 2
    vmovdqu %ymm4,64(%rbx)
    vmovdqu %ymm5,96(%rbx)
    FILL 1
    CHECK k_avx, 80(%rbx), %rax, 5
    CHECK k_avx, 104(%rbx), %r13, 6
    CHECK k_avx, 120(%rbx), %rcx, 7
    vmovdqu %ymm0,%ymm6
    vextracti128 $1,%ymm0,%xmm7
    FILL 2
    vmovq %xmm7,%rdx
    CHECK k_avx, %rdx, %rax, 8
    vmovdqa %xmm6,%xmm6             /* clears the high half */
    FILL 2
    vextracti128 $1,%ymm6,%xmm7
    vmovq %xmm7,%rdx
    CHECK k_avx, %rdx, $0, 9
.endr
    vzeroupper
    LEAVE_K k_avx

/* ---- x: the x87 stack ------------------------------------------------------------------------------------------------ */
.globl k_x87
k_x87:
    ENTER_K
k_x87_top:
.rept 3
    movq %r13,0x20(%r8)
    movq $1000,0x28(%r8)
    fildll 0x20(%r8)
    FILL 2
    fildll 0x28(%r8)
    FILL 2
    faddp
    FILL 2
    fildll 0x28(%r8)
    fxch
    FILL 2
    fsubp %st,%st(1)                /* 1000 - (r13 + 1000), or its opposite, by the assembler's reading */
    FILL 2
    fchs
    fabs
    FILL 2
    fistpll 0x30(%r8)
    FILL 1
    CHECK k_x87, 0x30(%r8), %r13, 1
.endr
    LEAVE_K k_x87

/* ---- m: MMX ----------------------------------------------------------------------------------------------------------- */
.globl k_mmx
k_mmx:
    ENTER_K
k_mmx_top:
.rept 3
    leaq 0x999(%r13),%rax
    movq %rax,%mm0
    FILL 2
    movq %r13,%mm1
    paddq %mm1,%mm0
    FILL 2
    movq %mm0,%mm2
    paddq %mm2,%mm2
    FILL 2
    movq %mm2,%rcx
    leaq (%rax,%r13),%rdx
    addq %rdx,%rdx
    CHECK k_mmx, %rcx, %rdx, 1
.endr
    emms
    LEAVE_K k_mmx

/* ---- d: the direction flag ------------------------------------------------------------------------------------------- */
.globl k_df
k_df:
    ENTER_K
k_df_top:
.rept 3
    leaq 0x40(%r8),%rsi
    leaq 0x80(%r8),%rdi
    movq %r13,(%rsi)
    FILL 1
    std
    FILL 2
    movsq
    FILL 2
    lodsb
    FILL 1
    cld
    FILL 2
    leaq 0x37(%r8),%rdx
    CHECK k_df, %rsi, %rdx, 1
    leaq 0x78(%r8),%rdx
    CHECK k_df, %rdi, %rdx, 2
    CHECK k_df, 0x80(%r8), %r13, 3
    leaq 0x40(%r8),%rsi
    lodsq
    CHECK k_df, %rax, %r13, 4
.endr
    LEAVE_K k_df

/* ---- p: pairs of stack operations -------------------------------------------------------------------------------------- */
.macro LEAFS
p_leaf1:                            /* pop; ret n */
    pushq %rbx
    movq %rdi,%rbx
    leaq 1(%rbx),%rax
    popq %rbx
    retq $16
p_leaf2:                            /* leave; ret */
    pushq %rbp
    movq %rsp,%rbp
    pushq %rdi
    pushq $-7
    popq %rax
    addq (%rsp),%rax
    leave
    retq
p_leaf3:                            /* seven saves, add rsp, pops, ret */
    pushq %r15
    pushq %r14
    pushq %r13
    pushq %r12
    pushq %rdi
    pushq %rsi
    pushq %rbp
    pushq %rbx
    subq $0x28,%rsp
    movq %rdi,%rax
    xorl %ebx,%ebx
    movl $1,%ebp
    movl $2,%esi
    movl $3,%edi
    movl $4,%r12d
    movl $5,%r13d
    movl $6,%r14d
    movl $7,%r15d
    addq $0x28,%rsp
    popq %rbx
    popq %rbp
    popq %rsi
    popq %rdi
    popq %r12
    popq %r13
    popq %r14
    popq %r15
    retq
p_leaf4:                            /* a tail call: pops, then jmp */
    pushq %rbx
    pushq %rsi
    movq %rdi,%rbx
    movq %rbx,%rsi
    popq %rsi
    popq %rbx
    jmp p_leaf2
.endm
LEAFS
.globl k_pairs
k_pairs:
    ENTER_K
k_pairs_top:
    movq %rsp,%r12
    leaq 0x101(%r13),%rbx
    leaq 0x202(%r13),%rsi
    leaq 0x303(%r13),%rbp
    movq %rbx,0x10(%r8)
    leaq 9f(%rip),%rax              /* what a doubled ret pops */
    movq %rax,(%rsp)
    movq %rax,8(%rsp)
.rept 2
    movq %r13,%rdi
    pushq $0
    pushq $0
    callq p_leaf1
    movq %rax,%r14
    leaq 1(%r13),%rdx
    cmpq %rsp,%r12
    jne 8f
    CHECK k_pairs, %r14, %rdx, 1
    movq %r13,%rdi
    callq p_leaf2
    cmpq %rsp,%r12
    jne 8f
    leaq -7(%r13),%rdx
    CHECK k_pairs, %rax, %rdx, 2
    movq %r13,%rdi
    movq %rbx,%r14
    callq p_leaf3
    cmpq %rsp,%r12
    jne 8f
    CHECK k_pairs, %rax, %r13, 3
    CHECK k_pairs, %rbx, %r14, 4
    leaq 0x202(%r13),%rdx
    CHECK k_pairs, %rsi, %rdx, 5
    leaq 0x303(%r13),%rdx
    CHECK k_pairs, %rbp, %rdx, 6
    movq %r13,%rdi
    callq p_leaf4
    cmpq %rsp,%r12
    jne 8f
    leaq -7(%r13),%rdx
    CHECK k_pairs, %rax, %rdx, 7
    /* pairs in a row, memory and immediate operands, pops into other registers */
    pushq %rbx
    pushq 0x10(%r8)
    pushq $0x77
    pushq %rsi
    popq %rax
    popq %rcx
    popq 0x18(%r8)
    popq %rdx
    cmpq %rsp,%r12
    jne 8f
    CHECK k_pairs, %rax, %rsi, 8
    CHECK k_pairs, %rcx, $0x77, 9
    CHECK k_pairs, 0x18(%r8), %rbx, 10
    CHECK k_pairs, %rdx, %rbx, 11
    pushq %rbx
    pushq %rsi
    popq %rbx
    popq %rsi
    xchgq %rbx,%rsi
    pushw %bx
    pushw %si
    popw %ax
    popw %cx
    cmpq %rsp,%r12
    jne 8f
    cmpw %ax,%si
    jne 7f
    cmpw %cx,%bx
    jne 7f
    pushq %rsp
    popq %rax
    CHECK k_pairs, %rax, %r12, 12
    pushfq
    pushq %rbx
    popq %rcx
    popfq
    CHECK k_pairs, %rcx, %rbx, 13
    pushq %r12
    pushq %rbx
    popq %rcx
    popq %rsp
    CHECK k_pairs, %rsp, %r12, 14
.endr
    LEAVE_K k_pairs
7:  movl $160,%eax
    jmp k_pairs_out
8:  movq %rsp,W_AUX(%r15)
    movq %r12,%rsp
    movl $108,%eax
    jmp k_pairs_out
9:  movq %r12,%rsp
    movl $109,%eax
    jmp k_pairs_out

/* ---- c: calls of a C function's shape with SSE, shifts, bit tests, conditional moves; block ends in jcc ---------- */
.globl k_mixed
k_mixed:
    ENTER_K
k_mixed_top:
    movq %rsp,%r12
.rept 3
    leaq 0x5151(%r13),%rax
    cvtsi2sdq %rax,%xmm0
    movapd %xmm0,%xmm1
    addsd %xmm1,%xmm1
    FILL 1
    cvttsd2siq %xmm1,%rdx
    leaq (%rax,%rax),%rcx
    CHECK k_mixed, %rdx, %rcx, 1
    movq %rax,%xmm2
    punpcklqdq %xmm2,%xmm2
    pshufd $0x4e,%xmm2,%xmm3
    paddq %xmm2,%xmm3
    movq %xmm3,%rdx
    CHECK k_mixed, %rdx, %rcx, 2
    ucomisd %xmm0,%xmm1
    FILL 1
    jbe 5f
    ucomisd %xmm1,%xmm0
    jae 5f
    movl $5,%ecx
    movq %rax,%rdx
    shlq %cl,%rdx
    shrq %cl,%rdx
    CHECK k_mixed, %rdx, %rax, 3
    rolq $17,%rdx
    rorq $17,%rdx
    CHECK k_mixed, %rdx, %rax, 4
    shldq $8,%rax,%rdx
    shrdq $8,%rax,%rdx
    movq %rax,%rsi
    btsq $63,%rsi
    FILL 1
    jc 5f
    btrq $63,%rsi
    FILL 1
    jnc 5f
    CHECK k_mixed, %rsi, %rax, 5
    movq %rax,%rbx
    lock cmpxchgq %rbx,0x50(%r8)
    movq %rax,%rbx
    leaq 0x5151(%r13),%rax
    movq %rax,0x50(%r8)
    movq %rax,%rbx
    leaq 1(%rax),%rdx
    cmpxchgq %rdx,0x50(%r8)
    jne 5f
    CHECK k_mixed, 0x50(%r8), %rdx, 6
    mulq %rdx
    movq %rax,%rsi
    movq %rbx,%rax
    imulq %rdx,%rcx
    leaq 0x5151(%r13),%rax
    leaq 1(%rax),%rcx
    imulq %rcx,%rax
    CHECK k_mixed, %rax, %rsi, 7
.endr
    LEAVE_K k_mixed
5:  movl $150,%eax
    jmp k_mixed_out
#ifdef WIN
#endif
