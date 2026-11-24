#!/usr/bin/env python3
"""Paired bootstrap for validation round 3 (Opus full-48 vs Haiku arms).
Same method as bootstrap_round3.py: resample PRs with replacement, recompute
micro F1 from summed tp/fp/fn, 10000 resamples, seed 42. No paid API calls.
Computes opus-baseline micro F1 CI and paired diffs opus-baseline minus
haiku-baseline and opus-baseline minus haiku-v4, plus per-repo and
per-diff-size breakdowns for opus-vs-haiku-v4 (strata from eval/holdout48.json)."""
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

B = per_pr('h3_haiku_baseline')
C = per_pr('h3_haiku_v4')
O = per_pr('h3_opus_baseline_full48')
ids = sorted(B.keys())
assert set(ids) == set(C.keys()) == set(O.keys()) and len(ids) == 48, (len(ids), set(ids) ^ set(O.keys()))

h48 = json.loads((ROOT / 'eval/holdout48.json').read_text())
strata = {}
for p in h48['prs']:
    pid = f"{p['repo']}#{p['num']}"
    ds = p.get('diff_lines')
    size = 'small' if ds <= 200 else ('medium' if ds <= 500 else 'large')
    strata[pid] = {'repo': p['repo'], 'diff_size': size, 'diff_lines': ds}
assert set(strata) == set(ids), set(strata) ^ set(ids)

rng = random.Random(42); N = 10000
o_f1s, b_f1s, c_f1s = [], [], []
diff_ob, diff_oc = [], []
for _ in range(N):
    sample = [ids[rng.randrange(48)] for _ in range(48)]
    o_f1s.append(micro_f1([O[i] for i in sample]))
    b_f1s.append(micro_f1([B[i] for i in sample]))
    c_f1s.append(micro_f1([C[i] for i in sample]))
    diff_ob.append(o_f1s[-1] - b_f1s[-1])
    diff_oc.append(o_f1s[-1] - c_f1s[-1])

def diff_block(vals, other):
    lo, hi = ci(vals)
    return {'observed': round(micro_f1([O[i] for i in ids]) - micro_f1([other[i] for i in ids]), 4),
            'mean': round(sum(vals)/N, 4), 'ci95': [lo, hi], 'includes_zero': lo <= 0 <= hi}

def block(sub_ids, label):
    sub = sorted(sub_ids)
    of, cf, df = [], [], []
    r2 = random.Random(42)
    for _ in range(N):
        s = [sub[r2.randrange(len(sub))] for _ in range(len(sub))]
        of.append(micro_f1([O[i] for i in s]))
        cf.append(micro_f1([C[i] for i in s]))
        df.append(of[-1] - cf[-1])
    lo, hi = ci(df)
    return {
        label: {
            'n_prs': len(sub),
            'opus_micro_f1': {'observed': round(micro_f1([O[i] for i in sub]), 4), 'mean': round(sum(of)/N, 4), 'ci95': ci(of)},
            'haiku_v4_micro_f1': {'observed': round(micro_f1([C[i] for i in sub]), 4), 'mean': round(sum(cf)/N, 4), 'ci95': ci(cf)},
            'paired_diff_opus_minus_haiku_v4': {'observed': round(micro_f1([O[i] for i in sub]) - micro_f1([C[i] for i in sub]), 4),
                                                'mean': round(sum(df)/N, 4), 'ci95': [lo, hi],
                                                'includes_zero': lo <= 0 <= hi},
        }
    }

per_repo = {}
for repo in sorted({strata[i]['repo'] for i in ids}):
    per_repo.update(block([i for i in ids if strata[i]['repo'] == repo], repo))
per_size = {}
for size in ['small', 'medium', 'large']:
    per_size.update(block([i for i in ids if strata[i]['diff_size'] == size], size))

d_ob = diff_block(diff_ob, B)
d_oc = diff_block(diff_oc, C)
out = {
    "method": "paired bootstrap over 48 holdout PRs (resample PRs with replacement, recompute micro F1 from summed tp/fp/fn), 10000 resamples, seed 42",
    "n_prs": 48, "resamples": N, "seed": 42,
    "opus_baseline_micro_f1": {"mean": round(sum(o_f1s)/N, 4), "ci95": ci(o_f1s), "observed": round(micro_f1([O[i] for i in ids]), 4)},
    "haiku_baseline_micro_f1": {"mean": round(sum(b_f1s)/N, 4), "ci95": ci(b_f1s), "observed": round(micro_f1([B[i] for i in ids]), 4)},
    "haiku_v4_micro_f1": {"mean": round(sum(c_f1s)/N, 4), "ci95": ci(c_f1s), "observed": round(micro_f1([C[i] for i in ids]), 4)},
    "paired_diff_opus_minus_haiku_baseline": d_ob,
    "paired_diff_opus_minus_haiku_v4": d_oc,
    "paired_diff_opus_minus_haiku_baseline_includes_zero": d_ob['includes_zero'],
    "paired_diff_opus_minus_haiku_v4_includes_zero": d_oc['includes_zero'],
    "per_repo_opus_vs_haiku_v4": per_repo,
    "per_diff_size_opus_vs_haiku_v4": per_size,
    "note": "Do not declare a winner if the paired-difference CI includes zero. No paid API calls; analysis only on existing scored records.",
}
(RES / 'bootstrap_round3_opus.json').write_text(json.dumps(out, indent=1))
print(json.dumps({k: out[k] for k in ['opus_baseline_micro_f1', 'haiku_baseline_micro_f1', 'haiku_v4_micro_f1', 'paired_diff_opus_minus_haiku_baseline', 'paired_diff_opus_minus_haiku_v4']}, indent=1))
print('per_repo opus-v4 diffs:')
for repo, d in per_repo.items():
    v = d['paired_diff_opus_minus_haiku_v4']
    print(f"  {repo}: obs {v['observed']:+.4f} CI {v['ci95']} includes_zero={v['includes_zero']}")
print('per_diff_size opus-v4 diffs:')
for size, d in per_size.items():
    v = d['paired_diff_opus_minus_haiku_v4']
    print(f"  {size}: obs {v['observed']:+.4f} CI {v['ci95']} includes_zero={v['includes_zero']}")
