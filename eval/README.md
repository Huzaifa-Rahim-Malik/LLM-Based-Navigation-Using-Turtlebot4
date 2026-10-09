# Evaluation kit

Scripts that produce the numbers for the **Results** section of the main README. Everything except the
robot trials runs on your PC with no robot, no ROS 2 and no microphone (the speech test needs a mic once,
to record the sample set).

| Step | Script | Needs | Gives you |
|---|---|---|---|
| 1 | `eval_nlu.py` | nothing (Ollama only for `--with-llm`) | Table 1 "Understood correctly", the invalid-place safety result, rule timing |
| 2 | `record_samples.py` | microphone | the spoken test set |
| 3 | `eval_stt.py` | Whisper models | Table 2 (word error rate, command understood, time) |
| 4 | `eval_llm.py` | Ollama + models pulled | Table 4 (LLM comparison) |
| 5 | robot trials + `summarize.py nav` | the robot | Table 1 "Reached goal" |
| 6 | `summarize.py latency` | your measurements | Table 3 (end-to-end latency) |

Run everything from the repository root. All raw results are saved as CSV in `eval/results/`; commit them,
they are your evidence.

```bash
pip install -r requirements.txt
ollama serve &                       # only for steps using the LLM
```

## 1. Language understanding (5 minutes, no hardware)

```bash
python3 eval/eval_nlu.py                 # rules only
python3 eval/eval_nlu.py --with-llm      # + rules-with-LLM pass (default model llama3.2:3b)
```

It sends every command in `nlu_test_cases.csv` through the real `IntentDetector` and `LocationExtractor`
and compares with the expected answer. **Edit the CSV to build your own test set** (aim for 10+ per type,
phrased the way people really speak). Write the expected answer from what the sentence *means*, never from
what the code currently returns, otherwise the test proves nothing.

How to read the output:
- **Understood (rules only):** correct without any LLM. **LLM consulted:** the rules failed but the guard let
  the LLM decide (those cases are counted as failures in the rules-only column and resolved in the hybrid column).
- **invalid** row = places that do not exist. Understood means the command was *rejected* and no goal would be
  sent. This is a safety result, so report it.
- The failures table lists every miss. Report them: honest limitations make the result credible.

## 2-3. Speech recognition

```bash
python3 eval/record_samples.py --list            # find your microphone number
python3 eval/record_samples.py --device <n>      # say each sentence; Enter = start, Enter = stop
python3 eval/eval_stt.py --models base small large-v3 --tag gpu
CUDA_VISIBLE_DEVICES="" python3 eval/eval_stt.py --models base small large-v3 --tag cpu    # CPU run
```

Record in a quiet room at a fixed distance, ideally 2 repetitions (`--reps 2`). `eval_stt.py` runs your real
`VoiceInput.transcribe_audio` pipeline and reports word error rate (share of words wrong), the share of
commands that still resolve to the right target, and mean transcription time per clip (warm-up excluded).
Add `--pipeline raw` to compare against plain Whisper without your location prompt and corrections.
The WAV files are your own voice; add `eval/stt_samples/*.wav` to `.gitignore` if you prefer not to publish them.

## 4. LLM comparison

```bash
ollama pull llama3.2:3b llama3.1:8b qwen2.5:7b mistral:7b
python3 eval/eval_llm.py                                   # every installed model, CPU and GPU
python3 eval/eval_llm.py --models llama3.2:3b llama3.1:8b --device gpu
```

Per model: fallback accuracy on the commands that really reach the LLM, time per call, chat reply time and
tokens/s (from Ollama's own counters), plus `ollama ps` size and GPU memory.

## 5. Robot trials ("Reached goal")

1. Terminal 1: `./scripts/robot_launch.sh <x> <y> <yaw>`; terminal 2: `cd src && python3 gui.py` (or `main.py --text-only`).
2. Use text mode so speech errors do not mix with navigation errors.
3. Take the navigate commands whose expected target is not NONE, plus the invalid ones. Repeat each at least 3 times,
   always starting from the same marked spot (reset the pose with the same `robot_launch.sh` arguments).
4. Copy `navigation_trials_template.csv` to `eval/results/navigation_trials.csv` and add one row per trial:
   `understood` = the assistant picked the intended target; `reached` = log says arrived **and** the robot is
   physically on the goal (mark it with tape); `start_to_goal_s` from the log timestamps or a stopwatch;
   `failure_note` = why it failed. For invalid places use `expected_target` NONE and `understood` 1 only if it
   refused to move.
5. `python3 eval/summarize.py nav eval/results/navigation_trials.csv`

## 6. End-to-end latency

Fill `eval/results/latency_trials.csv` (template included), one row per measurement, `device` cpu or gpu:

| Stage | Where the number comes from |
|---|---|
| `speech_to_text` | mean seconds per clip from `eval/results/stt_cpu.csv` / `stt_gpu.csv` |
| `rule_extraction` (ms) | "Median rule-based ... time" printed by `eval_nlu.py` |
| `llm_fallback` | "LLM fallback time" printed by `eval_nlu.py --with-llm` (CPU run and `--gpu` run) |
| `utterance_to_robot_moves` | film the screen and the robot; count frames from the end of your sentence to the first wheel movement (or use a stopwatch), at least 10 runs |

`python3 eval/summarize.py latency eval/results/latency_trials.csv`

## Reporting checklist

- State N, the hardware, the model names and the date next to every table.
- Show mean ± standard deviation for times; keep the raw CSVs in the repository.
- Keep the failure cases. A reviewer trusts "17 of 20, failures listed" more than "100 %".
- If you fix something because of a failure, re-run and report both runs ("before / after").
  `optional_rule_fix.patch` is one such change found while building this kit
  (`git apply eval/optional_rule_fix.patch`; read the discussion in the chat before applying).
