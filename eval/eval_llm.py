#!/usr/bin/env python3
"""
LLM comparison for the models offered in the GUI (CPU and/or GPU).

For each model it measures
  1. location-fallback accuracy: the commands where the rules fail but the fallback guard lets the
     LLM decide (found automatically from nlu_test_cases.csv), run through the real
     LocationExtractor.extract_location_with_ai, plus time per call;
  2. chat speed: 10 short questions using the same prompt template as ResponseGenerator, timed
     with Ollama's own counters (total time, tokens/s, model load time);
  3. memory: `ollama ps` (model size and CPU/GPU split) and nvidia-smi memory right after the run.

Needs `ollama serve` running and the models pulled (ollama pull llama3.2:3b ...).

    python3 eval/eval_llm.py                                  # all installed catalog models, CPU and GPU
    python3 eval/eval_llm.py --models llama3.2:3b llama3.1:8b --device gpu
"""
import argparse
import os
import re
import statistics
import subprocess

import ollama

import eval_nlu
from common import HERE, RESULTS, md_table, read_csv, write_csv

CHAT_PROMPTS = [
    "Hello, who are you?",
    "What can you help me with?",
    "How do you find your way around a building?",
    "Tell me a fun fact about robots.",
    "What sensors do you have?",
    "Can you explain what SLAM is?",
    "Why do robots need maps?",
    "How does your battery work?",
    "Give me a tip for staying focused at work.",
    "What is the difference between a robot and a machine?",
]
CHAT_TEMPLATE = ("You are a friendly, helpful indoor robot assistant. Give a direct, warm response in 50-60 words. "
                 "Answer the current question - don't force links to unrelated prior topics."
                 "\n\nUser: {q}\n\nRobot:")


def field(resp, key):
    v = getattr(resp, key, None)
    if v is None and isinstance(resp, dict):
        v = resp.get(key)
    return v


def sh(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return ""


def ollama_ps_line(model):
    out = sh(["ollama", "ps"])
    for line in out.splitlines()[1:]:
        if line.split() and line.split()[0] == model:
            m = re.search(r"(\d+(?:\.\d+)?\s?[KMG]B)\s+(\S+(?:\s*(?:GPU|CPU))?(?:/\S+\s*(?:GPU|CPU))?)", line)
            return f"{m.group(1)} ({m.group(2).strip()})" if m else line.strip()
    return "n/a"


def vram_used_mb():
    out = sh(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"])
    try:
        return int(out.splitlines()[0])
    except Exception:
        return None


def fallback_candidates(cases):
    """Commands where the rules fail but the guard still consults the LLM."""
    ex, idet, _lm, _cfg = eval_nlu.build()
    probe = eval_nlu.Probe(use_real=False)
    rows = eval_nlu.run_suite(cases, ex, idet, probe)
    return [c for c, r in zip(cases, rows)
            if r["llm_consulted"] and c["expected_intent"] == "navigate"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", nargs="+", default=None, help="default: catalog models that are installed")
    ap.add_argument("--device", choices=["cpu", "gpu", "both"], default="both")
    ap.add_argument("--runs", type=int, default=1, help="repeat the chat prompts this many times")
    ap.add_argument("--cases", default=os.path.join(HERE, "nlu_test_cases.csv"))
    args = ap.parse_args()

    from response_generator import InferenceConfig
    models = args.models
    if not models:
        installed = InferenceConfig.detect_installed_models()
        models = [m for m in InferenceConfig.MODEL_CATALOG if m in installed]
    if not models:
        raise SystemExit("no catalog models installed - run: ollama pull llama3.2:3b")
    devices = {"cpu": [False], "gpu": [True], "both": [False, True]}[args.device]

    cands = fallback_candidates(read_csv(args.cases))
    print(f"{len(cands)} fallback commands: " + "; ".join(c["command"] for c in cands))

    results = []
    for model in models:
        for gpu in devices:
            label = "GPU" if gpu else "CPU"
            print(f"\n== {model} on {label} ==")
            ex, idet, _lm, cfg = eval_nlu.build(model, gpu)
            probe = eval_nlu.Probe(use_real=True)

            # warm-up (loads the model, not timed)
            ollama.generate(model=model, prompt="Hi", options={"num_gpu": cfg.num_gpu})

            rows = eval_nlu.run_suite(cands, ex, idet, probe)
            correct = sum(r["understood"] for r in rows)
            fb_times = [float(r["llm_s"]) for r in rows if r["llm_s"] != ""]

            totals, rates = [], []
            for _ in range(args.runs):
                for q in CHAT_PROMPTS:
                    r = ollama.generate(model=model, prompt=CHAT_TEMPLATE.format(q=q),
                                        options={"num_gpu": cfg.num_gpu})
                    td, ec, ed = field(r, "total_duration"), field(r, "eval_count"), field(r, "eval_duration")
                    if td:
                        totals.append(td / 1e9)
                    if ec and ed:
                        rates.append(ec / (ed / 1e9))
            mem = ollama_ps_line(model)
            vram = vram_used_mb()
            results.append({
                "model": model, "device": label,
                "fallback_correct": correct, "fallback_total": len(rows),
                "fallback_mean_s": round(statistics.mean(fb_times), 2) if fb_times else "",
                "chat_mean_s": round(statistics.mean(totals), 2) if totals else "",
                "chat_sd_s": round(statistics.stdev(totals), 2) if len(totals) > 1 else "",
                "tokens_per_s": round(statistics.mean(rates), 1) if rates else "",
                "ollama_ps": mem, "vram_used_mb": vram if vram is not None else "",
            })
            for r in rows:
                if not r["understood"]:
                    print(f"   miss: {r['command']!r} -> {r['got']} (expected {r['expected_target']})")
            try:                                            # unload before the next model
                ollama.generate(model=model, prompt="", keep_alive=0)
            except Exception:
                pass

    print("\n### LLM comparison\n")
    print(md_table(
        ["Model", "Device", "Fallback accuracy", "Fallback time (s)", "Chat reply time (s)",
         "Tokens/s", "Loaded size (ollama ps)", "GPU memory used (MB)"],
        [[f"`{r['model']}`", r["device"], f"{r['fallback_correct']} / {r['fallback_total']}",
          r["fallback_mean_s"], f"{r['chat_mean_s']} ± {r['chat_sd_s']}" if r["chat_sd_s"] != "" else r["chat_mean_s"],
          r["tokens_per_s"], r["ollama_ps"], r["vram_used_mb"] or "n/a"] for r in results]))
    write_csv(os.path.join(RESULTS, "llm_comparison.csv"), results,
              ["model", "device", "fallback_correct", "fallback_total", "fallback_mean_s",
               "chat_mean_s", "chat_sd_s", "tokens_per_s", "ollama_ps", "vram_used_mb"])


if __name__ == "__main__":
    main()
