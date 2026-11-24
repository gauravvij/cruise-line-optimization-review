# E1 — Model sweep (fixed 4-PR slice, identical prompt/effort)

| model | effort | F1 | P | R | cost $ | $/PR | $/TP | mean lat (s) | turns(sum) | schema | pareto |
|---|---|---|---|---|---|---|---|---|---|---|---|
| anthropic/claude-haiku-5.5 | high | **0.531** | 0.867 | 0.382 | 0.0814 | 0.0203 | 0.0063 | 120.5 | 54 | 4/4 | YES |
| claude-opus-5-5 | high | **0.500** | 0.857 | 0.353 | 0.7679 | 0.1920 | 0.0640 | 85.4 | 24 | 4/4 | YES |
| anthropic/claude-sonnet-5.5 | high | **0.468** | 0.846 | 0.324 | 0.3762 | 0.0940 | 0.0342 | 35.0 | 19 | 4/4 | YES |
| deepseek/deepseek-v4.1-flash-1017 | high | **0.468** | 0.846 | 0.324 | 0.2231 | 0.0558 | 0.0203 | 202.0 | 201 | 4/4 | no |
| z-ai/glm-5.2 | high | **0.435** | 0.833 | 0.294 | 0.5228 | 0.1307 | 0.0523 | 133.6 | 72 | 4/4 | no |
| qwen/qwen3-coder-next | high | **0.250** | 0.833 | 0.147 | 0.1405 | 0.0351 | 0.0281 | 71.4 | 75 | 4/4 | YES |

`turns(sum)` is the SUM of num_turns across the 4 PRs, not a mean.

## E2 — Effort sweep (haiku-5.5)

| effort | F1 | P | R | cost $ | mean lat (s) | turns(sum) |
|---|---|---|---|---|---|---|
| low | **0.538** | 0.778 | 0.412 | 0.0204 | 44.4 | 19 |
| medium | **0.549** | 0.824 | 0.412 | 0.0329 | 60.3 | 24 |
| high | **0.531** | 0.867 | 0.382 | 0.0814 | 120.5 | 54 |

## E3 — Prompt variants (haiku-5.5)

| variant | effort | F1 | P | R | ΔF1 vs same-model baseline prompt | cost $ |
|---|---|---|---|---|---|---|
| baseline prompt | high | 0.531 | 0.867 | 0.382 | — | 0.0814 |
| eval/prompts/v1_recall.txt | high | **0.586** | 0.708 | 0.500 | +0.056 | 0.0764 |
| eval/prompts/v4_recall_anchor.txt | high | **0.597** | 0.739 | 0.500 | +0.066 | 0.1011 |
| eval/prompts/v4_recall_anchor.txt | medium | **0.630** | 0.850 | 0.500 | +0.099 | 0.0459 |
