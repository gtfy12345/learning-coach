# L1 数据模板

来源：`test/scenarios/l1/001-deployplan-create/data/deployplan.yaml`

L1 Controller 集成测试的核心数据文件为 `data/deployplan.yaml`（DeployPlan CRD 对象）。

## deployplan.yaml 模板

```yaml
# L1.{SEQ} 测试数据 - {SCENARIO_TITLE}
# 用于验证 {SCENARIO_DESCRIPTION}

apiVersion: ferry.monshunter.dev/v1alpha1
kind: DeployPlan
metadata:
  name: test-plan-l1-{SEQ:03d}
  namespace: ferry-l1-{SEQ:03d}
  labels:
    app.kubernetes.io/name: ${APP_NAME}
    app.kubernetes.io/instance: test-plan-l1-{SEQ:03d}
    ferry.monshunter.dev/test-scenario: l1-{SEQ:03d}
spec:
  # 应用标识符
  app: ${APP_NAME}

  # Git 分支名（与 ClusterMeta clusterId 对应）
  branch: ${BRANCH}

  # Git commit SHA（测试用占位符）
  commit: "0000000000000000000000000000000000000000"

  # 意图仓库 URL
  specRepo: http://gitea.gitea.svc:3000/ferry-test/l1-{SEQ:03d}-spec-repo.git

  # 流水线类型: pr | main
  pipelineType: ${PIPELINE_TYPE}

  # 清单仓库 URL
  deliveryRepo: http://gitea.gitea.svc:3000/ferry-test/l1-{SEQ:03d}-delivery-repo.git

  # CI 流水线信息
  pipelineId: "test-pipeline-l1-{SEQ:03d}"
  pipelineUrl: "http://ci.example.com/pipeline/l1-{SEQ:03d}"

  # 是否需要审批（main 流水线通常为 true）
  requireApproval: ${REQUIRE_APPROVAL}

  # 部署超时时间
  timeout: 30m
```

## 占位符说明

| 占位符 | 说明 |
|--------|------|
| `{SEQ:03d}` | 场景序号，3 位补零，如 `001` |
| `${APP_NAME}` | 应用名称，如 `test-app` |
| `${BRANCH}` | 分支/集群ID，如 `cls-dev-aws-us-east-1` |
| `${PIPELINE_TYPE}` | `pr` 或 `main` |
| `${REQUIRE_APPROVAL}` | `true` 或 `false` |
| `0000...0000` | 40 位 Git commit SHA 占位符 |

## L1 场景数据文件约定

- 仅一个数据文件：`data/deployplan.yaml`
- namespace 格式：`ferry-l1-{SEQ:03d}`（随场景唯一）
- specRepo/deliveryRepo：使用 gitea 内部服务地址
- 对于 Webhook 场景，可在 yaml 中添加 `annotations` 字段
