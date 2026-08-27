---
name: design
description: "Design crystallizer: turn a converged design discussion into the minimal sufficient set of spec/plan/test/BDD documents. IMPORTANT: Invoke this skill automatically when a design discussion has converged and needs to be formalized into project documents. Triggers on /design, or when the user says 'crystallize this design', 'turn this into a spec', 'create spec and plan from this discussion', 'formalize this design', or otherwise indicates that a design conversation should produce actionable documents. Also triggers when the user has a design document or discussion file and wants to generate the matching plan/checklist/test suite."
---

# /design Skill

Turn a converged design discussion into the minimal sufficient set of project documents.
Instead of manually guiding the AI through 6-8 file creation steps, one command produces
exactly the documents the current need requires — no more, no less.

## Usage

```
/design {subject}                    # Extract from current conversation
/design {subject} --from {path}      # Extract from a docs/discuss/ file
/design -h                           # Show help
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `{subject}` | Yes | Topic identifier used for file naming (e.g., `sealed-secrets`, `wiki-sync`) |
| `--from {path}` | No | Path to a discussion/design file to extract from instead of conversation context |
| `-h` / `--help` | No | Show usage and stop |

## Workflow

### Step 1: Extract Design Brief

Gather structured information from the conversation context (or `--from` file). Map each
piece of discussion content to the Brief fields below.

| Brief Field | Source | Maps To |
|-------------|--------|---------|
| `subject` / `title` | Parameter + discussion title | File naming |
| `goals` | Stated design objectives | spec 2 |
| `decisions` | Confirmed choices (ID / decision / conclusion / rationale) | spec 3 |
| `acceptance_criteria` | criterion-id / Given / When / Then / Phase | spec Acceptance Criteria |
| `requirements` | Functional needs and constraints | spec 4-7 |
| `non_goals` | Explicitly excluded scope | spec Non-goals |
| `interfaces` | API / data structure definitions | spec 5 |
| `source_spec` | Existing spec path to reuse when no new spec is generated | context.yaml `spec` + summary |
| `components` | Involved components mapped to main code areas | plan phases + context discovery |
| `risks` | Risks and mitigations | plan Risks |
| `open_questions` | Unresolved items | spec Open Questions |
| `inferred_outputs` | Recommended document set (see Step 3) | Output scope |
| `bdd_scenarios` | Target test layers, numbering rules, and scenario IDs/reservations | bdd-test-plan + checklist BDD-Gate |
| `bdd_strategy` | Whether BDD phase gates are needed + rationale | BDD document generation |

The Brief is a transient confirmation artifact — it is never persisted as a file.

### Step 2: User Confirmation

Present the Brief to the user in a structured format:

1. **Summary table** with subject, goals, key decisions
2. **Recommended output scope** — which documents will be generated and why (see Step 3 logic)
3. **BDD strategy** — whether BDD phase gates are recommended and the reasoning
4. **Acceptance criteria summary** (if any criteria were extracted) + BDD scenario matrix (when BDD is active)

Wait for explicit user confirmation before proceeding. If the user cancels, stop without
generating any files.

### Step 3: Infer Minimal Sufficient Output Scope

Based on the Brief content, determine the smallest document set that fully serves the need.
Do not expose `--scope` or `--skip-bdd` flags — the scope is an LLM judgment call, not a
user toggle. This prevents users from accidentally under-scoping or over-generating.

**Decision logic:**

1. **Needs design landing?** (new architecture, trade-offs, interface contracts, schema changes)
   - Yes -> generate spec
   - No (pure implementation of existing design) -> skip spec, but require an explicit reusable spec path from current context or the user and store it as `source_spec`

2. **Needs execution plan?** (multi-step implementation, checklist tracking, team coordination)
   - Yes -> generate implementation.md + implementation-checklist.md + context.yaml
   - No (spec-only crystallization) -> stop after spec

3. **Needs test plan?** (unit testable components, complex logic, regression risk)
   - Yes -> generate unit-test-plan.md + unit-test-plan-checklist.md
   - No -> skip test plan

4. **Needs BDD phase gates?** (behavior phases that can be independently deployed and verified,
   acceptance criteria with Given/When/Then, end-to-end verification requirements)
   - Yes -> read `test/scenarios/README.md` plus the relevant layer `README.md` / `INDEX.md`, generate bdd-test-plan.md with scenario IDs that follow those conventions, add BDD-Gate items keyed by scenario IDs, add `bddPlan` to context.yaml
   - No -> skip BDD artifacts, no `bddPlan` in context.yaml

**Output the reasoning** for each decision so the user can challenge it in Step 2.

### Step 4: Generate Documents

Generate only the documents determined in Step 3. For each document type, follow the
corresponding template from the project documentation — reference the template, do not
inline-copy it (prevents template drift).

Before creating or modifying any file under `docs/`, invoke `/create-doc` and follow the
target directory README/INDEX rules. `/design` decides the minimal sufficient scope; `/create-doc`
owns the repository's document creation mechanics.

#### 4.1 Spec Document

- Path: `docs/spec/{subject}-{type}.md`
- Template source: `docs/spec/README.md` 4.1
- Naming: follow `docs/spec/README.md` 3 naming table (choose suffix by document type)
- Include Acceptance Criteria section (8) when criteria are present in the Brief
- Keep Acceptance Criteria descriptive; do not use `AC-*` as BDD-Gate machine references in new documents
- Use the spec's section numbering: 1-Overview through 10-Related Documents
- When Step 3 chose spec reuse instead of new spec generation, do not create a new spec file; keep the reused path in `source_spec`

#### 4.2 Implementation Plan + Checklist

- Plan path: `docs/plan/{subject}/implementation.md`
- Checklist path: `docs/plan/{subject}/implementation-checklist.md`
- Template source: `docs/plan/README.md` 5.1 / 5.2 / 5.6
- When BDD is needed: add `BDD-Gate:` items at the end of each behavior phase per `docs/plan/README.md` 5.6, using scenario IDs from `bdd-test-plan.md`
- Phase design must follow the phase closability principle from spec 4.4:
  each behavior phase is a vertical behavior slice that can be independently deployed and verified

#### 4.3 Unit Test Plan + Checklist

- Plan path: `docs/plan/{subject}/unit-test-plan.md`
- Checklist path: `docs/plan/{subject}/unit-test-plan-checklist.md`
- Use phase-number section headings that directly mirror the implementation checklist by default.
- Only emit `<!-- phase-mapping: -->` when repairing or extending a legacy plan that already uses that annotation.

#### 4.4 BDD Test Plan

- Path: `docs/plan/{subject}/bdd-test-plan.md`
- Only generated when Step 3 inferred BDD is needed
- Before allocating IDs, read `test/scenarios/README.md` and the target layer `README.md` / `INDEX.md`
- Contains detailed Given/When/Then scenarios grouped by Phase
- Each scenario uses a layer scenario ID such as `L4.070` or `L5.019`; if needed, map back to spec acceptance criteria inside `bdd-test-plan.md`, not in `BDD-Gate` items

#### 4.5 context.yaml

- Path: `docs/plan/{subject}/context.yaml`
- Generated whenever implementation plan is generated
- Template reference: `docs/plan/README.md` 6.1
- Generator reference: `.agent-skills/implement/shared/scripts/generate_context_yaml.py`
- `spec` must point to either the newly generated spec path or `source_spec`; if neither exists, stop and ask for clarification before writing the plan set
- Include `bddPlan` field only when bdd-test-plan.md is generated
- Fill `spec.discovery` with aliases and keywords from the Brief
- Fill `spec.targets.<target>.discovery.packages` from the component list

### Step 5: Update INDEX Files

Update the relevant INDEX files for each generated document type:

- `docs/spec/INDEX.md` — if a spec was generated
- `docs/plan/INDEX.md` — if a plan was generated

Follow the existing INDEX format and sorting conventions. Add new entries in the
appropriate status group.

### Step 6: Verify and Summarize

Run validation and present a summary:

1. **context.yaml validation** (when generated):
   ```bash
   python3 .agent-skills/implement/shared/scripts/validate_context.py \
     --context docs/plan/{subject}/context.yaml \
     --docs-root docs \
     --target {default-target}
   ```

2. **BDD reference integrity** (when BDD is active):
   - Every scenario ID in the checklist has a corresponding entry in `bdd-test-plan.md`
   - Every generated scenario ID follows the relevant layer `README.md` / `INDEX.md` numbering convention
   - Legacy `AC-*` coverage checks only apply when explicitly repairing an existing historical plan
   - Report any gaps as errors

3. **Output summary**:
   - Files generated (with paths)
   - Reused spec input (when Step 3 skipped new spec generation)
   - Output scope decision rationale
   - BDD strategy rationale
   - INDEX entries added
   - Any warnings or items needing attention

## Prohibited Actions

- Generating documents beyond what the Brief justifies (over-generation wastes effort and
  creates maintenance burden)
- Skipping spec generation when the Brief contains unrecorded trade-offs or architecture
  decisions (these need a persistent home)
- Inlining template content from README files (always reference the template source; inlined
  copies drift from the canonical template over time)
- Generating implementation plan/context artifacts without a concrete spec path (either a newly
  generated spec file or an explicit `source_spec` reuse path)
- Generating `bddPlan` in context.yaml without generating bdd-test-plan.md (or vice versa)
- Generating BDD-Gate checklist items with `AC-*` references for new documents
- Inventing BDD scenario IDs without first consulting the relevant `test/scenarios/<layer>/README.md` and `INDEX.md` when such conventions exist
- Creating or updating files under `docs/` without invoking `/create-doc`
- Proceeding past Step 2 without explicit user confirmation of the Brief
- Persisting the Brief as a file (it is a transient conversation artifact)
