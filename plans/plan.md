# Cruise Line — Autoresearch Optimization of the PR-Review Agent

## Goal
Improve the quality (and/or cost/latency) of Cruise Line's PR-analysis stage via
autoresearch-style experiments, measured against a ground-truth bug-detection
benchmark, and apply the winning configuration to the repo. Budget: **≤ $4**
(OpenRouter key has ~$33.82 remaining).

## Research Summary (verified this session, not assumed)
- **Repo = Cruise Line**, an AI GitHub-PR review agent. The analysis stage
  (`agent/analysis/analyzer.ts` → `sandbox/index.ts` `/query`) runs a **Claude
  Agent SDK** loop: tools = `Read, Glob, Grep`, `permissionMode: bypassPermissions`,
  `maxTurns: 60`, and **structured output** via `outputFormat:{type:'json_schema', schema: walkthroughJsonSchema}`.
- **Model is configurable** (`config.claude.model`, default `claude-opus-5-5`;
  per-use override in Settings; effort default `high`). Model reaches the sandbox
  as `options.model` and is passed straight to the SDK.
- **OpenRouter is Anthropic-compatible and drives the full agent loop.** Verified by
  running the real `claude` CLI (v2.1.325) with
  `ANTHROPIC_BASE_URL=https://openrouter.ai/api` + `ANTHROPIC_AUTH_TOKEN=<key>`:
  - Anthropic-format `/v1/messages` returns proper `content`/`usage`/`stop_reason`.
  - **Tool use** works (`stop_reason: tool_use`, correct `input`).
  - **`--json-schema` structured output** works.
  - Full loop (read file + tools + json_schema) succeeded on **both**
    `anthropic/claude-haiku-5.5` and OSS `qwen/qwen3-coder-next`.
- **Verified live models & pricing on OpenRouter** ($/M in,out):
  `anthropic/claude-opus-5.5` (4,20), `claude-sonnet-5.5` (2,10),
  `claude-haiku-5.5` (0.1,0.5), `qwen/qwen3-coder-next` (0.12,0.8),
  `deepseek/deepseek-v4.1-flash-1017` (0.02,0.108), `z-ai/glm-5.2` (0.007,6.8),
  `openai/gpt-oss-120b` (0.15,0.6). Note: repo uses dashes (`claude-opus-5-5`);
  OpenRouter uses dots (`anthropic/claude-opus-5.5`) → mapping needed.
- **Ground-truth benchmark**: `Qodo/PR-Review-Bench` (HF). Fields: `repo`,
  `pr_url_to_review`, `issues[]{title, description, file_path, start_line,
  end_line, problematic_code_snippet, rule_name}`, `num_of_issues`. PRs come from
  `github.com/agentic-review-benchmarks/<repo>` and **clone + PR-head fetch +
  diff works** (verified on `Ghost` PR #1).
- **Runtime**: VSCode sandbox, no GPU, 2 cores, 7.7 GB RAM, **~11 GB disk free**.
  No `bun` (must install to run repo tests). Present: Node v26 (can import the
  repo's `.ts` directly via `--experimental-strip-types`), npm 11, python3.12
  (venv works), git, `claude` CLI.

**Load-bearing assumption**: the benchmark's injected-defect detection rate is a
valid proxy for "review quality", and the analysis stage can be reproduced
faithfully in isolation with a swappable model endpoint. (Both directly verified
above.)

## Approach
**Delivery-focused** optimization, grounded by a faithful local eval harness.

1. **Faithful harness** — reproduce the analysis stage using the repo's *real*
   `SYSTEM_PROMPT`, `buildUserPrompt`, and `walkthroughJsonSchema` (imported
   directly, not re-typed), run the agent loop through OpenRouter with a
   swappable model/effort. Same tool set, same `maxTurns`, same diff-truncation.
2. **Baseline** = current config (default model `claude-opus-5-5`, effort `high`,
   current prompt) on a fixed, modest-size eval subset.
3. **Experiments (one variable at a time)**:
   - **E1 model sweep** (incl. cheap Claude + OSS) → quality/cost/latency Pareto.
   - **E2 effort sweep** on the best model.
   - **E3 prompt optimization** (finding completeness, severity calibration,
     directive correctness) — the most likely quality lever.
4. **Apply the winner** to the repo, run the repo's own tests, and report.

Rejected: swapping to a different provider stack (OpenRouter Anthropic-compat is
verified and keeps the code change minimal); full-application runs (needs Postgres
+ GitHub App — the analysis stage is the optimization target and is isolated).

## Subtasks
1. **Eval subset + prep** — install deps in `.venv`; download `Qodo/PR-Review-Bench`;
   select ~20 PRs with modest diffs (≤20 changed files, ≤600 changed lines) and
   stratified across the available repos; write `eval/manifest.json`. Verify each
   repo clones + PR head fetches + diff computes.
   *Output: `eval/manifest.json`, `eval/prepare.py`.*
2. **Analysis runner** — `eval/run_review.mjs`: import real `SYSTEM_PROMPT` /
   `buildUserPrompt` / `walkthroughJsonSchema` from `cruise-line/agent/analysis/`;
   for each PR, clone at head, build the real user prompt, run the agent loop via
   `@anthropic-ai/claude-agent-sdk` (fallback: `claude` CLI) through OpenRouter with
   swappable model/effort/tools/maxTurns; capture `structured_output`, cost,
   latency, turns, stop_reason; write per-run JSON. Sanity-run 2 PRs on a cheap
   model; confirm schema-valid findings appear.
   *Output: `eval/run_review.mjs`, `eval/results/raw/*.json`.*
3. **Matcher + metrics** — `eval/score.py`: match predicted findings → ground-truth
   issues by **file match + line-range overlap** with a cheap LLM-judge semantic
   confirmation; compute micro precision/recall/F1, severity-calibration, schema
   validity, cost, latency. **Validate the matcher on 2 hand-checked runs before
   trusting it** (false-negative safeguard).
   *Output: `eval/score.py`, `eval/results/scored/*.json`.*
4. **Baseline** — run subtask 2 with current default config (model `claude-opus-5-5`,
   effort `high`, current prompt) on the subset.
   *Output: `eval/results/baseline.json` (F1, cost, latency).*
5. **E1 — model sweep** — same prompt, models: `claude-opus-5.5`, `claude-sonnet-5.5`,
   `claude-haiku-5.5`, `qwen/qwen3-coder-next`, `deepseek/deepseek-v4.1-flash-1017`,
   `z-ai/glm-5.2`. Build Pareto (F1 vs $ vs sec).
   *Output: `eval/results/models.json` + comparison table.*
6. **E2 — effort sweep** — low/medium/high for the best-quality model.
   *Output: `eval/results/effort.json`.*
7. **E3 — prompt optimization** — 2–4 `SYSTEM_PROMPT` variants targeting issue
   recall, severity calibration, and directive/line-number correctness; run on the
   best model+subset; keep only variants that beat baseline.
   *Output: `eval/results/prompts.json` + winning prompt.*
8. **Apply + verify** — apply the winning prompt (and, if justified, the recommended
   default model) to the repo; install `bun`; run the repo's unit tests
   (`bun test`) and a TS typecheck; confirm the prompt test still passes.
   *Output: edited `agent/analysis/prompt.ts` (+ `config.ts`/`astropods.yml` if model changes).*
9. **Report** — `OPTIMIZATION_REPORT.md`: baseline vs optimized, methodology,
   per-experiment evidence, measured cost, and a clear recommendation.
   *Output: `OPTIMIZATION_REPORT.md`.*

## Deliverables
| File Path | Description |
|-----------|-------------|
| `/home/azureuser/optimize-cruiseline/eval/manifest.json` | Fixed eval subset + ground-truth issues |
| `/home/azureuser/optimize-cruiseline/eval/run_review.mjs` | Faithful analysis runner (swappable model) |
| `/home/azureuser/optimize-cruiseline/eval/score.py` | Matcher + metrics |
| `/home/azureuser/optimize-cruiseline/eval/results/*.json` | Baseline + per-experiment results |
| `/home/azureuser/optimize-cruiseline/cruise-line/agent/analysis/prompt.ts` | Winning prompt (if improved) |
| `/home/azureuser/optimize-cruiseline/OPTIMIZATION_REPORT.md` | Full report + recommendation |

## Evaluation Criteria
- Harness reproduces the analysis stage: structured findings parse, matcher
  validated on ≥2 hand-checked runs.
- Baseline recorded (F1, cost, latency) on the fixed subset.
- ≥6 models compared on identical inputs; Pareto reported.
- A winning configuration identified that improves detection F1 (or matches it at
  materially lower cost/latency), with evidence.
- Repo tests pass after applying the winner.
- Total OpenRouter spend ≤ **$4** (checked via `/api/v1/key`; abort if exceeded).

## Notes
- **Budget guardrails**: small eval subset; cheap models for sweeps; run the
  expensive opus baseline on the *same* subset only; checkpoint every PR; poll
  cumulative spend and stop if it approaches the cap.
- **Disk (~11 GB free)**: clone one PR repo at a time and clean up after each run.
- **Faithfulness**: use the repo's real prompt/schema/tool-set/`maxTurns`;
  OpenRouter routing is the only substitution, and it is applied identically to
  every config so relative rankings are valid.
- **Model naming**: map repo-style `claude-opus-5-5` ↔ OpenRouter `anthropic/claude-opus-5.5`.
- Eval-only tooling lives in `eval/` and does not touch the app at runtime.
