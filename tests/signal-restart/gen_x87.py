#!/usr/bin/env python3
"""Writes random x87 programs with one instruction that faults in the middle: gen_x87.py SEED COUNT > x87_k.S
x_N(page, image, values) runs one from a fresh stack and leaves fxsave's image of the x87 state at its end; y_N the same up to the
instruction that faults. xf_N is its address. The stack never overflows and no empty register is read."""
import random, sys
R = random.Random(int(sys.argv[1])); COUNT = int(sys.argv[2])
NV = 16  # values of 16 bytes: a double at +0, a float at +8; 80 bits at 0x100 + 16 * i; integers at 0x200 + 8 * i
def w(s): print('    ' + s)
class P:
    def __init__(self): self.st = []          # what each register from the top on holds: True when it is valid
    def live(self): return [i for i, v in enumerate(self.st) if v]
    def push(self): self.st.insert(0, True)
    def pop(self): self.st.pop(0)
    def room(self): return len(self.st) < 8
    def op(self):
        live = self.live(); top = bool(self.st) and self.st[0]
        k = R.randrange(22); v = R.randrange(NV)
        if k <= 3 and self.room(): w(f'fldl {16 * v}(%rdx)'); self.push()
        elif k == 4 and self.room(): w(f'flds {16 * v + 8}(%rdx)'); self.push()
        elif k == 5 and self.room(): w(f'fldt {0x100 + 16 * v}(%rdx)'); self.push()
        elif k == 6 and self.room(): w(f'fild{R.choice(["l", "ll"])} {0x200 + 8 * v}(%rdx)'); self.push()
        elif k == 7 and self.room(): w(R.choice(['fld1', 'fldz', 'fldpi', 'fldl2e'])); self.push()
        elif k == 8 and self.room() and live: w(f'fld %st({R.choice(live)})'); self.push()
        elif k == 9 and top and live: w(f'fxch %st({R.choice(live)})')
        elif k == 10 and top: w(R.choice(['fchs', 'fabs']))
        elif k == 11 and top: w(f'f{R.choice(["add", "mul", "sub", "subr"])}l {16 * R.randrange(6)}(%rdx)')
        elif k == 12 and top and len(live) > 1: w(f'f{R.choice(["add", "mul", "sub"])} %st({R.choice(live[1:])}),%st')
        elif k == 13 and top and len(live) > 1 and live[1] == 1: w(f'f{R.choice(["add", "mul"])}p %st,%st(1)'); self.pop()
        elif k == 14 and top: w(f'fstpl {0x400 + 16 * v}(%rdx)'); self.pop()
        elif k == 15 and top: w(f'fst{R.choice(["l", "s"])} {0x400 + 16 * v}(%rdx)')
        elif k == 16 and top and live: j = R.choice(live); w(f'fstp %st({j})'); self.pop()
        elif k == 17 and top: w('fstp %st(0)'); self.pop()
        elif k == 18 and live and R.randrange(3) == 0: j = R.choice(live); w(f'ffree %st({j})'); self.st[j] = False; self.trim()
        elif k == 19 and top: w('frndint')
        elif k == 20: w(R.choice(['addq $3,%rax', 'adcq $1,%rcx', 'movq 8(%rdx),%rax', 'movups (%rdx),%xmm1', 'adcq %rcx,0x700(%rdx)', 'pushq %rax\n    popq %rcx']))
        elif k == 21 and R.randrange(3) == 0: w('jmp 7f'); print('7:')
    def trim(self):
        while self.st and not self.st[-1]: self.st.pop()
def body(n, stop):
    R.seed(f'{sys.argv[1]}/{n}'); p = P()
    w('fninit'); w('xorl %eax,%eax'); w('xorl %ecx,%ecx'); w('movl $0x1234,%eax'); w('movups 0x30(%rdx),%xmm1')
    for _ in range(R.randrange(1, 14)): p.op()
    # the instruction that faults
    top = bool(p.st) and p.st[0]; f = []
    if top: f += ['fstpl (%rdi)', 'fstl (%rdi)', 'fstps (%rdi)', 'fstpt (%rdi)', 'fstpl (%rdi)', 'fistpll (%rdi)', 'faddl (%rdi)', 'fmuls (%rdi)', 'fcoml (%rdi)']
    if p.room(): f += ['fldl (%rdi)', 'flds (%rdi)', 'fldt (%rdi)', 'fildll (%rdi)']
    f += ['fxsave64 (%rdi)', 'fnstenv (%rdi)', 'fnsave (%rdi)', 'movq (%rdi),%mm0', 'paddd (%rdi),%mm2', 'fxsave64 (%rdi)']
    f += ['movq %rax,(%rdi)', 'addq %rax,(%rdi)', 'movq (%rdi),%rcx', 'movups %xmm1,(%rdi)', 'adcq $0,(%rdi)', 'fnstcw (%rdi)']
    i = R.choice(f)
    mmx.append('mm' in i and 'xmm' not in i); image.append(1 if 'fxsave' in i else 2 if i.startswith(('fnsave', 'fnstenv')) else 0)
    if stop: w('fxsave64 (%rsi)'); w('fninit'); w('retq'); return
    print(f'.globl xf_{n}\nxf_{n}:'); w(i)
    if 'mm' in i and 'xmm' not in i: w('emms'); p.st = []
    if i == 'fnsave (%rdi)': p.st = []
    if i.startswith('fstp') or i.startswith('fistp'): p.pop()
    if i.startswith(('fld', 'fild')): p.push()
    for _ in range(R.randrange(0, 10)): p.op()
    w('fxsave64 (%rsi)'); w('fninit'); w('retq')
mmx, image = [], []
print('.text')
for n in range(COUNT):
    for kind, stop in (('x', False), ('y', True)):
        print(f'.globl {kind}_{n}\n.p2align 4\n{kind}_{n}:'); body(n, stop)
print('.section .rodata\n.globl x87_table, x87_count\n.p2align 3\nx87_table:')
for n in range(COUNT): print(f'    .quad x_{n},y_{n},xf_{n},{int(mmx[2 * n])},{image[2 * n]}')
print(f'x87_count: .quad {COUNT}')
print('.section .note.GNU-stack,"",@progbits')
