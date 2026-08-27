---
name: new-scenario
description: Create new Ferry scenario test cases from spec/plan documents. Generates complete scenario directory structure (README, scripts, data files) for L1-L5 layers and appends unified INDEX entries. Use when creating new integration test scenarios, adding test coverage for a feature, or scaffolding L1-L5 scenario directories. Triggers on /new-scenario.
---

# New Scenario Skill

Creates Ferry scenario test cases by reading a reference document and generating the complete directory structure with unified INDEX entries.

## Prerequisites

- Test scenarios directory exists: `test/scenarios/l{N}/`
- Unified INDEX.md exists at `test/scenarios/l{N}/INDEX.md`
- Reference document (`--ref`) is readable

## Usage

```
/new-scenario -l L1 --ref docs/spec/my-spec.md
/new-scenario -l L2 --ref docs/plan/my-plan/implementation.md
/new-scenario -l L5 --ref docs/spec/e2e-design.md
/new-scenario -h          # Show help
/new-scenario -h -v       # Show help + full workflow
```

| Flag | Required | Description |
|------|----------|-------------|
| `-l L{N}` | Yes | Target layer: L1-L5 |
| `--ref <path>` | Yes | Reference document path (spec or plan) |

## Workflow

### Step 1: Parse & Validate

- Validate `-l` is one of: `L1`, `L2`, `L3`, `L4`, `L5`
- Validate `--ref` path exists and is readable
- If either check fails, output error and stop

### Step 2: Collect Context

Read the following:

1. `test/scenarios/l{N}/INDEX.md` — compute `next_seq = max(existing scene IDs) + 1`
2. `--ref` document — full content
3. `.agent-skills/new-scenario/references/l{N}-data-templates.md` — layer-specific data templates

Layer defaults:

| Layer | Execution Mode |
|-------|---------------|
| L1-L4 | `automated` |
| L5 | `manual` |

### Step 3: Identify Candidate Scenarios

From the `--ref` document, extract independently testable behavior units (API endpoints, CLI commands, UI workflows, E2E flows). Present a numbered list:

```
Candidate scenarios from <ref-doc>:
  1. <scenario title> — <one-line description>
  2. <scenario title> — <one-line description>
  ...

Select: (single: 1, multi: 1,3, all: all, cancel: cancel)
```

On `cancel`: stop immediately, create no files.

### Step 4: Infer Parameters

For each selected scenario, infer:

| Parameter | Rule |
|-----------|------|
| `seq` | From `next_seq`, increment for each selected |
| `slug` | Title → lowercase, spaces → `-`, strip special chars |
| `category` | From ref doc section heading or keyword match; fallback: `General` |
| `business_id` | Match existing ID pattern in layer (e.g., `AP-001`); fallback: `-` |
| `execution_mode` | Fixed by layer (see Step 2) |
| `status` | Always `Pending` for new scenarios |
| `data files` | Per layer mapping (see Data File Mapping below) |

**Data File Mapping** (per spec §5.3):

| Layer | Reference File | Generated File(s) |
|-------|---------------|-------------------|
| L1 | `references/l1-data-templates.md` | `data/deployplan.yaml` |
| L2 | `references/l2-data-templates.md` | `data/create-plan.json` |
| L3 | `references/l3-data-templates.md` | `data/approval-policy.yaml` |
| L4 | `references/l4-data-templates.md` | `data/plan.yaml` + `data/plan-status.json` |
| L5 | `references/l5-data-templates.md` | `data/approval-policy.yaml` + `data/cluster-meta.yaml` + `data/applicationset.yaml` |

### Step 5: Parallel Scenario Generation

#### Parallelism Threshold

- **1–2 scenarios selected** → generate directly in the lead agent (no subagent overhead). Follow sub-steps 5.1, 5.2, then create files inline sequentially, then skip to 5.4.
- **3+ scenarios selected** → dispatch parallel subagents via sub-steps 5.1–5.5. Subagent startup cost (~3 tool calls overhead) is only justified when amortized across 3+ scenarios.

#### 5.1 Read Reference Scenario (Lead, Sequential)

Pick the highest-seq existing scenario in the same layer with status `Ready` or `Verified`. Read its full file set (`README.md`, `scripts/*.sh`, `data/*`). Store as `REFERENCE_CONTENT` — a text block with each file's relative path and full content.

Purpose: every subagent needs a style reference. Reading it once avoids N redundant reads.

#### 5.2 Pre-create Directories (Lead, Single Command)

Issue one `mkdir -p` call creating all scenario directories:

```bash
mkdir -p test/scenarios/l{N}/{seq1:03d}-{slug1}/{scripts,data} \
         test/scenarios/l{N}/{seq2:03d}-{slug2}/{scripts,data} \
         ...
```

Eliminates race conditions; an empty directory after dispatch signals subagent failure.

#### 5.3 Dispatch Parallel Subagents

Issue **N `Task` tool calls in a single message** (one per scenario):

```
Task:
  subagent_type: general-purpose
  mode: bypassPermissions
  description: "Create L{N}.{seq} scenario"
  prompt: <SUBAGENT_PROMPT>  # see Subagent Prompt Template below
```

Do NOT use Agent Teams (TeamCreate/SendMessage). Scenario scaffolding is deterministic file generation with no interaction needed.

#### 5.4 Collect Results & Update INDEX.md (Lead, Sequential)

After all subagents complete:

1. For each scenario, verify files were created (glob `{dir}/README.md`)
2. If a subagent failed, log warning and skip its INDEX entry
3. Append all successful scenario rows to `test/scenarios/l{N}/INDEX.md`:

```markdown
| L{N}.{seq} | {business_id} | {category} | [{seq:03d}-{slug}](./{seq:03d}-{slug}/) | {title} | {execution_mode} | Pending |
```

4. Update statistics section
5. **Idempotency check**: verify no duplicate `L{N}.{seq}` rows before appending

#### 5.5 Output Summary

```
已创建 L{N}.{seq}: {Title}
路径: test/scenarios/l{N}/{seq:03d}-{slug}/
执行方式: {execution_mode}
状态: Pending
```

If multiple scenarios were created, list all. If any subagent failed, report which scenario failed and why.

### Subagent Prompt Template

Used in Step 5.3. Substitute all `{...}` placeholders before dispatch.

```
You are generating scenario test files for L{N}.{seq}: {title}.

## Task
Create the following files in `{dir_path}/`:
- README.md
- scripts/setup.sh, scripts/cleanup.sh [+ trigger.sh, verify.sh for L5]
- data/{data_files}

Then run: chmod +x {dir_path}/scripts/*.sh

## Scenario Parameters
- Layer: L{N}
- Seq: {seq} ({seq:03d})
- Slug: {slug}
- Title: {title}
- Description: {description}
- Category: {category}
- Execution Mode: {execution_mode}
- Scenario ID: l{N}-{seq:03d}

## Directory Structure

L1-L4:
{dir_path}/
├── README.md
├── scripts/
│   ├── setup.sh
│   └── cleanup.sh
└── data/
    └── {layer-specific files}

L5:
{dir_path}/
├── README.md
├── scripts/
│   ├── setup.sh
│   ├── trigger.sh
│   ├── verify.sh
│   └── cleanup.sh
└── data/
    └── {layer-specific files}

## Style Reference (match this scenario's patterns exactly)
{REFERENCE_CONTENT}

## Data Templates (substitute placeholders with scenario params)
{DATA_TEMPLATE_CONTENT}

## README Requirements
Must contain sections: Overview, Prerequisites, Test Data, Steps (with Setup/Cleanup; L5 adds Trigger/Verify), Result Recording, Troubleshooting.

## Script Requirements
- `set -euo pipefail`
- Source `../../_shared/scripts/common.sh` (L1-L4) or `../_shared/scripts/common.sh` (L5; check actual path)
- Use log functions: log_step, log_info, log_success, log_warn, log_error
- cleanup.sh must be idempotent
```

### Error Handling

- If a subagent fails, the lead reports which scenario failed and continues with INDEX.md for successful ones
- Empty directories from failed subagents are NOT cleaned up (user can inspect)

## Help Flag Handling

- `-h` / `--help`: show name, description, Usage section, then stop
- `-h -v` / `--help --verbose`: show above + full Workflow, then stop

## References

Load these files only when needed for the target layer:

- `references/l1-data-templates.md` — L1 data file templates
- `references/l2-data-templates.md` — L2 data file templates
- `references/l3-data-templates.md` — L3 data file templates
- `references/l4-data-templates.md` — L4 data file templates
- `references/l5-data-templates.md` — L5 data file templates
