#!/usr/bin/env python3
"""Swap eval/manifest.json to holdout48 PRs (backup original), or restore.
Usage: python3 eval/swap_manifest.py swap|restore
Keeps harness files untouched (hash unchanged); run_review.mjs reads manifest.json only.
"""
import json, shutil, sys
from pathlib import Path
ROOT = Path('/home/azureuser/optimize-cruiseline/eval')
MAN = ROOT/'manifest.json'
BAK = ROOT/'manifest.json.bak_round2'
H48 = ROOT/'holdout48.json'
if sys.argv[1] == 'swap':
    if BAK.exists():
        print('backup already exists, refusing'); sys.exit(1)
    shutil.copy2(MAN, BAK)
    h = json.loads(H48.read_text())
    doc = {'benchmark': h['benchmark'], 'source_file': h['source_file'],
           'subset_size': h['subset_size'], 'verified': True,
           'selection_criteria': {'round': 'validation_round3_haiku_phase', 'seed': h['seed'],
                                  'method': h['selection_method']},
           'prs': h['prs']}
    MAN.write_text(json.dumps(doc, indent=1))
    print(f'swapped manifest to {len(h["prs"])} holdout48 PRs; backup at {BAK}')
elif sys.argv[1] == 'restore':
    if not BAK.exists():
        print('no backup found'); sys.exit(1)
    shutil.copy2(BAK, MAN)
    BAK.unlink()
    print('restored original manifest.json')
else:
    sys.exit('usage: swap|restore')
