---
name: test-investigate
description: Investigate scenario test failures by checking test design, environment, and code issues in priority order. Triggers on /test-investigate.
---

# Ferry Test Investigate Skill

Investigates scenario test failures by systematically checking potential causes in priority order.

## Trigger Command

```
/test-investigate L1.003                              # Investigate latest failure
/test-investigate L1.003 --run 20260120-153045-a1b2   # Investigate specific run
```

## Reference Documents

- Scenario contract: the failing scenario's `README.md`
- Framework truth source: `test/scenarios/README.md`
- Layer truth source: `test/scenarios/l4/README.md` or `test/scenarios/l5/README.md`

Use these documents for concrete environment topology, cleanup expectations, consumer surfaces, and layer-specific troubleshooting commands. Keep this skill focused on investigation order and decision points.

## Workflow

### Step 1: Gather Failure Context

1. Locate the run output directory:
   - Latest: `{TEST_OUTPUT_DIR}/latest/l{N}/{scenario_id}/`
   - Specific run: `{TEST_OUTPUT_DIR}/runs/{run_id}/l{N}/{scenario_id}/`

2. Read failure artifacts:
   - `result.json` - Scenario result with failed step info
   - `steps/*.log` - Step execution logs
   - Scenario `README.md` - Expected behavior reference
   - Framework README and layer README - environment behavior, cleanup rules, and live verification reference

### Step 2: Priority 1 - Check the Test Itself

Most failures are test issues. Check:

- **Is the scenario design correct?** Compare README steps against actual system behavior
- **Is the test data valid?** Check `data/*.yaml` for correctness, verify placeholders were replaced
- **Are the steps in correct order?** Check dependency between steps
- **Are the expected results reasonable?** Compare with actual CRD spec/status behavior
- **Is the wait time sufficient?** Check timeout values in `wait-for-phase.sh` calls (some operations need >60s)
- **Was setup.sh executed?** Scenario repos and namespaces must exist before test steps

### Step 3: Priority 2 - Check the Environment and Shared Control Plane

If the scenario design looks correct, investigate environment-level causes before blaming code:

- Is the failure explained by incomplete cleanup, residual scenario resources, or blocked control-plane convergence?
- Is the failure coming from a shared environment component rather than the scenario under test?
- Do the framework/layer README documents describe a known cleanup verification step or contamination source that was skipped?

Use the framework README and layer README for the concrete commands and layer-specific signals.

### Step 4: Priority 3 - Check Consumer Artifact Drift

If the environment looks healthy, verify that the test is hitting current consumer artifacts instead of stale ones:

- locally built binaries
- generated clients or generated schema artifacts
- cluster-installed schemas or CRDs
- deployed components
- user-facing entrypoints that proxy or front the underlying service

Treat consumer drift as distinct from code bugs. Use the layer README to identify the concrete surfaces that must align in that environment.

### Step 5: Priority 4 - Check for Code Bugs

Only after the test contract, environment, and consumer artifacts look correct should you attribute the failure to product code.

At that point, inspect the relevant component logs, resource status, and recent code changes.

### Step 6: Generate Investigation Report

Write `investigation.json` to the scenario output directory:

```json
{
  "investigation": {
    "scenario_id": "L1.003",
    "run_id": "20260120-153045-a1b2",
    "investigated_at": "2026-01-20T16:00:00Z",
    "failure_symptom": "Description of what failed",
    "investigation_steps": [
      {
        "priority": 1,
        "area": "test",
        "findings": "Summary of test-level findings"
      },
      {
        "priority": 2,
        "area": "environment",
        "findings": "Summary of environment findings"
      },
      {
        "priority": 3,
        "area": "code",
        "findings": "Summary of code-level findings"
      }
    ],
    "root_cause": "Identified root cause",
    "recommendation": "Suggested fix"
  }
}
```

### Step 7: Propose Fix

Present findings and ask user to choose:

- **Option A: Fix the test** - Modify scenario README/data/scripts
- **Option B: Fix the code** - Fix source code, then `/ferry-redeploy {component}`
- **Option C: Create an Issue** - Document as a known bug for later
- **Option D: Mark as expected** - Update scenario expected results

## Investigation Checklist

- [ ] Read result.json and step logs
- [ ] Read scenario README.md for expected behavior
- [ ] Read framework README and layer README for environment-specific truth
- [ ] Check test data and placeholder replacement
- [ ] Check setup.sh was executed (scenario repos/namespaces exist)
- [ ] Check environment contamination and shared control-plane health
- [ ] Check consumer artifact drift before blaming code
- [ ] Check component logs and resource state only after higher-priority checks
- [ ] Identify root cause
- [ ] Write investigation.json
- [ ] Propose fix options to user
