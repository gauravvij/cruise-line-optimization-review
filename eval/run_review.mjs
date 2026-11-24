#!/usr/bin/env node
/**
 * Cruise Line — faithful PR-analysis eval runner (harness v2).
 *
 * Reproduces the analysis stage (`agent/analysis/analyzer.ts` -> `sandbox/index.ts`
 * POST /query) against the Qodo/PR-Review-Bench subset:
 *
 *   - uses the repo's buildUserPrompt / walkthroughJsonSchema (imported from the
 *     .ts sources, never re-typed)
 *   - the SYSTEM_PROMPT must be given explicitly with --prompt-file (see below)
 *   - clones the PR head, computes the diff exactly like sandbox/index.ts
 *   - runs a Claude Agent SDK loop (claude CLI) with the same tool set
 *     (Read/Glob/Grep), permission mode, effort and json_schema structured output
 *   - routes the model through OpenRouter's Anthropic-compatible endpoint
 *
 * Harness v2 changes (round 2):
 *   1. Turn cap is ENFORCED by this runner. The stream-json is parsed live and
 *      the number of distinct assistant API turns (unique message.id) is counted.
 *      If it exceeds --max-turns the process group is killed and the record gets
 *      turn_cap_hit=true with a reason. The CLI's --max-turns flag is still
 *      passed but was observed NOT to stop runs (see OPTIMIZATION_REPORT.md).
 *   2. Per-PR cost is authoritative: OpenRouter key usage_monthly delta around
 *      each PR. Requires --concurrency 1 (otherwise deltas mix). cli_cost_usd is
 *      kept only as a secondary field.
 *   3. Every record is self-describing: harness_version (sha256 of this file +
 *      score.py), prompt sha256, model, effort, PR list, cruise-line git HEAD.
 *   4. No silent default prompt: --prompt-file is required (the working-tree
 *      prompt.ts is the v4 variant, so it must not be used as the baseline).
 *
 * Usage:
 *   node --experimental-strip-types eval/run_review.mjs \
 *     --model anthropic/claude-haiku-5.5 --effort medium \
 *     --prompt-file eval/prompts/v4_recall_anchor.txt \
 *     --prs "firefox-ios#1,redis#5" --out eval/results/raw --tag my_tag --concurrency 1
 */

import { spawn, execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdirSync, readFileSync, writeFileSync, existsSync } from 'node:fs';
import { join, basename } from 'node:path';
import { homedir } from 'node:os';
import { createHash } from 'node:crypto';

const execFileP = promisify(execFile);

// ---------------------------------------------------------------------------
// Paths / config
// ---------------------------------------------------------------------------

const PROJECT = '/home/azureuser/optimize-cruiseline';
const REPO_SRC = join(PROJECT, 'cruise-line');
const EVAL = join(PROJECT, 'eval');
const MANIFEST = join(EVAL, 'manifest.json');
const REPOS_ROOT = join(EVAL, 'data', 'repos');
const CLONE_BASE = 'https://github.com/agentic-review-benchmarks';
const HARNESS_FILES = [join(EVAL, 'run_review.mjs'), join(EVAL, 'score.py')];

const CLAUDE_BIN = process.env.CLAUDE_BIN ?? join(homedir(), '.local', 'bin', 'claude');

// Round-2 spend anchor: usage_monthly read at round start (2026-11-17).
// Round spend = usage_monthly - TASK_START_SPEND. Override via env if needed.
const TASK_START_SPEND = Number(process.env.TASK_START_SPEND ?? 20.65877423);
const BUDGET_USD = Number(process.env.BUDGET_USD ?? 4.0);

// Real production builder + schema, imported (not re-typed). The SYSTEM_PROMPT
// export is deliberately NOT used (working tree = v4).
const { buildUserPrompt } = await import(join(REPO_SRC, 'agent', 'analysis', 'prompt.ts'));
const { walkthroughJsonSchema } = await import(join(REPO_SRC, 'agent', 'analysis', 'types.ts'));

// Mirrors sandbox/index.ts
const READ_ONLY_TOOLS = ['Read', 'Glob', 'Grep'];
const DEFAULT_MAX_TURNS = 60; // analyzer.ts passes maxTurns: 60
const MAX_TURNS_CAP = 100;

/** repo-style (dashed) model ids -> OpenRouter slugs */
export const MODEL_MAP = {
  'claude-opus-5-5': 'anthropic/claude-opus-5.5',
  'claude-sonnet-5-5': 'anthropic/claude-sonnet-5.5',
  'claude-haiku-5-5': 'anthropic/claude-haiku-5.5',
};
export function toOpenRouter(model) {
  return MODEL_MAP[model] ?? model;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const sha256 = (s) => createHash('sha256').update(s).digest('hex');

/** Must match score.py harness_version(): sha256(run_review.mjs bytes + score.py bytes)[:16] */
export function harnessVersion() {
  const h = createHash('sha256');
  for (const f of HARNESS_FILES) h.update(readFileSync(f));
  return h.digest('hex').slice(0, 16);
}

// ---------------------------------------------------------------------------
// Args
// ---------------------------------------------------------------------------

function parseArgs(argv) {
  const a = { effort: 'high', maxTurns: DEFAULT_MAX_TURNS, out: join(EVAL, 'results', 'raw'),
              tag: 'run', concurrency: 1, timeoutSec: 1200, prs: null, promptFile: null,
              model: null, limit: null, dryRun: false, force: false };
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i];
    const v = argv[i + 1];
    if (k === '--model') { a.model = v; i++; }
    else if (k === '--effort') { a.effort = v; i++; }
    else if (k === '--max-turns') { a.maxTurns = Number(v); i++; }
    else if (k === '--out') { a.out = v; i++; }
    else if (k === '--tag') { a.tag = v; i++; }
    else if (k === '--concurrency') { a.concurrency = Number(v); i++; }
    else if (k === '--timeout') { a.timeoutSec = Number(v); i++; }
    else if (k === '--prs') { a.prs = v.split(',').map((s) => s.trim()).filter(Boolean); i++; }
    else if (k === '--prompt-file') { a.promptFile = v; i++; }
    else if (k === '--limit') { a.limit = Number(v); i++; }
    else if (k === '--dry-run') { a.dryRun = true; }
    else if (k === '--force') { a.force = true; }
    else throw new Error(`unknown arg: ${k}`);
  }
  return a;
}

// ---------------------------------------------------------------------------
// OpenRouter spend (authoritative cost accounting)
// ---------------------------------------------------------------------------

function readApiKey() {
  const cfg = JSON.parse(readFileSync(join(homedir(), '.config', 'openrouter', 'config'), 'utf-8'));
  return cfg.api_key;
}

async function openrouterSpend() {
  const key = readApiKey();
  const r = await fetch('https://openrouter.ai/api/v1/key', { headers: { Authorization: `Bearer ${key}` } });
  const j = await r.json();
  return j.data.usage_monthly;
}

/**
 * Key usage is eventually consistent. Poll until it moves away from `before`
 * (or give up after maxWaitMs). Returns whether the value settled.
 */
async function spendAfterChange(before, maxWaitMs = 30000) {
  const t0 = Date.now();
  let v = await openrouterSpend();
  while (v === before && Date.now() - t0 < maxWaitMs) {
    await sleep(3000);
    v = await openrouterSpend();
  }
  return { value: v, settled: v !== before, waitMs: Date.now() - t0 };
}

// ---------------------------------------------------------------------------
// Repo prep (mirrors sandbox/index.ts ensure-clone + diff strategy)
// ---------------------------------------------------------------------------

function git(args, cwd, timeout = 900000) {
  return execFileP('git', args, { cwd, maxBuffer: 256 * 1024 * 1024, timeout });
}

async function ensureRepo(repo) {
  const dir = join(REPOS_ROOT, repo);
  if (!existsSync(join(dir, '.git'))) {
    mkdirSync(REPOS_ROOT, { recursive: true });
    await git(['clone', '--depth=50', '--filter=blob:none', '--no-checkout',
               `${CLONE_BASE}/${repo}.git`, dir], REPOS_ROOT);
  }
  return dir;
}

async function preparePr(pr) {
  const dir = await ensureRepo(pr.repo);
  await git(['fetch', 'origin', '--depth=50',
             `+refs/pull/${pr.num}/head:refs/remotes/origin/pr-head`], dir);

  let sha = pr.head_sha;
  try {
    const { stdout } = await git(['rev-parse', 'origin/pr-head'], dir);
    if (stdout.trim()) sha = stdout.trim();
  } catch { /* keep manifest sha */ }

  await git(['checkout', '--force', sha], dir);

  await git(['fetch', 'origin', `+refs/heads/${pr.base_ref}:refs/remotes/origin/${pr.base_ref}`], dir)
    .catch(() => {});

  let diff = '';
  for (const args of [
    ['diff', `origin/${pr.base_ref}...HEAD`],
    ['diff', `origin/${pr.base_ref}..HEAD`],
    ['diff', `origin/${pr.base_ref}`, 'HEAD'],
  ]) {
    try {
      const { stdout } = await git(args, dir);
      if (stdout.trim()) { diff = stdout; break; }
    } catch { /* try next */ }
  }
  return { repoDir: dir, sha, diff };
}

// ---------------------------------------------------------------------------
// Agent loop via the claude CLI routed through OpenRouter
// ---------------------------------------------------------------------------

/**
 * Spawns the CLI and parses stream-json LIVE. A "turn" is one distinct assistant
 * API response, identified by message.id (the CLI emits one stream line per
 * content block, several lines can share one message.id). Lines without an id
 * are counted individually as a fallback and reported separately.
 *
 * When the counted turns exceed maxTurns the whole process group is killed and
 * turnCapHit is set.
 */
function runClaude({ prompt, systemPrompt, model, effort, maxTurns, repoDir, timeoutSec }) {
  return new Promise((resolveRun) => {
    const key = readApiKey();
    const args = [
      '--print',
      '--output-format', 'stream-json',
      '--verbose',
      '--model', toOpenRouter(model),
      '--system-prompt', systemPrompt,
      '--allowedTools', ...READ_ONLY_TOOLS,
      '--permission-mode', 'bypassPermissions',
      '--dangerously-skip-permissions',
      // Don't load CLAUDE.md / settings / hooks from the repo under review
      '--setting-sources=',
      '--json-schema', JSON.stringify(walkthroughJsonSchema),
      '--max-turns', String(Math.min(maxTurns, MAX_TURNS_CAP)),
    ];
    if (effort) args.push('--effort', effort);

    const started = Date.now();
    // detached => the CLI is a process-group leader, so we can kill its children too
    const child = spawn(CLAUDE_BIN, args, {
      cwd: repoDir,
      detached: true,
      env: {
        ...process.env,
        PATH: `${join(homedir(), '.local', 'bin')}:${process.env.PATH}`,
        ANTHROPIC_BASE_URL: 'https://openrouter.ai/api',
        ANTHROPIC_AUTH_TOKEN: key,
        ANTHROPIC_API_KEY: key,
        // Cap CLI max_tokens so OpenRouter does not reserve $2.56 (128000 * $0.00002)
        // per request, which caused 402s once remaining balance fell below $2.56.
        // Verified fix (2026-11-17): diagnostic r2_opus_test_dify11 schema-valid, F1 0.667.
        CLAUDE_CODE_MAX_OUTPUT_TOKENS: process.env.CLAUDE_CODE_MAX_OUTPUT_TOKENS ?? '16000',
      },
    });

    const st = {
      stdout: '', stderr: '', lineBuf: '',
      msgIds: new Set(), anonLines: 0, assistantLines: 0,
      toolUseBlocks: 0, textChars: 0, toolCalls: [], result: null,
      killReason: null, turnCapHit: false, timedOut: false,
    };

    const killGroup = (reason) => {
      if (st.killReason) return;
      st.killReason = reason;
      try { process.kill(-child.pid, 'SIGKILL'); }
      catch { try { child.kill('SIGKILL'); } catch { /* already gone */ } }
    };

    const timer = setTimeout(() => {
      st.timedOut = true;
      killGroup(`timeout after ${timeoutSec}s`);
    }, timeoutSec * 1000);

    const consume = (line) => {
      // Frozen at the cap: lines already buffered in the same stdout chunk must not
      // inflate num_turns_counted past the count that actually tripped the cap.
      if (st.turnCapHit) return;
      const s = line.trim();
      if (!s || s[0] !== '{') return;
      let msg;
      try { msg = JSON.parse(s); } catch { return; }
      if (msg.type === 'assistant') {
        st.assistantLines++;
        const mid = msg.message?.id;
        if (mid) st.msgIds.add(mid); else st.anonLines++;
        const counted = st.msgIds.size + st.anonLines;
        for (const block of msg.message?.content ?? []) {
          if (block.type === 'tool_use') {
            st.toolUseBlocks++;
            st.toolCalls.push({ name: block.name, input: block.input });
          } else if (block.type === 'text') {
            st.textChars += (block.text ?? '').length;
          }
        }
        if (counted > maxTurns && !st.turnCapHit) {
          st.turnCapHit = true;
          killGroup(`turn cap exceeded: counted ${counted} assistant turns > maxTurns ${maxTurns}`);
        }
      } else if (msg.type === 'result') {
        st.result = msg;
      }
    };

    child.stdout.on('data', (d) => {
      const s = d.toString();
      st.stdout += s;
      st.lineBuf += s;
      let i;
      while ((i = st.lineBuf.indexOf('\n')) >= 0) {
        const line = st.lineBuf.slice(0, i);
        st.lineBuf = st.lineBuf.slice(i + 1);
        consume(line);
      }
    });
    child.stderr.on('data', (d) => { st.stderr += d.toString(); });
    child.stdin.on('error', () => { /* child may exit early on kill */ });

    const finish = (exitCode, error) => {
      clearTimeout(timer);
      if (st.lineBuf) { consume(st.lineBuf); st.lineBuf = ''; }
      resolveRun({
        exitCode,
        spawnError: error ?? null,
        killed: st.timedOut,
        turnCapHit: st.turnCapHit,
        killReason: st.killReason,
        latencyMs: Date.now() - started,
        result: st.result,
        toolCalls: st.toolCalls,
        textChars: st.textChars,
        turnTrace: {
          assistant_lines: st.assistantLines,
          unique_message_ids: st.msgIds.size,
          lines_without_id: st.anonLines,
          tool_use_blocks: st.toolUseBlocks,
        },
        numTurnsCounted: st.msgIds.size + st.anonLines,
        stderrTail: st.stderr.split('\n').slice(-8).join('\n'),
      });
    };

    child.on('close', (code) => finish(code));
    child.on('error', (err) => finish(-1, String(err)));

    child.stdin.write(prompt);
    child.stdin.end();
  });
}

// ---------------------------------------------------------------------------
// Schema validation (no external deps): structural check against the real schema
// ---------------------------------------------------------------------------

function validateFindings(out) {
  const errs = [];
  if (!out || typeof out !== 'object') return { valid: false, errors: ['structured_output missing'], nFindings: 0 };
  for (const k of walkthroughJsonSchema.required) {
    if (out[k] === undefined) errs.push(`missing required top-level field: ${k}`);
  }
  if (!Array.isArray(out.findings)) errs.push('findings is not an array');
  const SEV = ['critical', 'high', 'medium', 'low', 'info'];
  const CAT = ['correctness', 'security', 'maintainability', 'performance', 'style'];
  (out.findings ?? []).forEach((f, i) => {
    for (const k of ['title', 'severity', 'category', 'body', 'files']) {
      if (f[k] === undefined) errs.push(`findings[${i}].${k} missing`);
    }
    if (!SEV.includes(f.severity)) errs.push(`findings[${i}].severity invalid: ${f.severity}`);
    if (!CAT.includes(f.category)) errs.push(`findings[${i}].category invalid: ${f.category}`);
    if (f.severity && f.severity !== 'info') {
      if (!f.fixPrompt) errs.push(`findings[${i}].fixPrompt missing (severity=${f.severity})`);
      if (!f.commentAnchor) errs.push(`findings[${i}].commentAnchor missing (severity=${f.severity})`);
      else {
        if (typeof f.commentAnchor.file !== 'string') errs.push(`findings[${i}].commentAnchor.file invalid`);
        if (!Number.isInteger(f.commentAnchor.lineStart)) errs.push(`findings[${i}].commentAnchor.lineStart invalid`);
        if (!Number.isInteger(f.commentAnchor.lineEnd)) errs.push(`findings[${i}].commentAnchor.lineEnd invalid`);
      }
    }
  });
  return { valid: errs.length === 0, errors: errs.slice(0, 20), nFindings: (out.findings ?? []).length };
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

const args = parseArgs(process.argv.slice(2));
const manifest = JSON.parse(readFileSync(MANIFEST, 'utf-8'));
let prs = manifest.prs;
if (args.prs) {
  const want = new Set(args.prs.map((s) => s.replace('#', '/')));
  prs = prs.filter((p) => want.has(`${p.repo}/${p.num}`) || want.has(`${p.repo}#${p.num}`));
}
if (args.limit) prs = prs.slice(0, args.limit);

if (!args.dryRun) {
  if (!args.promptFile) throw new Error('--prompt-file is required (no silent default prompt; see harness v2 notes)');
  if (!args.model) throw new Error('--model is required');
  if (args.concurrency !== 1) throw new Error('--concurrency must be 1: per-PR key-delta cost is only valid when runs are serialized');
}
const systemPrompt = args.promptFile ? readFileSync(args.promptFile, 'utf-8') : '';
const promptSha = args.promptFile ? sha256(systemPrompt) : null;
const HARNESS = harnessVersion();
const cruiseHead = (await execFileP('git', ['rev-parse', 'HEAD'], { cwd: REPO_SRC })).stdout.trim();
const prList = prs.map((p) => `${p.repo}#${p.num}`);

mkdirSync(args.out, { recursive: true });
console.log(`[run_review] harness=${HARNESS} model=${args.model} effort=${args.effort} prs=${prs.length} ` +
            `maxTurns=${args.maxTurns} tag=${args.tag}`);
console.log(`[run_review] prompt=${args.promptFile} sha256=${promptSha?.slice(0, 16)} chars=${systemPrompt.length}`);

if (args.dryRun) {
  const p = prs[0];
  const { repoDir, diff } = await preparePr(p);
  const meta = { owner: 'agentic-review-benchmarks', repo: p.repo, number: p.num, title: p.title,
    author: p.author ?? '', baseRef: p.base_ref, headRef: 'pr-head', baseSha: p.base_sha, headSha: p.head_sha,
    installationId: 1, body: p.body, authorAvatarUrl: null, additions: p.additions, deletions: p.deletions,
    changedFiles: p.changed_files, state: 'open', mergedAt: null, closedAt: null, updatedAt: '' };
  const up = buildUserPrompt(meta, diff, p.body, undefined);
  console.log(`[dry-run] repoDir=${repoDir} diffChars=${diff.length} userPromptChars=${up.length}`);
  console.log('[dry-run] user prompt head:\n' + up.slice(0, 900));
  process.exit(0);
}

// Refuse to mix into an existing tag silently
const existing = prs.map((p) => join(args.out, `${args.tag}__${p.repo}_${p.num}.json`)).filter((f) => existsSync(f));
if (existing.length && !args.force) {
  throw new Error(`tag "${args.tag}" already has ${existing.length} record(s) in ${args.out}; use a new --tag or --force`);
}

const spendBefore = await openrouterSpend();
const taskSpent0 = spendBefore - TASK_START_SPEND;
console.log(`[run_review] openrouter usage_monthly before: $${spendBefore.toFixed(6)} ` +
  `(round spend $${taskSpent0.toFixed(4)} of $${BUDGET_USD} budget)`);
if (taskSpent0 >= BUDGET_USD) {
  console.error(`[run_review] BUDGET EXCEEDED: $${taskSpent0.toFixed(4)} >= $${BUDGET_USD}. Aborting.`);
  process.exit(2);
}

const results = [];

async function runOne(pr) {
  const id = `${pr.repo}#${pr.num}`;
  const t0 = Date.now();
  const rec = {
    id, repo: pr.repo, num: pr.num,
    // provenance (harness v2)
    harness_version: HARNESS, tag: args.tag, model: args.model,
    openrouter_model: toOpenRouter(args.model), effort: args.effort, maxTurns: args.maxTurns,
    prompt_file: args.promptFile, promptVariant: basename(args.promptFile), prompt_sha256: promptSha,
    cruise_line_git_head: cruiseHead, pr_list: prList, run_started_at: new Date(t0).toISOString(),
    num_of_issues: pr.num_of_issues, issues: pr.issues,
  };

  // Budget guard before every PR (not only at start)
  const pre = await openrouterSpend();
  if (pre - TASK_START_SPEND >= BUDGET_USD) {
    rec.skipped = 'budget_exceeded_before_pr';
    rec.schema_valid = false; rec.n_findings = 0; rec.cost_usd = 0;
    writeRecord(rec);
    console.log(`[SKIP] ${id}: round spend $${(pre - TASK_START_SPEND).toFixed(4)} >= $${BUDGET_USD}`);
    return rec;
  }

  try {
    const prep = await preparePr(pr);
    rec.repo_dir = prep.repoDir;
    rec.head_sha = prep.sha;
    rec.diff_chars = prep.diff.length;
    rec.diff_lines = prep.diff.split('\n').length;

    const meta = { owner: 'agentic-review-benchmarks', repo: pr.repo, number: pr.num, title: pr.title,
      author: pr.author ?? '', baseRef: pr.base_ref, headRef: 'pr-head', baseSha: pr.base_sha,
      headSha: prep.sha, installationId: 1, body: pr.body, authorAvatarUrl: null,
      additions: pr.additions, deletions: pr.deletions, changedFiles: pr.changed_files,
      state: 'open', mergedAt: null, closedAt: null, updatedAt: '' };
    const userPrompt = buildUserPrompt(meta, prep.diff, pr.body, undefined);
    rec.user_prompt_chars = userPrompt.length;

    // Authoritative cost: key usage delta around this single PR (concurrency 1)
    const spendPre = await openrouterSpend();
    const run = await runClaude({
      prompt: userPrompt, systemPrompt, model: args.model, effort: args.effort,
      maxTurns: args.maxTurns, repoDir: prep.repoDir, timeoutSec: args.timeoutSec,
    });
    const settle = await spendAfterChange(spendPre);

    rec.exit_code = run.exitCode;
    rec.spawn_error = run.spawnError;
    rec.timed_out = run.killed;
    rec.latency_ms = run.latencyMs;
    rec.wall_ms = Date.now() - t0;
    rec.tool_calls = run.toolCalls.map((t) => ({ name: t.name,
      detail: t.input?.file_path ?? t.input?.pattern ?? t.input?.path ?? '' }));
    rec.n_tool_calls = run.toolCalls.length;
    rec.stderr_tail = run.stderrTail;

    // Turn accounting (enforced from the live stream)
    rec.num_turns_counted = run.numTurnsCounted;
    rec.turn_trace = run.turnTrace;
    rec.turn_cap_hit = run.turnCapHit;
    rec.turn_cap_reason = run.turnCapHit ? run.killReason : null;
    rec.turn_check_ok = run.numTurnsCounted <= args.maxTurns || run.turnCapHit;

    // Cost: authoritative key-delta
    rec.spend_pre_usd = spendPre;
    rec.spend_post_usd = settle.value;
    rec.cost_settled = settle.settled;
    rec.cost_wait_ms = settle.waitMs;
    rec.cost_usd = Math.max(0, settle.value - spendPre);
    rec.cost_flag = !settle.settled ? 'key_delta_unsettled_after_30s'
                  : rec.cost_usd === 0 ? 'key_delta_zero' : null;

    const r = run.result;
    if (r) {
      rec.subtype = run.turnCapHit ? 'turn_cap_hit' : r.subtype;
      rec.is_error = r.is_error;
      rec.num_turns = r.num_turns;              // CLI's own count (secondary)
      rec.stop_reason = r.stop_reason;
      rec.cli_cost_usd = r.total_cost_usd;      // CLI estimate, secondary only
      rec.usage = r.usage;
      rec.model_usage = r.modelUsage;
      rec.structured_output = r.structured_output ?? null;
      rec.result_text_head = typeof r.result === 'string' ? r.result.slice(0, 500) : null;
      const v = validateFindings(r.structured_output);
      rec.schema_valid = v.valid && !run.turnCapHit;
      rec.schema_errors = run.turnCapHit ? [`turn_cap_hit: ${run.killReason}`, ...v.errors] : v.errors;
      rec.n_findings = v.nFindings;
    } else {
      rec.subtype = run.turnCapHit ? 'turn_cap_hit' : run.killed ? 'timeout' : null;
      rec.schema_valid = false;
      rec.schema_errors = [run.turnCapHit ? `turn_cap_hit: ${run.killReason}`
        : run.killed ? `timeout: ${run.killReason}` : 'no result message emitted'];
      rec.n_findings = 0;
    }
  } catch (err) {
    rec.error = String(err?.message ?? err).slice(0, 500);
    rec.schema_valid = false;
    rec.n_findings = 0;
    rec.cost_usd = 0;
    rec.cost_flag = 'error_before_cost_measured';
    rec.latency_ms = Date.now() - t0;
  }

  writeRecord(rec);
  const bad = rec.schema_valid ? '' : ` SCHEMA_INVALID(${rec.schema_errors?.[0] ?? '?'})`;
  const cap = rec.turn_cap_hit ? ' TURN_CAP_HIT' : '';
  console.log(`[${results.length}/${prs.length}] ${id.padEnd(20)} counted=${rec.num_turns_counted ?? '-'} ` +
    `cli_turns=${rec.num_turns ?? '-'} findings=${rec.n_findings} tools=${rec.n_tool_calls ?? '-'} ` +
    `key_cost=$${(rec.cost_usd ?? 0).toFixed(5)}${rec.cost_flag ? ' [' + rec.cost_flag + ']' : ''} ` +
    `${((rec.latency_ms ?? 0) / 1000).toFixed(1)}s${cap}${bad}`);
  return rec;
}

function writeRecord(rec) {
  const file = join(args.out, `${args.tag}__${rec.repo}_${rec.num}.json`);
  writeFileSync(file, JSON.stringify(rec, null, 1));
  results.push(rec);
}

// Strictly sequential: one PR at a time so the key-delta is attributable
for (const pr of prs) await runOne(pr);

const spendAfter = await openrouterSpend();
const totalCost = results.reduce((s, r) => s + (r.cost_usd ?? 0), 0);
const summary = {
  tag: args.tag, harness_version: HARNESS, model: args.model, openrouter_model: toOpenRouter(args.model),
  effort: args.effort, maxTurns: args.maxTurns, prompt_variant: args.promptFile,
  prompt_sha256: promptSha, cruise_line_git_head: cruiseHead, pr_list: prList,
  n_prs: results.length,
  n_skipped_budget: results.filter((r) => r.skipped).length,
  n_schema_valid: results.filter((r) => r.schema_valid).length,
  n_with_findings: results.filter((r) => (r.n_findings ?? 0) > 0).length,
  n_turn_cap_hit: results.filter((r) => r.turn_cap_hit).length,
  n_turn_check_violations: results.filter((r) => r.turn_check_ok === false).length,
  n_cost_flags: results.filter((r) => r.cost_flag).length,
  total_findings: results.reduce((s, r) => s + (r.n_findings ?? 0), 0),
  sum_key_delta_cost_usd: totalCost,
  cli_cost_usd_secondary: results.reduce((s, r) => s + (r.cli_cost_usd ?? 0), 0),
  spend_before: spendBefore, spend_after: spendAfter,
  run_spend_delta_usd: spendAfter - spendBefore,
  mean_latency_ms: results.length ? results.reduce((s, r) => s + (r.latency_ms ?? 0), 0) / results.length : 0,
  total_turns_counted: results.reduce((s, r) => s + (r.num_turns_counted ?? 0), 0),
  per_pr: results.map((r) => ({ id: r.id, n_findings: r.n_findings, schema_valid: r.schema_valid,
    cost_usd: r.cost_usd, cost_flag: r.cost_flag ?? null, cli_cost_usd: r.cli_cost_usd ?? null,
    latency_ms: r.latency_ms, num_turns: r.num_turns, num_turns_counted: r.num_turns_counted,
    turn_cap_hit: r.turn_cap_hit ?? false, subtype: r.subtype })),
};
writeFileSync(join(args.out, `${args.tag}__summary.json`), JSON.stringify(summary, null, 1));
console.log(`\n[run_review] DONE tag=${args.tag} harness=${HARNESS}: ${summary.n_schema_valid}/${summary.n_prs} schema-valid, ` +
  `${summary.total_findings} findings, sum key-delta $${totalCost.toFixed(5)} ` +
  `(whole-run usage delta $${summary.run_spend_delta_usd.toFixed(5)}), turn_cap_hit=${summary.n_turn_cap_hit}, ` +
  `cost_flags=${summary.n_cost_flags}`);
