#!/usr/bin/env bash
# Serialized cost calibration: one config at a time, authoritative key-delta accounting.
# Usage: bash eval/calibrate.sh
set -u
cd /home/azureuser/optimize-cruiseline
KEY=$(python3 -c "import json;print(json.load(open('/home/azureuser/.config/openrouter/config'))['api_key'])")
spend() { curl -s --max-time 30 https://openrouter.ai/api/v1/key -H "Authorization: Bearer $KEY" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['usage_monthly'])"; }

run() { # model effort maxTurns prs tag
  local model="$1" effort="$2" mt="$3" prs="$4" tag="$5"
  local before after
  before=$(spend)
  node --experimental-strip-types eval/run_review.mjs \
    --model "$model" --effort "$effort" --max-turns "$mt" --prs "$prs" \
    --tag "$tag" --out eval/results/calib --concurrency 1 --timeout 900 2>&1 \
    | grep -E "^\[1/|^\[2/|DONE" || true
  after=$(spend)
  python3 -c "print('  KEY-DELTA $tag: \$%.6f' % ($after - $before))"
}

echo "### calibration on tauri#9 (small diff: 14 files / 236 lines) ###"
run deepseek/deepseek-v4.1-flash-1017 low    60 tauri#9 cal_ds_low
run deepseek/deepseek-v4.1-flash-1017 medium 60 tauri#9 cal_ds_med
run deepseek/deepseek-v4.1-flash-1017 high   60 tauri#9 cal_ds_high
echo "### other cheap candidates ###"
run qwen/qwen3-coder-next              high   60 tauri#9 cal_qwen_high
run z-ai/glm-5.2                       high   60 tauri#9 cal_glm_high
run anthropic/claude-haiku-5.5         high   60 tauri#9 cal_haiku_high
echo "### total spend ###"
spend
