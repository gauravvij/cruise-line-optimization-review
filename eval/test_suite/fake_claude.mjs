#!/usr/bin/env node
/**
 * Zero-cost stand-in for the claude CLI. Used ONLY to verify the runner's turn
 * cap enforcement without any OpenRouter spend. Not used for any result.
 *
 * FAKE_MODE=distinct -> FAKE_N assistant messages, each with its own message.id
 *                       (one API call per message). Should trigger the turn cap.
 * FAKE_MODE=streamed -> FAKE_N content-block lines that all share ONE message.id
 *                       (one API call split into blocks). Must count as 1 turn.
 */
process.stdin.on('data', () => {});
process.stdin.on('end', () => {});
const mode = process.env.FAKE_MODE ?? 'distinct';
const n = Number(process.env.FAKE_N ?? 10);
const out = (o) => process.stdout.write(JSON.stringify(o) + '\n');

out({ type: 'system', subtype: 'init' });
for (let i = 0; i < n; i++) {
  const id = mode === 'streamed' ? 'msg_shared' : `msg_${i}`;
  out({ type: 'assistant', message: { id, content: [{ type: 'text', text: `step ${i}` }] } });
}
out({ type: 'result', subtype: 'success', is_error: false, num_turns: n,
      structured_output: null, result: '', total_cost_usd: 0 });
