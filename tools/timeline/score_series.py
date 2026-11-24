#!/usr/bin/env python3
"""What a whole series of three starts says (README.md, "The A/B/A of queries=once"): A, B, A again, by the criteria that were written down
before any of them was made. Nothing is averaged over starts or windows, and W1 decides nothing.

Usage: score_series.py <folder of the series> [--nothing-wrong-seen] [--json out.json]

Prints each window's numbers, what made it inconclusive, and one word: KEEP (provisionally), REJECT, INCONCLUSIVE, or INVALID (the files of the
series contradict each other, or do not show what its journal says). Pictures and what was seen by eye are not in the numbers: until both
comparisons with B are recorded (compare_pictures.py --series) and the person at the Mac has said of all three starts that nothing was wrong
(--nothing-wrong-seen: here of the third, and of the two before it; it is kept in the series' folder), what is said is of timing only. A defect
of either is a rejection whatever this says."""
import argparse, datetime, importlib.util, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("real_session", os.path.join(HERE, "real_session.py"))
rs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rs)

STEADY = (2, 3)        # the windows that decide, each with its like
BETTER = 0.02          # of the shown rate, at the least, above both As
SHORTER_MS = 0.5       # of the mean production interval, below both As
WORSE = 0.03           # of the shown rate below both As in both windows: a rejection
REFRESH_MS = 16.7      # of a latency tail above both As beyond the As' own difference: a rejection
DRAWS, ENDS = 0.05, 0.10  # how far apart the work of a frame may be (draws; Ends of event and disjoint queries) for a window to be compared
PRESSURE = 2
SWITCHES = ({}, {"OBELISK_DXMT_QUERY_RESCUE": "once"}, {})  # A, B, A
NEEDED = ("shown", "interval", "draws", "ends", "redundant", "pressure", "shown_p95", "shown_p99", "client_p95")


def said(value, form=".1f"):
    return "not known" if value is None else format(value, form)


def numbers(w):
    c = (w.get("cadence") or [{}])[0]
    q = w.get("queries") or {}
    signals = q.get("signals") or 0
    ended = [(q.get("ended") or {}).get(k, 0) for k in ("event", "disjoint")]
    return dict(shown=w.get("shown_per_s"), interval=((w.get("production") or {}).get("interval_ms") or {}).get("mean"),
                draws=(w.get("work") or {}).get("draws"), buffers=(w.get("work") or {}).get("command_buffers"),
                ends=sum(ended) / signals if signals and None not in ended else None,
                redundant=(w.get("queries_of_every_queue") or q).get("handed_over_and_committed"),
                shown_p95=(c.get("shown_interval_ms") or {}).get("p95"), shown_p99=(c.get("shown_interval_ms") or {}).get("p99"),
                client_p95=(c.get("client_to_shown_ms") or {}).get("p95"), tick_p50=(c.get("tick_to_shown_ms") or {}).get("p50"), largest_gap=c.get("largest_gap_ms"), holds=c.get("holds_of_3_refreshes_or_more"),
                pressure=max((p for p in (w.get("conditions") or {}).get("pressure") or [] if p is not None), default=None),
                warmup=w["from_s"] - w["arrived_after_s"] if None not in (w.get("from_s"), w.get("arrived_after_s")) else None, list_ends=(q.get("one_by_one") or {}).get("in_lists"))


def apart(values):
    values = [v for v in values if v is not None]
    return (max(values) - min(values)) / max(values) if len(values) > 1 and max(values) else 0.0


def failures(r):
    """What of a result's windows that are recorded whole is wrong whatever the work was: with the switch, of every queue."""
    out = []
    for w in r.get("windows") or []:
        q = w.get("queries_of_every_queue") or {}
        if w.get("trace_not_complete") != [] or q.get("once") != [True]:
            continue
        for value, what in ((q.get("handed_over_and_committed"), "commits for a marker already handed over"), (q.get("left_not_handed_over"), "markers left not handed over"),
                            ((q.get("debts") or {}).get("cancelled"), "owed markers that went with their context"),
                            ((q.get("one_by_one") or {}).get("not_seen_though_looked_at_of_more_than_a_second"), "Ends that were looked at and never found")):
            if value:
                out.append(f"W{w.get('window')}: B had {value} {what}")
    return out


def score(results):
    """[A, B, A] results (result.json) -> dict(verdict, why, windows, holds_40). What can be compared first: where it cannot, nothing is said of
    performance, for B or against it. What B got wrong (failures) is no matter of performance: it is a rejection in any case."""
    inconclusive, slower, notes, windows = [], [], [], {}
    better, wrong = [], failures(results[1]) if len(results) > 1 else []
    if wrong:
        return dict(verdict="REJECT", why=wrong, windows={}, notes=[], holds_40=None)
    if len(results) != 3 or not all(r.get("go_on") for r in results):
        return dict(verdict="INCONCLUSIVE", why=["the series is not three starts that went as planned"], windows={}, notes=[], holds_40=None)
    for n in (1,) + STEADY:
        of = [next((numbers(w) for w in r.get("windows") or [] if w.get("window") == n), {}) for r in results]
        windows[n] = of
        if n not in STEADY:
            continue
        a1, b, a2 = of
        missing = sorted({k for x in of for k in NEEDED if x.get(k) is None})
        if missing:
            inconclusive.append(f"W{n}: a number of it is not known ({', '.join(missing)})")
            continue
        if apart([x["draws"] for x in of]) > DRAWS:
            inconclusive.append(f"W{n}: another workload ({', '.join(format(x['draws'], '.0f') for x in of)} draws a frame)")
        if apart([x["ends"] for x in of]) > ENDS:
            inconclusive.append(f"W{n}: another workload ({', '.join(format(x['ends'], '.2f') for x in of)} Ends of queries a frame)")
        if len({x["pressure"] >= PRESSURE for x in of}) > 1:
            inconclusive.append(f"W{n}: thermal pressure {', '.join(str(x['pressure']) for x in of)}")
        if not (a1["redundant"] and a2["redundant"]):
            inconclusive.append(f"W{n}: an A without redundant commits: there was nothing for the switch to take away")
        drift = abs(a1["shown"] - a2["shown"])
        up = b["shown"] - max(a1["shown"], a2["shown"])
        shorter = min(a1["interval"], a2["interval"]) - b["interval"]
        better.append(up >= BETTER * max(a1["shown"], a2["shown"]) and up > drift and shorter >= SHORTER_MS)
        notes.append(f"W{n}: B {b['shown']:.2f} shown frames a second, the As {a1['shown']:.2f} and {a2['shown']:.2f} (drift {drift:.2f}): {up:+.2f} on the better A; the mean "
                     f"production interval {shorter:+.2f} ms shorter than the shorter A's")
        for k, name in (("shown_p95", "shown p95"), ("shown_p99", "shown p99"), ("client_p95", "client stamp to shown p95")):
            over = b[k] - max(a1[k], a2[k]) - abs(a1[k] - a2[k])
            ticks = [x.get("tick_p50") for x in of]
            if k == "client_p95" and over > REFRESH_MS and (None in ticks or abs(ticks[1] - max(ticks[0], ticks[2])) > REFRESH_MS / 2):
                # the window server's own: from its tick to the screen one drawable more for a whole start, or not, by the start
                # (2026-11-24: 32.8 or 49.5 ms, with the switch and without). Nothing of DXMT's; nothing that can be compared either.
                inconclusive.append(f"W{n}: {name} {b[k]:.1f} ms, the As {a1[k]:.1f} and {a2[k]:.1f}, but the window server's own part of it (tick to shown) is "
                                    f"{said(ticks[1])} ms, the As' {said(ticks[0])} and {said(ticks[2])}")
            elif over > REFRESH_MS:
                slower.append(f"W{n}: {name} {b[k]:.1f} ms, the As {a1[k]:.1f} and {a2[k]:.1f}")
            elif b[k] > max(a1[k], a2[k]):
                notes.append(f"W{n}: {name} is worse: {b[k]:.1f} ms, the As {a1[k]:.1f} and {a2[k]:.1f}")
        if any(x["list_ends"] for x in of):
            notes.append(f"W{n}: queries were ended in command lists ({', '.join(str(x['list_ends']) for x in of)} of those recorded), which B also signals otherwise: what is "
                         "gained or lost is of the switch as a whole, not of the rescue alone")
    of = [windows[n] for n in STEADY]
    if all(all(x.get("shown") is not None for x in w) and w[1]["shown"] < (1 - WORSE) * min(w[0]["shown"], w[2]["shown"]) for w in of):
        slower.append("B shows more than 3 % fewer frames than both As in both windows")
    warm = [x["warmup"] for x in of[0] if x.get("warmup")]
    if warm and max(warm) - min(warm) > 30:
        notes.append("W2 began at different times after the arrival: " + ", ".join(f"{x:.0f} s" for x in warm))
    holds = all((w[1].get("shown") or 0) >= 40 for w in of)
    if not slower and len(better) == 2 and better[0] != better[1]:
        inconclusive.append("W2 and W3 disagree")
    if inconclusive:
        verdict, why = "INCONCLUSIVE", inconclusive
        notes += [f"of what cannot be compared, and so no verdict: {x}" for x in slower]
    elif slower:
        verdict, why = "REJECT", slower
    elif better == [True, True]:
        verdict, why = "KEEP", ["B beats both As in W2 and in W3 (provisionally: independent starts in another order confirm it)"]
    else:
        verdict, why = "INCONCLUSIVE", ["under the bands that were written down"]
    return dict(verdict=verdict, why=why, windows=windows, notes=notes, holds_40=holds)


def read(path):
    with open(path) as f:
        return json.load(f)


def verified(folder):
    """(the three results as their own files are, what in the series' files contradicts itself or is not shown by them). Of a start that its journal
    and its result both say went wrong nothing is contradicted: it is not a whole series, and that is all."""
    wrong, results = [], []
    try:
        starts = read(os.path.join(folder, "series.json"))["starts"]
        if not isinstance(starts, list) or not all(isinstance(s, dict) for s in starts):
            raise ValueError("no starts in it")
    except (OSError, ValueError, KeyError, TypeError) as e:
        return [], [f"series.json cannot be read ({type(e).__name__})"]
    if len(starts) > len(SWITCHES):
        wrong.append(f"{len(starts)} starts: a series has {len(SWITCHES)}")
    paths = [s.get("result") for s in starts if s.get("result")]
    if len(set(paths)) != len(paths):
        wrong.append("two starts have one result")
    for n, (s, switches) in enumerate(zip(starts, SWITCHES), 1):
        say = lambda text, n=n: wrong.append(f"start {n}: {text}")
        if s.get("switches") != switches:
            say(f"its journal says the switches {s.get('switches')}, not {switches}")
        if not s.get("result"):
            if s.get("go_on"):
                say("its journal says it went as planned, and has no result")
            results.append(dict(go_on=False, windows=[]))
            continue
        try:
            r = read(s["result"])
            if not isinstance(r, dict) or not isinstance(r.get("windows"), list) or not all(isinstance(w, dict) for w in r["windows"]):
                raise ValueError("no result")
        except (OSError, ValueError, TypeError) as e:
            say(f"its result cannot be read ({type(e).__name__})")
            results.append(dict(go_on=False, windows=[]))
            continue
        results.append(r)
        if bool(s.get("go_on")) != (r.get("go_on") is True):
            say(f"its journal says go_on {s.get('go_on')}, its result {r.get('go_on')}")
        if (r.get("go_on") is True) != (r.get("why_not") == []):
            say(f"its result says go_on {r.get('go_on')}, and why not: {'; '.join(r.get('why_not') or ['not told'])}")
        if s.get("go_on") and s.get("result_sha256") != rs.sha(s["result"]):
            say("its result is not the one its journal has the digest of")
        if r.get("switches") != switches:
            say(f"its result says the switches {r.get('switches')}, not {switches}")
        fixed = s.get("fixed") or {}
        if fixed != (starts[0].get("fixed") or {}) or (fixed.get("plan") and fixed["plan"] != [r.get("percent")]):
            say("what is the same for the starts of a series is not")
        if not (s.get("go_on") or r.get("go_on")):
            continue
        back = r.get("restored")
        if not isinstance(back, dict) or back.get("verified") is not True or not back.get("files"):
            say("that the released generation was put back and proven is not in its result")
        try:
            against = rs.judge(r, fixed.get("windows") or 3, bool(switches), results[0] if n > 1 else None)
        except Exception as e:  # noqa: BLE001 - a result that cannot be judged is none
            against = [f"it cannot be judged ({type(e).__name__})"]
        if against:
            say("it says that it went as planned, and what is in it does not: " + "; ".join(against[:4]))
    return results, wrong


def not_recorded(folder):
    """What besides the timing a verdict needs and the series' folder does not have: both comparisons of B's pictures, and what was seen by eye."""
    out = []
    try:
        starts = read(os.path.join(folder, "series.json"))["starts"]
    except (OSError, ValueError, KeyError):
        starts = []
    for a, b in ((1, 2), (2, 3)):
        name = f"pictures-{a}-{b}.json"
        try:
            told = read(os.path.join(folder, name))
            of = [os.path.dirname(os.path.realpath(starts[i - 1]["result"])) for i in (a, b)]
            if [os.path.realpath(x) for x in told["starts"]] != of or told.get("pairs") != 9 or told.get("flagged") is None:
                raise ValueError
            if told["flagged"]:
                out.append(f"starts {a} and {b}: their pictures were flagged ({'; '.join(told['flagged'])}): looked at by eye, and judged there")
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            out.append(f"the pictures of starts {a} and {b} were not compared (compare_pictures.py --series)")
    seen = [bool(s.get("nothing_wrong_seen_before_it")) for s in starts[1:3]]
    try:
        third = read(os.path.join(folder, "observed.json")).get("nothing_wrong_seen") is True
    except (OSError, ValueError, AttributeError):
        third = False
    if seen != [True, True] or not third:
        out.append("that nothing wrong was seen in the three starts was not said (--nothing-wrong-seen, by the person at the Mac)")
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("folder")
    p.add_argument("--json")
    p.add_argument("--nothing-wrong-seen", action="store_true", help="no warning, crash, hang, black texture or lost picture was seen in any of the three starts")
    a = p.parse_args()
    results, wrong = verified(a.folder)
    if a.nothing_wrong_seen and len(results) == 3 and not wrong:
        rs.durable(os.path.join(os.path.abspath(a.folder), "observed.json"), dict(nothing_wrong_seen=True, when=datetime.datetime.now().isoformat(timespec="seconds")))
    told = score(results) if not wrong else dict(verdict="INVALID", why=wrong, windows={}, notes=[], holds_40=None)
    told["timing_only"] = not_recorded(a.folder)
    for n, of in told["windows"].items():
        for name, x in zip(("A", "B", "A'"), of):
            print(f"W{n} {name:2s} " + "  ".join(f"{k} {format(v, '.2f') if isinstance(v, float) else v}" for k, v in x.items()))
    for line in told["notes"]:
        print(f"  {line}")
    print(f"{told['verdict']}{' (timing only)' if told['timing_only'] else ''}: " + "; ".join(told["why"]))
    for line in told["timing_only"]:
        print(f"  timing only: {line}")
    if told["holds_40"] is not None:
        print("B " + ("sustained" if told["holds_40"] else "did not sustain") + " 40 distinct shown frames a second in both W2 and W3")
    if a.json:
        with open(a.json, "w") as f:
            json.dump(told, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
