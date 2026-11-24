#!/usr/bin/env python3
"""Paired bootstrap for validation round 3 (Haiku phase, 48 PRs).
Same method as bootstrap_r2.json / bootstrap_opus_full16.py: resample PRs with
replacement, recompute micro F1 from summed tp/fp/fn, 10000 resamples, seed 42.
No paid API calls. Adds per-repo and per-diff-size breakdowns (strata from
eval/holdout48.json)."""
import json, random
from collections import defaultdict
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

B = per_pr('h3_haiku_baseline')
C = per_pr('h3_haiku_v4')
ids = sorted(B.keys())
assert set(ids) == set(C.keys()) and len(ids) == 48, (len(ids), set(ids) ^ set(C.keys()))

# strata from holdout48.json
h48 = json.loads((ROOT / 'eval/holdout48.json').read_text())
strata = {}
for p in h48['prs']:
    pid = f"{p['repo']}#{p['num']}"
    ds = p.get('diff_lines')
    size = 'small' if ds <= 200 else ('medium' if ds <= 500 else 'large')
    strata[pid] = {'repo': p['repo'], 'diff_size': size, 'diff_lines': ds}
assert set(strata) == set(ids), set(strata) ^ set(ids)

rng = random.Random(42); N = 10000
b_f1s, c_f1s, diffs = [], [], []
for _ in range(N):
    sample = [ids[rng.randrange(48)] for _ in range(48)]
    b_f1s.append(micro_f1([B[i] for i in sample]))
    c_f1s.append(micro_f1([C[i] for i in sample]))
    diffs.append(c_f1s[-1] - b_f1s[-1])

def block(sub_ids, label):
    """Bootstrap within a subgroup (resample only that subgroup's PRs)."""
    sub = sorted(sub_ids)
    bf, cf, df = [], [], []
    r2 = random.Random(42)
    for _ in range(N):
        s = [sub[r2.randrange(len(sub))] for _ in range(len(sub))]
        bf.append(micro_f1([B[i] for i in s]))
        cf.append(micro_f1([C[i] for i in s]))
        df.append(cf[-1] - bf[-1])
    return {
        label: {
            'n_prs': len(sub),
            'baseline_micro_f1': {'observed': round(micro_f1([B[i] for i in sub]), 4), 'mean': round(sum(bf)/N, 4), 'ci95': ci(bf)},
            'v4_micro_f1': {'observed': round(micro_f1([C[i] for i in sub]), 4), 'mean': round(sum(cf)/N, 4), 'ci95': ci(cf)},
            'paired_diff_v4_minus_baseline': {'observed': round(micro_f1([C[i] for i in sub]) - micro_f1([B[i] for i in sub]), 4),
                                              'mean': round(sum(df)/N, 4), 'ci95': ci(df),
                                              'includes_zero': ci(df)[0] <= 0 <= ci(df)[1]},
        }
    }

per_repo = {}
for repo in sorted({strata[i]['repo'] for i in ids}):
    per_repo.update(block([i for i in ids if strata[i]['repo'] == repo], repo))
per_size = {}
for size in ['small', 'medium', 'large']:
    per_size.update(block([i for i in ids if strata[i]['diff_size'] == size], size))

lo, hi = ci(diffs)
out = {
    "method": "paired bootstrap over 48 holdout PRs (resample PRs with replacement, recompute micro F1 from summed tp/fp/fn), 10000 resamples, seed 42",
    "n_prs": 48, "resamples": N, "seed": 42,
    "baseline_prompt_micro_f1": {"mean": round(sum(b_f1s)/N, 4), "ci95": ci(b_f1s), "observed": round(micro_f1([B[i] for i in ids]), 4)},
    "v4_micro_f1": {"mean": round(sum(c_f1s)/N, 4), "ci95": ci(c_f1s), "observed": round(micro_f1([C[i] for i in ids]), 4)},
    "paired_diff_v4_minus_baseline": {"mean": round(sum(diffs)/N, 4), "ci95": [lo, hi], "observed": round(micro_f1([C[i] for i in ids]) - micro_f1([B[i] for i in ids]), 4)},
    "paired_diff_includes_zero": lo <= 0 <= hi,
    "per_repo": per_repo,
    "per_diff_size": per_size,
    "note": "Do not declare a prompt winner if the paired-difference CI includes zero.",
}
(RES / 'bootstrap_round3.json').write_text(json.dumps(out, indent=1))
print(json.dumps({k: out[k] for k in ['baseline_prompt_micro_f1', 'v4_micro_f1', 'paired_diff_v4_minus_baseline', 'paired_diff_includes_zero']}, indent=1))
print('per_repo diffs:')
for repo, d in per_repo.items():
    v = d['paired_diff_v4_minus_baseline']
    print(f"  {repo}: obs {v['observed']:+.4f} CI {v['ci95']}")
print('per_diff_size diffs:')
for size, d in per_size.items():
    v = d['paired_diff_v4_minus_baseline']
    print(f"  {size}: obs {v['observed']:+.4f} CI {v['ci95']}")
