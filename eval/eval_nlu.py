#!/usr/bin/env python3
"""
Offline evaluation of the language-understanding part (no robot, no microphone, no ROS 2).

For every command in nlu_test_cases.csv it runs the SAME code the assistant uses:
    IntentDetector.detect_intent  ->  (multi-stop split)  ->  LocationExtractor.extract_location
and compares the result with the expected answer.

Two passes:
  * rules only   - the LLM fallback is switched off. Cases where the rules fail but the fallback
                   guard would have asked the LLM are counted as "needs LLM".
  * rules + LLM  - (only with --with-llm; needs `ollama serve` and the model pulled)

Usage:
    python3 eval/eval_nlu.py                       # rules only (works anywhere)
    python3 eval/eval_nlu.py --with-llm            # also run the hybrid pass
    python3 eval/eval_nlu.py --with-llm --model llama3.1:8b --gpu
"""
import argparse
import os
import re
import statistics
import time

import ollama

from common import HERE, SRC, RESULTS, QuietLogger, md_table, read_csv, write_csv

# Keep in sync with src/chat_interface.py (_MULTI_SEP). It is copied here because importing
# chat_interface would require ROS 2.
MULTI_SEP = re.compile(
    r'\s+(?:then(?:\s+go\s+to)?|and\s+then(?:\s+go\s+to)?|after\s+that(?:\s+go\s+to)?'
    r'|followed\s+by|next\s+go\s+to)\s+',
    re.IGNORECASE,
)

_REAL_GENERATE = ollama.generate          # captured before any patching


class Probe:
    """Replaces ollama.generate inside the extractor to count / time LLM calls."""
    def __init__(self, use_real):
        self.use_real = use_real
        self.calls = 0
        self.llm_time = 0.0

    def reset(self):
        self.calls = 0
        self.llm_time = 0.0

    def generate(self, *args, **kwargs):
        self.calls += 1
        if not self.use_real:
            return {"response": "NONE"}
        t = time.perf_counter()
        try:
            return _REAL_GENERATE(*args, **kwargs)
        finally:
            self.llm_time += time.perf_counter() - t


def install(probe):
    ollama.generate = probe.generate


def build(model="llama3.2:3b", gpu=False):
    """Create the real application objects (without ROS 2)."""
    from intent_detector import IntentDetector
    from location_extractor import LocationExtractor
    from location_manager import LocationManager
    from response_generator import InferenceConfig

    logger = QuietLogger()
    lm = LocationManager(logger, os.path.join(SRC, "locations.yaml"))
    cfg = InferenceConfig()
    cfg.set_model(model)
    cfg.set_gpu(gpu)
    ex = LocationExtractor(logger, lm, model=model, inference_config=cfg)
    # the app asks the user to choose when several locations match; here we just record it
    ex.disambiguate_location = lambda matches: ("AMBIGUOUS", list(matches))
    return ex, IntentDetector(logger), lm, cfg


def parse_multi(ex, text):
    """Same logic as ChatInterface multi-location parsing."""
    parts = MULTI_SEP.split(text)
    if len(parts) < 2:
        return []
    locs = []
    for part in parts:
        loc = ex.extract_location(part.strip())
        if isinstance(loc, tuple):
            loc = "AMBIGUOUS"
        if loc and not isinstance(loc, list):
            locs.append(loc)
    return locs if len(locs) >= 2 else []


def to_key(res):
    if res is None or res == []:
        return "NONE"
    if isinstance(res, tuple):
        return "AMBIGUOUS"
    if isinstance(res, dict):
        return f"{res['x']:g},{res['y']:g}"
    if isinstance(res, list):
        return "|".join(to_key(r) for r in res)
    return str(res)


def norm_expected(s):
    s = (s or "").strip()
    m = re.fullmatch(r"(-?[\d.]+)\s*,\s*(-?[\d.]+)", s)
    if m:
        return f"{float(m.group(1)):g},{float(m.group(2)):g}"
    return s


def evaluate(ex, idet, probe, cmd, expected_intent, expected_target):
    """Run one command through intent detection + extraction. Returns a result dict."""
    probe.reset()
    t0 = time.perf_counter()
    intent = idet.detect_intent(cmd)
    got = "NOT_RUN"
    if intent == "navigate":                       # the app only extracts targets for navigate
        multi = parse_multi(ex, cmd)
        got = to_key(multi if multi else ex.extract_location(cmd))
    total = time.perf_counter() - t0
    intent_ok = intent == expected_intent
    if expected_intent == "chat":
        understood = intent_ok
    else:
        understood = intent_ok and got.lower() == norm_expected(expected_target).lower()
    return {
        "intent": intent, "intent_ok": int(intent_ok), "got": got,
        "understood": int(understood),
        "llm_consulted": int(probe.calls > 0),
        "rule_ms": round((total - probe.llm_time) * 1000, 3),
        "llm_s": round(probe.llm_time, 3) if probe.calls else "",
    }


def run_suite(cases, ex, idet, probe):
    install(probe)
    rows = []
    for c in cases:
        r = evaluate(ex, idet, probe, c["command"], c["expected_intent"], c["expected_target"])
        rows.append({**c, **r})
    return rows


def frac(rows, key="understood"):
    return f"{sum(int(r[key]) for r in rows)} / {len(rows)}"


def summarize(rows_rules, rows_hybrid):
    types = list(dict.fromkeys(r["type"] for r in rows_rules))
    headers = ["Command type", "Intent correct", "Understood (rules only)", "LLM consulted"]
    if rows_hybrid:
        headers.append("Understood (rules + LLM)")
    table = []
    for t in types:
        a = [r for r in rows_rules if r["type"] == t]
        row = [t, frac(a, "intent_ok"), frac(a), sum(r["llm_consulted"] for r in a)]
        if rows_hybrid:
            row.append(frac([r for r in rows_hybrid if r["type"] == t]))
        table.append(row)
    total = ["**all**", frac(rows_rules, "intent_ok"), frac(rows_rules),
             sum(r["llm_consulted"] for r in rows_rules)]
    if rows_hybrid:
        total.append(frac(rows_hybrid))
    table.append(total)
    return md_table(headers, table)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", default=os.path.join(HERE, "nlu_test_cases.csv"))
    ap.add_argument("--with-llm", action="store_true", help="also run the rules + LLM pass (needs Ollama)")
    ap.add_argument("--model", default="llama3.2:3b")
    ap.add_argument("--gpu", action="store_true", help="LLM on GPU (num_gpu=99) instead of CPU")
    args = ap.parse_args()

    cases = read_csv(args.cases)
    ex, idet, _lm, _cfg = build(args.model, args.gpu)

    rows_rules = run_suite(cases, ex, idet, Probe(use_real=False))
    rows_hybrid = run_suite(cases, ex, idet, Probe(use_real=True)) if args.with_llm else None

    print(f"\n### Natural-language understanding ({len(cases)} commands, rule-based intent + extraction)\n")
    print(summarize(rows_rules, rows_hybrid))

    nav = [r for r in rows_rules if r["intent"] == "navigate"]
    if nav:
        med = statistics.median(float(r["rule_ms"]) for r in nav)
        print(f"\nMedian rule-based intent + extraction time: {med:.3f} ms (n={len(nav)})")
    if rows_hybrid:
        llm = [float(r["llm_s"]) for r in rows_hybrid if r["llm_s"] != ""]
        if llm:
            dev = "GPU" if args.gpu else "CPU"
            print(f"LLM fallback ({args.model}, {dev}), {len(llm)} calls:")
            print(f"  first call {llm[0]:.2f} s  (includes loading the model if it was not already in memory)")
            if len(llm) > 1:
                warm = llm[1:]
                print(f"  following {len(warm)} calls: median {statistics.median(warm):.2f} s "
                      f"(min {min(warm):.2f}, max {max(warm):.2f})  <- report this as the normal fallback time")

    final = rows_hybrid or rows_rules
    fails = [r for r in final if not int(r["understood"])]
    print(f"\n### Failures in the {'rules + LLM' if rows_hybrid else 'rules-only'} pass ({len(fails)})\n")
    if fails:
        print(md_table(["Type", "Command", "Expected", "Got", "LLM consulted"],
                       [[r["type"], f'`{r["command"]}`',
                         r["expected_target"] or r["expected_intent"],
                         r["got"] if r["intent_ok"] else f'intent={r["intent"]}',
                         "yes" if r["llm_consulted"] else "no"] for r in fails]))
    else:
        print("none")

    fields = ["type", "command", "expected_intent", "expected_target", "intent", "intent_ok",
              "got", "understood", "llm_consulted", "rule_ms", "llm_s"]
    write_csv(os.path.join(RESULTS, "nlu_rules_only.csv"), rows_rules, fields)
    if rows_hybrid:
        write_csv(os.path.join(RESULTS, "nlu_rules_plus_llm.csv"), rows_hybrid, fields)


if __name__ == "__main__":
    main()
