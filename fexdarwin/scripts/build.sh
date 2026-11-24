#!/bin/bash
# Build FEXCore (stage 1) and the fexdarwin host (stage 2). Usage: scripts/build.sh [clean]
# Both stages build in Release without FEX's assertions; ASSERTIONS=ON turns them on in both, as the two must agree
# (several FEXCore structs change layout with them).
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="/opt/homebrew/bin:$PATH" # cmake and ninja
FEX_SRC="${FEX_SRC:-$HERE/../fex}"
FEX_COMMIT="$(git -C "$FEX_SRC" rev-parse HEAD 2>/dev/null || echo unknown)"
B1="$HERE/build/fexcore"
B2="$HERE/build/host"
ASSERTIONS="${ASSERTIONS:-OFF}"
if [ "${1:-}" = clean ]; then rm -rf "$B1" "$B2" "$HERE/build/fex"; fi
# Our changes to FEX (fex-patches/README.md) go into a copy: the submodule stays the commit of Zagrios/FEX it names. The copy is
# made again only when that commit or a patch changes. Without the tests' programs, which no build needs.
PATCHES=("$HERE"/fex-patches/*.patch)
if [ -e "${PATCHES[0]}" ]; then
  COPY="$HERE/build/fex"
  STAMP="$FEX_COMMIT $(cat "${PATCHES[@]}" | shasum -a 256 | cut -d' ' -f1)"
  if [ "$(cat "$COPY/.patched" 2>/dev/null)" != "$STAMP" ]; then
    mkdir -p "$COPY"
    rm -f "$COPY/.patched"
    rsync -a --delete --exclude .git --exclude '/External/fex-*-bins' "$FEX_SRC/" "$COPY/"
    for P in "${PATCHES[@]}"; do (cd "$COPY" && GIT_CEILING_DIRECTORIES="$HERE" git apply --whitespace=nowarn "$P") || { echo "$P does not apply to $FEX_SRC ($FEX_COMMIT)" >&2; exit 1; }; done
    echo "$STAMP" > "$COPY/.patched"
  fi
  FEX_SRC="$COPY"
fi
# A build folder configured for another FEX (a script that configures FEXCore itself, before the patches): again for this one, with
# the same prefixes ignored.
IGNORE=""
if [ -f "$B1/CMakeCache.txt" ] && [ "$(sed -n 's/^CMAKE_HOME_DIRECTORY:INTERNAL=//p' "$B1/CMakeCache.txt")" != "$(cd "$FEX_SRC" && pwd -P)" ] &&
   [ "$(sed -n 's/^CMAKE_HOME_DIRECTORY:INTERNAL=//p' "$B1/CMakeCache.txt")" != "$FEX_SRC" ]; then
  IGNORE="$(sed -n 's/^CMAKE_IGNORE_PREFIX_PATH:[^=]*=//p' "$B1/CMakeCache.txt")"
  rm -rf "$B1"
fi
if [ ! -f "$B1/build.ninja" ] || ! grep -qx "ENABLE_ASSERTIONS:BOOL=$ASSERTIONS" "$B1/CMakeCache.txt"; then
  cmake -G Ninja -S "$FEX_SRC" -B "$B1" ${IGNORE:+-DCMAKE_IGNORE_PREFIX_PATH="$IGNORE"} \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=/usr/bin/clang -DCMAKE_CXX_COMPILER=/usr/bin/clang++ \
    -DENABLE_LTO=OFF -DENABLE_FEX_ALLOCATOR=OFF -DENABLE_JEMALLOC_GLIBC_ALLOC=OFF \
    -DBUILD_TESTING=OFF -DBUILD_THUNKS=OFF -DBUILD_FEXCONFIG=OFF -DENABLE_CCACHE=OFF \
    -DENABLE_GDB_SYMBOLS=OFF -DENABLE_ASSERTIONS="$ASSERTIONS" -DENABLE_OFFLINE_TELEMETRY=OFF \
    -DCMAKE_OSX_DEPLOYMENT_TARGET=15.0 \
    -DOVERRIDE_VERSION="FEX-${FEX_COMMIT:0:9}-darwin" -DOVERRIDE_HASH="$FEX_COMMIT"
fi
ninja -j "${JOBS:-4}" -C "$B1" FEXCore FEXCore_Base JemallocDummy cephes_128bit softfloat_3e fmt xxhash
cmake -G Ninja -S "$HERE" -B "$B2" -DCMAKE_BUILD_TYPE=Release -DFEX_ASSERTIONS="$ASSERTIONS" -DFEX_SOURCE_DIR="$FEX_SRC" -DFEX_BUILD_DIR="$B1" -DLKD_DIR="$HERE/../lkd" -DCMAKE_C_COMPILER=/usr/bin/clang -DCMAKE_CXX_COMPILER=/usr/bin/clang++
ninja -j "${JOBS:-4}" -C "$B2"
ls -la "$B2/fexdarwin-run"
