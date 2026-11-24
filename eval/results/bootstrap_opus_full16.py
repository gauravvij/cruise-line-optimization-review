#!/usr/bin/env python3
"""Paired bootstrap for full-16 opus holdout. Same method as bootstrap_r2.json:
resample 16 PRs with replacement, recompute micro F1 from summed tp/fp/fn,
10000 resamples, seed 42. No paid API calls."""
import json, random
from pathlib import Path
ROOT = Path('/home/azureuser/optimize-cruiseline')
RES = ROOT / 'eval/results'
def per_pr(tag):
    d = json.loads((RES / 'scored' / f'{tag}.json').read_text())
    return {p['id']: (p['tp'], p['fp'], p['fn']) for p in d['aggregate']['per_pr']}
def micro_f1(triples):
    tp = sum(t[0] for t in triples); fp = sum(t[1] for t in triples); fn = sum(t[2] for t in triples)
    if tp + fp == 0 or tp + fn == 0: return 0.0
    p = tp / (tp + fp); r = tp / (tp + fn)
    return 0.0 if p + r == 0 else 2 * p * r / (p + r)
def ci(vals):
    s = sorted(vals)
    return [round(s[int(0.025 * len(s))], 4), round(s[int(0.975 * len(s)) - 1], 4)]
opus = per_pr('r2_holdout_opus_baseline_full16')
hb = per_pr('r2_holdout_haiku_baseline')
hv = per_pr('r2_holdout_haiku_v4')
ids = sorted(opus.keys())
assert set(ids) == set(hb.keys()) == set(hv.keys()) and len(ids) == 16, (len(ids), set(ids) ^ set(hb.keys()))
rng = random.Random(42); N = 10000
opus_f1s, diff_v4_opus, diff_v4_hb = [], [], []
for _ in range(N):
    sample = [ids[rng.randrange(16)] for _ in range(16)]
    o = micro_f1([opus[i] for i in sample]); v = micro_f1([hv[i] for i in sample]); b = micro_f1([hb[i] for i in sample])
    opus_f1s.append(o); diff_v4_opus.append(v - o); diff_v4_hb.append(v - b)
def obs(a, b): return round(micro_f1([a[i] for i in ids]) - micro_f1([b[i] for i in ids]), 4)
out = {
    "method": "paired bootstrap over 16 holdout PRs (resample PRs with replacement, recompute micro F1 from summed tp/fp/fn), 10000 resamples, seed 42",
    "n_prs": 16, "resamples": N, "seed": 42,
    "opus_baseline_micro_f1": {"mean": round(sum(opus_f1s)/N, 4), "ci95": ci(opus_f1s), "observed": round(micro_f1([opus[i] for i in ids]), 4)},
    "paired_diff_haiku_v4_minus_opus_baseline": {"mean": round(sum(diff_v4_opus)/N, 4), "ci95": ci(diff_v4_opus), "observed": obs(hv, opus), "includes_zero": ci(diff_v4_opus)[0] <= 0 <= ci(diff_v4_opus)[1]},
    "paired_diff_haiku_v4_minus_haiku_baseline": {"mean": round(sum(diff_v4_hb)/N, 4), "ci95": ci(diff_v4_hb), "observed": obs(hv, hb), "includes_zero": ci(diff_v4_hb)[0] <= 0 <= ci(diff_v4_hb)[1]},
    "note": "Full-16 opus set: 8 original valid + dify#11 diagnostic + 7 retry (CLAUDE_CODE_MAX_OUTPUT_TOKENS=16000). All 16 schema-valid. Do not declare a winner if CI includes zero.",
}
(RES / 'bootstrap_opus_full16.json').write_text(json.dumps(out, indent=1))
print(json.dumps(out, indent=1))
