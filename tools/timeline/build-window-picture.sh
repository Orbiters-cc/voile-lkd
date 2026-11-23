#!/bin/sh
set -eu
W=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$W/bin"
clang -arch arm64 -fobjc-arc -O2 -Wall -Werror -o "$W/bin/window_picture" "$W/window_picture.m" -framework AppKit
codesign -s - -f "$W/bin/window_picture" 2>/dev/null
shasum -a 256 "$W/bin/window_picture"
