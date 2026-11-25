/* Kernels of the cost bench: what the fixes can make slower. Each b_*(u64 n, void *mem) runs n rounds. */
.text
.macro BEGIN name
.globl \name
.p2align 6
\name:
    pushq %rbx
    pushq %rbp
    pushq %r12
    pushq %r13
    pushq %r14
    pushq %r15
    movq %rdi,%r15
    movq %rsi,%r14
.p2align 5
1:
.endm
.macro END
    decq %r15
    jnz 1b
    vzeroupper
    popq %r15
    popq %r14
    popq %r13
    popq %r12
    popq %rbp
    popq %rbx
    retq
.endm
bl_a:
    pushq %rbx
    pushq %rsi
    pushq %rdi
    movq %rdx,%rbx
    movq (%rbx),%rcx
    leaq 1(%rcx),%rax
    popq %rdi
    popq %rsi
    popq %rbx
    retq
bl_b:
    pushq %rbp
    movq %rsp,%rbp
    subq $0x20,%rsp
    movq %rdx,8(%rsp)
    movq 8(%rsp),%rax
    movq %rbp,%rsp
    popq %rbp
    retq
bl_full:
    pushq %r15
    pushq %r14
    pushq %r13
    pushq %r12
    pushq %rdi
    pushq %rsi
    pushq %rbp
    pushq %rbx
    subq $0x28,%rsp
    movq %rdx,%rax
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
BEGIN b_callret
    movq %r14,%rdx
    callq bl_a
    movq %r14,%rdx
    callq bl_b
END
BEGIN b_prologue
    movq %r14,%rdx
    callq bl_full
END
BEGIN b_pushpop
.rept 8
    pushq %rax
    pushq %rcx
    popq %rdx
    popq %rsi
.endr
END
/* fib: calls, saves, moves, compares, as compilers write them */
b_fibr:
    pushq %rbp
    pushq %rbx
    subq $8,%rsp
    movl %edi,%ebx
    cmpl $2,%edi
    jl 2f
    leal -1(%rbx),%edi
    callq b_fibr
    movl %eax,%ebp
    leal -2(%rbx),%edi
    callq b_fibr
    addl %ebp,%eax
    jmp 3f
2:  movl %ebx,%eax
3:  addq $8,%rsp
    popq %rbx
    popq %rbp
    retq
BEGIN b_fib
    movl $16,%edi
    callq b_fibr
END
BEGIN b_movalu
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
END
BEGIN b_div
.rept 4
    leaq 12345(%r15),%rax
    movl $77,%ecx
    cqto
    idivq %rcx
    movl %eax,%eax
    xorl %edx,%edx
    divl %ecx
.endr
END
BEGIN b_carry
    movq (%r14),%rax
    movq 8(%r14),%rcx
    movq 16(%r14),%rdx
    movq 24(%r14),%rsi
.rept 4
    addq 32(%r14),%rax
    adcq 40(%r14),%rcx
    adcq 48(%r14),%rdx
    adcq 56(%r14),%rsi
    adcq $0,%rax
.endr
    movq %rax,64(%r14)
    movq %rsi,72(%r14)
END
BEGIN b_avxcopy
    vmovdqu (%r14),%ymm0
    vmovdqu 32(%r14),%ymm1
    vmovdqu 64(%r14),%ymm2
    vmovdqu 96(%r14),%ymm3
    vmovdqu %ymm0,0x1000(%r14)
    vmovdqu %ymm1,0x1020(%r14)
    vmovdqu %ymm2,0x1040(%r14)
    vmovdqu %ymm3,0x1060(%r14)
END
BEGIN b_avxmath
    vmovups (%r14),%ymm0
    vmovups 32(%r14),%ymm1
    vmulps %ymm0,%ymm1,%ymm2
    vaddps %ymm2,%ymm0,%ymm3
    vsubps %ymm1,%ymm3,%ymm4
    vmulps 64(%r14),%ymm4,%ymm5
    vaddps %ymm5,%ymm3,%ymm6
    vmaxps %ymm6,%ymm0,%ymm7
    vminps %ymm7,%ymm1,%ymm8
    vaddps 96(%r14),%ymm8,%ymm9
    vmulps %ymm9,%ymm9,%ymm10
    vmovups %ymm10,0x1000(%r14)
END
BEGIN b_avxregs
    vmovups (%r14),%ymm0
.rept 4
    vmulps %ymm0,%ymm0,%ymm2
    vaddps %ymm2,%ymm0,%ymm3
    vsubps %ymm2,%ymm3,%ymm4
    vmulps %ymm3,%ymm4,%ymm5
    vaddps %ymm5,%ymm3,%ymm6
    vmaxps %ymm6,%ymm0,%ymm0
.endr
    vmovups %ymm0,0x1000(%r14)
END
BEGIN b_sse
    movups (%r14),%xmm0
    movups 16(%r14),%xmm1
    movaps %xmm0,%xmm2
    mulps %xmm1,%xmm2
    movaps %xmm2,%xmm3
    addps %xmm0,%xmm3
    movaps %xmm3,%xmm4
    shufps $0x1b,%xmm4,%xmm4
    subps %xmm1,%xmm4
    movups %xmm4,0x1000(%r14)
END
BEGIN b_x87
    fldl (%r14)
    fldl 8(%r14)
    fmul %st(1),%st
    faddl 16(%r14)
    fstpl 24(%r14)
    fmull 8(%r14)
    fstpl 32(%r14)
END
BEGIN b_x87copy
    fldl (%r14)
    fstpl 24(%r14)
    fldl 8(%r14)
    fstpl 32(%r14)
END
/* the shortest loops: what a check of every round costs */
BEGIN b_empty
END
BEGIN b_sum
    addq (%r14),%rax
END
BEGIN b_bytes
    movzbl 7(%r14),%eax
    leaq 1(%r14),%r14
    testl %eax,%eax
    leaq -1(%r14),%r14
    je 1b
END
BEGIN b_copy8
    movq (%r14),%rax
    movq %rax,0x1000(%r14)
    movq 8(%r14),%rcx
    movq %rcx,0x1008(%r14)
END
BEGIN b_nest
    movl $4,%ecx
2:  addl $3,%eax
    decl %ecx
    jnz 2b
END
BEGIN b_spinread
    cmpl $0x7fffffff,0x8000(%r14)
    je 1b
END
bl_empty:
    retq
BEGIN b_vcall
    leaq bl_empty(%rip),%rax
    movq %rax,0x8000(%r14)
    callq *0x8000(%r14)
END
.macro REPS name op n
BEGIN \name
    movq %r14,%rsi
    leaq 0x4000(%r14),%rdi
    movl $\n,%ecx
    \op
END
.endm
REPS b_rep0 "rep movsb" 0
REPS b_rep16 "rep movsb" 16
REPS b_rep100 "rep movsb" 100
REPS b_rep4k "rep movsb" 4096
REPS b_stos100 "rep stosb" 100
REPS b_stos4k "rep stosb" 4096
BEGIN b_scas100
    movl $0x55,%eax
    movq %r14,%rdi
    movl $100,%ecx
    repne scasb
END
BEGIN b_mmx
    movq (%r14),%mm0
    movq 8(%r14),%mm1
    paddd %mm1,%mm0
    movq %mm0,16(%r14)
END
.section .note.GNU-stack,"",@progbits
