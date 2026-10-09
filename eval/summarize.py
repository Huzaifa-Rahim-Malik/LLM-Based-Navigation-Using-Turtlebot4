#!/usr/bin/env python3
"""
Turn the hand-recorded robot trials into the README tables.

    python3 eval/summarize.py nav     eval/results/navigation_trials.csv
    python3 eval/summarize.py latency eval/results/latency_trials.csv
"""
import sys
from collections import defaultdict

from common import md_table, mean_sd, read_csv


def nav(path):
    rows = read_csv(path)
    by = defaultdict(list)
    for r in rows:
        by[r["type"]].append(r)
    table, tu, tr, tn = [], 0, 0, 0
    for t, rs in by.items():
        u = sum(int(r["understood"]) for r in rs)
        reached = [r for r in rs if r["expected_target"] != "NONE"]
        g = sum(int(r["reached"]) for r in reached)
        times = [float(r["start_to_goal_s"]) for r in reached if r["reached"] == "1" and r["start_to_goal_s"]]
        notes = "; ".join(sorted({r["failure_note"] for r in rs if r["failure_note"]}))
        table.append([t, f"{u} / {len(rs)}", f"{g} / {len(reached)}" if reached else "n/a",
                      mean_sd(times, 1) if times else "n/a", notes])
        tu += u; tr += g; tn += len(rs)
    print(f"\n### Navigation success (N = {tn} trials)\n")
    print(md_table(["Command type", "Understood correctly", "Reached goal", "Travel time (s)", "Notes"], table))
    reached_total = sum(1 for r in rows if r["expected_target"] != "NONE")
    print(f"\nOverall: understood {tu}/{tn}, reached goal {tr}/{reached_total} "
          f"({100 * tr / max(reached_total, 1):.0f} %).")


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
    if len(sys.argv) != 3 or sys.argv[1] not in ("nav", "latency"):
        raise SystemExit(__doc__)
    {"nav": nav, "latency": latency}[sys.argv[1]](sys.argv[2])
