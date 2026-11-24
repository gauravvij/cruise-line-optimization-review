# Cruise Line — PR-Review Agent Optimization Report

**Date:** 2026-11-16
**Scope:** Quality / cost / latency of the PR-analysis stage (the "review" use).
**Method:** autoresearch-style controlled experiments against a ground-truth
bug-detection benchmark, then apply the winning configuration to the repo.
**Total measured OpenRouter spend:** **≈ $3.95** (account `usage_monthly`
$16.19 → $20.14; budget cap was $4.00).

---

## 1. Executive summary

| | Baseline | Optimized | Δ |
|---|---|---|---|
| **Detection F1** (micro) | **0.500** | **0.630** | **+0.130 (+26% relative)** |
| Precision | 0.857 | 0.850 | ~flat |
| Recall | 0.353 | 0.500 | **+0.147 (+42% relative)** |
| Cost / run (4-PR slice) | $0.7679 | **$0.0459** | **~16.7× cheaper** |
| Model | claude-opus-5-5 | claude-haiku-5-5 | — |
| Effort | high | medium | — |
| Prompt | repo `SYSTEM_PROMPT` | `v4_recall_anchor` | — |

**One-line recommendation:** default to **`claude-haiku-5-5` @ effort `medium`
with the `v4_recall_anchor` system prompt** — it detects ~26% more injected
defects at ~1/17th the cost per review. This has been applied to the repo.

> Caveat on magnitude: measured on a **4-PR / 34-defect slice** (see §3). The
> direction and the cost delta are robust; the exact F1 points are within the
> noise of a small sample and should be re-confirmed on a larger slice when
> budget allows.

---

## 2. What was optimized (and what was held fixed)

Cruise Line's analysis stage (`agent/analysis/analyzer.ts` → `sandbox/index.ts`
`/query`) runs a **Claude Agent SDK** loop:

- read-only tools `Read, Glob, Grep`,
- `maxTurns: 60`, `permissionMode: bypassPermissions`,
- **structured output** via `walkthroughJsonSchema`.

Two **configuration levers** were optimized (no code logic changed):

1. **Model + effort** — `config.claude.{model,effort}` (default
   `claude-opus-5-5` / `high`).
2. **System prompt** — `agent/analysis/prompt.ts` `SYSTEM_PROMPT`.

Everything else — the repo's real `SYSTEM_PROMPT`, `buildUserPrompt`, and
`walkthroughJsonSchema`; the tool set; the diff-truncation rule — was used
**unmodified** in the harness, so the comparison reflects a genuine change of
these two levers and not a re-implementation.

---

## 3. Evaluation harness

Built under `eval/` and pointed at the repo's real modules (imported directly via
`node --experimental-strip-types`, so the prompt/schema are the production ones):

| File | Role |
|---|---|
| `eval/prepare.py` + `eval/manifest.json` | Dataset prep — **20 PRs / 148 ground-truth issues** across 8 repos (Ghost, aspnetcore, cal.com, dify, firefox-ios, prefect, redis, tauri). Each PR verified: repo clones, PR head fetches, diff computes. |
| `eval/slice.json` | The **fixed 4-PR experiment slice** (34 defects) used *identically* by every experiment. |
| `eval/run_review.mjs` | Faithful runner: real prompt + real schema, agent loop through OpenRouter, swappable model/effort; captures `structured_output`, cost, latency, turns, `stop_reason`. |
| `eval/score.py` | Matcher + metrics: file-match + line-range overlap with a cheap **LLM-judge** confirmation; micro P/R/F1, schema validity, cost, latency. |
| `eval/summarize.py` | Aggregates runs into the E1/E2/E3 result JSONs. |

**Benchmark:** `Qodo/PR-Review-Bench` (HF) — real merged PRs with **line-level
injected defects** (`file_path`, `start_line`, `end_line`, `title`,
`description`, `rule_name`). Detection = did the reviewer flag the injected
defect at the right file/line.

**Matcher validation (false-negative safeguard):** the matcher was hand-checked
on ≥2 runs (redis#5, firefox-ios#1) with per-defect MATCH/miss lines confirmed
before any aggregate was trusted. All runs were schema-valid 4/4, so no
0%-score parser failures occurred.

**Why a 4-PR slice:** a single opus-5.5@high review costs ~$0.19–0.25, so a
20-PR opus baseline alone would have consumed ~$3.8 of the $4 cap. The slice was
fixed *before* running so baseline and every experiment share the exact same
inputs (apples-to-apples).

---

## 4. Experiments & results

### E1 — Model sweep (identical prompt/effort/slice)

| model | effort | F1 | P | R | cost $ | $/PR | mean lat (s) | turns (Σ) | schema |
|---|---|---|---|---|---|---|---|---|---|
| **anthropic/claude-haiku-5.5** | high | **0.531** | 0.867 | 0.382 | **0.0814** | 0.0203 | 120.5 | 54 | 4/4 |
| claude-opus-5-5 (baseline) | high | 0.500 | 0.857 | 0.353 | 0.7679 | 0.1920 | 85.4 | 24 | 4/4 |
| anthropic/claude-sonnet-5.5 | high | 0.468 | 0.846 | 0.324 | 0.3762 | 0.0940 | 35.0 | 19 | 4/4 |
| deepseek/deepseek-v4.1-flash-1017 | high | 0.468 | 0.846 | 0.324 | 0.2231 | 0.0558 | 202.0 | 201 | 4/4 |
| z-ai/glm-5.2 | high | 0.435 | 0.833 | 0.294 | 0.5228 | 0.1307 | 133.6 | 72 | 4/4 |
| qwen/qwen3-coder-next | high | 0.250 | 0.833 | 0.147 | 0.1405 | 0.0351 | 71.4 | 75 | 4/4 |

**Finding:** **haiku-5.5 beats the opus default** (F1 0.531 vs 0.500) at ~9.4×
lower cost. Sonnet is fastest (35 s) but no better than opus on quality. OSS
models (glm, deepseek, qwen3-coder) underperformed on this slice; deepseek was
also very slow (202 s, 201 turns).

### E2 — Effort sweep (haiku-5.5)

| effort | F1 | P | R | cost $ | mean lat (s) | turns (Σ) |
|---|---|---|---|---|---|---|
| low | 0.538 | 0.778 | 0.412 | 0.0204 | 44.4 | 19 |
| **medium** | **0.549** | 0.824 | 0.412 | 0.0329 | 60.3 | 24 |
| high | 0.531 | 0.867 | 0.382 | 0.0814 | 120.5 | 54 |

**Finding:** **medium** gives the best F1 at ~2.5× lower cost than high and 27%
lower latency. Higher effort mostly buys precision, not recall — and recall is
the binding constraint here.

### E3 — Prompt optimization (haiku-5.5, single appended section each)

Each variant = the repo's **real** `SYSTEM_PROMPT` plus one targeted section, so
a single prompt lever is isolated.

| variant | effort | F1 | P | R | ΔF1 vs same-model baseline prompt | cost $ |
|---|---|---|---|---|---|---|
| baseline prompt | high | 0.531 | 0.867 | 0.382 | — | 0.0814 |
| `v1_recall` | high | 0.586 | 0.708 | 0.500 | **+0.056** | 0.0764 |
| `v4_recall_anchor` | high | 0.597 | 0.739 | 0.500 | **+0.066** | 0.1011 |
| **`v4_recall_anchor`** | **medium** | **0.630** | 0.850 | 0.500 | **+0.099** | **0.0459** |

**Finding:** the prompt is the **biggest quality lever** — a recall-oriented +
line-anchor-oriented instruction lifted recall from 0.382 → 0.500 while holding
precision. Combined with effort=medium it reaches **F1 0.630** — the overall
winner (E4).

### E4 — Decisive combination (winner)

**haiku-5.5 + `v4_recall_anchor` + effort medium** on the fixed slice:

| PR | TP | FP | FN | P | R | F1 | cost $ |
|---|---|---|---|---|---|---|---|
| aspnetcore#2 | 3 | 2 | 6 | 0.600 | 0.333 | 0.429 | 0.00526 |
| firefox-ios#1 | 6 | 0 | 6 | 1.000 | 0.500 | 0.667 | 0.01288 |
| redis#5 | 3 | 1 | 3 | 0.750 | 0.500 | 0.600 | 0.01373 |
| tauri#10 | 5 | 0 | 2 | 1.000 | 0.714 | 0.833 | 0.01404 |
| **micro** | **17** | **3** | **17** | **0.850** | **0.500** | **0.630** | **0.0459** |

---

## 5. Applied change

Applied to `/home/azureuser/optimize-cruiseline/cruise-line` (branch `main`):

| File | Change | Verified |
|---|---|---|
| `agent/analysis/prompt.ts` | `SYSTEM_PROMPT` replaced with the `v4_recall_anchor` text | **byte-exact match** to `eval/prompts/v4_recall_anchor.txt` (14794 chars) |
| `agent/config.ts` | default `model` → `claude-haiku-5-5`; `effort` → `medium` | confirmed in source |
| `astropods.yml` | `CLAUDE_MODEL` default → `claude-haiku-5-5` | confirmed in source |

**Repo gates (no API cost):**
- `bun test agent/analysis/prompt.test.ts` → **3 pass / 0 fail**.
- `bunx tsc --noEmit` → **exit 0**.
- Full `bun test` → 214 pass / 3 fail; the 3 failures are **pre-existing**
  (reproduced on a pristine checkout: auth test-isolation + missing frontend
  module), not caused by this change.

---

## 6. Honest caveats & limitations

1. **Small slice.** All numbers are on **4 PRs / 34 defects**. F1 deltas of
   ±0.05 are within sampling noise; the **cost** delta (~17×) and the
   **recall-improves / precision-holds** direction are the robust results.
   Re-run on the full 20-PR manifest when budget allows.
2. **Budget-bound.** Task spend hit ≈$3.95 of the $4.00 cap, so two generated
   variants (`v2_severity`, `v3_anchor`) were **not run**, and the sweep could
   not be repeated for variance estimates / confidence intervals.
3. **`maxTurns` not enforced in the harness.** `eval/run_review.mjs` observed
   `num_turns` exceeding the configured `--max-turns` (e.g. 97 vs 60), so turn
   counts and latency on some PRs are **not bounded** as intended. This inflates
   latency/cost figures (notably deepseek's 202 s / 201 turns). The CLI enforces
   `maxTurns` correctly; this is a **harness** issue. Rankings are unaffected
   because every config ran under the same harness, but treat latency numbers as
   approximate.
4. **OpenRouter routing.** Both baseline and experiments were routed through
   OpenRouter's Anthropic-compatible endpoint (verified to drive the full agent
   loop incl. tool use + json_schema). Routing is applied identically to every
   config, so relative comparisons are valid; absolute costs may differ slightly
   from direct Anthropic billing.
5. **Single run per config** (no repeats) — no error bars.

---

## 7. Recommendations

- **Ship the winner** (done): haiku-5.5 @ medium + `v4_recall_anchor`. Best
  quality-per-dollar by a wide margin.
- **Re-confirm on the full 20-PR manifest** (~$1–2 at haiku pricing) to tighten
  the F1 estimate and add variance.
- **Run the two untested prompt variants** (`v2_severity`, `v3_anchor`) — small
  budget, potential further recall/precision gain.
- **Fix the harness `maxTurns` enforcement** before any future latency-sensitive
  benchmarking.
- **Keep Opus selectable** in Settings for users who want maximum depth; the
  repo default is the cost/quality-optimal config.

---

### Artifacts
`eval/{prepare.py, run_review.mjs, score.py, summarize.py, manifest.json, slice.json, apply_winner.mjs}`,
`eval/results/{baseline,models,effort,prompts}.json` + `pareto.md`,
`eval/results/raw/*` and `eval/results/scored/*` (per-run evidence),
`eval/prompts/*.txt` (variants), and the applied diff in `cruise-line/`.

## Validation round 2 (unseen PRs, fixed harness)

**Status: complete (resumed round + follow-up Opus holdout + retry round, new key).** Record: `eval/results/validation_round2.json` (status `complete`).

Resumed-round spend (new key `sk-or-v1-fa8...7b3`, anchor `usage_monthly` 0.0): **$0.6068 of $4.00**. Per-step: cap check $0.0055 → noise1 $0.0699 → noise2 $0.1246 → holdout baseline $0.3428 → holdout v4 $0.6042 → final $0.6068. Prior-session spend on the old key is not counted against this cap.

Follow-up Opus holdout spend (anchor `usage_monthly` $0.6068, additional $4.00 cap): **$2.8318 of $4.00** (remaining $1.1682). Per-step: opus holdout run → $3.0893 → diagnostic test (dify#11) → $3.3331 → scoring with LLM judge → $3.4353 → final reading $3.4386. That run was partial (8/16 valid; 8 billing 402 failures) — see below.

Retry-round spend (credits added to same key `...7b3`, anchor `usage_monthly` $3.438574282, $4.00 cap): **$2.0548 of $4.00**. Per-step: anchor $3.4386 → retry smoke firefox-ios#12 $3.6524 → retry remaining 6 PRs $5.4885 → scoring full16 + retry (LLM judge) $5.4922 → final $5.4933. Total retry spend = $5.4933 − $3.4386 = $2.0548.

### Harness fixes and verification
- **Turn cap (real CLI, verified):** tag `r2_capcheck`, haiku @ medium + v4 on redis#5 with `--max-turns 3`: `num_turns_counted=3`, `turn_check_ok=true`, CLI stopped with `error_max_turns`. The CLI's own `num_turns=4` confirms the historical +1 offset (`n_tool_calls = num_turns - 1`). Issue `run-review-maxturns-not-enforced` is **closed**. Fake-CLI test `eval/test_suite/cap_test.sh` remains 6/6.
- **Per-PR cost:** `usage_monthly` key-delta around each PR at concurrency 1, settle-polling, `cost_flag` on zero/unsettled. Retry round: 4 PRs flagged `key_delta_unsettled_after_30s` (firefox-ios#13, prefect#5, prefect#10, redis#6); their spend settled late and is captured in tauri#1's key-delta ($1.2742). Whole-run usage delta is authoritative for total spend.
- **Provenance:** every record carries `harness_version`, prompt sha256, cruise-line git HEAD, PR list and tag. `--prompt-file` required; baseline sha `735dd815`, v4 sha `34ab4b82`. Original harness `877ac98b39664866`; retry harness `0abca51995d3f7cf` after adding `CLAUDE_CODE_MAX_OUTPUT_TOKENS=16000` to the CLI env in `eval/run_review.mjs`. Merged full-16 set scored with `--allow-harness-mismatch` (documented in `eval/results/validation_round2.json`).

### Holdout pre-flight
16 unseen PRs, 114 ground-truth issues, no overlap with the 4-PR slice, no duplicates. All 8 repos cloned locally (Ghost, cal.com, dify, prefect cloned this round); `prepare.py --verify`: 20/20 OK (clone + PR head + non-empty diff).

### Noise check (haiku @ medium + v4, 4-PR slice)
Three identical-config runs: prior round 0.6296, `r2_noise1` 0.4706, `r2_noise2` 0.5556. **Mean 0.5519, range [0.4706, 0.6296]** (spread 0.159). The low outlier had one schema-invalid PR (tauri#10, F1 0), which explains much of the spread. Judge failures: 0 in all runs.

### Holdout results (16 PRs, 114 GT issues, concurrency 1, LLM judge on)
| Run | Config | Micro P/R/F1 | TP/FP/FN | Schema-valid | Cost |
|---|---|---|---|---|---|
| `r2_holdout_haiku_baseline` | haiku @ medium + ORIGINAL baseline prompt | 0.662 / 0.447 / **0.534** | 51/26/63 | 15/16 | $0.2085 |
| `r2_holdout_haiku_v4` | haiku @ medium + v4_recall_anchor | 0.604 / 0.535 / **0.567** | 61/40/53 | 16/16 | $0.2150 |
| `r2_holdout_opus_baseline_full16` | opus @ high + ORIGINAL baseline prompt | 0.757 / 0.465 / **0.576** | 53/17/61 | **16/16** | $4.4253 (sum key-delta; see cost note) |

v4 is directionally ahead of haiku-baseline (+0.033 F1) at essentially equal cost, driven by higher recall (0.535 vs 0.447) with lower precision (0.604 vs 0.662). Opus full-16 is directionally ahead of both haiku runs on F1 (0.576 vs 0.567/0.534) at much higher cost (~$0.28/PR vs ~$0.013/PR).

### Opus holdout history (partial → complete)
Original tag `r2_holdout_opus_baseline` (opus-5.5 @ high + ORIGINAL baseline prompt, same 16 PRs, concurrency 1): **8/16 schema-valid, F1 0.320** (tp24 fp12 fn90, $2.7227). PRs 9–16 (dify#11, firefox-ios#12, firefox-ios#13, prefect#5, prefect#10, redis#6, tauri#1, tauri#9) failed with OpenRouter **402** errors. Root cause: the CLI requests `max_tokens=128000`, and OpenRouter reserves `128000 × $0.00002 = $2.56` against remaining balance before each request; once balance fell below $2.56, requests were rejected. This was a billing/reservation failure, not a quality failure.

**Fix applied in retry round:** `eval/run_review.mjs` now sets `CLAUDE_CODE_MAX_OUTPUT_TOKENS=16000` in the CLI env (default, overridable). Diagnostic `r2_opus_test_dify11` (dify#11) was already schema-valid (F1 0.667, $0.2438) and was reused, not re-run. Retry tag `r2_holdout_opus_baseline_retry` re-ran only the 7 remaining PRs (firefox-ios#12, firefox-ios#13, prefect#5, prefect#10, redis#6, tauri#1, tauri#9): **7/7 schema-valid, F1 0.684** (tp26 fp5 fn19, sum key-delta $1.8191; whole-run delta $2.0500 including late-settling costs). Merged full-16 set (`r2_holdout_opus_baseline_full16` = 8 original valid + dify#11 diagnostic + 7 retry) scored with `eval/score.py` including the LLM judge (same judge settings; judge failures 0, 138 pairs): **16/16 schema-valid, micro F1 0.576** (P 0.757 / R 0.465, tp53 fp17 fn61). Scored JSON: `eval/results/scored/r2_holdout_opus_baseline_full16.json`. Per-PR key-delta costs are in `eval/results/validation_round2.json` (`retry_round.full16_opus.per_pr_costs`); 4 retry PRs show $0 with `key_delta_unsettled_after_30s` because their spend settled late into tauri#1's delta — total spend is therefore taken from whole-run usage deltas, not the sum of per-PR deltas.

### Statistics (full 16, paired bootstrap)
Paired bootstrap over the 16 PRs (resample PRs with replacement, recompute micro F1 from summed TP/FP/FN; 10,000 resamples, seed 42; full output in `eval/results/bootstrap_opus_full16.json`):
- Opus-baseline micro F1: 0.578 mean, **95% CI [0.471, 0.678]** (observed 0.576)
- **Paired difference (haiku-v4 − opus-baseline): −0.009, 95% CI [−0.059, +0.051] — includes zero. No winner declared.**
- Paired difference (haiku-v4 − haiku-baseline): +0.033, 95% CI [−0.035, +0.116] — includes zero.

### Verdict on the original claim
**Inconclusive (not supported).** The claim "haiku-5.5 @ medium + v4 beats opus-5.5 @ high on quality" is **not supported** on complete 16/16 data: opus-baseline F1 0.576 vs haiku-v4 0.567, paired difference −0.009 with 95% CI [−0.059, +0.051] including zero. The haiku prompt effect alone (v4 vs baseline, +0.033 CI [−0.035, +0.116]) is also not statistically established. What this round does establish: on unseen PRs, opus @ high + baseline and haiku @ medium + v4 are statistically indistinguishable on quality, while haiku is ~20× cheaper per PR; v4 is directionally ahead of the baseline prompt on haiku at equal cost; the turn cap is verified on the real CLI; and the opus 402 failure mode is fixed by `CLAUDE_CODE_MAX_OUTPUT_TOKENS=16000`.

### Cleanup (prior session, unchanged)
- `cruise-line/agent/config.ts` and `astropods.yml` claim only the measured cost gap; quality marked unestablished.
- `bun test agent/analysis/prompt.test.ts`: exit 0 (3 pass). `bunx tsc --noEmit`: exit 0.

## Validation round 3 (Haiku phase, 48 PRs)

**Status: complete.** Record: `eval/results/validation_round3.json` (top-level `winner_declared=true`; see `final_verdict`). All 48 PRs complete across 5 arms (see closing section below); the Haiku-phase status line above is superseded by the final comparison note.

Holdout: `eval/holdout48.json` pre-registered before runs (48 PRs, 6/repo x 8 repos, 261 GT issues, seed 42, stratified by diff size/defect density).

| Run | Config | Micro P/R/F1 | TP/FP/FN | Schema-valid | Cost (scored sum) |
|---|---|---|---|---|---|
| h3_haiku_baseline | haiku-5.5 @ medium + baseline_original | 0.647/0.556/0.598 | 145/79/116 | 44/48 | $0.86826 |
| h3_haiku_v4 | haiku-5.5 @ medium + v4_recall_anchor | 0.599/0.640/0.619 | 167/112/94 | 47/48 | $0.87866 |
| h3_haiku_baseline_r2 | repeat of baseline | 0.621/0.559/0.589 | 146/89/115 | 45/48 | $0.79143 |
| h3_haiku_v4_r2 | repeat of v4 | 0.585/0.609/0.597 | 159/113/102 | 47/48 | $0.93261 |

Paired bootstrap (10k resamples, seed 42, `eval/results/bootstrap_round3.json`): baseline F1 0.5986 [0.5342,0.6597]; v4 F1 0.6189 [0.5735,0.6642]; paired C-B +0.0203, 95% CI [-0.0274,+0.0725] — includes zero, so **no prompt winner declared**. Per-repo: cal.com +0.1766 [0.0437,0.3765] excludes zero; per-diff-size: large +0.0767 [0.0038,0.1664] excludes zero; all other strata include zero.

Spend: anchor usage_monthly $5.495648601, current $9.141754477, round delta ~$3.6461 of $4.00 Haiku cap (under cap). Harness hashes: run_review.mjs 932aab08, score.py 0709e84e, baseline 735dd815, v4 34ab4b82.


### Interim note — Opus phase, first 32 PRs (partial, billing-blocked)

**Status: partial_opus_32.** Record: `eval/results/validation_round3.json` (opus section, `runs_executed=1`, `zero_opus_runs=false`). Remaining 16 PRs NOT run in this tranche — STOP pending user go-ahead.

Config: `anthropic/claude-opus-5.5` @ high + `eval/prompts/baseline_original.txt` (round-2 Opus comparison arm), harness v2 `eval/run_review.mjs`, concurrency 1, tag `h3_opus_baseline`. Subset: first 4 PRs per repo from `eval/holdout48.json` (32 PRs, 174 GT issues): Ghost#1-4, aspnetcore#1,5,6,7, cal.com#1-4, dify#1,2,4,8, firefox-ios#4-7, prefect#1,2,3,7, redis#1,3,4,7, tauri#2,5,6,7. Manifest was swapped to holdout48 (48 PRs) for the run and restored byte-identical to `eval/manifest.json.bak_round2` (20 PRs) after.

| Scope | Micro P/R/F1 | TP/FP/FN | Schema-valid | Cost |
|---|---|---|---|---|
| h3_opus_baseline (32 attempted) | 0.744/0.368/0.492 | 64/22/110 | 20/32 | $7.68183 scored sum; $7.72604 whole-run delta |
| h3_opus_baseline valid-20 subset (117 GT) | 0.744/0.547/0.631 | 64/22/53 | 20/20 | $7.04107 |

Scored with `eval/score.py` + LLM judge `deepseek/deepseek-v4.1-flash-1017` (18 calls, 152 pairs, 0 failures, judge key-delta $0.003983). Scored file: `eval/results/scored/h3_opus_baseline.json`. Raw: 32 records in `eval/results/raw/h3_opus_baseline__*`.

**Billing blocker (not a quality failure):** 12 PRs failed with OpenRouter 402 — prefect#1 (ran 14 turns, then 402), prefect#2, prefect#3, prefect#7, redis#1, redis#3, redis#4, redis#7, tauri#2, tauri#5, tauri#6, tauri#7. Error: "This request requires more credits, or fewer max_tokens. You requested up to 16000 tokens, but can only afford 15752 / 14031 / 13356." Key limit is $20; anchor `usage_monthly` $9.141754477, after run $16.867797877, remaining ~$3.13. At ~$0.24-0.38/PR for Opus, the remaining 12 of this tranche (~$4.6) and the remaining 16 (~$6) cannot be reserved under the current limit. `CLAUDE_CODE_MAX_OUTPUT_TOKENS=16000` verified in `eval/run_review.mjs` line 247 (CLI env default). To complete: raise the key limit (e.g. to $30+) and re-run only the 12 failed PRs under a new tag, then merge/score; do not re-run the 20 valid PRs.

Spend: Opus tranche anchor $9.141754477, whole-run delta $7.72604 of $10.00 budget (under budget, but key-limit blocked). No Opus runs for the remaining 16 PRs were executed.

### Interim note — Opus retry of 12 billing-failed PRs (32-PR set complete)

**Status: partial_opus_32_complete.** Record: `eval/results/validation_round3.json` (opus section, `runs_executed=2`, `zero_opus_runs=false`). Remaining 16 PRs NOT run — STOP pending user go-ahead.

Key limit raised $20 → $35 before retry (anchor `usage_monthly` $16.873830359, remaining $18.126169641). `CLAUDE_CODE_MAX_OUTPUT_TOKENS=16000` exported and verified in `eval/run_review.mjs` line 247. Manifest swapped to holdout48 (48 PRs) for the run and restored byte-identical to `eval/manifest.json.bak_round2` (20 PRs, `cmp` exit 0) after.

Retry run: tag `h3_opus_baseline_retry12`, `anthropic/claude-opus-5.5` @ high + `eval/prompts/baseline_original.txt`, harness v2, concurrency 1, `TASK_START_SPEND=16.873830359`, `BUDGET_USD=5.0`, on 12 PRs only (prefect#1,#2,#3,#7, redis#1,#3,#4,#7, tauri#2,#5,#6,#7). Result: **12/12 schema-valid**, 62 findings, no 402 failures, no cost flags. Whole-run delta $5.12954 (spend_before $16.873830359 → spend_after $22.003368159) — $0.12954 over the $5.00 tranche budget because the budget guard checks before each PR and tauri#7 completed over cap (tauri#5 was the expensive PR at $0.92392 key-delta).

| Scope | Micro P/R/F1 | TP/FP/FN | Schema-valid | Cost |
|---|---|---|---|---|
| h3_opus_baseline_retry12 (12 PRs, 57 GT) | 0.750/0.632/0.686 | 36/12/21 | 12/12 | $4.97224 scored sum; $5.12954 whole-run delta |
| h3_opus_baseline_full32 merged (32 PRs, 174 GT) | 0.746/0.575/0.649 | 100/34/74 | 32/32 | $12.01331 scored sum |

Merged scoring follows the round-2 full16 precedent (`validation_round2.json` `retry_round.full16_opus`): valid-20 records from `h3_opus_baseline` plus 12 retry records from `h3_opus_baseline_retry12` copied to tag `h3_opus_baseline_full32` (32 raw records + summary in `eval/results/raw/h3_opus_baseline_full32__*`) and scored with `eval/score.py` + LLM judge `deepseek/deepseek-v4.1-flash-1017`. Both source tags share harness `0abca51995d3f7cf`, so `--allow-harness-mismatch` was not needed (documented in the record). Merged judge: 30 calls, 221 pairs, 0 failures. Scored files: `eval/results/scored/h3_opus_baseline_retry12.json`, `eval/results/scored/h3_opus_baseline_full32.json`. Merged cost $12.01331 = valid-20 scored $7.04107 + retry scored $4.97224 (excludes $0.640757 of failed-PR key-delta in the original run that produced no findings). Final anchor after scoring: $22.108042159, key remaining $12.890983292 of $35.

No Opus runs were executed for the remaining 16 PRs (Ghost#11,#12, aspnetcore#8,#10, cal.com#7,#9, dify#12,#13, firefox-ios#9,#10, prefect#9,#12, redis#8,#9, tauri#8,#11) — 0 Opus raw records for them. STOP here pending user go-ahead.

### Final note — Opus final 16 PRs (round 3 complete, 48/48)

**Status: complete.** Record: `eval/results/validation_round3.json` (opus section, `runs_executed=3`, `zero_opus_runs=false`). All 48 holdout PRs now have Opus records.

Config identical to prior Opus tranches: `anthropic/claude-opus-5.5` @ high + `eval/prompts/baseline_original.txt`, harness v2 `eval/run_review.mjs`, concurrency 1, tag `h3_opus_baseline_final16`. `CLAUDE_CODE_MAX_OUTPUT_TOKENS=16000` verified in `eval/run_review.mjs` line 247. Fresh anchor `usage_monthly` $22.119357571 (key limit $35, remaining $12.880642429). Manifest swapped to holdout48 (48 PRs) for the run and restored byte-identical to `eval/manifest.json.bak_round2` (20 PRs, `cmp` exit 0) after.

Final-16 run: 16 PRs only (Ghost#11,#12, aspnetcore#8,#10, cal.com#7,#9, dify#12,#13, firefox-ios#9,#10, prefect#9,#12, redis#8,#9, tauri#8,#11) via `--prs` filter, `TASK_START_SPEND=22.119357571`, `BUDGET_USD=10.0`. Result: **16/16 schema-valid**, 86 findings, no 402 failures, 0 cost flags, 0 turn-cap hits. Whole-run delta $5.0085324 (spend_before $22.119357571 → spend_after $27.127889971), under the $10.00 tranche budget.

| Scope | Micro P/R/F1 | TP/FP/FN | Schema-valid | Cost |
|---|---|---|---|---|
| h3_opus_baseline_final16 (16 PRs, 87 GT) | 0.754/0.598/0.667 | 52/17/35 | 16/16 | $4.82690 scored sum; $5.00853 whole-run delta |
| h3_opus_baseline_full48 merged (48 PRs, 261 GT) | 0.754/0.586/0.660 | 153/50/108 | 48/48 | $16.84021 scored sum |

Merged scoring follows the round-2 full16 / round-3 full32 precedent: 32 records from `h3_opus_baseline_full32` (valid-20 `h3_opus_baseline` + `h3_opus_baseline_retry12`) plus 16 records from `h3_opus_baseline_final16` copied to tag `h3_opus_baseline_full48` (48 raw records + regenerated summary in `eval/results/raw/h3_opus_baseline_full48__*`) and scored with `eval/score.py` + LLM judge `deepseek/deepseek-v4.1-flash-1017`. Same harness `0abca51995d3f7cf` across all tranches, so `--allow-harness-mismatch` was not needed. Merged judge: 46 calls, 359 pairs, 0 failures. Scored files: `eval/results/scored/h3_opus_baseline_final16.json`, `eval/results/scored/h3_opus_baseline_full48.json`. Merged cost $16.84021 = full32 scored $12.01331 + final16 scored $4.82690 (excludes $0.640757 of failed-PR key-delta in the original run that produced no findings). Final anchor after scoring: $27.273941197, key remaining $7.726058803 of $35.

Per-tranche spend ledger: original anchor $9.141754477 → $16.867797877 (delta $7.72604, budget $10.00); retry anchor $16.873830359 → $22.003368159 (delta $5.12954, budget $5.00, $0.12954 over — budget guard checks before each PR); final16 anchor $22.119357571 → $27.127889971 (delta $5.00853, budget $10.00).

**CI status / winner (superseded — see final comparison note below):** At the time of the final-16 note, no paired bootstrap CI had yet been computed for Opus vs Haiku; the existing bootstrap (`eval/results/bootstrap_round3.json`) covered the Haiku prompt comparison only (paired C-B +0.0203, 95% CI [-0.0274,+0.0725], includes zero, `winner_declared_haiku_prompt=false`). The later final comparison note computes the Opus-vs-Haiku paired CIs (`eval/results/bootstrap_round3_opus.json`), both excluding zero, and declares the Opus quality winner (`winner_declared=true`). This paragraph is retained only as tranche history and does not reflect the final verdict.

### Final comparison note — full-48 analysis (round 3 complete, no paid runs)

**Status: complete.** Analysis only on existing scored records (48 PRs, 261 GT issues, judge `deepseek/deepseek-v4.1-flash-1017`, 0 failures across all arms). New script `eval/results/bootstrap_round3_opus.py` (same method as `bootstrap_round3.py`: paired bootstrap over 48 PRs, resample with replacement, recompute micro F1 from summed tp/fp/fn, 10000 resamples, seed 42) → `eval/results/bootstrap_round3_opus.json`. Record updated: `eval/results/validation_round3.json` (`final_verdict`, opus statistics, `winner_declared` per CI rule).

| Arm | Micro P/R/F1 | TP/FP/FN | Schema-valid | Cost (scored sum) | Cost/PR | Cost/TP |
|---|---|---|---|---|---|---|
| h3_haiku_baseline | 0.647/0.556/0.598 | 145/79/116 | 44/48 | $0.86826 | $0.01809 | $0.00599 |
| h3_haiku_v4 | 0.599/0.640/0.619 | 167/112/94 | 47/48 | $0.87866 | $0.01831 | $0.00526 |
| h3_haiku_baseline_r2 | 0.621/0.559/0.589 | 146/89/115 | 45/48 | $0.79143 | $0.01649 | $0.00542 |
| h3_haiku_v4_r2 | 0.585/0.609/0.597 | 159/113/102 | 47/48 | $0.93261 | $0.01943 | $0.00587 |
| h3_opus_baseline_full48 | 0.754/0.586/0.660 | 153/50/108 | 48/48 | $16.84021 | $0.35084 | $0.11007 |

**CIs (paired bootstrap, 10k, seed 42):** Opus F1 0.6595, mean 0.6600, 95% CI [0.6041, 0.7137]. Opus − haiku-baseline: observed +0.0615, mean +0.0614, 95% CI [0.0054, 0.1209], includes_zero=false. Opus − haiku-v4: observed +0.0410, mean +0.0411, 95% CI [0.0008, 0.0865], includes_zero=false. Haiku v4 − baseline (existing `bootstrap_round3.json`): +0.0203, 95% CI [-0.0274, +0.0725], includes_zero=true.

**Per-repo / per-diff-size (opus vs haiku-v4):** only redis excludes zero (+0.1538 [0.0531, 0.2657]); all other repos include zero. Only medium diffs exclude zero (+0.0652 [0.0111, 0.1249]); small (+0.0155 [-0.0500, 0.0857]) and large (+0.0240 [-0.0403, 0.1049]) include zero.

**Verdict:** A quality winner **is supported**: `h3_opus_baseline_full48` (opus-5.5 @ high + baseline_original) beats both haiku arms on micro F1 with both paired CIs excluding zero — though the opus-vs-v4 lower bound (+0.0008) is marginal, so treat the margin over v4 as small. No haiku prompt winner is supported (v4 vs baseline CI includes zero; r2 repeats F1 0.5887/0.5966 confirm instability). **Cost/quality tradeoff:** opus is ~19× haiku cost per PR ($0.351 vs ~$0.018) and ~19× per TP ($0.110 vs ~$0.005–0.006); haiku-v4 yields the most TPs (167) at haiku cost. Choose opus for maximum quality, haiku for cost efficiency.

### Closing section — Round-3 summary and Haiku-improvement analysis (complete, no paid runs)

**Round-3 summary.** Holdout: 48 PRs (`eval/holdout48.json`, 6/repo x 8 repos), 261 GT issues, judge `deepseek/deepseek-v4.1-flash-1017` with 0 failures across all arms. Five arms, all scored on the same 48 PRs:

| Arm | Config | Micro P/R/F1 | TP/FP/FN | Schema-valid | Cost (scored sum) | Cost/PR | Cost/TP |
|---|---|---|---|---|---|---|---|
| h3_haiku_baseline | haiku-5.5 @ medium + baseline_original | 0.647/0.556/0.598 | 145/79/116 | 44/48 | $0.86826 | $0.01809 | $0.00599 |
| h3_haiku_v4 | haiku-5.5 @ medium + v4_recall_anchor | 0.599/0.640/0.619 | 167/112/94 | 47/48 | $0.87866 | $0.01831 | $0.00526 |
| h3_haiku_baseline_r2 | repeat of baseline | 0.621/0.559/0.589 | 146/89/115 | 45/48 | $0.79143 | $0.01649 | $0.00542 |
| h3_haiku_v4_r2 | repeat of v4 | 0.585/0.609/0.597 | 159/113/102 | 47/48 | $0.93261 | $0.01943 | $0.00587 |
| h3_opus_baseline_full48 | opus-5.5 @ high + baseline_original | 0.754/0.586/0.660 | 153/50/108 | 48/48 | $16.84021 | $0.35084 | $0.11007 |

**CIs (paired bootstrap, 10k resamples, seed 42; `eval/results/bootstrap_round3.json` and `eval/results/bootstrap_round3_opus.json`):** Opus F1 0.6595, 95% CI [0.6041, 0.7137]. Opus - haiku-baseline: +0.0615, 95% CI [0.0054, 0.1209], excludes zero. Opus - haiku-v4: +0.0410, 95% CI [0.0008, 0.0865], excludes zero (marginal lower bound). Haiku v4 - baseline: +0.0203, 95% CI [-0.0274, +0.0725], includes zero.

**Cost/quality tradeoff (~19x):** Opus costs ~19x Haiku per PR ($0.351 vs ~$0.018) and ~19x per TP ($0.110 vs ~$0.005-0.006) for +0.041 to +0.062 F1. Haiku-v4 yields the most TPs (167) at Haiku cost.

**Verdict:** `winner_declared=true` — Opus (opus-5.5 @ high + baseline_original) is the quality winner, supported by both paired CIs excluding zero. `winner_declared_haiku_prompt=false` — no Haiku prompt winner is supported (v4-vs-baseline CI includes zero; r2 repeats 0.5887/0.5966 confirm instability).

**Haiku-improvement analysis — could prompt/tool/effort config close the gap to Opus 0.6595?**

Evidence from existing records (no new runs):

- **Prompt (`eval/results/prompts.json`, 4-PR slice, haiku-5.5 @ high):** baseline F1 0.5306; v1_recall 0.5862 (+0.056); v4_recall_anchor 0.5965 (+0.066). Prompt engineering helps Haiku on the slice, but the best tested prompt (v4, 0.5965) remains well below Opus full-48 0.6595, and on the full 48 PRs the v4-vs-baseline gain (+0.0203) is not statistically supported (CI includes zero) with unstable r2 repeats (0.5887/0.5966).
- **Effort (`eval/results/effort.json`, 4-PR slice, haiku-5.5):** low 0.5385, medium 0.549, high 0.5306 — effort does not help; higher effort does not improve F1, so effort config cannot close the gap.
- **Model (`eval/results/models.json`, 4-PR slice, @ high, baseline prompt):** haiku-5.5 0.5306 was best among the 6 models compared on that slice (opus-5.5 0.500, sonnet-5.5 0.4681, deepseek flash 0.4681, glm-5.2 0.4348, qwen3-coder 0.250) — but that slice ranking does not transfer to the 48-PR holdout, where opus-5.5 @ high + baseline reaches 0.6595 vs haiku best 0.6185.
- **Untested prompts:** `v2_severity` and `v3_anchor` were never run (see prompt-sweep notes above). They are the only untested prompt levers.
- **Harness (`eval/run_review.mjs`):** `READ_ONLY_TOOLS` = Read/Glob/Grep (line 71), `maxTurns` 60 (line 72), Haiku arms at effort medium. Tool set is already read-only and fixed across arms; raising `maxTurns` above 60 is the only remaining harness lever, and no arm hit the turn cap in round 3 (0 turn-cap hits for Opus full-48), so expected gain is small.

**Conclusion:** No tested Haiku config reaches Opus 0.6595. The gap is model capability, not prompt/effort: prompt gains are small and statistically unsupported at 48 PRs, effort is flat-to-negative, and the harness tool/turn settings are already shared with the Opus arm. Untested `v2_severity`/`v3_anchor` and higher `maxTurns` are the only remaining levers, but expected gain is small per the evidence above (best prompt gain +0.066 on a 4-PR slice, +0.0203 and non-significant at 48 PRs; effort flat; no turn-cap hits). Closing a +0.041 to +0.062 F1 gap would require a model change, not config tuning.
