#!/usr/bin/env python3
"""
Turn the hand-recorded robot trials into the README tables.

    python3 eval/summarize.py nav     eval/results/navigation_trials.csv          # one row per route / goal
    python3 eval/summarize.py nav     eval/results/navigation_trials.csv --by type
    python3 eval/summarize.py latency eval/results/latency_trials.csv
"""
import sys
from collections import defaultdict

from common import md_table, mean_sd, read_csv


def nav(path, by="route"):
    rows = [r for r in read_csv(path) if r.get("reached", "") != "" or r.get("understood", "") != ""]
    if not rows:
        raise SystemExit("no filled-in trials found in " + path)

    def label(r):
        if r["expected_target"] == "NONE":
            return "unknown place (must be refused)"
        if by == "type":
            return r["type"]
        start = (r.get("start") or "").strip()
        return f"{start} -> {r['expected_target']}" if start else r["expected_target"]

    groups = defaultdict(list)
    for r in rows:
        groups[label(r)].append(r)

    def ints(rs, key):
        return [int(r[key]) for r in rs if r.get(key, "") != ""]

    table = []
    for name, rs in groups.items():
        invalid = rs[0]["expected_target"] == "NONE"
        if invalid:
            refused = sum(ints(rs, "understood"))
            table.append([name, len(rs), f"refused {refused} / {len(rs)}", "n/a", "n/a", ""])
            continue
        reached = sum(ints(rs, "reached"))
        times = [float(r["start_to_goal_s"]) for r in rs if r["reached"] == "1" and r.get("start_to_goal_s")]
        col = ints(rs, "collisions")
        notes = "; ".join(sorted({r["failure_note"] for r in rs if r.get("failure_note")}))
        table.append([name, len(rs), f"{reached} / {len(rs)}",
                      mean_sd(times, 1) if times else "n/a",
                      sum(col) if col else "n/a", notes])
    print(f"\n### Robot trials (N = {len(rows)})\n")
    print(md_table(["Route / goal", "Trials", "Goal reached", "Travel time (s)", "Collisions", "Notes"], table))

    real = [r for r in rows if r["expected_target"] != "NONE"]
    if real:
        reached = sum(ints(real, "reached"))
        col = ints(real, "collisions")
        times = [float(r["start_to_goal_s"]) for r in real if r["reached"] == "1" and r.get("start_to_goal_s")]
        print(f"\nOverall: goal reached {reached}/{len(real)} ({100 * reached / len(real):.0f} %)"
              + (f", mean travel time {mean_sd(times, 1)} s" if times else "")
              + (f", {sum(col)} collision(s) in {len(col)} trials" if col else ", collisions not recorded") + ".")


def latency(path):
    rows = read_csv(path)
    stages = list(dict.fromkeys(r["stage"] for r in rows))
    devices = list(dict.fromkeys(r["device"] for r in rows))
    table = []
    for s in stages:
        row = [s]
        for d in devices:
            v = [float(r["value"]) for r in rows if r["stage"] == s and r["device"] == d]
            unit = next((r["unit"] for r in rows if r["stage"] == s), "")
            row.append(f"{mean_sd(v)} {unit}" if v else "n/a")
        table.append(row)
    print("\n### End-to-end latency\n")
    print(md_table(["Stage"] + devices, table))


if __name__ == "__main__":
    args = sys.argv[1:]
    by = "route"
    if "--by" in args:
        k = args.index("--by")
        by = args[k + 1]
        del args[k:k + 2]
    if len(args) != 2 or args[0] not in ("nav", "latency") or by not in ("route", "type"):
        raise SystemExit(__doc__)
    nav(args[1], by) if args[0] == "nav" else latency(args[1])
