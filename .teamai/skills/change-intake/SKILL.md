---
name: change-intake
description: "IMPORTANT: Use this skill when the user reports a bug, regression, broken behavior, screenshot-based issue, or asks to revise an existing feature without naming the exact plan. This is the default entry point for issue-driven work: it locates the most relevant plan/spec/bug context, decides whether the problem is implementation drift or a design/feature change, routes follow-up work to the right skill, prevents direct edits against completed plans, and must not leave newly created follow-up docs orphaned."
---

# Change Intake Skill

Route issue-driven requests before coding. `/change-intake` is the user-facing
entry point for:

- bug reports without a plan name
- screenshots or vague UI/API failures
- regressions against recently delivered work
- feature revisions that may require spec/plan updates first

This skill does **not** replace `/implement`, `/plan-review`, or
`/plan-code-review`. It decides which one should run next.

## Usage

- `/change-intake "login page blank after refresh"`
- `/change-intake "secret edit page still posts intentBlocks"`
- `/change-intake "need to revise selector behavior for authored blocks"`

## Required Inputs

The user can provide any combination of:

- free-form issue text
- screenshot / visible error text
- API name, route, CLI command, field name, or BUG ID

If a screenshot is present, extract any visible strings, labels, field names,
or request/response errors before ranking candidates.

## Shared Inputs To Read First

Before matching a plan, read:

1. `docs/work-journal/INDEX.md`
2. the latest work-journal entry relevant to the topic
3. `docs/bugs/PATTERNS.md` when the request is a bug or regression

Use the new matcher script for deterministic candidate ranking:

```bash
python3 .agent-skills/change-intake/scripts/match_change_context.py \
  --plan-root docs/plan \
  --query "<issue text>"
```

## Matching Workflow

### Step 1: Collect signals

Extract and normalize:

- user wording
- screenshot OCR / visible UI text
- API names
- routes
- commands
- field names
- BUG IDs

Build one combined query string and pass it to the matcher script.

### Step 2: Rank candidate plan targets

Interpret matcher output as:

- `high` confidence: top candidate is clear; load it directly
- `medium` confidence: top candidate is preferred, but compare the next result
- `low` confidence: present 2-3 candidates to the user before mutating anything
- `none`: fall back to manual repo search and explain the gap

Rules:

- Prefer the `recommended` candidate unless confidence is `low`
- If confidence is `low`, show the top candidates with reasons and ask the user
- If the matcher finds nothing, search by BUG ID / API / route / command manually

### Step 3: Decide plan lifecycle handling

After selecting a candidate:

1. Read the candidate `context.yaml`
2. Validate it with:

```bash
python3 .agent-skills/implement/shared/scripts/validate_context.py \
  --context docs/plan/<name>/context.yaml \
  --docs-root docs \
  --target <target>
```

3. Read the validated plan / checklist / spec / references
4. Inspect the selected plan Header `状态`

Routing rule:

- `active` / `draft`: the plan is still live; continue with the original plan context
- `completed`: **never** reopen the original checklist; create a follow-up or bugfix plan first
- `superseded` / `deprecated`: do not implement against it; locate the successor or ask the user

## Classification Workflow

### Step 4: Determine change type

Classify the request before coding:

- `implementation drift`
  - intended design is still correct
  - code, generated artifacts, tests, or deployment drifted from the plan/spec
- `design/feature change`
  - user expectation changes the design, contract, workflow, or target behavior
  - new user-visible behavior, schema, API, or compatibility rule is needed
- `uncertain`
  - the issue may be design drift, but the documents are ambiguous or stale

### Step 5: Route to the next skill

#### A. Active/Draft + implementation drift

- If the issue is already within a live plan and checklist scope, continue with `/implement`
- If the scope is already implemented but needs remediation, prefer `/plan-code-review --fix`
- If document drift is the blocker, use `/plan-review --fix` first

#### B. Completed plan

Before creating any new docs, branch into exactly one of these two paths:

1. `proposal-only`
   - user currently wants analysis, scoping, or naming guidance only
   - describe the proposed follow-up name, scope, related assets, and next owner skill
   - do **not** create follow-up docs yet
2. `created-and-owned`
   - user wants to continue the change now
   - create the follow-up docs and immediately hand them to the next owner skill in the same session

Rules:

- Never reopen the original completed checklist.
- Never create follow-up docs and then stop before owner handoff.
- If the user declines immediate continuation, stay in `proposal-only`.

Naming rules:

- generic change: `${original-subject}-follow-up-${short-topic}`
- bugfix with BUG record: `${original-subject}-bugfix-${bug-id}`

Required follow-up contents:

- follow-up `context.yaml` with discovery metadata
- references to the original plan, original spec, related BUG, and related report
- original completed plan gets a `## 后续修复 / Follow-ups` back-link block

For the `created-and-owned` path:

1. create the follow-up docs through `/create-doc`
2. if the docs need consistency cleanup, run `/plan-review --fix` on the new follow-up first
3. continue into the downstream owner skill, normally `/implement <follow-up>`

Do not end the session with a freshly created follow-up still acting as a passive note.

#### C. Design/Feature change

Do not code first.

1. Create or revise the spec first
2. Create the follow-up plan/checklist
3. Run `/plan-review --fix` if the new docs need consistency cleanup
4. Only then continue to implementation

#### D. Uncertain classification

Stop and show:

- the candidate plan
- the conflicting evidence
- whether the ambiguity is in spec, plan, or current code

If the ambiguity is document-owned, resolve it through spec/plan updates before
coding.

## Follow-up Document Contract

When `/change-intake` creates follow-up docs:

- spec and plan must be created before code changes
- new `context.yaml` must include discovery metadata
- the caller must already know which downstream owner skill will take over in the same session
- the new plan must reference:
  - original plan
  - original spec
  - related bug record when present
  - related assessment / retrospective when relevant

If the original completed plan lacks a `## 后续修复 / Follow-ups` section, add it
and append one entry per new follow-up.

If the session is still at proposal or scope-shaping stage, stop before this section and do not materialize the follow-up docs.

## Close-out Workflow

After the fix or revision is complete and verified:

1. run `plan-review` on the relevant plan if spec/plan changed
2. run `sync-doc-index` when Header / INDEX projections changed
3. evaluate `bug-report` when the session fixed a real bug
4. invoke `/retrospective --this` before final close-out

`/change-intake` is an entry skill, not a delivery owner. Once it has routed the
session into a concrete plan flow, the downstream delivery skill still owns its
normal testing and lifecycle duties. For completed-plan follow-ups, `/change-intake`
owns the gate that prevents orphan follow-up creation; once docs are created, it
must hand off to the next owner in the same session.
