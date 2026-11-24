#!/usr/bin/env python3
"""Writes the soak's kernels: gen_soak.py SEED COUNT > soak_k.S
Each s_N(scratch) runs one fixed random program from one fixed state and returns a hash of the registers, the stack pointer, the
flags and the memory at its end, so it must return the same for ever, however often it is stopped. The programs are made of what
a boundary between two instructions can get wrong: pushes and pops of every kind in every order, calls to functions with varied
epilogues, moves and exchanges whose results are overwritten, flags kept alive over other instructions, carries to memory, string
instructions, 256-bit registers, x87, MMX. Flags that x86 leaves undefined are never read."""
import random, sys
R = random.Random(int(sys.argv[1])); COUNT = int(sys.argv[2])
G = ['rax', 'rbx', 'rcx', 'rdx', 'rsi', 'rdi', 'rbp', 'r8', 'r9', 'r10', 'r11']
def n32(r): return 'r%sd' % r[1:] if r[1:].isdigit() else 'e' + r[1:]
def n16(r): return 'r%sw' % r[1:] if r[1:].isdigit() else r[1:]
def n8(r): return 'r%sb' % r[1:] if r[1:].isdigit() else {'rax': 'al', 'rbx': 'bl', 'rcx': 'cl', 'rdx': 'dl', 'rsi': 'sil', 'rdi': 'dil', 'rbp': 'bpl'}[r]
out = []
def w(s): out.append('    ' + s)
class P:
    def __init__(self, x87): self.fl = False; self.x87 = x87; self.lab = 0
    def r(self, *no): return R.choice([x for x in G if x not in no])
    def m(self): return '%d(%%r14)' % (8 * R.randrange(32))
    def imm(self): return R.choice([1, 2, 5, 0x7f, 0x1234, 0x7fffffff, -1, -77])
    def alu(self):
        op = R.choice(['add', 'sub', 'xor', 'and', 'or', 'cmp', 'test']); k = R.randrange(6); a = self.r(); b = self.r()
        if k == 0: w(f'{op}q %{a},%{b}')
        elif k == 1: w(f'{op}l %{n32(a)},%{n32(b)}')
        elif k == 2: w(f'{op}q ${self.imm()},%{b}')
        elif k == 3: w(f'{op}q {self.m()},%{b}' if op != 'test' else f'testq %{b},{self.m()}')
        elif k == 4: w(f'{op}q %{a},{self.m()}')
        else: w(f'{op}b %{n8(a)},%{n8(b)}')
        self.fl = True
    def carry(self):
        if not self.fl: return self.alu()
        k = R.randrange(8); a = self.r(); b = self.r()
        op = R.choice(['adc', 'sbb'])
        if k == 0: w(f'{op}q %{a},%{b}')
        elif k == 1: w(f'{op}l %{n32(a)},%{n32(b)}')
        elif k == 2: w(f'{op}q %{a},{self.m()}')
        elif k == 3: w(f'{op}q ${R.choice([0, 3])},%{b}')
        elif k == 4: w(f'{R.choice(["inc", "dec"])}q %{b}')
        elif k == 5: w(f'{R.choice(["inc", "dec"])}l {self.m()}')
        elif k == 6: w(f'{op}b %{n8(a)},%{n8(b)}')
        else: w(f'{R.choice(["cmc", "stc", "clc"])}')
    def use(self):
        if not self.fl: return self.alu()
        k = R.randrange(3); a = self.r(); b = self.r(); c = R.choice(['e', 'ne', 'b', 'ae', 'be', 'a', 's', 'ns', 'l', 'ge', 'le', 'g', 'o', 'no', 'p', 'np'])
        if k == 0: w(f'set{c} %{n8(a)}')
        elif k == 1: w(f'cmov{c}q %{a},%{b}')
        else:
            w(f'j{c} 7f'); w(f'leaq 0x55(%{a}),%{b}'); w(f'notq %{self.r()}'); out.append('7:')
    def move(self):
        k = R.randrange(9); a = self.r(); b = self.r()
        if k == 0: w(f'movq %{a},%{b}')
        elif k == 1: w(f'movl %{n32(a)},%{n32(b)}')
        elif k == 2: w(f'leaq {R.randrange(99)}(%{a},%{self.r()},{R.choice([1, 2, 4, 8])}),%{b}')
        elif k == 3: w(f'xchgq %{a},%{b}')
        elif k == 4: w(f'movq {self.m()},%{b}')
        elif k == 5: w(f'movq %{a},{self.m()}')
        elif k == 6: w(f'movzbl %{n8(a)},%{n32(b)}')
        elif k == 7: w(f'movswq %{n16(a)},%{b}')
        else: w(f'bswapq %{b}')
    def arith(self):
        k = R.randrange(7); a = self.r(); b = self.r()
        if k == 0: w(f'imulq %{a},%{b}'); self.fl = False
        elif k == 1: w(f'{R.choice(["shl", "shr", "sar", "rol", "ror"])}q ${R.randrange(1, 63)},%{b}'); self.fl = False
        elif k == 2: w(f'movb ${R.randrange(1, 60)},%cl'); w(f'{R.choice(["shl", "shr", "ror"])}q %cl,%{self.r("rcx")}'); self.fl = False
        elif k == 3:
            w('movq $%d,%%rcx' % R.choice([3, 7, 1000, -13])); w('cqto'); w('idivq %rcx'); self.fl = False
        elif k == 4: w(f'movl ${R.randrange(1, 9999)},%ecx'); w('xorl %edx,%edx'); w('divl %ecx'); self.fl = False
        elif k == 5: w(f'xaddq %{a},%{b}'); self.fl = True
        else: w(f'{R.choice(["neg", "not"])}q %{b}') ; self.fl = self.fl and out[-1].strip().startswith('not') or out[-1].strip().startswith('neg')
    def stack(self):
        n = R.randrange(1, 5)
        for _ in range(n):
            k = R.randrange(6)
            if k < 3: w(f'pushq %{self.r()}')
            elif k == 3: w(f'pushq ${self.imm()}')
            elif k == 4: w(f'pushq {self.m()}')
            else:
                if self.fl: w('pushfq'); w('andq $0x8c5,(%rsp)'); w('testq %rsp,%rsp') ; self.fl = True
                else: w(f'pushq %{self.r()}')
            if R.randrange(4) == 0: self.one(nostack=True)
        for _ in range(n):
            k = R.randrange(8)
            if k < 6: w(f'popq %{self.r()}')
            elif k == 6: w(f'popq {self.m()}')
            else: w(f'popw %{n16(self.r())}'); w('leaq 6(%rsp),%rsp')
            if R.randrange(5) == 0: self.one(nostack=True)
    def call(self): w('callq soak_leaf%d' % R.randrange(LEAVES)); self.fl = False
    def atomic(self):
        a = self.r()
        k = R.randrange(4)
        if k == 0: w(f'lock xaddq %{a},{self.m()}'); self.fl = True
        elif k == 1: w(f'xchgq %{a},{self.m()}')
        elif k == 2: w(f'lock cmpxchgq %{a},{self.m()}'); self.fl = True
        else: w(f'lock addq %{a},{self.m()}'); self.fl = True
    def string(self):
        a, b = 8 * R.randrange(1, 16), 8 * R.randrange(1, 16); k = R.randrange(4)
        w(f'leaq {a}(%r14),%rsi'); w(f'leaq {b}(%r14),%rdi')
        if k == 0: w('movsq')
        elif k == 1: w('std'); w('movsq'); w('leaq 1(%rdx,%rbx),%rdx'); w('movq %rdx,%rbx'); w('lodsq'); w('cld')
        elif k == 2: w(f'movl ${R.randrange(1, 60)},%ecx'); w('rep movsb')
        else: w(f'movl ${R.randrange(1, 9)},%ecx'); w('rep stosq')
    def sse(self):
        k = R.randrange(10); a, b, c = (R.randrange(8) for _ in range(3))
        if k == 0: w(f'movq %{self.r()},%xmm{a}')
        elif k == 1: w(f'movq %xmm{a},%{self.r()}')
        elif k == 2: w(f'paddq %xmm{a},%xmm{b}')
        elif k == 3: w(f'movdqa %xmm{a},%xmm{b}'); w(f'pxor %xmm{c},%xmm{b}')
        elif k == 4: w(f'pshufd ${R.randrange(256)},%xmm{a},%xmm{b}')
        elif k == 5: w(f'movdqu {8 * R.randrange(31)}(%r14),%xmm{a}')
        elif k == 6: w(f'movdqu %xmm{a},{8 * R.randrange(31)}(%r14)')
        elif k == 7: w(f'punpcklqdq %xmm{a},%xmm{b}')
        elif k == 8: w(f'cvtsi2sdl %{n32(self.r())},%xmm{a}'); w(f'addsd %xmm{a},%xmm{a}')
        else: w(f'cvtsi2sdl %{n32(self.r())},%xmm{a}'); w(f'cvtsi2sdl %{n32(self.r())},%xmm{b}'); w(f'ucomisd %xmm{a},%xmm{b}'); self.fl = True
    def avx(self):
        k = R.randrange(9); a, b, c = (R.randrange(8) for _ in range(3))
        if k == 0: w(f'vpaddq %ymm{a},%ymm{b},%ymm{c}')
        elif k == 1: w(f'vpxor %ymm{a},%ymm{b},%ymm{c}')
        elif k == 2: w(f'vmovdqu {8 * R.randrange(28)}(%r14),%ymm{a}')
        elif k == 3: w(f'vmovdqu %ymm{a},{8 * R.randrange(28)}(%r14)')
        elif k == 4: w(f'vextracti128 ${R.randrange(2)},%ymm{a},%xmm{b}')
        elif k == 5: w(f'vinserti128 ${R.randrange(2)},%xmm{a},%ymm{b},%ymm{c}')
        elif k == 6: w(f'vmovdqa %ymm{a},%ymm{b}'); w(f'vpaddq %ymm{b},%ymm{c},%ymm{b}')
        elif k == 7: w(f'vpermq ${R.randrange(256)},%ymm{a},%ymm{b}')
        else: w(f'vmovq %{self.r()},%xmm{a}'); w(f'vpbroadcastq %xmm{a},%ymm{a}')
    def fp(self):
        if self.x87 == 1:
            for _ in range(R.randrange(1, 3)):
                w(f'fildl {self.m()}')
                if R.randrange(2): self.one(nostack=True, plain=True)
                w(f'fildl {self.m()}')
                if R.randrange(2): w(R.choice(['fxch', 'fld %st(1)\n    fstp %st(2)', 'fchs', 'fabs']))
                if R.randrange(2): self.one(nostack=True, plain=True)
                w(R.choice(['faddp', 'fmulp', 'fsubp']))
                if R.randrange(2): self.one(nostack=True, plain=True)
                w(R.choice(['fistpll', 'fstpl']) + f' {self.m()}')
        else:
            a, b = R.randrange(4), R.randrange(4)
            k = R.randrange(4)
            if k == 0: w(f'movq %{self.r()},%mm{a}')
            elif k == 1: w(f'paddq %mm{a},%mm{b}')
            elif k == 2: w(f'movq %mm{a},%{self.r()}')
            else: w(f'movq %mm{a},{self.m()}')
    def one(self, nostack=False, plain=False):
        c = [(self.alu, 4), (self.carry, 4), (self.use, 3), (self.move, 6), (self.arith, 2)]
        if not plain: c += [(self.atomic, 1), (self.sse, 2), (self.avx, 3), (self.fp, 2)]
        if not nostack: c += [(self.stack, 6), (self.call, 3), (self.string, 1)]
        R.choices([x for x, _ in c], [y for _, y in c])[0]()
LEAVES = 14
def leaf(i):
    out.append('soak_leaf%d:' % i); p = P(1); kind = i % 7
    regs = R.sample([x for x in G if x not in ('rax',)], R.randrange(1, 8)); frame = R.choice([0, 8, 0x28])
    body = ['leaq %d(%%%s,%%%s),%%rax' % (i, R.choice(G), R.choice(G)), 'movq %%%s,%%%s' % (R.choice(G), R.choice([x for x in G if x in regs] or ['rax']))]
    if kind == 6: w('pushq %rbp'); w('movq %rsp,%rbp'); w('pushq %rbx'); w('pushq %rsi'); w('leaq 1(%rbx,%rsi),%rax'); w('leave') if False else None; w('leaq -16(%rbp),%rsp'); w('popq %rsi'); w('popq %rbx'); w('popq %rbp'); w('retq'); return
    if kind == 5: w('pushq %rbp'); w('movq %rsp,%rbp'); w('subq $0x20,%rsp'); w('movq %rdi,8(%rsp)'); w('movq 8(%rsp),%rax'); w('leave'); w('retq'); return
    for r in regs: w(f'pushq %{r}')
    if frame: w(f'subq ${frame},%rsp')
    for b in body: w(b)
    if kind == 1: w('nop'); w('nop')
    if frame: w(f'addq ${frame},%rsp')
    for k, r in enumerate(reversed(regs)):
        w(f'popq %{r}')
        if kind == 2 and k == 0: w('movq %rax,%r11' if 'r11' not in regs else 'nop')
    if kind == 3: w('jmp soak_leaf5')
    elif kind == 4: w('jmp 8f'); w('.skip 32, 0x90'); out.append('8:'); w('retq')
    else: w('retq')
def kernel(i):
    p = P(1 + (i % 4 == 3))
    out.append(f'.globl s_{i}\n.p2align 5\ns_{i}:')
    for r in ('rbx', 'rbp', 'r12', 'r13', 'r14', 'r15'): w(f'pushq %{r}')
    w('subq $0x88,%rsp'); w('movq %rdi,%r14'); w('movq %rsp,%r12')
    for k in range(32): w(f'movq ${(k * 0x01010203 + i) & 0x7fffffff},{8 * k}(%r14)')
    for k, r in enumerate(G): w(f'movq ${(0x12345678 * (k + 1) + i) & 0x7fffffff},%{r}')
    for k in range(8): w(f'vmovdqu {8 * k}(%r14),%ymm{k}')
    if p.x87 == 2:
        for k in range(4): w(f'movq %rax,%mm{k}')
    for _ in range(R.randrange(30, 90)): p.one()
    if p.fl: w('pushfq'); w('popq %r13'); w('andl $0x8c5,%r13d')
    else: w('xorl %r13d,%r13d')
    if p.x87 == 2:
        for k in range(4): w(f'movq %mm{k},{0x100 + 8 * k}(%r14)')
        w('emms')
    else:
        for k in range(4): w(f'movq $0,{0x100 + 8 * k}(%r14)')
    for k in range(8): w(f'vmovdqu %ymm{k},{0x120 + 32 * k}(%r14)')
    for k, r in enumerate(G): w(f'movq %{r},{0x220 + 8 * k}(%r14)')
    w('movq %r13,0x278(%r14)'); w('movq %rsp,%rax'); w('subq %r12,%rax'); w('movq %rax,0x280(%r14)'); w('movq %r12,%rsp')
    w('movabsq $0x9e3779b97f4a7c15,%rcx'); w('xorl %eax,%eax'); w('xorl %edx,%edx')
    out.append('1:'); w('xorq (%r14,%rdx,8),%rax'); w('imulq %rcx,%rax'); w('rolq $23,%rax'); w('incq %rdx'); w('cmpq $81,%rdx'); w('jne 1b')
    w('cld'); w('vzeroupper'); w('addq $0x88,%rsp')
    for r in reversed(('rbx', 'rbp', 'r12', 'r13', 'r14', 'r15')): w(f'popq %{r}')
    w('retq')
out.append('/* Written by gen_soak.py %s */\n.text' % ' '.join(sys.argv[1:]))
for i in range(LEAVES): leaf(i)
for i in range(COUNT): kernel(i)
out.append('.data\n.globl soak_table, soak_count\nsoak_table:')
for i in range(COUNT): w(f'.quad s_{i}')
out.append(f'soak_count:\n    .quad {COUNT}')
print('\n'.join(out))
