# Larger, Diverse Holdout — Design for a Conclusive Evaluation

## Goal
Replace the inconclusive 16-PR result with a pre-registered, stratified holdout
large and diverse enough that the Haiku-vs-Opus and prompt-vs-prompt comparisons
either reach a clear verdict or are honestly reported as equivalent.

## Why the current result is inconclusive (recap)
- 16 PRs / 114 GT issues. Paired diff Haiku-v4 − Opus = **-0.009, 95% CI
  [-0.059, +0.051]** — includes zero and both signs.
- Run-to-run noise on the 4-PR slice: F1 **0.47 / 0.56 / 0.63** for the identical
  config. Single-run comparisons are unreliable at this size.
- Composition is uneven (Ghost 3, dify 3, aspnetcore 1, redis 1, …) and the
  defect mix is dominated by a few rule families.

## Available pool (verified)
- `eval/data/git_code_review_bench_100_w_open_prs.jsonl`: **100 PRs, 580 GT
  issues**, 8 repos — Ghost 13, aspnetcore 10, cal.com 16, dify 13, firefox-ios
  13, prefect 13, redis 9, tauri 13.
- 20 PRs already used in `eval/manifest.json` (4 slice + 16 holdout). The other
  **80 PRs are untouched** and form a clean, never-seen pool.
- Pool records lack `diff_lines`/`diff_files` (only in the manifest), so diff
  size must be computed during prep (clone + `git diff --stat`), as before.

## Design

### 1. Pre-registered decision rule (fix BEFORE running)
Two questions, two rules — decided now, not after seeing results:

- **Q1 (model):** Is Haiku-5.5 @ medium *not meaningfully worse* than Opus-5.5 @
  high? → **Non-inferiority test.** Haiku is declared "acceptable substitute" if
  the lower bound of the paired 95% CI for (Haiku − Opus) is **> −0.05 F1**.
  Rationale: Haiku is ~15× cheaper, so the business question is "good enough?",
  not "strictly better?". A superiority claim would need the lower bound > 0,
  which is far harder and not required to justify the swap.
- **Q2 (prompt):** Does v4 beat the baseline prompt on the same model? →
  **Superiority test.** v4 is declared better only if the lower bound of the
  paired 95% CI for (v4 − baseline) is **> 0**. Otherwise the prompt change is
  reported as "no demonstrated benefit" and should be reverted or kept only as a
  no-cost default.

### 2. Sample size
Target **48 PRs** from the 80 untouched pool PRs (~280 GT issues, ~2.5× the
current 114). Expected CI width scales as ~1/√n, so the current ±0.055 band
should narrow to roughly **±0.03**, enough to resolve a 0.05 non-inferiority
margin and a ≥0.05 prompt effect. If the true effect is smaller than ~0.03, the
honest answer is "equivalent for practical purposes" — which, given the cost
gap, still favors Haiku.

### 3. Stratification (diversity)
Select the 48 PRs by **stratified sampling** on three axes, computed during prep:

| Axis | Buckets | Target |
|---|---|---|
| **Repo / language** | Ghost (JS/TS), cal.com (TS), dify (Python/TS), prefect (Python), aspnetcore (C#), firefox-ios (Swift), redis (C), tauri (Rust/TS) | ~6 PRs per repo (all 8 repos represented) |
| **Diff size** | small ≤200 lines, medium 200–500, large >500 | roughly thirds |
| **Defect density** | issues per 100 diff lines: low / medium / high | roughly thirds |

Also record, for reporting, the **rule-family mix** (the pool's `rule_name`
values) so we can state which defect types the result covers. The current
manifest is dominated by a handful of rules (SwiftLint, Async-suffix, type
annotations); the new set should not be.

Selection must be **deterministic** (fixed seed) and **pre-registered**: write
the chosen PR list to `eval/holdout48.json` *before* any model run, so the set
cannot be cherry-picked after seeing scores.

### 4. Runs (identical inputs, fixed harness v2)
Three configs on the same 48 PRs, concurrency 1, same judge:

| Config | Model | Effort | Prompt | Purpose |
|---|---|---|---|---|
| A | opus-5.5 | high | baseline_original | reference |
| B | haiku-5.5 | medium | baseline_original | isolates model effect |
| C | haiku-5.5 | medium | v4_recall_anchor | isolates prompt effect (C−B) |

- **Repeats:** run B and C **twice** (cheap) and average, to remove run-to-run
  noise. Run A once (expensive); if budget allows, a second A run on a subset.
- **Scoring:** `eval/score.py` with the LLM judge, same settings as round 2.
- **Statistics:** paired bootstrap over PRs (10k resamples, seed 42) for
  (B−A), (C−B), (C−A), each with 95% CI. Report per-repo and per-diff-size
  breakdowns, not just the aggregate.

### 5. Budget estimate (measured unit costs from round 2)
| Config | $/PR (measured) | ×48 PRs | ×repeats | Subtotal |
|---|---|---|---|---|
| A opus-5.5 @ high | ~$0.19 | $9.12 | ×1 | **$9.12** |
| B haiku-5.5 @ medium | ~$0.013 | $0.62 | ×2 | **$1.25** |
| C haiku-5.5 @ medium + v4 | ~$0.013 | $0.62 | ×2 | **$1.25** |
| **Total** | | | | **≈ $11.6** |

Opus dominates the cost. Cheaper variants if budget is tight:
- **32 PRs instead of 48** → A $6.08, total ≈ **$7.7** (CI ~±0.037; still
  resolves a 0.05 margin).
- **Opus on a 24-PR subset, Haiku on all 48** → A $4.56, total ≈ **$7.1**, but
  the model comparison then rests on 24 PRs (CI ~±0.045) — acceptable for a
  0.05 non-inferiority margin, weaker for superiority.

### 6. Deliverables
| File | Description |
|---|---|
| `eval/holdout48.json` | Pre-registered PR list + strata (written before any run) |
| `eval/results/raw/h3_*` | Raw runs for configs A/B/C |
| `eval/results/scored/h3_*.json` | Scored results |
| `eval/results/bootstrap_h3.json` | Paired CIs + per-stratum breakdowns |
| `eval/results/validation_round3.json` | Full record + verdicts |
| `OPTIMIZATION_REPORT.md` | New "Validation round 3" section (append, don't duplicate) |

### 7. Risks / honest limits
- **Benchmark bias remains:** real bugs not injected by the benchmark still
  count as false positives, so precision is a lower bound. More PRs reduce
  variance, not this bias.
- **Judge dependence:** the LLM judge decides ambiguous matches. Keep the same
  judge and settings as round 2 for comparability; note it as a limitation.
- **Contamination:** the benchmark is public and may be in model training data.
  Acknowledge it; the relative comparison is still informative.
- **Cost:** a conclusive Opus comparison is the expensive part. If budget is
  capped below ~$7, prefer the non-inferiority framing on 32 PRs over an
  underpowered superiority test.

## Recommendation
Approve a budget of **~$12** for the full 48-PR design, or **~$7.7** for the
32-PR variant. Pre-register the decision rules above (non-inferiority margin
0.05 for the model swap; superiority > 0 for the prompt) so the verdict is
decided by the data, not by post-hoc interpretation.
