"""Shared helpers for the evaluation scripts (no ROS 2 needed)."""
import csv
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SRC = os.path.join(ROOT, "src")
RESULTS = os.path.join(HERE, "results")
os.makedirs(RESULTS, exist_ok=True)
sys.path.insert(0, SRC)


class QuietLogger:
    """Stand-in for the ROS 2 logger used by the application classes."""
    def __init__(self, verbose=False):
        self.verbose = verbose

    def info(self, msg):
        if self.verbose:
            print("[info]", msg)

    def warn(self, msg):
        if self.verbose:
            print("[warn]", msg)

    def error(self, msg):
        print("[error]", msg)


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(line for line in f if not line.lstrip().startswith("#")))


def write_csv(path, rows, fieldnames):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"saved {os.path.relpath(path, ROOT)}")


def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def mean_sd(values, digits=2):
    values = [v for v in values if v is not None]
    if not values:
        return "n/a"
    if len(values) == 1:
        return f"{values[0]:.{digits}f} (n=1)"
    return f"{statistics.mean(values):.{digits}f} ± {statistics.stdev(values):.{digits}f} (n={len(values)})"
