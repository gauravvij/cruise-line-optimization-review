#!/bin/bash
# Run a Haiku repeat on holdout48 with the round-3 spend anchor (whole-round $4.00 cap).
# Usage: bash eval/run_repeat.sh <tag> <prompt-file>
set -e
export CLAUDE_CODE_MAX_OUTPUT_TOKENS=16000
cd /home/azureuser/optimize-cruiseline
TAG="$1"; PROMPT="$2"
TASK_START_SPEND=5.495648601 BUDGET_USD=4.0 node --experimental-strip-types eval/run_review.mjs \
  --model anthropic/claude-haiku-5.5 --effort medium \
  --prompt-file "$PROMPT" \
  --out eval/results/raw --tag "$TAG" --concurrency 1
