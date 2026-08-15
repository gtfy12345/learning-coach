# 评价、安全与完整交付单元测试计划

> **版本**: 1.0
> **状态**: draft
> **更新日期**: 2026-08-15

**关联 Checklist**: [unit-test-plan-checklist.md](./unit-test-plan-checklist.md)

## 测试原则

- 全部离线确定性：评估集、轨迹、安全与报告均不调用真实模型。
- 指标阈值取实测基线；安全样例覆盖命中、未命中与混合形态。
- 既有流程回归确认新字段可选且不影响旧断言。

## Phase 1: 安全层

- PII 五类样例命中与计数；正常文本零误报。
- 注入标记中英文样例命中；普通资料不误报。
- redact_pii 掩码保留首尾字符。
- hardened_study_context 含定界符与加固声明且保留原文。
- 收集节点把发现写入 safety_findings；Web 粘贴资料扫描进初始状态。

## Phase 2: 评价层

- evaluate_retrieval 在评估集上 hit_rate/MRR 不低于基线阈值。
- evaluate_trajectory 对合规状态全通过，对越界状态逐项失败。
- build_mastery_map 概念分级、缺口映射与回退路径。
- build_telemetry 计数正确。

## Phase 3: 阶段报告与集成

- 完成会话包含 stage_report 且字段安全（无原文/密钥）。
- CLI evaluate 输出指标摘要。
- Web 结果视图与 SessionView 暴露阶段报告。

## Phase 4: 公开文档与回归

- README 契约关键词。
- 全量测试套件通过。
