# F-019 RAG 选型 Gate 记录

## 当前结论

状态为 `PREPARED_NOT_SELECTED`。Batch 1 已冻结可重复的 corpus、人工 gold set、候选
中间合同、质量 Gate、增量审计和成本/耗时记录格式；尚未选择生产 RAG 框架，也不能把
确定性基线描述为正式 RAG 能力。

## 数据与合同

- Dataset version：`2026.07.19.1`。
- 20 份中文合成文档，覆盖 HTML、PDF、DOCX、纯文本及产品、竞品、市场资料。
- 60 条事实、53 个实体、40 条关系、40 个问题意图。
- 两个 Project，包含内容冲突、时间变化、噪声、重复导入、更新、删除和新增。
- Manifest 固定文件 SHA-256、LicenseRef、Project 边界和 schema version。
- 所有候选只能输出项目自有 `f019-candidate-output-v1`，框架对象不得进入 Domain、稳定
  API 或业务主数据。

正式质量硬门槛与实施计划第 4.8 节一致：实体 precision `>= 0.85`、关系 precision
`>= 0.80`、正式候选事实来源可追踪率 `= 100%`、无事实支持问题比例 `<= 5%`、
语义重复问题比例 `<= 10%`、有证据支撑的计划维度覆盖率 `>= 90%`；Project 泄漏、
绕过人工批准、`test_only` 产物可发布及增量重复/孤儿/回归必须为零。

## Batch 1 实测

| 候选 | 状态 | 质量分 | 模型调用 | 估算成本 | 墙钟时间 | 选型资格 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Deterministic structured fixture | passed | 1.000 | 0 | USD 0 | 7 ms | `harness_reference_only` |
| LlamaIndex Property Graph | unavailable | - | - | - | - | 依赖/执行器未配置 |
| Microsoft GraphRAG | unavailable | - | - | - | - | 仅隔离对比，依赖/执行器未配置 |

墙钟时间是本机单次记录，只用于证明格式可用，不是性能承诺。成本和耗时必须如实记录，
但不设固定或相对当前基线的淘汰上限。候选先通过所有质量与安全硬门槛；质量差小于
2 个百分点时才依次比较成本、耗时，仍相同时优先 LlamaIndex。

## 复核命令

```bash
make f019-benchmark
uv run python -m benchmarks.f019.cli run --adapter llamaindex \
  --output /tmp/f019-llamaindex.json
uv run python -m benchmarks.f019.cli run --adapter graphrag \
  --output /tmp/f019-graphrag.json
```

依赖或项目自有执行器不存在时，框架命令必须以 `unavailable` 非零退出，并将 metrics、
Gate、质量分、Token、成本和耗时保留为空，禁止伪造候选结果。

## 正式选型剩余条件

1. 固定候选框架版本及项目自有 adapter executor。
2. 使用同一 corpus、gold set 和模型策略执行 LlamaIndex 与项目基线；GraphRAG 只做隔离
   对比。
3. 保存每个候选的原始中间合同、scorecard、Token、调用数、成本和墙钟时间。
4. 所有硬门槛通过后按质量优先规则形成新的 `SELECTED` 记录。
5. 正式领域接入仍须等待 F-013、F-014、F-009 和 F-021 合同稳定。
