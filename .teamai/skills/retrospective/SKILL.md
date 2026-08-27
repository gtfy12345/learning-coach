---
name: retrospective
description: "IMPORTANT: Invoke this skill automatically after a feature or bugfix is completed and verification passes. Do NOT close out a successful delivery session without evaluating whether a post-pass retrospective report is needed. Create evidence-based delivery retrospectives in docs/reports, audit orphan follow-up risk when new follow-up docs were created in the session, and summarize concrete follow-up suggestions without directly mutating other skills or governance docs. Triggers on /retrospective or when a functionality/bugfix session is completed and verified."
---

# Retrospective Skill

Create an evidence-based post-pass retrospective after a successful feature or bug-fix delivery.

## Usage

- `/retrospective` - Gather context from the current session and ask for missing scope only if needed
- `/retrospective --this` - Use the current session as the retrospective scope and write the report by default

## Prerequisites

- `docs/reports/README.md` exists and defines the current report conventions
- `docs/reports/INDEX.md` exists for report indexing

If either file is missing, run `/init-docs` first.

## Workflow

### Step 1: Read the report specification

Read `docs/reports/README.md` before creating or updating any report under `docs/reports/`.

### Step 2: Determine retrospective scope

For `/retrospective --this`, derive the scope from the current session:

1. Delivery subject:
   - Prefer plan name if the session was driven by `/implement`
   - Otherwise prefer the feature or bug-fix theme established in the session
   - If neither is stable, derive a short slug from the session topic
2. Success gate:
   - Only proceed if the delivery has passing verification evidence
   - If verification is incomplete or contradictory, stop and report that the session is not yet eligible for retrospective close-out
   - If the session created a new follow-up plan/checklist but it never entered owner execution, remains `draft`, or has no verification-backed progress, stop and report an orphan follow-up risk instead of producing a normal close-out retrospective

For `/retrospective` without `--this`, use the current context first; only ask the user for missing scope if the subject or pass evidence cannot be determined from available materials.

### Step 3: Collect evidence

Collect only evidence-backed inputs:

- Verification evidence:
  - tests, builds, BDD runs, deploy checks, logs, reports, or validated artifacts
- Session friction:
  - semantic confusion, rework loops, environment blockers, stale consumer artifacts, documentation gaps, or workflow ambiguity that actually occurred during delivery
- Related governance assets:
  - `AGENTS.md`
  - relevant `SKILL.md`
  - relevant README documents
  - relevant spec/plan/checklist documents when the root cause is design or contract ambiguity
  - existing BUG records when they are directly related
  - any follow-up plan/checklist created in the same session, including its lifecycle state and downstream owner evidence

Rules:

- Do not invent pain points that are not supported by session evidence.
- Do not turn a one-off execution mistake into a process defect unless the same class of issue materially contributed to delay, confusion, or incorrect implementation.

### Step 4: Analyze and classify

For each major pain point, classify:

1. What happened
2. Evidence
3. Why it happened
4. Whether the root cause belongs to:
   - `skill`
   - `README`
   - `AGENTS.md`
   - `spec/plan`
   - `no repo change needed`

Additional rules:

- Recommendations must be concrete enough to tell a future implementer what asset should change.
- `/retrospective` does not directly edit the target skill, README, `AGENTS.md`, or spec/plan. It proposes follow-up changes only.
- `/retrospective` does not replace `/bug-report`. When the session is a bug fix, reference an existing BUG record if available, but do not create one automatically unless another workflow already requires it.
- Orphan follow-up is a close-out blocker, not a retrospective recommendation.

### Step 5: Write the report

Create a report in `docs/reports/` using the `assessment` type:

- Filename: `YYYY-MM-DD-${subject}-assessment.md`
- Date: today
- Reviewer: current agent or user

Required structure:

1. `## 1 复盘范围与成功证据`
2. `## 2 会话中的主要阻点/痛点`
3. `## 3 根因归类`
4. `## 4 对流程资产的改进建议`
5. `## 5 建议优先级与后续动作`

Minimum content expectations:

- Section 1 names the delivery scope and cites concrete pass evidence
- Section 2 lists only material pain points from the session
- Section 3 separates root causes from symptoms
- Section 4 maps every recommendation to a target asset type
- Section 5 prioritizes what should happen next

After writing the report, update `docs/reports/INDEX.md`.

### Step 6: Summarize to the user

Provide a short close-out summary containing:

- the main pain points
- the suggested target assets to improve
- which follow-up recommendations are highest value for the next implementation round

## Prohibited Actions

- Creating a retrospective before pass evidence exists
- Treating a session with orphan follow-up docs as eligible for normal successful close-out
- Writing generic advice with no session evidence
- Automatically modifying skills, README files, `AGENTS.md`, or spec/plan as part of the retrospective itself
- Treating `/retrospective` as a replacement for `/bug-report`

## Checklist

- [ ] Read `docs/reports/README.md`
- [ ] Confirm the delivery actually passed verification
- [ ] Derive a stable subject for the report filename
- [ ] Collect evidence from session outputs and relevant governance assets
- [ ] Distinguish process defects from one-off execution mistakes
- [ ] Map each recommendation to `skill` / `README` / `AGENTS.md` / `spec-plan` / `no repo change needed`
- [ ] Create `docs/reports/YYYY-MM-DD-${subject}-assessment.md`
- [ ] Update `docs/reports/INDEX.md`
- [ ] Summarize the highest-signal follow-up recommendations to the user
