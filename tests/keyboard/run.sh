#!/bin/sh
# Builds and runs the keyboard layout tests: keymap-test checks the Windows layout wineobelisk.drv makes of the Mac's
# installed input sources (US, French, French - PC, German, Dvorak, ABC - AZERTY, Russian); keymap-dump prints one.
#   WINE=<voile-wine checkout> tests/keyboard/run.sh [keymap-dump arguments]
# The driver's layout code (dlls/wineobelisk.drv/keymap.c) is built natively: it needs nothing of Wine.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
: "${WINE:?set WINE to a voile-wine checkout}"
DRIVER="$WINE/dlls/wineobelisk.drv"
[ -f "$DRIVER/keymap.c" ] || { echo "no keymap.c in $DRIVER" >&2; exit 1; }
cmp -s "$HERE/../../wsd/wsd_protocol.h" "$DRIVER/wsd_protocol.h" ||
    { echo "wsd_protocol.h differs between wsd and wineobelisk.drv" >&2; exit 1; }
OUT=${OUT:-$HERE/bin}
mkdir -p "$OUT"
for tool in keymap-test keymap-dump; do
    clang -arch arm64 -O1 -Wall -Wextra -Wno-missing-field-initializers -Wno-deprecated-declarations \
        -DOBELISK_KEYMAP_TEST -I"$DRIVER" -I"$HERE/../../wsd" -o "$OUT/$tool" "$HERE/$tool.c" "$DRIVER/keymap.c" \
        -framework Carbon
done
"$OUT/keymap-test"
[ $# -eq 0 ] || "$OUT/keymap-dump" "$@"
