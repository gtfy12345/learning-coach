---
name: test-env
description: "IMPORTANT: Invoke this skill automatically when user asks to create, verify, or cleanup a test environment. Do NOT run test environment commands without invoking this skill first. Manage Ferry scenario test environments (L4/L5). Automate prerequisite checks, environment creation, verification, and cleanup. Triggers on /test-env or when user asks to create, verify, cleanup, or check status of a test environment."
---

# Test Environment Skill

Manage Ferry scenario test environments (L4 Gitea / L5 GitLab) with automated prerequisite checks, setup, verification, and cleanup. L1-L3 scenarios run on the L4 environment.

## Usage

```
/test-env setup L4              # Create L4 environment (with prerequisite checks)
/test-env verify L4             # Verify L4 component health only
/test-env cleanup L4            # Clean up L4 environment
/test-env cleanup L4 --stop-lb  # Clean up L4 and stop cloud-provider-kind
/test-env status                # Show all clusters and component health
/test-env -h                    # Show this help
```

## Reference Documents

- Framework source of truth: `test/scenarios/README.md`
- Layer source of truth: `test/scenarios/l4/README.md` or `test/scenarios/l5/README.md`

Use these documents for environment topology, layer-specific bootstrap details, contamination sources, cleanup commands, and live verification surfaces. Keep this skill focused on workflow and escalation order.

## Layer Components

| Component | L4 (Gitea) | L5 (GitLab) |
|-----------|:--:|:--:|
| kind-cluster | * | * |
| cert-manager | * | * |
| gitea | * | |
| gitlab-onboarding | | * |
| clustermeta | * | * |
| mailpit | * | * |
| ferry-controller | * | * |
| api-server | * | * |
| ferryctl | * | * |
| web-ui | * | * |
| gitlab-runner | | * |
| argocd | | * |

Cluster name convention: `ferry-l4` (Gitea) or `ferry-l5` (GitLab)

## Workflow Rules

- Read the framework README and the selected layer README before running setup, verify, cleanup, or status commands.
- Treat scenario or app-level isolation separately from environment control-plane isolation. Shared control-plane services can leak state across runs; use the layer README to identify the concrete shared components.
- Apply the recovery ladder in this order:
  1. Targeted cleanup of dirty resources
  2. Targeted cleanup or redeploy of dirty components
  3. Full environment rebuild
- Do not jump straight to full environment rebuild unless the first two levels are exhausted or the README explicitly says the environment is unrecoverable.

## Workflow: setup

### Step 1: Parse layer argument

Accept `L4`, `l4`, or `4`. Normalize to lowercase `l{N}`. Validate N is 4 or 5. For L1-L3, inform user to use L4 instead.

### Step 2: Read Framework and Layer README

Read `test/scenarios/README.md` and `test/scenarios/l{N}/README.md` before proceeding.

### Step 3: Check image cache

```bash
./test/scenarios/_shared/scripts/image-cache.sh status
```

If images are missing, ask user:
- **"Pull missing images first (recommended)"** -- run `./test/scenarios/_shared/scripts/image-cache.sh pull`
- **"Skip and continue"** -- proceed without caching

### Step 4: Check cloud-provider-kind

```bash
./test/scenarios/_shared/scripts/cloud-provider-kind.sh status
```

If not running:
- Try `./test/scenarios/_shared/scripts/cloud-provider-kind.sh start`
- If it fails (needs sudo), warn user:
  > cloud-provider-kind requires sudo. Please run in another terminal:
  > `./test/scenarios/_shared/scripts/cloud-provider-kind.sh start`
  > Then confirm to continue.
- Wait for user confirmation before proceeding.

### Step 5: Run env-setup.sh

```bash
./test/scenarios/l{N}/env-setup.sh
```

Use 10-minute timeout. The script is re-entrant -- interrupted runs resume automatically.

### Step 6: Handle result

**On success**: Report environment info (cluster name, key endpoints, access commands).

**On failure**:
1. Check which component failed from the output
2. Check pod status: `kubectl get pods -A --context kind-ferry-l{N}`
3. Check events: `kubectl get events -A --sort-by='.lastTimestamp' --context kind-ferry-l{N} | tail -20`
4. Present findings and offer:
   - **Targeted cleanup first** -- consult the framework/layer README and remove dirty resources before retrying
   - **Targeted redeploy** -- redeploy only the failed component or dependency if the README supports it
   - **Retry** -- run env-setup.sh again (re-entrant) once the narrower fixes are done
   - **Full rebuild** -- use only after the narrower recovery levels are exhausted
   - **Abort** -- let user fix manually

## Workflow: verify

### Step 1: Parse layer argument

Same as setup Step 1.

### Step 2: Read Framework and Layer README

Read `test/scenarios/README.md` and `test/scenarios/l{N}/README.md` before proceeding.

### Step 3: Verify cluster exists

```bash
kind get clusters | grep "^ferry-l{N}$"
```

If cluster does not exist, report error and suggest `/test-env setup L{N}`.

### Step 4: Run component verify commands

Export required environment variables:

```bash
export CLUSTER_NAME=ferry-l{N}
export FERRY_NAMESPACE=ferry-system
export GITEA_NAMESPACE=gitea
export MAILPIT_NAMESPACE=mailpit
export POSTGRESQL_NAMESPACE=postgresql
export CLUSTERMETA_NAMESPACE=platform-clusters
export REGISTRY_PORT=5050
export PROJECT_ROOT=<project-root>
```

Then for each component in the layer (see Layer Components table):

```bash
./test/scenarios/_shared/scripts/components/{component}.sh verify
```

### Step 5: Report health summary

Present a table of component status. If any failed, prefer targeted cleanup or targeted redeploy before suggesting a full rebuild.

## Workflow: cleanup

### Step 1: Parse layer argument and flags

Same layer parsing. Check for `--stop-lb` flag.

### Step 2: Read Framework and Layer README

Read `test/scenarios/README.md` and `test/scenarios/l{N}/README.md` before proceeding.

### Step 3: Run env-cleanup.sh

```bash
./test/scenarios/l{N}/env-cleanup.sh
```

### Step 4: Optionally stop cloud-provider-kind

If `--stop-lb` flag is provided:

```bash
./test/scenarios/_shared/scripts/cloud-provider-kind.sh stop
```

Note: Stopping may require sudo. If it fails, provide the manual command.

### Step 5: Report result

Confirm cluster deleted and whether cloud-provider-kind was stopped.
If cleanup is partial, follow the recovery ladder and use the framework/layer README as the source of truth for targeted cleanup commands.

## Workflow: status

### Step 1: Check Kind clusters

```bash
kind get clusters 2>/dev/null
```

List all `ferry-l*` clusters.

### Step 2: Read Framework README

Read `test/scenarios/README.md` before interpreting status output.

### Step 3: Check cloud-provider-kind and image cache

```bash
./test/scenarios/_shared/scripts/cloud-provider-kind.sh status
./test/scenarios/_shared/scripts/image-cache.sh status
```

### Step 4: Check component health for running clusters

For each detected `ferry-l{N}` cluster:

```bash
kubectl get pods -n ferry-system --context kind-ferry-l{N}
kubectl get pods -n gitea --context kind-ferry-l{N}
kubectl get svc -n ferry-system --context kind-ferry-l{N}
```

### Step 5: Present summary

```
=== Ferry Test Environment Status ===

Kind Clusters:
  ferry-l4  Running (context: kind-ferry-l4)

Cloud Provider KIND: Running (PID: 12345)
Image Cache: 12/12 cached

Cluster ferry-l4:
  ferry-system:  controller OK, api-server OK, web-ui OK, postgres OK
  gitea:         OK
  mailpit:       OK
```

## Key Script Paths

| Script | Path |
|--------|------|
| env-setup | `test/scenarios/l{N}/env-setup.sh` |
| env-cleanup | `test/scenarios/l{N}/env-cleanup.sh` |
| image-cache | `test/scenarios/_shared/scripts/image-cache.sh` |
| cloud-provider-kind | `test/scenarios/_shared/scripts/cloud-provider-kind.sh` |
| components | `test/scenarios/_shared/scripts/components/{name}.sh` |
| framework README | `test/scenarios/README.md` |
