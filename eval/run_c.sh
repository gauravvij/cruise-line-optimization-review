#!/bin/bash
# Run Haiku config C (v4 prompt) on holdout48 with a fresh round-local spend anchor.
set -e
export CLAUDE_CODE_MAX_OUTPUT_TOKENS=16000
cd /home/azureuser/optimize-cruiseline
ANCHOR=$(python3 eval/spend_anchor.py)
echo "[run_c] fresh anchor usage_monthly=$ANCHOR"
TASK_START_SPEND=$ANCHOR BUDGET_USD=4.0 node --experimental-strip-types eval/run_review.mjs \
  --model anthropic/claude-haiku-5.5 --effort medium \
  --prompt-file eval/prompts/v4_recall_anchor.txt \
  --out eval/results/raw --tag h3_haiku_v4 --concurrency 1
