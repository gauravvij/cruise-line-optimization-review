#!/usr/bin/env node
/**
 * Apply the E3/E4 winning prompt to the repo.
 *
 * The winning variant (v4_recall_anchor) is the repo's REAL SYSTEM_PROMPT plus an
 * appended "Completeness pass" + "Anchoring accuracy" section. This script appends
 * exactly that section to the SYSTEM_PROMPT template literal in
 * agent/analysis/prompt.ts, escaping backticks/`${` so the literal stays valid.
 *
 * It verifies byte-exactness both ways:
 *   1. re-escaping the ORIGINAL SYSTEM_PROMPT must reproduce the file's current
 *      body verbatim (proves the escaping function is faithful), and
 *   2. importing SYSTEM_PROMPT from the edited file must equal
 *      original + appended section (proves the applied change is the winner).
 *
 * Usage: node --experimental-strip-types eval/apply_winner.mjs [--check]
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const REPO = '/home/azureuser/optimize-cruiseline/cruise-line';
const PROMPT_TS = join(REPO, 'agent', 'analysis', 'prompt.ts');
const VARIANT = '/home/azureuser/optimize-cruiseline/eval/prompts/v4_recall_anchor.txt';
const CHECK = process.argv.includes('--check');

const { SYSTEM_PROMPT } = await import(PROMPT_TS);
const variantText = readFileSync(VARIANT, 'utf-8');

// The variant file is <original SYSTEM_PROMPT><appended section>. Extract the delta.
if (!variantText.startsWith(SYSTEM_PROMPT)) {
  console.error('FATAL: variant file does not start with the current SYSTEM_PROMPT');
  process.exit(1);
}
const ADDITION = variantText.slice(SYSTEM_PROMPT.length);
console.log(`current SYSTEM_PROMPT : ${SYSTEM_PROMPT.length} chars`);
console.log(`appended section      : ${ADDITION.length} chars`);
console.log(`target SYSTEM_PROMPT  : ${variantText.length} chars`);

/** Escape a raw string so it can be embedded in a JS template literal. */
function escapeTemplate(s) {
  return s.replace(/\\/g, '\\\\').replace(/`/g, '\\`').replace(/\$\{/g, '\\${');
}

const src = readFileSync(PROMPT_TS, 'utf-8');
const marker = 'export const SYSTEM_PROMPT = `';
const start = src.indexOf(marker);
if (start < 0) { console.error('FATAL: SYSTEM_PROMPT declaration not found'); process.exit(1); }
const bodyStart = start + marker.length;
// closing delimiter is the first unescaped backtick followed by `;` at line end
const endRe = /`;/g;
let bodyEnd = -1;
endRe.lastIndex = bodyStart;
for (let m; (m = endRe.exec(src)); ) {
  const before = src.slice(bodyStart, m.index);
  // count trailing backslashes; even => the backtick is a real terminator
  const bs = (before.match(/\\+$/) || [''])[0].length;
  if (bs % 2 === 0) { bodyEnd = m.index; break; }
}
if (bodyEnd < 0) { console.error('FATAL: could not locate SYSTEM_PROMPT terminator'); process.exit(1); }

const fileBody = src.slice(bodyStart, bodyEnd);
// 1) escaping fidelity check against the ORIGINAL prompt
if (escapeTemplate(SYSTEM_PROMPT) !== fileBody) {
  console.error('FATAL: re-escaping the imported SYSTEM_PROMPT does not reproduce the file body');
  console.error('  file body len', fileBody.length, 'vs escaped len', escapeTemplate(SYSTEM_PROMPT).length);
  process.exit(1);
}
console.log('escaping fidelity check: OK (re-escaped original matches the file verbatim)');

if (CHECK) {
  console.log('--check mode: no write performed');
  process.exit(0);
}

const newBody = escapeTemplate(SYSTEM_PROMPT + ADDITION);
const updated = src.slice(0, bodyStart) + newBody + src.slice(bodyEnd);
writeFileSync(PROMPT_TS, updated);
console.log(`wrote ${PROMPT_TS} (${src.length} -> ${updated.length} chars)`);
