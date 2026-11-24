#!/usr/bin/env python3
import json, hashlib
from pathlib import Path
ROOT=Path('/home/azureuser/optimize-cruiseline')
RES=ROOT/'eval/results'
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def agg(tag): return json.loads((RES/'scored'/f'{tag}.json').read_text())['aggregate']
def summ(tag): return json.loads((RES/'raw'/f'{tag}__summary.json').read_text())
p=RES/'validation_round2.json'
d=json.loads(p.read_text())
anchor=3.438574282
final=5.493348639
retry_agg=agg('r2_holdout_opus_baseline_retry')
full_agg=agg('r2_holdout_opus_baseline_full16')
boot=json.loads((RES/'bootstrap_opus_full16.json').read_text())
# per-PR costs full16
per_pr=[{k:pp[k] for k in ('id','cost_usd','schema_valid','cost_flag')} for pp in full_agg['per_pr']]
d['retry_round']={
 "key_label":"sk-or-v1-fa8...7b3","key_ends":"7b3","key_limit_usd":20,
 "anchor_usage_monthly":anchor,"budget_usd":4.0,"final_usage_monthly":final,
 "total_retry_spend_usd":round(final-anchor,6),
 "note":"Credits added to same key ending 7b3; anchor verified via GET /key (usage_monthly 3.438574282, limit_remaining 16.561425718). Runner edited to set CLAUDE_CODE_MAX_OUTPUT_TOKENS=16000 in CLI env (eval/run_review.mjs); harness_version changed 877ac98b39664866 -> 0abca51995d3f7cf. Scored merged set with --allow-harness-mismatch.",
 "harness_version_new":"0abca51995d3f7cf",
 "run_review_mjs_sha256":sha(ROOT/'eval/run_review.mjs'),
 "score_py_sha256":sha(ROOT/'eval/score.py'),
 "failed_prs_rerun":["firefox-ios#12","firefox-ios#13","prefect#5","prefect#10","redis#6","tauri#1","tauri#9"],
 "dify11_note":"dify#11 already recovered diagnostically as r2_opus_test_dify11 (F1 0.667, $0.2438); not re-run in retry.",
 "retry_run":{"tag":"r2_holdout_opus_baseline_retry","model":"anthropic/claude-opus-5.5","effort":"high","prompt_file":"eval/prompts/baseline_original.txt","concurrency":1,"n_prs":7,"n_schema_valid":retry_agg['n_schema_valid'],"micro_f1":retry_agg['micro_f1'],"micro_precision":retry_agg['micro_precision'],"micro_recall":retry_agg['micro_recall'],"tp":retry_agg['micro_tp'],"fp":retry_agg['micro_fp'],"fn":retry_agg['micro_fn'],"total_cost_usd":retry_agg['total_cost_usd'],"judge_failures":retry_agg['judge_failures'],"cost_flag_note":"4 PRs key_delta_unsettled_after_30s (firefox-ios#13,prefect#5,prefect#10,redis#6) settled late and were captured in tauri#1 key-delta ($1.2742); whole-run usage delta is authoritative for total spend."},
 "full16_opus":{"tag":"r2_holdout_opus_baseline_full16","merged_from":{"original_valid8":"r2_holdout_opus_baseline","dify11":"r2_opus_test_dify11","retry7":"r2_holdout_opus_baseline_retry"},"model":"anthropic/claude-opus-5.5","effort":"high","prompt_file":"eval/prompts/baseline_original.txt","n_prs":16,"n_schema_valid":full_agg['n_schema_valid'],"schema_validity_rate":full_agg['schema_validity_rate'],"micro_f1":full_agg['micro_f1'],"micro_precision":full_agg['micro_precision'],"micro_recall":full_agg['micro_recall'],"tp":full_agg['micro_tp'],"fp":full_agg['micro_fp'],"fn":full_agg['micro_fn'],"total_cost_usd":full_agg['total_cost_usd'],"judge_failures":full_agg['judge_failures'],"per_pr_costs":per_pr},
 "bootstrap_full16":boot,
 "per_step":[
   {"step":"retry smoke firefox-ios#12","usage_monthly_after":3.652419282},
   {"step":"retry remaining 6 PRs run","usage_monthly_after":5.488529282},
   {"step":"scoring full16 + retry (LLM judge)","usage_monthly_after":5.492239796},
   {"step":"final reading","usage_monthly_after":final}
 ],
 "spend_check":round(final-anchor,6)
}
# update spend ledger
d['spend']['per_step'].extend([
 {"step":"retry-round anchor (credits added, same key 7b3)","usage_monthly_after":anchor},
 {"step":"retry smoke firefox-ios#12","usage_monthly_after":3.652419282},
 {"step":"retry remaining 6 PRs run","usage_monthly_after":5.488529282},
 {"step":"scoring full16 + retry (LLM judge)","usage_monthly_after":5.492239796},
 {"step":"retry-round final reading","usage_monthly_after":final}
])
d['spend']['retry_anchor_usage_monthly']=anchor
d['spend']['retry_total_usd']=round(final-anchor,6)
d['spend']['retry_under_budget']=round(final-anchor,6)<=4.0
d['statistics']['bootstrap_opus_full16']=boot
d['statistics']['winner_declared']=False
d['statistics']['reason']="Full-16 paired CI for haiku-v4 minus opus-baseline is [-0.0586,+0.0509] (observed -0.0086), includes zero. Haiku-v4 minus haiku-baseline CI [-0.0354,+0.1160] also includes zero. No winner declared."
d['verdict_original_claim']="INCONCLUSIVE. On complete 16/16 data, opus-baseline micro F1 is 0.576 (P0.757/R0.465, tp53 fp17 fn61) vs haiku-v4 0.567 and haiku-baseline 0.534. Paired diff haiku-v4 minus opus-baseline -0.009, 95% CI [-0.059,+0.051] includes zero, so claim 'haiku-5.5 @ medium + v4 beats opus-5.5 @ high on quality' is not supported. Haiku-v4 minus haiku-baseline +0.033 CI [-0.035,+0.116] also includes zero."
d['status']="complete"
d['open_items']=["Schema-invalid runs occur occasionally when CLI emits no structured output; retry round had 7/7 valid after token-cap fix.","4 retry PRs had key_delta_unsettled_after_30s; costs settled late and are included in whole-run delta."]
p.write_text(json.dumps(d,indent=1))
print("updated", round(final-anchor,6), full_agg['micro_f1'], boot)
