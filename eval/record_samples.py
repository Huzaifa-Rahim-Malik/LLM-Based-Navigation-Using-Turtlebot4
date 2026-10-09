#!/usr/bin/env python3
"""
Record the spoken test set for the speech-recognition evaluation.

For each test command you press Enter to start, say the sentence, press Enter to stop
(the same push-to-talk style as the GUI). WAV files and a manifest.csv are written to
eval/stt_samples/. Re-running skips files that already exist, so you can stop and continue.

    python3 eval/record_samples.py --list                 # show audio devices
    python3 eval/record_samples.py                        # default: named, filler, synonym, multi-stop
    python3 eval/record_samples.py --device 3 --rate 48000 --reps 2
"""
import argparse
import csv
import os
import wave

import numpy as np
import sounddevice as sd

from common import HERE, read_csv

OUT = os.path.join(HERE, "stt_samples")


def record(device, rate):
    chunks = []
    stream = sd.InputStream(samplerate=rate, channels=1, dtype="float32", device=device,
                            callback=lambda indata, f, t, s: chunks.append(indata[:, 0].copy()))
    stream.start()
    input("   ...recording, press Enter to STOP ")
    stream.stop()
    stream.close()
    return np.concatenate(chunks) if chunks else np.zeros(0, dtype="float32")


def save_wav(path, audio, rate):
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--device", type=int, default=None)
    ap.add_argument("--rate", type=int, default=48000, help="record at the microphone's native rate")
    ap.add_argument("--types", default="named,named_filler,synonym,multi_stop,invalid")
    ap.add_argument("--reps", type=int, default=1, help="repetitions of each sentence")
    ap.add_argument("--cases", default=os.path.join(HERE, "nlu_test_cases.csv"))
    args = ap.parse_args()

    if args.list:
        print(sd.query_devices())
        return
    os.makedirs(OUT, exist_ok=True)
    wanted = set(args.types.split(","))
    cases = [c for c in read_csv(args.cases) if c["type"] in wanted]

    manifest = os.path.join(OUT, "manifest.csv")
    old = read_csv(manifest) if os.path.exists(manifest) else []
    rows = list(old)
    done = {r["file"] for r in old}
    print(f"{len(cases) * args.reps} recordings to make; quiet room, same distance from the microphone.\n")
    for i, c in enumerate(cases, 1):
        for rep in range(1, args.reps + 1):
            name = f"{i:03d}_{rep}.wav"
            if name in done:
                continue
            print(f"[{i}/{len(cases)}] rep {rep}  SAY:  \"{c['command']}\"")
            input("   press Enter to START ")
            audio = record(args.device, args.rate)
            save_wav(os.path.join(OUT, name), audio, args.rate)
            rows.append({"file": name, "reference": c["command"], "type": c["type"],
                         "expected_intent": c["expected_intent"], "expected_target": c["expected_target"]})
            with open(manifest, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["file", "reference", "type", "expected_intent", "expected_target"])
                w.writeheader()
                w.writerows(rows)
    print("done ->", manifest)


if __name__ == "__main__":
    main()
