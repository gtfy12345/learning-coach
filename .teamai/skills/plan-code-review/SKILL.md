---
name: plan-code-review
description: "Review or fix code against spec/plan/checklist context. Use when the user wants L2 code review or remediation for already-implemented checklist phases. Reuses implement-owned shared plan-context scripts plus the existing review_code_precheck.py. Supports /plan-code-review PLAN_NAME [target] [--base-rev GIT_REV] [--fix]."
---

# Plan Code Review Skill

L2 code review for `code ↔ spec/plan/checklist`. This skill checks completed phases,
reports drift, and, when the user confirms fixes, routes remediation through
`/tdd --section`. It is not an end-to-end delivery entry point.

## Usage

- `/plan-code-review <plan-name>` - Review the default target of the named plan
- `/plan-code-review <plan-name> <target>` - Review a specific target
- `/plan-code-review <plan-name> [target] --base-rev <git-rev>` - Include git diff context
- `/plan-code-review <plan-name> [target] --fix` - Review, preview, confirm, and fix via `/tdd --section`
- `/plan-code-review <plan-name> [target] --fix --base-rev <git-rev>` - Same with git diff context
- `/plan-code-review -h` - Show help only
- `/plan-code-review -h -v` - Show verbose help (including workflow)

Flag rules:

- Plan name is mandatory
- `--fix` implies a review pass first
- Review is advisory; fix remains preview-only until user confirmation

## Shared Resources

Use the implement-owned shared resources:

- `.agent-skills/implement/shared/scripts/validate_context.py`
- `.agent-skills/implement/shared/references/plan-context-contract.md`
- `.agent-skills/implement/scripts/review_code_precheck.py`
- `.agent-skills/implement/scripts/review_plan.py` for parser-compatible phase/file semantics

Reviewer rule:

- New plan docs are sequential-only by default.
- Phase `<!-- files: -->` metadata is optional legacy input, not a required scope contract.

## Workflow

### Step 0: Handle help flags

- `-h`/`--help`: show skill name, description, usage, then stop.
- `-h -v`/`--help --verbose`: show usage + full workflow, then stop.

### Step 1: Resolve plan and target

1. Require an explicit `plan-name`.
2. Read `docs/plan/{name}/context.yaml`.
3. Determine target from the explicit argument or `spec.defaultTarget`.
4. If target is missing, stop and show available targets.

### Step 2: Validate manifest and collect normalized file set

Run:

```bash
python3 .agent-skills/implement/shared/scripts/validate_context.py \
  --context docs/plan/{name}/context.yaml \
  --docs-root docs \
  --target {target}
```

Persist the validator JSON to a temp file. Use the shared plan-context contract for
role mapping and common errors.

### Step 3: Determine code review scope

1. Main scope: checklist phases with at least one `[x]` item.
2. Gather concrete code scope from the strongest available sources, in this order:
   - `--base-rev` git diff filtered to files relevant to the current target
   - target-level discovery in `context.yaml` (`packages`, `uiRoutes`, `apiNames`, `commands`)
   - plan task declarations such as `**文件**:` or legacy `<!-- files: -->`
3. Missing phase file declarations do not invalidate the review by themselves.
4. If no concrete file set can be derived, fall back to target-level advisory review.
5. `--fix` requires a concrete checklist-section mapping; target-level-only findings stay preview-only until the user confirms the section.

Code scope sources:

- **Source A (git diff)**: if `--base-rev` is provided, `git diff --name-only {base}..HEAD`
- **Source B (context discovery)**: target `packages` plus other target discovery hints from validated `context.yaml`
- **Source C (plan declarations)**: `**文件**:` exact paths and legacy `<!-- files: -->` globs when present

### Step 4: Run deterministic pre-check

Call:

```bash
python3 .agent-skills/implement/scripts/review_code_precheck.py \
  --files-json {validated-files-json} \
  --phase-ids {comma-separated-phase-ids}
```

Use the pre-check output to identify:

- deterministic pass/fail results
- which declared files were verifiable from plan declarations
- which phases still need target-level or diff-derived semantic review

### Step 5: Execute L2 semantic review

For each in-scope phase:

1. Read code files for the phase.
2. Read relevant spec sections.
3. Read plan task descriptions.
4. Read checklist items and completion status.
5. Merge deterministic pre-check results with LLM findings.

Review dimensions:

- `R-series`: consistency with spec definitions
- `P-series`: completeness against plan tasks and error handling
- `E-series`: best-practice code quality, tests, naming, security

Output rules:

- Each finding includes check ID, severity, description, and `file:line`.
- Cite the relevant spec/plan evidence.
- Distinguish drift from acceptable design-preserving extension.
- Put any extra findings under `Extended Findings` with `X-L2-*` IDs.

### Step 6: Branch by mode

**Review mode**:

1. Review all in-scope phases.
2. Aggregate the report.
3. Stop.

**Fix mode**:

1. Generate fix proposals with diff-style previews.
2. Explicitly degrade target-level-only findings to preview-only when no checklist section can be mapped automatically.
3. Wait for user confirmation.
4. For each accepted finding, map it to a checklist section.
5. Execute remediation only through `/tdd --section`.

### Step 7: Fix via `/tdd --section`

When the user accepts a fix proposal:

1. Map each accepted finding to a checklist section; unmappable findings stay preview-only.
2. If an item is incorrectly marked `[x]`, the preview must offer either:
   - reopen the item, or
   - append a remediation item
3. When a finding is supported only by target-level discovery or git diff, ask the user to confirm the checklist section before routing to `/tdd --section`.
4. Invoke:

```text
/tdd --file {checklist-path} --section {phase-prefix} --references {ref1},{ref2},...
```

5. After `/tdd` completes, run focused tests and adjacent/regression tests.
6. Verify compilation succeeds for affected packages.
7. Any test or compile failure means the fix is not applied.

## Guardrails

- Findings with no concrete checklist-section mapping are never auto-fixed.
- `/plan-code-review --fix` is remediation only; it does not own plan lifecycle sync or retrospective.
- Do not edit code directly outside the `/tdd` Red-Green-Refactor loop once fix mode is accepted.
