#!/usr/bin/env bash
# Zero-cost verification of the harness v2 turn cap (no model calls).
# The claude CLI is replaced by eval/test_suite/fake_claude.mjs.
#   CAP TEST 1: 10 distinct assistant message ids, maxTurns=3 -> must set turn_cap_hit=true
#   CAP TEST 2: 10 stream lines sharing one message id, maxTurns=3 -> counted=1, no cap
set -u
cd /home/azureuser/optimize-cruiseline
OUT=/tmp/captest
rm -rf "$OUT"
export CLAUDE_BIN=/home/azureuser/optimize-cruiseline/eval/test_suite/fake_claude.mjs

echo "=== CAP TEST 1: distinct message ids x10, maxTurns=3 ==="
FAKE_MODE=distinct FAKE_N=10 node --experimental-strip-types eval/run_review.mjs \
  --model claude-haiku-5-5 --effort medium --max-turns 3 \
  --prompt-file eval/prompts/baseline_original.txt --prs "redis#5" \
  --tag captest_distinct --out "$OUT" --concurrency 1 --timeout 120
echo "exit=$?"

echo "=== CAP TEST 2: one shared message id x10 lines, maxTurns=3 ==="
FAKE_MODE=streamed FAKE_N=10 node --experimental-strip-types eval/run_review.mjs \
  --model claude-haiku-5-5 --effort medium --max-turns 3 \
  --prompt-file eval/prompts/baseline_original.txt --prs "redis#5" \
  --tag captest_streamed --out "$OUT" --concurrency 1 --timeout 120
echo "exit=$?"

echo "=== records ==="
python3 - <<'EOF'
import json
for t in ['captest_distinct', 'captest_streamed']:
    d = json.load(open(f'/tmp/captest/{t}__redis_5.json'))
    keys = ['num_turns_counted', 'turn_trace', 'turn_cap_hit', 'turn_cap_reason',
            'turn_check_ok', 'subtype', 'cost_usd', 'cost_flag', 'schema_valid',
            'harness_version', 'prompt_sha256']
    print(t, {k: d.get(k) for k in keys})
EOF
