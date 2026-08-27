"""L2 code review pre-check: deterministic file existence checks.

Verifies R-001 (checked checklist items have code files) and P-004
(plan-declared files exist on disk) before LLM semantic review.

Usage:
    python3 review_code_precheck.py --files-json PATH --phase-ids CSV [--json]
"""
import argparse
import glob
import json
import os
import sys

# Import parsers from review_plan.py (same directory)
from review_plan import (
    parse_plan_phases,
    parse_plan_file_declarations,
    parse_checklist_items,
)


def check_r001(plan_path: str, cl_path: str, phase_ids: list) -> list:
    """R-001: Checked [x] items must have corresponding code files.

    For each [x] item in the specified phases, find plan task file
    declarations and verify the files exist and are non-empty.
    """
    results = []
    cl_items = parse_checklist_items(cl_path)
    file_decls = parse_plan_file_declarations(plan_path)

    # Build phase_id → [file_declarations] mapping
    decl_by_phase = {}
    for d in file_decls:
        pid = d["phase_id"]
        decl_by_phase.setdefault(pid, []).append(d)

    for item in cl_items:
        if not item["checked"]:
            continue

        # Check if this item's section is in the requested phase_ids
        if item["section_id"] not in phase_ids:
            continue

        # Find file declarations for this task's phase
        phase_decls = decl_by_phase.get(item["section_id"], [])

        task_files = [
            d["exact_path"]
            for d in phase_decls
            if d["exact_path"] and d.get("task_id") == item["id"]
        ]
        if not task_files:
            phase_files = [
                d["exact_path"]
                for d in phase_decls
                if d["exact_path"] and d.get("task_id") is None
            ]
            if len(phase_files) == 1:
                task_files = phase_files

        if not task_files:
            # No file declarations for this task — nothing to check
            continue

        for fpath in task_files:
            if os.path.exists(fpath) and os.path.getsize(fpath) > 0:
                results.append({
                    "check_id": "R-001",
                    "status": "pass",
                    "item_id": item["id"],
                    "file": fpath,
                    "message": f"File exists and non-empty: {fpath}",
                })
            else:
                reason = "not found" if not os.path.exists(fpath) else "empty (0 bytes)"
                results.append({
                    "check_id": "R-001",
                    "status": "fail",
                    "item_id": item["id"],
                    "file": fpath,
                    "message": f"File {reason}: {fpath}",
                })

    return results


def check_p004(plan_path: str, phase_ids: list) -> list:
    """P-004: Plan-declared files within phase scope must exist.

    Checks both exact paths and glob patterns for specified phases.
    """
    results = []
    file_decls = parse_plan_file_declarations(plan_path)

    for d in file_decls:
        if d["phase_id"] not in phase_ids:
            continue

        if d["exact_path"]:
            fpath = d["exact_path"]
            if os.path.exists(fpath):
                results.append({
                    "check_id": "P-004",
                    "status": "pass",
                    "phase_id": d["phase_id"],
                    "file": fpath,
                    "message": f"Declared file exists: {fpath}",
                })
            else:
                results.append({
                    "check_id": "P-004",
                    "status": "fail",
                    "phase_id": d["phase_id"],
                    "file": fpath,
                    "message": f"Declared file missing: {fpath}",
                })
        elif d["glob"]:
            pattern = d["glob"]
            matches = glob.glob(pattern, recursive=True)
            if matches:
                results.append({
                    "check_id": "P-004",
                    "status": "pass",
                    "phase_id": d["phase_id"],
                    "file": pattern,
                    "message": f"Glob '{pattern}' matched {len(matches)} file(s)",
                })
            else:
                results.append({
                    "check_id": "P-004",
                    "status": "fail",
                    "phase_id": d["phase_id"],
                    "file": pattern,
                    "message": f"Glob '{pattern}' matched 0 files",
                })

    return results


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="L2 code pre-check: R-001 and P-004 file existence"
    )
    parser.add_argument("--files-json", required=True,
                        help="validate_context.py output JSON path")
    parser.add_argument("--phase-ids",
                        help="Comma-separated phase IDs to check")
    parser.add_argument("--json", action="store_true", default=True,
                        help="Output JSON (default)")

    args = parser.parse_args()

    if not args.phase_ids:
        print("ERROR: --phase-ids is required", file=sys.stderr)
        sys.exit(2)

    if not os.path.exists(args.files_json):
        print(f"ERROR: --files-json not found: {args.files_json}",
              file=sys.stderr)
        sys.exit(2)

    with open(args.files_json, "r", encoding="utf-8") as f:
        files_data = json.load(f)

    target_discovery = files_data.get("targetDiscovery", {})

    # Build role → path mapping
    files = {}
    for entry in files_data.get("files", []):
        role = entry.get("role")
        path = entry.get("path")
        if role and path:
            files[role] = path

    plan_path = files.get("plan")
    cl_path = files.get("checklist")
    if not plan_path or not cl_path:
        print("ERROR: files.json must contain plan and checklist roles",
              file=sys.stderr)
        sys.exit(2)

    phase_ids = [pid.strip() for pid in args.phase_ids.split(",")
                 if pid.strip()]

    # Run checks
    all_results = []
    all_results.extend(check_r001(plan_path, cl_path, phase_ids))
    all_results.extend(check_p004(plan_path, phase_ids))

    # Build summary
    pass_count = sum(1 for r in all_results if r["status"] == "pass")
    fail_count = sum(1 for r in all_results if r["status"] == "fail")

    # Determine phase IDs that are unknown to the plan parser.
    # Missing plan-declared files metadata no longer blocks new-format plans.
    plan_phases = parse_plan_phases(plan_path)
    plan_phase_ids = {p["id"] for p in plan_phases}
    scope_undetermined = [
        pid for pid in phase_ids
        if pid not in plan_phase_ids
    ]

    output = {
        "precheck_results": all_results,
        "summary": {
            "total": len(all_results),
            "pass": pass_count,
            "fail": fail_count,
        },
        "scopeUndeterminedPhaseIds": scope_undetermined,
        "targetDiscovery": target_discovery,
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))
    sys.exit(1 if fail_count > 0 else 0)


if __name__ == "__main__":
    main()
