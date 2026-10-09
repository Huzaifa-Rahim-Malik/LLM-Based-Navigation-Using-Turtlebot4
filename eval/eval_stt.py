#!/usr/bin/env python3
"""
Speech-recognition evaluation: word error rate (WER), transcription time, and whether the
transcript still produces the right command.

Uses the WAV files + manifest.csv from record_samples.py and runs them through the project's
own VoiceInput.transcribe_audio() (resample -> normalise -> Whisper with the location prompt ->
hallucination filter -> mishearing fix), so the numbers describe the real pipeline.

    python3 eval/eval_stt.py --models base small large-v3 --tag gpu
    CUDA_VISIBLE_DEVICES="" python3 eval/eval_stt.py --models base small --tag cpu   # force CPU
    python3 eval/eval_stt.py --pipeline raw --models base      # plain faster-whisper, no project logic
"""
import argparse
import gc
import os
import re
import time
import wave

import numpy as np

import eval_nlu
from common import HERE, QuietLogger, md_table, read_csv, write_csv, RESULTS

SAMPLES = os.path.join(HERE, "stt_samples")


def norm_words(text):
    text = re.sub(r"[^a-z0-9' ]+", " ", (text or "").lower())
    return text.split()


def edit_distance(ref, hyp):
    d = list(range(len(hyp) + 1))
    for i in range(1, len(ref) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(hyp) + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (ref[i - 1] != hyp[j - 1]))
            prev = cur
    return d[len(hyp)]


def read_wav(path):
    with wave.open(path, "rb") as w:
        sr, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError(f"{path}: expected 16-bit PCM")
    audio = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if ch > 1:
        audio = audio.reshape(-1, ch).mean(axis=1)
    return audio, sr


def make_transcriber(size, pipeline, locations):
    if pipeline == "project":
        from voice_input import VoiceInput
        vi = VoiceInput(QuietLogger(), model_size=size)

        def transcribe(audio, sr):
            vi._native_sr = sr
            return vi.transcribe_audio(audio, context_locations=locations)
        return transcribe, vi

    from faster_whisper import WhisperModel
    from voice_input import _resample_to_whisper
    model = WhisperModel(size)

    def transcribe(audio, sr):
        audio = _resample_to_whisper(audio, sr) if sr != 16000 else audio
        segs, _ = model.transcribe(audio, language="en", vad_filter=False)
        return " ".join(s.text for s in segs).strip()
    return transcribe, model


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", nargs="+", default=["base", "small", "large-v3"])
    ap.add_argument("--pipeline", choices=["project", "raw"], default="project")
    ap.add_argument("--tag", default="run", help="label for the output files, e.g. gpu or cpu")
    ap.add_argument("--manifest", default=os.path.join(SAMPLES, "manifest.csv"))
    ap.add_argument("--with-llm", action="store_true", help="allow the LLM fallback when checking commands")
    args = ap.parse_args()

    manifest = read_csv(args.manifest)
    if not manifest:
        raise SystemExit("manifest.csv is empty - run record_samples.py first")

    ex, idet, lm, _ = eval_nlu.build()
    probe = eval_nlu.Probe(use_real=args.with_llm)
    eval_nlu.install(probe)
    locations = lm.get_all_locations()

    per_sample, summary = [], []
    for size in args.models:
        print(f"\n== Whisper {size} ({args.pipeline} pipeline) ==")
        transcribe, handle = make_transcriber(size, args.pipeline, locations)
        first_audio, first_sr = read_wav(os.path.join(SAMPLES, manifest[0]["file"]))
        transcribe(first_audio, first_sr)                      # warm-up, not timed

        errors = words = ok = 0
        times = []
        for row in manifest:
            audio, sr = read_wav(os.path.join(SAMPLES, row["file"]))
            t0 = time.perf_counter()
            hyp = transcribe(audio, sr) or ""
            dt = time.perf_counter() - t0
            ref_w, hyp_w = norm_words(row["reference"]), norm_words(hyp)
            e = edit_distance(ref_w, hyp_w)
            res = eval_nlu.evaluate(ex, idet, probe, hyp, row["expected_intent"], row["expected_target"])
            errors += e
            words += len(ref_w)
            ok += res["understood"]
            times.append(dt)
            per_sample.append({"model": size, "file": row["file"], "type": row["type"],
                               "reference": row["reference"], "hypothesis": hyp,
                               "word_errors": e, "ref_words": len(ref_w),
                               "seconds": round(dt, 3), "command_understood": res["understood"]})
        summary.append([f"`{size}`", f"{100 * errors / max(words, 1):.1f} %",
                        f"{ok} / {len(manifest)}", f"{sum(times) / len(times):.2f}"])
        del transcribe, handle
        gc.collect()

    print(f"\n### Speech recognition (N = {len(manifest)} spoken commands, tag: {args.tag})\n")
    print(md_table(["Whisper model", "Word error rate", "Command understood", "Mean transcription time (s)"], summary))
    write_csv(os.path.join(RESULTS, f"stt_{args.tag}.csv"), per_sample,
              ["model", "file", "type", "reference", "hypothesis", "word_errors", "ref_words",
               "seconds", "command_understood"])


if __name__ == "__main__":
    main()
