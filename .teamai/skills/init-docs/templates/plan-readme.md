# 计划文档规范

## 1 目录结构

```
docs/plan/
├── README.md                              # 本文件，规范说明
├── INDEX.md                               # 文档索引
└── ${subject}/                            # 计划目录
    ├── context.yaml                       # 上下文声明（必填，计划上下文契约）
    ├── implementation.md                  # 实施计划
    ├── implementation-checklist.md        # 实施 Checklist
    ├── ${type}-plan.md                    # 其他计划（如测试计划）
    └── ${type}-plan-checklist.md          # 对应 Checklist
```

**示例**：
```
docs/plan/
├── feature-auth/
│   ├── context.yaml
│   ├── implementation.md
│   ├── implementation-checklist.md
│   ├── unit-test-plan.md
│   └── unit-test-plan-checklist.md
└── ...
```

## 2 核心规则

1. **成对创建**：每个计划文档必须有对应的 Checklist
2. **版本一致**：计划和 Checklist 版本号必须一致
3. **唯一真理**：Checklist 是任务完成状态的唯一真理来源
4. **原子更新**：修改计划内容时，必须同步更新 Checklist
5. **串行默认**：新计划默认采用顺序 phase 闭环，不再要求 `parallel` / Wave / DAG
6. **历史兼容**：旧 `parallel` / `phase-mapping` / HTML 注释格式仍可被读取，但不再是新文档规范
7. **上下文声明**：每个计划目录必须包含 `context.yaml`（`/implement`、`/plan-review`、`/plan-code-review` 共用的计划上下文契约）

## 3 文档元信息

所有计划文档必须在头部包含元信息：

```markdown
> **版本**: 1.0
> **状态**: active
> **更新日期**: YYYY-MM-DD
```

> 历史计划文档中若仍保留 `> **执行模式**: parallel|sequential`，共享工具应兼容读取；新文档不再要求该字段。

**状态值说明**：

| 状态 | 含义 |
|------|------|
| `draft` | 草稿，尚未正式生效 |
| `active` | 生效中，正在执行 |
| `completed` | 已完成 |
| `superseded` | 已被取代，需注明新文档路径 |
| `deprecated` | 已废弃，不再适用 |

## 4 命名规范

| 类型 | 计划文档 | Checklist |
|------|----------|-----------|
| 实施计划 | `implementation.md` | `implementation-checklist.md` |
| 测试计划 | `unit-test-plan.md` / `e2e-test-plan.md` / `bdd-test-plan.md` | 对应 `*-checklist.md` |
| 其他计划 | `${type}-plan.md` | `${type}-plan-checklist.md` |

## 5 文档模板（默认串行）

### 5.1 串行计划文档模板

```markdown
# 计划名称

> **版本**: 1.0
> **状态**: active
> **更新日期**: YYYY-MM-DD

**关联 Checklist**: [checklist](./implementation-checklist.md)

## 1 目标

描述本计划要达成的目标。

## 2 背景

说明为什么需要这个计划。

## 3 实施步骤

### Phase 1: 基础设施准备

#### 1.1 创建基础配置

具体步骤描述。

#### 1.2 校验默认值

具体步骤描述。

### Phase 2: 服务集成

#### 2.1 接入 Service 层

具体步骤描述。

## 4 验收标准

- 验收项 1
- 验收项 2

## 5 风险与应对

| 风险 | 应对措施 |
|------|----------|
| 风险 1 | 措施 1 |

## 6 关联文档

- [相关设计](../spec/xxx.md)
```

### 5.2 串行 Checklist 模板

```markdown
# 计划名称 Checklist

> **版本**: 1.0
> **状态**: active
> **更新日期**: YYYY-MM-DD

**关联计划**: [计划文档](./implementation.md)

## Phase 1: 基础设施准备

- [ ] 1.1 创建基础配置
- [ ] 1.2 校验默认值

## Phase 2: 服务集成

- [ ] 2.1 接入 Service 层
- [ ] 2.2 BDD-Gate: 验证 L4.070, L5.019 通过
```

### 5.3 串行模式格式约定

- Phase 标题格式：`### Phase {序号}: 描述`
- 任务标题格式：`#### {Phase序号}.{任务序号} 描述`
- Checklist section 标题格式：`## Phase {序号}: 描述`
- Checklist 任务 ID 必须与 plan task ID 一致（如 `1.1`、`2.1`）
- 新文档默认按本节格式书写；无需额外声明执行模式

### 5.4 Legacy 兼容说明

历史文档中仍存在以下旧格式，L1 review / parser 仍应兼容读取，但**新文档不再使用**：

- plan phase：`### 3.1 Phase 1: 描述`
- plan task：`#### 3.1.1 描述`
- plan phase：`### W1.Auth: 描述`
- checklist section：`## W1.Auth: 描述 [role]`
- phase 元数据：`<!-- agent: -->`、`<!-- files: -->`、`<!-- depends-on: -->`
- checklist section：`## 1 Phase 1: 描述`
- checklist section：`## 1 描述`
- checklist task：以 `### 2.1 描述` 子节代表 task，子节下再挂无 ID 的 checkbox 明细

### 5.5 测试 Checklist 模板

当测试 checklist 通过 `testChecklist` 字段关联到实施 target 时，新文档默认通过 section 标题直接表达对应 phase，不再要求 `<!-- phase-mapping: -->` 注释。

**默认写法**（section 标题直接复用实施 checklist 的 phase 编号）：

```markdown
## Phase 1: 登录页测试

- [ ] 1.1 渲染模式切换测试
- [ ] 1.2 本地登录表单校验

## Phase 2: 注册页面测试

- [ ] 2.1 Token 解析测试
- [ ] 2.2 密码校验测试
```

**Legacy 兼容写法**（仅历史文档继续使用）：

```markdown
## 1 登录页测试
<!-- phase-mapping: 1 -->

- [ ] 1.1 渲染模式切换测试
- [ ] 1.2 本地登录表单校验

## 2 注册页面测试
<!-- phase-mapping: 2 -->

- [ ] 2.1 Token 解析测试
```

**规则**：

- `/tdd --test-checklist` 优先根据 test checklist section 标题中的 `Phase {N}` 推断映射
- 若存在 `<!-- phase-mapping: {impl-phase-id} -->`，则视为 legacy 明确映射并优先使用
- 一个 test section 只映射到一个 impl phase
- 新文档推荐一对一映射：一个 implementation phase 对应一个 test checklist section

### 5.6 BDD-Gate 项

当关联需求包含 BDD 验证闭环时，implementation checklist 中每个需收口验证的行为 phase 应以 BDD-Gate 项收尾。

**格式**：`- [ ] {id} BDD-Gate: 验证 {scenario-ids} 通过`

**约定**：

- `BDD-Gate:` 前缀为 `/tdd` 机器识别标记
- `{scenario-ids}` 使用目标测试层的场景编号，遵守对应 `test/scenarios/<layer>/README.md` 与 `INDEX.md` 的规范，例如 `L4.070`、`L5.019`
- `bdd-test-plan.md` 是 BDD 场景分配与覆盖映射的真理源；如需把场景回连到 spec 验收标准，应在该文档中表达，而不是在 checklist 中引入 `AC-*` 机器引用
- BDD-Gate 项必须是 phase 内最后的 item(s)
- `/tdd` 执行 BDD-Gate 项时使用 Deploy-Verify 协议（非 Red-Green-Refactor）
- 历史 `AC-*` 风格的 BDD-Gate 项仍可被执行链路兼容读取，但新文档不再生成该格式

**串行示例**：

```markdown
- [ ] 1.3 BDD-Gate: 验证 L4.070, L5.019 通过
```

## 6 上下文声明（context.yaml）

每个计划目录必须包含 `context.yaml`，声明该计划的可执行目标与所需上下文文件。

- `/implement`、`/plan-review`、`/plan-code-review` 读取 `context.yaml` 的执行字段
- `/change-intake` 读取 `context.yaml` 的 discovery 字段做问题匹配

`context.yaml` 是 plan 上下文的单一真理源；不要再依赖 plan/spec 文档头部的关联链接、HTML 注释或 Header 扩展字段推断业务语义。

### 6.1 最小模板

```yaml
apiVersion: ferry.agent.context/v1alpha1
kind: PlanContext
metadata:
  name: ${subject}
spec:
  defaultTarget: backend
  discovery:
    aliases:
      - ${subject}
    keywords:
      - TODO: add user-facing issue keywords
  targets:
    backend:
      plan: ./implementation.md
      checklist: ./implementation-checklist.md
      spec: ../../spec/${subject}-design.md
      discovery:
        packages:
          - TODO: add main packages or modules
```

含测试计划与 target discovery 的模板：

```yaml
apiVersion: ferry.agent.context/v1alpha1
kind: PlanContext
metadata:
  name: ${subject}
spec:
  defaultTarget: backend
  discovery:
    aliases:
      - ${subject}
    keywords:
      - TODO: add issue keywords
    relatedBugs:
      - BUG-XXXX
    relatedSpecs:
      - ../../spec/${subject}-design.md
  targets:
    backend:
      plan: ./implementation.md
      checklist: ./implementation-checklist.md
      spec: ../../spec/${subject}-design.md
      testPlan: ./unit-test-plan.md
      testChecklist: ./unit-test-plan-checklist.md
      bddPlan: ./bdd-test-plan.md
      discovery:
        packages:
          - internal/example
        apiNames:
          - GetExample
        commands:
          - ferryctl example get
```

### 6.2 Execution 字段约束

| 字段 | 必填 | 说明 |
|------|------|------|
| `apiVersion` | 是 | 固定 `ferry.agent.context/v1alpha1` |
| `kind` | 是 | 固定 `PlanContext` |
| `metadata.name` | 是 | 计划标识，与目录名一致 |
| `spec.defaultTarget` | 是 | 默认执行目标 |
| `spec.targets` | 是 | 目标集合 |
| `spec.targets.<target>.plan` | 是 | 目标主计划文档（相对路径） |
| `spec.targets.<target>.checklist` | 是 | 目标执行 checklist（相对路径） |
| `spec.targets.<target>.spec` | 否 | 关联设计文档（相对路径） |
| `spec.targets.<target>.testPlan` | 否 | 目标关联测试计划文档（相对路径） |
| `spec.targets.<target>.testChecklist` | 否 | 目标关联测试 checklist（相对路径） |
| `spec.targets.<target>.bddPlan` | 否 | BDD 场景计划文档（相对路径） |
| `spec.targets.<target>.references` | 否 | 其他只读引用文件路径列表（字符串数组） |

### 6.3 Discovery 字段约束

| 字段 | 必填 | 说明 |
|------|------|------|
| `spec.discovery.aliases` | 新建 plan 必填 | 主题别名，用于匹配常见简称、模块名、旧称 |
| `spec.discovery.keywords` | 新建 plan 必填 | 用户常见问题表述、错误语义、业务关键词 |
| `spec.discovery.relatedBugs` | 否 | 关联 BUG ID 列表 |
| `spec.discovery.relatedSpecs` | 否 | 补充关联 spec 路径（字符串数组） |
| `spec.targets.<target>.discovery.packages` | 建议 | 主要代码目录或模块名 |
| `spec.targets.<target>.discovery.uiRoutes` | 否 | 关联 UI 路由 |
| `spec.targets.<target>.discovery.apiNames` | 否 | 关联 API / RPC / command 名称 |
| `spec.targets.<target>.discovery.commands` | 否 | 关联 CLI 子命令 |

规则：

- 新建 plan 必须填写 `spec.discovery`
- 新建 plan 的主要 target 必须填写至少一项 target-level discovery
- 历史 `completed` plan 可以缺失 discovery；`/change-intake` 会回退到 `metadata.name`、文件名与 references 做弱匹配
- 出于向后兼容与渐进补齐考虑，共享 validator 对 discovery 采用“缺失不阻断、出现则校验类型”的策略
- 任何正在维护的 `draft` / `active` plan，一旦本次任务改动到其 `context.yaml`，应顺手补齐 discovery 字段

### 6.4 Completed Plan 与 Follow-up 规则

`completed` plan 是历史交付记录，不允许为后续 bugfix 或特性修订直接重开原 checklist。

统一规则：

1. 命中 `completed` plan 且需要继续变更时，一律新建 follow-up / bugfix plan
2. 原 `completed` plan 只允许做文档级漂移修复：
   - Header / INDEX 同步
   - 链接修复
   - `context.yaml` 路径或 discovery 元数据补齐
   - 文末 `## 后续修复 / Follow-ups` 回链区块
3. 原 `completed` plan 的实现内容、原 checklist 勾选状态、原完成结论都不得改写

判定矩阵：

| 变更类型 | 是否允许原地修改 completed plan | 处理方式 |
|----------|-------------------------------|----------|
| Header / INDEX / 链接 / `context.yaml` 漂移 | 是 | 原地修复 |
| discovery 元数据补齐 | 是 | 原地补齐 |
| Bugfix / 回归修复 | 否 | 新建 follow-up 或 bugfix plan |
| 新特性 / 设计修订 / 契约变化 | 否 | 先修 spec，再建 follow-up plan |

### 6.5 Follow-up 命名与必带引用

默认命名：

- 通用修订：`${original-subject}-follow-up-${short-topic}`
- 纯 bugfix：`${original-subject}-bugfix-${bug-id}`

新的 follow-up plan 必须：

- 引用原 spec / 原 plan / 相关 BUG / 相关 report
- 在新的 `context.yaml` 中填写 discovery 元数据
- 若涉及设计变化，先创建 follow-up spec 或提升原 spec 版本，再开始编码

### 6.6 原计划回链模板

当某个 `completed` plan 有了后续修复时，在原计划文末追加：

```markdown
## 后续修复 / Follow-ups

- 2026-04-04: [session refresh follow-up](../local-auth-follow-up-session-refresh/implementation.md) - 修复 refresh 后 session 丢失问题
```

原 checklist 不追加新项，不重开旧项。

### 6.7 路径安全

所有路径归一化后必须位于 `docs/` 目录内，否则 implement 共享校验器会阻断。

## 7 检查清单

完成计划文档前，确认以下事项：

- [ ] 创建计划目录 `docs/plan/${subject}/`
- [ ] 创建 `context.yaml` 上下文声明
- [ ] 为新建 plan 填写 `spec.discovery.aliases` 与 `spec.discovery.keywords`
- [ ] 为主要 target 填写至少一项 `spec.targets.<target>.discovery.*`
- [ ] 计划与 Checklist 成对创建
- [ ] 两个文档版本号一致
- [ ] 计划文档 Header 使用 `版本 / 状态 / 更新日期` 三字段标准顺序
- [ ] 实施步骤使用规范顺序格式（如 `### Phase 1`、`#### 1.1`）
- [ ] Checklist 使用规范顺序格式（如 `## Phase 1`、`- [ ] 1.1 ...`）
- [ ] 若存在 test checklist，section 标题可直接映射到 implementation phase；无需新增 HTML 注释
- [ ] 已更新 `INDEX.md` 索引
- [ ] 计划文档关联了 Checklist
- [ ] Checklist 关联了计划文档
- [ ] 若本次是对 `completed` plan 的后续修复，已新建 follow-up plan 并回链原计划
