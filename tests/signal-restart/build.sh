#!/bin/sh
# Builds the witnesses into BIN (default ./bin): the Linux ones static and freestanding with an x86-64 clang and ld.lld
# (LLVM_BIN, default the llvm 15 of ~/.orbiters-forks/toolchains), the Windows one with mingw (MINGW, a compiler).
set -eu
D=$(cd "$(dirname "$0")" && pwd); BIN="${1:-$D/bin}"; mkdir -p "$BIN"
L="${LLVM_BIN:-$HOME/.orbiters-forks/toolchains/llvm15/llvm@15/15.0.7/bin}"
Z="${LLVM_DYLIBS:-$HOME/.orbiters-forks/toolchains/zstd/arm64_tahoe/zstd/1.5.7_1/lib}"
MINGW="${MINGW:-x86_64-w64-mingw32-gcc}"
SEP="-Wl,-z,separate-loadable-segments -Wl,-z,max-page-size=65536" # no data in a 16 KiB page with code: that is sigstorm_val
cc() { out=$1; shift; DYLD_LIBRARY_PATH="$Z" "$L/clang" --target=x86_64-linux-gnu -O1 -mno-avx -ffreestanding -fno-builtin -nostdlib -static -fno-stack-protector -fno-pic \
  -fno-asynchronous-unwind-tables -Wall -Wno-unused-function --ld-path="$L/ld.lld" -Wl,--build-id=none $SEP -o "$BIN/$out" "$@"; }
cd "$D"
cc sigstorm sigstorm.c sigstorm_k.S audit_k.S
cc sigstorm_far -DFARLEAF sigstorm.c sigstorm_k.S audit_k.S
cc sigstorm_nop -DFARLEAF -DLEAFNOP sigstorm.c sigstorm_k.S audit_k.S
cc sigstorm_jmp -DFARLEAF -DLEAFJMP sigstorm.c sigstorm_k.S audit_k.S
cc sigstorm_split -DFARLEAF -DLEAFSPLIT sigstorm.c sigstorm_k.S audit_k.S
SEP="" cc sigstorm_val sigstorm.c sigstorm_k.S audit_k.S
python3 gen_soak.py "${SOAK_SEED:-1}" "${SOAK_COUNT:-60}" > "$BIN/soak_k.S"
cc soak -I. soak.c "$BIN/soak_k.S"
cc bench bench.c bench_k.S
cc syncfault syncfault.c syncfault_k.S
win() { out=$1; shift; "$MINGW" -O1 -mno-avx -Wall -DWIN -o "$BIN/$out.exe" "$@"; }
win susp susp.c sigstorm_k.S
win susp_split -DLEAFSPLIT susp.c sigstorm_k.S
win susp_soak -DSOAK susp.c sigstorm_k.S "$BIN/soak_k.S"
"${MINGW32:-i686-w64-mingw32-gcc}" -O1 -mno-avx -Wall -o "$BIN/susp32.exe" susp.c susp32_k.S
cc latency latency.c bench_k.S
