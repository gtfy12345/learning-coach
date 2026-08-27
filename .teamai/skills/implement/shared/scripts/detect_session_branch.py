#!/usr/bin/env python3
"""Detect whether the current branch matches a plan session branch."""

from __future__ import annotations

import argparse
import json
import re


SESSION_BRANCH_PATTERN = r"^(?:feat|fix|opt|docs)/{stem}-\d{{4}}(?:-\d+)?$"


def detect_session_branch(
    *,
    plan_name: str,
    current_branch: str,
    branch_stem: str | None = None,
) -> dict[str, object]:
    stem = branch_stem or plan_name
    pattern = SESSION_BRANCH_PATTERN.format(stem=re.escape(stem))
    matches = re.match(pattern, current_branch) is not None

    if matches:
        reason = "branch name matches session feature branch contract"
    else:
        reason = "current branch does not match session feature branch contract"

    return {
        "currentBranch": current_branch,
        "branchStem": stem,
        "matchesSessionBranch": matches,
        "reason": reason,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect whether the current branch matches a plan session branch"
    )
    parser.add_argument("--plan-name", required=True, help="Plan name used as default stem")
    parser.add_argument("--current-branch", required=True, help="Current git branch name")
    parser.add_argument(
        "--branch-stem",
        help="Explicit branch stem override (defaults to --plan-name)",
    )
    args = parser.parse_args()

    result = detect_session_branch(
        plan_name=args.plan_name,
        current_branch=args.current_branch,
        branch_stem=args.branch_stem,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
