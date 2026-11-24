#!/usr/bin/env python3
"""Aggregate scored runs into the per-experiment result artifacts.

Reads eval/results/scored/*.json (written by score.py) and emits:
  eval/results/baseline.json   baseline (current default config) on the fixed slice
  eval/results/models.json     E1 model sweep + F1-vs-$-vs-latency Pareto table
  eval/results/effort.json     E2 effort sweep on the E1 winner
  eval/results/prompts.json    E3 prompt variants vs baseline
  eval/results/pareto.md       human-readable Pareto table

All figures come from the same fixed 4-PR slice so every comparison is
apples-to-apples. Costs are OpenRouter key-delta measurements (--concurrency 1).
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCORED = ROOT / "results" / "scored"
OUT = ROOT / "results"

SLICE = ["firefox-ios#1", "aspnetcore#2", "tauri#10", "redis#5"]
BASELINE_TAG = "baseline"

# tags that are not part of any reported experiment (calibration / sanity probes)
EXCLUDE = {"calib_t25", "sanity_cheap"}


def load(tag: str) -> dict | None:
    f = SCORED / f"{tag}.json"
    if not f.exists():
        return None
    return json.loads(f.read_text())


def agg_of(tag: str) -> dict | None:
    d = load(tag)
    return d["aggregate"] if d else None


def row(tag: str, label: str | None = None) -> dict:
    a = agg_of(tag)
    return {
        "tag": tag,
        "label": label or tag,
        "model": a.get("model"),
        "effort": a.get("effort"),
        "prompt_variant": a.get("prompt_variant"),
        "n_prs": a["n_prs"],
        "micro_precision": a["micro_precision"],
        "micro_recall": a["micro_recall"],
        "micro_f1": a["micro_f1"],
        "micro_tp": a["micro_tp"],
        "micro_fp": a["micro_fp"],
        "micro_fn": a["micro_fn"],
        "schema_valid": f"{a['n_schema_valid']}/{a['n_prs']}",
        "schema_validity_rate": a["schema_validity_rate"],
        "total_findings": a["total_pred_findings"],
        "total_cost_usd": a["total_cost_usd"],
        "cost_per_pr_usd": a["cost_per_pr_usd"],
        "cost_per_tp_usd": a["cost_per_tp_usd"],
        "mean_latency_s": round(a["mean_latency_ms"] / 1000, 1),
        "total_turns_sum": a["total_turns"],
        "total_tool_calls": a["total_tool_calls"],
        "judge_calls": a.get("judge_calls"),
        "judge_failures": a.get("judge_failures"),
        "per_pr": a["per_pr"],
    }


def pareto_front(rows: list[dict]) -> list[str]:
    """Tags not dominated on (f1 ↑, cost ↓, latency ↓)."""
    front = []
    for r in rows:
        dominated = any(
            o is not r
            and o["micro_f1"] >= r["micro_f1"]
            and o["total_cost_usd"] <= r["total_cost_usd"]
            and o["mean_latency_s"] <= r["mean_latency_s"]
            and (
                o["micro_f1"] > r["micro_f1"]
                or o["total_cost_usd"] < r["total_cost_usd"]
                or o["mean_latency_s"] < r["mean_latency_s"]
            )
            for o in rows
        )
        if not dominated:
            front.append(r["tag"])
    return front


def main() -> int:
    base = row(BASELINE_TAG, "BASELINE claude-opus-5-5 @ high (current default)")

    # ---------------- E1 model sweep ----------------
    e1_tags = ["e1_haiku55", "e1_sonnet55", "e1_deepseek_flash", "e1_glm52", "e1_qwen3coder"]
    e1 = [base] + [row(t) for t in e1_tags if agg_of(t)]
    # baseline is opus at the same prompt/effort -> part of the model comparison
    e1[0] = {**e1[0], "label": "anthropic/claude-opus-5.5 @ high"}
    front = pareto_front(e1)
    for r in e1:
        r["on_pareto_front"] = r["tag"] in front
    e1_sorted = sorted(e1, key=lambda r: -r["micro_f1"])
    best_f1 = max(e1, key=lambda r: r["micro_f1"])
    cheapest = min(e1, key=lambda r: r["total_cost_usd"])
    (OUT / "models.json").write_text(json.dumps({
        "experiment": "E1 model sweep",
        "fixed_slice": SLICE,
        "protocol": ("identical prompt (repo SYSTEM_PROMPT), identical effort (high), identical "
                     "4-PR slice, --concurrency 1; costs are OpenRouter key-delta measurements"),
        "n_models_compared": len(e1),
        "results": e1_sorted,
        "pareto_front": front,
        "best_f1": {"tag": best_f1["tag"], "model": best_f1["model"], "f1": best_f1["micro_f1"],
                    "cost_usd": best_f1["total_cost_usd"]},
        "cheapest": {"tag": cheapest["tag"], "model": cheapest["model"], "f1": cheapest["micro_f1"],
                     "cost_usd": cheapest["total_cost_usd"]},
        "baseline_tag": BASELINE_TAG,
    }, indent=1))

    # ---------------- E2 effort sweep ----------------
    eff = []
    for tag, level in [("e2_haiku_low", "low"), ("e2_haiku_medium", "medium"), ("e1_haiku55", "high")]:
        if agg_of(tag):
            eff.append({**row(tag, f"anthropic/claude-haiku-5.5 @ {level}"), "effort": level})
    eff_sorted = sorted(eff, key=lambda r: ["low", "medium", "high"].index(r["effort"]))
    best_eff = max(eff, key=lambda r: r["micro_f1"]) if eff else None
    (OUT / "effort.json").write_text(json.dumps({
        "experiment": "E2 effort sweep",
        "model": "anthropic/claude-haiku-5.5",
        "fixed_slice": SLICE,
        "protocol": "identical model/prompt/slice; only the effort level varies; --concurrency 1",
        "results": eff_sorted,
        "winner": {"effort": best_eff["effort"], "f1": best_eff["micro_f1"],
                   "cost_usd": best_eff["total_cost_usd"]} if best_eff else None,
    }, indent=1))

    # ---------------- E3 prompt variants ----------------
    base_ref = row("e1_haiku55", "baseline prompt (repo SYSTEM_PROMPT)")
    variants = []
    for tag, name in [("e3_v1_recall", "v1_recall"), ("e3_v4_recall_anchor", "v4_recall_anchor")]:
        if agg_of(tag):
            r = row(tag, f"{name} (haiku-5.5 @ high)")
            r["delta_f1_vs_baseline_prompt"] = round(r["micro_f1"] - base_ref["micro_f1"], 4)
            r["beats_baseline_prompt"] = r["micro_f1"] > base_ref["micro_f1"]
            variants.append(r)
    combo = row("e4_winner_combo", "v4_recall_anchor @ medium (winning combination)") if agg_of("e4_winner_combo") else None
    if combo:
        combo["delta_f1_vs_baseline_prompt"] = round(combo["micro_f1"] - base_ref["micro_f1"], 4)
        combo["beats_baseline_prompt"] = combo["micro_f1"] > base_ref["micro_f1"]
    best_variant = max(variants + ([combo] if combo else []), key=lambda r: r["micro_f1"]) if variants or combo else None
    (OUT / "prompts.json").write_text(json.dumps({
        "experiment": "E3 prompt optimization",
        "model": "anthropic/claude-haiku-5.5",
        "fixed_slice": SLICE,
        "protocol": ("each variant is the repo's REAL SYSTEM_PROMPT plus one targeted appended "
                     "section, so a single prompt lever is isolated; compared against the same "
                     "model on the unmodified prompt over the identical slice"),
        "reference_same_model_baseline_prompt": base_ref,
        "variants": variants,
        "winning_combination": combo,
        "winner": {"tag": best_variant["tag"], "label": best_variant["label"],
                   "f1": best_variant["micro_f1"], "cost_usd": best_variant["total_cost_usd"],
                   "effort": best_variant["effort"], "prompt_variant": best_variant["prompt_variant"]} if best_variant else None,
    }, indent=1))

    # ---------------- baseline ----------------
    (OUT / "baseline.json").write_text(json.dumps({
        "experiment": "BASELINE",
        "config": "claude-opus-5-5 (repo default) @ effort high, unmodified repo SYSTEM_PROMPT",
        "fixed_slice": SLICE,
        "fixed_slice_ground_truth_issues": sum(p["n_gt_issues"] for p in base["per_pr"]),
        "full_manifest": "eval/manifest.json (20 PRs / 148 issues, verified) — the slice is a "
                         "budget-feasible subset; a 20-PR opus-high baseline alone would cost ~$3.8 "
                         "against the $4 cap",
        "results": base,
    }, indent=1))

    # ---------------- Pareto markdown ----------------
    lines = ["# E1 — Model sweep (fixed 4-PR slice, identical prompt/effort)", "",
             "| model | effort | F1 | P | R | cost $ | $/PR | $/TP | mean lat (s) | turns(sum) | schema | pareto |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in e1_sorted:
        lines.append(
            f"| {r['model']} | {r['effort']} | **{r['micro_f1']:.3f}** | {r['micro_precision']:.3f} | "
            f"{r['micro_recall']:.3f} | {r['total_cost_usd']:.4f} | {r['cost_per_pr_usd']:.4f} | "
            f"{r['cost_per_tp_usd'] or 0:.4f} | {r['mean_latency_s']:.1f} | {r['total_turns_sum']} | "
            f"{r['schema_valid']} | {'YES' if r['on_pareto_front'] else 'no'} |")
    lines += ["", "`turns(sum)` is the SUM of num_turns across the 4 PRs, not a mean.", "",
              "## E2 — Effort sweep (haiku-5.5)", "",
              "| effort | F1 | P | R | cost $ | mean lat (s) | turns(sum) |", "|---|---|---|---|---|---|---|"]
    for r in eff_sorted:
        lines.append(f"| {r['effort']} | **{r['micro_f1']:.3f}** | {r['micro_precision']:.3f} | "
                     f"{r['micro_recall']:.3f} | {r['total_cost_usd']:.4f} | {r['mean_latency_s']:.1f} | {r['total_turns_sum']} |")
    lines += ["", "## E3 — Prompt variants (haiku-5.5)", "",
              "| variant | effort | F1 | P | R | ΔF1 vs same-model baseline prompt | cost $ |", "|---|---|---|---|---|---|---|"]
    lines.append(f"| baseline prompt | {base_ref['effort']} | {base_ref['micro_f1']:.3f} | "
                 f"{base_ref['micro_precision']:.3f} | {base_ref['micro_recall']:.3f} | — | {base_ref['total_cost_usd']:.4f} |")
    for r in variants + ([combo] if combo else []):
        lines.append(f"| {r['prompt_variant']} | {r['effort']} | **{r['micro_f1']:.3f}** | {r['micro_precision']:.3f} | "
                     f"{r['micro_recall']:.3f} | {r['delta_f1_vs_baseline_prompt']:+.3f} | {r['total_cost_usd']:.4f} |")
    (OUT / "pareto.md").write_text("\n".join(lines) + "\n")

    print("\n".join(lines))
    print(f"\nwrote models.json, effort.json, prompts.json, baseline.json, pareto.md -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
