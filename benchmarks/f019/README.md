# F-019 隔离选型基准

本目录保存 F-019 的冻结选型数据、真实候选报告和 hash-addressed 正式选择。当前选择
`project-native-rag-v1`；`llamaindex-property-graph-v1` 使用同一 corpus/gold/model
通过全部 Gate，保留为必须重新选型才能启用的合格回退。GraphRAG 仍只允许隔离对比。

语料是中文合成资料及其规范化文本表示；`source_format` 保留原始 HTML、PDF、DOCX、
纯文本类型，基准本身不测试文件解析器，也不读写产品数据库。

离线校验和确定性基线：

```bash
uv run python -m benchmarks.f019.cli validate
uv run python -m benchmarks.f019.cli run --adapter deterministic \
  --output /tmp/f019-baseline.json
uv run python -m benchmarks.f019.cli verify-selection
```

最后一条命令只读取 `selection.json` 及其所选报告，校验 SHA-256、数据集版本和全部硬
门槛，不会调用付费模型。已落盘报告位于 `reports/2026-07-19/`。

LlamaIndex 的固定可选依赖为 `llama-index-core==0.14.23`。重跑正式候选必须显式安装
`f019-rag` extra、提供 DeepSeek key file，并保存一套新的报告与选择清单：

```bash
uv run --extra f019-rag python -m benchmarks.f019.cli suite \
  --output-dir /tmp/f019-reports \
  --selection /tmp/f019-selection.json \
  --deepseek-key-file /run/secrets/deepseek_api_key
```

依赖、执行器或 key 未配置时，相关候选以 `unavailable` 结束且不产生伪造分数。所有框架
结果必须转换为 `f019-candidate-output-v1`，不能把框架对象写入业务主数据或稳定 API。

确定性基线使用资料中的结构化“事实/实体/关系”段验证评分器、增量审计和安全 Gate。
即使它通过 Gate，也只证明 harness 与这套结构化 fixture 可工作；它被标记为
`eligible_for_selection=false`，不参与生产选择。

成本、Token、模型调用数和墙钟时间必须如实记录，但没有固定或相对基线硬上限。候选先
通过全部质量与安全硬门槛；质量差距小于 2 个百分点时才依次比较成本、耗时，仍相同时
优先 LlamaIndex。

正式结果、调用数、Token、成本、耗时、候选丢弃证据和主选理由见
`docs/engineering/F019-rag-selection-gate-2026-07-19.md`。
