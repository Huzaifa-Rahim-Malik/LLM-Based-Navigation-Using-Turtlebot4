## Results

**Test setup:** TurtleBot 4, Ubuntu 24.04, ROS 2 Jazzy, map `maps/robotic_arena.yaml`, __ named goals,
PC: __ CPU / __ GPU / __ GB RAM, LLM `llama3.2:3b`, Whisper `base`, `small` and `large-v3`. Evaluated on 9 October 2026.
All raw results are in [`eval/results/`](eval/results/).

**1. Navigation success**

Language understanding was tested on text, so speech errors do not mix with understanding errors
(N = 45 navigation commands and 8 chat messages, 53 in total, from [`eval/nlu_test_cases.csv`](eval/nlu_test_cases.csv)).
"Rules only" uses no LLM. "Rules + LLM" lets `llama3.2:3b` decide when the rules cannot resolve a target.
Robot runs (reaching the goal) are __ runs per command, same start pose each time.

| Command type | Example | N | Understood: rules only | Understood: rules + LLM | Reached goal | Notes |
|---|---|---|---|---|---|---|
| Named location | "go to the lawn" | 13 | 13 / 13 | 13 / 13 | __ / __ | |
| Named + filler words | "can you take me to the canteen please" | 6 | 0 / 6 | 5 / 6 | __ / __ | LLM fallback needed |
| Synonym | "take me to human resources" | 7 | 0 / 7 | 3 / 7 | __ / __ | LLM fallback needed |
| Coordinates | "go to x 1.0 y 2.0" | 6 | 5 / 6 | 5 / 6 | __ / __ | `x .. y ..` form not parsed |
| Multi-stop | "go to home then lawn" | 6 | 6 / 6 | 6 / 6 | __ / __ | |
| Invalid / unknown place | "go to the moon" | 7 | correctly rejected 7 / 7 | correctly rejected 7 / 7 | n/a | no goal sent |
| Chat (not navigation) | "what is your name" | 8 | 8 / 8 | 8 / 8 | n/a | |
| **All commands** | | 53 | **39 / 53 (74 %)** | **47 / 53 (89 %)** | | |

**2. Speech recognition** (N = 39 spoken commands per model, quiet room, GPU)

| Whisper model | Word error rate | Command understood | Transcription time (s) |
|---|---|---|---|
| `base` | 16.0 % | 20 / 39 | 0.03 |
| `small` | 13.9 % | 21 / 39 | 0.07 |
| `large-v3` | 10.2 % | 23 / 39 | 0.17 |

Word error rate is the share of reference words that are wrong. "Command understood" means the transcript resolved
to the right target (or, for invalid places, was rejected). Transcription time is the mean per clip, warm-up excluded.
By command type, plain named commands work well on every model (11 to 12 of 13, word error rate 2 to 6 %), and all
invalid places are rejected (7 / 7). The failures are almost all in filler-word commands (0 / 6 on every model)
and synonyms (1 / 7 on every model). The transcripts of those are close to perfect (filler word error rate
2.5 % on `large-v3`), so the cause is in the language-understanding rules, not in the speech recognition.

**3. End-to-end latency** (CPU vs GPU)

| Stage | CPU | GPU |
|---|---|---|
| Speech -> text (`large-v3`, mean of 39 clips) | 4.05 s (std 0.12) | 0.17 s (std 0.02) |
| Intent + location extraction (rules, median of 45) | 0.014 ms | 0.015 ms |
| LLM fallback (when used, `llama3.2:3b`, median of 7 warm calls) | 0.38 s | 0.10 s |
| LLM first call after start-up (model load, one call) | 17.95 s | 24.41 s |
| Goal accepted by Nav2 | __ s | __ s |
| **Utterance -> robot starts moving** | **__ s** | **__ s** |

**4. LLM comparison**

The only LLM measured so far is `llama3.2:3b`, on the 8 text commands that the rules could not resolve.
Response time is the median of the 7 calls after the model was loaded (CPU / GPU).

| Model | Fallback location accuracy | Median response time (CPU / GPU) | Peak RAM / VRAM |
|---|---|---|---|
| `llama3.2:3b` | 100 % (8 / 8) | 0.38 s / 0.10 s | __ GB |
| `llama3.1:8b` | __ % | __ s / __ s | __ GB |

Latency notes: the rule-based path is about 0.015 ms, effectively instant, so the LLM only matters for the commands
the rules cannot resolve. The first LLM call after starting the app or switching between CPU and GPU takes
18 to 24 s while the model loads, so it is kept out of the averages above. One GPU call took 3.8 s (median 0.10 s),
so GPU times can occasionally spike.

**Observed failure cases**

- **Filler words and synonyms.** The rules alone resolve 0 of 6 filler commands ("could you take me to the fire room")
  and 0 of 7 synonyms ("go to hr", "go to admin"). The LLM fallback fixes 8 of these 13.
- **Commands the LLM never saw.** Six cases fail even with the LLM because the rule guard did not pass them on:
  "could you take me to the fire room", "take me to human resources", "go to HR department",
  "go to director general office", "go to b o q" and "go to x 1.0 y 2.0".
- **Multi-stop by voice.** Multi-stop commands resolve 6 / 6 as text, but spoken ones reached 1 / 6 (`base`, `small`)
  and 4 / 6 (`large-v3`). Transcripts with a changed connector, such as "... Main Gate and go to warehouse" or
  "... Main Gate then, go to warehouse", were not resolved.
- **Speech recognition on short or low-energy clips** produced hallucinated text such as "Thank you" in earlier
  recordings, which is why the silence and hallucination checks in `voice_input.py` exist.

**Takeaways:** The rule-based language layer, not the speech recognition, limits understanding: adding the
LLM fallback raises text understanding from 74 % to 89 % at a cost of about 0.4 s per fallback call, while invalid
places are still rejected 7 / 7. For speech, `large-v3` on GPU is the most accurate (10.2 % word error rate) and still
transcribes a command in about 0.17 s. Sample sizes are small (6 to 13 commands per type), so differences of one
command should not be over-read.
