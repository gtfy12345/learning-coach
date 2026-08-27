# L5 数据模板

来源：`test/scenarios/l5/003-argocd-e2e/data/`（3 个文件）

L5 全链路手动验收测试需要：ApprovalPolicy、ClusterMeta ConfigMap、ArgoCD ApplicationSet。

## approval-policy.yaml 模板

```yaml
# L5.{SEQ} ApprovalPolicy - 配置审批策略
apiVersion: ferry.monshunter.dev/v1alpha1
kind: ApprovalPolicy
metadata:
  name: l5-{SEQ:03d}-approval-policy
spec:
  approvalPolicies:
    - stage: approval
      policy:
        requiredApprovers:
          - ${APPROVER_EMAIL}
```

## cluster-meta.yaml 模板

```yaml
# ClusterMeta ConfigMap - 目标集群配置
apiVersion: v1
kind: ConfigMap
metadata:
  name: ${CLUSTER_ID}
  namespace: platform-clusters
  labels:
    ferry.monshunter.dev/resource-type: cluster-metadata
    ferry.monshunter.dev/cluster-id: ${CLUSTER_ID}
    ferry.monshunter.dev/env: ${ENV}
  annotations:
    ferry.monshunter.dev/cluster-state: active
    ferry.monshunter.dev/managed-by: l5-{SEQ:03d}-scenario
data:
  clusterId: ${CLUSTER_ID}
  provider: ${PROVIDER}
  engine: ${ENGINE}
  region: ${REGION}
  env: ${ENV}
  server: https://kubernetes.default.svc
  argocdClusterName: in-cluster
  labels: |
    env: ${ENV}
    test-scenario: l5-{SEQ:03d}
```

## applicationset.yaml 模板（ArgoCD 专用）

```yaml
# ArgoCD ApplicationSet for L5.{SEQ} scenario
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: l5-{SEQ:03d}-manifest-apps
  namespace: argocd
spec:
  generators:
  - git:
      repoURL: "${DELIVERY_REPO_URL}"
      revision: release
      files:
      - path: "configs/cls-*.json"
  template:
    metadata:
      name: 'l5-{SEQ:03d}-{{cluster.name}}'
      labels:
        app.kubernetes.io/managed-by: argocd-applicationset
        ferry.monshunter.dev/scenario: l5-{SEQ:03d}
        environment: '{{cluster.environment}}'
    spec:
      project: default
      source:
        repoURL: "${DELIVERY_REPO_URL}"
        targetRevision: '{{branch}}'
        path: 'manifests'
      destination:
        server: '{{cluster.server}}'
        namespace: '{{cluster.namespace}}'
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
        - CreateNamespace=true
        - ServerSideApply=true
```

## 占位符说明

| 占位符 | 说明 |
|--------|------|
| `{SEQ:03d}` | 场景序号，3 位补零 |
| `${APPROVER_EMAIL}` | 审批人邮箱 |
| `${CLUSTER_ID}` | 集群 ID，如 `cls-local` |
| `${ENV}` | 环境名，如 `local`、`dev` |
| `${PROVIDER}` | 集群提供商，如 `kind`、`eks` |
| `${ENGINE}` | 部署引擎，如 `kind`、`eks` |
| `${REGION}` | 区域，如 `local`、`us-east-1` |
| `${DELIVERY_REPO_URL}` | 运行时替换的 delivery 仓库 URL |

## L5 场景数据文件约定

- 必须有：`data/approval-policy.yaml`（审批策略）
- 必须有：`data/cluster-meta.yaml`（集群元信息）
- 有 ArgoCD 时加：`data/applicationset.yaml`
- L5 脚本分为 4 个：`setup.sh` / `trigger.sh` / `verify.sh` / `cleanup.sh`
- 执行方式：`manual`（由人工在真实 GitLab + 集群环境执行）
