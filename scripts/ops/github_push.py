#!/usr/bin/env python3
"""Safe GitHub push wrapper for OpenClaw agents.

Usage:
  python scripts/ops/github_push.py --branch openclaw/fix-xyz --message "fix: xyz"
  python scripts/ops/github_push.py --branch main --message "hotfix" --confirm CONFIRM_PUSH_MAIN

Rules:
- If branch != "main": pushes to that branch, creating it locally if needed.
- If branch == "main": requires --confirm CONFIRM_PUSH_MAIN, otherwise aborts.
- Always runs `git fetch` + `git rebase origin/<branch>` before pushing
  (no-op if the remote branch doesn't exist yet).
- Refuses to push if the working tree is dirty unless --allow-dirty is set.
- Every outcome (ok or error) writes one JSONL line to scripts/ops/ops_log.jsonl.

Designed to be invoked by OpenClaw via the developer / operator SOULs.
Humans can invoke directly too; behaviour is identical.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

# Make sibling `log_utils` importable regardless of cwd.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from log_utils import write_ops_log  # noqa: E402

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def run(cmd, cwd=None, check=True):
    result = subprocess.run(
        cmd,
        cwd=cwd or REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\n"
            f"STDOUT: {result.stdout}\n"
            f"STDERR: {result.stderr}"
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branch", required=True, help="Branch to push")
    parser.add_argument("--message", required=True, help="Commit message")
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow pushing with uncommitted changes (also commits them with --message).",
    )
    parser.add_argument(
        "--confirm",
        default="",
        help="Required for pushing to main: CONFIRM_PUSH_MAIN",
    )
    args = parser.parse_args()

    os.chdir(REPO_ROOT)

    # Dirty-tree guard
    status = run(["git", "status", "--porcelain"], check=False)
    dirty = bool(status.stdout.strip())
    if dirty and not args.allow_dirty:
        write_ops_log("github_push", "error", {
            "branch": args.branch,
            "reason": "dirty_working_tree",
            "hint": "re-invoke with --allow-dirty if the dirty state is intentional",
        })
        print(
            "Working tree is dirty. Refusing to push.\n"
            "  - commit or stash the changes yourself, OR\n"
            "  - re-run with --allow-dirty to commit + push in one shot.",
            file=sys.stderr,
        )
        return 1

    # Main branch guard
    if args.branch == "main" and args.confirm != "CONFIRM_PUSH_MAIN":
        write_ops_log("github_push", "error", {
            "branch": args.branch,
            "reason": "missing_confirm_for_main",
        })
        print(
            "Refusing to push to main without --confirm CONFIRM_PUSH_MAIN.",
            file=sys.stderr,
        )
        return 1

    try:
        # Always start from fresh remote state
        run(["git", "fetch", "origin"])

        # Checkout target branch (create locally if needed for non-main)
        existing = run(["git", "branch", "--list", args.branch], check=False).stdout.strip()
        if not existing:
            if args.branch == "main":
                run(["git", "checkout", "main"])
            else:
                run(["git", "checkout", "-b", args.branch])
        else:
            run(["git", "checkout", args.branch])

        # Rebase on origin if the remote branch exists
        remote_has_branch = run(
            ["git", "ls-remote", "--exit-code", "--heads", "origin", args.branch],
            check=False,
        ).returncode == 0
        if remote_has_branch:
            run(["git", "rebase", f"origin/{args.branch}"])

        # If --allow-dirty, commit whatever was modified
        if args.allow_dirty and dirty:
            run(["git", "add", "-A"])
            run(["git", "commit", "-m", args.message], check=False)

        # Push (set upstream if brand-new branch)
        if remote_has_branch:
            run(["git", "push", "origin", args.branch])
        else:
            run(["git", "push", "-u", "origin", args.branch])

        head_sha = run(["git", "rev-parse", "--short", "HEAD"], check=False).stdout.strip()
        write_ops_log("github_push", "ok", {
            "branch": args.branch,
            "message": args.message,
            "head_sha": head_sha,
            "allow_dirty_used": bool(args.allow_dirty),
        })
        print(f"Pushed {args.branch} @ {head_sha}")
        return 0

    except Exception as exc:
        write_ops_log("github_push", "error", {
            "branch": args.branch,
            "error": str(exc),
        })
        print(f"github_push failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
