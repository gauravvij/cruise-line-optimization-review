#!/usr/bin/env node
/**
 * Extracts the ORIGINAL (pre-optimization) SYSTEM_PROMPT from git HEAD of
 * cruise-line and writes it to eval/prompts/baseline_original.txt.
 *
 * Why: the working tree cruise-line/agent/analysis/prompt.ts already has
 * v4_recall_anchor applied (apply_winner.mjs), so importing SYSTEM_PROMPT from
 * the working tree silently yields the v4 prompt, not the baseline.
 *
 * Usage: node --experimental-strip-types eval/extract_baseline_prompt.mjs
 */
import { execFileSync } from 'node:child_process';
import { writeFileSync, mkdtempSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { createHash } from 'node:crypto';

const REPO = '/home/azureuser/optimize-cruiseline/cruise-line';
const OUT = '/home/azureuser/optimize-cruiseline/eval/prompts/baseline_original.txt';

const src = execFileSync('git', ['show', 'HEAD:agent/analysis/prompt.ts'], { cwd: REPO, encoding: 'utf-8' });
const dir = mkdtempSync(join(tmpdir(), 'orig-prompt-'));
const tmpTs = join(dir, 'prompt.ts');
writeFileSync(tmpTs, src);

const { SYSTEM_PROMPT } = await import(tmpTs);
if (typeof SYSTEM_PROMPT !== 'string' || SYSTEM_PROMPT.length < 1000) {
  throw new Error('extraction failed: SYSTEM_PROMPT missing or too short');
}
writeFileSync(OUT, SYSTEM_PROMPT);
const sha = createHash('sha256').update(SYSTEM_PROMPT).digest('hex');
const head = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: REPO, encoding: 'utf-8' }).trim();
console.log(JSON.stringify({ out: OUT, chars: SYSTEM_PROMPT.length, sha256: sha, cruise_line_head: head }, null, 1));
