# L3 数据模板

来源：`test/scenarios/l3/001-submit-main/data/approval-policy.yaml`

L3 ferryctl CLI 集成测试的核心数据文件为 `data/approval-policy.yaml`（ApprovalPolicy CRD 对象）。

## approval-policy.yaml 模板

```yaml
# L3.{SEQ} 测试数据 - ApprovalPolicy
apiVersion: ferry.monshunter.dev/v1alpha1
kind: ApprovalPolicy
metadata:
  name: l3-{SLUG}-approval-policy
spec:
  approvalPolicies:
    - stage: approval
      policy:
        requiredApprovers:
          - ${APPROVER_EMAIL}
```

## 占位符说明

| 占位符 | 说明 |
|--------|------|
| `{SEQ:03d}` | 场景序号，3 位补零，如 `001` |
| `{SLUG}` | 场景短名（含业务编号），如 `fc001` |
| `${APPROVER_EMAIL}` | 审批人邮箱，测试用 `test@example.com` |

## L3 场景数据文件约定

- 主数据文件：`data/approval-policy.yaml`
- L3 场景通过 `ferryctl deploy submit` 命令触发，底层调用 API Server
- ApprovalPolicy 需预先部署到集群，ferryctl 通过引用其名称使用
- 多阶段审批场景需在 `spec.approvalPolicies` 中添加多个条目
- 场景脚本通过 `kubectl apply -f data/approval-policy.yaml` 部署
