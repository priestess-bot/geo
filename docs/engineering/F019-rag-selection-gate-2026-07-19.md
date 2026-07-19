# F-019 RAG 正式选型 Gate 记录

## 结论

状态为 `SELECTED`：正式选择 `project-native-rag-v1`，
`llamaindex-property-graph-v1` 保留为已通过同一质量与安全 Gate 的合格回退方案。
回退方案不能通过改配置直接启用，必须重新生成一份指向对应报告哈希的选型清单。

正式机器可读结论位于 `benchmarks/f019/selection.json`。运行时加载器会校验清单状态、
候选 ID、数据集版本、报告 SHA-256 以及报告内全部硬门槛；报告缺失、被改写或任一
门槛未通过时均拒绝启动该 RAG adapter。

## 冻结数据与质量门槛

- Dataset version：`2026.07.19.1`。
- Benchmark manifest SHA-256：
  `ffaf4fb0bdc60098c1593f3b43ab0462b4e381dcdff2ca467540e4604bfa2c0f`。
- 20 份中文合成文档，覆盖 HTML、PDF、DOCX、纯文本及产品、竞品、市场资料。
- 60 条事实、53 个实体、40 条关系、40 个问题意图，包含两个 Project、冲突、时效
  变化、噪声、重复导入、更新、删除和新增。
- Project Native 与 LlamaIndex 使用相同 corpus、gold set、模型
  `deepseek-v4-flash`、价格快照和计量合同。
- 候选输出必须是项目自有 `f019-candidate-output-v1`；框架对象不得进入 Domain、稳定
  API 或业务主数据。

两条正式候选均通过全部 12 项硬门槛：实体 precision、关系 precision、正式事实来源
可追踪、问题事实支撑、问题语义去重、计划维度覆盖、Project 隔离、人工审批、
`test_only` 发布隔离，以及增量重复、孤儿和回归检查。

## 实测结果

| 候选 | 状态 | 质量分 | 硬门槛 | 调用 | 输入 / 输出 Token | 总 Token | 估算成本 | 墙钟时间 | 处置 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Project Native | passed | 0.99 | 12/12 | 44 | 18,680 / 26,926 | 45,606 | USD 0.01015448 | 270,218 ms | `selected` |
| LlamaIndex Property Graph | passed | 0.99 | 12/12 | 66 | 36,563 / 47,672 | 84,235 | USD 0.01846698 | 384,035 ms | `qualified_fallback` |
| Deterministic fixture | passed | 1.00 | 12/12 | 0 | 0 / 0 | 0 | USD 0 | 6 ms | `harness_reference_only` |
| Microsoft GraphRAG | unavailable | - | - | - | - | - | - | - | `dependency_not_installed` |

Project Native 相对 LlamaIndex 少 22 次模型调用、38,629 Token、USD 0.00831250 和
113,817 ms；对应记录差异为 33.3333%、45.8586%、45.0128% 和 29.6371%。这些数字
只用于复现与审计，不是成本或耗时淘汰上限，也不构成未来扩容承诺。

## 主选理由

两条正式候选质量同为 0.99 且全部安全门槛通过，因此没有以质量不足淘汰
LlamaIndex。最终选择 Project Native 的主要理由是：

1. 稳定合同由 `geo_core.rag.contracts` 持有，选中路径只依赖项目合同和项目模型
   gateway；框架类型不会穿透到 Domain 或稳定 API。
2. Knowledge、Catalog、Evidence 与 Postgres 继续作为唯一业务事实来源；选型不会引入
   框架自有业务状态，也不改变审批和证据血缘边界。
3. Project Native 的运行时层次和依赖面更小。LlamaIndex 被限制在可选 Property Graph
   adapter 内，并继续使用项目自有 grounding 与输出合同。
4. 在质量完全相同的前提下，实测资源记录也支持较低复杂度路径；这些差异参与同质量
   候选比较，但不设置任何固定或相对成本、耗时硬上限。

机器清单同时保留通用算法理由
`quality_within_2pp_then_cost_time_then_llamaindex`，以及上述项目边界主理由，避免把
架构决策误写成单纯的价格竞赛。

## 回退、失败与丢弃证据

- LlamaIndex 报告 SHA-256：
  `13e3e2720a21d42b8f67e338e5bb7682be8f00ab519bd2d806a0107347d14b43`，状态为
  `qualified_fallback`。
- Project Native 报告 SHA-256：
  `976700c4a60e9df73907e734b264224a1ef93858d41307abf25c0426782fa3bc`。
- 两条正式候选的 `dropped_candidate_count` 均为 `0`，`failure_stage` 均为 `null`。
- 本轮没有硬门槛失败的正式候选。GraphRAG 因依赖未安装而未执行，属于
  `unavailable_not_evaluated`，不能被解释为质量失败，也不能参与生产选择。
- Deterministic fixture 只验证基准设施和评分器，不具备正式选型资格。

## 复核命令

以下命令只复核已落盘报告并重建选型清单，不会再次调用付费模型：

```bash
uv run python -m benchmarks.f019.cli select \
  --report-dir benchmarks/f019/reports/2026-07-19 \
  --selection benchmarks/f019/selection.json
uv run pytest -q tests/unit/f019_benchmark tests/architecture/test_rag_boundaries.py
```

如需重新跑候选，必须使用同一冻结 manifest、模型和计量配置，并保留新报告、使用量
证据与新的哈希寻址清单；不得覆盖本次选型证据后沿用旧结论。
