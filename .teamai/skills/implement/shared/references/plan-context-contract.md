# Plan Context Contract

Shared plan-context contract owned by `/implement` and reused by sibling review skills.

## Shared Scripts

- `scripts/list_context_candidates.py`
- `scripts/validate_context.py`
- `scripts/generate_context_yaml.py`

## Validator Output Contract

`validate_context.py` returns normalized JSON with `files[]`.

When a concrete target is selected, the normalized payload may also include:

- `discovery`: top-level `spec.discovery` metadata
- `targetDiscovery`: target-level `spec.targets.<target>.discovery` metadata
- `baseBranch`: optional `metadata.baseBranch` string from `context.yaml`
- `branch`: optional `metadata.branch` string from `context.yaml`

Each `files[]` item contains:

- `role`
- `path`

Recognized roles:

| Role | Meaning | Typical Consumer |
|------|---------|------------------|
| `plan` | Main plan markdown | review + execution |
| `checklist` | Main execution checklist | `/tdd --file` |
| `spec` | Design/spec markdown | review + execution references |
| `test-plan` | Supporting test plan | `/tdd --references` |
| `test-checklist` | Test checklist mapped to impl phases | `/tdd --test-checklist` |
| `reference` | Additional markdown reference | review + execution references |
| `bdd-plan` | BDD scenario design document keyed by scenario IDs | `/tdd` BDD-Gate reference |

Role mapping rules:

- There must be exactly one `checklist`.
- `test-checklist`, when present, is passed to `/tdd --test-checklist`.
- `bdd-plan`, when present, is passed as a reference to `/tdd` for BDD-Gate item verification; `/tdd` treats the `bdd-test-plan.md` reference as the BDD scenario source keyed by layer scenario IDs. Legacy `AC-*` mappings remain compatibility input for historical plans only.
- All other markdown files remain read-only references.
- Consumers must keep file order stable and deduplicate by absolute path.

## Discovery Metadata

`context.yaml` may also include discovery metadata for issue-intake routing:

- `spec.discovery`
- `spec.targets.<target>.discovery`

Execution-focused consumers such as `/implement`, `/plan-review`, and
`/plan-code-review` must treat these fields as read-only metadata and must not
change their execution semantics based on them.

The shared validator applies backward-compatible type checks when these fields
are present, but their absence must not break legacy manifests.

## Branch Metadata

`context.yaml` may declare optional branch lifecycle hints under `metadata`:

| Field | Type | Required | Meaning |
|------|------|----------|---------|
| `metadata.baseBranch` | string | No | Base branch and merge target used by `/implement` Step 4.5 |
| `metadata.branch` | string | No | Feature branch name stem used by `/implement` Step 4.5 before the date/collision suffix is appended |

Rules:

- Both fields are optional and must be strings when present.
- These fields are not markdown references and are not subject to `.md` suffix checks or `docs/` boundary checks.
- `validate_context.py` must preserve these fields in normalized JSON output when present.
- `generate_context_yaml.py` must preserve these fields during reconciliation.
- `/implement` consumes them as execution metadata, not as document references.

`metadata.baseBranch` priority is:

1. `context.yaml` `metadata.baseBranch`
2. `AGENTS.md` project-level Git branch strategy
3. Git default branch auto-detection

`metadata.branch` only overrides the human-authored branch stem. `/implement` still owns
the generated suffixes such as `-{MMDD}` and collision suffixes like `-{MMDD}-2`.

## Shared Error Templates

### Missing `context.yaml`

```text
ERROR: docs/plan/{name}/context.yaml not found.
Create a context.yaml manifest to use plan-context skills. See docs/plan/README.md for template.
```

### Unknown target

```text
ERROR: Target '{target}' not found.
Available targets: {list of target keys}
```

### Declared file missing

```text
ERROR: Referenced file does not exist:
  - {path1}
  - {path2}
Fix the paths in context.yaml and retry.
```

### Path escapes `docs/`

```text
ERROR: Path escapes docs/ boundary:
  - {path} resolves outside docs/
Fix the relative paths in context.yaml.
```
