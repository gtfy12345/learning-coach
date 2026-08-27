---
name: work-journal
description: Record work journal entries with proper formatting and index updates. Use when completing code changes that need to be committed, or when explicitly asked to record work progress. Triggers on /work-journal or when user says "record work journal", "commit with journal", etc.
---

# Work Journal Skill

Records work progress following project conventions. Code changes and journal entries are committed together.

## Usage

- `/work-journal` - Interactive manual mode
- `/work-journal --auto --plan <name> --phase <heading>` - Non-interactive auto mode for phase-boundary commits

## Argument Contract

- `--auto`: enable non-interactive auto mode
- `--plan <name>`: plan name used to derive journal content and commit metadata
- `--phase <heading>`: completed phase heading used to derive journal content and commit subject

Rules:

- `--auto` must be used together with `--plan` and `--phase`
- `--plan` and `--phase` are reserved for auto mode and must not change manual mode behavior

## Prerequisites

Before using this skill, ensure `docs/work-journal/` directory exists with README.md and INDEX.md.
If not, run `/init-docs` first to initialize the documentation structure.

## Workflow

### Step 0: Analyze changes for logical boundaries

When `--auto` is present, skip Step 0 entirely and continue at Step 1.

Before proceeding, analyze the uncommitted changes to determine if they should be split:

1. Run `git diff --stat HEAD` to see all changed files
2. Group files by logical area (module/component):
   - `internal/controller/` - Controller logic
   - `internal/apiserver/` - API Server
   - `cmd/cli/` - CLI tool
   - `test/scenarios/` - Test framework
   - `web-ui/` - Frontend
   - `config/` - Configuration (associate with the component it configures)
   - `docs/` - Documentation

3. **If changes span 2+ distinct areas with different scopes**, ask user:
   > "Changes span multiple areas: [list areas]. Split into separate commits?"
   > - "Split into N commits (recommended)" - Each area gets its own commit + journal entry
   > - "Single commit" - Combine all changes

4. If splitting, identify the file groupings for each commit before proceeding

### Step 1: Read the specification

Read `docs/work-journal/README.md` to understand:
- Index update requirements (each commit gets its own line in INDEX.md)
- Journal template format
- Checklist items

### Step 2: Create/append journal file

- Filename: `docs/work-journal/YYYY-MM-DD.md` (today's date)
- If file exists, append new record at the end
- If file doesn't exist, create it

### Step 3: Write journal content

Use the simple template for daily work:

```markdown
## HH:MM 工作记录

### 完成事项

- 具体完成的工作描述

### 关联 Commit

- `type(scope): commit subject`

### 备注

其他需要记录的内容（可选）。
```

Auto mode content rules:

- `## HH:MM 工作记录` title remains unchanged
- `### 完成事项`: derive from the phase heading and the checked items completed in that phase
- `### 关联 Commit`: use the commit message derived for the auto-commit
- `### 备注`: `Auto-committed by /tdd phase-commit, plan: {name}`

Auto mode commit message derivation rules:

- `type`: infer from the phase content; default to `feat`
- `scope`: derive from the plan name core term
- `subject`: remove the `Phase N:` prefix from the phase heading and lowercase the remainder
- The full commit message must also include a body summarizing checklist, phase, and completed items.

### Step 4: Update INDEX.md

Add entry to `docs/work-journal/INDEX.md`. **Each commit gets its own line**:

```markdown
| [YYYY-MM-DD](YYYY-MM-DD.md) | `type(scope): commit subject` | #tag |
```

### Step 4.5: Check staged document Header/INDEX drift

Before committing, check if any staged files are documents under `docs/spec/` or `docs/plan/`:

1. Run `git diff --cached --name-only` to get the list of staged files.
2. For each staged `.md` file under `docs/spec/` or `docs/plan/` (excluding README.md, INDEX.md):
   - Read its Header `状态`, `版本`, `更新日期`.
   - Compare against the corresponding INDEX entry.
3. If drift is detected, present to user:
   > "Header/INDEX drift detected in [file]: Header says [value], INDEX says [value]."
   > - "Fix now before commit (Recommended)" — run `--fix-index` logic for the affected entry
   > - "Skip and record in journal" — proceed with commit, note the drift in journal Notes section
4. If no drift, proceed silently.

In auto mode, Step 4.5 must attempt automatic drift repair before asking for help.
If drift cannot be repaired automatically, stop the auto-commit and report the remaining drift.

### Step 5: Commit together

Commit code changes + journal file + index update together:

```
type(scope): subject

- Detail 1
- Detail 2
```

### Step 6: Verify commit result

**After every `git add` and `git commit` (including amend), the following checks must be performed:**

1. `git status` — Confirm that the staging area and working tree status match expectations (no missing files, no accidentally added files)
2. `git log --oneline -3` — Confirm the latest commit message is correct and previous commits have not been overwritten

If any anomalies are found (e.g., missing files, incorrect commit message), immediately notify the user and discuss a fix.

## Multi-Commit Workflow

When splitting changes into multiple commits, execute this workflow for **each logical group**:

```
For commit N of M:
1. Stage ONLY files belonging to this group (git add <specific files>)
2. Create/append journal entry for this group's changes
3. Update INDEX.md with this commit's entry (add new line at top of current month)
4. Commit with appropriate type(scope) for this group
5. Proceed to next group
```

**Important:**
- Each commit gets its own journal entry (same day file, different timestamps)
- Each commit gets its own INDEX.md line
- Stage files precisely - avoid `git add .` when splitting

## Commit Types

| Type | Description |
|------|-------------|
| `feat` | New feature |
| `fix` | Bug fix |
| `refactor` | Refactoring |
| `docs` | Documentation |
| `test` | Tests |
| `chore` | Build/tools |

## Tags

| Tag | Description |
|-----|-------------|
| `#feat` | Feature work |
| `#fix` | Bug fixes |
| `#refactor` | Refactoring |
| `#docs` | Documentation |
| `#test` | Test related |
| `#ui` | UI related |
| `#i18n` | Internationalization |
| `#pdf` | PDF export |

## Checklist

Before completing:
- [ ] Analyzed changes for logical boundaries (Step 0)
- [ ] If multi-area changes: asked user about splitting
- [ ] Journal filename is correct (`YYYY-MM-DD.md`)
- [ ] Contains completed items and related commit
- [ ] INDEX.md updated (each commit on its own line)
- [ ] Appropriate tags selected
- [ ] Staged docs Header/INDEX drift check passed (or skipped with reason)
- [ ] Code and journal committed together
- [ ] `git status` + `git log` verified after each commit (Step 6)
- [ ] If split: all commits completed with their journal entries
