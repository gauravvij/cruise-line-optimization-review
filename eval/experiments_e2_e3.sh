#!/usr/bin/env bash
# E2 effort sweep + E3 prompt variants — anthropic/claude-haiku-5.5 (E1 winner),
# fixed 4-PR slice, --concurrency 1, hard budget guard.
#
# E2: effort low / medium / high (high is reused from e1_haiku55, same slice/prompt).
# E3: prompt variants v1_recall and v4_recall_anchor, compared against the
#     haiku-5.5 high / baseline-prompt run (e1_haiku55).
#
# Usage: bash eval/experiments_e2_e3.sh
set -u
cd /home/azureuser/optimize-cruiseline

SLICE="firefox-ios#1,aspnetcore#2,tauri#10,redis#5"
TASK_START=16.186768157
BUDGET=4.0
STOP_AT=3.90          # hard stop: leave headroom for judge calls

KEY=$(python3 -c "import json;print(json.load(open('/home/azureuser/.config/openrouter/config'))['api_key'])")
spend() { curl -s --max-time 30 https://openrouter.ai/api/v1/key -H "Authorization: Bearer $KEY" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['usage_monthly'])"; }

guard() { # returns 0 (true) if we must STOP
  local used; used=$(python3 -c "print($(spend) - $TASK_START)")
  python3 -c "import sys;sys.exit(0 if $used > $STOP_AT else 1)"
}

run_cfg() { # model effort tag [prompt_file]
  local model="$1" effort="$2" tag="$3" pf="${4:-}"
  if guard; then
    echo "### BUDGET GUARD: task spend > \$$STOP_AT — SKIPPING $tag"
    return 1
  fi
  local before; before=$(spend)
  echo "### RUN $tag (model=$model effort=$effort prompt=${pf:-baseline})"
  if [ -n "$pf" ]; then
    node --experimental-strip-types eval/run_review.mjs \
      --model "$model" --effort "$effort" --max-turns 60 --prompt-file "$pf" \
      --prs "$SLICE" --tag "$tag" --out eval/results/raw --concurrency 1 --timeout 1500
  else
    node --experimental-strip-types eval/run_review.mjs \
      --model "$model" --effort "$effort" --max-turns 60 \
      --prs "$SLICE" --tag "$tag" --out eval/results/raw --concurrency 1 --timeout 1500
  fi
  local after; after=$(spend)
  python3 -c "print('### %s cost \$%.4f | task spend now \$%.4f' % ('$tag', $after - $before, $after - $TASK_START))"
}

echo "===== E2: effort sweep on anthropic/claude-haiku-5.5 ====="
run_cfg "anthropic/claude-haiku-5.5" low    e2_haiku_low
run_cfg "anthropic/claude-haiku-5.5" medium e2_haiku_medium
# effort=high already measured as e1_haiku55 on the identical slice

echo "===== E3: prompt variants on anthropic/claude-haiku-5.5 @ high ====="
run_cfg "anthropic/claude-haiku-5.5" high e3_v1_recall       eval/prompts/v1_recall.txt
run_cfg "anthropic/claude-haiku-5.5" high e3_v4_recall_anchor eval/prompts/v4_recall_anchor.txt

echo "===== DONE. Task spend: \$$(python3 -c "print($(spend) - $TASK_START)") ====="
