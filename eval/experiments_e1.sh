#!/usr/bin/env bash
# E1 model sweep driver — fixed experiment slice, --concurrency 1, budget-guarded.
#
# Runs the same prompt and effort (high, matching the baseline) across the model
# set on the SAME fixed slice used by the baseline. Cheap models first so partial
# progress is maximised if the budget guard trips.
#
# Usage: bash eval/experiments_e1.sh
set -u
cd /home/azureuser/optimize-cruiseline

SLICE="firefox-ios#1,aspnetcore#2,tauri#10,redis#5"
TASK_START=16.186768157
BUDGET=4.0
STOP_AT=3.85          # leave headroom for the judge calls and E2/E3

KEY=$(python3 -c "import json;print(json.load(open('/home/azureuser/.config/openrouter/config'))['api_key'])")
spend() { curl -s --max-time 30 https://openrouter.ai/api/v1/key -H "Authorization: Bearer $KEY" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['usage_monthly'])"; }

run_model() { # slug tag
  local slug="$1" tag="$2"
  local now; now=$(spend)
  local used; used=$(python3 -c "print($now - $TASK_START)")
  if python3 -c "import sys;sys.exit(0 if $used > $STOP_AT else 1)"; then
    echo "### BUDGET GUARD: task spend \$$used > \$$STOP_AT — skipping $slug"
    return 1
  fi
  echo "### E1 $tag ($slug) — task spend so far \$$used"
  node --experimental-strip-types eval/run_review.mjs \
    --model "$slug" --effort high --max-turns 60 \
    --prs "$SLICE" --tag "$tag" --out eval/results/raw \
    --concurrency 1 --timeout 1500
  local after; after=$(spend)
  python3 -c "print('### E1 %s total cost: \$%.4f  (task spend now \$%.4f)' % ('$tag', $after - $now, $after - $TASK_START))"
}

echo "=== E1 model sweep on fixed slice: $SLICE ==="
run_model "anthropic/claude-haiku-5.5"        e1_haiku55
run_model "qwen/qwen3-coder-next"             e1_qwen3coder
run_model "deepseek/deepseek-v4.1-flash-1017" e1_deepseek_flash
run_model "z-ai/glm-5.2"                      e1_glm52
run_model "anthropic/claude-sonnet-5.5"       e1_sonnet55

echo "=== E1 complete. Task spend: \$$(python3 -c "print($(spend) - $TASK_START)") ==="
