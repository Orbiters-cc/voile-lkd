#!/bin/sh
# Build the upscale bench (native; it draws into its own textures, shows nothing and reads no screen).
set -eu
W=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$W/bin"
clang -arch arm64 -fobjc-arc -O2 -Wall -Wno-deprecated-declarations -o "$W/bin/upscale_bench" "$W/upscale_bench.m" -framework Cocoa -framework Metal -framework QuartzCore
