#!/usr/bin/env python3
"""Build pre-registered holdout48 for validation round 3 (Haiku phase).

Joins bench jsonl + pr_meta, excludes 20 manifest PRs (80 remain), computes
diff_lines/diff_files via git fetch + diff (reuse prepare.py logic), then
deterministic stratified sampling seed 42: ~6/repo, thirds by diff size and
defect density. Writes eval/holdout48.json BEFORE any model run.
"""
import json, random, subprocess, sys
from collections import defaultdict, Counter
from pathlib import Path

ROOT = Path('/home/azureuser/optimize-cruiseline/eval')
BENCH = ROOT/'data/git_code_review_bench_100_w_open_prs.jsonl'
META = ROOT/'data/pr_meta.json'
MANIFEST = ROOT/'manifest.json'
REPOS = ROOT/'data/repos'
OUT = ROOT/'holdout48.json'
CLONE_BASE = 'https://github.com/agentic-review-benchmarks'
SEED = 42

def sh(cmd, cwd=None, timeout=900):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr

def load_pool():
    bench = [json.loads(l) for l in BENCH.read_text().splitlines() if l.strip()]
    meta = {f"{m['repo']}#{m['num']}": m for m in json.loads(META.read_text())}
    out = []
    for r in bench:
        parts = r['pr_url_to_review'].split('/')
        repo, num = parts[4], int(parts[-1])
        m = meta.get(f'{repo}#{num}', {})
        if m.get('err'):
            continue
        n_with_path = sum(1 for i in r['issues'] if i.get('file_path'))
        out.append({
            'repo': repo, 'num': num, 'url': r['pr_url_to_review'],
            'title': m.get('title') or '', 'body': m.get('body') or '',
            'author': '', 'base_ref': m.get('base') or 'main',
            'head_sha': m.get('head') or '', 'base_sha': m.get('base_sha') or '',
            'changed_files': m.get('changed_files') or 0,
            'additions': m.get('additions') or 0, 'deletions': m.get('deletions') or 0,
            'num_of_issues': r['num_of_issues'], 'n_issues_with_path': n_with_path,
            'issues': r['issues'],
        })
    return out

def ensure_repo(repo):
    d = REPOS/repo
    if not (d/'.git').exists():
        d.parent.mkdir(parents=True, exist_ok=True)
        rc,_,err = sh(['git','clone','--depth=50','--filter=blob:none','--no-checkout', f'{CLONE_BASE}/{repo}.git', str(d)], timeout=900)
        if rc != 0:
            raise RuntimeError(f'clone failed {repo}: {err[:300]}')
    return d

def compute_diff(repo, num, base_ref, head_sha):
    d = ensure_repo(repo)
    rc,_,err = sh(['git','fetch','origin','--depth=50', f'+refs/pull/{num}/head:refs/remotes/origin/pr-head'], cwd=d, timeout=900)
    if rc != 0:
        raise RuntimeError(f'fetch head failed: {err[:300]}')
    resolved = head_sha
    rc,out,_ = sh(['git','rev-parse','origin/pr-head'], cwd=d)
    if rc==0 and out.strip():
        resolved = out.strip()
    rc,_,err = sh(['git','checkout','--force',resolved], cwd=d, timeout=900)
    if rc != 0:
        raise RuntimeError(f'checkout failed: {err[:300]}')
    sh(['git','fetch','origin', f'+refs/heads/{base_ref}:refs/remotes/origin/{base_ref}'], cwd=d, timeout=900)
    diff = ''
    for cmd in (['git','diff', f'origin/{base_ref}...HEAD'],
                ['git','diff', f'origin/{base_ref}..HEAD'],
                ['git','diff', f'origin/{base_ref}','HEAD']):
        rc,out,_ = sh(cmd, cwd=d, timeout=600)
        if rc==0 and out.strip():
            diff = out; break
    return diff, resolved

def size_bucket(lines):
    if lines <= 200: return 'small'
    if lines <= 500: return 'medium'
    return 'large'

def main():
    pool = load_pool()
    man = json.loads(MANIFEST.read_text())
    used = {f"{p['repo']}#{p['num']}" for p in man['prs']}
    remaining = [p for p in pool if f"{p['repo']}#{p['num']}" not in used]
    print(f'pool={len(pool)} used={len(used)} remaining={len(remaining)}')
    print('remaining per repo:', dict(sorted(Counter(p["repo"] for p in remaining).items())))

    # Compute diff sizes for all 80 remaining (verify clones/heads/non-empty)
    verified, failed = [], []
    for i,p in enumerate(remaining,1):
        pid = f"{p['repo']}#{p['num']}"
        try:
            diff, sha = compute_diff(p['repo'], p['num'], p['base_ref'], p['head_sha'])
            if not diff.strip():
                raise RuntimeError('empty diff')
            nfiles = sum(1 for l in diff.splitlines() if l.startswith('diff --git '))
            p['head_sha'] = sha
            p['diff_lines'] = len(diff.splitlines())
            p['diff_files'] = nfiles
            p['diff_chars'] = len(diff)
            p['defect_density'] = round(p['num_of_issues']*100.0/max(1,p['diff_lines']), 4)
            p['size_bucket'] = size_bucket(p['diff_lines'])
            verified.append(p)
            print(f'[{i:2d}/{len(remaining)}] OK {pid:22s} lines={p["diff_lines"]:5d} files={nfiles:3d} issues={p["num_of_issues"]} dens={p["defect_density"]:.2f} size={p["size_bucket"]}')
        except Exception as e:
            failed.append({'id': pid, 'error': str(e)[:200]})
            print(f'[{i:2d}/{len(remaining)}] FAIL {pid} {str(e)[:120]}')
    print(f'verified={len(verified)} failed={len(failed)}')
    if failed:
        print(json.dumps(failed, indent=1))

    # Defect density tertiles over verified pool
    dens_sorted = sorted(p['defect_density'] for p in verified)
    n = len(dens_sorted)
    t1 = dens_sorted[n//3]; t2 = dens_sorted[2*n//3]
    def dens_bucket(d):
        if d <= t1: return 'low'
        if d <= t2: return 'medium'
        return 'high'
    for p in verified:
        p['density_bucket'] = dens_bucket(p['defect_density'])
    print(f'density tertile cutoffs: low<={t1:.3f} medium<={t2:.3f}')
    print('size buckets:', dict(Counter(p['size_bucket'] for p in verified)))
    print('density buckets:', dict(Counter(p['density_bucket'] for p in verified)))

    # Stratified sampling: target 6/repo (48 total), within repo balance size x density
    rng = random.Random(SEED)
    by_repo = defaultdict(list)
    for p in verified:
        by_repo[p['repo']].append(p)
    selected = []
    for repo in sorted(by_repo):
        cands = by_repo[repo][:]
        rng.shuffle(cands)
        # sort by stratum rarity to spread: round-robin over (size,density) cells
        cells = defaultdict(list)
        for p in cands:
            cells[(p['size_bucket'], p['density_bucket'])].append(p)
        # deterministic cell order
        cell_keys = sorted(cells.keys())
        picked = []
        # round-robin pick one per cell until 6 or exhausted
        idx = {k:0 for k in cell_keys}
        while len(picked) < 6:
            progressed = False
            for k in cell_keys:
                if len(picked) >= 6: break
                if idx[k] < len(cells[k]):
                    picked.append(cells[k][idx[k]]); idx[k]+=1; progressed=True
            if not progressed: break
        # if repo has <6 verified, take all
        selected.extend(picked)
        print(f'{repo}: pool={len(cands)} picked={len(picked)} sizes={dict(Counter(p["size_bucket"] for p in picked))} dens={dict(Counter(p["density_bucket"] for p in picked))}')

    selected.sort(key=lambda p: (p['repo'], p['num']))
    print(f'\nselected total={len(selected)}')
    print('per repo:', dict(sorted(Counter(p["repo"] for p in selected).items())))
    print('size:', dict(Counter(p['size_bucket'] for p in selected)))
    print('density:', dict(Counter(p['density_bucket'] for p in selected)))
    print('total GT issues:', sum(p['num_of_issues'] for p in selected))
    print('rule mix top:', Counter(i.get('rule_name','(none)') for p in selected for i in p['issues']).most_common(10))

    # Write holdout48.json (pre-registered, before any run)
    doc = {
        'benchmark': 'Qodo/PR-Review-Bench',
        'source_file': 'git_code_review_bench_100_w_open_prs.jsonl',
        'round': 'validation_round3_haiku_phase',
        'seed': SEED,
        'selection_method': 'deterministic stratified sampling seed 42: ~6/repo across 8 repos, round-robin over (diff-size bucket x defect-density bucket) cells within repo; diff_lines/diff_files computed via git fetch+diff (prepare.py logic) for all 80 untouched PRs before sampling',
        'size_buckets': {'small': '<=200 lines', 'medium': '200-500 lines', 'large': '>500 lines'},
        'density_buckets': {'low': f'issues/100 lines <= {t1:.4f}', 'medium': f'<= {t2:.4f}', 'high': f'> {t2:.4f}'},
        'density_tertile_cutoffs': {'t1': t1, 't2': t2},
        'pool_size': len(pool), 'used_excluded': len(used), 'untouched_pool': len(remaining),
        'verified_pool': len(verified), 'verify_failed': failed,
        'subset_size': len(selected),
        'prs': selected,
        'pr_ids': [f"{p['repo']}#{p['num']}" for p in selected],
        'strata_summary': {
            'per_repo': dict(sorted(Counter(p['repo'] for p in selected).items())),
            'by_size': dict(Counter(p['size_bucket'] for p in selected)),
            'by_density': dict(Counter(p['density_bucket'] for p in selected)),
            'total_gt_issues': sum(p['num_of_issues'] for p in selected),
        },
    }
    OUT.write_text(json.dumps(doc, indent=1))
    print(f'wrote {OUT} ({len(selected)} PRs)')
    return 0 if len(selected)==48 and not failed else 1

if __name__ == '__main__':
    sys.exit(main())
