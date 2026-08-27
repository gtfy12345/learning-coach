# L2 数据模板

来源：`test/scenarios/l2/001-createplan-basic/data/create-plan.json`

L2 API Server 集成测试的核心数据文件为 `data/create-plan.json`（CreatePlan gRPC 请求参数）。

## create-plan.json 模板

```json
{
  "namespace": "ns-l2-{SEQ:03d}",
  "app": "test-l2-{SEQ:03d}",
  "spec_repo": "http://gitea.gitea.svc:3000/ferry-test/l2-{SLUG}-spec-repo.git",
  "commit": "0000000000000000000000000000000000000000",
  "branch": "${BRANCH}",
  "delivery_repo": "http://gitea.gitea.svc:3000/ferry-test/l2-{SLUG}-delivery-repo.git",
  "pipeline_id": "pipeline-{SLUG}",
  "pipeline_url": "https://ci.example.com/pipelines/pipeline-{SLUG}",
  "pipeline_type": "${PIPELINE_TYPE}",
  "trigger_type": "TRIGGER_TYPE_MANUAL",
  "require_approval": ${REQUIRE_APPROVAL},
  "approval_policies": [
    {
      "stage": "approval",
      "policy": {
        "required_approvers": [
          "approver@example.com"
        ]
      }
    }
  ],
  "triggered_by": "test-user",
  "triggered_by_email": "test-user@example.com",
  "commit_author": "test-author",
  "commit_author_email": "author@example.com"
}
```

## 占位符说明

| 占位符 | 说明 |
|--------|------|
| `{SEQ:03d}` | 场景序号，3 位补零，如 `001` |
| `{SLUG}` | 场景短名，如 `ap001` |
| `${BRANCH}` | `main` 或其他分支名 |
| `${PIPELINE_TYPE}` | `PIPELINE_TYPE_MAIN` 或 `PIPELINE_TYPE_PR` |
| `${REQUIRE_APPROVAL}` | `true` 或 `false` |
| `0000...0000` | 40 位 Git commit SHA 占位符 |

## L2 场景数据文件约定

- 主数据文件：`data/create-plan.json`（CreatePlan 请求）
- 对于查询/操作类场景（GetPlan, Approve 等），可添加额外 JSON 文件
- namespace 格式：`ns-l2-{SEQ:03d}`（随场景唯一）
- 测试通过 gRPC 客户端或 HTTP Gateway 调用 API Server
