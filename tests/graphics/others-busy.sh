#!/bin/sh
# What else uses this Mac: the CPU of every process but the kernel and the window server over two seconds, in percent of
# one core, then the three largest. A measurement beside more than a core of it is not one.
top -l 2 -s 2 -n 25 -o cpu -stats pid,command,cpu 2>/dev/null | awk '
  /^PID/ {n++; next}
  n == 2 && $1 ~ /^[0-9]+$/ && $2 !~ /^(kernel_task|WindowServer|top|wsd|virgl_|fexdarwin|pass_costs|coreaudiod)/ {
    c = $NF; sum += c; if (k < 3) {k++; names = names " " $2 "=" c}
  }
  END {printf "others %d:%s\n", sum, names}'
