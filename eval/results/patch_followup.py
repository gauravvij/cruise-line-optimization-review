#!/usr/bin/env python3
import json
from pathlib import Path
ROOT=Path('/home/azureuser/optimize-cruiseline')
RES=ROOT/'eval/results'
p=RES/'validation_round2.json'
d=json.loads(p.read_text())
boot_opus=json.loads((RES/'bootstrap_opus.json').read_text())
def agg(tag):
    return json.loads((RES/'scored'/f'{tag}.json').read_text())['aggregate']
def summ(tag):
    return json.loads((RES/'raw'/f'{tag}__summary.json').read_text())
opus=agg('r2_holdout_opus_baseline')
test=agg('r2_opus_test_dify11')
osumm=summ('r2_holdout_opus_baseline')
tsumm=summ('r2_opus_test_dify11')
final=3.438574282
anchor=0.606793757
d['status']='complete'
d['generated_utc']='2026-11-17T14:00:00+00:00'
# paid runs: add opus + test, remove skipped opus entry
d['paid_runs']['executed'].extend([
 {"tag":"r2_holdout_opus_baseline","desc":"follow-up holdout c: opus-5.5 @ high + ORIGINAL baseline prompt, 16 PRs (PARTIAL: 8/16 schema-valid; 8 PRs failed with OpenRouter 402 credit-reservation errors)","cost_usd":opus['total_cost_usd'],"micro_f1":opus['micro_f1'],"micro_precision":opus['micro_precision'],"micro_recall":opus['micro_recall'],"tp":opus['micro_tp'],"fp":opus['micro_fp'],"fn":opus['micro_fn'],"schema_validity_rate":opus['schema_validity_rate'],"judge_failures":opus['judge_failures'],"judge_calls":opus['judge_calls'],"judge_pairs":opus['judge_pairs'],"n_cost_flags":osumm['n_cost_flags'],"run_spend_delta_usd":osumm['run_spend_delta_usd']},
 {"tag":"r2_opus_test_dify11","desc":"follow-up diagnostic single-PR test: opus-5.5 @ high + baseline prompt on dify#11 with CLAUDE_CODE_MAX_OUTPUT_TOKENS=16000 (fix verification; NOT part of holdout tag)","cost_usd":test['total_cost_usd'],"micro_f1":test['micro_f1'],"micro_precision":test['micro_precision'],"micro_recall":test['micro_recall'],"tp":test['micro_tp'],"fp":test['micro_fp'],"fn":test['micro_fn'],"schema_validity_rate":test['schema_validity_rate'],"judge_failures":test['judge_failures']},
])
d['paid_runs']['skipped']=[
 {"run":"holdout c completion: remaining 7 PRs (firefox-ios#12,#13 prefect#5,#10 redis#6 tauri#1,#9) after 402 failures","status":"aborted_budget_cap","reason":"Follow-up delta after partial opus run + diagnostic test + scoring was $2.8318 of $4.00 cap (remaining $1.1682). Remaining 7 PRs at measured opus rate ~$0.28/PR (8 valid PRs averaged $0.28; dify#11 test $0.2438) project to ~$1.96, which would exceed the $4.00 additional cap. Per task instruction to abort and report if cap would be exceeded, no further paid runs were launched. The 402 root cause and verified fix are recorded in followup_round so a future round can complete the holdout."}
]
d['followup_round']={
 "key_label":"sk-or-v1-fa8...7b3","key_ends":"7b3","anchor_usage_monthly":anchor,"budget_usd":4.0,
 "final_usage_monthly":final,"total_followup_spend_usd":round(final-anchor,6),"remaining_of_cap_usd":round(4.0-(final-anchor),6),
 "per_step":[
  {"step":"opus holdout run r2_holdout_opus_baseline (16 PRs attempted)","usage_monthly_after":osumm['spend_after'],"run_spend_delta_usd":osumm['run_spend_delta_usd'],"sum_key_delta_cost_usd":osumm['sum_key_delta_cost_usd']},
  {"step":"diagnostic test r2_opus_test_dify11 (dify#11, CLAUDE_CODE_MAX_OUTPUT_TOKENS=16000)","usage_monthly_after":tsumm['spend_after'],"run_spend_delta_usd":tsumm['run_spend_delta_usd']},
  {"step":"scoring r2_holdout_opus_baseline + r2_opus_test_dify11 (LLM judge, deepseek-v4.1-flash default)","usage_monthly_after":3.435340357},
  {"step":"final reading","usage_monthly_after":final}
 ],
 "opus_run":{
  "tag":"r2_holdout_opus_baseline","model":"anthropic/claude-opus-5.5","effort":"high","prompt_file":"eval/prompts/baseline_original.txt","prompt_sha256":"735dd8152a41cf235e62736f86f6d32f55cdc21839edd2bdefaa43b624e93e16","harness_version":"877ac98b39664866","concurrency":1,
  "n_prs":16,"n_schema_valid":8,"schema_validity_rate":0.5,"micro_f1":opus['micro_f1'],"micro_precision":opus['micro_precision'],"micro_recall":opus['micro_recall'],"tp":opus['micro_tp'],"fp":opus['micro_fp'],"fn":opus['micro_fn'],"total_cost_usd":opus['total_cost_usd'],"n_cost_flags":osumm['n_cost_flags'],"judge_failures":opus['judge_failures'],
  "per_pr_costs":[{"id":x['id'],"cost_usd":x['cost_usd'],"schema_valid":x['schema_valid'],"cost_flag":x.get('cost_flag')} for x in opus['per_pr']],
  "failed_prs":["dify#11","firefox-ios#12","firefox-ios#13","prefect#5","prefect#10","redis#6","tauri#1","tauri#9"],
  "failure_root_cause":"OpenRouter 402: CLI requests max_tokens=128000 (model max_completion_tokens); OpenRouter reserves 128000 * $0.00002 = $2.56 against account remaining before the request. After 8 PRs account remaining fell below $2.56, so PRs 9-16 were rejected with 'API Error: 402 This request requires more credits, or fewer max_tokens... can only afford ~114k'. Records show is_error=true, exit_code=1, structured_output missing, zero tokens used. This is a billing/reservation failure, not a quality failure.",
  "fix_verified":"CLAUDE_CODE_MAX_OUTPUT_TOKENS=16000 caps the CLI request max_tokens (CLI reads this env var; verified in CLI binary and by test run). Diagnostic tag r2_opus_test_dify11 on dify#11 with this env var: schema-valid 1/1, F1 0.667 (tp3 fp0 fn3), cost $0.2438, no cost flags. Fix was verified AFTER the main run; main-run records were not re-run with it because remaining budget ($1.1682) cannot cover the 7 remaining PRs (~$1.96 projected).",
  "partial_run_warning":"Opus micro F1 0.320 is computed over all 16 PRs with 8 failed PRs scoring F1 0. It is a lower bound biased downward by billing failures, not a clean quality estimate. On the 8 valid PRs opus precision was high (0.667 overall) but recall low (0.211 overall, dragged by zeros)."
 },
 "statistics_opus":boot_opus
}
d['statistics']={
 "bootstrap":json.loads((RES/'bootstrap_r2.json').read_text()),
 "bootstrap_opus":boot_opus,
 "winner_declared":False,
 "reason":"Two independent reasons: (1) haiku v4 vs haiku baseline paired CI [-0.0354,+0.1160] includes zero; (2) opus holdout is partial (8/16 valid, 8 billing 402 failures scoring 0), so the haiku-v4 minus opus-baseline CI [+0.0926,+0.4417] excluding zero reflects missing opus data, not demonstrated quality superiority. No winner declared."
}
d['spend']['per_step'].extend([
 {"step":"follow-up opus holdout run r2_holdout_opus_baseline","usage_monthly_after":osumm['spend_after']},
 {"step":"follow-up diagnostic test r2_opus_test_dify11","usage_monthly_after":tsumm['spend_after']},
 {"step":"follow-up scoring (judge)","usage_monthly_after":3.435340357},
 {"step":"follow-up final reading","usage_monthly_after":final}
])
d['spend']['followup_anchor_usage_monthly']=anchor
d['spend']['followup_total_usd']=round(final-anchor,6)
d['spend']['followup_under_budget']=True
d['verdict_original_claim']="INCONCLUSIVE. The claim 'haiku-5.5 @ medium + v4 beats opus-5.5 @ high on quality' is neither supported nor refuted. The follow-up opus holdout ran but is partial: 8/16 PRs schema-valid (F1 0.320 over 16 PRs, tp24 fp12 fn90, $2.7227); the other 8 PRs failed with OpenRouter 402 credit-reservation errors (CLI max_tokens=128000 reserves $2.56) and score F1 0, so the opus estimate is biased downward and cannot support a quality comparison. The paired CI for haiku-v4 minus opus-baseline (+0.247, 95% CI [+0.093,+0.442]) excludes zero only because half the opus data is missing, not because opus quality was measured lower. Separately, haiku v4 vs haiku baseline remains +0.033, CI [-0.035,+0.116] including zero. A clean verdict requires completing the 7 remaining opus PRs with CLAUDE_CODE_MAX_OUTPUT_TOKENS=16000 in a future round with ~$2.00 additional budget."
d['open_items']=[
 "Complete opus holdout: 7 PRs remain (firefox-ios#12,#13 prefect#5,#10 redis#6 tauri#1,#9). Use CLAUDE_CODE_MAX_OUTPUT_TOKENS=16000 (verified fix) and ~$2.00 additional budget. Then re-run paired bootstrap for haiku-v4 minus opus-baseline on complete 16/16 data.",
 "Schema-invalid runs occur occasionally when the CLI emits no structured output; these score F1 0 for that PR and add variance."
]
p.write_text(json.dumps(d,indent=1))
print('patched', p)
print(json.dumps({'followup_total':round(final-anchor,6),'opus_f1':opus['micro_f1'],'boot_opus':boot_opus},indent=1))
