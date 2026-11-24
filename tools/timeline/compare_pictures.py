#!/usr/bin/env python3
"""The pictures of two starts (real_session.py: picture-1.png to -3.png, taken at the same moment after the arrival) against each other.

Usage: compare_pictures.py <start folder> <start folder> [--out <folder>]
       compare_pictures.py --series <folder of the series>    both comparisons with B of a whole series (starts 1 and 2, 2 and 3), kept in its
                                                              folder for score_series.py: pictures-1-2.json, pictures-2-3.json

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


def flagged(told):
    """What README.md says flags the second start ("Pictures"): against the worse of the two by itself."""
    own, both = [told.get(k) for k in ("the first start by itself", "the second by itself")], told.get("the two against each other")
    if not both or not all(own):
        return ["pictures that cannot be compared"]
    out = []
    if both["ssim"] < min(x["ssim"] for x in own) - 0.01:
        out.append(f"mean SSIM {both['ssim']:.4f}, within the starts {min(x['ssim'] for x in own):.4f} at the worst")
    if both["pixels_over_32"] > max(x["pixels_over_32"] for x in own) + 0.01:
        out.append(f"{100 * both['pixels_over_32']:.2f} % of the pixels more than 32 levels off, within the starts {100 * max(x['pixels_over_32'] for x in own):.2f} % at the most")
    return out


def whole_series(folder):
    """Both comparisons with B; 1 when one could not be made."""
    with open(os.path.join(folder, "series.json")) as f:
        starts = [os.path.dirname(s["result"]) for s in json.load(f)["starts"]]
    if len(starts) != 3:
        print(f"{len(starts)} starts: a whole series has three", file=sys.stderr)
        return 1
    status = 0
    for a, b in ((1, 2), (2, 3)):
        out = os.path.join(folder, f"pictures-{a}-{b}")
        os.makedirs(out, mode=0o700, exist_ok=True)
        print(f"\n== starts {a} and {b}")
        told, pairs, sized = compare(starts[a - 1], starts[b - 1], out)
        with open(os.open(f"{out}.json", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
            json.dump(dict(starts=[starts[a - 1], starts[b - 1]], pairs=pairs, flagged=flagged(told) if sized else ["pictures of different sizes, or none"], numbers=told), f, indent=1)
        for line in flagged(told) if sized else ["not compared"]:
            print(f"FLAGGED: {line}")
        status = status if sized else 1
    return status


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("a", nargs="?")
    p.add_argument("b", nargs="?")
    p.add_argument("--out")
    p.add_argument("--series")
    args = p.parse_args()
    if bool(args.series) == bool(args.a and args.b) or (args.series and (args.a or args.out)):
        p.error("two start folders, or --series")
    if args.series:
        return whole_series(args.series)
    told, _, sized = compare(args.a, args.b, args.out or args.b)
    if args.out:
        with open(os.path.join(args.out, "pictures.json"), "w") as f:
            json.dump(told, f, indent=1)
    return 0 if sized else 1


def compare(one, other, out):
    """(the numbers, how many pairs of the two were compared, whether all could be)"""
    shots = [sorted(glob.glob(f"{folder}/picture-*.png")) for folder in (one, other)]
    if not all(shots):
        print(f"no pictures in {one if not shots[0] else other}", file=sys.stderr)
        return {}, 0, False
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
            diff(nearest[1], nearest[2], os.path.join(out, "heat.png"))
            with open(os.path.join(out, "side.txt"), "w") as f:
                f.write(f"{nearest[1]}\n{nearest[2]}\n")
            print(f"\nthe nearest two: {nearest[1]} {nearest[2]}\nwhere they differ: {os.path.join(out, 'heat.png')}; share of pixels over 8 by cell (16 x 9):")
            for line in nearest[0]["over_8_by_cell_16x9"]:
                print("  " + " ".join(f"{v:4.2f}" for v in line))
    return told, len(rows[-1][1]), sized


if __name__ == "__main__":
    sys.exit(main())
