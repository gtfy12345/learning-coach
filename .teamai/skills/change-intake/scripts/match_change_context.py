#!/usr/bin/env python3
"""Rank plan targets for a free-form bugfix/feature-change request."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

try:
    import yaml
except ImportError:
    print(
        "ERROR: PyYAML is not installed.\n"
        "Install it with: pip3 install PyYAML",
        file=sys.stderr,
    )
    sys.exit(1)

TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9_./:-]*|[\u4e00-\u9fff]{2,}", re.IGNORECASE)
STATUS_PATTERN = re.compile(r"^\s*>\s*\*\*状态\*\*:\s*([^\n]+)$", re.MULTILINE)
SPLIT_PATTERN = re.compile(r"[/._:-]+")
STATUS_PRIORITY = {
    "active": 0,
    "draft": 1,
    "completed": 2,
    "superseded": 3,
    "deprecated": 4,
    "unknown": 5,
}
HISTORICAL_STATUS_MAP = {
    "实施中": "active",
    "已完成": "completed",
    "废弃": "deprecated",
}
FIELD_WEIGHTS = {
    "aliases": (8, 4),
    "keywords": (6, 3),
    "relatedBugs": (10, 5),
    "relatedSpecs": (5, 2),
    "packages": (4, 2),
    "uiRoutes": (6, 3),
    "apiNames": (6, 3),
    "commands": (5, 3),
    "contextName": (4, 2),
    "targetName": (3, 1),
    "planFile": (2, 1),
    "specFile": (2, 1),
    "references": (2, 1),
}


def string_list(owner: dict, field_name: str) -> list[str]:
    """Read an optional list[str] field without exploding invalid scalars."""
    value = owner.get(field_name)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def tokenize(text: str) -> set[str]:
    """Tokenize English identifiers and contiguous Chinese phrases."""
    if not text:
        return set()
    tokens = set()
    for raw in TOKEN_PATTERN.findall(text):
        normalized = raw.lower()
        tokens.add(normalized)
        for part in SPLIT_PATTERN.split(normalized):
            if part:
                tokens.add(part)
    return tokens


def normalize_status(raw_status: str) -> str:
    """Normalize a markdown Header status value."""
    if not raw_status:
        return "unknown"
    value = raw_status.strip()
    value = HISTORICAL_STATUS_MAP.get(value, value).lower()
    return value if value in STATUS_PRIORITY else "unknown"


def read_plan_status(plan_path: str) -> str:
    """Extract Header 状态 from a markdown plan file."""
    if not os.path.isfile(plan_path):
        return "unknown"

    with open(plan_path, "r", encoding="utf-8") as f:
        text = f.read()

    match = STATUS_PATTERN.search(text)
    if not match:
        return "unknown"
    return normalize_status(match.group(1))


def make_abs(plan_dir: str, rel_path: str | None) -> str | None:
    """Resolve a plan-relative file path to an absolute path."""
    if not rel_path:
        return None
    return os.path.normpath(os.path.join(plan_dir, rel_path))


def iter_context_targets(plan_root: str):
    """Yield one record per plan target across docs/plan/*/context.yaml."""
    abs_plan_root = os.path.abspath(plan_root)
    if not os.path.isdir(abs_plan_root):
        return

    for entry in sorted(os.listdir(abs_plan_root)):
        plan_dir = os.path.join(abs_plan_root, entry)
        if not os.path.isdir(plan_dir):
            continue

        context_path = os.path.join(plan_dir, "context.yaml")
        if not os.path.isfile(context_path):
            continue

        with open(context_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            continue

        spec = data.get("spec")
        metadata = data.get("metadata")
        if not isinstance(spec, dict) or not isinstance(metadata, dict):
            continue

        top_discovery = spec.get("discovery")
        if not isinstance(top_discovery, dict):
            top_discovery = {}
        targets = spec.get("targets")
        if not isinstance(targets, dict):
            continue

        context_name = metadata.get("name", entry)
        for target_name, target in sorted(targets.items()):
            if not isinstance(target, dict):
                continue

            target_discovery = target.get("discovery")
            if not isinstance(target_discovery, dict):
                target_discovery = {}

            plan_path = make_abs(plan_dir, target.get("plan"))
            spec_path = make_abs(plan_dir, target.get("spec"))
            references = [
                make_abs(plan_dir, ref)
                for ref in target.get("references", [])
                if isinstance(ref, str)
            ]
            references = [ref for ref in references if ref]
            status = read_plan_status(plan_path) if plan_path else "unknown"

            yield {
                "contextName": context_name,
                "contextPath": context_path,
                "planDir": plan_dir,
                "target": target_name,
                "status": status,
                "files": {
                    "plan": plan_path,
                    "checklist": make_abs(plan_dir, target.get("checklist")),
                    "spec": spec_path,
                    "testPlan": make_abs(plan_dir, target.get("testPlan")),
                    "testChecklist": make_abs(plan_dir, target.get("testChecklist")),
                    "references": references,
                },
                "discovery": {
                    "aliases": string_list(top_discovery, "aliases"),
                    "keywords": string_list(top_discovery, "keywords"),
                    "relatedBugs": string_list(top_discovery, "relatedBugs"),
                    "relatedSpecs": string_list(top_discovery, "relatedSpecs"),
                    "packages": string_list(target_discovery, "packages"),
                    "uiRoutes": string_list(target_discovery, "uiRoutes"),
                    "apiNames": string_list(target_discovery, "apiNames"),
                    "commands": string_list(target_discovery, "commands"),
                },
            }


def score_discovery_values(
    query_text: str,
    query_tokens: set[str],
    field_name: str,
    values: list[str],
) -> tuple[int, list[str]]:
    """Score one discovery field against the query."""
    exact_weight, partial_weight = FIELD_WEIGHTS[field_name]
    score = 0
    reasons = []
    seen = set()

    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue

        normalized = value.strip().lower()
        value_tokens = tokenize(normalized)
        exact_hit = len(normalized) >= 2 and normalized in query_text
        overlap = query_tokens & value_tokens
        contribution = 0

        if exact_hit:
            contribution = exact_weight
        if overlap:
            contribution = max(contribution, partial_weight * len(overlap))

        if contribution <= 0:
            continue

        score += contribution
        reason = f"{field_name}={value}"
        if reason not in seen:
            reasons.append(reason)
            seen.add(reason)

    return score, reasons


def score_candidate(query_text: str, query_tokens: set[str], candidate: dict) -> tuple[int, list[str]]:
    """Score one target candidate."""
    score = 0
    reasons = []

    discovery = candidate["discovery"]
    for field_name in (
        "aliases",
        "keywords",
        "relatedBugs",
        "relatedSpecs",
        "packages",
        "uiRoutes",
        "apiNames",
        "commands",
    ):
        field_score, field_reasons = score_discovery_values(
            query_text, query_tokens, field_name, discovery.get(field_name, [])
        )
        score += field_score
        reasons.extend(field_reasons)

    fallback_values = {
        "contextName": [candidate["contextName"]],
        "targetName": [candidate["target"]],
        "planFile": [],
        "specFile": [],
        "references": [],
    }

    plan_path = candidate["files"].get("plan")
    if plan_path:
        fallback_values["planFile"].append(os.path.splitext(os.path.basename(plan_path))[0])

    spec_path = candidate["files"].get("spec")
    if spec_path:
        fallback_values["specFile"].append(os.path.splitext(os.path.basename(spec_path))[0])

    fallback_values["references"].extend(
        os.path.splitext(os.path.basename(path))[0]
        for path in candidate["files"].get("references", [])
    )

    for field_name, values in fallback_values.items():
        field_score, field_reasons = score_discovery_values(
            query_text, query_tokens, field_name, values
        )
        score += field_score
        reasons.extend(field_reasons)

    # Prefer active/draft plans as a tie-breaker, not as a primary score source.
    if score > 0 and candidate["status"] == "active":
        score += 1

    deduped_reasons = []
    seen = set()
    for reason in reasons:
        if reason in seen:
            continue
        deduped_reasons.append(reason)
        seen.add(reason)

    return score, deduped_reasons


def assess_confidence(candidates: list[dict]) -> str:
    """Return high / medium / low / none based on top score separation."""
    if not candidates or candidates[0]["score"] <= 0:
        return "none"

    top_score = candidates[0]["score"]
    second_score = candidates[1]["score"] if len(candidates) > 1 else 0
    delta = top_score - second_score

    if top_score >= 12 and delta >= 3:
        return "high"
    if top_score >= 7 and delta >= 2:
        return "medium"
    return "low"


def match_change_contexts(plan_root: str, query: str, limit: int = 3) -> dict:
    """Score all plan targets and return the best candidates."""
    normalized_query = query.strip().lower()
    query_tokens = tokenize(normalized_query)
    scored = []

    for candidate in iter_context_targets(plan_root):
        score, reasons = score_candidate(normalized_query, query_tokens, candidate)
        if score <= 0:
            continue

        scored.append(
            {
                "plan": os.path.basename(candidate["planDir"]),
                "target": candidate["target"],
                "status": candidate["status"],
                "score": score,
                "needsFollowup": candidate["status"] == "completed",
                "contextPath": candidate["contextPath"],
                "files": candidate["files"],
                "reasons": reasons,
            }
        )

    scored.sort(
        key=lambda item: (
            -item["score"],
            STATUS_PRIORITY.get(item["status"], STATUS_PRIORITY["unknown"]),
            item["plan"],
            item["target"],
        )
    )
    limited = scored[:limit]
    confidence = assess_confidence(limited)
    recommended = limited[0] if limited else None

    return {
        "query": query,
        "confidence": confidence,
        "recommended": recommended,
        "candidates": limited,
    }


def main():
    parser = argparse.ArgumentParser(description="Match a free-form issue to plan targets")
    parser.add_argument("--plan-root", default="docs/plan", help="Path to docs/plan root")
    parser.add_argument("--query", required=True, help="Free-form bug/change description")
    parser.add_argument("--limit", type=int, default=3, help="Max candidates to return")
    args = parser.parse_args()

    result = match_change_contexts(
        plan_root=args.plan_root,
        query=args.query,
        limit=max(args.limit, 1),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
