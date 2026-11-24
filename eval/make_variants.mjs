#!/usr/bin/env node
/**
 * Generate SYSTEM_PROMPT variants for the E3 prompt-optimization experiment.
 *
 * Each variant is the repo's REAL SYSTEM_PROMPT plus one targeted appended
 * section, so the experiment isolates a single prompt lever instead of
 * rewriting the production prompt. Writes to eval/prompts/<name>.txt; the
 * runner consumes them via --prompt-file.
 */
import { writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';

const REPO = '/home/azureuser/optimize-cruiseline/cruise-line';
const OUT = '/home/azureuser/optimize-cruiseline/eval/prompts';
const { SYSTEM_PROMPT } = await import(join(REPO, 'agent', 'analysis', 'prompt.ts'));

/** V1 — completeness / recall pass. Targets missed distinct defects. */
const V1_RECALL = `

## Completeness pass (do this before you finish)

A review that reports only two or three findings on a diff touching many files is almost always
incomplete. Work through the change systematically instead of stopping at the first problems you
notice:

1. Walk every changed file in the diff, one at a time. Read it with the tools and ask "what could
   be wrong here?". Do not skip a file because it looks routine — test files, config files,
   lockfiles, generated files, changelogs and one-line edits all contain defects.
2. Emit exactly one finding per distinct defect. Do not merge two unrelated defects into a single
   finding, and do not split one defect across several findings.
3. Actively check these high-yield categories, which reviewers most often miss:
   - inverted, off-by-one, or wrong-operator conditions
   - a call removed from an initialization/cleanup list while its import is left behind
   - a required constructor or function argument dropped from a call site
   - a value hard-coded where a previously saved or configured value should be restored
   - a rename or signature change applied in one place but not another (stale references, shadowing)
   - a declaration missing a required modifier (static, final, const, export, access modifier)
   - a newly added file missing a license header or include guard
   - an unused variable or import that will fail a -Werror build
   - a comment or docstring that contradicts the code next to it
   - version strings that disagree between manifest, changelog, and lockfile
   - a test whose assertion can never fail, or a test helper that contradicts the implementation
   - an NPM/yarn/other tooling instruction that contradicts the project's convention
4. Favour recall over brevity: a defensible \`low\` finding is better than a silent omission.`;

/** V2 — severity calibration and concrete consequences. */
const V2_SEVERITY = `

## Severity discipline

Justify every finding by the code in front of you, not by the category it belongs to.

- \`critical\` — reserve for defects that break the build, corrupt or lose data, open a security
  hole, or make a core feature non-functional. If you cannot name the concrete failure (the input,
  the crash, the lost write), it is not \`critical\`.
- \`high\` — a real bug reached in normal use, or a change that silently disables existing behaviour.
- \`medium\` — a defect with a narrower trigger: an edge case, missing validation, or a wrong value
  in one configuration.
- \`low\` — style, consistency, naming, documentation, or a theoretical concern.
- \`info\` — observations and positive notes only.

Rules:
- Do not inflate severity to make a finding look important, and do not deflate it to avoid
  anchoring. Report the severity you would defend in review.
- State the concrete consequence in the body ("this returns 1 instead of the saved value, so
  defragmentation is forced back on after reload") rather than asserting something "may" be wrong.
- If a finding is a judgement call or explicitly waivable, use \`low\` or \`info\` and say so.
- Positive findings belong in \`info\`; do not pad the review with them.`;

/** V3 — anchoring / line-number correctness. */
const V3_ANCHOR = `

## Anchoring accuracy (required)

Every non-info finding must point at a real, changed line. A wrong anchor makes the finding
unusable, so verify before you emit:

1. \`commentAnchor.file\` MUST be a path that appears in the diff above, written exactly as it
   appears there (same prefix and casing). Never anchor to an unchanged file you only read for
   context.
2. \`lineStart\` / \`lineEnd\` are 1-indexed in the NEW (head) version of that file. Open the file
   with the Read tool and confirm the numbers before writing them. Do not estimate.
3. The primary \`::diff{file="..." lines="start-end"}\` directive in the body must cover the changed
   hunk the finding is about, and should agree with \`commentAnchor\`.
4. \`files[]\` must list the paths you actually examined, using the same relative paths as the diff.
5. \`fixPrompt\` must name the file and the line numbers and say what to change and which existing
   pattern to follow. Keep it under ~150 words.

A finding whose anchor does not resolve to changed code is a broken finding, even when the
observation itself is correct.`;

/** V4 — recall + anchoring combined (tests whether the two levers stack). */
const V4_COMBINED = V1_RECALL + '\n' + V3_ANCHOR;

mkdirSync(OUT, { recursive: true });
const variants = {
  v1_recall: SYSTEM_PROMPT + V1_RECALL,
  v2_severity: SYSTEM_PROMPT + V2_SEVERITY,
  v3_anchor: SYSTEM_PROMPT + V3_ANCHOR,
  v4_recall_anchor: SYSTEM_PROMPT + V4_COMBINED,
};
for (const [name, text] of Object.entries(variants)) {
  const p = join(OUT, `${name}.txt`);
  writeFileSync(p, text);
  console.log(`${name}: ${text.length} chars (base ${SYSTEM_PROMPT.length}, delta +${text.length - SYSTEM_PROMPT.length}) -> ${p}`);
}
console.log(`wrote ${Object.keys(variants).length} variants`);
