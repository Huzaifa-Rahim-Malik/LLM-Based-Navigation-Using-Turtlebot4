#!/usr/bin/env python3
"""
Collect the automatically measured latency stages into eval/results/latency_trials.csv
(the file that `summarize.py latency` reads). Robot-side stages are added by hand.

    # speech -> text, from an eval_stt.py run (one Whisper model, one device)
    python3 eval/make_latency_csv.py stt eval/results/stt_gpu.csv --model large-v3 --device gpu
    python3 eval/make_latency_csv.py stt eval/results/stt_cpu.csv --model large-v3 --device cpu

    # rule extraction (ms) and LLM fallback (s), from an eval_nlu.py --with-llm run
    python3 eval/make_latency_csv.py nlu eval/results/nlu_cpu.csv --device cpu
    python3 eval/make_latency_csv.py nlu eval/results/nlu_gpu.csv --device gpu

Run each command once per file: rows are appended, so running it twice duplicates them.
"""
import argparse
import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results", "latency_trials.csv")
FIELDS = ["device", "stage", "value", "unit"]


def read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(line for line in f if not line.lstrip().startswith("#")))


def append(rows):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    new = not os.path.exists(OUT) or os.path.getsize(OUT) == 0
    with open(OUT, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerows(rows)
    print(f"appended {len(rows)} rows to {os.path.relpath(OUT, os.path.dirname(HERE))}")


def stt(args):
    rows = [r for r in read(args.file) if r["model"] == args.model]
    # a clip that returned no text can report 0.000 s; it is not a real transcription time
    vals = [float(r["seconds"]) for r in rows if float(r["seconds"]) > 0]
    if not vals:
        raise SystemExit(f"no rows for model {args.model} in {args.file}")
    append([{"device": args.device, "stage": "speech_to_text", "value": v, "unit": "s"} for v in vals])


def nlu(args):
    rows = read(args.file)
    out, seen_llm = [], False
    for r in rows:
        if r["type"] != "chat" and r["rule_ms"] != "":
            out.append({"device": args.device, "stage": "rule_extraction", "value": r["rule_ms"], "unit": "ms"})
        if r["llm_s"] != "":
            # the first LLM call after a CPU/GPU switch includes loading the model into memory
            # (many seconds), so it is kept apart from the normal per-call time
            stage = "llm_fallback" if seen_llm else "llm_first_call"
            seen_llm = True
            out.append({"device": args.device, "stage": stage, "value": r["llm_s"], "unit": "s"})
    append(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("stt")
    a.add_argument("file")
    a.add_argument("--model", default="large-v3")
    a.add_argument("--device", choices=["cpu", "gpu"], required=True)
    a.set_defaults(fn=stt)
    b = sub.add_parser("nlu")
    b.add_argument("file")
    b.add_argument("--device", choices=["cpu", "gpu"], required=True)
    b.set_defaults(fn=nlu)
    args = ap.parse_args()
    args.fn(args)
