#!/usr/bin/env python3
"""The pictures of two starts (real_session.py: picture-1.png to -3.png, taken at the same moment after the arrival) against each other.

Usage: compare_pictures.py <start folder> <start folder> [--out <folder>]

What moves by itself is told from what another switch changes by measuring both alike: the three pictures of one start against each
other (half a second apart), then every picture of one against every one of the other. A difference that is the switch's is larger than
both starts' own. Prints a table, writes heat.png (the differing pixels of the two nearest pictures, red) and side.txt with their paths, for
the eye. macOS's own programs and window_picture (build-window-picture.sh) alone."""
import argparse, glob, itertools, json, os, subprocess, sys

TOOL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin", "window_picture")


def diff(a, b, heat=None):
    r = subprocess.run([TOOL, "diff", a, b] + ([heat] if heat else []), capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except ValueError:
        return dict(same_size=False)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--out")
    args = p.parse_args()
    shots = [sorted(glob.glob(f"{folder}/picture-*.png")) for folder in (args.a, args.b)]
    if not all(shots):
        print(f"no pictures in {args.a if not shots[0] else args.b}", file=sys.stderr)
        return 1
    rows = [("the first start by itself", list(itertools.combinations(shots[0], 2))), ("the second by itself", list(itertools.combinations(shots[1], 2))),
            ("the two against each other", list(itertools.product(*shots)))]
    told, sized = {}, True
    print(f"{'':28s} {'pairs':>5s} {'mean diff':>10s} {'PSNR dB':>8s} {'SSIM':>8s} {'>8':>8s} {'>32':>8s}  black")
    for name, pairs in rows:
        results = [(diff(a, b), a, b) for a, b in pairs]
        if not all(r["same_size"] for r, _, _ in results):
            print(f"{name:28s} pictures of different sizes: {[(r.get('a'), r.get('b')) for r, _, _ in results if not r['same_size']][:1]}")
            sized = False
            continue
        mean = lambda k: sum(r[k] for r, _, _ in results) / len(results)
        if not results:
            continue
        told[name] = {k: mean(k) for k in ("mean_difference", "psnr_db", "ssim", "pixels_over_8", "pixels_over_32", "black_a", "black_b")}
        print(f"{name:28s} {len(results):5d} {mean('mean_difference'):10.3f} {mean('psnr_db'):8.2f} {mean('ssim'):8.4f} {100 * mean('pixels_over_8'):7.2f}% "
              f"{100 * mean('pixels_over_32'):7.2f}%  {100 * mean('black_a'):.2f}% {100 * mean('black_b'):.2f}%")
        if name.startswith("the two"):
            nearest = max(results, key=lambda r: r[0]["ssim"])
            out = args.out or args.b
            diff(nearest[1], nearest[2], os.path.join(out, "heat.png"))
            with open(os.path.join(out, "side.txt"), "w") as f:
                f.write(f"{nearest[1]}\n{nearest[2]}\n")
            print(f"\nthe nearest two: {nearest[1]} {nearest[2]}\nwhere they differ: {os.path.join(out, 'heat.png')}; share of pixels over 8 by cell (16 x 9):")
            for line in nearest[0]["over_8_by_cell_16x9"]:
                print("  " + " ".join(f"{v:4.2f}" for v in line))
    if args.out:
        with open(os.path.join(args.out, "pictures.json"), "w") as f:
            json.dump(told, f, indent=1)
    return 0 if sized else 1


sys.exit(main())
