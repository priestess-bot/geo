# 架构图

> **范围说明**：当前仓库本身是文档与规划项目（仓库目录结构见 [README](README.md)）。本文件画的是**规划中要构建的 GENO SaaS 澳大利亚首发系统架构**，源自规格 [docs/GENO-SaaS-AU-首发技术落地路径.md](docs/GENO-SaaS-AU-首发技术落地路径.md) 第 3 章，落地节奏见 [PROJECT-PLAN.md](PROJECT-PLAN.md)。
>
> 三张图：① 分层系统架构（静态结构）· ② 可插拔点（开源优先·可替换）· ③ 证据优先数据流水线（运行时）。Mermaid 在 GitHub / GitLab / VS Code 等可直接渲染。
>
> 📐 **出版级图注与设计规范**（配色 / 形状 / 线型 / 栏宽 / 逐图坐标，可据此产出 TikZ / SVG 矢量图）见 [docs/figure-specs.md](docs/figure-specs.md)。

## 1. 分层系统架构

三条硬约束在图中的体现：**开源优先**（基础设施全部开源自托管）、**松耦合**（上层只依赖下层接口、模块间走数据契约）、**可插拔**（带 `«接口»` 的模块其后端可替换，见图 2）。同时，P0a 开始就把 `AuditEvent`、`EvidenceLink`、`ScoreContribution`、`ReportExport` 作为跨模块数据契约，保证可审计、可溯源、可解释。

```mermaid
flowchart TB
  subgraph L1["① 控制台层"]
    UI["Next.js 控制台<br/>项目·问题·证据·报告·任务"]
  end
  subgraph L2["② 应用服务层 · FastAPI"]
    ORCH["编排：项目 / 评分 / 报告 / 复测"]
    WRK["采集·分析 Worker（与主服务隔离）"]
  end
  subgraph L3["③ 能力模块层（接口契约 · 松耦合 · 可插拔）"]
    COL["Collector<br/>«CollectorBackend»"]
    EVI["EvidenceStore"]
    PAR["Parser<br/>«ParserEngine»"]
    SCO["ScoringEngine<br/>«ScoringFormula»"]
    EXP["ExplanationBundle<br/>ScoreContribution"]
    CIT["CitationGraph<br/>«GraphStore»"]
    BEN["CompetitorBenchmark"]
    ACT["ActionPlanner"]
    REP["ReportExporter"]
    AUD["Audit / Provenance<br/>AuditEvent · EvidenceLink"]
    LLM["«LLMGateway»"]
    GEO["«GeoProvider»"]
  end
  subgraph L4["④ 基础设施层（开源 · 自托管）"]
    PG[("PostgreSQL + pgvector")]
    CH[("ClickHouse")]
    OBJ[("MinIO 对象存储")]
    GR[("PG 邻接表 / Neo4j")]
    TMP[["Temporal 调度"]]
    OBS["Langfuse / promptfoo<br/>观测·评测"]
  end

  UI --> ORCH
  ORCH --> COL & PAR & SCO & CIT & BEN & ACT & REP & AUD
  COL --> WRK
  WRK --> GEO
  COL --> EVI
  COL --> LLM
  PAR --> LLM
  ACT --> LLM
  EVI --> PG & OBJ & CH
  PAR --> PG
  SCO --> PG
  SCO --> EXP
  EXP --> REP
  CIT --> GR
  COL --> AUD
  PAR --> AUD
  SCO --> AUD
  CIT --> AUD
  BEN --> AUD
  REP --> AUD
  AUD --> PG & CH
  REP --> OBJ
  LLM --> OBS
  ORCH --> TMP
```

层与里程碑对应：能力模块层逐个由 [PROJECT-PLAN](PROJECT-PLAN.md) 的 M0（接口与底座）→ M5 落地；基础设施层在 M0 一键起服。

## 2. 可插拔点（开源优先 · 可替换）

左侧是先定义、后实现的**接口契约**；右侧是可替换实现。换实现时只新增一个适配器，不动业务代码（对应 PROJECT-PLAN 的「架构验收门槛」）。

```mermaid
flowchart LR
  CB["«CollectorBackend»"] --> CBi["Perplexity API · ChatGPT API<br/>Google AIO 浏览器/第三方 · SearXNG · 人工补录"]
  VS["«VectorStore»"] --> VSi["pgvector ➜ Qdrant / Milvus"]
  GS["«GraphStore»"] --> GSi["PG 邻接表 ➜ Neo4j / Apache Jena"]
  LG["«LLMGateway»"] --> LGi["LiteLLM ➜ 任意模型供应商 / vLLM 自托管"]
  PE["«ParserEngine»"] --> PEi["规则解析 ⇄ LLM-as-judge（可 A/B）"]
  SF["«ScoringFormula»"] --> SFi["au_visibility_v1 ➜ v2…（版本化，旧分可重算）"]
  GP["«GeoProvider»"] --> GPi["uule 参数 / 代理池 / 第三方供应商"]
  RE["«ReportExporter»"] --> REi["模板引擎 / Metabase（PDF · CSV）<br/>冻结 ReportExport 快照"]
  DC["跨模块数据契约<br/>AuditEvent · EvidenceLink · ScoreContribution · ReportExport"]
  CB -. must write .-> DC
  PE -. must write .-> DC
  SF -. must write .-> DC
  RE -. must write .-> DC
```

## 3. 证据优先数据流水线（运行时）

平台**评分权重**（Google 45 / ChatGPT 30 / Perplexity 25）与**采集构建顺序**（Perplexity 最易先建、Google AIO 最难当 spike）是两回事；下图是数据流，不是构建序。

```mermaid
flowchart LR
  MP["AU MarketProfile<br/>+ IndustryProfile"] --> PP["Prompt Pack<br/>100 条 × k=3"]
  PP --> RUN["AI Answer Runner<br/>可插拔采集"]
  RUN --> EV[("Raw Evidence Store<br/>AnswerRun·RawAnswer·Citation<br/>截图·HTML·hash·answer_present")]
  EV --> PS["Answer Parser<br/>提及/推荐/排名/竞品/本地相关性"]
  PS --> SC["AUVisibilityScore<br/>au_visibility_v1 · 双分母"]
  SC --> EX["ScoreContribution<br/>权重 · 分母 · 正负证据"]
  EV --> CG["Citation Graph<br/>source gap"]
  EV --> AU[("Audit / Provenance<br/>AuditEvent · EvidenceLink")]
  PS --> AU
  CG --> AU
  SC --> AU
  SC --> CB["Competitor<br/>Benchmark"]
  CG --> CB
  CB --> AP["Action Plan"]
  EX --> RPT["Evidence Report<br/>PDF / CSV<br/>审计摘要 · 分数解释包"]
  CG --> RPT
  CB --> RPT
  AP --> RPT
  AU --> RPT
  RPT --> RX[("ReportExport<br/>不可覆盖版本快照")]
  RX --> RC["复测<br/>T+7 / 14 / 30"]
  RC -. 同口径回采 .-> RUN
```

阶段与里程碑对应：MarketProfile/Prompt Pack → M1，Runner/Evidence/Audit 基础 → M2a，Parser/Score/ScoreContribution → M3，Citation/Benchmark → M4，ReportExport → M5，Action/复测 → M6。

## 4. 关键约束（图背后的规则）

- **依赖方向单向向下**：上层只依赖下层暴露的接口，不依赖其实现。
- **模块间走数据契约**：稳定的表结构/事件结构，不共享内部对象。
- **采集隔离**：采集 Worker 与主服务分进程，避免脆弱的浏览器自动化拖垮全局。
- **采集两大保真度问题原生处理**：API ≠ 消费者界面（抽检差异）；Google AIO 选择性触发（`answer_present` 双分母）。
- **审计/溯源/解释不可后补**：采集、解析、评分、人工补录、实体确认、报告导出必须写 `AuditEvent`；报告数值必须通过 `ReportExport -> VisibilityScoreSnapshot -> ScoreContribution -> AnswerAnalysis -> AnswerRun` 追溯；分数必须展示权重、分母、证据和局限。
- **开源优先但接口前置**：MVP 能一个组件覆盖就不引第二个（向量先 pgvector、图先 PG 邻接表），但接口按"将来要换"设计。
