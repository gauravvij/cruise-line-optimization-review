#!/usr/bin/env bash
# Free (no model calls) verification for validation round 2.
# Only GET requests to the OpenRouter key endpoint are made (no billable calls).
set -u
cd /home/azureuser/optimize-cruiseline

echo "=== 1. syntax checks ==="
node --check eval/run_review.mjs && echo "run_review.mjs: OK"
node --check eval/extract_baseline_prompt.mjs && echo "extract_baseline_prompt.mjs: OK"
python3 -m py_compile eval/score.py && echo "score.py: OK"

echo "=== 2. no silent default prompt in runner ==="
if grep -n "SYSTEM_PROMPT" eval/run_review.mjs | grep -v "^\s*[0-9]*:\s*\*" | grep -q "import\|systemPrompt ="; then
  grep -n "SYSTEM_PROMPT\|promptFile is required" eval/run_review.mjs
else
  echo "no SYSTEM_PROMPT import in runner"
fi
grep -n "prompt-file. is required" eval/run_review.mjs && echo "--prompt-file required: enforced"

echo "=== 3. prompt provenance ==="
sha256sum eval/prompts/baseline_original.txt eval/prompts/v4_recall_anchor.txt
cmp -s eval/prompts/baseline_original.txt eval/prompts/v4_recall_anchor.txt && echo "BAD: baseline == v4" || echo "baseline != v4: OK"
cruise_head=$(git -C cruise-line rev-parse HEAD)
echo "cruise-line HEAD=$cruise_head (baseline extracted from this commit)"

echo "=== 4. holdout pre-flight (manifest vs slice) ==="
python3 - <<'EOF'
import json, os
root = '/home/azureuser/optimize-cruiseline/eval'
man = json.load(open(f'{root}/manifest.json'))['prs']
sl = json.load(open(f'{root}/slice.json'))['experiment_slice']
slice_ids = {f"{p['repo']}#{p['num']}" for p in sl}
hold = [p for p in man if f"{p['repo']}#{p['num']}" not in slice_ids]
print('manifest PRs:', len(man), 'slice:', len(slice_ids), 'holdout:', len(hold))
from collections import Counter
by_repo = Counter(p['repo'] for p in hold)
print('holdout by repo:', dict(sorted(by_repo.items())))
print('holdout GT issues:', sum(p['num_of_issues'] for p in hold))
missing = [f"{p['repo']}#{p['num']}" for p in hold if not os.path.isdir(f"{root}/data/repos/{p['repo']}/.git")]
print('holdout PRs without local clone:', missing or 'none')
ids = [f"{p['repo']}#{p['num']}" for p in hold]
print('duplicates:', len(ids) - len(set(ids)), '| overlap with slice:', len(set(ids) & slice_ids))
EOF

echo "=== 5. OpenRouter spend sampling (GET only, 3 samples, 60s apart) ==="
python3 - <<'EOF'
import json, time, urllib.request, datetime
k = json.load(open('/home/azureuser/.config/openrouter/config'))['api_key']
for i in range(3):
    r = urllib.request.Request('https://openrouter.ai/api/v1/key', headers={'Authorization': 'Bearer ' + k})
    d = json.load(urllib.request.urlopen(r))['data']
    ts = datetime.datetime.now(datetime.timezone.utc).strftime('%H:%M:%S')
    print(ts, 'usage_monthly=%.6f usage_daily=%.6f' % (d['usage_monthly'], d['usage_daily']))
    if i < 2: time.sleep(60)
EOF

echo "=== 6. processes that could be making OpenRouter calls ==="
ps -o pid,ppid,etime,args -p 1035,600397,3940781,9830,3971914,3971926 2>/dev/null | cut -c1-200
echo "--- sockets to the two remote addresses seen earlier ---"
ss -tnp | grep -E "188.185.51.60|104.18.11.66" || echo "(none live)"
echo "--- user crontab / user timers ---"
crontab -l 2>/dev/null || echo "no crontab"
systemctl --user list-timers --no-pager 2>/dev/null | head -8 || echo "no user timers readable"
