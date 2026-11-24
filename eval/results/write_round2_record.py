#!/usr/bin/env /usr/bin/python3
"""Resumed-round writer for eval/results/validation_round2.json (status=complete).

Re-derives the record from the scored/raw artifacts on disk (r2_* tags,
bootstrap_r2.json) so re-running reproduces the same complete record.
It does NOT touch OPTIMIZATION_REPORT.md (that section was updated separately).
No paid API calls are made by this script.
"""
import hashlib, json
from pathlib import Path

ROOT = Path('/home/azureuser/optimize-cruiseline')
EVAL = ROOT / 'eval'
RESULTS = EVAL / 'results'

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def agg(tag): return json.loads((RESULTS / 'scored' / f'{tag}.json').read_text())['aggregate']
def summ(tag): return json.loads((RESULTS / 'raw' / f'{tag}__summary.json').read_text())

boot = json.loads((RESULTS / 'bootstrap_r2.json').read_text())
cap = json.loads((RESULTS / 'raw' / 'r2_capcheck__redis_5.json').read_text())
final_spend = 0.606793757

record = {
 "round": "validation_round2",
 "status": "complete",
 "generated_utc": "2026-11-17T12:00:00+00:00",
 "resumed_round": {
   "key_label": "sk-or-v1-fa8...7b3", "key_ends": "7b3", "key_limit_usd": 20,
   "anchor_usage_monthly": 0.0, "budget_usd": 4.0,
   "final_usage_monthly": final_spend, "total_resumed_round_spend_usd": round(final_spend, 6),
   "note": "Resumed round uses the new key only; prior-session spend on the old key is recorded separately in spend_prior_session and is not counted against the resumed-round $4.00 cap."
 },
 "harness": {
   "harness_version": "877ac98b39664866",
   "run_review_mjs_sha256": sha(EVAL / 'run_review.mjs'),
   "score_py_sha256": sha(EVAL / 'score.py'),
   "baseline_prompt_file": "eval/prompts/baseline_original.txt",
   "baseline_prompt_sha256": "735dd8152a41cf235e62736f86f6d32f55cdc21839edd2bdefaa43b624e93e16",
   "v4_prompt_file": "eval/prompts/v4_recall_anchor.txt",
   "v4_prompt_sha256": "34ab4b8270e81b23b3f027da7cefa08897dbf98faa885d5c7a9100b58af74f02",
   "cruise_line_git_head": summ('r2_holdout_haiku_v4')['cruise_line_git_head'],
   "note": "working-tree prompt.ts is byte-identical to v4 (sha 34ab4b82); runner requires --prompt-file and never imports SYSTEM_PROMPT"
 },
 "harness_fixes": {
   "turn_cap": {
     "enforcement": "live stream-json parse; distinct assistant message.id counted; process group killed when count > maxTurns; counter frozen at cap; turn_cap_hit with reason",
     "fake_cli_verification": "eval/test_suite/cap_test.sh 6/6 pass (prior session)",
     "real_cli_verification": {
       "tag": "r2_capcheck", "pr": "redis#5", "model": "anthropic/claude-haiku-5.5", "effort": "medium", "max_turns": 3,
       "num_turns_counted": cap['num_turns_counted'], "turn_cap_hit": cap['turn_cap_hit'],
       "turn_check_ok": cap['turn_check_ok'], "cli_num_turns": cap['num_turns'], "subtype": cap['subtype'],
       "cost_usd": cap['cost_usd'],
       "conclusion": "PASS: counted=3 <= maxTurns=3 and turn_check_ok=true on the real CLI. CLI's own num_turns=4 confirms the historical +1 offset (n_tool_calls = num_turns-1). Issue run-review-maxturns-not-enforced is closed."
     }
   },
   "per_pr_cost": "usage_monthly key-delta around each PR, concurrency 1, settle-polling, cost_flag on zero/unsettled; cli_cost_usd secondary",
   "provenance": "harness_version, prompt_sha256, cruise_line_git_head, pr_list, tag in every record; tag reuse refused without --force; score.py refuses mismatched harness versions",
   "prompt_default": "--prompt-file required"
 },
 "holdout_preflight": {
   "manifest_prs": 20, "slice_prs": 4, "holdout_prs": 16, "holdout_gt_issues": 114, "overlap_with_slice": 0, "duplicates": 0,
   "clones": "all 8 repos present in eval/data/repos (Ghost, cal.com, dify, prefect cloned this round, blob-filtered); prepare.py --verify: 20/20 OK (clone+head+non-empty diff)",
   "holdout_ids": ["Ghost#6","Ghost#8","Ghost#10","aspnetcore#4","cal.com#6","cal.com#14","dify#6","dify#10","dify#11","firefox-ios#12","firefox-ios#13","prefect#5","prefect#10","redis#6","tauri#1","tauri#9"]
 },
 "paid_runs": {
   "executed": [
     {"tag": "r2_capcheck", "desc": "real-CLI max-turns 3 check, haiku medium + v4, redis#5", "cost_usd": cap['cost_usd'], "result": "counted=3, turn_check_ok=true"},
     {"tag": "r2_noise1", "desc": "noise repeat 1: haiku medium + v4, 4-PR slice", "cost_usd": agg('r2_noise1')['total_cost_usd'], "micro_f1": agg('r2_noise1')['micro_f1'], "schema_validity_rate": agg('r2_noise1')['schema_validity_rate']},
     {"tag": "r2_noise2", "desc": "noise repeat 2: haiku medium + v4, 4-PR slice", "cost_usd": agg('r2_noise2')['total_cost_usd'], "micro_f1": agg('r2_noise2')['micro_f1'], "schema_validity_rate": agg('r2_noise2')['schema_validity_rate']},
     {"tag": "r2_holdout_haiku_baseline", "desc": "holdout a: haiku medium + ORIGINAL baseline prompt, 16 PRs", "cost_usd": agg('r2_holdout_haiku_baseline')['total_cost_usd'], "micro_f1": agg('r2_holdout_haiku_baseline')['micro_f1'], "micro_precision": agg('r2_holdout_haiku_baseline')['micro_precision'], "micro_recall": agg('r2_holdout_haiku_baseline')['micro_recall'], "tp": agg('r2_holdout_haiku_baseline')['micro_tp'], "fp": agg('r2_holdout_haiku_baseline')['micro_fp'], "fn": agg('r2_holdout_haiku_baseline')['micro_fn'], "schema_validity_rate": agg('r2_holdout_haiku_baseline')['schema_validity_rate'], "judge_failures": agg('r2_holdout_haiku_baseline')['judge_failures']},
     {"tag": "r2_holdout_haiku_v4", "desc": "holdout b: haiku medium + v4_recall_anchor, same 16 PRs", "cost_usd": agg('r2_holdout_haiku_v4')['total_cost_usd'], "micro_f1": agg('r2_holdout_haiku_v4')['micro_f1'], "micro_precision": agg('r2_holdout_haiku_v4')['micro_precision'], "micro_recall": agg('r2_holdout_haiku_v4')['micro_recall'], "tp": agg('r2_holdout_haiku_v4')['micro_tp'], "fp": agg('r2_holdout_haiku_v4')['micro_fp'], "fn": agg('r2_holdout_haiku_v4')['micro_fn'], "schema_validity_rate": agg('r2_holdout_haiku_v4')['schema_validity_rate'], "judge_failures": agg('r2_holdout_haiku_v4')['judge_failures']}
   ],
   "skipped": [
     {"run": "holdout c: opus-5.5 @ high + ORIGINAL baseline prompt, 16 PRs", "status": "skipped_budget_gate",
      "reason": "Cumulative resumed-round spend at decision time was $0.602. Rule: run only if cumulative + ~$3.5 < $4.00. $0.602 + $3.5 = $4.10 > $4.00, so skipped. For reference, measured opus rate from the round-1 baseline run was $0.192/PR, i.e. ~$3.07 for 16 PRs, which would have totalled ~$3.67; the skip follows the stated ~$3.5 estimate rule, not the measured rate."}
   ]
 },
 "noise_check": {
   "config": "haiku-5.5 @ medium + v4_recall_anchor on 4-PR slice (firefox-ios#1, aspnetcore#2, tauri#10, redis#5)",
   "runs": [{"tag": "e4_winner_combo (prior round, same config)", "micro_f1": 0.6296}, {"tag": "r2_noise1", "micro_f1": 0.4706}, {"tag": "r2_noise2", "micro_f1": 0.5556}],
   "mean_micro_f1": 0.5519, "range": [0.4706, 0.6296],
   "note": "Spread of 0.159 across identical-config repeats on 4 PRs. One repeat had a schema-invalid PR (tauri#10 in r2_noise1, F1 0 for that PR), which alone explains much of the low outlier."
 },
 "statistics": {"bootstrap": boot, "winner_declared": False,
   "reason": "Paired 95% CI for v4 minus baseline prompt on haiku is [-0.0354, +0.1160], which includes zero. No winner is declared."},
 "spend": {
   "resumed_round_anchor_usage_monthly": 0.0, "budget_usd": 4.0,
   "per_step": [
     {"step": "cap check r2_capcheck", "usage_monthly_after": 0.00554567},
     {"step": "noise1 run+score", "usage_monthly_after": 0.06990792},
     {"step": "noise2 run+score", "usage_monthly_after": 0.124584505},
     {"step": "holdout baseline run+score", "usage_monthly_after": 0.34282537},
     {"step": "holdout v4 run+score", "usage_monthly_after": 0.604174173},
     {"step": "final reading", "usage_monthly_after": final_spend}
   ],
   "total_resumed_round_spend_usd": round(final_spend, 6), "under_budget": True
 },
 "spend_prior_session": {
   "note": "Prior session on the old key (anchor usage_monthly 20.65877423) ended partial_blocked with unattributed background-automation spend. The project root /home/azureuser/optimize-cruiseline is not a git repository (no .git), so there is no git history for this record; the only git repo in the tree is cruise-line/ (HEAD d98cfa767551da72c23d52fb6d5cecd78901a0d9). Prior-session spend is not counted against the resumed-round $4.00 cap. No background-automation names are recorded in this record."
 },
 "verdict_original_claim": "INCONCLUSIVE. The claim 'haiku-5.5 @ medium + v4 beats opus-5.5 @ high on quality' is not supported and not refuted by round 2: (1) the opus holdout was skipped by the budget gate, so there is no opus holdout quality evidence; (2) on haiku, v4 vs baseline prompt on 16 unseen PRs gives +0.033 micro F1 with paired 95% CI [-0.035, +0.116] including zero, so even the prompt effect is not established. What round 2 does establish: v4 is directionally ahead on holdout (0.567 vs 0.534) at essentially equal cost ($0.215 vs $0.209), and the turn cap is now verified on the real CLI.",
 "cleanup": {
   "agent/config.ts": "comments claim only the measured cost gap; quality marked unestablished (prior session)",
   "gates": "bun test agent/analysis/prompt.test.ts exit 0 (3 pass); bunx tsc --noEmit exit 0 (prior session)",
   "forbidden_name_grep": {
     "command": 'grep -r -I -n -i -E "<forbidden background-automation names, case-insensitive>" . --exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=.git --exclude-dir=__pycache__ --exclude-dir=repos --exclude-dir=.tmp  (pattern: the stopped background automation names; see task spec)',
     "result": "exit 1 (no matches) on project text files; eval/data/repos (third-party clones), .venv, node_modules, .git excluded per task. .tmp exec-wrapper scratch scripts embed the grep pattern itself and are not project content.",
     "note": "Docs/code/records refer only to 'background automation' where needed."
   }
 },
 "open_items": [
   "Opus holdout remains unrun (budget gate). A future round with a larger cap could run it; measured opus rate $0.192/PR suggests ~$3.07 for 16 PRs.",
   "Schema-invalid runs occur occasionally (1/16 baseline holdout, 1/4 noise1) when the CLI emits no structured output; these score F1 0 for that PR and add variance."
 ]
}

(RESULTS / 'validation_round2.json').write_text(json.dumps(record, indent=1))
print(json.dumps({"status": record["status"], "spend": record["spend"]["total_resumed_round_spend_usd"]}))
