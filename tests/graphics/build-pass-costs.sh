#!/bin/sh
# Build the pass-cost client (Windows x86-64, needs mingw-w64; statically linked, so it needs nothing but Wine).
set -eu
W=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$W/bin"
x86_64-w64-mingw32-g++ -O2 -Wall -static -o "$W/bin/pass_costs.exe" "$W/pass_costs.cpp" -ld3d11 -ldxgi -ldxguid -luuid -lgdi32 -luser32
shasum -a 256 "$W/pass_costs.cpp" "$W/bin/pass_costs.exe"
