# Cruise Line — PR-Review Agent Optimization (Review Repo)

This repository is a **review / evidence copy** of the Cruise Line
(`cruise-line/`, upstream: astropods/cruise-line) PR-review agent after a
controlled optimization of its analysis stage, together with the full
evaluation harness and results that justify the change.

**Full report:** [`OPTIMIZATION_REPORT.md`](OPTIMIZATION_REPORT.md) — every
number below is taken from it and from the machine-readable records in
`eval/results/` (`validation_round2.json`, `validation_round3.json`,
`bootstrap_*.json`, `models.json`, `effort.json`, `prompts.json`).

> No paid API runs were made to produce this push. All results are from
> previously executed, recorded runs.

---

## 1. What was optimized

Cruise Line's review stage (`cruise-line/agent/analysis/analyzer.ts` →
`sandbox/index.ts` `/query`) runs a Claude Agent SDK loop with read-only
tools (`Read, Glob, Grep`), `maxTurns: 60`, and structured output via
`walkthroughJsonSchema`. Only **two configuration levers** were changed —
no agent logic, tool set, or schema was altered:

1. **Model + effort** — `config.claude.{model, effort}`
2. **System prompt** — `SYSTEM_PROMPT` in `agent/analysis/prompt.ts`

Everything else (real prompt base, `buildUserPrompt`, schema, diff
truncation) was used **unmodified** in the harness, so comparisons reflect
a genuine change of these two levers, not a re-implementation.

---

## 2. Results — performance and cost

### 2.1 Original 4-PR slice (model / effort / prompt sweeps)

Fixed slice: 4 PRs / 34 injected defects (`eval/slice.json`), identical
inputs for every config. Baseline = `claude-opus-5-5` @ `high` + original
prompt.

| | Baseline (Opus @ high) | Optimized (Haiku @ medium + v4 prompt) | Δ |
|---|---|---|---|
| **Detection F1 (micro)** | **0.500** | **0.630** | **+0.130 (+26% relative)** |
| Precision | 0.857 | 0.850 | ~flat |
| Recall | 0.353 | 0.500 | **+0.147 (+42% relative)** |
| Cost / run (4-PR slice) | $0.7679 | **$0.0459** | **~16.7× cheaper** |
| Model / effort / prompt | opus-5-5 / high / original | haiku-5-5 / medium / `v4_recall_anchor` | — |

Sweep detail (same slice):

| Sweep | Best config | F1 | Cost |
|---|---|---|---|
| E1 model (baseline prompt, high) | **haiku-5.5** | 0.531 (vs Opus 0.500, Sonnet 0.468, DeepSeek flash 0.468, GLM 0.435, Qwen3-coder 0.250) | $0.0814 (~9.4× cheaper than Opus $0.7679) |
| E2 effort (Haiku) | **medium** | 0.549 (low 0.538, high 0.531) | $0.0329 (~2.5× cheaper than high) |
| E3 prompt (Haiku @ high) | **v4_recall_anchor** | 0.597 (v1_recall 0.586, baseline 0.531) | $0.1011 |
| E4 combination (winner) | **Haiku @ medium + v4** | **0.630** (P 0.850 / R 0.500, 17 TP / 3 FP / 17 FN) | **$0.0459** |

Caveat (from the report): 4 PRs / 34 defects is small — F1 deltas of
±0.05 are within noise; the **cost delta (~17×)** and the
**recall-up / precision-holds** direction are the robust findings. That is
why two holdout validation rounds were run.

### 2.2 Validation round 2 — 16 unseen PRs (114 GT issues)

| Run | Config | Micro P/R/F1 | TP/FP/FN | Schema-valid | Cost |
|---|---|---|---|---|---|
| `r2_holdout_haiku_baseline` | Haiku @ medium + original prompt | 0.662/0.447/**0.534** | 51/26/63 | 15/16 | $0.2085 |
| `r2_holdout_haiku_v4` | Haiku @ medium + v4 prompt | 0.604/0.535/**0.567** | 61/40/53 | 16/16 | $0.2150 |
| `r2_holdout_opus_baseline_full16` | Opus @ high + original prompt | 0.757/0.465/**0.576** | 53/17/61 | 16/16 | $4.4253 |

Paired bootstrap (10k, seed 42): Haiku-v4 − Opus = −0.009, 95% CI
[−0.059, +0.051] — **includes zero, no winner declared**. Haiku-v4 −
Haiku-baseline = +0.033, CI [−0.035, +0.116] — also includes zero.
Established: Opus and Haiku+v4 are statistically indistinguishable on
quality on unseen PRs, while Haiku is ~20× cheaper per PR.

### 2.3 Validation round 3 — 48 unseen PRs (261 GT issues, final)

Pre-registered holdout (`eval/holdout48.json`, seed 42, 6/repo × 8 repos).
Judge: `deepseek/deepseek-v4.1-flash-1017`, 0 failures across all arms.

| Arm | Config | Micro P/R/F1 | TP/FP/FN | Schema-valid | Cost (scored sum) | Cost/PR | Cost/TP |
|---|---|---|---|---|---|---|---|
| `h3_haiku_baseline` | Haiku-5.5 @ medium + original | 0.647/0.556/**0.598** | 145/79/116 | 44/48 | $0.86826 | $0.01809 | $0.00599 |
| `h3_haiku_v4` | Haiku-5.5 @ medium + v4 | 0.599/0.640/**0.619** | 167/112/94 | 47/48 | $0.87866 | $0.01831 | $0.00526 |
| `h3_haiku_baseline_r2` | repeat of baseline | 0.621/0.559/**0.589** | 146/89/115 | 45/48 | $0.79143 | $0.01649 | $0.00542 |
| `h3_haiku_v4_r2` | repeat of v4 | 0.585/0.609/**0.597** | 159/113/102 | 47/48 | $0.93261 | $0.01943 | $0.00587 |
| `h3_opus_baseline_full48` | Opus-5.5 @ high + original | 0.754/0.586/**0.660** | 153/50/108 | 48/48 | $16.84021 | $0.35084 | $0.11007 |

Paired bootstrap (10k resamples, seed 42;
`eval/results/bootstrap_round3.json`,
`eval/results/bootstrap_round3_opus.json`):

| Comparison | Observed ΔF1 | 95% CI | Excludes zero? |
|---|---|---|---|
| Opus − Haiku baseline | +0.0615 | [0.0054, 0.1209] | **Yes** |
| Opus − Haiku v4 | **+0.0410** | [0.0008, 0.0865] | **Yes (marginal)** |
| Haiku v4 − Haiku baseline | +0.0203 | [−0.0274, +0.0725] | No |

**Verdict (`eval/results/validation_round3.json`, `winner_declared=true`):**
Opus is the **quality** winner on the full 48 (F1 0.6595 vs Haiku-v4
0.6185 — a ~0.04 F1 gap), winning on precision (0.754 vs 0.599) while
Haiku-v4 wins on recall (0.640 vs 0.586, 167 TP vs 153 TP at 112 FP vs
50 FP). No Haiku prompt winner is supported (v4−baseline CI includes
zero; r2 repeats 0.5887/0.5966 confirm instability).

**Cost/quality tradeoff (~19×):** Opus costs ~19× Haiku per PR
($0.351 vs ~$0.018) and ~19× per TP ($0.110 vs ~$0.005–0.006) for
+0.041 to +0.062 F1. **Choose Opus for maximum quality, Haiku for cost
efficiency.** The deployed default (below) is Haiku for cost; Opus
remains selectable in Settings. No tested Haiku prompt/effort/tool
configuration reaches Opus 0.6595 — the gap is model capability, not
configuration (see the Haiku-improvement analysis in
`OPTIMIZATION_REPORT.md`, closing section).

---

## 3. How the evaluation dataset was produced

**Source benchmark:** `Qodo/PR-Review-Bench` (Hugging Face) — real merged
PRs with **line-level injected defects** (`file_path`, `start_line`,
`end_line`, `title`, `description`, `rule_name`). Detection = did the
reviewer flag the injected defect at the right file/line?

**Raw inputs (not committed — 4.3 GB, see `.gitignore`):**

| File | Role |
|---|---|
| `eval/data/git_code_review_bench_100_w_open_prs.jsonl` | Bench records (100 PRs with injected issues) |
| `eval/data/pr_meta.json` | PR metadata (title/body/base/head SHAs, changed files/lines) |
| `eval/data/repos/` | Local clones of the 8 benchmark repos (Ghost, aspnetcore, cal.com, dify, firefox-ios, prefect, redis, tauri) from `https://github.com/agentic-review-benchmarks/<repo>.git` |

**Pipeline (all deterministic, seed 42 where sampling is involved):**

1. **`eval/prepare.py`** — joins bench JSONL + `pr_meta.json`, filters to
   modest diffs (≤20 changed files, ≤600 changed lines), ≥50% of issues
   file-anchored, stratified across repos (2–3/repo), then **verifies**
   each pick: repo clones, PR head fetches (`refs/pull/<n>/head`), diff
   computes non-empty. Writes **`eval/manifest.json`** — **20 PRs /
   148 ground-truth issues** across 8 repos.
2. **`eval/slice.json`** — the fixed **4-PR / 34-defect experiment
   slice** (aspnetcore#2, firefox-ios#1, redis#5, tauri#10), frozen
   *before* running so baseline and every experiment share identical
   inputs (apples-to-apples).
3. **`eval/prep_holdout48.py`** — for round 3: excludes the 20 manifest
   PRs (80 untouched remain), computes `diff_lines`/`diff_files` via
   `git fetch` + `git diff` for all 80, then deterministic stratified
   sampling (seed 42): ~6/repo, thirds by diff size (small ≤200 /
   medium 200–500 / large >500 lines) × defect density (tertiles at
   0.8541 / 1.5823 issues per 100 lines). Writes
   **`eval/holdout48.json` before any model run** (pre-registered) —
   **48 PRs / 261 GT issues**, no overlap with the slice or round 2.
4. **Round 2 holdout** — 16 unseen PRs / 114 GT issues drawn the same
   way from the untouched pool (recorded in
   `eval/results/validation_round2.json`).

**Scoring:** `eval/score.py` — file-match + line-range overlap with a
cheap **LLM-judge** confirmation (`deepseek/deepseek-v4.1-flash-1017`);
micro P/R/F1, schema validity, cost, latency. Matcher was hand-checked
on ≥2 runs (redis#5, firefox-ios#1) before any aggregate was trusted.
Statistics: paired bootstrap over PRs (resample with replacement,
recompute micro F1 from summed TP/FP/FN, 10,000 resamples, seed 42) —
`eval/results/bootstrap_round3.py`, `bootstrap_round3_opus.py`, etc.

---

## 4. Evaluation harness

| File | Role |
|---|---|
| `eval/prepare.py` | Dataset prep → `eval/manifest.json` (20 PRs) |
| `eval/prep_holdout48.py` | Pre-registered holdout → `eval/holdout48.json` (48 PRs) |
| `eval/slice.json` | Fixed 4-PR experiment slice |
| `eval/run_review.mjs` | Faithful runner: real prompt + real schema imported from `cruise-line/`, agent loop via OpenRouter, swappable model/effort/prompt; captures `structured_output`, cost, latency, turns, `stop_reason`. Harness `0abca51995d3f7cf`; `READ_ONLY_TOOLS = [Read, Glob, Grep]`, `maxTurns 60` (cap 100), `CLAUDE_CODE_MAX_OUTPUT_TOKENS=16000` |
| `eval/score.py` | Matcher + LLM judge + micro P/R/F1, schema validity, cost |
| `eval/summarize.py` | Aggregates runs into E1/E2/E3 result JSONs |
| `eval/make_variants.mjs`, `eval/extract_baseline_prompt.mjs`, `eval/apply_winner.mjs` | Prompt-variant generation / baseline extraction / applying the winner |
| `eval/prompts/*.txt` | Prompt variants: `baseline_original.txt`, `v1_recall.txt`, `v2_severity.txt` (never run), `v3_anchor.txt` (never run), `v4_recall_anchor.txt` (winner) |
| `eval/results/*.json` | Machine-readable records: `baseline.json`, `models.json`, `effort.json`, `prompts.json`, `validation_round2.json`, `validation_round3.json`, `bootstrap_*.json`, `pareto.md` |
| `eval/results/raw/`, `eval/results/scored/` | Per-run evidence (raw structured outputs + scored records) |
| `eval/test_suite/` | Fake-CLI harness tests (turn-cap test 6/6) |
| `eval/spend_anchor.py`, `eval/spend_check.py` | OpenRouter spend/budget guards |

---

## 5. Exactly what enhancements were made and where

Applied to `cruise-line/` (3 files, +62/−8 vs upstream `d98cfa7`):

### 5.1 `cruise-line/agent/analysis/prompt.ts` — `v4_recall_anchor` prompt

`SYSTEM_PROMPT` (line 3) gained two appended sections (lines 168–~215),
byte-exact to `eval/prompts/v4_recall_anchor.txt` (14,794 chars):

- **"Completeness pass (do this before you finish)"** (line 168) —
  walk every changed file one at a time (including test/config/lockfiles),
  emit exactly one finding per distinct defect, actively check 12
  high-yield defect categories (inverted/off-by-one conditions, dropped
  init/cleanup calls, dropped arguments, hard-coded values, stale
  renames, missing modifiers, missing license headers/guards, unused
  imports under `-Werror`, contradicting comments, version-string drift,
  never-failing assertions, tooling-convention contradictions), and
  favour recall over brevity.
- **"Anchoring accuracy (required)"** (line 195) — every non-info
  finding must anchor to a real changed line: `commentAnchor.file` must
  appear in the diff verbatim, `lineStart`/`lineEnd` are 1-indexed in
  the new (head) version and must be confirmed with the Read tool,
  `::diff` directive must agree with the anchor, `files[]` lists
  actually-examined paths, `fixPrompt` names file + lines + pattern
  (<~150 words).

Effect (Haiku, 4-PR slice): recall 0.382 → 0.500, F1 0.531 → 0.597 @ high
effort; on the 48-PR holdout v4 vs baseline = +0.0203 F1 (CI includes
zero — directionally positive, not statistically established).

### 5.2 `cruise-line/agent/config.ts` — model + effort defaults

In `config.claude` (lines 44–57):

| Setting | Before | After |
|---|---|---|
| `model` (`optionalEnv('CLAUDE_MODEL', …)`) | `claude-opus-5-5` | **`claude-haiku-5-5`** |
| `effort` | `'high'` | **`'medium'`** |

Comments in the file record the honest basis: Haiku costs far less per
review on the same slice; quality relative to Opus was *not* established
at the time (later round-3 result: Opus +0.041 F1, CI excludes zero);
`medium` is a cost-motivated default (F1 0.55/0.54/0.53 for
medium/low/high is within noise on 4 PRs). Owners can still pick Opus in
Settings.

### 5.3 `cruise-line/astropods.yml` — deploy default

`CLAUDE_MODEL` env default (line 29): `"claude-opus-5-5"` →
**`"claude-haiku-5-5"`**, with the description updated to note the lower
measured per-review cost and that quality vs Opus was not yet
established on unseen PRs at the time of the change.

### 5.4 Verification gates (no API cost)

- `bun test agent/analysis/prompt.test.ts` → 3 pass / 0 fail
- `bunx tsc --noEmit` → exit 0
- Full `bun test` → 214 pass / 3 fail (3 failures pre-existing on a
  pristine checkout: auth test-isolation + missing frontend module)

---

## 6. Repository layout

```
README.md                  ← this file
OPTIMIZATION_REPORT.md     ← full optimization report (rounds 1–3)
cruise-line/               ← Cruise Line agent with the 3 applied changes
                             (prompt.ts, config.ts, astropods.yml)
eval/                      ← harness, manifests, prompts, results
plans/                     ← holdout design / plan notes
```

**Excluded from git (see `.gitignore`):** `eval/data/` (4.3 GB bench
JSONL + repo clones — regenerable via `eval/prepare.py` /
`eval/prep_holdout48.py` from `Qodo/PR-Review-Bench`),
`.venv/`, `node_modules/`, `.tmp/`, `__pycache__/`, `.env*`.

## 7. Reproducing (requires your own OpenRouter key + budget)

```bash
python eval/prepare.py --verify          # rebuild eval/manifest.json (20 PRs)
python eval/prep_holdout48.py            # rebuild eval/holdout48.json (48 PRs)
node eval/run_review.mjs --model anthropic/claude-haiku-5.5 --effort medium \
  --prompt-file eval/prompts/v4_recall_anchor.txt --tag <tag>
python eval/score.py ...                 # score with LLM judge
```

Budget note: a single Opus-5.5 @ high review costs ~$0.19–0.35; the
original slice work was capped at $4.00, round 3 at $35.00 total.
