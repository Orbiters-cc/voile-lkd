/* 32-bit kernels of susp (the game's 32-bit neighbours run them through wow64): int k32_pairs(struct wk32 *), int k32_x87(struct wk32 *). */
.text
.macro FILL32 n
.rept \n
    leal 1(%ebp),%edx
    movl %edx,%eax
    leal 3(%eax),%edx
.endr
.endm
leaf32_a:
    pushl %ebx
    pushl %esi
    pushl %edi
    movl 16(%esp),%eax
    movl %eax,%ebx
    leal 1(%ebx),%eax
    popl %edi
    popl %esi
    popl %ebx
    ret
leaf32_b:
    pushl %ebp
    movl %esp,%ebp
    pushl %ebx
    movl 8(%ebp),%ebx
    leal 2(%ebx),%eax
    popl %ebx
    leave
    ret $4
.globl _k32_pairs
_k32_pairs:
    pushl %ebx
    pushl %esi
    pushl %edi
    pushl %ebp
    subl $0x80,%esp
    movl 0x94(%esp),%edi
    xorl %ebp,%ebp
    leal 9f,%eax
    movl %eax,(%esp)
    movl %eax,4(%esp)
1:  movl %esp,%esi
    leal 0x111(%ebp),%ebx
    pushl %ebp
    calll leaf32_a
    popl %ecx
    leal 1(%ebp),%edx
    cmpl %edx,%eax
    jne 6f
    cmpl %ebp,%ecx
    jne 6f
    pushl %ebp
    calll leaf32_b
    leal 2(%ebp),%edx
    cmpl %edx,%eax
    jne 6f
    cmpl %esp,%esi
    jne 8f
    pushl %ebx
    pushl $77
    pushl %ebp
    popl %eax
    popl %ecx
    popl %edx
    cmpl %ebp,%eax
    jne 6f
    cmpl $77,%ecx
    jne 6f
    cmpl %ebx,%edx
    jne 6f
    pushal
    popal
    cmpl %ebp,%eax
    jne 6f
    movl $-1,%eax
    addl $1,%eax
    FILL32 2
    movl $0,%eax
    adcl $0,%eax
    cmpl $1,%eax
    jne 6f
    cmpl %esp,%esi
    jne 8f
    incl 4(%edi)
    incl %ebp
    cmpl $0,(%edi)
    je 1b
    xorl %eax,%eax
2:  addl $0x80,%esp
    popl %ebp
    popl %edi
    popl %esi
    popl %ebx
    ret
6:  movl $6,%eax
    movl %esi,%esp
    jmp 2b
8:  movl $8,%eax
    movl %esi,%esp
    jmp 2b
9:  movl $9,%eax
    movl %esi,%esp
    jmp 2b
.globl _k32_x87
_k32_x87:
    pushl %ebx
    pushl %esi
    pushl %edi
    pushl %ebp
    subl $0x80,%esp
    movl 0x94(%esp),%edi
    xorl %ebp,%ebp
    movl %esp,%esi
1:  movl %ebp,0x20(%esp)
    movl $1000,0x24(%esp)
    fildl 0x20(%esp)
    FILL32 1
    fildl 0x24(%esp)
    faddp
    FILL32 1
    fstl 0x28(%esp)
    fsubl 0x28(%esp)
    fiaddl 0x20(%esp)
    flds 0x24(%esp)
    fxch
    FILL32 1
    fistpl 0x30(%esp)
    fstps 0x34(%esp)
    cmpl 0x30(%esp),%ebp
    jne 6f
    movl 0x34(%esp),%eax
    cmpl 0x24(%esp),%eax
    jne 6f
    incl 4(%edi)
    incl %ebp
    andl $0xfffff,%ebp
    cmpl $0,(%edi)
    je 1b
    xorl %eax,%eax
2:  addl $0x80,%esp
    popl %ebp
    popl %edi
    popl %esi
    popl %ebx
    ret
6:  movl $6,%eax
    jmp 2b
