#!/usr/bin/env python3
"""What a whole series of three starts says (README.md, "The A/B/A of queries=once"): A, B, A again, by the criteria that were written down
before any of them was made. Nothing is averaged over starts or windows, and W1 decides nothing.

Usage: score_series.py <folder of the series> [--json out.json]

Prints each window's numbers, what made it inconclusive, and one word: KEEP (provisionally), REJECT, or INCONCLUSIVE. Pictures and what was seen
by eye are not in it: compare_pictures.py, and the person at the Mac; a defect of either is a rejection whatever this says."""
import argparse, json, os, sys

STEADY = (2, 3)        # the windows that decide, each with its like
BETTER = 0.02          # of the shown rate, at the least, above both As
SHORTER_MS = 0.5       # of the mean production interval, below both As
WORSE = 0.03           # of the shown rate below both As in both windows: a rejection
REFRESH_MS = 16.7      # of a latency tail above both As beyond the As' own difference: a rejection
DRAWS, ENDS = 0.05, 0.10  # how far apart the work of a frame may be (draws; Ends of event and disjoint queries) for a window to be compared
PRESSURE = 2


def numbers(w):
    c = (w.get("cadence") or [{}])[0]
    q = w.get("queries") or {}
    signals = q.get("signals") or 0
    ended = q.get("ended") or {}
    return dict(shown=w.get("shown_per_s"), interval=((w.get("production") or {}).get("interval_ms") or {}).get("mean"),
                draws=(w.get("work") or {}).get("draws"), buffers=(w.get("work") or {}).get("command_buffers"),
                ends=(ended.get("event", 0) + ended.get("disjoint", 0)) / signals if signals else None,
                redundant=(w.get("queries_of_every_queue") or q).get("handed_over_and_committed"),
                shown_p95=(c.get("shown_interval_ms") or {}).get("p95"), shown_p99=(c.get("shown_interval_ms") or {}).get("p99"),
                client_p95=(c.get("client_to_shown_ms") or {}).get("p95"), tick_p50=(c.get("tick_to_shown_ms") or {}).get("p50"), largest_gap=c.get("largest_gap_ms"), holds=c.get("holds_of_3_refreshes_or_more"),
                pressure=max((p for p in (w.get("conditions") or {}).get("pressure", []) if p is not None), default=None),
                warmup=(w.get("from_s") or 0) - (w.get("arrived_after_s") or 0), list_ends=(q.get("one_by_one") or {}).get("in_lists"))


def apart(values):
    values = [v for v in values if v is not None]
    return (max(values) - min(values)) / max(values) if len(values) > 1 and max(values) else 0.0


def score(results):
    """[A, B, A] results (result.json) -> dict(verdict, why, windows, holds_40)."""
    inconclusive, reject, notes, windows = [], [], [], {}
    better = []
    if len(results) != 3 or not all(r.get("go_on") for r in results):
        return dict(verdict="INCONCLUSIVE", why=["the series is not three starts that went as planned"], windows={}, notes=[], holds_40=None)
    for n in (1,) + STEADY:
        of = [next((numbers(w) for w in r["windows"] if w["window"] == n), {}) for r in results]
        windows[n] = of
        if n not in STEADY:
            continue
        a1, b, a2 = of
        if any(x.get(k) is None for x in of for k in ("shown", "interval", "draws", "ends", "redundant", "pressure", "shown_p95", "shown_p99", "client_p95")):
            inconclusive.append(f"W{n}: a number of it is not known")
            continue
        if apart([x["draws"] for x in of]) > DRAWS:
            inconclusive.append(f"W{n}: another workload ({', '.join(format(x['draws'], '.0f') for x in of)} draws a frame)")
        if apart([x["ends"] for x in of]) > ENDS:
            inconclusive.append(f"W{n}: another workload ({', '.join(format(x['ends'], '.2f') for x in of)} Ends of queries a frame)")
        if len({x["pressure"] >= PRESSURE for x in of}) > 1:
            inconclusive.append(f"W{n}: thermal pressure {', '.join(str(x['pressure']) for x in of)}")
        if not (a1["redundant"] and a2["redundant"]):
            inconclusive.append(f"W{n}: an A without redundant commits: there was nothing for the switch to take away")
        if b["redundant"]:
            reject.append(f"W{n}: B committed {b['redundant']} times for a marker already handed over")
        drift = abs(a1["shown"] - a2["shown"])
        up = b["shown"] - max(a1["shown"], a2["shown"])
        shorter = min(a1["interval"], a2["interval"]) - b["interval"]
        better.append(up >= BETTER * max(a1["shown"], a2["shown"]) and up > drift and shorter >= SHORTER_MS)
        notes.append(f"W{n}: B {b['shown']:.2f} shown frames a second, the As {a1['shown']:.2f} and {a2['shown']:.2f} (drift {drift:.2f}): {up:+.2f} on the better A; the mean "
                     f"production interval {shorter:+.2f} ms shorter than the shorter A's")
        for k, name in (("shown_p95", "shown p95"), ("shown_p99", "shown p99"), ("client_p95", "client stamp to shown p95")):
            over = b[k] - max(a1[k], a2[k]) - abs(a1[k] - a2[k])
            if k == "client_p95" and over > REFRESH_MS and abs((b["tick_p50"] or 0) - max(a1["tick_p50"] or 0, a2["tick_p50"] or 0)) > REFRESH_MS / 2:
                # the window server's own: from its tick to the screen one drawable more for a whole start, or not, by the start
                # (2026-11-24: 32.8 or 49.5 ms, with the switch and without). Nothing of DXMT's; nothing that can be compared either.
                inconclusive.append(f"W{n}: {name} {b[k]:.1f} ms, the As {a1[k]:.1f} and {a2[k]:.1f}, but the window server's own part of it (tick to shown) is "
                                    f"{b['tick_p50']:.1f} ms, the As' {a1['tick_p50']:.1f} and {a2['tick_p50']:.1f}")
            elif over > REFRESH_MS:
                reject.append(f"W{n}: {name} {b[k]:.1f} ms, the As {a1[k]:.1f} and {a2[k]:.1f}")
            elif b[k] > max(a1[k], a2[k]):
                notes.append(f"W{n}: {name} is worse: {b[k]:.1f} ms, the As {a1[k]:.1f} and {a2[k]:.1f}")
        if any(x["list_ends"] for x in of):
            notes.append(f"W{n}: queries were ended in command lists ({', '.join(str(x['list_ends']) for x in of)} of those recorded), which B also signals otherwise: what is "
                         "gained or lost is of the switch as a whole, not of the rescue alone")
    of = [windows[n] for n in STEADY]
    if all(all(x.get("shown") is not None for x in w) and w[1]["shown"] < (1 - WORSE) * min(w[0]["shown"], w[2]["shown"]) for w in of):
        reject.append("B shows more than 3 % fewer frames than both As in both windows")
    warm = [x["warmup"] for x in of[0] if x.get("warmup")]
    if warm and max(warm) - min(warm) > 30:
        notes.append("W2 began at different times after the arrival: " + ", ".join(f"{x:.0f} s" for x in warm))
    holds = all((w[1].get("shown") or 0) >= 40 for w in of)
    if len(better) == 2 and better[0] != better[1]:
        inconclusive.append("W2 and W3 disagree")
    if reject:
        return dict(verdict="REJECT", why=reject, windows=windows, notes=notes, holds_40=holds)
    if inconclusive:
        return dict(verdict="INCONCLUSIVE", why=inconclusive, windows=windows, notes=notes, holds_40=holds)
    if better == [True, True]:
        return dict(verdict="KEEP", why=["B beats both As in W2 and in W3 (provisionally: independent starts in another order confirm it)"], windows=windows, notes=notes, holds_40=holds)
    return dict(verdict="INCONCLUSIVE", why=["under the bands that were written down"], windows=windows, notes=notes, holds_40=holds)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("folder")
    p.add_argument("--json")
    a = p.parse_args()
    with open(os.path.join(a.folder, "series.json")) as f:
        starts = json.load(f)["starts"]
    results = []
    for s in starts:
        try:
            with open(s["result"]) as f:
                results.append(json.load(f) | dict(go_on=s["go_on"]))
        except (OSError, ValueError, KeyError):
            results.append(dict(go_on=False, windows=[]))
    told = score(results)
    for n, of in told["windows"].items():
        for name, x in zip(("A", "B", "A'"), of):
            print(f"W{n} {name:2s} " + "  ".join(f"{k} {format(v, '.2f') if isinstance(v, float) else v}" for k, v in x.items()))
    for line in told["notes"]:
        print(f"  {line}")
    print(f"{told['verdict']}: " + "; ".join(told["why"]))
    if told["holds_40"] is not None:
        print("B " + ("sustained" if told["holds_40"] else "did not sustain") + " 40 distinct shown frames a second in both W2 and W3")
    if a.json:
        with open(a.json, "w") as f:
            json.dump(told, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
