# F-019 隔离选型基准

本目录只用于批次 1 的选型 Gate 准备，不读写产品数据库，也不代表 F-019
生产功能或框架选型已经完成。语料是中文合成资料及其规范化文本表示；`source_format`
保留原始 HTML、PDF、DOCX、纯文本类型，基准本身不测试文件解析器。

离线校验和确定性基线：

```bash
python -m benchmarks.f019.cli validate
python -m benchmarks.f019.cli run --adapter deterministic --output /tmp/f019-baseline.json
```

LlamaIndex 与 GraphRAG 入口只做隔离依赖探测。在依赖或项目自有执行器未配置时，命令以
`unavailable` 结束且不产生分数。GraphRAG 仅允许隔离对比。框架执行器必须把结果转换为
`f019-candidate-output-v1`，不能把框架对象写入业务主数据或稳定 API。

确定性基线使用资料中的结构化“事实/实体/关系”段验证评分器、增量审计和安全 Gate。
即使它通过 Gate，也只证明 harness 与这套结构化 fixture 可工作；它被标记为
`eligible_for_selection=false`，不能据此宣称完成正式框架选型。

成本、Token、模型调用数和墙钟时间必须如实记录，但没有固定或相对基线硬上限。候选先
通过全部质量与安全硬门槛；质量差距小于 2 个百分点时才依次比较成本、耗时，仍相同时
优先 LlamaIndex。
