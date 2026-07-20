# GEO 效果优先整改决策记录

> 创建日期：2026-07-18
> 最后更新：2026-07-19
> 决策依据：`GEO_REQUIREMENTS.md`、`GEO-project-full-audit-2026-07-18.md`
> 适用范围：当前项目 GEO 整改取舍
> 核心约束：开发产能有限，优先处理直接影响实际使用效果的问题
> 维护方式：A-E 五组逐组讨论；用户确认后在本文件记录最终处置意见
> 统一实施计划：`docs/engineering/GEO-accepted-remediation-implementation-plan-2026-07-19.md`

## 1. 决策原则

本记录不以“补齐成熟 GEO 平台全部功能”为近期目标，而以尽快形成稳定、正确、可验证的实际效果闭环为目标。

近期所称“效果”主要指：

1. 目标内容能够正确生成，并使用正确的 Campaign、渠道和 Prompt。
2. 内容能够由人工发布到真实目标位置。
3. 发布结果可以公开访问，正文、链接和必要披露符合批准版本。
4. 内容具备被抓取、索引、引用和正确表述的基础条件。
5. 能使用最低成本的人工或外部工具确认效果，而不强制把全部能力内建到平台。

统一取舍原则：

- 能直接阻断或扭曲效果的问题优先实现。
- 成熟平台能力若可由人工流程、外部工具或受控脚本可靠替代，可以暂缓内建。
- 不为追求成熟度等级而开发暂时不影响实际使用的功能。
- “暂缓”不等于风险消失；涉及公开暴露、多租户、客户数据或正式生产时，应重新检查安全前置条件。
- 已决定实施的功能必须具备明确范围和验收标准，防止实现过程中扩张成完整平台重构。

## 2. 状态定义

| 状态 | 含义 |
|---|---|
| `ACCEPTED` | 已确认按本文件范围实施 |
| `ACCEPTED_RISK` | 已了解风险，当前阶段明确选择不处理 |
| `MANUAL_WORKAROUND` | 暂不建设完整功能，使用明确的人工或外部工具流程 |
| `OUT_OF_SCOPE` | 经业务边界确认不属于当前平台职责 |
| `DEFERRED` | 当前阶段不处理，到指定条件出现时重新评估 |
| `NEXT_PHASE_REQUIRED` | 当前阶段不实施，但已确认是下一阶段必须建设的能力 |
| `REJECTED` | 明确不采用该处置方案 |
| `PENDING` | 尚未完成讨论和决策 |

## 3. 分组进度

| 分组 | 定位 | 问题数 | 状态 |
|---|---|---:|---|
| A | 直接阻断或扭曲当前使用效果 | 4 | `COMPLETED` |
| B | 会影响效果，但可以暂时人工替代 | 6 | `COMPLETED` |
| C | 效果测量、判断和优化能力 | 7 | `COMPLETED` |
| D | 生产安全、数据诚信和运行可靠性 | 5 | `COMPLETED` |
| E | 工程质量、性能和使用体验 | 5 | `COMPLETED` |

## 4. A 组：直接阻断或扭曲当前使用效果

### A 组决策摘要

| ID | 问题 | 最终决策 | 状态 |
|---|---|---|---|
| F-001 | 生产环境阻断必要外部访问 | 增加独立 egress 网络，只允许必要服务外连 | `ACCEPTED` |
| F-011 | 发布与验证链未闭合 | 保留人工发布，只修 URL 验证契约和最小发布结果验证 | `ACCEPTED` |
| F-012 | 多 Campaign 上下文串数据 | 完整修复多 Campaign 上下文，前后端共同校验归属 | `ACCEPTED` |
| F-014 | Prompt 与渠道绑定错误 | 每个渠道显式选择 approved Prompt Release | `ACCEPTED` |

### F-001：增加独立 egress 网络

#### 最终处置

保留生产 `backend` 内部网络，用于 Postgres、Valkey、MinIO 和应用间通信；新增独立、非 internal 的 `egress` 网络，只连接确实需要访问外部资源的服务。

初始允许连接 egress 的服务范围：

- Internal API：OIDC discovery/JWKS、Knowledge URL 获取等。
- Task Worker：DeepSeek、发布 URL 验证及其他后台外部任务。
- 其他服务只有在存在实际外连用例和测试证据后才加入。

#### 实施要求

- Postgres、Valkey、MinIO 不连接 egress。
- egress 网络不发布新的宿主机入站端口。
- 保留现有 edge/backend 入站与数据网络边界。
- 外部请求继续使用现有 SSRF、超时、重试和日志规则。
- 在生产等价 Compose 配置中增加网络拓扑测试，防止后续误删 egress。

#### 当前明确不做

- 暂不建设统一 egress proxy。
- 暂不建设完整域名/IP allowlist 管理中心。
- 暂不引入 service mesh 或完整零信任网络改造。

#### 验收标准

1. 生产等价环境能够完成 OIDC discovery/JWKS 获取。
2. Worker 能够完成一次受控模型调用。
3. Internal API 能够获取允许的公开 Knowledge URL。
4. Worker 能够验证允许的公开发布 URL。
5. Postgres、Valkey、MinIO 没有新的外部入口，且不加入 egress。
6. 未配置 egress 的后端服务仍不能直接访问外网。

### F-011：人工发布加最小发布结果验证

#### 最终处置

所有内容继续由人工发布。平台不负责操作第三方 CMS 或渠道账号，但必须验证人工发布后的结果，避免把“填写了 URL”误判为“正确上线”。

保留的最小流程：

```text
系统导出批准版本
-> 运营人员人工发布
-> 运营人员录入正式 URL
-> 系统执行最小 URL 验证
-> 保存验证结果和失败原因
```

#### 实施要求

- 修复 Publication 到 URL verifier 的参数契约。
- `required_disclosures` 必须始终显式传递：需要披露时传具体规则，不需要时传空列表，不能省略字段。
- 验证 URL 可公开访问且响应状态合格。
- 验证页面包含批准版本的关键正文或稳定内容指纹。
- 验证必要目标链接存在。
- 渠道要求披露时验证披露文本存在。
- 保存验证时间、结果、失败原因和验证规则版本。
- 验证失败后由人工修正页面，再显式重试；不得自动重新调用模型。

#### 当前明确不做

- 不建设 CMS 自动发布。
- 不自动创建或更新第三方草稿。
- 不实现 IndexNow、Sitemap 自动更新、Feed 提交或自动删除通知。
- 不因输入了 URL 就自动标记发布完成。

#### 验收标准

1. 不需要披露的渠道以空列表完成验证，不再因字段缺失进入 `retry_wait`。
2. 需要披露但页面缺少披露时验证失败，并给出可操作原因。
3. 错误 URL、非公开页面、错误正文、缺少目标链接均验证失败。
4. 正确人工发布页面验证成功并保存证据。
5. 重试 URL 验证不会触发新的付费模型生成。

### F-012：完整修复多 Campaign 上下文

#### 最终处置

继续支持一个 Project 下多个 Campaign，不通过限制单 Campaign 规避问题。Campaign 必须成为 Protocol、Destination、Opportunity、Job、Publication、Submission 和测量数据的根上下文。

#### 实施要求

- 切换 Campaign 时清除所有不属于新 Campaign 的下游 URL 参数和本地选择状态。
- 不再独立选择项目内“第一条 Campaign”和“第一条 Protocol”。
- 前端请求必须携带当前 Campaign 上下文。
- 后端对 `protocol_id`、`destination_id`、`opportunity_id`、`job_id`、`publication_id` 和 `submission_id` 执行归属校验。
- 无效或跨 Campaign ID 必须返回明确的 404/409/422，不能静默回退到第一条数据。
- 页面、动作 payload、数据库写入和后续导航必须保持同一 Campaign。

#### 当前明确不做

- 不删除多 Campaign 能力。
- 不依赖运营人员手工检查 URL 参数。
- 不只修前端而保留后端越界写入可能性。

#### 验收标准

1. 使用至少两个 Campaign、每个 Campaign 至少两个 Destination 的 fixture。
2. 切换 Campaign 后旧 Protocol/Destination/Job/Publication/Submission 参数全部失效或清除。
3. 跨 Campaign 读取和 mutation 在后端被拒绝。
4. 浏览器测试验证页面内容、URL、动作 payload 和数据库写入始终属于当前 Campaign。
5. 返回、刷新和深链接不会恢复旧 Campaign 的下游上下文。

### F-014：渠道显式绑定 approved Prompt Release

#### 最终处置

不再自动使用“项目第一条 Skill”或“最新 Release”。运营人员必须为每个实际渠道任务显式选择一个已批准的 Prompt Release，并保存绑定关系。

#### 实施要求

- 在 Destination/Opportunity 的实际生成上下文中保存明确的 `prompt_release_id`。
- 只能选择状态为 approved 的 Release。
- Prompt Bundle 必须从当前 Campaign、当前渠道任务的绑定生成。
- 生成记录必须保存实际使用的 Release ID、版本和 hash。
- Release 更新后不得静默替换历史绑定；必须由运营人员显式变更。
- 渠道就绪度不能只检查记录数 `>= 9`。
- 就绪度至少检查九个唯一目标渠道、当前 Campaign 归属、Destination policy、approved Prompt Release、必要 Evidence 和阻断状态。

#### 当前明确不做

- 暂不建设复杂的自动渠道 Prompt 推荐或自动迁移机制。
- 不允许所有渠道默认共用一个通用 Prompt。
- 不允许以“第一条”或“最新版本”作为隐式选择规则。

#### 验收标准

1. 九个渠道分别绑定不同 Release 时，生成结果记录的 Release ID/hash 与选择一致。
2. 未绑定、未批准、已撤销或跨 Campaign Release 均不能生成正式 Bundle。
3. 发布新 Release 不改变已有任务的历史绑定。
4. 重复渠道、blocked Destination 或缺 Prompt 的任务不计入完成度。
5. 操作者可以在生成前明确看到并确认当前渠道使用的 Prompt Release。

### A 组实施顺序

建议按以下依赖关系实施：

1. F-012：先保证所有操作写入正确 Campaign。
2. F-014：再保证正确 Campaign 使用正确渠道 Prompt。
3. F-011：闭合批准版本到人工发布结果的验证。
4. F-001：在生产等价拓扑中开放必要外连并执行端到端验收。

F-001 的基础设施修改可以与 F-012/F-014 并行，但 A 组只有在四项验收全部通过后才算整体完成。

## 5. B 组：影响效果但可人工替代

### B 组决策进度

| ID | 问题 | 当前决定 | 状态 |
|---|---|---|---|
| F-005 | 缺少传统 SEO 与逐 URL 技术资格底座 | 不建设独立 SEO 审计；渠道使用 F-011，官网由官网团队或外部工具检查 | `MANUAL_WORKAROUND` |
| F-008 | 缺少爬虫用途策略中心 | 不管理渠道网站或公司官网 robots/WAF，排除出当前平台范围 | `OUT_OF_SCOPE` |
| F-010 | 证据真实性、时效与 Claim-citation 蕴含检查不足 | 原型阶段不处理，后续设立专门合规阶段 | `DEFERRED` |
| F-013 | Knowledge 到正式 Evidence 的 UI 工作流断裂 | 增加最小 Fact -> Evidence UI | `ACCEPTED` |
| F-019 | 问题体系、内容库存和实体图谱过薄 | 复用成熟 RAG 组件建设事实/实体、测试问题和内部仿真测评核心模块 | `ACCEPTED` |
| F-026 | Prompt Injection、YMYL、版权和保留策略不完整 | 采用原方案 4，当前不增加限制或治理能力 | `ACCEPTED_RISK` |

### F-005：不建设独立 SEO 审计模块

#### 最终处置

当前平台不承担第三方渠道或公司官网的完整技术 SEO 审计职责，不建设站点 crawler、渲染器、索引诊断或 Search Console 类平台能力。

#### 替代流程

- 第三方渠道：使用 F-011 的最小发布结果验证，确认 URL 公开、正文正确、必要链接和披露存在。
- 公司官网：由官网团队或外部 SEO 工具负责 robots、noindex、canonical、Sitemap、渲染和索引资格检查。
- 当前平台可以保存人工检查结论或外部报告引用，但不负责自动采集和诊断。

#### 重新评估条件

平台开始托管页面、提供客户网站 SEO 审计，或实际发现官网页面因抓取/索引技术问题无法产生效果时重新评估。

### F-008：Crawler 用途策略中心不属于当前范围

#### 最终处置

平台不配置或管理第三方渠道网站和公司官网的 robots、WAF、CDN 或 crawler 用途策略。第三方渠道由渠道运营方负责，公司官网由官网技术团队负责。

#### 当前明确不做

- 不建设 Search/Training/User-fetch crawler matrix。
- 不生成或修改 robots.txt。
- 不管理官方 crawler IP、WAF allowlist 或 CDN 规则。
- 不对第三方渠道 crawler 策略作可控性承诺。

#### 重新评估条件

平台开始托管客户页面、管理客户站点技术配置，或业务明确要求分别控制搜索抓取与训练授权时重新评估。

### F-010：延后到专门合规阶段

#### 最终处置

当前原型以可用、好用和验证实际效果为目标，不建设来源真实性、证据时效、冲突检测、自动 Claim-evidence 蕴含或 YMYL 加强审查。

#### 当前明确不做

- 不实现自动来源真实性检查。
- 不实现自动证据过期和冲突检测。
- 不实现 LLM Claim-evidence 蕴含评分。
- 不因最高级、比较或体验型表述增加新的系统审核门禁。

#### 重新评估条件

进入独立的合规治理阶段，或项目开始承接需要强事实审查、监管审查、自动发布的正式生产内容时重新设计。

### F-013：增加最小 Fact -> Evidence UI

#### 最终处置

在 Knowledge 工作区为 approved Fact 增加创建正式 Evidence 的最小 UI，闭合 Knowledge 到 Evidence Pack 的日常运营流程。

#### 实施要求

- 只有 approved Fact 可以发起转换。
- 操作者确认 Evidence 标题、证据片段、来源 URL、引用信息、使用权和公开范围。
- 保存 Knowledge source/document/fact 到 Evidence 的 lineage。
- 修正 `public_domain` 与 `public_reference` 的枚举不一致。
- 防止同一个 Fact 无提示地重复创建 Evidence。
- 创建 Evidence 后仍沿用现有 Evidence 状态和人工流程，不自动进入正式发布。

#### 当前明确不做

- 不自动把全部 approved Fact 转成 Evidence。
- 不增加 F-010 已决定延后的真实性、时效或蕴含引擎。
- 不在本项中重构整个 Knowledge 或 Evidence 数据模型。

#### 验收标准

1. 操作者可以完全通过 UI 从 approved Fact 创建 Evidence。
2. 未批准 Fact、缺必要元数据或无权项目成员不能创建。
3. 新 Evidence 能进入现有 Evidence Pack 流程。
4. 页面可追踪回原 Knowledge source、document 和 fact。
5. 枚举在前端、API、Domain 和脚本中保持一致。

### F-019：复用成熟 RAG 组件建设核心模块

#### 最终处置

F-019 不再按“可用表格长期替代”的普通缺口处理。采用成熟开源 RAG 组件作为可替换引擎，在其上二次开发项目专属的内容事实库、实体关系、GEO 测试问题生成和内部仿真测评能力。

#### 技术边界

- 以 LlamaIndex 作为首选的内嵌图提取、检索和 RAG 编排组件，优先验证其 Property Graph、严格实体/关系 schema、缓存和文档去重能力。
- 现有 Knowledge、Catalog、Evidence 和 PostgreSQL 领域表继续作为唯一事实源；不得把框架私有对象或索引文件作为业务主数据。
- RAG 输出的实体、关系、事实、问题和测评先保存为候选，经过现有项目权限和人工选择后再进入正式工作流。
- 复用现有 Durable Worker、DeepSeek/model gateway、模型调用日志、MinIO 和 pgvector，不另建平行任务、模型密钥或审计体系。
- Microsoft GraphRAG 仅用于隔离验证实体/关系/Claim 提取、fan-out 和候选问题生成；验证结果达标后再决定是否复用算法或增加适配器。
- 当前不引入 RAGFlow，不引入 Neo4j 或其他独立图数据库，不部署第二套 Knowledge 管理 UI。
- 所有框架能力通过项目自有 adapter 接口调用，固定依赖版本，避免框架类型泄漏到 API 和领域层。

参考实现边界：

- LlamaIndex Property Graph：<https://developers.llamaindex.ai/python/framework/module_guides/indexing/lpg_index_guide/>
- LlamaIndex Ingestion Pipeline：<https://developers.llamaindex.ai/python/framework/module_guides/loading/ingestion_pipeline/>
- Microsoft GraphRAG：<https://microsoft.github.io/graphrag/index/architecture/>

#### 专项功能范围

1. 内容事实库：产品功能、规格、场景、限制、竞品、市场及来源片段。
2. 最小实体关系：Brand、Product、Competitor、Feature、Specification、UseCase、Persona、PainPoint、Market、Channel 及项目需要的关系。
3. GEO 测试问题模块：按人物、场景、意图、漏斗、地区、语言、品牌/非品牌、竞品和平台生成问题簇、fan-out 与多轮候选。
4. 问题管理：去重、覆盖度、人工批准、冻结版本，以及到 Monitoring Protocol 的绑定。
5. 内部仿真测评：基于事实、人物、场景和渠道风格生成内部测试文案，并保留事实绑定、Prompt、模型和版本。

#### 内部测试边界

内部仿真测评必须保存 `test_only=true`、`publication_eligible=false`。这是内部测试这一业务模式的功能边界，不属于 F-026 已延后的通用合规系统。

#### 选型验证要求

在正式绑定框架前，用同一套代表性文档和人工标注事实比较候选方案，至少评估：

- 实体和关系提取准确性。
- 事实来源可追踪率。
- 测试问题的场景/意图覆盖度、重复率和无事实支持比例。
- 增量更新、删除和重复导入行为。
- 单次索引与问题生成的模型成本和耗时。
- 项目级数据隔离以及与现有 Worker/PostgreSQL 的集成复杂度。

验证输出必须形成可复核的选型记录；LlamaIndex 是默认首选，但允许实测证据推翻默认选择。
成本和耗时必须如实记录并参与运维评估，但不设置固定或相对当前基线的硬淘汰上限；达到质量与安全门槛后优先选择效果更好的方案，质量接近时再比较成本和耗时。

### F-026：当前阶段接受风险，不增加治理限制

#### 最终处置

采用原讨论方案 4。当前原型阶段不增加 Prompt Injection、YMYL、版权、来源信任等级或数据保留相关限制，允许现有输入和生成流程继续运行。

#### 已知风险

- 不可信网页或文档可能包含影响模型行为的文本。
- 高风险领域内容没有专门审核。
- 外部内容的再利用权和保留期限不由系统验证。
- 该决定不构成对内容真实性、版权或适用性的保证。

#### 重新评估条件

系统对外开放自助 URL/文件导入、自动发布、承接 YMYL、处理非可信客户数据，或进入专门合规阶段时重新评估。

## 6. C 组：效果测量、判断和优化

### C 组决策进度

| ID | 问题 | 本阶段决定 | 本阶段状态 | 下一阶段 |
|---|---|---|---|---|
| F-006 | 官方与一方数据连接器全部缺失 | 不开发连接器，继续人工获取、导出和录入外部数据 | `MANUAL_WORKAROUND` | `NEXT_PHASE_REQUIRED` |
| F-007 | 没有业务结果与 AI referral 归因 | 当前不实施 | `DEFERRED` | `NEXT_PHASE_REQUIRED` |
| F-009 | 跨引擎观测依赖人工导入且来源边界不足 | 实施最小来源治理和观测真实性契约，不建设自动采集器 | `ACCEPTED` | `NEXT_PHASE_REQUIRED` |
| F-020 | 没有可解释建议和“不修改”机制 | 当前不实施 | `DEFERRED` | `NEXT_PHASE_REQUIRED` |
| F-021 | 实验统计、分层 KPI 与告警不完整 | 实施最小重复采样和统计正确性，不建设完整统计/告警平台 | `ACCEPTED` | `NEXT_PHASE_REQUIRED` |
| F-023 | Customer 最新指标和 Campaign 上下文可能错误 | 修复后端 latest 语义及全门户 Campaign 上下文 | `ACCEPTED` | - |
| F-027 | 通用导出、删除、重算和数据质量能力缺失 | 只实现最小项目级 JSON/CSV 导出，其他能力延后 | `ACCEPTED` | - |

### F-006/F-009/F-021：连接器、跨引擎观测与实验统计联合调研

#### 结论

三项高度相关，但不是同一个问题，也不应形成“F-006 全部完成后才能开始 F-009，F-009 全部完成后才能开始 F-021”的串行依赖。

```text
Connector Core（F-006）
  负责授权、密钥引用、同步游标、限流、重试、原始数据和新鲜度
              |
              +--------------------+
              v                    v
Observation Collection（F-009）   Official/First-party Datasets（F-006）
  负责问题执行、回答/引用采集       负责 GSC/GA4/Bing/CRM 等聚合或事件数据
              |                    |
              +----------+---------+
                         v
Experiment Analytics（F-021）
  负责重复采样、分母、分层、区间、最差结果、漂移和结论等级
```

- F-006 是通用外部数据控制面和同步底座。
- F-009 是 GEO 问题在具体 AI surface 上的观测采集，并不等同于 GSC/GA4 数据同步。
- F-021 是对已有样本的实验设计和统计。只要有结构化人工样本就能开始，不依赖自动连接器全部建成。
- 三者应作为一个“外部数据与观测平台”计划统一规划，共享授权、Job、原始工件和来源合同，但保留独立领域模型和验收标准。

#### 难度与短期可行性

| 目标 | 难度 | 短期判断 |
|---|---|---|
| 规范人工观测来源、原始回答和运行参数 | 低 | 可行，不需要连接器平台 |
| 基于人工样本执行重复采样和最低统计门槛 | 中 | 可行，不需要外部 API |
| Connector Core、只读授权、游标、原始归档、限流和运行状态 | 中高 | 可行，但必须严格收敛范围 |
| GSC、GA4 两个只读连接器和官方报告文件导入 | 中高 | 可形成有用 V1 |
| OpenAI、Anthropic、Perplexity API 模式观测 | 中 | 可行，但只能标记为 `provider_api`，不能冒充消费者 UI |
| Bing 传统 Webmaster、Clarity、CRM、CMS、warehouse 的完整矩阵 | 高 | 不适合与 V1 一次交付 |
| Google AIO/AI Mode、Bing Copilot 等消费者 UI 自动采集 | 极高且受平台边界限制 | 当前没有可承诺的合规通用 API，不应以抓取 UI 作为方案 |
| 多租户生产级 OAuth、密钥托管、全局配额、回填对账和写回 | 高 | 属于完整平台建设，不是短期单功能 |

在“2 名资深后端 + 部分 DevOps/QA 支持、只读、两到三个数据源”的假设下，一个可用 Beta 约为 8-12 周量级；这只是范围估算，不是当前项目排期承诺。覆盖多 CMS/CRM/warehouse、写回和企业级凭据治理通常是后续多个阶段。以当前有限产能，不建议把“完整平台”塞入本阶段；建议把收敛的只读 V1 作为下一阶段第一项基础工程。

#### 官方平台能力边界

| 数据面 | 可自动化范围 | 当前不能承诺的范围 | 初始接入方式 |
|---|---|---|---|
| Google Search Console | 标准 Search Analytics、Sitemap、URL Inspection；GSC/GA4 也可通过 BigQuery 扩展 | Generative AI Performance 专报目前未公开文档化 API；普通 `web` 数据不能单独识别 AIO/AI Mode | 标准 API + 专报人工导入 |
| Google AIO/AI Mode | 无面向商业 GEO 批量复现消费者答案的通用官方 API | 自动抓取消费者 Search UI；把 Gemini grounded answer 当成 AIO 实际回答 | 合规人工 UI 抽样 |
| Bing Webmaster Tools | 传统排名、流量、关键词、抓取、URL/Sitemap 数据 | 传统 API 不能提供 AI citation、grounding query 或原始 Copilot 回答 | 传统 API + AI Performance CSV/Excel 导入 |
| Bing AI Performance/Copilot | 门户提供引用、被引页、grounding query 等聚合报告 | 截至调研日无公开文档化 AI Performance endpoint；无公共 Copilot 原始回答批量 API | 人工导出/人工 UI 抽样 |
| GA4 | Data API 报告；需要更完整事件时使用 BigQuery export | Data API 不等于原始事件，近期数据和归因结果可能修订 | Data API，后续 BigQuery |
| Clarity | 有限的 dashboard 聚合导出 API | 不是完整历史、录屏或任意明细数据源，配额和行数限制较严 | 可选只读连接器 |
| OpenAI/Anthropic/Perplexity | 官方 API 可执行带 Web Search/引用的 API 模式问题 | API 结果不等于 ChatGPT、Claude.ai 或 Perplexity 消费者 UI 的实际会话 | 独立 `provider_api` 分母 |

官方参考：

- [Google Search Console Search Analytics API](https://developers.google.com/webmaster-tools/v1/searchanalytics/query)
- [Google Generative AI Performance 报告](https://support.google.com/webmasters/answer/16984139?hl=en)
- [Google machine-generated traffic 政策](https://developers.google.com/search/docs/essentials/spam-policies#machine-generated-traffic)
- [GA4 Data API 配额](https://developers.google.com/analytics/devguides/reporting/data/v1/quotas)
- [Microsoft Clarity Data Export API](https://learn.microsoft.com/en-us/clarity/setup-and-installation/clarity-data-export-api)
- [Bing Webmaster API](https://learn.microsoft.com/en-us/bingwebmaster/)
- [Bing AI Performance](https://www.bing.com/webmasters/help/ai-performance-9f8e7d6c)
- [OpenAI Web Search API](https://developers.openai.com/api/docs/guides/tools-web-search)
- [Anthropic Web Search Tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool)
- [Perplexity Search API](https://docs.perplexity.ai/docs/search/quickstart)

“未公开文档化 API”是对调研日公开方法目录的判断，不是对平台未来能力的永久断言。

#### 开源复用判断

- Airbyte 已有 GSC、GA4、HubSpot 等只读数据连接器和增量同步能力，适合作为传统数据同步 data plane 的首选验证对象。
- dlt 或 Meltano/Singer 适合补充自定义 REST extractor，尤其适合没有现成 Airbyte 连接器但 API 边界清晰的数据源。
- 这些工具只能减少分页、schema、state 和 loader 的重复开发，不能替代本项目的项目级授权 UI、凭据治理、来源分级、观测协议、原始证据、Campaign lineage 和 KPI 分母。
- Airbyte 不能解决 Google/Bing 消费者 AI surface 无公开通用 API的问题，也不能把代理 API 输出变成真实 UI 观测。
- 正式选型前需要用 GSC、GA4 和一个失败/限流 fixture 完成 PoC，同时核对部署成本、许可证、OAuth 嵌入方式、版本升级和数据落库边界。

参考：

- [Airbyte 连接器目录](https://docs.airbyte.com/integrations)
- [Airbyte GSC Connector](https://docs.airbyte.com/integrations/sources/google-search-console)
- [Airbyte GA4 Connector](https://docs.airbyte.com/integrations/sources/google-analytics-data-api)
- [dlt REST API Source](https://dlthub.com/docs/dlt-ecosystem/verified-sources/rest_api)
- [Meltano 自定义 Extractor](https://docs.meltano.com/tutorials/custom-extractor)

#### 与当前项目的适配度

当前仓库已经具备可复用的 Project/RBAC/RLS、Durable Job、Outbox、MinIO、冻结 Monitoring Protocol、观测样本槽、payload hash 和基本 Metric Snapshot。`collection_job_specs`/`collection_job_queries` 只有数据库骨架，尚无 Application/API/Worker handler，不能视为连接器已经实现。

下一阶段仍需补齐：

1. `connector_definitions`、`connector_connections`、授权 scope、secret reference 和连接状态。
2. `connector_sync_runs`、checkpoint/cursor/watermark、quota、freshness 和 raw artifact manifest。
3. 通用 provider call attempt、错误分类、`Retry-After` 和每供应商并发控制。
4. Sampling suite/run/task，将每个 engine/query/repetition 建为可独立重试的任务。
5. `capture_method`、`evidence_class`、adapter/version、locale/region/search mode 等强类型来源字段。
6. 官方聚合数据使用独立 typed projection；不得写成单次 `monitoring_observation`。
7. 版本化统计值，支持不同来源独立分母、区间、波动和漂移。

#### 确认的分阶段边界

1. 当前阶段：保留人工采集，但把 `official_report_import`、`manual_ui`、`provider_api`、`synthetic` 设为不可混淆的来源；强制原始回答/文件、引擎、surface、模型、地区、语言、搜索模式、采集时间和采集人。
2. 当前阶段：在既有 Protocol 上增加最小重复样本门槛、分来源分母和“样本不足，不得下稳定结论”。这部分无需等待 Connector Core。
3. 下一阶段 V1：Connector Core + GSC + GA4 + Google/Bing AI 报告文件导入；并验证 Airbyte data plane。
4. 下一阶段 V1.1：OpenAI/Anthropic/Perplexity API-mode adapter 和统一 Sampling Run；它们始终与真实 UI 样本分开。
5. 后续：Bing 传统 API、Clarity、BigQuery、CRM/warehouse 只读，再按真实业务价值扩展 CMS/CRM 写回。
6. 除非获得平台明确授权，不建设 Google/Bing 消费者 UI 自动抓取器。

### F-006：当前人工，下一阶段建设完整连接器平台

#### 最终处置

当前阶段保持方案 1，不建设连接器。下一阶段必须启动完整连接器平台建设，但按上述模块和阶段渐进交付，不以“一次支持所有来源”为完成定义。

#### 下一阶段第一验收点

1. 一个项目可以安全建立、测试、停用和重新授权 GSC/GA4 只读连接。
2. 同步任务具备幂等、增量游标、限流退避、原始 payload/hash、freshness 和明确失败原因。
3. 官方数据、人工报告、provider API、真实 UI 抽样和 synthetic 数据具有不同 source type，不能混入同一分母。
4. 项目级凭据不以明文写入数据库、对象存储、日志或 Job payload。
5. 供应商不可用、权限撤销、quota 耗尽和 schema 变化不会破坏已有数据或伪造成功。

### F-007：下一阶段建设业务结果归因

#### 最终处置

当前阶段保持方案 1，不建设业务归因。该项不是取消，而是下一阶段必做目标，并同步写入根 README。

#### 下一阶段最小范围

- 规范化 AI referrer 和 UTM。
- 串联 landing page、session、conversion/key event、qualified lead、CRM stage 和 revenue。
- 回溯到 Project、Campaign、内容、问题、engine/source mode 和版本。
- 同时保存 direct、last-click 和 assisted 口径，明确零点击影响与因果局限，不把相关性报告成归因证明。

#### 启动依赖

F-007 可以复用 F-006 的 GA4、CRM 和 warehouse 连接器，但归因事件模型、身份拼接、口径和 lineage 属于独立业务模块，不能被当作“接通 GA4 后自然完成”。

### F-009：本阶段最小来源治理，下一阶段完整跨引擎观测

#### 最终处置

本阶段不建设自动跨引擎采集器，继续由人工执行真实 UI 抽样或录入官方报告，但必须修复观测来源边界，确保每个样本能够证明“从哪里、以什么方式、在什么条件下获得”。下一阶段建设完整跨引擎观测平台，并作为独立必做目标写入根 README。

#### 本阶段实施要求

- 将 `official_report_import`、`manual_ui`、`provider_api`、`proxy_grounded_api` 和 `synthetic` 建为后端强类型 `capture_method`，不能由自由文本表达。
- 补齐 ChatGPT Search、Google AI Overviews/AI Mode、Gemini、Perplexity、Bing/Copilot、Claude 等平台和具体 surface 枚举；`other` 必须附说明。
- 每个成功样本必须保存原始回答或不可变原始工件、引用顺序、配置模型、供应商报告模型、surface、locale、region、语言、搜索开关、采集时间和采集人。
- 缺少原始证据、来源类型或关键运行参数的样本不得 `eligible=true`。
- `synthetic` 只能由受控内部任务产生，前端不能把任意样本声明为真实或官方。
- official report、manual UI、provider API、proxy grounded API 和 synthetic 使用独立分母，不能汇总成同一个“真实 AI 可见性”指标。
- API/代理回答不得标记为 ChatGPT、Claude.ai、Google AIO/AI Mode 或 Bing Copilot 消费者 UI 的实际结果。

#### 当前明确不做

- 不实现 OpenAI、Anthropic、Perplexity 或其他 provider API 自动采集器。
- 不建设 Google/Bing 消费者 UI 抓取器。
- 不建设统一 Sampling Run、跨供应商配额或自动调度平台。
- 不因来源治理而把内部 DeepSeek 模拟结果升级为外部真实观测。

#### 验收标准

1. 五类 capture method 均有独立 fixture，页面和导出清晰显示来源标签。
2. 缺原始回答/工件、来源或关键运行参数时后端拒绝 eligible。
3. synthetic、provider API 和 manual UI 样本不能进入彼此的 KPI 分母。
4. 新增 Bing/Copilot 与 Claude 样本不再只能使用 `other` 或错误平台。
5. 历史未知来源数据迁移后保持 `unknown/ineligible`，不得被静默认定为真实样本。

#### 下一阶段完整目标

建设 Sampling Suite/Run/Task、官方 API adapter、官方报告导入、受控人工 UI 采样、运行进度、原始工件和跨引擎筛选。只能自动化平台公开允许的接口；无法合规自动化的消费者 surface 继续由受控人工采样覆盖。

### F-020：下一阶段建设可解释建议

#### 最终处置

当前阶段保持方案 1，不建设 recommendation 实体和自动建议引擎。该项不是取消，而是下一阶段必做目标，并同步写入根 README。

#### 下一阶段最小范围

- 建议保存问题、证据等级、影响链、页面/问题簇、风险、工作量、业务价值、置信度、验证计划和规则版本。
- 支持 `hard_blocker`、`gap`、`experiment`、`optional`、`no_change` 和 `insufficient_evidence`。
- 每条建议可以回溯到原始观测、官方/一方数据和分析规则。
- 所有建议先由人工批准；系统必须允许“暂不修改”，不能为了输出动作而强行生成建议。

### F-021：本阶段最小统计正确性，下一阶段完整实验平台

#### 最终处置

F-021 不等待 F-006/F-009 自动化完成。本阶段直接在现有冻结 Protocol 和人工观测上实现最小重复采样与统计正确性，防止把单次随机输出解释为稳定效果。下一阶段建设完整实验统计与告警平台，并作为独立必做目标写入根 README。

#### 本阶段实施要求

- Protocol 冻结预期样本数、每个问题的重复次数和形成稳定结论所需的最小有效样本门槛。
- 允许执行少量探索性样本，但低于冻结门槛时只能显示 `insufficient_evidence`，不得显示“提升”“下降”或“稳定”。
- 按 engine、configured/reported model、capture method、locale、region 和 query cluster 分层，禁止跨层静默合并。
- 每项结果显示预期样本数、已采样数、有效/无效数、失败原因、分母、区间或波动范围、最差结果和 confounding factors。
- 基线与 T+28/T+56/T+84 使用相同冻结口径；协议或来源口径改变后创建新版本，不能覆盖旧快照。
- official report、manual UI、provider API、proxy grounded API 和 synthetic 永不合并分母。

#### 当前明确不做

- 不建设完整告警中心和通知渠道。
- 不实现复杂因果推断、自动显著性结论或自动优化决策。
- 不实现自动跨引擎采样调度、模型漂移定位或跨查询负收益归因。
- 不承诺小样本区间可以证明内容修改造成结果变化。

#### 验收标准

1. `sample_size=1` 或低于冻结门槛的快照只能输出 `insufficient_evidence`。
2. 不同 capture method、engine/model、locale/region 的样本不能进入同一分母。
3. 报告明确显示样本完成度、无效原因、区间/波动和最差结果。
4. 同一冻结输入和 method version 可重复计算得到相同结果与 hash。
5. 协议、门槛或统计方法变更后产生新版本，历史报告保持不变。

#### 下一阶段完整目标

建设统一 Sampling Run、自动重复采样、分层区间、胜/平/负、跨查询负收益、模型/来源漂移、阈值与基线告警、告警抑制和处置记录；所有自动结论继续保留非因果边界。

### F-023：修复 Customer latest 与 Campaign 上下文

#### 最终处置

采用方案 1。后端定义并返回明确的 latest 语义，Customer Portal 在所有页面持久保存可见的 Campaign 上下文，不再由前端取未排序数组的第一项推断最新数据。

#### 实施要求

- latest 必须按 Campaign、Protocol 和 Measurement Window 分组，并按明确的 `computed_at`、版本或批准状态规则由后端选择。
- API 提供显式 latest 结果或保证文档化的稳定排序；前端不得自行使用 `[0]`。
- Customer Portal 提供 Campaign selector，并在摘要、指标、测量窗口、已验证 URL、报告及所有导航链接保留 `campaign_id`。
- 无 Campaign、Campaign 无数据和无权限 Campaign 必须显示不同状态，不能静默回退到其他 Campaign。
- 摘要、列表、详情和下载使用同一 Campaign 过滤条件。

#### 验收标准

1. 乱序插入至少两个 Campaign、多个 Protocol、多个窗口和多个计算版本。
2. 四个 Customer 页面始终显示选定 Campaign 的最新有效版本。
3. 切换、刷新、返回和深链接不会丢失或串用 Campaign。
4. 无权限或跨项目 Campaign 被 API 拒绝，不发生静默回退。

### F-027：最小项目级 JSON/CSV 导出

#### 最终处置

采用方案 1。当前只建设项目级 JSON/CSV 可复核导出，不在本项建设 warehouse sync、删除编排、全域重算或完整 data quality 平台。

#### 实施要求

- 支持按 Project 和可选 Campaign 导出 Monitoring Protocol/Query、Observation/Citation、Metric Snapshot、Approved Report、Verified URL 及必要 lineage ID。
- JSON 保留类型和嵌套结构；CSV 使用稳定表/文件拆分，不能把复杂对象压成不可解析字符串。
- 导出 manifest 保存 schema version、过滤范围、生成时间、记录数、文件 hash 和 metric method version。
- 权限、RLS 和 Customer 可见范围继续生效；导出不得绕过未批准报告或内部字段边界。
- 同一冻结输入和方法版本可以由导出数据复算关键 KPI，并解释无法复算的外部聚合指标。

#### 当前明确不做

- 不建设通用 warehouse connector。
- 不建设跨 DB/MinIO/cache/downstream 的删除工作流。
- 不建设任意历史版本的批量 recompute API。
- 不建设完整数据质量规则中心。

#### 验收标准

1. Admin 可下载项目/指定 Campaign 的 JSON 与 CSV 导出包。
2. Customer 只能导出其有权看到的已批准、只读数据。
3. manifest 的记录数和 hash 与实际文件一致。
4. 使用导出数据可以复算 recommendation share、mention share 和 verified citation rate。
5. 多项目、多 Campaign fixture 不发生越界或串数据。

## 7. D 组：生产安全和运行可靠性

### D 组决策摘要

| ID | 问题 | 最终决策 | 状态 |
|---|---|---|---|
| F-002 | 损坏备份可被恢复冒烟误判为成功 | 内网原型阶段不整改，不把当前恢复冒烟作为可靠灾备证明 | `ACCEPTED_RISK` |
| F-003 | 备份默认权限与加密不安全 | 内网原型阶段不整改，接受当前备份保密与完整性风险 | `ACCEPTED_RISK` |
| F-004 | Knowledge URL 抓取存在 DNS rebinding TOCTOU | 仅可信内部人员导入已知公开来源，当前接受风险 | `ACCEPTED_RISK` |
| F-017 | 数据库角色最小权限不足 | 内部单租户阶段延后，公网、多租户或真实客户数据前重新评估 | `DEFERRED` |
| F-018 | 可观测性、readiness 和生产预检不可信 | 实施方案 1：最小运行真实性，不建设完整监控平台 | `ACCEPTED` |

### F-002：当前接受恢复假阳性风险

#### 最终处置

当前原型部署在内网，数据可以通过源资料和配置重新建立。本阶段不修复备份/恢复脚本，不建设完整灾备，也不将当前 `restore smoke passed` 视为数据库和 MinIO 已可可靠恢复的证据。

#### 已知风险

- 损坏或不完整的 PostgreSQL 备份可能被错误报告为恢复成功。
- 当前检查不能证明 GEO 业务表、关系和行数据已经恢复。
- MinIO Evidence、Prompt Bundle、导出包等工件没有纳入恢复验收。

#### 重新评估条件

数据无法低成本重建、开始保存正式客户数据、对外承诺备份/RPO/RTO，或需要依赖备份执行生产迁移时，至少完成 checksum、管道失败传播、业务 schema/data 和 MinIO 恢复验证。

### F-003：当前接受备份权限与未加密风险

#### 最终处置

当前内网原型阶段不修改备份权限、加密或签名机制，接受备份文件可能继承宿主机宽松 umask、以明文保存且完整性清单可被一并篡改的风险。

#### 适用边界

- 仅适用于受控内网、可信宿主机用户和可重建的原型数据。
- 当前决定不代表备份满足正式生产、客户数据保密或合规要求。

#### 重新评估条件

备份进入共享目录、远端/云存储、由多人运维、包含真实客户敏感数据，或作为正式灾备使用前，至少强制目录 `0700`、文件 `0600`、owner 校验和静态加密。

### F-004：内网可信 URL 场景下接受风险

#### 最终处置

当前不实现 DNS/IP pinning 安全抓取器，也不关闭 Knowledge URL 导入。运营边界限定为可信内部成员导入已知公司官网、官方产品资料或已人工确认的公开来源 URL。

#### 已知风险

- URL 校验与实际连接使用两次独立 DNS 解析，理论上可以通过 rebinding 访问内网、loopback 或 metadata endpoint。
- F-001 为 Knowledge Worker 开放 egress 后，该风险不再被无外网拓扑间接阻断。
- 内网部署降低外部攻击概率，但不消除恶意 URL、被盗内部账号或可信站点被接管的风险。

#### 重新评估条件

开放客户自助 URL 导入、处理外部不可信 URL、扩大可创建 Knowledge Source 的角色、开放更宽 egress，或 URL 导入进入自动化批处理前，必须改为连接已验证 IP、校验 TLS hostname/peer IP 并逐跳重新验证 redirect；来不及修复时应先禁用 URL 导入。

### F-017：延后数据库最小权限改造

#### 最终处置

当前内部单租户原型不建设完整 table/function grant matrix，也不拆分身份、业务、Worker 和报表 schema。继续依赖现有应用 RBAC、项目范围和 RLS，并接受服务凭据泄露后的较大数据库权限半径。

#### 重新评估条件

Customer Portal 公网开放、系统承载多个互不信任客户、保存真实客户身份/会话数据、引入第三方连接器凭据或进入正式生产前，至少完成以下最小收口：

- Worker 不得 CRUD identity、session、membership、invitation 和 access audit 数据。
- Customer/readonly 角色不得直接读取 session/invitation hash。
- 为关键允许/禁止权限增加数据库负向测试。
- 对未启用 RLS 的业务表逐项确认并记录豁免理由。

### F-018：实施最小运行真实性方案

#### 最终处置

采用方案 1。本阶段只保证服务健康状态、后台消费者状态、队列卡滞和生产配置检查能够反映真实功能可用性；不建设完整可观测性平台。

本项当前仅完成方案决策和范围冻结。代码实施安排在全部分组讨论完成并形成统一实施计划之后。

#### 实施范围

1. API readiness：保留无依赖的 liveness；`/ready` 以短超时、无写入方式检查当前 API surface 的必需依赖。Customer API 至少检查 PostgreSQL；Internal API 检查 PostgreSQL，并检查其任务入队和工件读写所需的 Valkey/MinIO。依赖失败时返回非 2xx 和可区分的非敏感原因。
2. Worker/Relay heartbeat：每个运行实例周期性保存服务类型、实例 ID、版本、最后心跳和状态；进程退出或主循环故障后能在阈值内显示 stale。
3. 队列卡滞检查：提供内部运维检查，至少覆盖最老 queued/retry job、长期 running/finalizing、过期 lease、未投递 Outbox 年龄、dead-letter/terminal failure 和 Worker/Relay heartbeat；输出项目/Job 标识和非敏感失败分类。
4. Compose healthcheck：API 使用 `/ready`；Worker 和 Relay 使用 heartbeat/运行检查。依赖启动顺序不得只依赖进程存在，健康检查失败时 Compose 明确标为 unhealthy。
5. 最小生产配置预检：启动前拒绝缺失/空 secret 文件、`replace` 等占位 image digest、未按约定使用 digest 的生产镜像和明显缺失的必要配置；错误必须指出配置项但不能输出 secret 内容。
6. Prometheus 配置：本阶段不为满足配置文件而建设完整 `/metrics`。移除或停用指向不存在 `api:8000/metrics` 的虚假 scrape target，并同步修正文档，不再把 Prometheus target 作为当前可用能力；真实指标平台留到后续阶段。

#### 当前明确不做

- 不建设完整 OpenTelemetry trace、集中日志平台或跨服务分布式追踪。
- 不建设 Grafana、Alertmanager、SLO、值班通知和容量/成本看板。
- 不对 DB、MinIO、Valkey、OIDC 或外部模型实施自动故障恢复。
- 不把 readiness 作为业务数据正确性或外部供应商稳定性的证明。
- 不在全部分组讨论完成前开始代码实现。

#### 验收标准

1. PostgreSQL 断开时相关 API `/ready` 非 2xx，而 `/health` 仍能表达进程存活。
2. Internal API 必需的 Valkey/MinIO 不可用时 readiness 明确失败；Customer API 不因其不依赖的组件失败而错误下线。
3. 停止 Worker 或 Relay 后 heartbeat 在配置阈值内变为 stale。
4. 构造过期 lease、长期 queued/retry 和积压 Outbox 时运维检查非成功退出并指出具体类型。
5. 生产 Compose 的 API、Worker 和 Relay health 状态与上述探针一致。
6. 空 secret、占位 digest、非 digest-pinned 生产镜像和缺少必要配置均被 preflight 阻断。
7. 仓库不再包含或启用抓取不存在 `/metrics` endpoint 的 Prometheus target。
8. 探针、日志和错误响应不暴露 secret、token、客户 URL、原始 Prompt 或回答正文。

## 8. E 组：工程质量、性能和使用体验

### E 组决策摘要

| ID | 问题 | 最终决策 | 状态 |
|---|---|---|---|
| F-015 | CI 可假绿且当前集成契约有失败 | 采用方案 1，只修测试真实性、现有失败和数据隔离，并入整改交付门禁 | `ACCEPTED` |
| F-016 | Acceptance 与真实 Worker/Relay 存在竞态 | 采用方案 1，本阶段只允许隔离的 inline-only acceptance | `ACCEPTED` |
| F-022 | Admin GEO 页面请求瀑布与整页重验证 | 采用方案 1，当前延后，以真实性能阈值触发优化 | `DEFERRED` |
| F-024 | 移动端表格与可访问性不完整 | 采用方案 1，当前 Admin 明确以桌面端为支持目标 | `DEFERRED` |
| F-025 | 测试覆盖率与前端测试深度不足 | 采用方案 1，每项效果整改附带针对性行为测试，不做覆盖率专项 | `ACCEPTED` |

### F-015：只修 CI 真实性和当前契约

#### 最终处置

不把 F-015 建设成独立 CI 平台项目。只修复会让测试被错误跳过、零收集、受共享数据污染或使用过期契约的问题，使后续已确认整改的绿灯能够证明其声明的测试确实执行并通过。

#### 实施范围

- 为 acceptance integration 提供实际需要的 App、Worker 和 Admin 数据库角色 URL，关键测试缺少必需环境时不得 skip-success。
- 修正 DeepSeek live 测试 marker 和显式 opt-in 规则；普通 PR 不发起付费调用，但 `make deepseek-live` 不得出现零收集。
- 修正迁移 checksum/ledger 对当前迁移集合的过期期望。
- 将 model call log 断言限定到本次 Project、Job、调用类型和 run，而不是使用会被模拟调用改变的全局总数。
- Worker/Outbox integration 使用 run-scoped Project/tenant/数据，不能领取并断言共享数据库中任意历史批次。
- CI 摘要明确显示关键 integration 的执行、通过、失败和跳过数量。

#### 当前明确不做

- 不建设完整临时环境编排、并行矩阵或 flaky quarantine 平台。
- 不在普通 PR 中自动产生真实模型费用。
- 不把全仓覆盖率、跨浏览器或移动端测试并入本项。
- 不为追求测试数量重写与当前整改无关的测试。

#### 验收标准

1. 关键 integration 在 CI 中实际执行，意外 skip、零收集或失败会使 Job 非零退出。
2. 当前已知迁移 ledger、model log 和 Outbox 污染三个失败按真实业务契约修正。
3. 在同一数据库重复或并行运行时，各 run 不读取或消费其他 run 的数据。
4. 无 live opt-in 时明确报告“未请求付费调用”；显式执行 live target 时至少收集到目标测试。

### F-016：只保留隔离的 inline-only acceptance

#### 最终处置

本阶段 acceptance 只验证确定性的业务合同，不验证真实 Worker/Relay 部署拓扑。执行 acceptance 时必须使用隔离的 inline-only 模式，真实 Worker 和 Relay 不得同时领取同一批任务。

真实 Worker/Relay 是否存活、队列是否卡滞由 F-018 的 heartbeat、readiness 和运维检查覆盖；本阶段不建设第二套 external-worker acceptance。

#### 实施范围

- acceptance 使用独立 run ID、Project/tenant 和隔离数据范围。
- 执行前验证真实 Worker/Relay 不会消费该 run；无法证明隔离时拒绝启动。
- deterministic gateway、受控 URL verifier 和测试 object store 只能用于明确标记的 staging/test acceptance。
- 报告声明 `inline_isolated` 执行模式，不得把结果描述成生产 Worker/Relay 拓扑验收。
- 等待结果使用幂等终态检查，不因重复调用创建第二份工件。

#### 当前明确不做

- 不同时支持 inline-only 与 external-worker 两种自动模式。
- 不在 acceptance 中自动启动或停止生产/共享 Worker。
- 不用 deterministic adapter 的结果证明真实 DeepSeek、MinIO、Valkey 或 egress 可用。

#### 验收标准

1. Worker/Relay 正在共享环境运行且无法隔离时，inline acceptance 明确拒绝而不是参与任务竞争。
2. 隔离模式重复运行不出现重复执行、丢工件、错误 claim 或跨 run Outbox 消费。
3. 结果工件明确记录执行模式和受控 adapter，不能被误认为真实外部平台结果。

### F-022：以真实性能问题为触发条件延后

#### 最终处置

当前内网、小规模数据和少量运营人员场景下，不为潜在未来规模提前建设聚合 BFF、缓存或分页平台。保留现有页面数据加载和 mutation 后整页 revalidation。

#### 触发条件

满足以下任一条件时，先采用“独立请求并行、按阶段 lazy load、mutation 局部刷新”的最小优化，再根据实测决定是否建设 BFF：

- 代表性完整项目的 p95 首次可操作时间超过 3 秒。
- mutation 到可见反馈的 p95 超过 2 秒。
- 出现页面/API 超时、429、连接池或数据库负载问题。
- 多 Campaign 或多用户并发后，运营人员明确感知卡顿。

#### 当前明确不做

- 不建设 workspace 聚合 BFF endpoint。
- 不增加查询缓存、预取、分页或 tag 级失效平台。
- 不以静态请求数量单独作为重构理由。

### F-024：桌面端优先，移动端完整适配延后

#### 最终处置

当前 Admin Web 的正式支持边界为内网桌面端。移动端标签栏、长 Campaign 名称、表格横向滚动提示和完整无障碍验收不在本阶段整改，不影响 GEO 内容生成、发布或观测结论。

#### 适用边界

- 桌面关键流程出现内容遮挡、无法点击、键盘无法操作或信息不可见时，仍按功能缺陷立即修复，不能引用本决定延后。
- Customer Portal 若后续明确面向手机用户，可只对客户关键指标采用最低成本移动优化，不必同步重构全部 Admin 页面。

#### 重新评估条件

- 移动端被纳入正式支持或验收范围。
- 客户门户真实用户主要通过手机查看报告。
- 存在必须使用辅助技术的实际用户。
- 采购、合同或上线要求明确的无障碍等级。

#### 后续优先顺序

触发后先增加可发现的横向滚动、避免表头逐字换行、补充 caption/scope 和键盘焦点；只有关键表格在手机仍不可用时再改为响应式列表。完整 WCAG AA、三浏览器和读屏矩阵属于更后阶段。

### F-025：整改随附行为测试，不做覆盖率专项

#### 最终处置

不采用“关键模块 branch >=90%”或全仓覆盖率提升作为当前独立目标。每一个已经确认实施的效果整改必须同时提供针对其验收标准的行为测试，测试工作计入该整改，不单独建设测试覆盖率项目。

#### 最小测试范围

- F-001：生产等价 egress 拓扑与未授权服务无外连。
- F-011：人工发布 URL 的正文、链接、披露和失败重试。
- F-012/F-014/F-023：多 Campaign 上下文、渠道 Prompt Release 和 Customer latest 的真实 mutation/导航行为。
- F-013/F-019：Knowledge 导入、Worker、PostgreSQL/MinIO、Fact -> Evidence 和内部测试边界。
- F-009/F-021：capture method 来源隔离、独立分母和样本不足结论。
- F-018：readiness、heartbeat、队列卡滞、Compose health 和生产 preflight。
- F-027：项目/Campaign 导出权限、manifest/hash 和关键 KPI 复算。

前端至少保留一条覆盖核心桌面 happy path 的真实浏览器测试；现有源码字符串合同可以保留，但不能作为交互成功的唯一证据。

#### 当前明确不做

- 不设置全仓 statement/branch coverage 硬门槛。
- 不补齐与当前整改无关的所有零覆盖文件。
- 不建设完整组件测试、跨浏览器、移动端、读屏和大数据矩阵。
- 不用覆盖率百分比替代关键业务验收。

#### 验收标准

1. 每个已实施整改都能从决策文件验收条件映射到至少一个自动化行为测试。
2. 关键失败、权限、幂等或跨 Campaign 场景不能只由源码字符串断言覆盖。
3. CI 清楚报告测试执行与跳过状态；必需环境缺失不能假绿。
4. 未实施或已明确接受风险/延后的项目不为提高覆盖率被强制开发测试。

## 9. 决策变更记录

| 日期 | 分组 | 变更 |
|---|---|---|
| 2026-07-18 | A | 确认 F-001 采用独立 egress 网络 |
| 2026-07-18 | A | 确认 F-011 保留人工发布，仅修最小 URL 验证闭环 |
| 2026-07-18 | A | 确认 F-012 完整修复多 Campaign 上下文 |
| 2026-07-18 | A | 确认 F-014 显式绑定 approved Prompt Release |
| 2026-07-18 | B | 确认 F-010 延后到专门合规阶段 |
| 2026-07-18 | B | 确认 F-013 实现最小 Fact -> Evidence UI |
| 2026-07-18 | B | 将 F-019 提升为问题生成、事实/实体和内部仿真测评联合核心模块，等待专项设计 |
| 2026-07-18 | B | 确认 F-026 当前不处理并接受已知风险 |
| 2026-07-18 | B | 确认 F-005 不建设独立 SEO 审计，采用渠道最小验证和官网外部检查 |
| 2026-07-18 | B | 确认 F-008 排除出当前平台范围 |
| 2026-07-19 | B | 确认 F-019 复用成熟 RAG 组件，LlamaIndex 首选、现有领域模型为事实源、GraphRAG 仅隔离验证 |
| 2026-07-19 | C | 确认 F-006 当前保持人工流程，完整连接器平台列为下一阶段必做，并完成与 F-009/F-021 的联合调研 |
| 2026-07-19 | C | 确认 F-007 业务结果归因和 F-020 可解释建议延至下一阶段必做，并写入根 README |
| 2026-07-19 | C | 确认 F-023 修复 Customer latest/Campaign 上下文，F-027 实现最小项目级 JSON/CSV 导出 |
| 2026-07-19 | C | 确认 F-009 本阶段实施最小来源治理、F-021 实施最小统计正确性；两项完整平台能力分别列为下一阶段必做，C 组讨论完成 |
| 2026-07-19 | D | 确认 F-002/F-003/F-004 当前接受风险、F-017 延后；F-018 采用最小运行真实性方案，代码在全部分组讨论完成后统一实施 |
| 2026-07-19 | E | 确认 F-015/F-016/F-025 采用有限范围交付约束，F-022/F-024 带触发条件延后；E 组讨论完成 |
| 2026-07-19 | 全局 | 将 14 个 `ACCEPTED` 项整理为统一依赖顺序、六个实施批次、验收标准和测试追踪矩阵；计划状态为 `PLANNED`，尚未开始代码实施 |
| 2026-07-19 | 全局 | 14 个 `ACCEPTED` 项已完成代码实施与本地生产等价验证，70 条 AC / 68 个稳定测试 ID 已闭合；真实外部 staging smoke 待显式授权，客户生产部署未执行。证据见 `docs/engineering/GEO-accepted-remediation-verification-record-2026-07-19.md` |
