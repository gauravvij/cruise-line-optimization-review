#!/usr/bin/env bash
# API-free gates for the cruise-line comment cleanup (validation round 2, step 6).
# The full `bun test` suite already fails on the pristine repo (pre-existing auth
# isolation + missing frontend module errors), so the gate is the prompt test plus tsc.
set -u
export PATH="$HOME/.bun/bin:$PATH"
cd /home/azureuser/optimize-cruiseline/cruise-line

echo "=== bun test agent/analysis/prompt.test.ts ==="
bun test agent/analysis/prompt.test.ts
echo "PROMPT_TEST_EXIT=$?"

echo "=== bunx tsc --noEmit ==="
bunx tsc --noEmit
echo "TSC_EXIT=$?"

echo "=== git diff stat (cleanup scope) ==="
git diff --stat -- agent/config.ts astropods.yml
