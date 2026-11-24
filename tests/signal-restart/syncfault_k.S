/* Cases of the synchronous-fault witness: t_*(u64 page, u64 *out, u64 *in). Each accesses the host page at `page`, which the
 * caller may have made inaccessible or read-only; its handler gives the access back and returns, and the instruction must run
 * as if nothing had happened. The results go to out[0..7] and to the memory around `page`. *_f is the instruction that
 * faults: the address the handler must be given (or *_g, where two stack operations may fault as one). */
.text
.macro T name
.globl t_\name
t_\name:
    pushq %rbx
    pushq %rbp
    pushq %r12
    pushq %r13
    pushq %r14
    pushq %r15
    pushq %rsi
    movq %rsp,%r15
    movq %rdi,%r14                  /* r14 = page */
    movq (%rdx),%r13                /* r13 = the round's value */
    xorl %eax,%eax
    xorl %ebx,%ebx
    xorl %ecx,%ecx
    xorl %edx,%edx
    xorl %esi,%esi
    xorl %edi,%edi
    xorl %ebp,%ebp
    xorl %r8d,%r8d
    xorl %r9d,%r9d
    xorl %r10d,%r10d
    xorl %r11d,%r11d
    xorl %r12d,%r12d
    cld
.endm
/* rax rbx rcx rdx rsi rdi rbp + the flags (but AF) + rsp - its value at entry */
.macro R
    movq %rsp,%r11
    movq %r15,%rsp
    pushfq
    movq 8(%rsp),%r10
    movq %rax,(%r10)
    movq %rbx,8(%r10)
    movq %rcx,16(%r10)
    movq %rdx,24(%r10)
    movq %rsi,32(%r10)
    movq %rdi,40(%r10)
    movq %rbp,48(%r10)
    popq %rax
    andl $0xcc5,%eax
    movq %rax,56(%r10)
    movq %r11,64(%r10)
    cld
    vzeroupper
    popq %rsi
    popq %r15
    popq %r14
    popq %r13
    popq %r12
    popq %rbp
    popq %rbx
    retq
.endm
.macro F name
.globl t_\name\()_f
t_\name\()_f:
.endm
.macro G name
.globl t_\name\()_g
t_\name\()_g:
.endm
/* ---- pairs ---- */
T pop_pair                          /* the second pop's slot is on the page */
    movq %r13,-8(%r14)
    movq $0x11,%rax
    movq $0x22,%rbx
    leaq -8(%r14),%rsp
G pop_pair
    popq %rax
F pop_pair
    popq %rbx
    R
T pop_ret                           /* pop; ret, the return address on the page */
    movq %r13,-8(%r14)
    leaq -8(%r14),%rsp
G pop_ret
    popq %rax
F pop_ret
    retq
    ud2
.globl t_pop_ret_9
t_pop_ret_9:
    addq $1,%rbx
    R
T push_pair
    leaq 8(%r14),%rsp
    addq $0x4000,%rsp
    movq $0x33,%rax
    movq %r13,%rbx
G push_pair
    pushq %rax
F push_pair
    pushq %rbx
    R
T push_call
    leaq 0x4008(%r14),%rsp
    movq %r13,%rax
G push_call
    pushq %rax
F push_call
    callq 8f
    R
8:  popq %rcx
    leaq 8b(%rip),%rdx
    subq %rdx,%rcx
    R
T push_mem                          /* the operand on the page */
F push_mem
    pushq 0x10(%r14)
    popq %rax
    R
T pop_mem                           /* the destination on the page */
    pushq %r13
    pushq $0x44
F pop_mem
    popq 0x10(%r14)
    popq %rax
    R
T pop_mem_rsp                       /* ... addressed by rsp, which the pop has moved by then */
    movq %r13,-0x18(%r14)
    leaq -0x18(%r14),%rsp
F pop_mem_rsp
    popq 0x18(%rsp)
    R
T pop_mem16
    pushq %r13
F pop_mem16
    popw 0x10(%r14)
    popw %ax
    R
T pop_pop_mem
    pushq %r13
    pushq $0x55
    popq %rax
F pop_pop_mem
    popq 0x20(%r14)
    R
T leave_ret
    movq %r13,-8(%r14)
    leaq -8(%r14),%rbp
G leave_ret
    leave
F leave_ret
    retq
    R
T push_flags
    leaq 0x4000(%r14),%rsp
    movq $-1,%rax
    addq $1,%rax
F push_flags
    pushfq
    popq %rcx
    andl $0x8c5,%ecx
    adcq $0,%rax
    R
/* ---- moves ---- */
T mov_load
    leaq 0x40(%r14),%rbx
    movq $0x66,%rax
    movq %rbx,%rax
F mov_load
    movq (%rax),%rax
    R
T mov_add_mem
    movq %r13,%rbx
    movq $0x66,%rax
    movq %rbx,%rax
F mov_add_mem
    addq 0x40(%r14),%rax
    R
T xchg_store
    movq %r13,%rax
    movq $0x77,%rcx
    xchgq %rax,%rcx
F xchg_store
    movq %rcx,0x48(%r14)
    R
T cqo_idiv_mem
    movq %r13,%rax
    negq %rax
    movq $0x99,%rdx
    cqto
F cqo_idiv_mem
    idivq 0x50(%r14)
    R
/* ---- flags over and in a faulting instruction ---- */
T add_store_adc
    movq $-1,%rax
    addq $1,%rax
F add_store_adc
    movq %r13,0x58(%r14)
    adcq $0,%rbx
    R
T add_load_adc
    xorl %eax,%eax
    addq $1,%rax                    /* CF = 0 */
F add_load_adc
    movq 0x58(%r14),%rcx
    adcq $0,%rbx
    R
T sub_store_sbb
    xorl %eax,%eax
    subq $1,%rax
F sub_store_sbb
    movq %r13,0x58(%r14)
    sbbq $0,%rbx
    R
T cmp_store_jcc
    cmpq $5,%r13
F cmp_store_jcc
    movq %r13,0x58(%r14)
    seta %bl
    setg %cl
    setp %dl
    R
T adc_mem1                          /* carry of an addition */
    movq $-1,%rax
    addq $1,%rax
F adc_mem1
    adcq %r13,0x60(%r14)
    R
T adc_mem0
    xorl %eax,%eax
    addq $1,%rax
F adc_mem0
    adcq %r13,0x60(%r14)
    R
T adc_mem_b                         /* carry of a borrow */
    xorl %eax,%eax
    subq $1,%rax
F adc_mem_b
    adcl %r13d,0x60(%r14)
    R
T sbb_mem1
    movq $-1,%rax
    addq $1,%rax
F sbb_mem1
    sbbq %r13,0x60(%r14)
    R
T sbb_mem_b
    xorl %eax,%eax
    subq $1,%rax
F sbb_mem_b
    sbbq %r13,0x60(%r14)
    R
T adcb_mem
    movq $-1,%rax
    addq $1,%rax
F adcb_mem
    adcb %r13b,0x61(%r14)
    R
T adcw_mem
    xorl %eax,%eax
    subq $1,%rax
F adcw_mem
    adcw %r13w,0x62(%r14)
    R
T rcl_mem
    movq $-1,%rax
    addq $1,%rax
F rcl_mem
    rclq $1,0x60(%r14)
    R
T rcr_mem
    xorl %eax,%eax
    subq $1,%rax
    movl $3,%ecx
F rcr_mem
    rcrq %cl,0x60(%r14)
    R
T rcr_mem_a                         /* carry of an addition, variable count: the translation branches before its load */
    movq $-1,%rax
    addq $1,%rax
    movl $3,%ecx
F rcr_mem_a
    rcrq %cl,0x60(%r14)
    R
T rcl_mem_a
    movq $-1,%rax
    addq $1,%rax
    movl $3,%ecx
F rcl_mem_a
    rclq %cl,0x60(%r14)
    R
T rclb_mem_a
    xorl %eax,%eax
    addq $1,%rax
    movl $3,%ecx
F rclb_mem_a
    rclb %cl,0x60(%r14)
    R
T rep_lodsb                         /* keeps the flags */
    leaq -0x10(%r14),%rsi
    movl $0x30,%ecx
    movq $-1,%rax
    addq $1,%rax
F rep_lodsb
    rep lodsb
    adcq $0,%rbx
    R
T adcx_mem
    movq $-1,%rax
    addq $1,%rax
    movq %r13,%rax
F adcx_mem
    adcxq 0x60(%r14),%rax
    R
T cmov_mem
    movq $-1,%rax
    addq $1,%rax
F cmov_mem
    cmovbq 0x60(%r14),%rax
    adcq $0,%rbx
    R
T sahf_push                         /* the second push on the page, the carry of an addition alive */
    leaq 0x4008(%r14),%rsp
    movq $-1,%rax
    addq $1,%rax
G sahf_push
    pushq %rax
F sahf_push
    callq 8f
    R
8:  setc %bl
    adcq $0,%rax
    popq %rcx
    xorl %ecx,%ecx
    R
T inc_mem
    movq $-1,%rax
    addq $1,%rax
F inc_mem
    incq 0x60(%r14)
    R
T add_mem
    stc
F add_mem
    addq %r13,0x60(%r14)
    R
T neg_mem
F neg_mem
    negq 0x60(%r14)
    R
T shl_mem
    movl $5,%ecx
    stc
F shl_mem
    shlq %cl,0x60(%r14)
    R
T shl0_mem                          /* a shift by 0 leaves the flags */
    movq $-1,%rax
    addq $1,%rax
F shl0_mem
    shlq %cl,0x60(%r14)
    R
T setc_mem
    movq $-1,%rax
    addq $1,%rax
F setc_mem
    setc 0x60(%r14)
    adcq $0,%rbx
    R
T bts_mem
    movq %r13,%rcx
    andl $63,%ecx
F bts_mem
    btsq %rcx,0x60(%r14)
    R
/* ---- read-modify-write ---- */
T xchg_mem
    movq %r13,%rax
F xchg_mem
    xchgq %rax,0x68(%r14)
    R
T xadd_mem
    movq %r13,%rax
F xadd_mem
    xaddq %rax,0x68(%r14)
    R
T lock_xadd_mem
    movq %r13,%rax
F lock_xadd_mem
    lock xaddq %rax,0x68(%r14)
    R
T lock_add_mem
F lock_add_mem
    lock addq %r13,0x68(%r14)
    R
T lock_adc_mem
    movq $-1,%rax
    addq $1,%rax
F lock_adc_mem
    lock adcq %r13,0x68(%r14)
    R
T cmpxchg_mem
    movq $0x1234,%rax
    movq %r13,%rbx
F cmpxchg_mem
    cmpxchgq %rbx,0x68(%r14)
    R
T lock_cmpxchg_mem
    movq $0x1234,%rax
    movq %r13,%rbx
F lock_cmpxchg_mem
    lock cmpxchgq %rbx,0x68(%r14)
    R
T cmpxchg16b_mem
    movq $1,%rax
    movq $2,%rdx
    movq %r13,%rbx
    movq $5,%rcx
F cmpxchg16b_mem
    lock cmpxchg16b 0x80(%r14)
    R
T mul_mem
    movq %r13,%rax
F mul_mem
    mulq 0x68(%r14)
    setc %bl                        /* the other flags are undefined */
    seto %cl
    testq %rax,%rax
    R
/* ---- string instructions ---- */
T movsq_
    leaq -0x40(%r14),%rsi
    leaq 0x10(%r14),%rdi
F movsq_
    movsq
    lodsq
    R
T movsq_std
    leaq -0x40(%r14),%rsi
    leaq 0x10(%r14),%rdi
    movq %r13,(%rsi)
    std
    leaq 1(%r13),%rax
F movsq_std
    movsq
    lodsb
    R
T stosq_std
    leaq 0x20(%r14),%rdi
    movq %r13,%rax
    std
F stosq_std
    stosq
    R
T rep_movsb                         /* over the page's first byte */
    leaq -0x200(%r14),%rsi
    leaq -0x31(%r14),%rdi
    movl $0x61,%ecx
F rep_movsb
    rep movsb
    R
T rep_movsb_down                    /* memmove to a lower address: the source is overwritten as it is read */
    leaq -0x30(%r14),%rsi
    leaq -0x33(%r14),%rdi
    movl $0x75,%ecx
F rep_movsb_down
    rep movsb
    R
T rep_movsq_down
    leaq -0x30(%r14),%rsi
    leaq -0x38(%r14),%rdi
    movl $20,%ecx
F rep_movsq_down
    rep movsq
    R
T rep_movsb_fill                    /* one byte spread upwards */
    leaq -0x41(%r14),%rsi
    leaq -0x40(%r14),%rdi
    movl $0x70,%ecx
F rep_movsb_fill
    rep movsb
    R
T rep_movsb_up                      /* backwards, to a higher address */
    leaq 0x4030(%r14),%rsi
    leaq 0x4033(%r14),%rdi
    movl $0x75,%ecx
    std
F rep_movsb_up
    rep movsb
    R
T rep_stosb
    leaq -0x33(%r14),%rdi
    movl $0x75,%ecx
    movq %r13,%rax
F rep_stosb
    rep stosb
    R
T rep_cmpsb
    leaq -0x30(%r14),%rsi
    leaq 0x10000-0x30(%r14),%rdi
    movl $0x75,%ecx
F rep_cmpsb
    repe cmpsb
    R
T rep_scasb
    leaq -0x30(%r14),%rdi
    movl $0x75,%ecx
    movq %rax,(%rdi)
    movq %rax,8(%rdi)
    movq %rax,16(%rdi)
    movq %rax,24(%rdi)
    movq %rax,32(%rdi)
    movq %rax,40(%rdi)
    movb $0xee,%al
F rep_scasb
    repne scasb
    R
/* ---- vectors ---- */
T sse_load
    movq %r13,%xmm0
    movdqa %xmm0,%xmm1
F sse_load
    paddq 0x80(%r14),%xmm1
    movq %xmm1,%rax
    movq %xmm0,%rbx
    R
T avx_store
    vmovq %r13,%xmm0
    vpbroadcastq %xmm0,%ymm0
    vpaddq %ymm0,%ymm0,%ymm1
    vpaddq %ymm1,%ymm0,%ymm2
F avx_store
    vmovdqu %ymm2,0x80(%r14)
    vextracti128 $1,%ymm1,%xmm3
    vmovq %xmm3,%rax
    vextracti128 $1,%ymm2,%xmm3
    vmovq %xmm3,%rbx
    R
T avx_load
    vmovq %r13,%xmm0
    vpbroadcastq %xmm0,%ymm0
    vpaddq %ymm0,%ymm0,%ymm1
F avx_load
    vpaddq 0x80(%r14),%ymm1,%ymm1
    vmovdqu %ymm1,-0x100(%r14)
    vmovdqu %ymm0,-0x140(%r14)
    R
T avx_load_cross                    /* the second half on the page; destination = source */
    vmovq %r13,%xmm0
    vpbroadcastq %xmm0,%ymm0
F avx_load_cross
    vpaddq -0x10(%r14),%ymm0,%ymm0
    vmovdqu %ymm0,-0x100(%r14)
    R
T avx_store_cross
    vmovq %r13,%xmm0
    vpbroadcastq %xmm0,%ymm0
    vpaddq %ymm0,%ymm0,%ymm0
F avx_store_cross
    vmovdqu %ymm0,-0x10(%r14)
    vmovdqu %ymm0,-0x100(%r14)
    R
T avx_scalar_store                  /* a scalar store between two 256-bit instructions */
    vmovq %r13,%xmm0
    vpbroadcastq %xmm0,%ymm0
    vpaddq %ymm0,%ymm0,%ymm1
F avx_scalar_store
    movq %r13,0x90(%r14)
    vpaddq %ymm1,%ymm0,%ymm2
    vmovdqu %ymm2,-0x100(%r14)
    R
T avx_gather
    vpxor %xmm0,%xmm0,%xmm0
    vpcmpeqd %ymm1,%ymm1,%ymm1
    movl $8,%eax
    vmovd %eax,%xmm2
    vpbroadcastd %xmm2,%ymm2
    vpaddd %ymm2,%ymm2,%ymm3
    vpunpckldq %ymm3,%ymm2,%ymm2
F avx_gather
    vpgatherdd %ymm1,-16(%r14,%ymm2,4),%ymm0
    vmovdqu %ymm0,-0x100(%r14)
    R
T avx_maskstore
    vmovq %r13,%xmm0
    vpbroadcastq %xmm0,%ymm0
    vpcmpeqd %ymm1,%ymm1,%ymm1
    vpsrlq $32,%ymm1,%ymm1
    vpslld $31,%ymm1,%ymm1
F avx_maskstore
    vpmaskmovd %ymm0,%ymm1,-0x10(%r14)
    vmovdqu %ymm0,-0x100(%r14)
    R
T x87_store
    movq %r13,-0x20(%r14)
    fildll -0x20(%r14)
    fildll -0x20(%r14)
    faddp
    fildll -0x20(%r14)
F x87_store
    fistpll 0x90(%r14)
    fistpll -0x18(%r14)
    R
T x87_load
    movq %r13,-0x20(%r14)
    fildll -0x20(%r14)
F x87_load
    fildll 0xa0(%r14)
    faddp
    fistpll -0x18(%r14)
    R
T x87_scalar_store
    movq %r13,-0x20(%r14)
    fildll -0x20(%r14)
    fld %st
    faddp
F x87_scalar_store
    movq %r13,0x90(%r14)
    fistpll -0x18(%r14)
    R
T mmx_store
    movq %r13,%mm0
    paddq %mm0,%mm0
F mmx_store
    movq %mm0,0x90(%r14)
    paddq %mm0,%mm0
    movq %mm0,%rax
    emms
    R
/* ---- 10000 instructions with a parity branch over them (far branches), the fault in the middle ---- */
T big
    movl $1,%esi
    xorps %xmm0,%xmm0
    xorps %xmm1,%xmm1
big_top:
.macro BIGPART
.rept 800
    addq $1,%rax
    addl $1,-0x40(%r14)
    ucomiss %xmm1,%xmm0
    jp 4f
.endr
.endm
    BIGPART
    addq $1,%rbx
F big
    addq $1,0xb0(%r14)
    addq $1,%rcx
    BIGPART
    movl $1,%edx
    testl %edx,%edx
    jp big_top
4:  R
T bigctl
    movl $1,%esi
    xorps %xmm0,%xmm0
    xorps %xmm1,%xmm1
.rept 800
    addq $1,%rax
    addl $1,-0x40(%r14)
    ucomiss %xmm1,%xmm0
    jb 4f
.endr
    addq $1,%rbx
F bigctl
    addq $1,0xb0(%r14)
    addq $1,%rcx
.rept 800
    addq $1,%rax
    addl $1,-0x40(%r14)
    ucomiss %xmm1,%xmm0
    jb 4f
.endr
4:  R
