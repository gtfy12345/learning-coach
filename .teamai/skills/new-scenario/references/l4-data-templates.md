# L4 数据模板

来源：`test/scenarios/l4/003-plans-list/data/plan.yaml` + `plan-status.json`

L4 Web UI 集成测试需要两个数据文件：DeployPlan CRD 对象 + 状态 patch。

## plan.yaml 模板

```yaml
apiVersion: ferry.monshunter.dev/v1alpha1
kind: DeployPlan
metadata:
  name: test-{SLUG}-plan-pipeline-{SLUG}
  namespace: ns-l4-{SEQ:03d}
  labels:
    ferry.monshunter.dev/app: test-{SLUG}
    ferry.monshunter.dev/pipeline-type: ${PIPELINE_TYPE}
    ferry.monshunter.dev/scenario: ${BUSINESS_ID}
  annotations:
    ferry.monshunter.dev/triggered-by: test-user
    ferry.monshunter.dev/commit-author: test-user
spec:
  app: test-{SLUG}
  specRepo: http://gitea.gitea.svc:3000/ferry-test/l4-{SLUG}-spec-repo
  commit: "${SPEC_COMMIT}"
  branch: ${BRANCH}
  deliveryRepo: http://gitea.gitea.svc:3000/ferry-test/l4-{SLUG}-delivery-repo
  pipelineId: pipeline-{SLUG}
  pipelineUrl: https://ci.example.com/pipelines/pipeline-{SLUG}
  pipelineType: ${PIPELINE_TYPE}
  requireApproval: ${REQUIRE_APPROVAL}
  approvalPolicies:
    - stage: approval
      policy:
        requiredApprovers:
          - approver@example.com
```

## plan-status.json 模板

```json
{
  "status": {
    "phase": "${PHASE}",
    "message": "${STATUS_MESSAGE}",
    "clusterSummary": {
      "total": 2,
      "pending": ${PENDING_COUNT},
      "rendering": 0,
      "rendered": 0,
      "pushing": 0,
      "completed": ${COMPLETED_COUNT},
      "failed": 0,
      "skipped": 0
    },
    "matchedClusterIds": [
      "cls-dev-aws-us-east-1",
      "cls-dev-aws-us-west-2"
    ],
    "startTime": "2026-01-28T08:00:00Z"
  }
}
```

## 占位符说明

| 占位符 | 说明 |
|--------|------|
| `{SEQ:03d}` | 场景序号，3 位补零 |
| `{SLUG}` | 场景短名，如 `pl-001` |
| `${BUSINESS_ID}` | 业务编号，如 `pl-001` |
| `${PIPELINE_TYPE}` | `main` 或 `pr` |
| `${BRANCH}` | `main` 或其他分支名 |
| `${SPEC_COMMIT}` | 运行时替换的 commit SHA 变量 |
| `${REQUIRE_APPROVAL}` | `true` 或 `false` |
| `${PHASE}` | DeployPlan 状态：`WaitingApproval`/`Rendering`/`Completed`/`Failed` |
| `${STATUS_MESSAGE}` | 状态描述文字 |
| `${PENDING_COUNT}` / `${COMPLETED_COUNT}` | 集群数量统计 |

## L4 场景数据文件约定

- 必须有：`data/plan.yaml`（DeployPlan 资源）
- 通常有：`data/plan-status.json`（控制 Web UI 显示状态的 patch）
- L4 通过 Playwright 驱动浏览器与 Web UI 交互
- namespace 格式：`ns-l4-{SEQ:03d}`
- 场景脚本需 `kubectl apply` 资源，再用 `kubectl patch` 注入 status
