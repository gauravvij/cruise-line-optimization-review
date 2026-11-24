#!/usr/bin/env python3
"""Cruise Line eval — matcher + metrics.

Matches predicted findings (from eval/run_review.mjs structured output) against
Qodo/PR-Review-Bench ground-truth issues and computes micro precision / recall /
F1, severity calibration, schema validity, cost and latency.

Matching strategy (deliberately conservative and auditable):
  1. FILE match  — predicted finding's commentAnchor.file or files[] vs the
     ground-truth issue's file_path, compared on normalised paths (suffix match
     so 'src/a.c' == 'a.c' when unambiguous).
  2. LINE match  — ground-truth [start_line, end_line] expanded by a tolerance
     window must intersect the predicted anchor range. If the ground truth has no
     line info, a file match alone suffices.
  3. SEMANTIC confirmation — for candidate pairs that pass (1) but not (2), and
     for ground-truth issues with no file anchor, an optional cheap LLM judge
     decides. Disabled with --no-judge.

Assignment is a greedy one-to-one maximum-score matching, so a single prediction
cannot claim two ground-truth issues (and vice versa). Precision therefore counts
predictions that matched nothing as false positives, which is what "does the
reviewer surface real injected bugs without noise" means here.

Harness v2: refuses to score a tag whose records were produced by a different
harness version (sha256 of run_review.mjs + score.py) unless
--allow-harness-mismatch is given. Judge spend is measured via the OpenRouter
key usage delta around the scoring call.

Usage:
  python eval/score.py --tag baseline                  # score one run
  python eval/score.py --tag baseline --explain firefox-ios#1
  python eval/score.py --all                            # score every run tag
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "results" / "raw"
CALIB = ROOT / "results" / "calib"
SCORED = ROOT / "results" / "scored"

LINE_TOLERANCE = 8  # +/- lines around a ground-truth range that still counts as the same defect

NON_ACTIONABLE = {"info"}  # findings that are not defect claims; excluded from precision

# Harness identity: must equal run_review.mjs harnessVersion() =
# sha256(run_review.mjs bytes + score.py bytes)[:16].
HARNESS_FILES = [ROOT / "run_review.mjs", ROOT / "score.py"]


def harness_version() -> str:
    h = hashlib.sha256()
    for f in HARNESS_FILES:
        h.update(f.read_bytes())
    return h.hexdigest()[:16]


# ---------------------------------------------------------------------------
# Path normalisation
# ---------------------------------------------------------------------------

def norm_path(p: str | None) -> str:
    if not p:
        return ""
    p = p.strip().replace("\\", "/")
    p = re.sub(r"^\./", "", p)
    p = re.sub(r"^/+", "", p)
    return p


def paths_match(a: str, b: str) -> bool:
    """True when two normalised paths denote the same file.

    Exact match, or one is a path-suffix of the other on a component boundary.
    Suffix matching handles the benchmark's inconsistent anchoring (some issues
    record 'boot.js', others 'ghost/core/core/boot.js').
    """
    a, b = norm_path(a), norm_path(b)
    if not a or not b:
        return False
    if a == b:
        return True
    return a.endswith("/" + b) or b.endswith("/" + a)


# ---------------------------------------------------------------------------
# Prediction extraction
# ---------------------------------------------------------------------------

def predicted_findings(rec: dict) -> list[dict]:
    """Flatten a run record's structured_output.findings into matchable units."""
    so = rec.get("structured_output") or {}
    out = []
    for i, f in enumerate(so.get("findings") or []):
        ca = f.get("commentAnchor") or {}
        files = [norm_path(x) for x in (f.get("files") or [])]
        anchor_file = norm_path(ca.get("file"))
        cand_files = ([anchor_file] if anchor_file else []) + [x for x in files if x and x != anchor_file]
        ls, le = ca.get("lineStart"), ca.get("lineEnd")
        if not isinstance(ls, int):
            ls = None
        if not isinstance(le, int):
            le = None
        if ls is not None and le is not None and le < ls:
            ls, le = le, ls
        out.append({
            "idx": i,
            "title": f.get("title") or "",
            "severity": f.get("severity") or "",
            "category": f.get("category") or "",
            "body": (f.get("body") or "")[:2000],
            "files": cand_files,
            "anchor_file": anchor_file,
            "line_start": ls,
            "line_end": le,
            "actionable": (f.get("severity") or "") not in NON_ACTIONABLE,
            "raw": f,
        })
    return out


def gt_issues(rec: dict) -> list[dict]:
    out = []
    for i, iss in enumerate(rec.get("issues") or []):
        fp = norm_path(iss.get("file_path"))
        sl, el = iss.get("start_line"), iss.get("end_line")
        if not isinstance(sl, int):
            sl = None
        if not isinstance(el, int):
            el = None
        if sl is not None and el is not None and el < sl:
            sl, el = el, sl
        out.append({
            "idx": i,
            "title": iss.get("title") or "",
            "description": (iss.get("description") or "")[:2000],
            "file_path": fp,
            "start_line": sl,
            "end_line": el,
            "rule_name": iss.get("rule_name") or "",
        })
    return out


def lines_overlap(gt: dict, pred: dict, tol: int = LINE_TOLERANCE) -> bool:
    if gt["start_line"] is None or pred["line_start"] is None:
        return False
    gs = gt["start_line"] - tol
    ge = (gt["end_line"] if gt["end_line"] is not None else gt["start_line"]) + tol
    ps = pred["line_start"]
    pe = pred["line_end"] if pred["line_end"] is not None else pred["line_start"]
    return not (pe < gs or ps > ge)


def line_affinity(gt: dict, pred: dict) -> float:
    """0..1 similarity of the two line ranges, used only to break score ties.

    The benchmark contains several distinct issues anchored to the same or
    adjacent lines (e.g. five separate SwiftLint line-length issues on lines
    203-210). When one prediction overlaps several ground-truth issues, the
    assignment must prefer the issue whose range it actually describes rather
    than whichever happens to come first in the file, otherwise the reported
    match is arbitrary.
    """
    if gt["start_line"] is None or pred["line_start"] is None:
        return 0.0
    gs, ge = gt["start_line"], gt["end_line"] if gt["end_line"] is not None else gt["start_line"]
    ps, pe = pred["line_start"], pred["line_end"] if pred["line_end"] is not None else pred["line_start"]
    inter = max(0, min(ge, pe) - max(gs, ps) + 1)
    if inter == 0:
        # within tolerance but not overlapping: rank by proximity
        dist = min(abs(gs - pe), abs(ps - ge))
        return max(0.0, 1.0 - dist / (LINE_TOLERANCE + 1)) * 0.5
    union = max(ge, pe) - min(gs, ps) + 1
    return inter / union


# ---------------------------------------------------------------------------
# Optional cheap LLM judge
# ---------------------------------------------------------------------------

def _api_key() -> str:
    cfg = json.loads(Path.home().joinpath(".config/openrouter/config").read_text())
    return cfg["api_key"]


def openrouter_usage_monthly() -> float:
    """Authoritative account spend (GET /api/v1/key data.usage_monthly). Free call."""
    req = urllib.request.Request("https://openrouter.ai/api/v1/key",
                                 headers={"Authorization": f"Bearer {_api_key()}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return float(json.load(r)["data"]["usage_monthly"])


# Judge failures must be loud: a silent all-False fallback would understate
# recall and make a working model look like it missed everything.
JUDGE_STATS = {"calls": 0, "failures": 0, "pairs": 0}


def llm_judge(pairs: list[tuple[dict, dict]], model: str) -> list[bool]:
    """Ask a cheap model whether each (ground truth, prediction) pair is the same defect."""
    if not pairs:
        return []
    import urllib.request as _ur
    JUDGE_STATS["calls"] += 1
    JUDGE_STATS["pairs"] += len(pairs)

    prompt = [
        "You are grading whether a code reviewer's finding identifies the same underlying defect "
        "as a known injected issue in a pull request.",
        "Answer for each pair. Same defect = the reviewer is pointing at the same root cause / problem, "
        "even if worded differently or located a few lines off. Different defect = unrelated concern.",
        "Respond with ONLY a JSON array of booleans, one per pair, in order. Example: [true,false,true]",
        "",
    ]
    for n, (g, p) in enumerate(pairs):
        prompt.append(f"--- Pair {n} ---")
        prompt.append(f"KNOWN ISSUE (file={g['file_path']} lines={g['start_line']}-{g['end_line']}): {g['title']} :: {g['description'][:700]}")
        prompt.append(f"REVIEWER FINDING (files={p['files'][:3]} lines={p['line_start']}-{p['line_end']}): {p['title']} :: {p['body'][:700]}")

    # Reasoning-capable models spend the whole completion budget thinking and
    # return an empty `content`, which would silently collapse to all-False and
    # understate recall. Disable reasoning where supported and give the verdict
    # itself plenty of room.
    body = json.dumps({
        "model": model,
        "max_tokens": 3000,
        "temperature": 0,
        "reasoning": {"enabled": False},
        "messages": [{"role": "user", "content": "\n".join(prompt)}],
    }).encode()

    req = _ur.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"},
    )
    try:
        with _ur.urlopen(req, timeout=180) as r:
            resp = json.load(r)
        msg = resp["choices"][0].get("message") or {}
        # Some providers return reasoning-only payloads; fall back across fields.
        text = msg.get("content") or msg.get("reasoning") or msg.get("reasoning_content") or ""
        if isinstance(text, list):
            text = " ".join(str(x.get("text", x)) if isinstance(x, dict) else str(x) for x in text)
        if not isinstance(text, str):
            text = str(text)
        m = re.search(r"\[[^\]]*\]", text)
        if not m:
            JUDGE_STATS["failures"] += 1
            print(f"  [judge] NO JSON ARRAY in response: {text[:160]!r}", file=sys.stderr)
            return [False] * len(pairs)
        vals = json.loads(m.group(0))
        out = [bool(v) for v in vals]
        while len(out) < len(pairs):
            out.append(False)
        return out[: len(pairs)]
    except Exception as e:  # noqa: BLE001
        JUDGE_STATS["failures"] += 1
        print(f"  [judge] FAILED ({type(e).__name__}: {str(e)[:100]}) -> all False", file=sys.stderr)
        return [False] * len(pairs)


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def match_record(rec: dict, use_judge: bool, judge_model: str, explain: bool = False) -> dict:
    preds = predicted_findings(rec)
    gts = gt_issues(rec)

    # Candidate pairs with a deterministic score.
    #   score 1.0 = same file AND overlapping/adjacent lines (a confident match)
    #   score 0.5 = same file, different lines  (ambiguous: needs the judge)
    #   score 0.2 = ground truth has no file anchor at all (needs the judge)
    # Only actionable predictions are eligible to be a true positive; `info`
    # findings are observations and are excluded from the defect claim set.
    cands: list[tuple[float, int, int, str]] = []  # score, gt_idx, pred_idx, how
    for g in gts:
        for p in preds:
            if not p["actionable"]:
                continue
            file_ok = any(paths_match(g["file_path"], f) for f in p["files"]) if g["file_path"] else False
            if g["file_path"] and not file_ok:
                continue
            if g["file_path"] and file_ok and lines_overlap(g, p):
                cands.append((1.0 + line_affinity(g, p), g["idx"], p["idx"], "file+line"))
            elif g["file_path"] and file_ok:
                cands.append((0.5, g["idx"], p["idx"], "file_only"))
            elif not g["file_path"]:
                cands.append((0.2, g["idx"], p["idx"], "no_anchor"))

    # Judge the ambiguous ones (file-only and unanchored ground truth)
    ambiguous = [(g, p) for (s, gi, pi, how) in cands if how != "file+line"
                 for g in [gts[gi]] for p in [preds[pi]]]
    if use_judge and ambiguous:
        verdicts = llm_judge(ambiguous, judge_model)
        key = {(g["idx"], p["idx"]): v for (g, p), v in zip(ambiguous, verdicts)}
        rescored = []
        for s, gi, pi, how in cands:
            if how == "file+line":
                rescored.append((s, gi, pi, how))
            elif key.get((gi, pi), False):
                rescored.append((0.9, gi, pi, how + "+judge"))
        cands = rescored
    else:
        cands = [(s, gi, pi, how) for (s, gi, pi, how) in cands if how == "file+line"]

    # Greedy one-to-one assignment by descending score, tie-broken by line affinity
    cands.sort(key=lambda t: (-t[0], t[1], t[2]))
    used_g, used_p = set(), set()
    matches = []
    for s, gi, pi, how in cands:
        if gi in used_g or pi in used_p:
            continue
        used_g.add(gi)
        used_p.add(pi)
        matches.append({"gt_idx": gi, "pred_idx": pi, "score": round(s, 4), "how": how})

    # Precision counts only actionable predictions (info findings are observations,
    # not defect claims, so they are neither TP nor FP)
    actionable_preds = [p for p in preds if p["actionable"]]
    tp = sum(1 for m in matches if preds[m["pred_idx"]]["actionable"])
    fp = len(actionable_preds) - tp
    fn = len(gts) - len(used_g)

    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec_ = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec_ / (prec + rec_) if (prec + rec_) else 0.0

    # Severity calibration on matched pairs
    sev_rank = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
    high_sev_tp = sum(1 for m in matches if preds[m["pred_idx"]]["severity"] in ("critical", "high"))

    result = {
        "id": rec.get("id"),
        "tag": rec.get("tag"),
        "model": rec.get("model"),
        "effort": rec.get("effort"),
        "max_turns": rec.get("maxTurns"),
        "prompt_variant": rec.get("promptVariant"),
        "schema_valid": rec.get("schema_valid"),
        "subtype": rec.get("subtype"),
        "n_pred_findings": len(preds),
        "n_pred_actionable": len(actionable_preds),
        "n_gt_issues": len(gts),
        "tp": tp, "fp": fp, "fn": fn,
        "precision": round(prec, 4),
        "recall": round(rec_, 4),
        "f1": round(f1, 4),
        "n_high_sev_tp": high_sev_tp,
        "cost_usd": rec.get("cost_usd", 0.0),          # key-delta (authoritative, harness v2)
        "cli_cost_usd": rec.get("cli_cost_usd"),       # CLI estimate (secondary)
        "cost_flag": rec.get("cost_flag"),
        "num_turns_counted": rec.get("num_turns_counted"),
        "turn_cap_hit": rec.get("turn_cap_hit"),
        "turn_check_ok": rec.get("turn_check_ok"),
        "harness_version": rec.get("harness_version"),
        "prompt_sha256": rec.get("prompt_sha256"),
        "latency_ms": rec.get("latency_ms", 0),
        "num_turns": rec.get("num_turns"),
        "n_tool_calls": rec.get("n_tool_calls"),
        "matches": matches,
    }
    if explain:
        result["_detail"] = {
            "predictions": [{"idx": p["idx"], "severity": p["severity"], "title": p["title"][:110],
                             "files": p["files"][:3], "lines": [p["line_start"], p["line_end"]],
                             "actionable": p["actionable"]} for p in preds],
            "ground_truth": [{"idx": g["idx"], "title": g["title"][:110], "file": g["file_path"],
                              "lines": [g["start_line"], g["end_line"]]} for g in gts],
            "matched_gt": sorted(used_g),
            "unmatched_gt": sorted(set(range(len(gts))) - used_g),
            "unmatched_pred": sorted(set(range(len(preds))) - used_p),
        }
    return result


def aggregate(records: list[dict], tag: str, meta: dict | None = None) -> dict:
    tp = sum(r["tp"] for r in records)
    fp = sum(r["fp"] for r in records)
    fn = sum(r["fn"] for r in records)
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec_ = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec_ / (prec + rec_) if (prec + rec_) else 0.0
    cost = sum(r["cost_usd"] for r in records)
    lat = sum(r["latency_ms"] for r in records)
    return {
        "tag": tag,
        "n_prs": len(records),
        "micro_tp": tp, "micro_fp": fp, "micro_fn": fn,
        "micro_precision": round(prec, 4),
        "micro_recall": round(rec_, 4),
        "micro_f1": round(f1, 4),
        "total_pred_findings": sum(r["n_pred_findings"] for r in records),
        "total_gt_issues": sum(r["n_gt_issues"] for r in records),
        "n_schema_valid": sum(1 for r in records if r["schema_valid"]),
        "schema_validity_rate": round(sum(1 for r in records if r["schema_valid"]) / len(records), 4) if records else 0.0,
        "total_cost_usd": round(cost, 6),
        "n_cost_flags": sum(1 for r in records if r.get("cost_flag")),
        "cli_cost_usd_secondary": round(sum((r.get("cli_cost_usd") or 0.0) for r in records), 6),
        "n_turn_cap_hit": sum(1 for r in records if r.get("turn_cap_hit")),
        "n_turn_check_violations": sum(1 for r in records if r.get("turn_check_ok") is False),
        "cost_per_pr_usd": round(cost / len(records), 6) if records else 0.0,
        "cost_per_tp_usd": round(cost / tp, 6) if tp else None,
        "total_latency_ms": lat,
        "mean_latency_ms": round(lat / len(records), 1) if records else 0.0,
        "total_turns": sum(r["num_turns"] or 0 for r in records),
        "total_tool_calls": sum(r["n_tool_calls"] or 0 for r in records),
        "judge_calls": JUDGE_STATS["calls"],
        "judge_pairs": JUDGE_STATS["pairs"],
        "judge_failures": JUDGE_STATS["failures"],
        "judge_failure_rate": round(JUDGE_STATS["failures"] / JUDGE_STATS["calls"], 4) if JUDGE_STATS["calls"] else 0.0,
        "per_pr": [{k: r[k] for k in ("id", "tp", "fp", "fn", "precision", "recall", "f1",
                                      "n_pred_findings", "n_gt_issues", "cost_usd", "latency_ms",
                                      "num_turns", "schema_valid", "num_turns_counted", "turn_cap_hit",
                                      "cost_flag")} for r in records],
        **(meta or {}),
    }


def load_run(tag: str, raw_dir: Path = RAW) -> tuple[list[dict], dict]:
    recs, summary = [], {}
    for f in sorted(raw_dir.glob(f"{tag}__*.json")):
        d = json.loads(f.read_text())
        if f.name.endswith("__summary.json"):
            summary = d
            continue
        recs.append(d)
    return recs, summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dir", default=str(RAW))
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--judge-model", default="deepseek/deepseek-v4.1-flash-1017")
    ap.add_argument("--explain")
    ap.add_argument("--allow-harness-mismatch", action="store_true",
                    help="score tags whose records came from a different harness version (warned)")
    ap.add_argument("--out")
    args = ap.parse_args()

    SCORED.mkdir(parents=True, exist_ok=True)
    raw_dir = Path(args.dir)

    if args.all:
        tags = sorted({f.name.split("__")[0] for f in raw_dir.glob("*__*.json")})
    elif args.tag:
        tags = [args.tag]
    else:
        ap.error("need --tag or --all")

    cur = harness_version()
    out_all = {}
    for tag in tags:
        recs, summary = load_run(tag, raw_dir)
        if not recs:
            print(f"[score] no records for tag {tag}")
            continue
        rec_hv = {r.get("harness_version") for r in recs}
        if rec_hv != {cur}:
            if not args.allow_harness_mismatch:
                print(f"[score] SKIP tag {tag}: record harness_version={sorted(map(str, rec_hv))} "
                      f"!= current {cur} (legacy or other harness). Re-run it, or pass --allow-harness-mismatch.")
                continue
            print(f"[score] WARNING tag {tag}: harness mismatch {sorted(map(str, rec_hv))} vs current {cur}")
        explain_ids = set((args.explain or "").split(",")) if args.explain else set()
        JUDGE_STATS.update(calls=0, failures=0, pairs=0)
        judge_before = openrouter_usage_monthly() if not args.no_judge else None
        scored = [match_record(r, not args.no_judge, args.judge_model,
                               explain=(r.get("id") in explain_ids)) for r in recs]
        judge_delta = (openrouter_usage_monthly() - judge_before) if judge_before is not None else 0.0
        meta = {"model": summary.get("model") or recs[0].get("model"),
                "effort": summary.get("effort") or recs[0].get("effort"),
                "prompt_variant": summary.get("prompt_variant") or recs[0].get("promptVariant")}
        agg = aggregate(scored, tag, meta)
        agg.update({
            "harness_version": cur,
            "prompt_sha256": summary.get("prompt_sha256"),
            "pr_list": summary.get("pr_list"),
            "judge_key_delta_usd": round(judge_delta, 6),
            "judge_key_delta_note": "usage_monthly delta across the scoring call; includes any other account spend in that window",
        })
        out_all[tag] = {"aggregate": agg, "per_pr": scored}
        (SCORED / f"{tag}.json").write_text(json.dumps({"aggregate": agg, "per_pr": scored}, indent=1))

        print(f"\n=== {tag}  model={meta['model']} effort={meta['effort']} variant={meta['prompt_variant']} ===")
        print(f"  micro P/R/F1 = {agg['micro_precision']:.3f} / {agg['micro_recall']:.3f} / {agg['micro_f1']:.3f}"
              f"   (tp={agg['micro_tp']} fp={agg['micro_fp']} fn={agg['micro_fn']})")
        print(f"  schema-valid {agg['n_schema_valid']}/{agg['n_prs']}  findings={agg['total_pred_findings']}"
              f"  cost=${agg['total_cost_usd']:.4f}  mean {agg['mean_latency_ms']/1000:.0f}s  turns={agg['total_turns']}")
        print(f"  judge: calls={JUDGE_STATS['calls']} pairs={JUDGE_STATS['pairs']} "
              f"failures={JUDGE_STATS['failures']} key-delta=${agg['judge_key_delta_usd']:.5f}")
        print(f"  cost: sum key-delta=${agg['total_cost_usd']:.5f}  cli(secondary)=${agg['cli_cost_usd_secondary']:.5f}"
              f"  cost_flags={agg['n_cost_flags']}  turn_cap_hit={agg['n_turn_cap_hit']}"
              f"  turn_check_violations={agg['n_turn_check_violations']}")
        for p in agg["per_pr"]:
            print(f"    {p['id']:20s} P={p['precision']:.2f} R={p['recall']:.2f} F1={p['f1']:.2f}"
                  f"  tp={p['tp']} fp={p['fp']} fn={p['fn']}  preds={p['n_pred_findings']} gt={p['n_gt_issues']}")
        for s in scored:
            if "_detail" in s:
                d = s["_detail"]
                print(f"\n  --- EXPLAIN {s['id']} ---")
                print(f"  matched GT {d['matched_gt']} | unmatched GT {d['unmatched_gt']} | unmatched preds {d['unmatched_pred']}")
                for g in d["ground_truth"]:
                    mark = "MATCH" if g["idx"] in d["matched_gt"] else "miss "
                    print(f"    [{mark}] gt{g['idx']:2d} {g['file']}:{g['lines'][0]}-{g['lines'][1]} :: {g['title']}")
                for p in d["predictions"]:
                    mark = "USED " if p["idx"] not in d["unmatched_pred"] else "extra"
                    print(f"    [{mark}] p{p['idx']:2d} [{p['severity']}] {p['files'][:1]} {p['lines']} :: {p['title']}")

    if args.out:
        Path(args.out).write_text(json.dumps(out_all, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
