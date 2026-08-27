---
name: redeploy
description: Rebuild and redeploy the full Ferry system to a local Kind test cluster. Always rebuilds controller, api-server, and web-ui together, updates the chart global image.tag, and performs a single Helm upgrade. Before running deployment commands, read the scenario environment README to select the correct `HELM_ENV` and values file. Triggers on /redeploy.
---

# Ferry Redeploy Skill

Rebuilds and redeploys the full Ferry system to the local Kind test cluster using project Makefile targets and Helm.

## Trigger Command

```
/redeploy                # Redeploy full ferry-system
/redeploy all            # Same as default
```

## Prerequisites

- A Kind cluster is running (check with `kind get clusters`)
- Docker is available
- Helm is installed
- The `KIND_CLUSTER` environment variable or default matches the target cluster
- Read `test/scenarios/README.md` and the target environment README before deploying:
  - `test/scenarios/l4/README.md`
  - `test/scenarios/l5/README.md`

## Reference Documents

- Framework truth source: `test/scenarios/README.md`
- Layer truth source: `test/scenarios/l4/README.md` or `test/scenarios/l5/README.md`

Use these documents for environment-specific topology, live verification surfaces, values-file selection, and caveats about schemas or entrypoints. Keep this skill focused on deployment workflow and contract hygiene.

## Workflow

### Step 1: Read the Target Environment README

Identify the target cluster, then read the matching scenario README before running `make`:

```bash
kind get clusters
```

Use the environment README as the source of truth for:

1. which `KIND_CLUSTER` to target
2. which `HELM_ENV` to pass
3. which Helm values file will be edited and applied
4. whether the environment has extra constraints such as GitLab- or Gitea-specific bootstrap state

Do not infer the Helm values selection from `DEPLOY_ENV` alone. `DEPLOY_ENV=local` controls local build/load/tag behavior, while `HELM_ENV` is resolved from the target environment README.

### Step 2: Run Contract Preflight When Needed

If the pending change touches checked-in contracts such as schemas, generated APIs, CLI/UI request shapes, or other consumer-facing structures:

1. Complete the required repo-tracked code generation or artifact refresh first.
2. Confirm any local consumer artifacts used for verification are rebuilt and current.
3. Use the framework README and layer README to identify which live surfaces must be checked after deployment.

### Step 3: Build, Load, and Deploy

```bash
make deploy-components DEPLOY_ENV=local HELM_ENV={from-environment-readme} KIND_CLUSTER={cluster}
```

This command handles the full pipeline:
1. Rebuild `controller`, `api-server`, and `web-ui`
2. Load all three images into the Kind cluster when `LOAD_TO_KIND=true`
3. Update the chart global `image.tag` via `yq`
4. Clear component-local tag overrides (`controller.image.tag`, `apiServer.image.tag`, `webUI.image.tag`)
5. `helm upgrade --install` once for the full Ferry release
6. Wait for `ferry-controller-manager`, `ferry-api-server`, and `ferry-web-ui` rollouts

The `DEPLOY_TAG` is auto-generated as `local-{YYYYMMDDHHmmSS}` when `DEPLOY_ENV=local`, and becomes the shared global `image.tag` for the whole Ferry system.

### Step 4: Verify Health

```bash
kubectl -n ferry-system get deploy ferry-controller-manager ferry-api-server ferry-web-ui \
  -o jsonpath='{range .items[*]}{.metadata.name}{"="}{.spec.template.spec.containers[0].image}{" ready="}{.status.readyReplicas}{"/"}{.status.replicas}{"\n"}{end}'
```

Check that all three Deployments are on the same tag and `ready=1/1`.

If Step 2 applied, also verify the live contract surfaces defined by the framework README and layer README are aligned with the deployed revision.

### Step 5: Report Result

Report the deployment result:
- Shared image tag used
- The three Deployment image references
- Rollout status
- Whether contract-sensitive consumer surfaces were rechecked
- Any errors encountered

## Makefile Target Reference

| Target | Purpose |
|--------|---------|
| `deploy-components` | Rebuild/load all Ferry system components, update global `image.tag`, single Helm upgrade |
| `deploy-component` | Compatibility wrapper that redirects to `deploy-components` |
| `apply-component` | Compatibility wrapper that redirects to `deploy-components` |
| `deploy-env` | Helm upgrade --install the full environment |
| `docker-build-and-load` | Only build image and load to Kind |
| `helm-template` | Render the current chart/values combination before deployment |

## Optional Overrides

| Variable | Default | When to Override |
|----------|---------|-----------------|
| `KIND_CLUSTER` | `ferry-test-e2e` | Kind cluster name differs |
| `DEPLOY_TAG` | `{DEPLOY_ENV}-{timestamp}` | Pin a specific image tag |
| `HELM_ENV` | `$(DEPLOY_ENV)` | Override according to the target environment README; do not assume the default is correct |
