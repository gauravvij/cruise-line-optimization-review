#!/usr/bin/env python3
"""Merge opus holdout raw records into a full-16 set for scoring.
Sources (no paid calls):
 - 8 schema-valid from r2_holdout_opus_baseline (harness 877ac98b39664866)
 - dify#11 from r2_opus_test_dify11 diagnostic (same harness, CLAUDE_CODE_MAX_OUTPUT_TOKENS=16000)
 - 7 retry from r2_holdout_opus_baseline_retry (harness 0abca51995d3f7cf, token cap in runner)
Output dir: eval/results/raw_merged_opus_full16 with tag r2_holdout_opus_baseline_full16
"""
import json, shutil
from pathlib import Path
ROOT=Path('/home/azureuser/optimize-cruiseline')
RAW=ROOT/'eval/results/raw'
OUT=ROOT/'eval/results/raw_merged_opus_full16'
OUT.mkdir(parents=True, exist_ok=True)
TAG='r2_holdout_opus_baseline_full16'
valid8=['Ghost#6','Ghost#8','Ghost#10','aspnetcore#4','cal.com#6','cal.com#14','dify#6','dify#10']
retry7=['firefox-ios#12','firefox-ios#13','prefect#5','prefect#10','redis#6','tauri#1','tauri#9']
def fname(repo,num): return f"{repo}_{num}.json"
def copy(src_tag, pr_id):
    repo,num=pr_id.split('#')
    src=RAW/f"{src_tag}__{fname(repo,num)}"
    dst=OUT/f"{TAG}__{fname(repo,num)}"
    shutil.copy(src,dst)
    print(f"copied {pr_id} from {src_tag}")
for pid in valid8: copy('r2_holdout_opus_baseline',pid)
copy('r2_opus_test_dify11','dify#11')
for pid in retry7: copy('r2_holdout_opus_baseline_retry',pid)
# summary from original, updated
summ=json.loads((RAW/'r2_holdout_opus_baseline__summary.json').read_text())
summ['tag']=TAG
summ['pr_list']=["Ghost#6","Ghost#8","Ghost#10","aspnetcore#4","cal.com#6","cal.com#14","dify#6","dify#10","dify#11","firefox-ios#12","firefox-ios#13","prefect#5","prefect#10","redis#6","tauri#1","tauri#9"]
summ['merged_from']={'original_valid8':'r2_holdout_opus_baseline','dify11':'r2_opus_test_dify11','retry7':'r2_holdout_opus_baseline_retry'}
summ['note']='Merged full-16 opus set; harness versions differ (877ac98b39664866 for 9, 0abca51995d3f7cf for 7 retry). Score with --allow-harness-mismatch.'
(OUT/f"{TAG}__summary.json").write_text(json.dumps(summ,indent=1))
print(f"wrote {OUT}/{TAG}__summary.json with {len(valid8)+1+len(retry7)} PRs")
