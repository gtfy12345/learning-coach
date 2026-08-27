---
name: test-scenario
description: Execute scenario integration tests for Ferry. Supports single scenario, full layer, and rerun modes. Uses parallel sub-agent dispatch for 3+ scenarios. Triggers on /test-scenario.
---

# Ferry Scenario Test Skill

Executes scenario integration tests following the Ferry scenario test framework.

## Prerequisites

- Test environment is ready (`test/scenarios/l{N}/env-setup.sh` has been run)
- Read `test/scenarios/README.md` before first use to understand the framework

## Reference Documents

- Framework truth source: `test/scenarios/README.md`
- Layer truth source: `test/scenarios/l4/README.md` or `test/scenarios/l5/README.md`
- Scenario truth source: the scenario's own `README.md`

Use these documents for scenario semantics, prerequisites, troubleshooting, cleanup expectations, and layer-specific contamination sources. Keep this skill focused on execution protocol.

## Usage

```
/test-scenario -i L1.001               # Run a single scenario by ID
/test-scenario -l L1                   # Run all Ready scenarios in a layer
/test-scenario -l L1 --from L1.003    # Run layer, starting from a specific scenario
/test-scenario -r {run-id}             # Rerun failed scenarios from a previous run
```

| Flag | Description |
|------|-------------|
| `-i` | Scenario ID (e.g., `L1.001`) - run a single scenario |
| `-l` | Layer ID (e.g., `L1`) - run all Ready scenarios in the layer |
| `--from` | Used with `-l`, start from the specified scenario (skip earlier ones) |
| `-r` | Run ID - rerun failed scenarios from a previous run |
| `--batch-size` | Max parallel sub-agents per batch (default: 8) |

**Execution modes:**
- **Direct Mode** (1-2 scenarios): Execute sequentially in the lead agent — sub-agent overhead not justified
- **Parallel Mode** (3+ scenarios): Dispatch via Task tool sub-agents in batches (default 8, configurable via `--batch-size`)

## Workflow

### Step 1: Parse Arguments and Determine Scenarios

**Single scenario** (`/test-scenario -i L1.001`):
- Parse scenario ID: layer=`l1`, seq=`001`
- Locate directory: `test/scenarios/l1/001-*/`

**Layer mode** (`/test-scenario -l L1`):
- Read `test/scenarios/l1/INDEX.md`
- Collect all scenarios with status `Ready` or `Verified`
- If `--from` specified, skip scenarios before the given ID (e.g., `-l L1 --from L1.003`)

**Rerun mode** (`/test-scenario -r {run-id}`):
- Read `{TEST_OUTPUT_DIR}/runs/{run-id}/summary.json`
- Collect scenarios with `result: "FAIL"` or `result: "ERROR"`

### Step 2: Initialize Run

1. Source `test/scenarios/_shared/scripts/common.sh`
2. Generate Run ID: `generate_run_id`
3. Set `TEST_OUTPUT_DIR` (default: `.test-output/`)
4. Initialize output directory: `init_run_output`
5. Load cached environment info: `cache_common_info`
6. **Count scenarios and determine execution mode:**
   - 1-2 scenarios → Direct Mode (Step 3A)
   - 3+ scenarios → Parallel Mode (Step 3B)
7. **Pre-create all scenario output directories** (eliminates race conditions in Parallel Mode):
   ```bash
   mkdir -p {TEST_OUTPUT_DIR}/runs/{run_id}/l{N}/{scenario_id_1} \
            {TEST_OUTPUT_DIR}/runs/{run_id}/l{N}/{scenario_id_2} \
            ...
   ```

8. Read the framework README and layer README once for cleanup verification rules and shared-environment caveats before executing any scenario.

### Step 3A: Execute Scenarios — Direct Mode (1-2 scenarios)

For each scenario, execute sequentially in the lead agent:

1. **Read the scenario's README.md** in its directory for prerequisites, expected behavior, and troubleshooting context.
2. **Initialize scenario output**: `init_scenario_output`
3. **Inspect `scripts/` first**. Treat scenario scripts as the execution contract whenever they exist.
4. **Execute `scripts/setup.sh`** if present.
5. **Execute `scripts/trigger.sh`** if present.
6. **Execute `scripts/verify.sh`** if present. This is the primary assertion driver when available.
7. **If `verify.sh` is absent**, fall back to the scenario README for manual operation/verification steps.
8. **Always execute `scripts/cleanup.sh`** if present, even when earlier steps failed.
9. **Perform cleanup verification** using the framework README, layer README, and scenario README:
   - confirm scenario-owned resources expected to disappear are actually gone
   - if residual resources remain, record contamination instead of treating cleanup as fully successful
10. **Record scenario result**: `write_scenario_result`

### Step 3B: Execute Scenarios — Parallel Mode (3+ scenarios)

#### 3B.1: Batch Preparation

Split the scenario list into batches of **N scenarios** each (N = `--batch-size`, default **8**).

Example with default batch size 8: 12 scenarios → 2 batches (8 + 4)

#### 3B.2: Dispatch Each Batch

For each batch:

1. **Issue N `Task` tool calls in a single message** (one per scenario in the batch) to achieve parallel execution:

   ```
   Task:
     subagent_type: general-purpose
     mode: bypassPermissions
     description: "Run {scenario_id}"
     prompt: <SUB-AGENT PROMPT — see template below>
   ```

2. **Wait** for all sub-agents in the batch to complete.

3. **Collect results**: For each scenario in the batch, check `{output_dir}/{scenario_id}/result.json`:
   - **File exists with valid JSON** → read the result (`PASS` or `FAIL`)
   - **File missing or invalid** → sub-agent crashed; write an ERROR result:
     ```bash
     cat > {output_dir}/{scenario_id}/result.json << 'EOF'
     {
       "scenario_id": "{scenario_id}",
       "result": "ERROR",
       "error": "Sub-agent crashed or failed to write result",
       "duration_seconds": 0
     }
     EOF
     ```

4. **Report batch progress**:
   ```
   Batch {M}/{total_batches} complete: {pass} passed, {fail} failed, {error} errors
   Cumulative: {total_pass}/{total_scenarios} passed
   ```

5. Repeat for next batch.

#### Sub-agent Prompt Template

Use the following template for each sub-agent prompt. Replace all `{...}` placeholders with actual values.

```
You are executing a single Ferry scenario integration test.

## Scenario
- Scenario ID: {scenario_id}
- Scenario directory: {scenario_dir}  (absolute path)
- README path: {scenario_dir}/README.md
- Output directory: {output_dir}/{scenario_id}  (absolute path, already created)

## Run Context
- run_id: {run_id}
- run_dir: {run_dir}  (absolute path)
- Layer: {layer}
- TEST_OUTPUT_DIR: {test_output_dir}

## Execution Protocol

**IMPORTANT**: Every Bash call starts a fresh shell. You must re-source common.sh at the beginning of EVERY Bash call.

1. Read the scenario README at `{scenario_dir}/README.md` for prerequisites, expected behavior, cleanup expectations, and troubleshooting context.

2. Source common.sh and initialize:
   ```bash
   source test/scenarios/_shared/scripts/common.sh
   export RUN_ID="{run_id}"
   export TEST_OUTPUT_DIR="{test_output_dir}"
   export SCENARIO_ID="{scenario_id}"
   init_scenario_output
   cache_common_info
   ```

3. Check prerequisites listed in the README. If prerequisites are not met, write a FAIL result and stop.

4. Inspect `{scenario_dir}/scripts/`. Treat scenario scripts as the execution contract whenever they exist.

5. Execute `scripts/setup.sh` if present:
   ```bash
   source test/scenarios/_shared/scripts/common.sh
   export RUN_ID="{run_id}" TEST_OUTPUT_DIR="{test_output_dir}" SCENARIO_ID="{scenario_id}"
   cache_common_info
   cd {scenario_dir} && bash scripts/setup.sh
   ```

6. Execute `scripts/trigger.sh` if present:
   ```bash
   source test/scenarios/_shared/scripts/common.sh
   export RUN_ID="{run_id}" TEST_OUTPUT_DIR="{test_output_dir}" SCENARIO_ID="{scenario_id}"
   cache_common_info
   cd {scenario_dir} && bash scripts/trigger.sh
   ```

7. Execute `scripts/verify.sh` if present. Treat it as the primary assertion driver:
   ```bash
   source test/scenarios/_shared/scripts/common.sh
   export RUN_ID="{run_id}" TEST_OUTPUT_DIR="{test_output_dir}" SCENARIO_ID="{scenario_id}"
   cache_common_info
   cd {scenario_dir} && bash scripts/verify.sh
   ```

8. If `verify.sh` is absent, fall back to the README-defined manual operation/verification steps and record results via `write_step_result`.

9. **ALWAYS execute the cleanup step** — even if earlier steps failed. This is critical to avoid resource leaks:
   ```bash
   source test/scenarios/_shared/scripts/common.sh
   export RUN_ID="{run_id}" TEST_OUTPUT_DIR="{test_output_dir}" SCENARIO_ID="{scenario_id}"
   cache_common_info
   cd {scenario_dir} && bash scripts/cleanup.sh
   ```

10. After cleanup, verify that scenario-owned resources expected to disappear are actually gone. Use the framework README, layer README, and scenario README as the source of truth. If residual resources remain, record that as contamination in the scenario output.

11. Record the final scenario result:
   ```bash
   source test/scenarios/_shared/scripts/common.sh
   export RUN_ID="{run_id}" TEST_OUTPUT_DIR="{test_output_dir}" SCENARIO_ID="{scenario_id}"
   write_scenario_result
   ```

## Key Reminders
- Re-source `common.sh` in EVERY Bash call (shell state does not persist between calls)
- Always set RUN_ID, TEST_OUTPUT_DIR, SCENARIO_ID environment variables after sourcing
- Always call `cache_common_info` after sourcing to load environment variables (GIT_TOKEN, GITEA_HOST, etc.)
- ALWAYS run cleanup, even on failure
- Cleanup completion is not enough by itself; verify the expected resources actually disappeared
- The output directory `{output_dir}/{scenario_id}` already exists — write results there
- Use `write_step_result` and `write_scenario_result` from common.sh to record results
```

### Step 4: Handle Failures

After all scenarios complete (Direct or Parallel mode):

If any scenario has result `FAIL`:
- Automatically trigger `/test-investigate {scenario_id}` for each failure
- Or ask user whether to investigate now or continue

If any scenario has result `ERROR`:
- Report which scenarios had sub-agent errors
- Suggest rerunning those specific scenarios with `-i` flag
- ERROR scenarios indicate infrastructure issues, not test failures

If failure or cleanup output indicates shared-environment contamination:
- Prefer targeted cleanup before rerunning
- Use the framework README and layer README for environment-specific contamination checks
- Do not default to full environment rebuild unless the narrower recovery levels are exhausted

### Step 5: Generate Summary and Report

1. Write summary: `write_summary`
2. Update latest symlink: `ln -sfn runs/{run_id} {TEST_OUTPUT_DIR}/latest`
3. Present results:

```
Run: {run_id}
Mode: {Direct|Parallel (N batches)}
Total: X | Passed: Y | Failed: Z | Errors: E | Skipped: W

Failed scenarios:
  - L1.003: Phase stuck at Rendering after 60s
  - L1.005: Approval condition not set

Error scenarios (sub-agent crash):
  - L2.045: Sub-agent crashed or failed to write result
```

4. Ask user for next action:
   - Investigate failures (`/test-investigate`)
   - Rerun failures (`/test-scenario -r {run-id}`)
   - Continue to next layer
   - Stop

## Output Structure

```
{TEST_OUTPUT_DIR}/runs/{run_id}/
  manifest.json                    # Run metadata
  summary.json                     # Summary report
  l{N}/{scenario_id}/
    result.json                    # Scenario result
    steps/{step_name}.log          # Step logs
    artifacts/                     # Scenario artifacts
```
