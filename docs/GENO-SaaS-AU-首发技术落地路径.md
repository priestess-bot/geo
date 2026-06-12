# GENO SaaS 澳大利亚首发技术落地路径

版本日期：2026-06-09

## 1. 核心判断

澳大利亚首发不复制完整 GENO 闭环，也不优先做内容生成、自动分发或多模态资产，而是先做一个 **Evidence-first AI Search Visibility MVP**：

> 先证明 AI 如何看见品牌、引用哪些来源、推荐哪些竞品、哪些澳洲本地信源缺失，再把证据转成可执行任务和复测报告。

原因：

- 澳大利亚是 Google 强势市场，Google Search / AI Overviews / AI Mode 必须优先监测。
- 澳大利亚客户更容易接受可审计报告、原始证据、引用来源和行动清单，不容易接受黑箱"投喂大模型"。
- Semrush、Ahrefs、HubSpot 等 SEO 工具会是强竞品，单纯做一个 AI visibility 分数不够，需要把 raw evidence、citation graph 和 agency report 做深。
- 一期最重要的是建立数据口径、采样方法和客户信任，而不是先追求自动化内容生产。

因此，澳洲首发主流程从原来的：

```text
项目配置 -> 问题集 -> AI回答采集 -> 可见性评分 -> 知识库 -> 内容生成审核 -> 分发记录 -> 报表预警
```

调整为：

```text
AU Market Profile
  -> ICP/行业 Prompt Pack
  -> AI Answer Runner
  -> Raw Evidence Store
  -> Answer Parser
  -> Citation Graph
  -> Visibility Score
  -> Competitor Benchmark
  -> Action Plan
  -> Evidence Report Export
  -> 7/14/30 天复测
  -> P2 Content Engine / Integrations
```

这不是放弃 GENO 闭环，而是把闭环拆成更容易落地和验收的顺序：

```text
证据 -> 信源图谱 -> 竞品差距 -> 行动建议 -> 报告 -> 复测 -> 内容和分发自动化
```

### 1.1 工程取向：三条架构硬约束

本次 MVP 在工程实现上明确三条硬约束，贯穿全文（详见第 3 章）：

1. **开源优先**：每一个能力优先采用成熟、可自托管的开源组件，避免一开始被单一商业 SaaS 或单一模型供应商锁定。
2. **模块化、松耦合**：采集、存储、解析、评分、信源图谱、报告各自是独立模块，模块之间只通过明确的接口契约和数据契约通信，不互相反向依赖内部实现。
3. **可插拔替换**：任一采集后端、向量库、图数据库、LLM 供应商、解析器、评分公式，都可以在不改动其他模块业务代码的前提下替换或并存。

### 1.2 两个必须正视的现实

- **采集是第一难题，不是附属字段。** 这类产品的真正壁垒在"能不能稳定、保真地把 AI 答案采到手"，而不在采到之后的解析和出图。两个具体问题必须在架构层解决：一是 **API 返回的答案不保证与真实用户在消费者界面看到的一致**（保真度缺口）；二是 **Google AI Overviews 是选择性触发的**，很多 prompt 根本不触发 AIO，"没触发"和"触发了但没提品牌"是两种完全不同的状态。这两点直接决定评分是否可信，必须在采集和数据模型里原生处理（见第 3、5、8 章）。
- **数据规模这一仗打不赢 Semrush/Ahrefs，护城河得换地方。** 它们已有亿级 prompt 库和澳洲区域数据，一个几百条 prompt 的 MVP 在"AI 可见性分数"广度上无法对抗。差异化必须押在它们做不深的地方：可点回原始回答的证据链、澳洲本地 citation graph 与信源图谱、代理商白标工作流、以及可解释可复盘的口径。这是产品定位，也是下面所有取舍的前提。

### 1.3 可行性修正：P0 分级交付，而不是一个大爆炸 P0

澳洲首发仍然把 Google AI Overviews / AI Mode 作为最高权重目标面，但工程上不能让 Google 采集阻塞整个 MVP。P0 拆成三层：

| 层级 | 目标 | 交付状态 | 失败时处理 |
| --- | --- | --- | --- |
| **P0a Stable Evidence Chain** | 先用稳定 API 平台跑通证据链：Perplexity Sonar、OpenAI web search、Raw Evidence Store、Parser、Score、基础报告 | 内部 demo / design partner 试点必须达成 | 无降级，未达成则不能进入客户试点 |
| **P0b Google High-risk Spike** | 独立验证 Google AIO / AI Mode 的浏览器采集、第三方 SERP 供应商、人工补录三条路径 | P0 高权重 spike，必须有结论 | 若未过健康闸门，Google 以抽样附录/第三方/人工补录交付，不阻塞 P0a/P0c |
| **P0c Customer Evidence Report** | 把 P0a 证据和 P0b 结论组合成可售报告：Citation Graph、Competitor Benchmark、PDF/CSV、方法说明 | 可售 MVP 必须达成 | Google 覆盖范围在方法说明里明确标注，不把未稳定的 Google 数据混入同一分母 |

因此，**平台权重、产品重要性、工程构建顺序是三件事**：

- 权重上：Google 仍然最高，决定报告解读和后续投入优先级。
- 构建上：先做 Perplexity / OpenAI API，保证证据链和报告链路可交付。
- 风险上：Google AIO / AI Mode 用限时 spike 和健康闸门管理，过闸后再进入全量 P0 评分。

## 2. 一期产品定位

一期产品定位为：

> 面向澳大利亚品牌和代理商的 AI Search Visibility & GEO Evidence Platform。

核心交付物不是"自动生成一堆内容"，而是一份可审计 AI 可见性报告：

- AI 是否提到品牌。
- AI 是否推荐品牌。
- 品牌在推荐列表中的位置。
- AI 是否引用品牌官网或澳洲本地信源。
- AI 引用了哪些竞品信源。
- 竞品在哪些 prompt/topic/source 上压制品牌。
- 品牌事实是否缺少澳洲本地化信息。
- 下一步需要修补哪些网页、FAQ、Schema、评价源、对比页、本地媒体或行业目录。
- 发布或修补后，7/14/30 天是否发生变化。

## 3. 架构原则与开源技术选型（模块化·松耦合·可插拔）

本章是本次 MVP 的工程主线。后面的 Step、数据模型、验收标准都以本章定义的接口和选型为准。

### 3.1 分层与模块边界

```text
控制台层      Next.js 控制台（项目/问题/证据/报告/任务）
应用服务层    FastAPI：项目编排、评分编排、报告编排、任务编排
能力模块层    Collector | EvidenceStore | Parser | CitationGraph
              | ScoringEngine | CompetitorBenchmark | ActionPlanner | ReportExporter
基础设施层    关系库 | 向量库 | 图库 | 指标库 | 对象存储 | 任务编排 | LLM 网关 | 观测评测
```

模块边界规则：

- 上层只依赖下层暴露的**接口**，不依赖其实现。例如评分引擎只读 `EvidenceStore` 的数据契约，不关心答案是 Playwright 采的还是官方 API 采的。
- 模块之间用**数据契约**（稳定的表结构/事件结构）通信，不共享内部对象。
- 采集层与主业务进程隔离（独立 worker），避免一个脆弱的浏览器自动化拖垮整个服务。

### 3.2 接口契约（必须先定义，再写实现）

采集后端统一接口，使任意平台/任意采集方式都能挂进来：

```text
CollectorBackend（接口）
  id() -> str                      # 如 google_aio.playwright / perplexity.sonar
  capabilities() -> {
    platform, surface,             # google_aio | google_ai_mode | chatgpt | perplexity ...
    supports_geo,                  # 是否支持城市级地理
    supports_citation,             # 是否返回引用链接
    access_method                  # browser | official_api | third_party_api | manual
  }
  collect(prompt, market, city, language, device) -> RawCollectResult
  health() -> status

RawCollectResult（数据契约）
  answer_present        # 关键：该界面/答案是否出现（AIO 是否触发）
  surface_triggered     # 目标生成式界面是否被触发
  answer_text
  citations[]           # url, domain, position
  screenshot, html_snapshot, raw_payload
  model_or_surface, account_state, collector_version
```

其他需要先定义接口、后填实现的可插拔点：

```text
LLMGateway       chat()/embed()，统一多模型，路由/重试/成本/日志；P0a 先用 FixtureLLMGateway 写 llm_call_logs，LiteLLMGateway adapter 已支持 OpenAI-compatible /chat/completions 与 /embeddings，chat 路径具备 retry/backoff、失败调用审计和上游响应 cost 读取；infra 已提供可选 `llm-gateway` Compose profile、`litellm` proxy config 与 `collector-worker-litellm`，真实 provider key 联调后可切换
ParserEngine     parse_record(RawEvidenceRecord, BrandEntity, competitors, entity_aliases) -> AnswerAnalysis（实现：规则 + LLM-as-judge，二者可切换/并存）
VectorStore      upsert()/search()（实现：pgvector / Qdrant / Milvus）
GraphStore       upsert_node()/query()（实现：Neo4j / Apache Jena / 纯 SQL 邻接表）
GeoProvider      resolve(city) -> 地理参数/出口（实现：uule 参数 / 代理池 / 第三方供应商，见 Step 6）
ScoringFormula   score_analysis()/score_analyses() -> VisibilityScoreSnapshot + ScoreContribution + AuditEvent（公式版本化，可整体替换，见 Step 9）
ReportExporter   export(snapshot, contributions, records, graph, method) -> Markdown/PDF/CSV + ReportExport（实现：模板引擎 / Metabase 导出）
```

P0a 这四个主链路接口必须是可测试的运行时契约，而不是仅保留文档名。工程实现要求：

- `CollectorBackend / ParserEngine / ScoringFormula / ReportExporter` 使用 runtime-checkable Protocol 对齐真实调用签名。
- 每个接口都有 `NotConfigured*` stub，能暴露 id/version/health 等元信息，业务调用时明确失败，避免静默落空。
- 每个接口至少有一个工作实现进入合约测试：fixture collector、rule/comparative parser、registry scoring formula、Markdown/PDF/CSV report exporter。
- 合约测试必须证明 stub 和工作实现都满足同一接口，且工作实现可以串起 evidence -> analysis -> score -> report。
- 运行时服务必须区分 liveness 与 readiness：`/health` 只证明 API 进程响应，`/ready` 至少验证 PostgreSQL 可用；`/v1/runtime-diagnostics` 暴露 database/object_store/runtime_auth 的配置诊断、连接池快照和 JWT/JWKS/access-control 状态。对象存储诊断默认只检查配置完整性，不主动写对象，避免健康检查产生副作用。
- 运行时可观测性先落轻量 Prometheus 文本格式 `/metrics` 与结构化 access log：按 route template 记录请求总量、状态码、请求延迟 histogram，并暴露 runtime PostgreSQL connection pool enabled/max size/timeout/created/available gauge；`/metrics` 自身不计入请求指标。API 对每个非 `/metrics` 请求回传 `X-GENO-Request-Id`，接受调用方传入的安全 request id 或自动生成 32 位 hex id，并向 `geno_api.access` 输出 `runtime_api_request` JSON 日志，记录 request id、method、path、route、status、duration_ms 和 client_host；日志不写 query string。工程已提供可选 `observability` Compose profile：Prometheus 抓取 `api:8000/metrics`，Grafana 自动 provision `GENO Prometheus` datasource，便于本地试点观察请求量、状态码、延迟和连接池状态。完整 OpenTelemetry、集中式日志采集、慢查询追踪、生产 dashboard、告警订阅和 SLO 仍是生产化后续项。

### 3.3 开源优先选型映射

| 能力 | 模块/接口 | 开源优先选型 | 可替换后端 |
| --- | --- | --- | --- |
| 控制台前端 | 控制台层 | Next.js | 任意 SPA 框架 |
| 应用服务/API | 应用服务层 | FastAPI + OpenAPI | NestJS |
| 主数据/多租户 | 关系库 | PostgreSQL（+ RLS） | 任意兼容 PG 的库 |
| 向量检索 | VectorStore | pgvector（起步，少引一个组件） | Qdrant、Milvus |
| 信源/知识图谱 | GraphStore | 起步用 PostgreSQL 邻接表 | Neo4j、Apache Jena、RDFLib |
| 指标事件 | 指标库 | ClickHouse | DuckDB（小规模）、PG 分区表 |
| 对象存储 | 对象存储 | MinIO（S3 兼容） | 任意 S3 兼容存储 |
| 网页/AI 界面采集 | CollectorBackend | Playwright、Crawlee、Scrapy | 第三方 SERP/AI-answer API |
| 传统结果基线 | CollectorBackend | SearXNG、SerpBear | 商业 SERP API |
| LLM 统一网关 | LLMGateway | LiteLLM | 直连各家 SDK |
| 自托管模型（降本期） | LLMGateway | vLLM / Ollama + Qwen/DeepSeek | 商业 API |
| RAG/编排 | Parser/Planner | LlamaIndex、LangChain | 自写最小编排 |
| NLP/实体/聚类 | ParserEngine | spaCy、Sentence-Transformers、BERTopic、KeyBERT | scikit-learn 流水线 |
| Prompt 追踪/评测 | 观测评测 | Langfuse、promptfoo、Ragas | OpenTelemetry + 自建评测集 |
| 任务编排/复测调度 | 任务编排 | Temporal、Airflow、n8n | Celery/RQ + cron |
| 看板/报表 | ReportExporter | Metabase、Grafana、Superset | 自写报表 + 模板 |
| 身份/多租户认证 | 基础设施 | Keycloak/OIDC + PG RLS | 自建 header/HS256 JWT/inline/remote/OIDC-discovered JWKS RS256 |
| 容器与部署 | 基础设施 | Docker Compose 起步 → K8s | 单机 systemd |

> 选型纪律：MVP 阶段能用一个组件覆盖就不引第二个（如向量先用 pgvector、图先用 PG 邻接表）；但**接口必须按"将来要换"来设计**，这样换 Qdrant、换 Neo4j、换第三方采集后端时只新增一个适配器实现，不动业务代码。许可证（如 MinIO AGPLv3、Redis/Valkey、n8n 商用条款）在选定时逐项核查。

工程当前已先落一层默认关闭的 API 级运行时项目访问控制，用于补齐澳洲首发的最小多客户隔离验证：设置 `GENO_RUNTIME_PROJECT_ACCESS_CONTROL=1` 后，runtime API 要求可信 actor；默认 demo 模式从 `X-GENO-Actor-Id` 读取，设置 `GENO_RUNTIME_AUTH_MODE=jwt` 后则要求 `Authorization: Bearer <JWT>`，用 `GENO_RUNTIME_JWT_SECRET` 校验 HS256 签名；设置 `GENO_RUNTIME_AUTH_MODE=jwks` 后会优先用 `GENO_RUNTIME_JWKS_JSON` inline JWKS 校验 RS256，也可从 `GENO_RUNTIME_JWKS_URL` 拉取远端 JWKS，并按 `GENO_RUNTIME_JWKS_CACHE_TTL_SECONDS` 缓存，拉取超时由 `GENO_RUNTIME_JWKS_FETCH_TIMEOUT_SECONDS` 控制；若未配置显式 JWKS URL，可通过 `GENO_RUNTIME_OIDC_DISCOVERY_URL` 或 URL-form `GENO_RUNTIME_JWT_ISSUER` 拉取 OIDC discovery document 并发现 `jwks_uri`，discovery document 按 `GENO_RUNTIME_OIDC_DISCOVERY_CACHE_TTL_SECONDS` 缓存；生产兜底默认关闭，只有显式设置 `GENO_RUNTIME_JWKS_STALE_IF_ERROR_SECONDS` 或 `GENO_RUNTIME_OIDC_DISCOVERY_STALE_IF_ERROR_SECONDS` 为正数时，远端 refresh 失败才会在对应 stale 窗口内继续使用同 URL 的过期缓存；两类 JWT 模式都会从 `sub` 或 `GENO_RUNTIME_JWT_ACTOR_CLAIM` 解析 actor，并支持 issuer、audience 和 clock skew 校验。项目列表按 `project_members.user_id` 过滤，项目创建把当前 actor 写为 owner/member，项目级读接口必须带 `project_id` 并校验 actor 是项目成员；报告 artifact、traceability、fidelity trend/check 和 alias confirm 这类对象级入口会先从 `report_exports` 或品牌/竞品实体反查所属项目再校验。成员管理也已落到最小可审计路径：`GET /v1/project-members/runtime?project_id=...` 读取成员和审计历史，`POST /v1/project-members/runtime` 按 `project_id + user_id` 幂等 upsert `owner/admin/analyst/viewer` 角色并写入 `project_member_saved` 审计事件，`DELETE /v1/project-members/runtime` 删除成员并写入 `project_member_deleted` 审计事件，repository 会阻止删除或降级最后一个 owner，Runtime Console 的 Project Members 面板可展示、维护和删除这些成员。API 层最小角色矩阵已落：owner/admin 可执行成员维护、prompt 导入、saved view 保存、Brand Kit/Logo 和 Score Weights 等管理写操作；owner/admin/analyst 可执行 entity alias confirm、manual backfill、human review、fidelity check 等分析复核写操作；viewer 只读。数据库层已接入 `0010_runtime_project_rls`：迁移创建 `geno_runtime_app` 非 bypass runtime role，给 projects/project_members/证据/评分/报告/图谱/content/audit 等项目级表启用 RLS，并通过 `geno.runtime_project_access_control`、`geno.runtime_actor_id`、`geno.runtime_project_id` 三个 session GUC 执行项目隔离；API 在成员校验通过后写入该上下文。常驻 API 服务通过 `GENO_RUNTIME_DB_POOL_ENABLED=1` 默认启用进程内 PostgreSQL connection pool，连接归还时会 rollback、清空上述 RLS session GUC 并提交清理，避免同一连接被下个请求复用时带出前一个 actor/project；worker、scheduler 和 runtime E2E 默认保持短生命周期直连。runtime E2E 已验证 actor 只能看到自己所属项目。该层是 MVP 门禁和可审计隔离证明，不替代 Keycloak/OIDC login/session、前端 SSO 登录流、成员邀请、真实用户目录、客户授权流转、生产压测或账单隔离。

工程门禁已从单一 Python contract 扩展为本地/CI 同构验证：本地 `make ci-local` 与 GitHub Actions `contracts-and-runtime` 会执行 `make quality`、`make test`、`make web-build`、默认/LLM/scheduler/observability/db-smoke Compose config 校验、`make db-smoke` 和 `make runtime-e2e`。其中 `make quality` 覆盖 Ruff Python lint、Python compileall 和 Runtime Console TypeScript `tsc --noEmit`；`make db-smoke` 用临时 PostgreSQL 新卷执行全部 `infra/db/migrations/up/`，检查扩展、核心表/关键列、runtime role、RLS helper/policy，并证明 `geno_runtime_app` 开启 `geno.runtime_*` GUC 后只能读取授权项目。这证明当前代码在无真实外部 provider key 的 fixture、Postgres 和 MinIO 环境下可静态检查、可构建、可解析部署配置、可迁移起干净 schema、可写入审计链/解释链、可归档报告 artifact，并可验证项目级 RLS 隔离；但它仍不替代真实 Perplexity/OpenAI/Google provider E2E、生产发布迁移策略、压测和发布流水线。

### 3.4 必须可插拔的关键点清单

| 可插拔点 | 为什么必须能换 | 验收方式 |
| --- | --- | --- |
| 采集后端（每个平台） | 平台改版/失效时要能换实现或换供应商而不停服 | 同一平台至少跑通"开源自建"和"官方/第三方 API"两种后端 |
| 向量库 | 规模增长后可从 pgvector 迁 Qdrant/Milvus | 切换后端，检索结果一致性可回归；当前已用本地 pgvector projection 与 Qdrant projection 做 VectorStore contract 验证，真实 Qdrant/Milvus service/driver 联调后补 |
| 图库 | 关系复杂度上来后从 SQL 邻接表迁 Neo4j | 切换后端，citation graph 查询不变；当前已用本地 PG adjacency projection 与 Neo4j node/relation projection 做 GraphStore contract 验证，真实 Neo4j driver/container 联调后补 |
| LLM 供应商/模型 | 成本/质量/可用性变化时切换 | 通过 LiteLLM 切换供应商，解析与生成不改 |
| 解析器实现 | 规则与 LLM 判定要能 A/B 和回退 | 同一答案两种解析器可对比，保留版本 |
| 评分公式 | 公式要随校准迭代且可复现历史 | 公式版本化，历史分数按旧版本可重算 |

## 4. MVP 范围分层

### 4.1 P0：必须做（分级交付）

| 层级 | 模块 | 目标 |
| --- | --- | --- |
| P0a | AU Market Profile | 固定澳大利亚市场配置、平台权重、语言、城市和信源分类 |
| P0a | Prompt Pack | 生成 100 条澳洲英文问题集（上限 200），覆盖品牌、品类、竞品、口碑、价格、本地服务 |
| P0a | AI Answer Runner（API-first） | 先跑通 Perplexity Sonar 与 OpenAI web search 两个稳定 API 后端，打通 answer/citation/evidence 全链路 |
| P0a | Raw Evidence Store | 保存 prompt、平台、城市、时间、原始回答、引用 URL、截图/HTML 快照、是否触发、采样序号 |
| P0a | Audit & Provenance Trail | 记录采集、解析、评分、人工修正、报告导出的审计事件；建立报告数值到原始证据的可追溯关系 |
| P0a | Answer Parser | 解析品牌提及、推荐、排名、竞品、引用、情绪和本地相关性 |
| P0a | Visibility Score | 计算可解释、公式版本化的 AU Visibility Score，支持拆分指标和双分母 |
| P0b | Google AIO / AI Mode Spike | 独立验证 Google AIO / AI Mode 的浏览器采集、第三方 SERP API、人工补录路径，并输出健康闸门结论 |
| P0c | Citation Graph | 统计 AI 引用源、竞品来源、source type、topic 和本地权重 |
| P0c | Competitor Benchmark | 对比 3-5 个竞品的提及、推荐、引用和 source overlap |
| P0c | Evidence Report Export | 输出客户可审计报告，支持 PDF/CSV，明确披露平台覆盖、采样量、Google spike 结果、降级口径和分数解释包 |

P0b 不是 P1，也不是可忽略功能。它是 P0 内的高风险技术验证，但其验收方式是"限时出结论 + 可降级交付"，不是"必须全量稳定后才能发布 P0a/P0c"。

### 4.2 P1：第二阶段做

| 模块 | 目标 |
| --- | --- |
| Action Plan | 把证据和信源缺口转成可执行任务 |
| Localized Knowledge Facts | 维护澳洲本地品牌事实、价格、配送、服务、城市覆盖和证据 URL |
| Agency Workflow | 多客户、多项目、白标报告、任务 owner 和复测窗口 |
| 7/14/30 天复测 | 发布前后窗口对比，展示指标变化和原始证据 |
| Manual Distribution Record | 只记录人工发布 URL 和状态，不做自动发布 |

### 4.3 P2：验证市场后再做

| 模块 | 目标 |
| --- | --- |
| Content Engine | 基于 prompt gap、source gap 和知识库事实生成 FAQ、comparison、schema、landing page outline |
| Integrations | GA4、Google Search Console、Shopify、WordPress、Webflow、HubSpot、Cloudflare |
| Broader Platform Coverage | Gemini、Bing Copilot、Claude、YouTube、Reddit、ProductReview 深度采集 |
| Workflow Automation | 自动创建 CMS 草稿、自动提醒、自动复测、API 输出 |
| Multi-market Expansion | 从 AU 扩展到 NZ、UK、US、SG 等英语市场 |

## 5. Step-by-step 实施方案

### Step 1：建立 AU Market Profile

新增 `MarketProfile = AU`，把澳洲市场配置从业务逻辑中抽离出来。

市场配置（固定值）：

```text
market: Australia
market_code: AU
locale: en-AU
timezone: Australia/Sydney
currency: AUD
primary_language: Australian English
cities: Australia, Sydney, Melbourne, Brisbane, Perth, Adelaide
```

P0 AI 平台配置：

```text
P0a stable:
  ChatGPT Search / browsing（OpenAI web search API）
  Perplexity（Sonar API）

P0b high-risk spike:
  Google AI Overviews
  Google AI Mode
```

说明：Google 仍然是澳洲报告中最高权重平台族，但采集实现先走独立 spike。`MarketProfile` 必须把 `platform_weight` 与 `build_stage` 分开存储，避免"权重最高"被误读成"第一个上线且必须全量稳定"。

P1/P2 平台扩展：

```text
Gemini
Bing Copilot
Claude
YouTube
Reddit
ProductReview
```

工程落地口径：上述 P1/P2 平台已进入 `AU broader platform registry`，并同步登记到 `MarketProfile.platforms`，但全部默认 `enabled=false`、`weight=0.0`，不改变 P0a 2400 planned runs、不进入 P0b Google spike，也不进入主评分分母。`make au-broader-platform-registry` / `make verify-au-broader-platform-registry` 会生成并复算 `docs/runtime_preflight/au-broader-platform-registry-latest.json`，固定候选平台顺序、build stage、platform role、access methods、required environment、evidence requirements、scoring policy 和 recommended sequence；`GET /v1/au-broader-platform-registry` 与 Runtime Console Broader Platform Registry 面板读取同一清单。真实 Gemini/Copilot/Claude/YouTube/Reddit/ProductReview adapter、evidence package 和 gate 通过后，再另起公式版本或 MarketProfile 版本给权重。

澳洲信源分类：

```text
official_site
google_business
review_site
reddit
youtube
local_media
industry_site
comparison_site
marketplace
government_or_regulator
association
```

技术要求：

- 平台、城市、语言、货币、采样权重、评分权重均从 `MarketProfile` 读取。
- 不把澳洲平台、城市或权重写死在采集、评分、报表代码里。
- 为后续 NZ、UK、US、SG 扩展保留同一配置模型。

### Step 2：确定 ICP 和首批行业模板

不要一开始泛化到所有行业。澳洲首发 P0 固定先做 1 个易验证行业（从下表 4 个候选中选定）。

优先行业判断：

| 行业 | 适合原因 |
| --- | --- |
| DTC / e-commerce | Shopify/WordPress 使用广，评价和 comparison 信源明显，复测周期较短 |
| 本地服务 | Google Business Profile、Google Reviews、城市维度强，容易展示 local relevance |
| B2B SaaS / agency 客户 | 能接受报告和数据产品，容易形成代理商工作流 |
| 教育培训 | prompt 明确、对比和口碑强，但转化归因较慢 |

每个行业建立独立 `IndustryProfile`：

```text
industry_code
default_prompt_templates
source_type_weights
competitor_fields
required_local_facts
report_template
```

### Step 3：生成澳洲 Prompt Pack

一期每个项目 P0 固定配置 100 条 prompt（上限 200），不做国内问题集直译。

工程当前已支持两条 prompt 运营导入路径：`POST /v1/prompts/runtime/import.csv` 接收 JSON body 中的 CSV 文本，`POST /v1/prompts/runtime/import.file` 接收 raw-body 文件并支持 `.csv/.txt` UTF-8 和 `.xlsx` 第一工作表。两条路径最终复用同一个 `PromptQuestion` upsert 与 `runtime_prompts_imported` 审计事件，审计 `input_refs` 会记录 `csv_sha256/source_format/source_filename/source_content_type`，用于复盘“这批 prompt 从哪个文件、哪个格式导入”。`GET /v1/prompts/runtime/imports` 会从同一批 `AuditEvent` 读回项目级导入历史，不新增表，返回 source、hash、prompt count、method version 和审计行。开启 `GENO_RUNTIME_PROJECT_ACCESS_CONTROL=1` 后，导入与导入历史都必须携带可信 actor（默认 `X-GENO-Actor-Id`，或 `GENO_RUNTIME_AUTH_MODE=jwt/jwks` 下的 Bearer JWT），且 actor 属于目标 `project_id` 的 `project_members`，其中导入写操作要求 owner/admin，导入历史读取允许任意项目成员；PostgreSQL RLS 会在 repository 查询层继续按当前 actor/project GUC 做数据库级兜底隔离。Runtime Console 的 Prompt Pack 面板已同时提供 Prompt CSV Import、Prompt File Import 和 Prompt Import History；复杂多工作表、公式求值、导入前 diff 预览、错误行下载、Keycloak/OIDC login/session、前端 SSO 登录流和完整权限后台仍放到 P1 产品化增强。

问题类型：

```text
品牌认知类：Is [brand] good in Australia?
品类推荐类：Best [category] in Australia
城市场景类：Best [category] in Sydney / Melbourne
竞品对比类：[brand] vs [competitor]
购买决策类：Is [brand] worth it?
评价口碑类：[brand] reviews Australia
价格类：[product] price Australia
服务覆盖类：Does [brand] ship to Australia?
本地可信类：Is [brand] legit in Australia?
替代方案类：Alternatives to [competitor] in Australia
```

数据字段：

```text
question_id
project_id
market_code = AU
industry_code
text
intent_type
city
language = en-AU
target_brand
competitors
priority
intent_weight
prompt_version
status
```

Prompt Pack 生成原则：

- 每条 prompt 必须绑定 intent_type。
- 每个 intent_type 至少有品牌、品类、竞品和本地化变体。
- 城市类 prompt 不全量复制：P0 只覆盖 Sydney、Melbourne、Brisbane 三个城市，且只取品类推荐、竞品对比、购买决策三类高意图问题。
- prompt 版本必须保留，复测时使用同一版本。

### Step 4：开发 AI Answer Runner（可插拔采集后端）

采集层是本 MVP 的工程重心，按第 3 章的 `CollectorBackend` 接口实现，**每个平台、每种采集方式都是一个可热插拔的后端**，由 `MarketProfile` 的平台配置决定启用哪些。

P0 目标界面分为稳定链路与高风险 spike。注意：AI Overviews 与 AI Mode 是两个不同界面，拆成两个独立后端。

```text
P0a stable:
  chatgpt          ChatGPT Search / browsing（OpenAI web search API）
  perplexity       Perplexity（引用透明，官方 Sonar API 友好）

P0b high-risk spike:
  google_aio       Google AI Overviews（内嵌 SERP，可从 SERP HTML/截图解析）
  google_ai_mode   Google AI Mode（独立对话界面，交互式，触发和采集机制不同）
```

采集构建顺序（P0）：

```text
1. Perplexity Sonar：最稳定、引用透明，先打通证据链
2. OpenAI web search：补齐 ChatGPT Search / browsing 口径
3. Google AIO / AI Mode spike：限时验证自建浏览器、第三方 SERP、人工补录
4. 过健康闸门后，Google 数据进入全量评分；未过闸时仅进入抽样附录或单独 Google section
```

**为什么 Perplexity 进 P0、Copilot 暂列 P1 之首**：按澳洲 AI chatbot 份额，Copilot（约 11.6%）高于 Perplexity（约 5.4%），但 Perplexity 引用透明、有官方 API、对 citation graph 的信号价值最高，最契合"证据型平台"的 P0 目标；Copilot 份额有相当部分来自 Windows/Edge 默认分发，且基于 Bing 检索，可在 P1 用 Bing 通道补齐。这个取舍是有意为之，不是按份额排序。若客户行业的 Copilot 实际使用高，可在 `MarketProfile` 里把它提到 P0——平台是配置，不是写死。

每个平台至少提供两类可替换后端，避免单点失效：

```text
google_aio   ：PlaywrightGoogleAIOCollector（开源自建） | ThirdPartySerpCollector（第三方 SERP API）
google_ai_mode：PlaywrightAIModeCollector（开源自建） | ManualBackfillCollector（人工补录）
chatgpt      ：OpenAIWebSearchCollector（官方 API） | PlaywrightChatGPTCollector（浏览器）
perplexity   ：PerplexitySonarCollector（官方 API） | PlaywrightPerplexityCollector（浏览器）
baseline     ：SearxngBaselineCollector（开源 SearXNG，传统结果基线，辅助信源对照）
```

Google spike 健康闸门（P0b 必须输出结论）：

```text
spike_scope:
  prompts: 30 条高意图 prompt
  geo: Australia + Sydney
  sample_size: k=2
  surfaces: google_aio, google_ai_mode
  candidates:
    - browser: PlaywrightGoogleAIOCollector / PlaywrightAIModeCollector
    - third_party_api: ThirdPartySerpCollector
    - manual: ManualBackfillCollector

pass_gate:
  - 至少一个 google_aio 后端可在同一窗口完成 >= 80% 计划样本
  - readiness gate 至少观察到 browser / third_party_api / manual 中的两条采集路径
  - 每条结果能可靠记录 surface_triggered / answer_present
  - 有截图或 HTML 快照作为证据
  - 失败原因可分类：not_triggered / layout_changed / blocked / timeout / geo_mismatch / account_state
  - 单项目 Google 采集成本、耗时和失败率可估算

fail_gate:
  - 若未达到 pass_gate，Google 不进入 P0a 主评分分母
  - 报告保留 Google spike 附录：触发率、样本截图、失败原因、下一步方案
  - 客户交付主报告使用 Perplexity + OpenAI 稳定链路，Google section 明确标注为 limited coverage
```

工程落地要求：`GoogleSpikeGateResult` 负责判断 Google AIO 成功率是否达标，`GoogleSpikeReadinessGate` 负责判断 P0b spike 是否满足“两路径对照”验收；真正进入 `VisibilityScoreSnapshot.answer_run_ids` 前还必须经过 `score_input_policy`。该策略要求两个 gate 同时通过，才允许 Google answer runs 进入主评分分母；否则 Google 记录只保留在证据附录、报告方法说明和溯源链里。browser-only fixture 可以通过 AIO 成功率 gate，但必须 fail readiness gate，因此也必须被 `score_input_policy` 排除出主分母；browser + third_party_api 或 browser + manual 等两路径组合才可通过 readiness gate。当前工程已新增真实 `google-spike` worker 模式、collector health-only 预检、`--require-google-spike-gates` 强制门禁，以及 P0b 专用 `make au-p0b-google-runbook` / `make verify-au-p0b-google-runbook` / `make au-p0b-google-runbook-dry-run` / `make verify-au-p0b-google-runbook-execution` / `make verify-au-p0b-google-env-template` / `make au-p0b-google-spike-health` / `make au-p0b-google-spike-health-manifest` / `make au-p0b-google-spike` / `make au-p0b-google-spike-manifest` / `make au-p0b-google-status` / `make verify-au-p0b-google-status` / `make au-p0b-google-package` / `make verify-au-p0b-google-package` / `make au-p0b-google-execution-checklist` / `make verify-au-p0b-google-execution-checklist`。`PlaywrightGoogleAIOCollector` / `PlaywrightAIModeCollector` 已从 shell 升级为 selector-driven Playwright browser adapter：health gate 会检查 `GOOGLE_PLAYWRIGHT_ENABLED`、prompt/answer selector、可选 storage state 和 Playwright 包，失败时输出 `selector_missing`、`session_state_missing` 或 `playwright_missing`；成功采集会生成 HTML snapshot hash、screenshot hash、final URL、page title、citation selector 结果和 `google-playwright-browser-v1` 版本标识。P0b 还新增默认关闭的 `.env.au-p0b-google.example` 脱敏模板，以及 `make verify-au-p0b-google-env-template`、`make au-p0b-google-playwright-env` / `make verify-au-p0b-google-playwright-env`；模板 gate 会在复制真实 env 前确认 Google Playwright 默认关闭，selector/storage/manual/database/SERP key/object store 为空，browser/SERP 地区参数和 runtime 输出路径为安全默认值；Playwright env report 则在 smoke 前生成脱敏环境 readiness 报告，只记录 env 来源、长度和 sha256 前缀，不保存原始 selector、secret 或数据库 URL，并复算 runbook、required env、selector group、storage state 文件、Python Playwright 包、`collector_health`、`ready_for_playwright_smoke`、`ready_for_full_google_run` 和 `next_action`。P0b runbook 已把 `make au-p0b-google-playwright-smoke` 与 `make verify-au-p0b-google-playwright-smoke` 固化为 240-run 前置步骤，并把 health/full spike 固化为 `make au-p0b-google-spike-health`、`make au-p0b-google-spike-health-manifest`、`make au-p0b-google-spike`、`make au-p0b-google-spike-manifest`：默认 verifier 证明 smoke payload hash、结构和失败原因可审计，`--require-success` 才作为 browser path 晋级门禁，要求一条真实 browser capture 成功、HTML/screenshot hash 存在且 `_geno_browser_capture.capture_type=google_browser_ui`。上述命令会生成和校验 runbook、dry-run execution、environment template gate、environment report、smoke payload、manual backfill verification、health payload、spike payload、manifest、status report、P0b evidence package 与 P0b execution checklist hash；execution checklist 会把 env template gate、env、selector group、manual path、DB、smoke、health、full spike、status/package hard gates 和证据输出路径合成脱敏执行清单，用于交接当前 Google blocker 和下一步；evidence package 以 status report 为最终 gate，并汇总每个产物的文件 sha256、verifier hash、ready 字段、`remaining_blockers` 和 `google_main_scoring_allowed`，用于单文件交接复盘；它们证明真实 Google spike 的可审计执行路径已经固定，但不代表澳洲真实 selector/账号/session、真实 AI Mode 入口或 240-run 已经完成。默认真实 `google-spike` 核心矩阵仍为 browser + manual 两条 access method，以保持 30 prompts × 2 geo × k=2 × 2 surfaces = 240 planned runs；`ManualBackfillCollector` 已支持 `MANUAL_BACKFILL_PATH` JSONL 文件，health gate 会检查文件存在，真实采集按同一 `prompt + city` 的出现顺序消费 k 样本，并把 line number、submitted_by、citation/asset count 写入 raw payload；`make au-p0b-google-manual-template` 可生成 30 prompts × Australia/Sydney × k=2 = 120 行待填模板，`make verify-au-p0b-google-manual-backfill` 会 strict 校验每个 prompt/city 两条样本、answer、citation 与 screenshot/HTML 资产，并固定输出 `docs/runtime_preflight/au-p0b-google-manual-backfill-verification-latest.json`，其中包含原始 JSONL `file_sha256` 与 `verification_hash`；P0b runbook/status/remediation plan 已把 `google_manual_backfill_verify` 放在 smoke strict gate 之后、health-only 之前，manual verification 缺失或 strict 失败时会先返回 `run_verify_google_manual_backfill` / `prepare_google_manual_backfill_file` / `fix_google_manual_backfill_coverage`，不放行 health-only 或 240-run；缺记录、空文件或 JSON 错误会成为可审计 collection failure。`ThirdPartySerpCollector` 已实现 provider-neutral JSON adapter，可通过 `SERP_API_KEY` / `SERP_API_ENDPOINT` 请求第三方 SERP/AI-answer 服务，解析 `ai_overview` / `answer_box` / `organic_results` 等常见字段，生成 `geno-api-snapshot://google.third_party_serp/...` HTML snapshot 证据 hash；普通 organic-only 响应只计 `answer_present`，不误报 `surface_triggered`。第三方路径已落为独立 `google-serp-fixture` / `google-serp-spike` 对照模式，计划口径为 30 prompts × 2 geo × k=2 × 1 third-party backend = 120 planned runs，可通过 `make au-p0b-google-serp-fixture` 做 fixture 复核、通过 `make au-p0b-google-serp-health` 做真实供应商 health-only 预检，并通过 `make verify-au-p0b-google-serp-fixture` / `make verify-au-p0b-google-serp-health` 复核 payload hash、计划口径、collector health、full spike gate 缺席和 comparison-ready 状态；`make au-p0b-google-serp-status` / `make verify-au-p0b-google-serp-status` 会进一步汇总 fixture、manifest、supplier health 和真实 comparison 产物，输出 `comparison_evidence_ready`、`supplier_health_ready`、`remaining_blockers` 与 `next_action`。该模式输出 `google_serp_comparison_plan` 与 `google_serp_comparison_summary`，`--persist` 时只保存 raw evidence 与 `CollectionRunSummary(run_type=google_serp_comparison)`，且禁止 `--persist-analysis`，避免把同一 prompt/city/sample 的多后端重复结果直接混入主评分分母；即使 SERP status pass，也只代表 third-party comparison evidence 可进入 P0b review，不代表 Google 进入主评分分母。

补充状态：P0b 总控状态报告已经读取 Google Playwright env readiness 与 smoke artifact。若 env readiness 报告缺失，`make au-p0b-google-status` 会输出 `next_action=run_google_playwright_env_report`；若 env strict gate 未通过，会优先返回 env 报告里的 `next_action`；若 strict smoke 未成功，才会输出 `next_action=run_google_playwright_smoke`，并把 `playwright_smoke:*` 放入 `remaining_blockers`，不会继续放行 health-only 或 240-run。

人工补录运营补充：Runtime API 已新增 `POST /v1/evidence-runs/runtime/manual-backfill/import.csv`，Runtime Console 已新增 `Manual Backfill CSV` 表单。该入口接收项目级 CSV，必填 `prompt_question_id,answer_text`，可选 platform/surface/citation_urls/screenshot_url/html_snapshot_url/sample_index/sample_size/device/account_state/submitted_by/notes；后端会先整批反查 prompt 存在且属于同一 `project_id`，通过后再写入标准 `AnswerRun/RawAnswer/AnswerCitation/EvidenceAsset/CollectionCost/CollectorLog`，逐条保留 `manual_backfill_recorded`，并追加 `manual_backfill_batch_imported` 批次审计摘要。失败行会返回 row number 和错误原因，默认不半写入。该入口用于降低 P0b Google manual path 的运营录入成本，不替代 `MANUAL_BACKFILL_PATH` JSONL strict verifier，也不代表真实 120-row manual backfill、browser/manual readiness gate 或 240-run Google spike 已完成。

两个采集保真度问题必须在后端处理：

- **API ≠ 消费者界面**：官方 API（如 ChatGPT web search、Perplexity Sonar）便于稳定采集，但其答案组装、模型版本、引用与个性化不保证与消费者界面一致。默认走 API 是"用稳定性换保真度"的有意取舍，必须配一个**抽检环节**：定期对同一批 prompt 用官方 API 后端与浏览器后端各采一次，量化差异率并在报告方法说明里披露。`access_method` 字段全程记录，便于区分。工程上已经把该环节落为独立 `ApiBrowserFidelityCheck`：对同一 `prompt_question_id + city` 的 `official_api` 与 `browser` run 做可比较配对，冻结 status、样本数、mismatch count、difference rate、payload hash，并写入 `api_browser_fidelity_checked` 审计事件；`GET /v1/fidelity-checks/runtime/trend` 已基于最近已落库 checks 提供 sampled/total、latest/earliest/average/max difference rate、趋势窗口和 improving/worsening/flat/insufficient_sampled_data/no_data 方向，Runtime Console 已展示趋势摘要与查询路径。worker 的 `--include-browser-fidelity-fixture` 可先用 `chatgpt_search.browser.fixture` 生成 paired sampled 数据，且这些 browser fidelity samples 通过 `score_input_policy.excluded_fidelity_sample_answer_run_ids` 排除出主评分分母。真实浏览器入口已接为 `PlaywrightChatGPTSearchCollector` / `--include-browser-fidelity-playwright` / `make api-browser-fidelity-preflight`：它要求显式 `GENO_BROWSER_COLLECTOR_ENABLED=1`、Playwright、prompt/answer selector、可选 ChatGPT storage state 和 artifact dir；缺配置时通过 `collector_health_gate` 在采集前输出 `not_configured`、`selector_missing`、`session_state_missing` 或 `playwright_missing`；health 通过后若浏览器启动、登录态、selector 交互或官方 API 调用失败，`--require-no-collection-failures` 会输出 JSON 后以 exit 5 失败。采集执行层已提供 worker-local `CollectionExecutionPolicy`，可用 `--collection-max-retries`、`--collection-retry-backoff-seconds` 和 `--collection-rate-limit-delay-seconds` 控制每个计划样本的重试、指数退避和样本间节流；重试不会膨胀 planned/attempted 分母，成功重试写 `collection_retry_succeeded`，失败耗尽写入 `attempt_count/retry_errors/max_retries`。成功时会把浏览器 screenshot 与 HTML snapshot hash 写入标准 RawEvidence 链；如果同时配置 `GENO_BROWSER_ARTIFACT_DIR` 和 `OBJECT_STORE_ENDPOINT`，worker 会在落库前把本地 `file://` browser HTML/PNG 归档到对象存储 `evidence/<project_id>/<answer_run_id>/<asset_id>.<ext>`，再用 `s3://...` URL 与对象 content hash 更新 `EvidenceAsset`，并写入 `browser_capture_assets_archived` 审计事件；没有可读取原始文件的 `geno-browser-*://` 引用不会被伪装成 durable object。调度上已接入 `BrowserFidelitySamplingPlan` / `--plan-browser-fidelity-sampling` / `make browser-fidelity-plan`：按 run date、cadence 和 seed 从 100 条 prompt 与 AU 城市中确定性抽样，输出可复跑的 `--prompt-ids/--cities` worker 参数，并写入 `browser_fidelity_sampling_planned` 审计事件；`scripts/run_browser_fidelity_scheduler.py`、`make browser-fidelity-scheduler-plan/run` 与 Compose `scheduler` profile 已把“生成计划 -> 可选执行推荐 worker 参数”封装为 cron/K8s CronJob 友好的 JSON 入口，默认只落计划审计，显式 `--execute` 或 `GENO_BROWSER_FIDELITY_EXECUTE=1` 后才会执行真实采集。真实 API adapter 会为官方 API response 生成 `geno-api-snapshot://...` HTML snapshot 资产和 payload hash；当 worker `--persist` 且存在 `OBJECT_STORE_ENDPOINT` 时，会在保存原始证据前把 snapshot 渲染为静态 HTML 并归档到对象存储 `evidence/<project_id>/<answer_run_id>/<asset_id>.html`，再用 `s3://...` URL 与对象 content hash 更新 `EvidenceAsset`，并写入 `api_snapshot_assets_archived` 审计事件。该资产证明原始 API 响应可复盘，但不能冒充消费者界面截图；真实 ChatGPT selector/账号联调、真实周期样本数据、分布式失败重试队列和 Temporal 深度编排仍是后续出口条件。
- **AIO 选择性触发**：Google AI Overviews 不是每个 query 都出现。后端必须如实返回 `answer_present / surface_triggered`，把"AIO 没触发"与"触发了但没提品牌"区分开（影响 Step 9 的分母口径）。

采集服务要求：

- 与主业务服务隔离，作为独立 worker 运行。
- 支持失败重试、平台级限流、`collector_version`、手动补录；P0a 已先落 worker 内可审计重试/backoff/节流策略，P1 再升级为分布式队列、全局限流和 Temporal 可重放工作流。
- 支持截图和 HTML 快照留存、`raw_payload_hash` 完整性校验。
- 记录账号状态、地区、设备、采集方式（`access_method`）。
- 同一 prompt 的多次重复采样用 `sample_index` 区分（见 Step 9 非确定性处理）。

### Step 5：建立 Raw Evidence Store

这是澳洲首发 MVP 的核心，不是附属字段。

每次采集必须保存：

```text
prompt
prompt_version
answer
answer_present        # 该生成式界面/答案是否出现（AIO 是否触发）
surface_triggered     # 目标界面是否被触发
platform
surface               # aio / ai_mode / search / browsing
access_method         # browser / official_api / third_party_api / manual
market_code
city
language
device
model_or_surface
citations
screenshot_url
html_snapshot_url
account_state
collector_version
sample_index          # 同一 prompt 第几次重复采样
collected_at
raw_payload_hash
```

数据模型：

```text
AnswerRun
RawAnswer
AnswerCitation
EvidenceAsset
CollectorLog
```

证据留存规则：

- 每一个 score 都必须能追溯到 `AnswerRun`。
- 每一个 citation 都必须能追溯到原始回答。
- 每一次报告导出都记录所用 answer_run_ids。
- 同一 prompt 的复测和重复采样必须保留历史版本，不能覆盖。

### Step 5.1：建立 Audit / Provenance / Explanation 机制

当前的 Raw Evidence Store 已经能保存原始回答和采集元数据，但还不够。P0 必须把"可审计、可溯源、可解释"作为独立能力实现，避免报告只是展示结论、无法复盘计算过程。

三类能力边界：

```text
Audit Trail        记录谁/哪个系统在何时做了什么，输入输出是什么版本
Provenance Trail   记录每个报告数值、图表、建议来自哪些 answer_run / citation / analysis
Explanation Bundle 记录分数为什么这样算：子指标、权重、分母、证据、局限和置信度
```

P0 审计事件必须覆盖：

```text
project_created
market_profile_changed
prompt_pack_generated
prompt_pack_modified
collector_run_started
collector_run_completed
collector_run_failed
manual_backfill_created
raw_evidence_stored
parser_run_completed
score_snapshot_created
source_graph_updated
competitor_benchmark_created
report_exported
score_formula_changed
entity_alias_confirmed
```

审计事件字段：

```text
event_id
event_type
project_id
actor_type          # user / system / worker / api
actor_id
target_type         # project / prompt / answer_run / score_snapshot / report
target_id
before_hash
after_hash
input_refs          # prompt_question_ids / answer_run_ids / source_ids
output_refs         # analysis_ids / score_snapshot_ids / report_export_id
method_version      # collector_version / parser_version / scoring_formula_version
created_at
```

可溯源链路要求：

```text
ReportExport
  -> VisibilityScoreSnapshot
  -> AnswerAnalysis
  -> AnswerRun
  -> RawAnswer / AnswerCitation / EvidenceAsset

SourceGap / ActionRecommendation
  -> SourceGraph
  -> AnswerCitation
  -> AnswerRun
```

实现规则：

- `ReportExport` 必须冻结 `score_snapshot_ids`、`answer_run_ids`、`prompt_version`、`scoring_formula_version`、`platform_weights_snapshot`、`sample_size`、`window_start/window_end`，导出后不允许重写，只能重新生成新版本。
- `VisibilityScoreSnapshot.answer_run_ids` 在 P0 可先用数组保存，但必须同时预留 `ScoreSnapshotRun` 关联表，避免后续大样本查询困难。
- `SourceGraph.answer_run_ids` 在 P0 可先用数组保存，但必须同时预留 `SourceGraphEvidence` 关联表，用于追踪某个 source gap 来自哪些引用。
- `raw_payload_hash`、`html_snapshot_url`、`screenshot_url` 不可覆盖；同一采集重跑必须生成新的 `AnswerRun`。
- 人工补录、实体别名确认/批量确认、评分权重修改、评分公式重放都必须写 `AuditEvent`，并在报告方法说明中披露是否存在人工介入或重算口径。

分数解释包（Explanation Bundle）：

```text
score_snapshot_id
scope_type / scope_value
final_score
formula_version
platform_weights_snapshot
component_weights_snapshot
component_contributions:
  - component_name
  - component_score
  - weight
  - weighted_contribution
  - denominator
  - evidence_answer_run_ids
  - explanation_text
uncertainty:
  - sample_size
  - stddev
  - confidence_note
limitations:
  - API != consumer UI
  - Google limited coverage / not triggered
  - AI answer non-determinism
```

验收口径：

- 任意报告总分、平台分、城市分、intent 分都能点开解释包。
- 解释包能列出贡献最大的 3 个正向证据、3 个负向/缺口证据和对应原始回答。
- 任意人工修改都能在 `AuditEvent` 中看到 actor、时间、前后 hash、原因或备注。
- 重新导出同一报告不会覆盖旧版本；两次报告的差异能通过 `ReportExport` 和 `AuditEvent` 复盘。

### Step 6：做地理采样机制（GeoProvider 抽象）

澳洲结果需要区分全国表现和城市表现。城市级地理定位的实现方式需保持可替换，因此抽象成可插拔的 `GeoProvider`：

```text
GeoProvider（接口）
  resolve(city) -> {geo_params, egress}   # 给采集后端注入地理信号
实现可选：
  UuleGeoProvider          # 通过 Google uule / near 等地理参数
  ProxyPoolGeoProvider     # 通过城市出口的代理池
  VendorGeoProvider        # 通过第三方供应商的地理定位能力
```

采集后端通过 `GeoProvider` 拿到地理信号，本身不关心地理是怎么实现的。这样从"参数注入"换到"代理池"再换到"供应商"，采集逻辑不动。

P0 地理范围：

```text
Australia
Sydney
Melbourne
Brisbane
```

P1 扩展：

```text
Perth
Adelaide
```

`GeoSample` 配置：

```text
market_code = AU
country = AU
city
language = en-AU
device = desktop/mobile
geo_provider          # 使用哪个 GeoProvider 实现
sampling_weight
status
```

评分和报告需要支持：

- 全国总览。
- 城市对比。
- 城市问题明细。
- 城市级竞品压制。
- 本地相关性不足提示。

工程当前已在 Runtime Console 补齐 `Question Detail` 问题明细矩阵：前端会额外拉取最多 200 条当前筛选下的 evidence window，并与最多 200 条 runtime prompt 做服务端渲染期聚合，不新增后端接口。每条问题展示 run count、trigger/answer rate、required platform coverage、missing platform、citation/asset/audit 计数、城市/access method/surface/status 分布、最新运行时间和最近证据摘要；默认只展开有缺口的问题，已覆盖问题折叠，便于运营先处理 platform gap、trigger gap、answer gap 和 source gap。

### Step 7：改造澳洲答案解析器（可切换实现）

`ParserEngine` 按接口实现，规则解析与 LLM-as-judge 两种实现可切换或并存（A/B），保留 `analysis_version`。澳洲英文回答需要单独做实体识别、推荐判断和本地相关性判断。

解析字段：

```text
brand_mentioned
brand_recommended
brand_rank
competitors_mentioned
competitor_rank
recommendation_strength
sentiment
local_relevance
citation_sources
review_sources
price_mentions
availability_mentions
negative_mentions
uncertainty_flags
```

`local_relevance` 是澳洲首发关键字段，用来判断 AI 是否真的把品牌识别为澳洲可用方案，而不是泛泛介绍。

判断依据：

```text
是否提到 Australia / Australian customers
是否提到澳洲城市
是否提到 AUD 价格
是否提到澳洲配送或服务范围
是否提到澳洲客服、门店或本地团队
是否引用澳洲本地信源
是否使用澳洲相关术语
```

实体识别要求：

- 支持品牌别名、域名、产品名、母公司名（实体与别名表见 8.14）。
- 支持竞品别名和产品线。
- 对同名品牌做人工确认机制。
- 从已入库 `RawAnswer` 与 `AnswerCitation` 挖掘高置信候选时必须保留 answer run / citation URL 引用，候选确认后再进入 parser。
- 保存解析置信度和规则/模型版本（`analysis_version`）。

### Step 8：建立 Citation Graph

Citation Graph 在内容生成之前上线。底层存储通过 `GraphStore` 接口实现：MVP 起步用 PostgreSQL 邻接表，关系复杂后可平滑替换为 Neo4j / Apache Jena，查询接口不变。工程上已补 `InMemoryPostgresAdjacencyGraphStore` 与 `InMemoryNeo4jCitationGraphStore` 的投影合约测试：同一 `CitationGraphResult` 写入两种存储投影后，source nodes、evidence links、source gaps 和 competitor benchmarks 的 summary 查询结果必须一致；这证明业务查询口径可切换，但不等同于已完成真实 Neo4j 服务、驱动和 Cypher 联调。

数据字段：

```text
source_id
source_url
source_domain
source_type
market_code = AU
topic
intent_type
brand_mentioned
competitors_mentioned
citation_count
ai_platform_seen
answer_run_ids
authority_score
freshness_score
local_relevance_score
source_gap_type
last_seen_at
```

系统应自动输出：

```text
哪些信源经常被 AI 引用
哪些信源有竞品但没有我方品牌
哪些信源内容过旧
哪些信源适合补充内容
哪些信源对某类问题影响最大
哪些澳洲本地信源缺失
```

澳洲高价值信源层：

| 信源层 | 代表 |
| --- | --- |
| 官方/监管 | gov.au、ACCC、ASIC、ATO、TGA、ACMA、州政府网站 |
| 品牌自有 | `.com.au` 官网、AU landing page、FAQ、shipping/returns、pricing AUD |
| 消费评价 | ProductReview.com.au、Google Reviews、Trustpilot、Reddit AU threads |
| 独立评测 | CHOICE、Canstar、Finder、WhistleOut、Mozo |
| 本地媒体 | ABC、SBS、The Guardian Australia、SMH/The Age、AFR、news.com.au |
| 视频/社媒 | YouTube、TikTok、Instagram、LinkedIn |
| B2B/软件 | G2、Capterra、GetApp、行业协会、案例页、白皮书 |

### Step 9：计算 AU Visibility Score

评分必须可解释、公式版本化（`ScoringFormula` 可整体替换，历史分数按旧版本可重算），不输出单一总分。

#### 9.1 子指标与公式

评分子指标（固定 8 项）：

```text
MentionScore：品牌是否出现
RecommendationScore：是否被明确推荐
PositionScore：在推荐列表中的位置
CitationScore：是否引用澳洲本地或高权重信源
LocalRelevanceScore：回答是否体现澳洲可购买、可服务、可交付
SentimentScore：描述是否正向、中性、负向
FreshnessScore：引用信息是否较新
CompetitorShareScore：竞品共现和压制程度
```

评分公式 `au_visibility_v1`（8 项权重之和为 1.00）：

```text
AUVisibilityScore =
  MentionScore * 0.18 +
  RecommendationScore * 0.22 +
  PositionScore * 0.12 +
  CitationScore * 0.16 +
  LocalRelevanceScore * 0.14 +
  SentimentScore * 0.08 +
  FreshnessScore * 0.05 +
  CompetitorShareScore * 0.05
```

评分公式 registry：

```text
SCORE_FORMULA_REGISTRY
  au_visibility_v1
    status: active
    weights: 默认 P0a 证据报告公式
  au_visibility_v1_1_local_boost
    status: candidate
    supersedes: au_visibility_v1
    weights: 提高 LocalRelevanceScore 与 FreshnessScore 权重，用于 AU 本地化敏感行业试算
```

实现约束：

- `formula_version` 必须来自 registry，未知版本直接拒绝，避免报告中出现不可复盘公式。
- runtime API 通过 `/v1/score-formulas/runtime` 暴露公式目录，控制台 Score Weights 表单使用该目录选择版本。
- worker `--persist-analysis` 默认使用 `au_visibility_v1`；如需候选公式，可传 `--score-formula-version au_visibility_v1_1_local_boost`。
- 历史重算必须从冻结的 `AnswerAnalysis`、`platform_weights_snapshot` 和指定 `formula_version` 重放，生成新的 `VisibilityScoreSnapshot`、`ScoreContribution` 与 `visibility_score_snapshot_rescored` 审计事件，不覆盖旧快照。
- `ReportExport` 只引用某次已冻结的 `score_snapshot_ids` 和 `scoring_formula_version`；重算后若要出新报告，必须生成新的 `ReportExport` 版本。

P0 平台权重（固定默认值，可在 MarketProfile 调整）：

```text
Google AI Overviews / AI Mode: 45%
ChatGPT Search / browsing: 30%
Perplexity: 25%
```

项目级评分权重可通过 `score_weight_configs` 按 `project_id + formula_version` 覆盖默认 8 项组件权重；保存时必须校验组件完整、非负、总和为 1.00，并写入 `score_weight_config_saved` 审计事件。每次生成 `VisibilityScoreSnapshot` 时都把实际使用的 `formula_version` 与 `component_weights_snapshot` 冻结到快照，后续即使项目权重调整或默认公式升级，历史分数和 `ScoreContribution.weight` 仍能按当时口径复盘。人工复核采用追加型 `human_review_records`，不覆盖原始评分、内容草稿正文或证据绑定；每条记录保存 `project_id / target_type / target_id / review_status / decision / reviewer_id / notes / payload / created_at`，并写入 `human_review_recorded` 审计事件。MVP 可先覆盖 `visibility_score_snapshot`、`content_draft`、`answer_analysis`、`answer_run`、`score_weight_config` 和 `project` 六类对象；当前已补 `RuntimeHumanReviewQueue` 队列，从 `visibility_score_snapshot` 与 `content_draft` 聚合待审对象，冻结 `priority / reason / latest_review / evidence_refs` 供 Console 复盘；对 `content_draft` 的复核会把同项目 `content_drafts.review_status` 投影为本次复核状态并写入 `content_draft_review_status_updated`。开启 API 级项目访问控制后，score weight 读取、human review 读取和 review queue 都会按 `project_members` 做项目成员校验，actor 可来自 header、HS256 JWT 或 inline/remote/OIDC-discovered JWKS RS256 JWT；数据库层 RLS 会按同一个 actor/project 上下文限制评分、复核、内容草稿和审计表可见范围；score weight 保存要求 owner/admin，human review 写入允许 owner/admin/analyst。后续再接复杂审批流、分配、通知、Keycloak/OIDC login/session、前端 SSO 登录流、完整权限后台和抽样校准。

P1/P2 平台扩展权重（当前注册表默认值，先不进入主评分）：

```text
Gemini: 0%
Bing Copilot: 0%
Claude: 0%
YouTube: 0%
Reddit: 0%
ProductReview: 0%
```

这些 0% 不是业务价值判断，而是工程门禁：候选平台只有在 adapter health、证据字段、方法披露、采样口径和回归 verifier 都通过后，才允许进入新的评分配置或 source-graph-only 分析口径。

#### 9.2 分母口径（必须区分"没触发"和"没提到"）

由于 Google AIO 选择性触发，各比率必须明确分母，避免把"AIO 没出现"误算成"品牌缺失"：

```text
Trigger Rate      = surface_triggered 次数 / 采集尝试次数
Mention Rate      = 提及品牌次数 / surface_triggered 次数      # 分母是触发子集，不是全部尝试
Recommendation Rate = 明确推荐次数 / surface_triggered 次数
```

报告中两个分母都要展示：既看"AI 答案出现的概率"（Trigger Rate），也看"出现时品牌的表现"（Mention/Recommendation Rate）。

工程落地要求：`ReportExport.method_disclosure.score_rate_denominators` 必须冻结三类 rate 的 `numerator / denominator / formula` 与本报告窗口的 `attempted_records / surface_triggered_records / evidence_trigger_rate`。Markdown、PDF、白标 PDF 和 Runtime Console 只能复用这个冻结口径；若旧报告缺少该字段，runtime artifact 可用已绑定的 answer runs 兼容补算展示，但不改写历史 `ReportExport`。

#### 9.3 非确定性与重复采样

AI 答案非确定性强，单次采样（N=1）评分噪声大。要求：

```text
每条 prompt 在每个平台、每个城市重复采样 k 次（P0a stable 固定 k=3，用 sample_index 区分）
Google spike 固定 k=2 起步，通过健康闸门后再提升到 k=3
分数按 k 次聚合，报告展示均值与离散度（标准差或置信区间）
样本量、采集时间窗口、平台覆盖范围在报告中显示
明确提示 AI 答案非确定性，不做绝对排名承诺
```

P0 采样量闸门：

```text
P0a stable 默认上限:
  prompts: 100
  platforms: 2（chatgpt, perplexity）
  geo: Australia + Sydney + Melbourne + Brisbane
  k: 3
  planned_runs: 100 * 2 * 4 * 3 = 2400

P0b Google spike 默认上限:
  prompts: 30
  platforms/surfaces: 2（google_aio, google_ai_mode）
  geo: Australia + Sydney
  k: 2
  planned_runs: 30 * 2 * 2 * 2 = 240

cost_gate:
  - 每个 collector_backend 必须写入 CollectionCost
  - 单项目 planned_runs、成功率、平均耗时、API/代理/LLM 成本必须在报告方法页展示
  - 若 P0a 2400 runs 的耗时或成本不可控，优先降级城市数或 prompt 数，不降级证据字段
```

#### 9.4 评分要求与局限

- 总分必须能拆到平台、intent、city、prompt，每个分数能点回原始 answer run。
- 公式版本化；调整权重或公式时不覆盖历史，旧分数可用旧公式重算。
- **构念效度局限要写进方法说明**：T+7/14/30 复测能展示"分数变化"，但本期不声称"分数高 = 业务结果好"。后续若拿到客户转化/咨询数据，再做相关性验证。

### Step 10：做 Competitor Benchmark

P0 每个项目支持 3-5 个竞品。

对比维度：

```text
brand mention rate
recommendation rate
average answer position
citation count
source overlap
unique competitor sources
sentiment
local relevance
city-level advantage
intent-level advantage
```

输出内容：

- 哪些 prompt 竞品出现而我方没有。
- 哪些 source 只覆盖竞品。
- 竞品在哪些城市或意图中更强。
- 竞品被推荐时 AI 使用了什么理由。
- 我方需要补哪些事实、页面或第三方信源。

### Step 11：输出 Action Plan

P0 报告给轻量建议；完整 Action Plan 自 P1 起做。

行动建议类型：

```text
更新 AU landing page
新增 FAQ
新增 comparison page
补充 Schema.org 结构化数据
补充 AUD 价格、配送、售后、城市覆盖
修复品牌事实不一致
建立或更新 ProductReview / Google Reviews / Trustpilot
监测 Reddit 讨论
创建 YouTube explanation / review 内容
补充本地媒体或行业目录资料
补充 B2B 案例页或白皮书
```

每条建议必须绑定：

```text
action_id
source_gap_id
related_prompt_ids
related_answer_run_ids
evidence_summary
target_source_type
expected_impact
effort_level
owner
status
next_check_date
```

原则：

- 不输出没有证据支撑的泛泛建议。
- 不承诺强因果。
- 用任务状态和复测窗口展示变化。

当前工程落地已把 Action Plan 后的轻量预警做成“派生 alert + append-only 管理事件”模型：`GET /v1/runtime-alerts` 不把风险判断写成可变事实表，而是从最新 `VisibilityScoreSnapshot`、对应 `ScoreContribution`、`AnswerAnalysis`、`SourceGap`、`CompetitorBenchmark` 和 `ActionRecommendation` 派生预警；人工或外部流程对预警的处理状态通过独立 `runtime_alert_events` 追加写入。第一版规则为 `runtime_alerts_v1`，覆盖：

- `brand_absent`：品牌 mention rate 低于阈值，证据回指 score snapshot、MentionScore contribution 和相关 answer runs。
- `low_recommendation_rate`：recommendation rate 低于阈值，证据回指 RecommendationScore contribution 和相关 answer runs。
- `negative_sentiment`：answer analysis 的 sentiment score 低于阈值，证据回指 answer analysis、score snapshot 和相关 answer runs。
- `source_gap`：source gap 的 expected weight 触发风险，关联已有 source gap action。
- `competitor_pressure`：竞品 mention rate 高于品牌 mention rate，证据回指 competitor benchmark、score snapshot 和 answer runs。

每条预警返回 `severity / metric_name / metric_value / threshold / source / source_id / evidence_refs / related_actions / audit_events / management_events`，Runtime Console 的 Runtime Alerts 面板可直接展示证据链、关联 action、最近处理历史，并通过 `POST /v1/runtime-alerts/{alert_id}/events` 记录 `acknowledged/resolved/snoozed/reopened/escalated`。该写入只追加 `runtime_alert_events` 和 `runtime_alert_event_recorded` 审计事件，保存 actor、note、metadata、before/after hash 和输出事件 id，不改写派生 alert、评分、answer analysis、source gap 或竞品 benchmark。`POST /v1/runtime-alerts/notifications` 进一步把当前未 resolved/snoozed 的派生 alert 显式入队为 `runtime_notifications.notification_type=runtime_alert`，并复用 `runtime_notification_subscriptions/deliveries` 按 event types 与 severity threshold 生成 webhook、Slack Incoming Webhook 或 SMTP email delivery；该动作只写通知与投递审计，不改写 alert 判断本身。`workers/notification_worker/run_runtime_alert_notifications.py` 和 `make runtime-alert-notification-worker` 则提供 cron/K8s CronJob 友好的通知扫描入口，可按 AU market 或显式 project id 批量调用同一入队逻辑，并输出每项目 notification/delivery/skipped/failed 计数。`workers/notification_worker/run_runtime_alert_escalations.py` 和 `make runtime-alert-escalation-worker` 进一步提供最小 SLA 升级扫描入口，默认按 `critical=4h,high=24h` 判断 overdue alerts，跳过 latest management status 为 acknowledged/resolved/snoozed/escalated 的 alert，并只追加 `runtime_alert_events.status=escalated` 与 `runtime_alert_event_recorded` 审计事件。该能力解决“可审计、可解释地看到、处理、升级并推送负面情绪、品牌缺失和竞品压制风险”，但还不是完整实时告警系统；邮件模板/退订/服务商 API、Slack App/OAuth/交互式消息、复杂值班升级和 Temporal/长驻队列化调度仍放在 P1 后续增强。

### Step 12：本地化品牌知识事实

知识库在 P1 做轻量版本，不作为 P0 的阻塞项。

字段：

```text
AU product availability
AUD price range
delivery coverage
local support hours
Australian customer cases
city coverage
local competitors
local FAQs
local terminology
local source references
```

知识库检索规则（通过 `VectorStore` 接口，pgvector 起步）：

```text
生成澳洲内容或建议时，优先检索 market = AU 的事实
AU 事实不足时，允许回退到 global 事实
回退事实必须标记为 global_source
内容和建议需要提示本地化缺口
```

当前工程落地路径：

```text
LocalizedKnowledgeFact
  -> knowledge_fact_text()
  -> fixture-knowledge-embedding-v1 8 维 deterministic embedding
  -> knowledge_fact_embeddings.embedding vector(8)
  -> /v1/knowledge-facts/runtime/search
  -> Runtime Console pgvector Knowledge Search
  -> knowledge_fact_embeddings_indexed AuditEvent
```

这一路径先使用 PostgreSQL + pgvector 跑通 runtime 检索、AU 优先排序、global fallback 标记和索引审计。工程上已补 `InMemoryPgVectorStore` 与 `InMemoryQdrantVectorStore` 的投影合约测试：同一批 deterministic knowledge fact embeddings 写入两种存储投影后，统一 `summarize_vector_search()` 返回一致的 top-k id/score 排序；这证明检索业务口径可切换，但不等同于已完成真实 Qdrant/Milvus 服务、驱动、ANN 索引和性能调优。真实 embedding provider、embedding 维度升级、Qdrant/Milvus 适配器、内容生成时的在线 RAG 策略，放在 P1/P2 产品化切片中替换，不改变 `VectorStore`/runtime search 的业务语义。

### Step 13：报告导出和代理商工作流

报告导出是 P0/P1 的关键能力，通过 `ReportExporter` 接口实现。

报告结构：

```text
Executive Summary
Methodology
Audit & Provenance Summary
Platform Coverage
Prompt Coverage
AU Visibility Score
Score Explanation Bundle
Platform Breakdown
City Breakdown
Intent Breakdown
Competitor Benchmark
Citation Graph
Source Gaps
Raw Evidence Appendix
Manual Intervention Log
Action Plan
Next Check Schedule
```

代理商工作流：

```text
multi_client
multi_project
white_label_report
report_template
assignee
task_status
monthly_snapshot
export_history
```

当前工程已把代理商白标工作流拆成一条可演示的最小闭环：`Project Bootstrap` 创建 AU/DTC 客户项目；`Project Members` 维护 owner/admin/analyst/viewer；`Brand Kit` 保存 `client_name / prepared_by / logo_url / primary_color / secondary_color / footer_text` 并写 `project_brand_kit_saved`；`Logo Upload` 把品牌图片归档到 MinIO/S3-compatible `brand-assets/<project_id>/...`，写回 Brand Kit 的 `logo_url`，生成 `project_brand_logo_uploaded`，并同步 upsert `project_brand_assets`（`asset_type=logo / category=brand_logo / status=active / content_hash / storage_version`）及 `project_brand_asset_registered` 审计事件；`Brand Assets` 从 `project_brand_logo_uploaded` 和 `project_brand_logo_version_activated` 审计事件投影出 Logo 版本列表，展示来源文件、content hash、上传人、上传时间和当前 active 状态，并通过 `POST /v1/project-brand-kits/runtime/assets/activate` 把历史 Logo URI 重新激活为 Brand Kit 默认值，同时追加 `project_brand_logo_version_activated` 审计事件；`Asset Register / Asset Library` 通过 `GET/POST /v1/project-brand-assets/runtime` 登记和读取项目级素材，冻结 `asset_type/category/asset_url/preview_url/source_filename/source_content_type/content_hash/storage_version/status/metadata`，并以 `project_brand_asset_registered` 记录审计链；`POST /v1/project-brand-assets/runtime/{asset_id}/scan-status` 可把素材扫描状态更新为 `pending/passed/failed/skipped`，记录 `scan_checked_at/scan_method_version/scan_notes`，并追加 `project_brand_asset_scan_recorded` 审计事件；`Theme Editor` 不新增主题 schema，而是复用同一组 Brand Kit 字段，在 Runtime Console 中提供颜色输入、客户/服务商/页脚预览、white-label artifact path 和最近 Brand Kit 审计摘要；`Report History` 读取最近 5 个冻结 `ReportExport`，支持追加 `internal_review/client_ready/archived` 管理事件并写入 `report_export_management_recorded`，只表达报告交付状态，不改写报告版本、方法披露、对象存储 URL 或评分快照；`Report Export Queue` 使用 `report_export_jobs` 持久化项目、目标报告、artifact type、template、筛选条件、排序、请求人、状态、artifact URL、错误信息、attempt、lease 和 next attempt，`GET/POST /v1/report-export-jobs/runtime` 负责查询和排队任务，`GET /v1/report-export-jobs/runtime/stats` 负责队列指标，`POST /v1/report-export-jobs/runtime/{job_id}/status` 负责状态推进，并写入 `report_export_job_queued` / `report_export_job_status_updated` 审计事件；任务进入 `succeeded/failed/dead_letter/cancelled` 终态时会同步写入 `runtime_notifications`，追加 `runtime_notification_created` 审计事件，Runtime Console 的 `Runtime Notifications` 可读取 unread count、severity、target、payload 摘要，并通过 `POST /v1/runtime-notifications/{notification_id}/status` 追加 `runtime_notification_status_updated` 来标记 read/unread；Runtime Alerts 可通过 `POST /v1/runtime-alerts/notifications` 把当前未 resolved/snoozed 的派生 alert 显式入队为 `runtime_alert` notification，并复用同一套订阅和投递队列；`make runtime-alert-notification-worker` 与 Compose `scheduler` profile 可把该入队逻辑包装为 cron/K8s CronJob 可调用的单次扫描入口；`make runtime-alert-escalation-worker` 与 Compose `scheduler` profile 可按 `critical=4h/high=24h` 默认 SLA 阈值追加 `escalated` 管理事件；外部 webhook/Slack Incoming Webhook/SMTP email 采用同一套订阅与投递表，`GET/POST /v1/runtime-notification-subscriptions` 保存项目级 endpoint、event types、severity threshold、channel 和 active/paused/disabled 状态，追加 `runtime_notification_subscription_saved`，通知创建时按 event type 与 severity threshold 生成 `runtime_notification_deliveries` queued 行并追加 `runtime_notification_delivery_queued`；`channel=webhook` 冻结 canonical GENO payload 并可由 worker 加 HMAC header，`channel=slack` 额外冻结 `slack.text/blocks/metadata` 并在投递时只把 Slack payload POST 到 Incoming Webhook URL；`channel=email` 通过 `mailto:` endpoint 冻结 `email.to/subject/text/headers`，worker 使用 `GENO_NOTIFICATION_SMTP_*` 环境变量发送 SMTP 邮件；`GET /v1/runtime-notification-deliveries` 可读取投递状态、attempt、lease、next attempt、response status/body hash/error 和最近审计事件；`make notification-delivery-worker` 提供单次 delivery worker，用 `FOR UPDATE SKIP LOCKED` 领取 queued 或 lease 过期 sending delivery，2xx 标记 delivered，非 2xx/异常按 backoff 回到 queued，达到 max attempts 后进入 `dead_letter`，状态变更统一追加 `runtime_notification_delivery_status_updated`；`make report-export-worker` 提供单次执行 worker：用 `FOR UPDATE SKIP LOCKED` 领取最早可执行 queued job 或 lease 过期 running job，将任务置为 running，调用 `get_runtime_report_artifact()` 渲染对应 Markdown/CSV/PDF/white-label PDF，配置对象存储时归档到 `s3://.../report-artifacts/...`，未配置时写入 `runtime-report-artifact://...` fallback URL，失败时按 backoff 回到 queued，达到 max attempts 后进入 `dead_letter`；`Report Artifact Signed URL` 通过 `/v1/reports/runtime/{report_export_id}/artifact/signed-url` 生成带 `expires_at/signature` 的 HMAC 下载 URL，签名覆盖 report id、type、template、filter、sort 与 actor，防止交付链接被改参。这样白标 PDF 的 runtime artifact、Logo 版本切换、素材元数据登记、预览 URL、扫描状态门禁、控制台预览、导出历史管理、导出任务状态、项目内通知、alert 通知、webhook/Slack Incoming Webhook/SMTP email 外部推送、签名交付入口和审计链共用同一份项目级上下文，避免在 MVP 阶段引入独立主题配置表、报告模板版本管理或可变报告状态表；对象存储原生 presigned URL、CDN token、Temporal/长驻 worker、并发池、邮件模板/退订/服务商 API、Slack App/OAuth/交互式消息、复杂 SLA/值班升级、图片裁剪、真实病毒扫描引擎和对象存储原生版本控制仍放在 P1 后续增强。

Webhook 外发签名已作为上述投递链路的最小安全增强落地：订阅 metadata 可记录 `signing_secret_env` / `webhook_signing_secret_env`，Runtime Console 的订阅表单也暴露 `Signing env` 输入；该签名只用于 `channel=webhook`，`channel=slack` 发送 Slack Incoming Webhook payload 时不附带 `x-geno-*` 签名头；worker 只从环境变量读取 secret，默认 env 为 `GENO_NOTIFICATION_WEBHOOK_SIGNING_SECRET`，不把 raw secret 存入数据库或审计。签名输入固定为 `timestamp.delivery_id.notification_id.payload_sha256`，请求头包含 `x-geno-signature`、`x-geno-signature-timestamp`、`x-geno-signature-version=runtime_notification_webhook_hmac_sha256_v1` 和 `x-geno-signature-input`，接收方可用 delivery id、notification id、payload sha256 与 timestamp 复算完整性。工程已把这套口径抽成 `geno_core.webhook_signing` helper：发送端用 `sign_runtime_notification_webhook()`，接收端可用 `verify_runtime_notification_webhook_signature()` 校验必需 header、HMAC、payload hash 和 timestamp tolerance，并返回可审计失败 reason。若订阅显式指定的 secret env 未配置，worker 不会无签名投递，而是进入现有 retry/dead-letter 状态机并记录错误；默认 env 未配置则保持可选签名语义。该切片仍不是 secret rotation、托管验证服务、订阅鉴权回调、双 secret 灰度窗口、Slack App/OAuth/交互式消息或完整通知平台。

报告必须展示：

- 采集时间窗口。
- 平台覆盖与采集方式（`access_method`）。
- prompt 数量。
- 城市覆盖。
- 样本量（含每 prompt 重复次数 k）与离散度。
- Trigger Rate 与 Mention/Recommendation Rate 两类口径。
- 原始证据链接。
- 评分公式版本摘要。
- 分数解释包：每个总分/平台分/城市分/intent 分的子指标贡献、权重、分母、证据 answer_run_ids。
- 审计摘要：报告版本、导出时间、导出人/系统、score_snapshot_ids、answer_run_ids、是否存在人工补录或人工实体确认。
- API 与消费者界面差异抽检结论。
- AI 答案非确定性说明。

### Step 14：做发布前后复测

复测节奏：

```text
T0：行动前基线
T+7 days：第一次复测
T+14 days：第二次复测
T+30 days：月度复测
```

复测指标：

```text
品牌是否开始出现
品牌推荐率是否上升
平均位置是否上升
引用源是否变化
竞品是否下降
回答是否更本地化
LocalRelevanceScore 是否提升
CitationScore 是否提升
```

效果归因口径：

```text
不做强因果归因
做前后窗口对比
展示行动任务与指标变化的时间线
对同类问题聚合计算趋势
保留所有原始 answer runs
复测沿用同一 prompt_version 和同一 k 次采样口径
```

工程当前先把复测调度落成可审计执行契约，再接 Temporal / Airflow 深度编排：`make au-retest-scheduler-plan` 生成 `docs/runtime_preflight/au-retest-scheduler-plan-latest.json`，固定 T0/T+7/T+14/T+30 四个窗口，每个窗口沿用 `au_dtc_ecommerce_v1`、100 prompts、Australia/Sydney/Melbourne/Brisbane、ChatGPT Search + Perplexity Sonar、k=3，即每窗口 2400 planned runs、总计 9600 planned runs；每个窗口都冻结 collection 命令、manifest 命令、证据输出路径、design-partner gate 和 replay key。`make verify-au-retest-scheduler-plan` 会复算 `retest_scheduler_plan_hash`，校验窗口顺序、计划量、命令 hard gate、证据输出、runtime endpoint 和当前边界。`make au-retest-execution-status` 会读取同一 plan，逐个检查 `docs/runtime_preflight/au-retest-baseline.json`、`au-retest-t-plus-7.json`、`au-retest-t-plus-14.json`、`au-retest-t-plus-30.json` 以及对应 manifest 是否存在、payload hash / manifest hash 是否有效、payload 与 manifest 是否都通过 design-partner gate，并输出 `retest_execution_ready`、`comparison_allowed`、每窗口 `window_ready`、`missing_artifact_count`、`next_action` 和 `retest_execution_status_hash`；`make verify-au-retest-execution-status` 离线复算这些推导。`GET /v1/au-retest-scheduler-plan`、`GET /v1/au-retest-execution-status` 与 Runtime Console 的 AU Retest Scheduler Plan 区块展示同一份 plan hash、执行状态、窗口 readiness、缺失 artifact、下一执行窗口和 `planned_not_temporalized` 边界。当前没有真实 T 窗口产物时，execution status 应保持 `status=fail`、`retest_execution_ready=false`、`comparison_allowed=false`、`missing_artifact_count=8`、`next_action=run_retest_window:baseline`；这代表证据缺失被正确阻断，而不是复测失败。真实执行仍要求 P0a 环境 ready、baseline 通过 design-partner gate，后续再由 Temporal / Airflow 把同一 replay key 编排为可重放工作流。

### Step 15：P2 内容生成和集成

内容生成必须建立在 evidence 和 source gap 上，生成链路复用 `LLMGateway` 与 `VectorStore` 接口。

P2 内容模板：

```text
Best [category] in Australia
[brand] review Australia
[brand] vs [competitor]
How to choose [category] in Australia
[city] guide for [category]
FAQ for Australian customers
Comparison table
Schema.org structured data draft
YouTube script
Reddit-style answer draft
ProductReview response draft
```

生成链路：

```text
source gap / prompt gap
  -> 查 AU 知识事实（VectorStore）
  -> 查 Citation Graph（GraphStore）
  -> 选择 AU 内容模板
  -> 生成内容（LLMGateway）
  -> 人工审核
  -> 创建发布任务或 CMS 草稿
  -> 复测
```

内容生成结果必须关联：

```text
target_question_ids
target_city
target_platform
target_source_type
used_knowledge_fact_ids
source_gap_ids
content_template_id
review_status
human_review_record_ids
```

`review_status` 表示内容草稿自身的默认状态，例如 `pending_human_review`；实际人工判断先追加写入 `human_review_records`，用 `target_type=content_draft`、`target_id=<content_draft_id>` 记录 reviewer、decision、notes 和 `human_review_recorded` 审计事件，再把同项目草稿的 `review_status` 投影为本次复核状态并写入 `content_draft_review_status_updated` 审计事件。该投影只更新状态，不改写草稿正文、知识事实、source gap 或 evidence answer run 绑定。这样内容是否可发布、为何需要修改、由谁审核，能和原始证据、source gap、score snapshot 一起被追溯。`RuntimeHumanReviewQueue` 会把 `pending_human_review` / `needs_changes` 草稿与评分快照放进同一复核列表，已通过的草稿会因 latest review 进入 reviewed 队列，便于一期先做可审计人工复核入口，而不是提前实现复杂审批流。

P2 集成优先级：

```text
Google Search Console
GA4
Shopify
WordPress
Webflow
HubSpot
Cloudflare
Looker Studio / CSV export
```

## 6. 最小可落地版本

最快澳洲首发 MVP 压缩为 3 层、10 个交付项：

```text
P0a Stable Evidence Chain:
1. AU MarketProfile
2. 1 个行业模板 + 100 条 AU Prompt Pack
3. Perplexity Sonar + OpenAI web search 两个稳定采集后端
4. Raw Evidence Store（含 answer_present、surface_triggered、sample_index、CollectionCost）
5. Answer Parser
6. AUVisibilityScore（公式版本化，含 Trigger/Mention 双分母）

P0b Google High-risk Spike:
7. Google AIO / AI Mode 采集 spike（30 prompts、Australia + Sydney、k=2、自建/第三方/人工三路径对比）

P0c Customer Evidence Report:
8. Citation Graph
9. Competitor Benchmark
10. Evidence Report Export（含 Google spike 结论、平台覆盖和降级说明）
```

P0a 开源底座（一键起服）：

```text
PostgreSQL(+pgvector) + MinIO + FastAPI + Next.js
+ LiteLLM + Playwright + simple worker/cron
（Docker Compose 起步，组件按 3.3 选型，接口保留可替换）
```

P0 可延后但保留接口的组件：

```text
ClickHouse：P0a 可先用 PostgreSQL 分区表记录指标；采集量稳定后再迁移
Temporal：P0a 可先用 simple worker/cron；复测和大规模重试进入 P1
Langfuse/promptfoo：P0a 可先用结构化日志和小型评测集；解析器校准期再接入
SearXNG：仅作为传统结果基线，不阻塞 P0a
Metabase：P0c 可用模板导出优先，Metabase 不阻塞报告
```

这个版本不要求：

- 自动生成内容。
- 自动发布。
- 完整知识图谱（用 PG 邻接表起步即可）。
- 多模态素材。
- 全平台采集。
- Google AIO / AI Mode 全量稳定采集（P0b 先给 spike 结论）。
- 强因果归因。

## 7. 研发顺序

| 阶段 | 重点 | 产出 | 主要开源组件 |
| --- | --- | --- | --- |
| 第 0 阶段 | 接口契约与轻量开源底座 | CollectorBackend/ParserEngine/VectorStore 等接口定义、核心 Compose 起服；重组件只保留接口和迁移路径 | FastAPI、PostgreSQL、MinIO、Docker |
| 第 1 阶段 | AU MarketProfile、行业模板、Prompt Pack | 市场配置、1 个行业、100 条问题 | PostgreSQL |
| 第 2a 阶段 | P0a 稳定 AI Answer Runner 和 Raw Evidence Store | Perplexity Sonar + OpenAI web search 两个后端、截图/HTML/引用/触发状态留存、CollectionCost、P0ACollectionReadinessGate、真实 API preflight JSON 落盘 | LiteLLM、MinIO、Playwright、simple worker/cron |
| 第 2b 阶段 | P0b Google AIO / AI Mode spike | 自建浏览器、第三方 SERP、人工补录三路径对比，输出 pass/fail gate | Playwright、第三方 SERP API、MinIO |
| 第 3 阶段 | Answer Parser 和 AUVisibilityScore | 提及/推荐/排名/竞品/引用/本地相关性、双分母、重复采样 | spaCy、Sentence-Transformers、Langfuse、promptfoo |
| 第 4 阶段 | Citation Graph 和 Competitor Benchmark | 信源图谱、竞品压制、source gap | PostgreSQL 邻接表（后续 Neo4j）、ClickHouse |
| 第 5 阶段 | Evidence Report Export | PDF/CSV 报告、证据附录、方法说明 | Metabase、模板引擎 |
| 第 6 阶段 | Action Plan 和复测 | 任务建议、T+7/T+14/T+30 复测 | Temporal/Airflow |
| 第 7 阶段 | Knowledge Facts、Content Engine、Integrations | 本地事实库、内容生成、GSC/GA4/Shopify/WordPress | pgvector、LlamaIndex/LangChain |

## 8. 数据模型增量

> 所有表设计遵循第 3 章的数据契约原则：业务模块只依赖这些表结构，不依赖具体采集/存储实现。

### 8.1 MarketProfile

```text
id
market_code
market_name
locale
timezone
currency
primary_language
platform_weights
city_samples
source_type_weights
status
```

### 8.2 IndustryProfile

```text
id
industry_code
market_code
default_prompt_templates
source_type_weights
competitor_fields
required_local_facts
report_template_id
status
```

### 8.3 PromptQuestion

```text
id
project_id
market_code
industry_code
text
intent_type
city
language
target_brand
competitors
priority
intent_weight
prompt_version
status
```

### 8.4 GeoSample

```text
id
market_code
country
city
language
device
geo_provider
sampling_weight
status
```

### 8.5 AnswerRun

```text
id
project_id
prompt_question_id
platform
surface                 # aio / ai_mode / search / browsing
access_method           # browser / official_api / third_party_api / manual
market_code
city
language
device
model_or_surface
account_state
collector_version
collector_backend_id    # 使用了哪个采集后端实现
answer_present          # 该答案/界面是否出现
surface_triggered       # 目标生成式界面是否触发
sample_index            # 同一 prompt 第几次重复采样
sample_size             # 本轮计划重复次数 k
collected_at
raw_payload_hash
status
```

### 8.6 RawAnswer

```text
id
answer_run_id
answer_text
answer_html_snapshot_url
screenshot_url
raw_payload_url
created_at
```

### 8.7 AnswerCitation

```text
id
answer_run_id
source_url
source_domain
source_title
citation_position
source_type
market_code
created_at
```

### 8.8 AnswerAnalysis

```text
id
answer_run_id
brand_mentioned
brand_recommended
brand_rank
competitors_mentioned
competitor_rank
recommendation_strength
sentiment
local_relevance_score
citation_score
freshness_score
competitor_share_score
au_visibility_score
scoring_formula_version   # 使用的评分公式版本
uncertainty_flags
analysis_version          # 解析器实现/模型版本
parser_engine_id          # 规则 / LLM-as-judge 等实现标识
diagnosis
```

### 8.9 SourceGraph

```text
id
project_id
market_code
source_url
source_domain
source_type
topic
intent_type
brand_mentioned
competitors_mentioned
citation_count
ai_platform_seen
answer_run_ids
authority_score
freshness_score
local_relevance_score
source_gap_type
last_seen_at
```

### 8.10 CompetitorBenchmark

```text
id
project_id
market_code
competitor_name
intent_type
city
mention_rate
recommendation_rate
average_position
citation_count
source_overlap
unique_sources
sentiment_score
local_relevance_score
snapshot_at
```

### 8.11 ActionRecommendation

```text
id
project_id
market_code
source_gap_id
related_prompt_ids
related_answer_run_ids
action_type
evidence_summary
target_source_type
expected_impact
effort_level
owner_id
status
next_check_date
created_at
```

### 8.12 LocalizedKnowledgeFact

```text
id
project_id
market_code
fact_type
subject
predicate
object
city
evidence_source_id
confidence
status
valid_from
valid_until
```

### 8.12.1 KnowledgeFactEmbedding

```text
id
project_id
knowledge_fact_id
embedding_model
embedding
content_hash
created_at
updated_at
```

实现约束：

- `knowledge_fact_id + embedding_model` 幂等 upsert，避免同一 fact 重复索引。
- `embedding_model = fixture-knowledge-embedding-v1` 是当前本地可复盘实现；后续可新增真实 provider 版本，不覆盖旧模型。
- `content_hash` 来自规范化 fact 文本，用于判断 fact 内容与向量索引是否一致。
- 每次内容引擎保存 facts 后追加 `knowledge_fact_embeddings_indexed` 审计事件，记录输入 fact id、输出 embedding id、方法版本和索引原因。
- runtime search 使用 pgvector `<=>` 排序，并保留 AU/global fallback 标记，便于报告和内容建议解释“为什么用了这条事实”。

### 8.13 VisibilityScoreSnapshot（聚合分数，新增）

单条答案分数在 `AnswerAnalysis`；项目/平台/城市/意图维度的加权汇总单独落表，保证报告可复现。

```text
id
project_id
market_code
scope_type            # project / platform / city / intent / prompt
scope_value
scoring_formula_version
platform_weights_snapshot
component_weights_snapshot
sample_size           # 该范围聚合用到的采样总数
trigger_rate
mention_rate
recommendation_rate
au_visibility_score_mean
au_visibility_score_stddev
answer_run_ids
window_start
window_end
created_at
```

### 8.14 BrandEntity / CompetitorEntity / EntityAlias（实体消歧，新增）

支撑解析器做品牌/竞品识别与同名消歧，避免实体误判。

```text
BrandEntity / CompetitorEntity
  id
  project_id
  canonical_name
  official_domains
  parent_company
  product_lines
  status

EntityAlias
  id
  entity_id
  entity_kind           # brand / competitor
  alias
  alias_type            # 别名 / 域名 / 产品名 / 母公司名
  confidence
  confirmed_by          # 同名消歧的人工确认
```

工程当前已落最小运行时闭环：`GET /v1/entity-aliases/runtime/candidates` 从 canonical name、官方域名、产品线和母公司字段生成计算型候选，并排除已确认 alias；同一 read model 还会读取项目内最近已入库的 `raw_answers.answer_text` 与 `answer_citations.domain/url`，用高置信规则生成 `evidence_answer_text` / `evidence_citation_domain` 候选，候选 payload 会带回 `evidence_count`、`evidence_answer_run_ids`、`evidence_urls` 与 `supporting_sources`，便于审核时回查原始 answer run 或 citation。若证据命中的是已有官方域名候选，系统会把证据合并为 supporting evidence，而不是生成重复候选。`POST /v1/entity-aliases/runtime/confirm` 可单条确认，`POST /v1/entity-aliases/runtime/confirm-batch` 可批量确认当前候选，默认先预校验实体存在与项目访问权限，要求同一批 alias 属于同一个 project，并避免失败批次半写入。批量响应返回 `entity_alias_confirm_batch_v1`、成功/失败计数、confirmed records 和 `entity_alias_batch_confirmed` 摘要；系统还会写入一条项目级 `entity_alias_batch_confirmed` 聚合审计事件，但真实主事实仍是每个 alias 的 `entity_alias_confirmed`，后续 `--persist-analysis` 使用确认后的 alias 参与 `rule_based_v2_aliases` parser。候选审核决策已新增最小持久化表 `entity_alias_candidate_reviews`：`POST /v1/entity-aliases/runtime/candidates/review` 可把 `needs_review/rejected/approved`、reviewer、notes 和 answer/citation 证据引用按 `project_id + candidate_id` 幂等保存，写入 `entity_alias_candidate_review_recorded` 审计事件；`POST /v1/entity-aliases/runtime/candidates/review-batch` 可对最多 25 条同项目候选做批量 needs-review / reject / approved，默认先预校验项目和实体，失败不半写入，逐条写 `entity_alias_candidate_review_recorded`，并追加 `entity_alias_candidate_batch_reviewed` 聚合审计摘要。候选列表会返回 `latest_review`，并默认隐藏已 `rejected` 的候选；`GET /v1/entity-aliases/runtime/candidates/reviews` 会按项目、decision、entity_kind、assigned_to、assignment_status、priority 和 due_before 分页返回审核历史、分配队列及最近审计事件，因此被隐藏的 rejected 候选仍可被复盘，已分配 reviewer 的待办也可被单独读取。`POST /v1/entity-aliases/runtime/candidates/assign` 会在既有审核记录上保存 `assigned_to/assigned_by/assignment_status/priority/due_at/assignment_note`，并写入 `entity_alias_candidate_assigned` 审计事件，用于把 reviewer owner、优先级、截止时间和 `assigned/in_progress/blocked/completed` 状态推进纳入可审计链路。Runtime Console 的 Entity Alias 面板已提供单条确认、候选一键确认、`Bulk Alias Review Queue`、批量 mark needs review、批量 reject、逐条 needs review/reject、`Alias Candidate Assignment Queue`、`Alias Candidate Review History` 恢复/改判入口，以及从审核历史分配 reviewer / priority / due date、从 assignment queue 推进 Start / Block / Complete 的轻量表单，并展示 evidence rows / answer run / review audit / assignment audit 引用。该实现仍不是多级审批流、完整 reviewer workbench、SLA 自动升级/通知或黑箱 NLP 自动消歧。

### 8.15 CollectionCost（单位经济，新增）

跟踪每次采集与分析的成本，支撑定价与 unit economics。

```text
id
answer_run_id
project_id
collector_backend_id
llm_provider
llm_tokens
llm_cost
proxy_or_vendor_cost
compute_cost
total_cost
created_at
```

### 8.15.1 ApiBrowserFidelityCheck（API/浏览器保真度抽检，新增）

将"官方 API 答案是否等同于消费者界面答案"从报告里的说明文字升级为可查询、可审计、可重跑的运行时对象。它不替代 `ReportExport.method_disclosure`，而是为 Method Disclosure 提供独立证据。

```text
id
project_id
report_export_id
status                         # not_run / no_overlap / sampled
official_api_records
browser_records
comparable_prompt_city_pairs
mismatch_count
difference_rate
payload                        # 完整 comparison payload 和 summary
payload_hash
answer_run_ids
checked_by
checked_at
```

实现约束：

- 同一批次优先按 `report_export_id -> report_evidence -> answer_run_ids` 取样；没有 report 时可按项目当前 answer runs 生成临时 check。
- 只比较同一 `prompt_question_id + city` 下的 `official_api` 与 `browser` access method；没有 browser 样本时状态为 `not_run`，两类样本没有交集时状态为 `no_overlap`。
- `payload_hash` 冻结比较口径；Runtime Console 和报告方法说明展示 status、official/browser 记录数、comparable pairs、mismatch count、difference rate 和 hash。
- 每次生成或重跑 check 追加 `api_browser_fidelity_checked` 审计事件，记录输入 report/answer_run ids、输出 check id、方法版本和 actor。
- P0c 可先由 worker 在 `--persist-analysis` 后自动生成；启用 `--include-browser-fidelity-fixture` 时，报告 Method Disclosure 的 fidelity payload 使用全量 official_api + browser 抽检样本，但报告证据附录、score rate denominators 和 `VisibilityScoreSnapshot.answer_run_ids` 仍只使用 `score_input_records`；`GET /v1/fidelity-checks/runtime/trend` 已把最近 checks 聚合为可解释趋势摘要，并由 Runtime Console 展示；`make browser-fidelity-plan` 负责生成可审计、可复跑的 prompt/city 抽样计划，`scripts/run_browser_fidelity_scheduler.py` / Compose `scheduler` profile 负责把计划生成和可选执行包装成 cron/K8s CronJob 可消费的 JSON 调度入口；启用 `--include-browser-fidelity-playwright` 时可把真实 browser collector 加入 API 批次，先用 `make api-browser-fidelity-preflight` 验证启用开关、selector、session state 和 Playwright 依赖；采集执行可用 `CollectionExecutionPolicy` 做 worker 内重试/backoff/节流并保留 attempt 审计；配置 `GENO_BROWSER_ARTIFACT_DIR` 与对象存储后，浏览器截图/HTML 可归档为 `s3://...` EvidenceAsset；`make au-launch-status` 会把 P0a design partner 状态、P0b Google 主评分准入和 P0c 报告方法披露本地合同合并为 `ready_for_customer_report_handoff`、`next_action`、remaining blockers 与 hash，可作为真实客户报告交付前的总控准入检查；`make au-launch-remediation-plan` 会把 remaining blockers 一一映射到 work item、命令、验证命令、证据产物和外部依赖类型，当前本地 29 个 blocker 可复算收敛为 8 个清障 work item，下一步为 `p0a_environment`，其中 P0a 环境项已先包含 `make verify-au-p0a-env-template`，再包含 `make au-p0a-environment-checklist` 和 `make verify-au-p0a-environment-checklist`，用于在复制真实 env 前固定模板安全、脱敏变量清单、setup/verification commands 与证据输出路径；P0b Google work item 已先包含 `make verify-au-p0b-google-env-template`，再包含 `make au-p0b-google-execution-checklist` 和 `make verify-au-p0b-google-execution-checklist`，用于固定 Google env 模板安全、selector/manual path/DB/smoke/health/full spike 的脱敏执行清单和 hard gate 命令；`make au-retest-scheduler-plan` / `make verify-au-retest-scheduler-plan` 已把 T0/T+7/T+14/T+30 复测 replay key、每窗口 2400 planned runs、collection/manifest 命令、证据输出和非 Temporal 边界冻结为可复算计划；`make au-retest-execution-status` / `make verify-au-retest-execution-status` 已把每个复测窗口的 payload/manifest 存在性、hash、design-partner gate、missing artifact、comparison allowed 和 next action 冻结为可复算状态；`make au-handoff-dossier` 会把 launch status、remediation plan、P0a environment checklist 摘要、P0b Google execution checklist 摘要、stage summary、blocker 分布、source file sha256、下一 work item、runtime endpoint 和 Markdown 交接稿合成 `docs/runtime_preflight/au-handoff-dossier-latest.json/.md`，`make verify-au-handoff-dossier` 默认证明交付状态总包自洽，`--require-customer-ready` 才作为客户报告交付硬门禁；同一状态、清障计划、P0a 环境清单、P0b Google 执行清单、AU 复测调度计划、AU 复测执行状态和交付总包已通过 `GET /v1/launch-status/au`、`GET /v1/launch-remediation-plan/au`、`GET /v1/p0a-environment-checklist/au`、`GET /v1/p0b-google-execution-checklist/au`、`GET /v1/au-retest-scheduler-plan`、`GET /v1/au-retest-execution-status`、`GET /v1/handoff-dossier/au` 暴露给 runtime，并在 Runtime Console 首页 AU Launch Gate / Action Plan & Retest Detail 面板展示 P0a/P0b/P0c 摘要、剩余 blocker、next action、remediation work items、missing required/recommended env、Google missing env/selector、environment/checklist hash、hard gate、复测计划 hash/窗口/命令/边界、复测执行 status/window readiness/missing artifacts/comparison allowed、handoff dossier readiness、客户交付硬门禁、Markdown hash、验证命令和查询路径；P1 再补真实账号/selector 联调、真实周期样本数据、分布式失败重试队列和 Temporal 深度编排。

### 8.16 AuditEvent（审计事件，新增）

记录系统、用户、worker 对关键对象的修改和运行事件，支撑客户质询、内部排障和报告复盘。

```text
id
event_type
project_id
actor_type              # user / system / worker / api
actor_id
target_type             # project / prompt / answer_run / analysis / score_snapshot / report
target_id
before_hash
after_hash
input_refs              # prompt_question_ids / answer_run_ids / source_ids
output_refs             # analysis_ids / score_snapshot_ids / report_export_id
method_version          # collector_version / parser_version / scoring_formula_version
reason
created_at
```

### 8.17 ReportExport（报告版本快照，新增）

报告导出是不可覆盖的版本快照。每次导出生成一条新记录，保证同一客户在不同时间看到的数字可以复盘。

```text
id
project_id
market_code
report_version
report_type             # internal_demo / design_partner / customer
score_snapshot_ids
answer_run_ids
prompt_version
scoring_formula_version
platform_weights_snapshot
sample_size
window_start
window_end
methodology_hash
pdf_url
csv_url
exported_by
exported_at
```

### 8.18 ScoreContribution（分数解释贡献，新增）

保存每个聚合分数的子指标贡献，避免报告只给总分、无法解释"为什么是这个分"。

```text
id
score_snapshot_id
component_name           # Mention / Recommendation / Position / Citation / LocalRelevance ...
component_score
weight
weighted_contribution
denominator
evidence_answer_run_ids
positive_evidence_summary
negative_evidence_summary
confidence_note
created_at
```

### 8.19 EvidenceLink（证据关联表，新增）

替代大数组的长期方案。P0 可以先保留 `answer_run_ids` 数组，但必须同步设计关联表，便于后续查询、分页和审计。

```text
SourceGraphEvidence
  id
  source_graph_id
  answer_run_id
  answer_citation_id
  relation_type          # cited_by_ai / competitor_only / source_gap / stale_source
  created_at

ScoreSnapshotRun
  id
  score_snapshot_id
  answer_run_id
  contribution_role      # numerator / denominator / excluded / google_limited_coverage
  created_at

ReportEvidence
  id
  report_export_id
  answer_run_id
  evidence_role          # score_input / appendix / google_spike / manual_backfill
  created_at
```

## 9. 一期验收标准

澳洲首发 P0 技术验收：

- 可创建 `market = AU` 的 GEO 项目。
- 可选择 1 个行业模板并生成 100 条澳洲问题集。
- 可配置 3-5 个竞品。
- **P0a 稳定链路**：可完成 Perplexity Sonar 与 OpenAI web search 两个平台采集，每条有 answer、citation、screenshot 或 HTML 快照；真实 key 上线前先跑 `make api-preflight`，并把成功/失败 JSON 固定落到 `docs/runtime_preflight/api-preflight-latest.json` 或 `GENO_API_PREFLIGHT_OUTPUT_PATH` 指定路径，供审计复盘。预检 JSON 必须包含 `preflight_summary`、`preflight_audit_checklist` 和 `preflight_payload_hash`，用 `phase`、`exit_code`、`ready_for_design_partner`、gate failure reasons、`recommended_next_action`、阻塞原因、证据字段引用、replay args 和 canonical JSON sha256 明确说明当前是否可扩大到真实 AU design-partner 批次，并能通过 `make verify-api-preflight` 复算 stdout/落盘文件是否一致；`make preflight-manifest` 必须生成含 preflight 文件 sha256、verifier 结果、阻塞原因、worker args 和 `manifest_payload_hash` 的审计索引；`make au-p0a-runbook` 必须生成 preflight、5 prompt small batch 和 100 prompts × 4 geo full batch 的机器可读命令计划，且 `make verify-au-p0a-runbook` 必须复算 runbook hash 并校验步骤顺序、planned runs 与 gate 参数；`make verify-au-p0a-env-template` 必须在复制或填写真实 `.env.au-p0a` 前校验已提交 `.env.au-p0a.example` 的必需键、空 provider key、本地占位 `DATABASE_URL`/对象存储配置、runtime 输出路径和疑似 secret 标记；`make au-p0a-env` 必须生成不泄露 secret 的脱敏环境报告并由 `make verify-au-p0a-env` 复算 hash；`make au-p0a-environment-checklist` 必须把 runbook、environment report 和 status 摘要合并为脱敏配置清单，列出必填 provider/database 变量、推荐对象存储变量、setup commands、hard gate、DB readiness、证据输出路径和 `environment_checklist_hash`，且 `make verify-au-p0a-environment-checklist` 必须复算 hash、summary 计数、脱敏约束和命令完整性，并要求 setup commands 包含 env template gate；`make au-p0a-runbook-dry-run` 必须读取同一份 `GENO_AU_P0A_ENV_FILE` / `.env.au-p0a`，按“进程环境优先、文件只补缺”的规则把 env-file 值注入执行环境，并在不执行外部 provider 调用的前提下输出步骤、产物、external_call_risk、环境缺口、ready_to_execute、env-file 元数据和 execution_payload_hash；输出只能包含来源、长度、sha256 前缀和 `secrets_redacted=true`，不得落原始 secret，且 `make verify-au-p0a-runbook-execution` 必须离线复算 execution hash、步骤计数、dry-run invariant 和 forbidden secret field；`make au-p0a-readiness` 必须读取同一份 `GENO_AU_P0A_ENV_FILE` / `.env.au-p0a`，在 preflight、small_batch、full_batch 阶段分别输出脱敏 env-file metadata、环境、runbook、上游 payload/manifest gate 的机器可读 readiness，真实执行前可开启 `GENO_AU_P0A_REQUIRE_DB_CHECK=1` 对 env-file 或进程环境里的 `DATABASE_URL` 强制只读 PostgreSQL 连通性检查；`make au-p0a-package` 必须生成汇总 runbook/environment report/runbook execution/readiness/preflight/small/full 产物 hash、ready 状态、缺失项和 package hash 的证据包清单，且 `make verify-au-p0a-package` 必须离线复算 package hash 与 summary/artifacts 一致性；`make au-p0a-status` 必须用同源 env-file 复算三阶段 readiness，并生成包含 runbook、environment report、runbook execution、package verifier、completion/design-ready 百分比、remaining blockers 和 next action 的总控状态报告，且 `make verify-au-p0a-status` 必须离线复算 status report hash、completion、remaining blockers 与 next action。进入 design partner 前还必须让 `python3 scripts/verify_preflight_payload.py --require-design-partner-ready` 通过。
- **P0a 脱敏硬门禁**：environment report、environment checklist、runbook execution、evidence package 和 status report verifier 必须递归拒绝 `value` / `raw_value`，保证 env-file、process env 与数据库连接串不会因为手工拼包、hash 重算或状态汇总进入可提交证据。
- **P0a execution checklist 总控门禁**：`make au-p0a-execution-checklist` / `make verify-au-p0a-execution-checklist` 必须把 env template gate、environment checklist、runbook dry-run、preflight、small batch、full batch、package/status hard gates、setup/execution/verification commands、12 个证据输出路径、completion/design-ready 百分比和 remaining blockers 汇总为 `docs/runtime_preflight/au-p0a-execution-checklist-latest.json`；`GET /v1/p0a-execution-checklist/au`、handoff dossier 和 Runtime Console 必须读取同一清单。该清单用于交接“当前还差什么”和“下一步按什么命令跑”，不允许用缺失真实 provider env、small/full batch 证据的 blocked 状态冒充 design partner ready。
- **P0b Google spike**：可完成 Google AIO / AI Mode 的限时采集验证，输出 pass/fail gate、触发率、失败原因、成本/耗时估算和样本证据。
- `GoogleSpikeReadinessGate` 必须在 worker/API 合同中可见，明确区分“Google 是否可进主评分分母”和“P0b 是否完成两路径对照”。
- `score_input_policy` 必须冻结在评分审计和 Report Method Disclosure 中，列出 all/score-input/excluded answer_run_ids，证明未过双 gate 的 Google 证据没有进入主评分分母。
- API-vs-browser fidelity samples 必须同样经过 `score_input_policy` 排除出主评分分母，只作为保真度抽检、方法披露和审计证据；报告分母不能因 browser 抽检样本膨胀。
- **每个平台的采集后端可插拔**：P0a 至少两个官方 API 后端可工作；P0b 至少对比自建浏览器、第三方 SERP API、人工补录中的两条路径；新增后端不改业务代码。
- 每条采集结果有 answer、citation、screenshot 或 HTML 快照；官方 API 的 HTML snapshot 在对象存储可用时必须归档为可追溯 `s3://...` EvidenceAsset，未配置对象存储时保留 `geno-api-snapshot://...` 与 content hash。
- 每条采集结果记录平台、surface、access_method、城市、语言、设备、采集时间、collector_version 和 collector_backend_id。
- **每条采集结果记录 `answer_present` / `surface_triggered`**，报告能区分 Trigger Rate 与 Mention/Recommendation Rate，并在 `method_disclosure.score_rate_denominators` 中冻结分母定义。
- **审计链路可用**：采集、解析、评分、人工补录、实体确认、报告导出都写入 `AuditEvent`。
- **溯源链路可用**：任意报告数值都能从 `ReportExport -> VisibilityScoreSnapshot -> ScoreContribution -> AnswerAnalysis -> AnswerRun -> RawAnswer/AnswerCitation/EvidenceAsset` 追溯。
- **解释包可用**：任意总分/平台分/城市分/intent 分都能展示子指标贡献、权重、分母、正负证据和局限说明。
- P0a 每条 prompt 支持 k=3 重复采样（`sample_index`），评分展示均值与离散度；P0b Google spike 可先用 k=2，通过健康闸门后再升到 k=3。
- 每个 collector_backend 写入 `CollectionCost`；报告能展示 planned_runs、成功率、平均耗时和单位成本。
- `P0ACollectionReadinessGate` 必须在 worker/API 合同中可见，自动检查 required platforms、必备元数据、`answer_present/surface_triggered`、citation、screenshot/HTML 和 k=3；真实 API 批次未通过 gate 时不能进入 design partner 试点。`collector_health_gate` 失败也必须在采集前输出并落盘，例如缺 Perplexity/OpenAI key 时记录 `not_configured`，避免把配置问题误判为平台采集结果。
- 可自动解析品牌提及、推荐、排名、竞品、引用源和本地相关性。
- 可生成可拆解、公式版本化的 `AUVisibilityScore`。
- 可生成 Citation Graph。
- 可输出 3-5 个竞品的 Benchmark。
- 可识别 source gap。
- 可导出包含方法说明（含 API/消费者界面差异抽检结论、Google spike 结论、平台覆盖/降级口径）、审计摘要、分数解释包和原始证据附录的 PDF/CSV 报告；工程实现必须把审计摘要冻结到 `ReportExport.method_disclosure.audit_summary`，并在 Markdown/PDF/runtime artifact 中展示事件数量、事件类型分布、target 类型、method version、actor 类型、input/output ref keys、事件时间窗和代表性 audit event ids；`make au-p0c-report-package` 必须生成可复算 P0c 报告交付包，至少覆盖 Markdown/CSV/PDF/白标 PDF artifact hash、API-vs-browser fidelity sampled 口径、Method Disclosure、Audit Summary 和 `ReportExport -> VisibilityScoreSnapshot -> AnswerRun` traceability 合同；真实客户报告交付前必须通过 `make au-launch-status` / `make verify-au-launch-status` 的 hash 自洽检查，并用 `make au-launch-remediation-plan` / `make verify-au-launch-remediation-plan` 把未 ready 的 blocker 固定到可执行清障计划；交接时必须用 `make au-handoff-dossier` / `make verify-au-handoff-dossier` 生成 JSON+Markdown 总包，冻结 launch/remediation hash、P0a environment checklist hash/缺项、P0a execution checklist hash/remaining blockers、source file sha256、blocker 覆盖、下一 work item 和 Markdown hash；同时可通过 `GET /v1/launch-status/au`、`GET /v1/launch-remediation-plan/au`、`GET /v1/p0a-environment-checklist/au`、`GET /v1/p0a-execution-checklist/au`、`GET /v1/handoff-dossier/au` 与 Runtime Console AU Launch Gate 做人工复核；需要硬门禁时运行 `scripts/verify_au_launch_status.py --require-ready` 或 `scripts/verify_au_handoff_dossier.py --require-customer-ready`。
- 报告溯源必须有可分享的独立详情入口：`/traceability?project_id=...` 已复用 `GET /v1/projects/runtime`、`GET /v1/traceability/runtime` 与 `GET /v1/citation-graphs/runtime`，展示 report、score、answer run、source graph、action、content draft、audit event 和 evidence link 节点，并保留与 Runtime Console 相同的锚点深链。该页用于客户质询或内部复盘时直接打开一份项目级溯源视图；P1 再增强为可拖拽、可缩放、可筛选的大图谱工作台。

架构验收（开源·可插拔）：

- P0a 必须完成接口级可插拔：CollectorBackend、ParserEngine、ScoringFormula、ReportExporter 均有 stub 与至少一个工作实现，并用合约测试证明真实实现满足协议签名。
- 向量库、图库、LLM 供应商的替换演示不阻塞 P0a 客户试点；P0c/P1 前至少各演示一次"替换/切换后业务不变"：向量库 pgvector ↔ Qdrant、图库 PG 邻接表 ↔ Neo4j、LLM 供应商经 LiteLLM 切换。当前 `VectorStore` 已有 pgvector 与 Qdrant projection 的本地合约测试，证明 deterministic embedding search 排序口径一致；`GraphStore` 已有 PG adjacency 与 Neo4j projection 的本地合约测试，证明 Citation Graph 关键查询口径一致；`LiteLLMGateway` 已可注入 `LLMJudgeAnswerParser` 和 `analyze_and_score_records()`，并保留成功/失败调用日志；chat 路径已具备 retry/backoff、重试错误留痕和上游响应 cost 优先读取；Compose 已提供可选 `llm-gateway` profile 与 `collector-worker-litellm`。真实 Qdrant/Milvus service、真实 Neo4j driver/container、真实 provider key 联调、供应商路由选择和账单 reconciliation 仍需完成。
- 解析器规则实现与 LLM-as-judge 实现可对同一答案并行对比并保留版本。
- 评分公式可升级到新版本，历史分数仍可按旧版本重算。

P1 技术验收：

- 可基于 source gap 生成 Action Plan。
- 可维护 AU 本地化知识事实。
- 可创建任务 owner、状态和 next_check_date。
- 可按 T+7/T+14/T+30 复测。
- 可在报告中展示前后窗口变化。

## 10. 结论

澳大利亚首发仍然复用 GENO 的底层逻辑，但落地顺序要调整：

```text
先做证据平台
再做信源图谱
再做竞品差距
再做行动建议
再做复测报告
最后再做内容生成、自动分发和集成
```

工程实现上，最关键的不是先把内容生成做完整，而是把以下能力做扎实：

- `AU Market Profile`
- `Prompt Pack`
- `AI Answer Runner`（可插拔采集后端，AIO/AI Mode 分离，记录触发状态）
- `Raw Evidence Store`
- `Answer Parser`
- `Citation Graph`
- `Competitor Benchmark`
- `Evidence Report Export`

并且全程坚持三条架构硬约束——**开源优先、模块化松耦合、可插拔替换**：每个能力对应一个明确接口和一套开源选型，采集后端、向量库、图库、LLM 供应商、解析器、评分公式都能独立替换。这样既能在 MVP 阶段用最小开源底座快速跑通，又能在平台改版、规模增长或商业化降本时逐块替换而不重写系统。

这条路径更适合澳大利亚首发，因为它能更快形成客户可验证价值，也能为后续内容生成、分发和多市场扩展打下可审计、可替换的数据与工程基础。
