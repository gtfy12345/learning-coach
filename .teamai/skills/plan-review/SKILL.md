---
name: plan-review
description: "Review or fix spec/plan/checklist context documents for a plan target. Use when the user wants L1 review or document remediation for spec/plan/checklist consistency, including spec-owned issues that should be repaired in the same fix pass. Reuses implement-owned shared plan-context scripts and the existing review_plan.py deterministic checker. Supports /plan-review [plan-name] [target] [--fix]."
---

# Plan Review Skill

L1 document review for `spec ↔ plan ↔ checklist`. This skill owns review output and
document remediation. It does **not** implement code and does **not** hand off to `/tdd`.

## Usage

- `/plan-review` - List latest candidate plans and let user choose, then run review
- `/plan-review <plan-name>` - Review the default target of the named plan
- `/plan-review <plan-name> <target>` - Review a specific target
- `/plan-review <plan-name> [target] --fix` - Preview, confirm, and apply spec/plan/checklist/context fixes
- `/plan-review -h` - Show help only
- `/plan-review -h -v` - Show verbose help (including workflow)

Flag rules:

- `--fix` requires an explicit plan name
- No-plan mode exists only for review, not for fix
- Review is advisory and read-only

## Shared Resources

Use the implement-owned shared resources:

- `.agent-skills/implement/shared/scripts/list_context_candidates.py`
- `.agent-skills/implement/shared/scripts/validate_context.py`
- `.agent-skills/implement/shared/references/plan-context-contract.md`
- `.agent-skills/implement/scripts/review_plan.py`

Reviewer rule:

- New plan docs are sequential-only by default.
- `review_plan.py` must treat missing `执行模式`, missing phase HTML comments, and missing `<!-- phase-mapping: -->` as acceptable for new-format documents.
- Legacy `parallel` structure is still parsed when present so historical plans remain reviewable.

## Workflow

### Step 0: Handle help flags

- `-h`/`--help`: show skill name, description, usage, then stop.
- `-h -v`/`--help --verbose`: show usage + full workflow, then stop.

### Step 1: Resolve plan name

**With argument**:

1. Check if `docs/plan/{name}/` exists.
2. If not found, read `docs/plan/INDEX.md` and fuzzy-match plan names.
3. If multiple matches, ask the user to choose.
4. If no match, stop and report available plan names.

**Without argument**:

1. Run:

```bash
python3 .agent-skills/implement/shared/scripts/list_context_candidates.py \
  --plan-index docs/plan/INDEX.md \
  --plan-root docs/plan
```

2. Display numbered candidates with reasons.
3. Ask user to select one number.
4. If no candidates, show script output and stop.
5. If input is invalid, re-display the list and wait.

### Step 2: Read manifest and determine target scope

1. Read `docs/plan/{name}/context.yaml`.
2. Determine target:
   - If user passed `<target>`, use it.
   - Otherwise use `spec.defaultTarget`.
3. If target is not defined in `spec.targets`, stop and show available targets.

### Step 3: Validate manifest and collect normalized file set

Run:

```bash
python3 .agent-skills/implement/shared/scripts/validate_context.py \
  --context docs/plan/{name}/context.yaml \
  --docs-root docs \
  --target {target}
```

Use the shared plan-context contract to interpret `files[]`. Persist the validator JSON
to a temp file for the deterministic review script.

### Step 4: Run deterministic checks

Call:

```bash
python3 .agent-skills/implement/scripts/review_plan.py \
  --context docs/plan/{name}/context.yaml \
  --target {target} \
  --files-json {validated-files-json} \
  --check [--json] \
  [--agent-md AGENTS.md]
```

### Step 5: Branch by mode

**Review mode**:

1. Call `review_plan.py --check` and display the report.
2. Always proceed to semantic analysis, even if `semanticPending` is empty.
3. Merge deterministic findings and semantic findings into the final report, then stop.

**Fix mode**:

1. Call `review_plan.py --check --json` to collect `violations`, `semanticPending`, and `fixCandidates`.
2. Run semantic analysis to generate semantic fix suggestions across the current target's spec/plan/checklist/context documents.
3. Display combined preview grouped by document type and wait for user confirmation.
4. On confirmation:
   - call `review_plan.py --fix` for deterministic fixes
   - write only the semantic fixes explicitly confirmed by the user
   - if both spec and plan/checklist/context need updates, write spec first, then write downstream documents
5. Re-run `review_plan.py --check` to show post-fix results, then stop.

Exit-code handling:

- `0`: normal, display the result and continue
- `1`: issues found, still display the result
- `2`: input error, display stderr and stop

### Step 6: L1 semantic analysis

Baseline rule:

- Even if `review_plan.py` reports no `semanticPending`, still execute baseline semantic review.
- `semanticPending` is a prioritization hint, not the full semantic review scope.

Review dimensions:

- `Consistency`: terminology, state model, target scoping, truth-source boundaries, fit with repo patterns
- `Completeness`: success path, error path, boundary cases, non-goals, verification/test coverage
- `Best Practice`: security/privacy/authz, minimal scope, idempotency, concurrency, testability, maintainability

Baseline checks:

- `S-001`: spec section coverage
- `S-002`: error path coverage
- `S-003`: description alignment
- `S-004`: orphan judgment

Extension review:

- `X-L1-Value`: practical value / operator workflow closure
- `X-L1-Landing`: delivery and landing feasibility
- `X-L1-Risk`: security, privacy, and operational risk

### Step 7: Report contract

Final L1 report must use this structure:

1. `Findings`
2. `Dimension Coverage`
3. `Strengths`
4. `Open Questions / Assumptions`
5. `Optimization Opportunities`

Rules:

- Order findings by severity.
- Each finding must cite impact, evidence, and remediation direction.
- If a dimension has no material finding, explicitly say `No material finding`.
- Do not merge `Strengths` or `Optimization Opportunities` into `Findings`.

## Fix Guardrails

- `--fix` without plan name is an error.
- Fix mode only updates the current target's `spec` / `plan` / `checklist` / `context` documents; it never edits source code.
- Do not edit documents outside the validated file set for the current target.
- If a fix would change design or plan semantics beyond the user's confirmed intent rather than repair drift or requested document-owned issues, stop and confirm with the user first.
