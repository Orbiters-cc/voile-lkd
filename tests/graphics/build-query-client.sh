#!/bin/sh
# Build the query client twice: Windows x86-64 (mingw-w64, statically linked), and, with DXMT=<a checkout of Orbiters-cc/dxmt> given, a
# Mac program on libdxmt-native itself.
set -eu
W=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$W/bin"
x86_64-w64-mingw32-g++ -std=c++20 -O2 -Wall -static -o "$W/bin/query_client.exe" "$W/query_client.cpp" -ld3d11 -ldxgi -ldxguid -luuid
if [ -n "${DXMT:-}" ]; then
  clang++ -arch arm64 -std=c++20 -O2 -Wno-everything -I"$W" -I"$DXMT/include/native/windows" -I"$DXMT/include/native/directx" \
    "$W/query_client.cpp" -o "$W/bin/query_client"
  codesign -s - -f "$W/bin/query_client" 2>/dev/null
fi
shasum -a 256 "$W/query_client.cpp" "$W"/bin/query_client*
