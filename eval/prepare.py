#!/usr/bin/env python3
"""Build the fixed evaluation subset for the Cruise Line PR-review optimization.

Selects ~20 PRs from Qodo/PR-Review-Bench with modest diffs, stratified across
repos, then verifies that each repo clones, the PR head fetches, and the diff
computes non-empty. Writes eval/manifest.json.

Usage:  python eval/prepare.py [--verify]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BENCH = ROOT / "data" / "git_code_review_bench_100_w_open_prs.jsonl"
META = ROOT / "data" / "pr_meta.json"
MANIFEST = ROOT / "manifest.json"
REPOS = ROOT / "data" / "repos"
CLONE_BASE = "https://github.com/agentic-review-benchmarks"

# Subset constraints (task spec: <=20 changed files, <=600 changed lines)
MAX_CHANGED_FILES = 20
MAX_CHANGED_LINES = 600
TARGET_PRS = 20
PER_REPO_MAX = 3
PER_REPO_MIN = 2


def sh(cmd: list[str], cwd: Path | None = None, timeout: int = 300) -> tuple[int, str, str]:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def load_bench() -> list[dict]:
    recs = [json.loads(l) for l in BENCH.read_text().splitlines() if l.strip()]
    meta = {f"{m['repo']}#{m['num']}": m for m in json.loads(META.read_text())}
    out = []
    for r in recs:
        parts = r["pr_url_to_review"].split("/")
        repo, num = parts[4], int(parts[-1])
        m = meta.get(f"{repo}#{num}", {})
        if "err" in m and m["err"]:
            continue
        n_with_path = sum(1 for i in r["issues"] if i.get("file_path"))
        out.append({
            "repo": repo,
            "num": num,
            "url": r["pr_url_to_review"],
            "title": m.get("title") or "",
            "body": m.get("body") or "",
            "author": "",
            "base_ref": m.get("base") or "main",
            "head_sha": m.get("head") or "",
            "base_sha": m.get("base_sha") or "",
            "changed_files": m.get("changed_files") or 0,
            "additions": m.get("additions") or 0,
            "deletions": m.get("deletions") or 0,
            "num_of_issues": r["num_of_issues"],
            "n_issues_with_path": n_with_path,
            "issues": r["issues"],
        })
    return out


def select(pool: list[dict]) -> list[dict]:
    """Stratified pick: modest diffs, issues with file anchors, >=2 per repo."""
    by_repo: dict[str, list[dict]] = defaultdict(list)
    for p in pool:
        lines = p["additions"] + p["deletions"]
        if p["changed_files"] > MAX_CHANGED_FILES or lines > MAX_CHANGED_LINES:
            continue
        if p["changed_files"] < 1:
            continue
        # Need at least half the ground-truth issues anchored to a file path so the
        # line-overlap matcher has something to bind to.
        if p["n_issues_with_path"] * 2 < p["num_of_issues"]:
            continue
        by_repo[p["repo"]].append(p)

    selected: list[dict] = []
    # Round 1: guarantee PER_REPO_MIN from each repo, best (most anchored, fewest lines)
    for repo in sorted(by_repo):
        cands = sorted(by_repo[repo], key=lambda p: (-p["n_issues_with_path"], p["additions"] + p["deletions"]))
        selected.extend(cands[:PER_REPO_MIN])

    # Round 2: top up to TARGET_PRS, spread evenly, respecting PER_REPO_MAX
    counts = defaultdict(int)
    for p in selected:
        counts[p["repo"]] += 1
    remaining = []
    for repo in sorted(by_repo):
        extra = sorted(by_repo[repo], key=lambda p: (-p["n_issues_with_path"], p["additions"] + p["deletions"]))
        for p in extra:
            if p not in selected and counts[repo] < PER_REPO_MAX:
                remaining.append((repo, p))
    # interleave repos so no single repo dominates
    remaining.sort(key=lambda rp: (counts[rp[0]], rp[1]["additions"] + rp[1]["deletions"]))
    for repo, p in remaining:
        if len(selected) >= TARGET_PRS:
            break
        if counts[repo] >= PER_REPO_MAX:
            continue
        selected.append(p)
        counts[repo] += 1

    selected.sort(key=lambda p: (p["repo"], p["num"]))
    return selected


def repo_dir(repo: str) -> Path:
    return REPOS / repo


def ensure_repo(repo: str) -> Path:
    """Blob-filtered shallow clone; cheap on disk, fetches blobs on demand."""
    d = repo_dir(repo)
    if not (d / ".git").exists():
        d.parent.mkdir(parents=True, exist_ok=True)
        rc, _, err = sh(["git", "clone", "--depth=50", "--filter=blob:none", "--no-checkout",
                         f"{CLONE_BASE}/{repo}.git", str(d)], timeout=900)
        if rc != 0:
            raise RuntimeError(f"clone failed for {repo}: {err[:300]}")
    return d


def compute_diff(repo: str, num: int, base_ref: str, head_sha: str) -> tuple[str, str]:
    """Fetch the PR head and compute the diff the way the sandbox does.

    Returns (diff, head_sha_resolved).
    """
    d = ensure_repo(repo)
    rc, _, err = sh(["git", "fetch", "origin", "--depth=50",
                     f"+refs/pull/{num}/head:refs/remotes/origin/pr-head"], cwd=d, timeout=900)
    if rc != 0:
        raise RuntimeError(f"fetch PR head failed: {err[:300]}")

    resolved = head_sha
    rc, out, _ = sh(["git", "rev-parse", "origin/pr-head"], cwd=d)
    if rc == 0 and out.strip():
        resolved = out.strip()

    rc, _, err = sh(["git", "checkout", "--force", resolved], cwd=d, timeout=900)
    if rc != 0:
        raise RuntimeError(f"checkout failed: {err[:300]}")

    # Mirror the sandbox diff strategy: base branch fetch + 3-way diff fallbacks
    sh(["git", "fetch", "origin", f"+refs/heads/{base_ref}:refs/remotes/origin/{base_ref}"],
       cwd=d, timeout=900)
    diff = ""
    for cmd in (["git", "diff", f"origin/{base_ref}...HEAD"],
                ["git", "diff", f"origin/{base_ref}..HEAD"],
                ["git", "diff", f"origin/{base_ref}", "HEAD"]):
        rc, out, _ = sh(cmd, cwd=d, timeout=600)
        if rc == 0 and out.strip():
            diff = out
            break
    return diff, resolved


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="clone + fetch + diff each PR")
    ap.add_argument("--clean", action="store_true", help="remove clones after verifying")
    args = ap.parse_args()

    pool = load_bench()
    sel = select(pool)
    print(f"pool={len(pool)} selected={len(sel)}")
    counts = defaultdict(int)
    for p in sel:
        counts[p["repo"]] += 1
    print("per-repo:", dict(sorted(counts.items())))

    if not args.verify:
        MANIFEST.write_text(json.dumps({
            "benchmark": "Qodo/PR-Review-Bench",
            "source_file": str(BENCH.name),
            "subset_size": len(sel),
            "selection_criteria": {
                "max_changed_files": MAX_CHANGED_FILES,
                "max_changed_lines": MAX_CHANGED_LINES,
                "min_anchored_issue_ratio": 0.5,
                "stratified_by_repo": True,
            },
            "prs": sel,
        }, indent=1))
        print(f"wrote {MANIFEST} (unverified)")
        return 0

    # Verified manifest: prove clone + head fetch + diff for every PR
    ok, failed = [], []
    for i, p in enumerate(sel, 1):
        pid = f"{p['repo']}#{p['num']}"
        try:
            diff, sha = compute_diff(p["repo"], p["num"], p["base_ref"], p["head_sha"])
            nfiles = sum(1 for l in diff.splitlines() if l.startswith("diff --git "))
            if not diff.strip():
                raise RuntimeError("empty diff")
            p["head_sha"] = sha
            p["diff_lines"] = len(diff.splitlines())
            p["diff_files"] = nfiles
            p["diff_chars"] = len(diff)
            ok.append(p)
            print(f"[{i:2d}/{len(sel)}] OK  {pid:22s} files={nfiles:3d} lines={len(diff.splitlines()):5d} issues={p['num_of_issues']}")
        except Exception as e:  # noqa: BLE001
            failed.append({"id": pid, "error": str(e)[:200]})
            print(f"[{i:2d}/{len(sel)}] FAIL {pid:22s} {str(e)[:120]}")

    print(f"\nverified: {len(ok)} ok, {len(failed)} failed")
    if failed:
        print("failures:", json.dumps(failed, indent=1))

    MANIFEST.write_text(json.dumps({
        "benchmark": "Qodo/PR-Review-Bench",
        "source_file": str(BENCH.name),
        "subset_size": len(ok),
        "verified": True,
        "selection_criteria": {
            "max_changed_files": MAX_CHANGED_FILES,
            "max_changed_lines": MAX_CHANGED_LINES,
            "min_anchored_issue_ratio": 0.5,
            "stratified_by_repo": True,
        },
        "prs": ok,
    }, indent=1))
    print(f"wrote {MANIFEST} ({len(ok)} verified PRs)")

    if args.clean:
        shutil.rmtree(REPOS, ignore_errors=True)
        print("cleaned clones")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
