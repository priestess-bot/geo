# GEO 文案生成系统设计方案 v1.0-r4

> **已废止：** 本文仅保留为设计审查历史，不是当前实现、API、部署或验收真源。当前合同请使用 [GEO v3 运行与验收合同](GEO-v3-%E5%85%A8%E6%B5%81%E7%A8%8B%E8%BF%90%E8%A1%8C%E6%89%8B%E5%86%8C.md)、[系统架构](architecture/system-overview.md) 和 [全流程操作手册](operations/geo-full-flow-runbook.md)。

> - 文档状态：Draft for Review
> - 文档 Owner：批准前必须由项目负责人指定
> - 必需评审：Product、Engineering、Security、Delivery
> - 设计基线：2026-07-12，`HEAD edc7dba` + 当前未提交工作区
> - 当前数据库基线：`0001` 至 `0028`
> - 适用范围：GEO 分析驱动的证据型文案生成、审核、交付和效果回看
> - 非生产声明：当前项目的 Production Final Gate 尚未在最新代码上通过，本文件描述的“已实现”不等于“已投产验证通过”

## 0. 文档约定

### 0.1 要求等级

- **MUST**：缺失时不得进入对应发布门禁。
- **SHOULD**：默认实现；偏离时必须记录 ADR、原因和风险。
- **MAY**：可选增强，不阻塞当前阶段。

### 0.2 实现状态

- **已实现**：代码和数据契约已经存在。
- **部分实现**：已有薄能力，但不满足本方案完整合同。
- **未实现**：仓库中没有对应的一等领域能力。
- **后置**：明确不进入当前 MVP。

“已实现”只说明代码存在。是否可用于生产，必须另外满足：

1. 行为测试通过；
2. 真实依赖联合运行通过；
3. 产物时间新鲜；
4. Production Final Gate 通过；
5. 没有被 accepted risk 绕过的安全、隐私或追踪硬门禁。

### 0.3 核心设计结论

本项目不是从零建设文案系统。当前已经存在一条可运行但较薄的链路：

```text
ActionRecommendation / Report / Retest IDs
  + SourceGap type label（当前无 source_gap_id/对象 trace）
  -> content_generation_jobs
  -> knowledge worker
  -> approved facts + active embedded chunks
  -> content_drafts
  -> generation/security/traceability gate
  -> internal human review
  -> Markdown export
  -> [legacy/partial] manual distribution URL backfill
```

目标方案必须在这条链路上增量演进，不能再建设一套平行的 Job、Review、Trace、Audit 和 Distribution 真源。

最终边界保持不变：

> **GEO 分析决定为什么写和优先写什么；知识库决定哪些事实允许写；生成策略决定怎么写；质量门禁和人工审核决定能否交付。文案系统不得自行创造事实。**

### 0.4 变更记录

| 版本 | 日期 | 状态 | 说明 |
| --- | --- | --- | --- |
| v1.0 | 未记录 | 原始草案 | 目标架构和能力愿景 |
| v1.0-r2 | 2026-07-12 | Draft for Review | 按当前代码、迁移、前端、worker、基础设施和测试进行现状校准，改为增量实施方案 |
| v1.0-r3 | 2026-07-12 | Draft for Review | 收口 Export/Delivery/Publication、Evidence Attempt、复合外键、Asset 编辑、Claim completeness、API 和前端协同合同 |
| v1.0-r4 | 2026-07-12 | Draft for Review | 补齐 production 对象存储身份传播、Knowledge/Collection 过期租约回收、多项目 Session、tenant-derived RLS 和可重放邀请兑换合同 |

---

## 1. 方案审查结论

### 1.1 原方案值得保留的部分

以下方向正确，继续作为目标架构：

1. 从 GEO 报告、信源缺口、竞品差距和知识事实进入生成，不以空白输入框作为主要入口；
2. 证据不足时进入 `needs_evidence`，禁止让模型猜测；
3. 使用冻结 Evidence Pack，而不是把 Qdrant 原始召回直接交给模型；
4. Canonical Content 与 Platform Variant 分离；
5. 写作规则、市场规则、品牌语气和渠道规则可版本化、可评测、可回滚；
6. 自动 QA 分为确定性检查、逐 Claim 证据检查和软质量评测；
7. 高风险内容必须人工审核；
8. 首期只导出，不自动发布；
9. 发布后用同口径 GEO 复测观察变化，不直接宣称因果。

### 1.2 原方案需要纠正的部分

| 原设计问题 | 当前事实 | 修订决策 |
| --- | --- | --- |
| 把文案系统描述成待新增领域 | 已有生成 Job、草稿、人审、追踪、Markdown 导出和分发回填 | 改为 Content v0 到 Content v1 的增量演进 |
| 一次新增约 20 多张表 | 多数能力已有真源 | 首期只增加不可由现表表达的版本化对象 |
| 所有表强制 `tenant_id + brand_id` | 当前隔离锚点是 `project_id`；已有 project-scoped `brand_entities`，但没有跨项目 brand aggregate | 项目数据继续使用 `project_id + RLS`；内容引用现有 `brand_entity_id`；共享 Skill 单独定义 scope |
| 新建 `content_reviews` | 已有通用 `human_review_records` | 继续复用通用审核记录 |
| 新建 generation run/job | 已有 `content_generation_jobs` 和 pipeline stages | 扩展现有 Job，不建立双真源 |
| 新建对象级证据图 | 已有 `knowledge_trace_refs`、`evidence_links`、`audit_events` | 扩展 trace 类型；只新增 Claim 级证据映射 |
| 首期拆独立 `content_worker` | 当前 knowledge actor 已消费 content job | Phase 0 先修任务可靠性；达到隔离触发条件后再拆队列 |
| 使用 `/api/v1/...` | 仓库统一使用 `/v1/...` | 新接口继续使用 `/v1` |
| Repository “约 4,000 行” | 当前主 repository 约 18,700 行，FastAPI 入口约 12,100 行 | 新内容代码必须进入独立 router/service/repository 模块 |
| Prompt Bundle 只保存 hash 却声称完整复现 | hash 不能恢复原始输入 | MinIO 保存受控快照，PostgreSQL 保存 URI、hash 和元数据 |
| 一套状态机覆盖所有对象 | Job、Brief、Asset、Review、Publication 生命周期不同 | 拆分状态机并定义转换守卫 |
| Export 自动产生待发布任务 | 导出可能用于内部复核、法务、备份或外部编辑 | Export、Delivery、Publication Request 分离；只有显式 publication request 才创建 manual distribution |
| 只依靠 `project_id + RLS` 保证项目一致性 | RLS 控制可见性，不能阻止跨项目错误外键 | 项目内引用使用 `(id, project_id)` 复合外键并为 FK 建索引 |
| 声明 Asset Version 不可变但缺少编辑 API | Admin 被称为编辑器，却没有新版本写入合同 | 人工编辑基于精确版本创建新 version，重新进入 QA/Review |
| 前端只给出三栏概念图 | 无状态-操作矩阵、DTO、错误恢复和移动端降级 | 增加 Phase 0-3 页面、ViewModel、权限、响应式和联调合同 |

### 1.3 本方案的总实施顺序

```text
Phase 0  修复现有薄闭环和生产底座
Phase 0.5  Evidence Data Readiness Slice
Phase 1  版本化 Brief + Evidence Pack + Website Canonical
Phase 2  完整自动 Claim entailment/QA + LinkedIn/YouTube Variant + Delivery Package
Phase 3  Opportunity 产品化 + Customer Approval + Skill Registry
Phase 4  Publication/Feedback/Experiment
Phase 5  CMS 和平台发布连接器
```

基础 Production Final Gate 没有恢复为 Green 之前，不得把 Phase 1 及以后能力标记为 production ready。

### 1.4 设计批准阻断项

当前状态保持 `Draft for Review`。以下六项已在 v1.0-r3 形成明确合同，但仍需 Product、Engineering、Security、Delivery 逐项签署，之后才能改为 `Approved for Phase 0/1 Implementation`：

1. Export、Delivery、Publication Request 边界和显式发布意图；
2. 不包含 exported/delivered 的 Asset Version 状态机；
3. Durable Evidence Job + immutable Pack Attempt 重试模型；
4. 同项目复合外键、typed 多态 FK 和 Brief current-version 循环策略；
5. 独立于 Draft 的 Prompt Bundle 对象路径；
6. Claim inventory completeness 与 Asset 人工编辑新版本合同。

v1.0-r4 另外确认了三个 Base/Phase 0 实现阻断项；它们不改变内容领域边界，但未关闭前不得宣称基础生产门禁 Green：

1. embedded MinIO 的 root/application/backup 身份分离，以及所有对象存储消费者的 production 配置一致传播；
2. Knowledge 与 Collection Durable Job 对 expired-running lease 的原子接管、heartbeat、fencing token 和 DLQ；
3. 邀请兑换前的 portal/role 原子校验、同 key 稳定 Session delivery，以及同一 tenant 内完整多项目 membership/grant/RLS Session。

“Approved for Implementation”仍不等于 production ready；实现后必须通过对应 Gate profile。

---

## 2. 当前实现基线

### 2.1 能力核对

| 能力 | 状态 | 当前实现证据 | 本方案决策 |
| --- | --- | --- | --- |
| GEO 回答、引用、评分、竞品和信源缺口 | 已实现 | `models.py` 的 `SourceGap`、`ActionRecommendation`；citation graph、score、report 路径 | 直接复用为内容机会输入 |
| Action/Report/Retest 关联内容任务 | 部分实现 | Job metadata 携带 ID，worker 会写 trace，但 API/worker 未先校验对象存在、类型和同 project | Phase 0 补 referential validation 后再进入正式 Brief 来源合同 |
| Source Gap 关联内容任务 | 部分实现 | 当前只有 `source_gap_type` 标签，没有 `source_gap_id`，worker 不写对象级 Source Gap trace | Phase 0 增加可选 `source_gap_id`、同项目校验和 trace；类型标签只作为分类属性 |
| 知识导入、解析、OCR、表格、Chunk | 已实现 | knowledge pipeline、`0023/0027/0028` migrations | 直接复用 |
| BGE-M3 与 Qdrant 检索 | 已实现 | `QdrantKnowledgeStore`、embedding API、Qdrant smoke | 只负责候选召回，PostgreSQL 仍是事实真源 |
| Fact Candidate、人工审核、active fact | 部分实现 | approved/active 主路径已存在；但最新生命周期 CHECK 与 rejected/pending review 写入存在冲突 | 直接复用模型，Phase 0 修复 status/review_status 映射 |
| 内容生成 Job | 已实现 | `content_generation_jobs`，含 lease、attempt、retry 字段 | 扩展幂等、回收和 DLQ |
| DeepSeek 内容生成 | 已实现 | `knowledge_application.py` 与 knowledge worker | 迁移到统一 LLM Gateway |
| Content Draft | 已实现 | `content_drafts`，含 fact/chunk/citation/trace/status | 演进为 Content Asset 当前投影 |
| generation/security/traceability gate | 部分实现 | forbidden substring、引用数量、secret marker、trace presence | 补逐 Claim、PII、注入、publish gate |
| 内容人审 | 已实现 | `human_review_records`；批准时重新检查 active facts/chunks/risk flags | 复用；新增版本绑定和职责分离 |
| Markdown 导出 | 已实现 | `/v1/knowledge/content-drafts/runtime/{id}/export.md` | 保留兼容，扩展 HTML/manifest/package |
| 手工分发 URL 回填 | 部分实现 | `manual_distribution_records` | 保留回填能力；新增显式“标记为待发布”，禁止由 export 自动创建 |
| Admin Content Workbench | 已实现薄版 | 生成、任务、草稿、审核、导出、URL 回填 | 原地演进为 Content Studio |
| Customer 内容交付与审批 | 未实现 | Customer Web 仅加载 score/evidence/report/action/trace | Phase 3 新增 |
| Content Opportunity | 部分实现 | Source Gap + Action Recommendation 可表达来源和建议 | Phase 1 先做 typed projection，Phase 3 再产品化 |
| 版本化 Content Brief | 未实现 | Job request 只是隐式 Brief | Phase 1 新增 |
| 冻结 Evidence Pack | 未实现 | 当前只在生成时选择事实并写 ID 数组 | Phase 1 新增 |
| 写作 Skill Registry | 未实现 | `prompt_generation_templates` 是监测问题生成模板，不是写作 Skill | Phase 3 新增；Phase 1 只用版本化 Generation Template |
| Prompt Bundle 快照 | 部分实现 | 只记录 model、prompt version 和 output hash | Phase 1 新增完整受控快照 |
| Canonical/Variant | 未实现 | 一次 Job 只生成单个平台草稿 | Phase 2 新增 |
| Claim-Evidence QA | 未实现 | 没有 claim extraction/entailment | Phase 1 建立基础抽取、映射和人工确认；Phase 2 增加完整自动 entailment/conflict 硬门禁 |
| Delivery Package | 未实现 | 只有同步 Markdown | Phase 2 新增并复用对象存储 |
| 内容级反馈与实验 | 未实现 | 有 Retest，但没有 asset attribution | Phase 4 新增 |

### 2.2 当前薄闭环中的必须修复项

这些问题必须进入 Phase 0，不能被“后续完善”掩盖：

1. **选证据过于粗糙**

   当前内容 worker 默认按 confidence 读取全项目前 5 个 active fact。内容 API 没有传入完整 fact/chunk filter，第一条事实的 subject 又被当成品牌，category 固定为 `GEO knowledge`。可能把竞品或市场事实当成品牌主语。

2. **事实有效期未用于生成守卫**

   `_load_active_facts` 检查 status 和 Chunk 状态，但没有检查 `valid_from/valid_until`。过期事实仍可能参与生成并通过现有审核。

3. **tone 没有真正生效**

   `tone` 已进入 Job，但当前 content generator 没有把它传给模型。

4. **required citations 只比较 Chunk 数量**

   当前没有验证正文是否实际包含引用，也没有证明每个 Claim 被引用事实蕴含。

5. **citation_refs 语义不准确**

   当前写入的是 approved fact ID，不是正文引用或 Claim 到 Evidence 的映射。

6. **风险标记和 Gate 没有统一阻断导出**

   security gate 的 secret marker 不一定进入 draft `risk_flags`；批准和导出也没有统一查询所有 hard gate。理论上可能出现 gate blocked 但人工批准后仍导出的状态。

7. **publish gate 只存在于 schema/config**

   当前缺少明确执行点和不可绕过的 publish/export guard。

8. **任务 lease 可靠性不足**

   Knowledge Pipeline 和 Collection 的 claim 都只领取 `queued` job。worker 在 claim 后被终止、OOM 或节点重启时，记录永久停在 `running`；recovery dispatcher 只重发 actor，不恢复数据库状态。两类 complete/fail 也没有 lease token/owner CAS，若只放开 expired-running claim，旧 worker 仍可能覆盖新 owner 的结果。

9. **新 Pipeline 缺少显式 Publication Intent**

   新 knowledge worker 与现有 Admin 只有导出和 URL 回填，没有“标记为待发布”的显式操作。不能用“导出时自动建 distribution”修补，否则内部复核、备份等导出会被误计为发布任务。

10. **新旧两代知识生成路径并存**

    `knowledge_generation_jobs`、旧 `/v1/knowledge-applications/runtime` 与新的 pipeline jobs 同时存在。Admin 已不再调用旧路径，但数据、API 和测试仍需明确兼容/淘汰计划。

11. **当前“promptfoo”评测不是完整 LLM Eval**

    现有脚本主要验证 approved fact 被使用、pending fact 被排除和 source fact IDs 存在，共三项确定性检查，不能等同多平台 Golden Set 或逐 Claim 评测。

12. **生产部署安全尚未收口**

    base + production overlay 合并后，只有 API 获得 production 对象存储凭据；MinIO、Collector/Report/Knowledge/Dramatiq worker、runtime E2E 和 backup smoke 仍保留 `minio/minio123` 或硬编码默认值。配置非默认凭据时服务身份不一致，使用默认值时生产保留弱凭据。数据面端口、Qdrant 鉴权/TLS、MinIO policy/versioning/encryption 也仍需生产合同。

13. **Fact Review 状态与数据库生命周期约束冲突**

    `0027` 将 `localized_knowledge_facts.status` 限制为 `active/superseded/archived/forbidden`，但当前 Runtime Fact Review 对 `rejected/pending_review` 仍把同名值写入 `status`，会在最新迁移上触发 CHECK 失败。`review_status` 和生命周期 `status` 必须分离，并补真实数据库行为测试。

14. **邀请兑换会缩窄 Session 或错误消费一次性 token**

    邀请兑换按 `project_id` 查询 membership scope，导致已有多项目用户的新 Session 只包含本次邀请项目；同时 Session 只保存全局 roles，无法表达逐项目角色。Admin Web 又在 API 已接受邀请、创建 Session 后才检查管理角色，viewer/analyst 从错误入口提交会消耗 token，却既拿不到 Admin cookie，也无法再去 Customer Web 兑换。另外，当前 FORCE RLS 只认显式 Project Member，tenant admin 即使被写入 Session 也不能访问无 Member 的同 tenant 项目；兑换也没有“事务已提交、Cookie 响应丢失”的稳定重放合同。

### 2.3 现有能力的成熟度表达

后续进度文档必须分别记录：

```text
implemented
contract_tested
integration_tested
live_verified
production_gate_passed
```

不得再用单一 “Done” 同时表示代码存在和真实生产验证通过。

---

## 3. 产品目标、指标与非目标

### 3.1 产品目标

`CG-PROD-001`：用户应从可审计的 GEO 问题或事实出发创建内容，而不是从空白写作请求开始。

`CG-PROD-002`：任何公开事实性 Claim 必须能追溯到冻结 Evidence Pack 中的精确证据版本。

`CG-PROD-003`：证据不足、冲突、过期或不允许用于目标渠道时，系统必须阻断最终生成或发布。

`CG-PROD-004`：同一 Canonical Content 的所有平台 Variant 必须共享核心 Claim 集和 Evidence Pack。

`CG-PROD-005`：每次生成必须可审计重放，包括 Brief、Evidence、Skill、模型策略、Prompt、模型调用、输出、评测和审核版本。

`CG-PROD-006`：Claim 级 coverage 只有在事实性 Claim inventory 完整性经确认后才有效，漏抽取不能形成 100% coverage。

`CG-PROD-007`：Export 和 Delivery 不产生发布意图；只有授权用户对精确版本的显式 Publication Request 才能创建待发布记录。

`CG-PROD-008`：Production 中对象存储 provider 与所有 consumer 必须使用一致、非默认、最小权限的配置；root/application/backup 身份不得混用。

`CG-PROD-009`：Knowledge 与 Collection Durable Job 必须在 worker 崩溃后回收过期租约，并用 fencing token 阻止旧 worker 提交结果。

`CG-PROD-010`：Invitation 只能在目标 surface 合法且 Session 可原子创建时消费；响应丢失时同 key 必须重放同一短时 Session delivery；Session 必须保留同 tenant 完整项目范围并通过 Member/Grant RLS 按项目授权。

这里的“可审计重放”是指能够恢复同一输入和配置，不承诺外部模型产生字节级相同输出。

### 3.2 成功指标

首期上线前先采集基线，再确定正式 SLO。至少记录：

| 指标 | 定义 |
| --- | --- |
| opportunity_to_first_draft_seconds | 接受内容机会到生成首稿 |
| first_draft_to_approval_seconds | 首稿到内部批准 |
| evidence_coverage_ratio | 已支持 Claim / 事实性 Claim |
| unsupported_high_risk_claim_count | 高风险不支持 Claim，发布前必须为 0 |
| first_pass_approval_rate | 首次审核通过比例 |
| human_edit_ratio | 人工修改字符数 / 初稿字符数 |
| content_adoption_rate | 已批准或交付 / 已生成 |
| export_count | 成功导出事件数，不代表交付或发布意图 |
| delivery_rate | 已交付精确版本 / 已批准精确版本 |
| publication_request_rate | 至少产生一个显式 publication request 的精确版本 / 同期 `publication_eligible=true` 的精确版本；Delivery 可选，不作为分母 |
| publication_rate | 已发布 destination / 有效 publication request |
| token_and_cost_per_asset | 每资产 Token 和费用 |
| stale_asset_count | 上游事实或 Skill 变化后待复核资产数 |
| post_publication_geo_delta | 同口径复测变化，仅表示观察关联 |

### 3.3 MVP 非目标

以下能力不进入 Phase 1：

- 自动发布到 CMS 或社交平台；
- 图片、视频和语音生成；
- 高风险金融、医疗、法律内容自动批准；
- 完整多语言工作流；
- 无监督 Skill 自学习；
- 把生成内容自动回灌为知识事实；
- 建设五个以上 Qdrant collection；
- 用单次发布前后变化宣称因果；
- 替代法律、版权、广告和客户授权审查。

---

## 4. 角色与权限

产品角色不等同于数据库角色。当前 `project_members.role` 可持久化值只有 `owner/admin/analyst/viewer`；`rbac.py` 虽定义了 `reviewer/content_operator/client_viewer` 等更细角色和 permission vocabulary，但尚未完整贯穿成员写入、API allowed roles 和 RLS。首期必须先形成 capability 映射与迁移，不能把 `project_admin/internal_operator/compliance_reviewer` 等散落字符串当成已完成 RBAC。

| 产品角色 | 当前可用映射 | 目标 capability | 关键限制 |
| --- | --- | --- | --- |
| GEO Analyst | `analyst` | content read/create brief/generate | 不能批准自己生成的版本 |
| Content Editor | 暂由 `owner/admin` 承担 | `content_operator` | 需要成员角色迁移后才能独立授权 |
| Subject Matter Reviewer | 暂由 `owner/admin/analyst` + 审计 reason 承担 | `reviewer:subject_matter` | 只确认事实，不代表发布批准 |
| Compliance Reviewer | 未正式持久化 | `reviewer:compliance` | 高风险内容启用前必须实现 |
| Internal Approver | 暂由 `owner/admin` 承担 | `content.review` | 必须与 submitted_for_review_by 分离 |
| Customer Approver | `viewer` + customer portal token | `content.accept_customer` | 只能操作 customer-visible 精确版本 |
| Project Admin | `owner/admin` | 项目内容管理 | 不能绕过 hard gate |
| System Worker | maintenance scope | 执行 Job | 不能产生人工审批记录 |

发布必须支持职责分离：

```text
submitted_for_review_by != required_internal_approver
```

高风险内容还必须满足：

```text
internal_approval
+ compliance_approval
+ customer_acceptance（若合同要求）
```

Customer acceptance 与 Internal approval 是两条不同的 `human_review_records`，不得用一个状态互相覆盖。

---

## 5. 统一术语

| 术语 | 定义 |
| --- | --- |
| Monitoring Query | 用于 ChatGPT/Perplexity/Google 等平台观测的正式问题，当前表为 `prompt_questions` |
| Query Candidate | 知识事实生成、待审核后导入的监测问题，当前表为 `prompt_candidates` |
| Generation Template | 生成时使用的内容模板；Phase 1 新增 `content_generation_templates`，仅复用现有 versioned template 的设计模式 |
| Prompt Bundle | 编译后的完整模型输入快照，不等于 Monitoring Query |
| Observation Provider | 被观测的 AI 平台，例如 ChatGPT、Perplexity、Google |
| Publication Channel | 内容发布渠道，例如 Website、LinkedIn、YouTube |
| Content Opportunity | 从 GEO 缺口或 Action Recommendation 投影出的可执行内容机会 |
| Content Brief | 版本化、人工可编辑的生成输入合同 |
| Evidence Pack | 对生成所用证据的不可变快照 |
| Content Asset | 领域概念；Phase 1 物理上继续由 `content_drafts` 表示当前版本 |
| Canonical Asset | 平台无关的权威内容 |
| Variant | 从 Canonical Asset 派生的渠道版本 |
| Claim | 内容中的可验证事实性陈述 |
| Skill | 可组合、可版本化的写作约束和偏好 |
| Delivery Package | 内容、证据、评测、审核和 manifest 的冻结交付包 |
| Export | 生成或下载一个制品的事件，不代表已交付或准备发布 |
| Delivery | 将精确 Asset Version/Package 交付给指定接收方的独立记录 |
| Publication Request | 用户对精确版本、渠道和 destination 发出的显式发布意图 |
| Manual Distribution | Publication Request 后的人工发布执行/回填记录 |

新代码彻底使用 `observation_provider` 或 `publication_channel`；`target_platform/platform` 只允许出现在 Legacy Adapter、兼容 DTO 和历史列中，避免语义冲突。

### 5.1 证据分类不使用单一 A-E 层级

仓库 README 已有 A-D 来源权威等级。文案生成不能再引入含义不同的 A-E 单轴等级。Evidence Pack 对每项证据记录以下正交维度：

```yaml
authority_grade: A | B | C | D
lifecycle_status: active | superseded | archived | forbidden
human_review_status: approved | pending_review | rejected | unknown
validity_status: current | not_yet_valid | expired | unknown
confidentiality: public | internal | confidential | restricted
usage_rights: public_reuse | customer_authorised | quotation_only | internal_only | unknown
claim_risk: low | medium | high | regulated
```

权威等级排序固定为 `A > B > C > D`；比较和最低等级判断必须通过显式 rank 映射，不能依赖字符串排序。

模型推断不是 Evidence，只能记录为 `inference`，不得支持公开事实 Claim。

这些治理字段当前并未作为完整的一等列存在于 fact/chunk。为避免 Phase 1 代码完成后没有任何可用 Evidence，相关 additive migration 和治理回填 MUST 前移到 Phase 0.5；Phase 1 只消费已经治理过的真源。规则是：

- `knowledge_source_assets` 增加或规范 `authority_grade/confidentiality/usage_rights/allowed_channels/consent_expires_at`；
- `localized_knowledge_facts` 保留 `status` 作为生命周期、`review_status` 作为人审结果，并可覆盖 `claim_risk/allowed_channels`；
- Chunk 继承 Source Asset 的治理属性，自己的 `status/embedding_status` 仍只表达技术生命周期；
- Evidence Pack 保存解析后的最终值和来源，不修改上游记录；
- 旧数据回填为 `authority_grade=D`、`confidentiality=internal`、`usage_rights=unknown`，必须人工确认后才能公开生成；
- `unknown` 一律 fail closed，不得为了兼容旧数据默认放行。

Phase 0.5 的迁移先增加可空列和约束较弱的枚举/check，完成分类、owner 分配和异常清理后再收紧 `NOT NULL`/CHECK；该迁移是 Data Readiness Gate 的前置条件，不得推迟到 Phase 1。

---

## 6. 目标架构与领域边界

```text
Admin Web / Customer Web
             |
        FastAPI Routers
             |
  +----------+-----------+----------------+
  |                      |                |
GEO Analysis       Content Domain    Knowledge Domain
  |                      |                |
Score / Gap /       Opportunity       Source Asset
Action / Report     Brief             Parser / Chunk
Retest              Evidence Pack     Approved Fact
  |                 Prompt Bundle          |
  +----------------------+-----------------+
                         |
                  Generation Job
                         |
              PostgreSQL durable ledger
                         |
                Valkey/Dramatiq wake-up
                         |
             knowledge/content worker
                         |
             Canonical -> Variant -> QA
                         |
        Human Review -> Export | Delivery | explicit Publication Request
                         |
                 same-scope GEO Retest
```

### 6.1 共享能力

以下能力继续共享，不在 Content Domain 内复制：

- `audit_events`
- `knowledge_trace_refs`
- `evidence_links`
- `human_review_records`
- `llm_call_logs`
- 项目 RBAC 与 RLS
- S3-compatible object store
- Qdrant adapter
- Dramatiq/Valkey dispatch
- PostgreSQL durable job ledger
- runtime notifications 和 alerts

### 6.2 真源规则

1. PostgreSQL 是 Job、状态、版本、审核、Trace 和发布记录真源。
2. Valkey/Dramatiq 只负责唤醒和调度，不是任务状态真源。
3. Qdrant 只负责候选召回；Evidence eligibility 必须回 PostgreSQL 验证。
4. MinIO 保存大型不可变快照和交付物；PostgreSQL 保存 URI、hash、size、content type 和授权元数据。
5. 生成内容永远不能自动成为 approved fact。

---

## 7. 核心业务流程

### 7.1 标准流程

```text
GEO Gap / Action / Report / Retest
  -> Content Opportunity
  -> accept or dismiss
  -> versioned Content Brief
  -> validate
  -> enqueue Evidence Pack Job
  -> immutable Pack Attempt: ready | needs_evidence | blocked
  -> compile Prompt Bundle
  -> enqueue content_generation_job
  -> generate Canonical Asset
  -> deterministic QA
  -> Claim-Evidence QA
  -> soft quality evaluation
  -> internal review
  -> generate Variants
  -> variant QA/review
  -> optional internal Export（无发布副作用）
  -> Delivery Package / customer acceptance（按项目策略）
  -> explicit Publication Request
  -> manual distribution/backfill
  -> same-scope GEO retest
```

### 7.2 自由 Brief

Manual Brief 可以保留。它允许没有 Opportunity，但不能没有来源和审计：

- 明确 `source_type=manual`；
- 必须关联项目；
- 记录 `created_by/reason/manual_source_refs`；
- 必须构建 Evidence Pack；
- 不得绕过 Evidence/QA/Review gate；
- 审计中记录创建人和原因；
- 高风险领域默认禁止。

---

## 8. Content Opportunity

### 8.1 Phase 1 建模决策

Phase 1 不立即创建第二套推荐引擎。逻辑 `ContentOpportunity` 首先是以下对象的 typed projection：

- `action_recommendations`
- `source_gaps`
- `competitor_benchmarks`
- `visibility_score_snapshots`
- `reports`
- `retest_comparisons`

`action_recommendations.action_type = 'content_opportunity'` 作为主要锚点。建议增量添加：

```text
recommended_asset_type
recommended_channels
opportunity_score
opportunity_score_components
opportunity_formula_version
evidence_readiness
risk_level
opportunity_status
expires_at
```

Projection 的对外 ID 不能伪装成单表 UUID。API 返回不透明 `opportunity_ref`：

```text
action_recommendation:{uuid}
report:{uuid}
retest_comparison:{uuid}
source_gap_projection:{uuid}  # only after a real persisted projection exists
```

服务端负责解析 type/id、校验 allowlist、对象存在性和同 project；客户端不得拆解后自行拼表查询。Phase 3 迁移到独立表时保留旧 ref alias，避免链接和审计失效。

只有当 Opportunity 需要独立批量生成、复杂去重或跨 Action 聚合时，Phase 3 才迁移为独立 `content_opportunities` 表。

### 8.2 机会类型

MVP 支持：

```text
brand_absent
competitor_citation_gap
source_gap
brand_misrepresentation
localisation_gap
```

后续可增加 freshness、entity ambiguity、commercial、trust 和 channel gap。

### 8.3 评分合同

机会分和风险门禁必须分离。风险不能简单作为一个可被高分抵消的 penalty。

```text
base_score =
  0.22 * query_importance
+ 0.20 * visibility_gap
+ 0.16 * competitor_advantage
+ 0.14 * commercial_relevance
+ 0.12 * source_gap_severity
+ 0.09 * localisation_value
+ 0.07 * publication_channel_fit

priority_score =
  normalise_available_components(base_score)
  * evidence_readiness_factor
  * confidence_factor
```

规则：

- 每项 0-100；
- 缺失项不默认为 0，按可用权重重新归一化；
- 保存原始值、权重、公式版本、输入引用和计算时间；
- `evidence_readiness < 50` 时可以接受机会，但不能进入自动生成；
- `risk_level=high/regulated` 进入专门审核路径；
- 评分必须有校准数据，初始权重只标记为 `opportunity_v0_uncalibrated`。

---

## 9. Content Brief

### 9.1 Brief 是正式输入合同

当前 Job request 中的 content type、channel、city、audience、tone、citation 和 target action 是隐式 Brief。Phase 1 拆成：

- `content_briefs`：可变 aggregate head，只保存当前版本、lifecycle status、revision 和来源摘要；
- `content_brief_versions`：不可变业务 payload，每次编辑新增一行。

Head 示例：

```yaml
brief:
  id: uuid
  project_id: uuid
  current_version_id: uuid
  lifecycle_status: draft
  revision: 3
  source_type: action_recommendation
  source_id: uuid
```

不可变版本示例：

```yaml
brief_version:
  id: uuid
  brief_id: uuid
  version: 1
  project_id: uuid
  source:
    type: action_recommendation
    id: uuid
    opportunity_type: source_gap
  objective:
    primary_goal: ai_citation
    secondary_goals: [organic_visibility]
  audience:
    market_code: AU
    locale: en-AU
    persona: small_business_owner
    awareness_stage: solution_aware
  topic:
    primary_question: "..."
    monitoring_query_ids: [uuid]
    required_subtopics: [pricing, GST, limitations]
  asset:
    canonical_type: answer_page
    publication_channels: [website]
    desired_length: long_form
  brand:
    primary_brand_entity_id: uuid
    compared_entity_ids: [uuid]
    allowed_subject_entity_ids: [uuid]
    tone_profile_ref: project_brand_kit
  evidence_policy:
    minimum_claim_coverage: 1.0
    minimum_authority_grade: C
    require_active_facts: true
    allow_inference: false
  constraints:
    forbidden_claims: []
    mandatory_disclosures: []
    legal_review_required: false
    customer_consent_required: false
  schema_version: content_brief_v1
  payload_hash: sha256
```

### 9.2 版本规则

- `content_briefs.id` 标识业务 Brief，`content_brief_versions.id` 标识不可变版本；
- `content_brief_versions.payload/payload_hash` 不可变，`workflow_status` 是该精确版本的受控状态；
- PATCH Brief 必须在同一事务中把旧 current version（包括 draft/validating/validated/evidence_building/needs_evidence/ready/locked）标记为 `superseded`、创建新的 `draft` version，并更新 head 的 `current_version_id/revision/lifecycle_status`；若旧版本有进行中的验证或证据任务，同事务标记 cancel requested；
- 已被 generation job 引用的版本不可修改；
- 新版本必须重新构建 Evidence Pack；
- 使用 `If-Match` 或 revision 防止多人覆盖；
- 每次修改写 `audit_event`，记录 before/after hash 和 reason；
- 旧版本只能转为 `superseded`，不能物理删除；已有 Job 继续引用原 locked version；
- `content_briefs.lifecycle_status` 只是 current version 状态的事务内投影，不允许独立更新。

### 9.3 Brief 状态机

```text
draft
  -> validating
      -> validated
validated
  -> evidence_building
      -> needs_evidence
      -> blocked
      -> ready
ready
  -> locked（已进入生成）
ready/locked
  -> needs_evidence | blocked（上游 validity/rights/policy 失效，清除 selected Pack）
needs_evidence
  -> evidence_building（payload 不变，创建新 Evidence Job/Pack Attempt）
blocked
  -> evidence_building（策略/授权问题修复后创建新 Attempt）
draft/validating/validated/evidence_building/needs_evidence/blocked/ready/locked
  -> superseded（任何内容编辑都创建新 draft version）
任何非终态
  -> cancelled
```

转换守卫：

- `validated` 只证明 Brief schema 和引用对象有效；
- `ready` 必须由 `selected_evidence_pack_id` 指向当前 Brief Version 唯一有效的 ready Attempt；
- `locked` 必须记录 selected exact Evidence Pack 和 Prompt Bundle；
- `superseded` 后不得创建新 Job；
- `needs_evidence` 不允许生成最终文案；修改 Brief 内容必须创建新 version，只有 payload 未变且上游证据已补齐时才能创建新 Evidence Attempt；
- `blocked` 不允许普通 retry；必须先记录 remediation，再创建新 Attempt；
- 新版本创建后，aggregate head 指向新 `draft` version；旧 locked version 及其 Job/Asset lineage 保持不变。

### 9.4 品牌、竞品和事实主体合同

`primary_brand_entity_id` 必填；比较内容必须显式列出 `compared_entity_ids`，Evidence Builder 只允许 `allowed_subject_entity_ids` 中的实体进入主体性 Claim。每个 Fact 和 Evidence Item 必须解析：

```text
subject_entity_id
subject_role = primary_brand | competitor | market | product | neutral
```

守卫：

- 品牌能力 Claim 只能使用该品牌或归属产品的事实；
- 竞品事实不得转换成品牌自述；
- market/neutral 事实不得表述为企业自有能力；
- 比较内容中的每个实体必须有明确角色和同 project 复合外键；
- 无法解析 subject/entity role 时进入 `needs_evidence`，不能回退到第一条 Fact 的 subject。

---

## 10. Evidence Pack

### 10.1 定义

Evidence Pack 是生成时允许使用证据的不可变 Attempt 快照，不是一次实时搜索结果，也不是可以原地重跑的工作区。

来源可以包括：

- active approved fact；
- active + embedded knowledge chunk；
- source asset 和 parser artifact；
- AnswerRun / citation；
- report / action / retest；
- 经审核的官方外部来源。

同一 Brief Version 可以有多个 Attempt：

```text
Brief Version
  +-- Evidence Pack Attempt 1: needs_evidence
  +-- Evidence Pack Attempt 2: blocked
  +-- Evidence Pack Attempt 3: ready
```

每个 Attempt 有递增 `attempt_number`、`previous_pack_id` 和 builder policy version。新 `ready` Pack 产生后，旧 `ready` Pack 可标记为 `superseded`，但其 items、hash、诊断和 lineage 永不修改。

### 10.2 Builder 流程

```text
Brief Version
  -> create durable evidence_pack_job
  -> query decomposition
  -> Qdrant candidate retrieval
  -> PostgreSQL exact fact/chunk lookup
  -> project access check
  -> active/embedded check
  -> valid_from/valid_until check
  -> authority/usage/confidentiality filter
  -> conflict detection
  -> duplicate/near-duplicate collapse
  -> required subtopic coverage
  -> finalization transaction
  -> insert immutable Pack Attempt + items + hashes
  -> ready | needs_evidence | blocked
```

`content_evidence_pack_jobs` 是 Durable Job 真源，使用 `queued/running/retry_wait/finalizing/succeeded/failed/dead_letter/cancelled`，支持 lease、heartbeat、幂等、查询和 replay。技术故障通过 `retry_wait` 重试同一个 Job；业务结论 `needs_evidence/blocked` 会成功完成 Job 并产出终态 Pack。再次构建必须创建新 Job 和新 Attempt，不能修改旧 Pack。

Qdrant 命中只能成为候选。Builder 必须拒绝：

- project 不匹配；
- status 非 active；
- human review status 非 approved；
- embedding_status 非 embedded；
- fact 过期或尚未生效；
- authority、usage rights 或 confidentiality 为 unknown；
- usage rights 不允许目标渠道；
- confidentiality 超出 Model Policy；
- source hash 与数据库记录不一致。

### 10.3 冻结内容

Evidence Item 使用判别联合，不强迫不同来源共享含义模糊的 `statement_snapshot/source_version`：

```yaml
item:
  item_type: approved_fact | chunk | citation | report_extract | action_extract | retest_extract | source_asset
  source_id: uuid
  source_revision:
    kind: row_version | content_hash | report_version | action_revision | retest_run
    value: "3"
  locator:
    page: 3
    chunk_index: 12
    json_pointer: /recommendations/0
  snapshot:
    text: "short fact or extract"
    uri: null
    hash: sha256
    content_type: text/plain
  subject_entity_id: uuid
  subject_role: primary_brand | competitor | market | product | neutral
  authority_grade: A
  lifecycle_status: active
  human_review_status: approved
  valid_from: timestamp
  valid_until: null
  confidentiality: public
  usage_rights: customer_authorised
  allowed_channels: [website, linkedin]
  claim_risk: medium
  public_disclosure_allowed: true
  public_source_url: https://example.com/source
  public_source_title: "Source title"
  citation_label: "Source title"
  quotation_allowed: true
  attribution_required: true
```

短 Fact/节选可保存在 PostgreSQL；长 Chunk、报告节选和机密内容存 MinIO content-addressed 快照，数据库保存 locator、URI、hash、size、content type 和授权。`source_revision.kind/value` 必须非空；snapshot 必须满足 text 或 URI **恰好一个**存在、值 trim 后非空且 hash 必填。需要列表预览时使用独立 `preview_text`（由 snapshot 派生、可重建、不参与证据身份），不能同时把 snapshot 正文存入 text 和 URI。仅保存源 ID 不足以复现，因为上游可能被 supersede。

内部可追踪引用与公开 Citation 分开：

```text
internal_evidence_refs  -- 可包含内部/机密 ID，只供审计
public_citation_refs    -- 只能引用 public_disclosure_allowed=true 的来源
```

公开 Citation 不得泄露内部 Evidence URI、内部标题、机密 locator 或受限引文。

### 10.4 Pack Attempt 结果语义

Pack payload/items 从 finalization insert 起不可变；只有治理投影可做 `ready -> stale/superseded`：

```text
evidence_pack_job: queued -> running -> succeeded | retry_wait | finalizing | failed | dead_letter | cancelled
pack attempt: ready | needs_evidence | blocked
ready -> stale | superseded
```

`needs_evidence` 表示可通过补充事实、来源、主题覆盖或人工治理恢复；`blocked` 表示当前授权、机密级别、同项目约束、事实冲突或安全策略禁止继续。二者都必须保存 machine-readable reason code、owner 和 remediation；旧 Attempt 不会重新进入 building。

典型 `needs_evidence`：

- 必填主题无证据；
- 证据权威等级不足；
- 尚无符合 public citation policy 的来源。

典型 `blocked`：

- 事实冲突未解决；
- 证据使用许可不满足；
- confidentiality 超出 Model Policy；
- 客户案例缺少明确授权；
- cross-project 引用或 source hash 不一致；
- 包含不允许发送给目标模型的数据。

### 10.5 上游失效传播

以下变化必须把相关 Brief/Asset 标为 stale 或 needs revision：

- source asset archive/reject；
- chunk disable/stale；
- fact superseded/forbidden/expired；
- Evidence Pack 规则版本变化；
- Skill hard rule 变化；
- Model Policy 不再允许原数据分类；
- 客户撤销内容授权。

现有项目已经具备部分 chunk/fact 失效传播逻辑，扩展时必须保留。

当失效对象属于 Brief Version 当前 `selected_evidence_pack_id` 时，传播事务必须同时：标记 Pack stale/superseded、清空 selected Pack、将 ready/locked Brief 转为 `needs_evidence/blocked`、对未完成 Generation Job 请求 cancel，并把相关 Asset 标为 `needs_revision/blocked`。deferred selected-ready constraint 在事务提交时校验最终状态，不能先单独把 Pack 标 stale 而留下悬挂 selected 指针。

---

## 11. Generation Template、Skill 与 Prompt Compiler

### 11.1 Phase 1 与 Phase 3 的边界

Phase 1：

- 复用现有 `prompt_generation_templates` 的版本、schema、model config 和 evaluation set **设计模式**，但不复用同一物理表；
- 新建用途明确的 `content_generation_templates`，保存不可变 `GenerationTemplateRelease`，避免 Monitoring Query worker 误读内容输出 schema；
- 将内容模板在领域代码中称为 `GenerationTemplate`；
- 只支持系统级 core、market、content type、channel 组合；
- 项目品牌语气读取现有 Brand Kit；
- 不建设完整 Skill Marketplace。

Phase 3：

- 增加 `content_skill_versions`；
- 支持 system/tenant/project scope；
- 支持 draft/testing/active/deprecated/archived；
- 支持离线评测、灰度 assignment、回滚和效果对比。

长期真源关系固定为：

```text
Skill Version（可编辑规则源）
  -> Content Prompt Compiler
  -> Generation Template Release（不可变可执行产物）
  -> Prompt Bundle（单次生成快照）
```

Phase 1 手工维护的 Template Release 标记 `origin=manual_system_seed`。Phase 3 上线 Skill 后，将这些 release 对应规则迁移为 system Skill，再由 compiler 产生新 release；历史 release 保留，不允许 Skill 和 Template 同时作为可编辑规则真源。

### 11.2 Skill 层级

```text
hard policy:
  security
  privacy
  legal/compliance
  evidence/claim policy

business policy:
  campaign
  brand
  market
  industry
  content type
  publication channel

soft preference:
  core writing style
```

解析不是简单“后者覆盖前者”。每个字段必须声明 merge strategy：

```text
replace
append_unique
intersect
min
max
deny_wins
required_wins
```

安全、隐私、法律、禁止 Claim 使用 `deny_wins`，不能被品牌或 Campaign 覆盖。

### 11.3 Prompt Bundle

每次生成保存：

```yaml
prompt_bundle:
  id: uuid
  project_id: uuid
  brief_version_id: uuid
  evidence_pack_id: uuid
  generation_template_release_id: uuid
  resolved_rule_sources:
    template_release_origin: manual_system_seed
    skill_version_ids: []
  model_policy_version: content_public_v1
  output_schema_version: content_asset_v1
  compiler_version: content_prompt_compiler_v1
  system_prompt_hash: sha256
  user_prompt_hash: sha256
  full_snapshot_uri: s3://...
  full_snapshot_hash: sha256
  context_token_estimate: 12345
  conflict_diagnostics: []
  created_at: timestamp
```

完整 Prompt、Brief 和 Evidence 可能包含敏感数据，因此：

- PostgreSQL 默认只保存元数据、hash 和授权引用；
- MinIO 保存受控完整快照；
- 下载走项目授权代理；
- 日志不得打印完整 Prompt 或 Evidence；
- raw snapshot 有 retention 和 deletion policy。

### 11.4 Prompt 分区

模型输入必须明确分区：

```text
SYSTEM_SECURITY_POLICY
EVIDENCE_AND_CLAIM_POLICY
BRAND_AND_MARKET_POLICY
PUBLICATION_CHANNEL_RULES
TASK_BRIEF
UNTRUSTED_EVIDENCE_DATA
OUTPUT_JSON_SCHEMA
```

Evidence 永远是数据，不能进入 system instruction；生成任务默认无工具调用权限。

---

## 12. Model Policy 与统一 Gateway

### 12.1 当前缺口

仓库已有 `LLMGateway` 和 `LiteLLMGateway`，可记录 request/response hash、Token、成本、延迟和 retry。但当前内容、Prompt 和事实生成仍直接调用 DeepSeek，未进入统一 call log。

`CG-MODEL-001`：所有新内容生成和评测 MUST 通过统一 Gateway；前端和 worker 不得直接绑定 provider endpoint。

### 12.2 Model Policy

```yaml
model_policy:
  key: content_public_long_form
  version: 1
  task: canonical_long_form
  preferred_model: provider/model
  compatible_fallbacks: [provider_b/model_y]
  input_classifications: [public, internal]
  pii_policy: authorised_public_only
  confidential_allowed: false
  external_training_allowed: false
  max_input_tokens: 80000
  max_output_tokens: 10000
  temperature: 0.2
  top_p: 1.0
  seed: null
  structured_output_required: true
  timeout_seconds: 120
  max_gateway_attempts_per_operation: 2
  max_model_calls_per_job: 3
  max_cost_usd: 2.00
```

`external_training_allowed=false` 不能只是调用参数。Provider Capability Registry 必须记录 provider/model、训练/保留政策证据、区域、数据分类、合同版本、复核时间和有效期；Gateway 只有在能力记录满足 Model Policy 时才能路由。

### 12.3 Gateway 行为

当前 `LLMGateway.chat(messages, model, metadata)` 无法承载完整 Model Policy。目标接口应增加结构化 request，旧 `chat` 通过 adapter 兼容：

```python
@dataclass(frozen=True)
class ModelGatewayRequest:
    messages: tuple[dict[str, str], ...]
    model: str
    response_schema: dict[str, object] | None
    temperature: float
    top_p: float
    max_output_tokens: int
    seed: int | None
    timeout_seconds: float
    policy_key: str
    policy_version: str
    metadata: dict[str, object]


@dataclass(frozen=True)
class ModelGatewayResult:
    output: dict[str, object]
    call_log_id: UUID
    attempt_call_log_ids: tuple[UUID, ...]
    provider_request_id: str | None
    configured_model: str
    provider_reported_model: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_usd: Decimal | None
    finish_reason: str | None
    response_hash: str


class ModelGateway(Protocol):
    def generate(self, request: ModelGatewayRequest) -> ModelGatewayResult: ...
```

必须实现：

- Schema-aware structured output；
- provider timeout 与 rate limit 分类；
- 仅在兼容模型间 fallback；
- exponential backoff + jitter；
- circuit breaker；
- 每 project/tenant/任务预算；
- request/response hash；
- provider request ID；
- exact model name/revision；
- Token、成本、延迟；
- `llm_call_logs` 持久化并关联 generation job；
- `llm_call_logs` 增加 nullable `generation_job_id/evaluation_id/prompt_bundle_id`，成功和失败调用都必须持久化；
- 每次 retry/schema repair/fallback 都有独立 call log；最终 result 返回采用的 call ID 和完整 attempt ID 序列，失败异常也携带 call IDs/retryability；
- 敏感正文脱敏；
- 模型升级 Golden Set 门禁。

Schema 修复、同 provider retry、fallback 和 Job retry 共同消耗 `max_model_calls_per_job/max_cost_usd`。Gateway 每次调用前原子预留预算、结束后结算；Job retry 不会重置预算，避免 `Gateway 3 x Job 3` 产生 9 次付费调用。Schema 失败最多修复一次，不得通过删除必填字段让输出“通过”。

---

## 13. Canonical Content 与 Variant

### 13.1 建模决策

领域统一使用 `ContentAsset`。Phase 1 不立即创建与 `content_drafts` 平行的 `content_assets` 真源：

- `content_drafts` 表示 Asset 的当前投影；
- 新增正文载荷不可变的 `content_draft_versions`；
- `content_draft_versions.workflow_status` 表示精确版本状态，正文、结构化内容和 hash 插入后不可变；
- `content_drafts.current_version_id/current_status` 仅作为当前版本查询投影，在同一事务中维护；
- 增加 `asset_role = canonical | variant`；
- 增加 `parent_draft_id`；
- 增加 `publication_channel` 和 `locale`；
- 增加 `content_json`、`rendered_text`、`current_version`；
- 增加 `brief_version_id/evidence_pack_id/prompt_bundle_id`。

后续如需把表改名为 `content_assets`，必须通过 view/adapter 兼容，而不是双写两套长期真源。

### 13.2 Canonical 合同

Canonical Asset 保存：

- 核心 Claim；
- 章节和内容结构；
- FAQ；
- 比较维度；
- CTA；
- `internal_evidence_refs`；
- `public_citation_refs`；
- 必须保留的信息；
- 禁止下游 Variant 修改的约束。

### 13.3 Variant 合同

Variant 必须引用：

- Canonical version；
- Evidence Pack；
- Prompt Bundle；
- channel Skill version；
- generation Job；
- QA result；
- review records。

Variant 不得：

- 新增 Canonical 中没有且 Evidence Pack 不支持的事实；
- 删除 mandatory disclosure；
- 改变数字、价格、时间和限定词；
- 绕过渠道合规规则。

### 13.4 MVP 渠道

Phase 1：Website Canonical Article/Answer Page。

Phase 2：

- LinkedIn Post；
- YouTube Script。

Reddit、Newsletter、Instagram、Google Business 和 Sales Enablement 后置。

### 13.5 人工编辑创建新 Asset Version

已持久化 Version 的正文和 hash 不可修改。Admin Editor 的“保存”必须基于精确版本创建新 Version，而不是 UPDATE 原行：

```json
{
  "base_version_id": "uuid",
  "base_content_hash": "sha256...",
  "content_json": {},
  "rendered_text": "optional client preview",
  "reason": "Customer requested changes"
}
```

规则：

- `content_json` 是唯一 canonical 正文；服务端按固定 `content_schema_version + renderer_version` 生成 `rendered_text`，客户端若提交 preview，服务端必须重渲染并比较，规范化后不一致返回 `422 rendered_content_mismatch`；
- canonical JSON 使用固定字段、UTF-8 和 JCS/RFC 8785 序列化；`content_hash = sha256(canonical_json({content_schema_version, renderer_version, content_json}) + NUL + rendered_text_utf8)`，renderer 升级必须创建新 Version；
- 使用 Asset head `ETag/If-Match` 和 `base_content_hash` 防止并发覆盖；
- `base_version_id` 必须等于当前 head，否则返回 `409 base_version_not_current`；ETag/hash 不匹配返回 `412 content_hash_mismatch`；
- 新版本记录 `edited_by/edited_at/reason/base_version_id`，从 `generated -> qa_running` 重新开始；
- 旧版本转 `superseded`，其有效审批全部 invalidate 但不删除；
- Claim extraction、inventory completeness、Evidence support、QA 和 Review 全部重跑；
- 历史 Export、Delivery、Publication 和 Customer Acceptance 仍绑定旧精确版本，不改挂到新版本；
- superseded/archived 版本只读，不允许继续审批、交付或创建新发布请求。

版本插入、head 切换和 `content_evaluation_jobs` outbox 创建在同一事务完成并返回 `201 Created`；响应附 `evaluation_job_id/status_url`。QA 由可查询、可恢复的 Evaluation Job 异步执行，不使用只有前端 ID、没有 durable ledger 的临时任务。

---

## 14. 生成 Job、Worker、幂等与恢复

### 14.1 现有调度语义

```text
API transaction
  -> PostgreSQL content_generation_jobs
  -> dispatch_background_task
  -> Valkey/Dramatiq actor
  -> worker claim with DB lease
  -> result + audit + trace in DB
```

Valkey 消息可以重复或丢失，PostgreSQL ledger 必须保证最终可恢复。

### 14.2 Phase 0 扩展字段

现表已有 `locked_by/locked_at/lease_expires_at/heartbeat_at/attempt_count/max_attempts/next_run_at`。Phase 0 需要让 worker 真正执行 heartbeat 和过期 lease 回收，并增量添加：

```text
source_fact_filter jsonb NOT NULL DEFAULT '{}'
source_chunk_filter jsonb NOT NULL DEFAULT '{}'
input_snapshot jsonb NOT NULL DEFAULT '{}'
input_snapshot_hash
request_idempotency_scope_hash
request_idempotency_key_hash
request_payload_hash
execution_fingerprint
regeneration_nonce
replay_nonce
parent_job_id
max_model_calls_per_job / model_calls_used
max_total_cost_usd / cost_usd_used
max_prompt_tokens / prompt_tokens_used
max_completion_tokens / completion_tokens_used
dead_lettered_at
cancel_requested_at
result_draft_id
correlation_id
lease_token uuid
lease_reclaimed_count integer NOT NULL DEFAULT 0
last_reclaimed_at/last_reclaimed_from
```

Phase 0 的持久化链路必须闭合：API request -> `knowledge_pipeline_runs.metadata` -> `content_generation_jobs.source_*_filter` -> worker。若调用方提交了 filter 而入队后丢失，Job 必须失败，不能静默回退为“全项目前 5 条”。

幂等分两层：

- `request_idempotency_scope_hash + request_idempotency_key_hash`：API 在创建 Job 前根据调用方 Header、actor、route 和 canonical request payload 防止网络重复提交；原始 opaque key 不落库；
- `execution_fingerprint`：worker 解析最终 Evidence/规则/模型后，根据冻结 `input_snapshot_hash + regeneration_nonce + replay_nonce` 防止相同执行重复写 Asset。

worker 领取 Job 后、调用外部模型前，在短事务和行锁内一次性初始化最终 brand/category/tone、来源对象、已解析 fact/chunk ID 及其 hash 到 `input_snapshot/input_snapshot_hash/execution_fingerprint`，随后 commit 并释放锁。外部模型调用期间绝不能持有数据库行锁；hash 非空后不可改写。

```text
短事务：SKIP LOCKED claim + freeze input + lease token
  -> commit/release lock
  -> external model call
  -> 短事务：validate status/worker/lease/fingerprint
  -> atomically write Version/trace/audit/outbox + Job succeeded
```

Phase 1 创建对应表后，再增加 `brief_version_id/evidence_pack_id/prompt_bundle_id` 外键。Content v1 Job 必须引用这些精确版本，legacy Content v0 Job 才允许为空。

`regeneration_nonce/replay_nonce` 为非负整数，默认 `0`。Legacy row 可以暂时没有 key，新路径必须非空。请求作用域必须物理参与唯一索引，不能只写在 service 注释中：

```sql
CREATE UNIQUE INDEX ... ON content_generation_jobs(
  project_id, request_idempotency_scope_hash, request_idempotency_key_hash
)
WHERE request_idempotency_key_hash IS NOT NULL;

CREATE UNIQUE INDEX ... ON content_generation_jobs(project_id, execution_fingerprint)
WHERE execution_fingerprint IS NOT NULL;
```

`request_idempotency_scope_hash = sha256(project_id + actor_id + canonical_route)`，`request_idempotency_key_hash = sha256(scope_hash + opaque_header_key)`，并单独保存 `request_payload_hash`；同 scope/key 不同 payload 返回 `409 idempotency_key_reused`。actor/route 变化不会误冲突，日志和响应不得回显原始 key。worker 的 `execution_fingerprint` 默认计算：

```text
sha256(
  project_id
  + input_snapshot_hash
  + model
  + prompt_bundle_id
  + prompt_bundle_full_snapshot_hash
  + generation_template_release_id
  + template_release_hash
  + compiler_version
  + publication_channel
  + regeneration_nonce
  + replay_nonce
)
```

Phase 1 起将 `brief_version_id + evidence_pack_id + prompt_bundle_id/full_snapshot_hash + generation_template_release_id/release_hash + compiler_version + resolved_skill_hash（Phase 3 前可为空）+ model_policy_version + publication_channel` 纳入 `input_snapshot_hash`，不另建第二套幂等算法。不同 Prompt Bundle/Template Release 即使来自同一 Brief/Pack 也不能被错误去重。

迁移还必须 drop/recreate 当前 status CHECK，正式加入 `retry_wait/dead_letter`；只改应用常量而不改数据库约束会导致运行时失败。

### 14.3 Job 状态机

```text
queued
  -> running
      -> succeeded
      -> retry_wait
      -> failed（不可重试的业务失败）
      -> dead_letter
      -> finalizing -> succeeded | retry_wait | dead_letter
queued/running/retry_wait/finalizing
  -> cancelled
```

必须支持：

- `FOR UPDATE SKIP LOCKED`；
- heartbeat；
- expired lease reclaim；
- attempt 上限；
- `retry_wait` 到期重新入队；
- dead letter；
- `retry`：只允许 `retry_wait -> queued`，复用同一 Job、input 和 key，不增加 nonce；可由调度器到期触发，也可由授权用户提前触发；
- `failed` 是 terminal 且不能原地 retry。若服务端判断同一冻结输入可通过重新采样/兼容模型处理，才返回 `regenerate` action 并创建 nonce+1 的新 Job；若 Brief、Evidence、Prompt 或策略输入本身错误，必须创建新的 Brief Version/Pack/Prompt Bundle 后再建 Job，不能声称 regenerate 修正了不可变 input snapshot；
- `regenerate`：创建新 Job，`regeneration_nonce + 1`；
- dead-letter `operator replay`：创建新 Job，保存 `parent_job_id`，`replay_nonce + 1`；
- cancel；
- 同一 request key 不重复建 Job，同一 execution fingerprint 不重复写 Asset；
- 单 Asset Job 不使用 `partial_succeeded`；模型结果成功持久化即 Job `succeeded`，QA 不通过由 Asset `blocked/needs_revision` 表达；
- 结果与 Job 均在 PostgreSQL 时，MUST 在同一事务写结果、trace/audit 并完成 Job；
- 涉及 MinIO 时使用 pending artifact -> hash verify -> `finalizing` -> finalize/outbox 协议；进入 `finalizing` 前外部模型结果和 pending artifact 元数据已冻结，lease 恢复器只重做幂等的 hash verify/finalize/DB 引用，绝不能再次调用模型；
- 完成事务必须重新校验 lease owner、lease expiry 和 execution fingerprint；
- dispatch outbox 或 recovery dispatcher；
- 崩溃恢复测试。

### 14.4 Knowledge/Collection 过期租约恢复合同

该合同是现有 Durable Queue 的 Base 前置能力，适用于 `knowledge_import_jobs/crawl_jobs/knowledge_parser_runs/chunk_jobs/embedding_jobs/fact_extraction_jobs/prompt_generation_jobs/content_generation_jobs` 以及 `collection_jobs`。`knowledge_pipeline_runs` 是 aggregate scheduler 状态，仍只从 `queued` 启动；不能把子 Job reclaim 条件误套到已运行 Pipeline aggregate。Valkey/Dramatiq 只负责唤醒，PostgreSQL row 是任务状态真源；recovery dispatcher 重发 actor 不能替代数据库租约恢复。

Phase 0 migration 必须：

- 为所有 Knowledge Job 增加 `lease_token/lease_reclaimed_count/last_reclaimed_at/last_reclaimed_from/dead_lettered_at/cancel_requested_at`；
- 为 Collection Job 同时增加 `heartbeat_at/lease_token/lease_reclaimed_count/last_reclaimed_at/last_reclaimed_from/dead_lettered_at/cancel_requested_at`；
- 收口各表 status CHECK 时追加 lease 共通状态 `retry_wait/dead_letter`，有 artifact finalize 的表再追加 `finalizing`，同时保留每张表现有合法状态（例如 Import 的 `draft/ready`、Parser 的 `fallback_succeeded`、合法 batch 的 `partial_succeeded`）；只有单 Asset Content Job 明确禁止 `partial_succeeded`，不能用一套枚举覆盖所有 Knowledge 表；
- 增加 active-lease CHECK：`running/finalizing` 时 `locked_by/locked_at/lease_token/lease_expires_at/heartbeat_at` 必须全部非空，防止再次产生 claim 永远无法命中的 active row；
- 保留 Collection 多子项任务的 `partial_succeeded`，但它不用于单 Asset Content Job。

每次 claim 都在一个短事务中以 `FOR UPDATE SKIP LOCKED` 原子选择并更新一条记录：

```text
claimable =
  (status IN (queued, retry_wait) AND next_run_at/next_attempt_at <= now())
  OR
  (status IN (running, finalizing) AND lease_expires_at IS NOT NULL AND lease_expires_at <= now())

AND attempt_count < max_attempts
AND cancel_requested_at IS NULL

UPDATE claimed row:
  status = finalizing when reclaimed from finalizing, otherwise running
  locked_by = new_worker_id
  lease_token = new_random_uuid_per_claim
  locked_at/heartbeat_at = now()
  lease_expires_at = now() + lease_duration
  attempt_count = attempt_count + 1
  lease_reclaimed_count += 1 only when previous status was running/finalizing
  last_reclaimed_from = previous locked_by only when reclaimed
```

不能先把所有 expired row 批量重置为 queued 后再领取，这会制造竞争窗口。expired `finalizing` 必须保持 `finalizing` 并只重做幂等 artifact finalize，禁止重调 provider/model。attempt 已耗尽的 expired active row 由同一 recovery transaction 或独立受锁 sweeper 转为 `dead_letter`、清空 owner/token/lease 并写 error/audit；`cancel_requested_at` 非空的 expired row 转为 `cancelled`，不得接管执行。

领取调度冻结为 **expired-first + 逐表公平 recovery pass**，不得继续按固定 `JOB_TABLES` 遇到第一个有 fresh Job 的表就提前返回：

1. 每个 recovery interval 先按 round-robin 对 8 张 Knowledge Job 表和 Collection 各执行至少一次 bounded recovery claim/reap，一轮内每表都获得机会；
2. 每表 recovery 查询只选 expired `running/finalizing`，按 `lease_expires_at ASC, priority DESC, created_at ASC` 选择，完成 owner transfer/dead-letter/cancel 后才给该表的 fresh `queued/retry_wait` 配额；Collection 没有 priority 时按 `lease_expires_at ASC, created_at ASC`；
3. 跨表第一轮完成后，才可用剩余 worker/`max_jobs` 预算消费 fresh backlog；必须预留 recovery slots，fresh backlog 不得耗尽回收配额；
4. 若单表 expired 超过一轮 batch，以持久化 round-robin cursor 继续下一轮；`recovery_batch_per_table/interval` 必须按已批准峰值容量设置，并用压测证明最老 expired row 在 2 个 interval 内完成 token 转移或合法终止；超容量时立即告警，不能静默放宽 SLO。

recovery dispatcher 必须按表发出 wakeup，或调用携带 preferred table 的 actor；actor 仍在上述短数据库事务中执行 owner transfer，dispatcher 不能在数据库外伪造租约。

每次 claim 产生的 `lease_token` 是 fencing token。Heartbeat、complete、fail、worker 对 cancel 的确认以及 finalize 必须使用 CAS：

```sql
UPDATE job_table
SET heartbeat_at = now(), lease_expires_at = now() + :lease
WHERE id = :id
  AND status IN ('running', 'finalizing')
  AND locked_by = :worker_id
  AND lease_token = :lease_token
  AND lease_expires_at > now()
RETURNING id, cancel_requested_at, lease_expires_at;
```

complete/fail/finalize 使用相同 `id + status + locked_by + lease_token + lease_expires_at > now() + cancel_requested_at IS NULL` 守卫，并在写结果前再次确认 lease 未失效；返回 0 行表示 worker 已丢失租约或 cancel 已先线性化，必须丢弃本地结果且不能写业务副作用。只检查 `locked_by` 不够，因为进程重启可能复用同一个 worker ID。

外部 cancel command 不需要知道 worker token，但按当前状态分支：`queued/retry_wait` 直接以 revision/state CAS 转 `cancelled`；`running/finalizing` 只原子设置 `cancel_requested_at`。heartbeat 必须 `RETURNING cancel_requested_at`，当前 owner 协作停止后以 token CAS 转 `cancelled`；owner 已崩溃则 expired sweeper 转 cancelled。若 complete/fail 先提交，cancel 对 terminal row 返回 `409`；若 cancel request 先提交，promotion 的 `cancel_requested_at IS NULL` 守卫阻止 succeeded/failed，形成明确线性化。retryable handler error 在当前 token 下转 `retry_wait` 并用数据库时钟计算 backoff；non-retryable error 转 terminal `failed`；本次 attempt 已达上限则直接 `dead_letter`。

`lease_token` 只进入 worker 内部 DTO/LeaseGuard，不得进入 Web/API、普通日志或用户可下载 artifact。claim/reclaim audit 与 owner/token 更新同事务写入，但 audit 只记录 token fingerprint、previous worker、attempt 和 reason。

worker 在外部模型、crawler 或 subprocess 执行期间不得持有数据库锁，但必须由独立 DB connection 的 LeaseGuard/进度回调以不超过 `lease_duration / 3` 的间隔续租；该连接必须初始化与 owner 一致的 maintenance/RLS context，否则 FORCE RLS 下的 0-row update 会被误判为 LostLease。阻塞式 Collection subprocess 必须改为可轮询/可终止的执行方式或由后台 LeaseGuard 包裹。连续 heartbeat 失败或 CAS 失败即停止/隔离当前执行；lease duration 必须大于网络抖动和调度暂停预算，actor time limit 必须大于 handler timeout + cleanup，不能用超长固定 lease 掩盖没有 heartbeat 的问题。租约有效性一律使用 PostgreSQL `now()`，不能使用 worker 本地时钟判定。

队列必须分别建立与 claim predicate 匹配的 partial index：

```sql
CREATE INDEX ... ON job_table(next_run_at, priority DESC, created_at)
WHERE status IN ('queued', 'retry_wait');

CREATE INDEX ... ON job_table(lease_expires_at, priority DESC, created_at)
WHERE status IN ('running', 'finalizing') AND lease_expires_at IS NOT NULL;
```

Collection 使用 `next_attempt_at, created_at` 代替 `next_run_at, priority, created_at`。迁移后必须对真实 claim SQL 运行 `EXPLAIN (ANALYZE, BUFFERS)`，证明不会为每次 recovery 扫描全部历史终态 Job。

该模型提供 at-least-once 执行，不承诺 exactly-once provider call；业务结果仍必须使用 job ID、execution fingerprint、content hash 或目标自然键幂等。result/trace/audit/terminal Job 必须在验证 lease 后的同一短事务 promotion，中间 artifact 使用 attempt-scoped key，旧 token 的 attempt 永远不能 finalize/publish。recovery dispatcher 每个 interval 负责完成逐表公平 wakeup/recovery pass 并记录 reclaimed/dead-letter/starvation 指标，实际 owner 转移只能发生在上述数据库 claim transaction。

迁移 rollout 必须先停领/drain 旧 consumer；遗留 `running/finalizing` 且 token/lease 缺失的 row 按明确规则标为 expired recoverable 或进入人工 DLQ，建立/验证 active-lease CHECK、status CHECK 与 partial index 后再启动新 consumer。不能在旧 complete/fail 仍只按 `id` 更新时提前启用 reclaim。

### 14.5 是否拆 content worker

Phase 0 先在当前 knowledge worker 内修复可靠性并抽出独立 handler/service。

满足任一条件时拆 `process_content_queue`：

- 内容 Job 占 knowledge queue 处理时间超过 30%；
- 长文模型调用影响导入/解析 SLA；
- 内容任务需要不同并发、内存或网络策略；
- 需要独立扩缩容、预算或故障域。

拆分时沿用同一 PostgreSQL Job 合同，不复制表。

---

## 15. 质量评测与发布硬门禁

### 15.1 第一层：确定性检查

- JSON Schema；
- 必填标题/章节；
- 长度、段落和 CTA；
- en-AU 拼写、AUD/GST 格式；
- URL 和 HTML 安全；
- 禁用词、禁止 Claim；
- disclosure；
- Evidence ID 存在；
- Evidence 有效期；
- PII/secret；
- Prompt Injection marker；
- 竞争对手商标和高风险比较规则；
- publication channel 限制。

### 15.2 第二层：逐 Claim 证据检查

```text
Asset Version
  -> Claim Extraction
  -> Claim normalisation
  -> Evidence Pack matching
  -> entailment/conflict check
  -> supported/partial/unsupported/conflict/inference
  -> hard gate
```

每个 Claim 保存：

```yaml
claim:
  text: "..."
  start_offset: 120
  end_offset: 188
  claim_type: product_capability
  subject_entity_id: uuid
  subject_role: primary_brand
  risk_level: high
  support_status: partially_supported
  evidence_item_ids: [uuid]
  evaluator_key: claim_evaluator
  evaluator_version: 2
  rationale: "..."
```

高风险 `partial/unsupported/conflict` 必须阻断。

只检查“已抽取 Claim”会产生漏抽取绕过。每个精确 Asset Version 必须有独立的 Claim Inventory Review：

```yaml
claim_inventory_complete: true
claim_inventory_hash: sha256
claim_inventory_reviewed_by: user_id
claim_inventory_reviewed_at: timestamp
extractor_key: claim_extractor
extractor_version: 3
```

Reviewer 必须分别确认：1）事实性 Claim inventory 完整；2）每个已抽取事实 Claim 的 support。新 Asset Version、正文变更或 extractor version 变化都会 invalidate completeness。`claim_inventory_complete != true` 时，`evidence_coverage_ratio` 必须返回 `null/unknown`，不能显示为 100%。

分阶段执行口径：

- Phase 0 的内联 Claim/Evidence ID 只做对象存在、状态和同 project 检查，不产生 `supported` 结论；
- Phase 1 持久化 Claim 和 Evidence 映射，由确定性规则筛除无效引用，并由内部 reviewer 对公开事实 Claim 的 support status 作最终确认；
- Phase 2 才引入版本化自动 entailment/conflict evaluator、Golden Set 和对抗集；自动结果仍不能覆盖高风险人工审核要求。

### 15.3 第三层：软质量评测

维度包括：

- publication channel fit；
- brand voice；
- AU localisation；
- clarity；
- originality；
- commercial alignment；
- GEO usefulness；
- structure；
- readability。

软分不能覆盖 hard gate。`citation_likelihood` 只能作为代理指标，不能显示为真实被引用概率。

### 15.4 Export、Delivery 与 Publication 资格

```text
exportable_internal =
  schema_gate == passed
  AND security_gate == passed
  AND privacy_gate == passed
  AND traceability_gate == passed
  AND actor_can_export_internal

deliverable_customer =
  exportable_internal
  AND evidence_gate == passed
  AND claim_inventory_complete == true
  AND unsupported_high_risk_claim_count == 0
  AND required_internal_reviews == approved
  AND customer_safe_package == passed

publication_eligible =
  deliverable_customer
  AND public_citation_gate == passed
  AND usage_rights_gate == passed
  AND customer_acceptance_satisfied
  AND publication_channel_policy == passed
```

上式是 Content v1 合同。Phase 0 尚无 Claim 表时使用严格的兼容 guard：exact draft hash、所有 Base hard gate、active/valid approved Fact/Chunk、允许公开使用的 rights、有效 internal approval，以及 review payload 中人工确认的 `inline_claim_inventory_complete=true`。Phase 0 不计算/展示 evidence coverage；Phase 1 上线后该临时字段迁移为正式 Claim Inventory Review 并停止写入。

`customer_acceptance_satisfied` 精确定义为：

```text
NOT customer_acceptance_required
OR valid customer_acceptance exists for exact asset_version_id + content_hash
```

内部导出可以用于复核、法务或备份，不产生 Delivery/Publication 状态；未通过 Evidence/Review 的内部包必须带不可移除的 `DRAFT / NOT FOR PUBLICATION` manifest 标记。客户包和 publication request 必须分别校验后两种资格。

初始分数阈值只是待校准配置，不得在没有标注集时把 `95` 等数字描述成科学结论。

### 15.5 accepted risk

以下门禁永远不能 accepted risk：

- secret；
- unauthorised PII；
- classification policy violation；
- unredacted restricted data；
- Prompt Injection；
- cross-project/cross-tenant evidence；
- high-risk unsupported claim；
- traceability；
- legal/customer consent required；
- publish approval。

其他 warning 的 accepted risk 必须有审批人、原因、到期时间和受影响对象。

---

## 16. 对象状态机

### 16.1 Opportunity

```text
proposed -> accepted -> converted
proposed -> dismissed
proposed/accepted -> expired
accepted -> blocked
blocked -> accepted（问题修复后恢复）
proposed/accepted/blocked -> terminated（人工明确终止，必须有 reason）
blocked -> dismissed | expired
```

### 16.2 Brief

```text
draft -> validating -> validated
validated -> evidence_building -> needs_evidence | blocked | ready
ready -> locked
ready/locked -> needs_evidence | blocked（上游失效并清除 selected Pack）
needs_evidence -> evidence_building（同一 payload，创建新 Job/Attempt）
blocked -> evidence_building（remediation 后创建新 Job/Attempt）
任一非终态 -> superseded（仅通过创建新 draft version）
```

该状态机属于精确 Brief Version；`content_briefs.lifecycle_status` 只镜像 current version，不是第二真源。

### 16.3 Evidence Pack

```text
evidence_pack_job: queued -> running -> retry_wait | finalizing | succeeded | failed | dead_letter | cancelled
pack attempt terminal result: ready | needs_evidence | blocked
ready -> stale | superseded（只改变治理投影，snapshot/items 不变）
```

`needs_evidence/blocked` 后重试必须创建新 Attempt；Brief Version 的 `selected_evidence_pack_id` 只能指向同 project、同 Brief Version 的 `ready` Attempt。

### 16.4 Generation Job

见第 14.3 节。

### 16.5 Asset

Phase 1 后，以下状态属于精确 Asset Version：

```text
generated
  -> qa_running
qa_running
  -> pending_human_review
  -> needs_revision
  -> blocked
pending_human_review
  -> approved
  -> needs_revision
  -> rejected
approved
  -> needs_revision（上游失效）
任何非终态
  -> archived
旧版本
  -> superseded
```

Export、Delivery 和 Published 都不属于 Asset workflow。Phase 0 暂时兼容现有 `content_drafts.status=exported/published`，但只允许 Legacy Adapter 读写；Phase 1 回填后，`content_draft_versions.workflow_status` 不包含这些值，`content_drafts.current_status/review_status` 只投影 current version。查询可返回 `last_exported_at/delivery_package_count/latest_delivery_status/publication_request_count`，这些是独立对象的聚合投影，不得反向驱动 Asset 状态。

### 16.6 Delivery

```text
delivery job: queued -> running -> retry_wait | finalizing | succeeded | failed | dead_letter | cancelled
delivery package: ready -> customer_visible -> revoked
```

Package 永远绑定精确 Asset Version/hash；事实失效只会阻断后续下载/交付并产生 stale/revoked 投影，不会篡改历史包。

### 16.7 Publication

Phase 0-2 Manual Distribution：

```text
awaiting_url_backfill -> url_backfilled -> published -> verified
awaiting_url_backfill/url_backfilled/published -> blocked
```

`/url` 只执行 `awaiting_url_backfill -> url_backfilled`，`/confirm-published` 只执行 `url_backfilled -> published`，`/verify` 只执行 `published -> verified`；三者不能合并或跳级。`blocked` 为该 attempt 的终态，修复后需创建新的 publication request/attempt，以保留失败历史。

Phase 4：

```text
draft -> scheduled -> publishing -> published
scheduled -> cancelled
publishing -> failed
failed -> cancelled | retrying
retrying -> publishing
published -> unpublished
```

Delivery 不等于 Published，Published 也不保证产生 GEO 提升。

---

## 17. 数据模型与迁移策略

### 17.1 复用、扩展、新增、后置

| 对象 | 决策 |
| --- | --- |
| `action_recommendations` | 扩展为 Phase 1 Opportunity 投影 |
| `content_generation_jobs` | 扩展，不新建 generation_runs |
| `content_drafts` | 扩展为 Asset 当前投影 |
| `human_review_records` | 复用并扩展精确 Asset Version、review kind、policy 和失效字段 |
| `knowledge_trace_refs` | 复用并扩展类型 |
| `knowledge_quality_gates/findings/runs` | 复用 |
| `manual_distribution_records` | 仅由显式 publication request 创建；Phase 0 绑定 draft+hash，Phase 1-2 绑定精确 Version，Phase 4 迁移为 attempt/兼容投影 |
| `llm_call_logs` | 复用并关联 generation/evaluation |
| `model_provider_capabilities` | Gateway 共享治理表；训练、保留、区域、数据分类和合同有效期 |
| `audit_events` | 复用 |
| Knowledge 8 类 Job + `collection_jobs` | Phase 0 统一增加 lease token、heartbeat、expired-running reclaim、CAS terminal 和 DLQ；不另建队列真源 |
| `runtime_sessions` | Phase 0 扩展为 scope v2；保存 tenant roles 和逐项目 roles/permissions/capabilities，flat role 不再用于授权 |
| Auth redemption attempt ledger | Phase 0 新增；短时 envelope-encrypted Session delivery、同 key 稳定重放、confirmation/replay limit/secret erasure |
| `project_members/project_member_invitations` | Phase 0 移除 viewer 全局唯一，改为项目内 case-insensitive 唯一；两者增加 tenant 复合 FK，Invitation 增加 audience/surface policy |
| `runtime_project_access_grants` | Phase 0 新增可审计 tenant-role -> Project 授权投影，与 Member 共同作为 FORCE RLS 锚点 |
| `prompt_generation_templates` | 保持 Monitoring Query 模板专用，不混入内容模板 |
| `content_generation_templates` | Phase 1 新增不可变 Template Release；Phase 3 后只允许 compiler 产生新 release |
| `knowledge_generation_jobs` | Legacy，只读兼容后淘汰 |
| `faq_answer_candidates` | Legacy，只读兼容后合并到 Asset |
| `content_briefs` | 新增，可变 aggregate head |
| `content_brief_versions` | 新增，不可变业务 payload |
| `content_brief_subject_entities` | 新增；把品牌/竞品主体从 JSON 投影为可约束关系 |
| `content_evidence_pack_jobs` | Phase 1 新增 durable builder job |
| `content_evidence_packs` | 新增 |
| `content_evidence_pack_items` | 新增 |
| `content_prompt_bundles` | 新增 |
| `content_draft_versions` | 新增 |
| `content_claims` | 新增 |
| `content_claim_evidence` | 新增 |
| `content_evaluation_jobs` | Phase 1 新增；精确 Asset Version/hash 的 durable QA job |
| `content_evaluations` | 新增 |
| `content_export_events` | 优先复用 `audit_events`；Phase 1 仅在查询量证明需要时增加结构化投影 |
| `content_skill_versions` | Phase 3 新增 |
| `content_skill_compile_jobs` | Phase 3 新增 durable compiler job；产出 immutable Template Release |
| `content_delivery_jobs` | Phase 2 新增 durable artifact job |
| `content_delivery_packages` | Phase 2 新增 |
| `content_publications` | Phase 4 新增 |
| `content_feedback_signals` | Phase 4 新增 |
| `content_experiments` | Phase 4/5 新增 |

### 17.2 项目隔离

所有项目拥有的数据 MUST 包含：

```sql
project_id uuid NOT NULL REFERENCES projects(id)
```

并使用现有：

```text
geo_runtime_can_access_project(project_id)
```

作为 RLS 锚点。

全局关系不变量：

> **项目拥有对象之间的引用，必须通过包含 `project_id` 的数据库复合外键保证双方属于同一 project；RLS 只负责访问隔离，不能代替关系完整性。**

统一模式：

```sql
UNIQUE (project_id, id);

FOREIGN KEY (project_id, parent_id)
REFERENCES parent_table(project_id, id);
```

至少覆盖 Brief -> typed Opportunity/Action/Report/Retest、Evidence Pack -> Brief Version、Evidence Item -> Fact/Chunk/Citation/Report/Source、Prompt Bundle -> Brief/Pack/Template Release、Draft Version -> Brief/Pack/Bundle、Claim -> Draft Version、Review -> Draft Version/hash、Delivery/Publication Request -> Draft Version/hash。

重点链路还必须约束“属于同一编译链”，不只约束同 project：

```sql
-- Pack 必须属于该 Brief Version
UNIQUE (project_id, id, brief_version_id);

-- Prompt Bundle 声明的 Pack 与 Brief 必须互相匹配
FOREIGN KEY (project_id, evidence_pack_id, brief_version_id)
REFERENCES content_evidence_packs(project_id, id, brief_version_id);

-- Draft Version 引用同一 Brief/Pack/Bundle 组合
FOREIGN KEY (project_id, prompt_bundle_id, brief_version_id, evidence_pack_id)
REFERENCES content_prompt_bundles(project_id, id, brief_version_id, evidence_pack_id);

-- Review/Delivery/Publication 同时锁定精确内容 hash
FOREIGN KEY (project_id, content_draft_version_id, target_content_hash)
REFERENCES content_draft_versions(project_id, id, content_hash);
```

Brief head/version 循环关系采用预生成 UUID、同事务两阶段写入和可延迟 FK：

```sql
-- 1. insert head with current_version_id NULL
-- 2. insert version -> head
-- 3. update head.current_version_id

FOREIGN KEY (project_id, brief_id)
REFERENCES content_briefs(project_id, id)
DEFERRABLE INITIALLY DEFERRED;

FOREIGN KEY (project_id, id, current_version_id)
REFERENCES content_brief_versions(project_id, brief_id, id)
DEFERRABLE INITIALLY DEFERRED;
```

迁移窗口允许 `current_version_id NULL`，回填/校验后对正式 head 收紧；deferred FK 使用 `NO ACTION`。Opportunity 来源、Evidence Source、品牌/竞品主体属于多态关系，物理层必须使用 typed nullable FK + `num_nonnulls(...)` CHECK，不能用无法建立 FK 的泛化 `source_type/source_id` 充当强关系。Brief 的 JSON payload 是快照，`content_brief_subject_entities` 等关系表才是同项目完整性的约束投影，两者 hash 必须在写入事务中一致。

所有 FK 引用侧必须显式建索引，PostgreSQL 不会自动创建；RLS 列和常用 `project_id + status + updated_at` 查询使用匹配访问路径的组合/partial index。所有新表启用并 `FORCE ROW LEVEL SECURITY`，同时配置 `USING` 和 `WITH CHECK`。新增历史 FK 可先 `NOT VALID`、清理后 `VALIDATE CONSTRAINT`；父侧先建立精确 UNIQUE。幂等迁移不得使用 PostgreSQL 不支持的 `ADD CONSTRAINT IF NOT EXISTS`，应通过命名 constraint + catalog/DO block 检查。

不要求每表冗余 `tenant_id`。如果为了跨项目分析确实冗余 tenant，必须有数据库约束或触发器保证与 projects 一致。

当前已有 project-scoped `brand_entities`，首期新数据使用 `brand_entity_id` 外键；只有 legacy row 可暂时回退到 `projects.target_brand`。仓库没有跨项目/tenant 的 brand aggregate，一项目多品牌和跨项目品牌复用仍需独立 ADR。

共享 Skill 使用：

```text
scope_type = system | tenant | project
scope_id
```

system Skill 只读；tenant/project Skill 走对应 manage policy。

### 17.3 关键 Schema 约束

`content_briefs`：

```text
project_id NOT NULL
current_version_id
revision integer NOT NULL
lifecycle_status CHECK (...)
source_action_recommendation_id/source_report_export_id/source_retest_comparison_id/source_gap_projection_id nullable typed FKs
source_kind CHECK (...); CHECK manual OR num_nonnulls(typed source FKs)=1
UNIQUE(project_id, id)
deferred FK(project_id, id, current_version_id) -> content_brief_versions(project_id, brief_id, id)
```

`source_gap_projection_id` 只有在实际持久表和 composite FK 存在后才能启用；此前 Source Gap 内容机会必须锚定到 ActionRecommendation 或真实 citation graph/source gap owning object。

`content_brief_versions`：

```text
brief_id NOT NULL
project_id NOT NULL
version integer NOT NULL CHECK(version > 0)
payload jsonb NOT NULL
payload_hash text NOT NULL
selected_evidence_pack_id uuid NULL
workflow_status CHECK (draft, validating, validated, evidence_building, needs_evidence, blocked, ready, locked, superseded, cancelled)
UNIQUE(project_id, brief_id, version)
UNIQUE(project_id, brief_id, id)
FK(project_id, brief_id) -> content_briefs(project_id, id)
FK(project_id, selected_evidence_pack_id, id) -> content_evidence_packs(project_id, id, brief_version_id)
immutable payload/payload_hash after insert; guarded workflow_status transitions only
```

`content_brief_subject_entities`：

```text
project_id NOT NULL
brief_version_id NOT NULL
subject_role = primary_brand | competitor | product | market | neutral
brand_entity_id uuid NULL
competitor_entity_id uuid NULL
CHECK ((role IN (market,neutral) AND num_nonnulls(...)=0) OR (role NOT IN (market,neutral) AND num_nonnulls(...)=1))
subject_key text NOT NULL  -- typed entity id or canonical market/neutral key
composite FK to Brief Version and typed entity table
UNIQUE(project_id, brief_version_id, subject_role, subject_key)
```

`content_evidence_pack_jobs/content_evidence_packs`：

```text
job: project_id, brief_version_id, requested_attempt_number, status, lease/retry/DLQ fields
pack: project_id, brief_version_id, attempt_number, previous_pack_id
pack: build_result = ready | needs_evidence | blocked
pack: builder_policy_version, snapshot_hash, sealed_at, stale_at, superseded_at
UNIQUE(project_id, brief_version_id, attempt_number)
UNIQUE(project_id, brief_version_id, requested_attempt_number) on jobs
UNIQUE(project_id, id, brief_version_id)
partial UNIQUE(project_id, brief_version_id) WHERE build_result='ready' AND stale_at IS NULL AND superseded_at IS NULL
partial UNIQUE(project_id, brief_version_id) on jobs WHERE status IN ('queued','running','retry_wait','finalizing')
composite FK pack/job -> exact Brief Version
```

创建 builder Job 时必须锁定 exact Brief Version 行（或获取以 `project_id + brief_version_id` 为 key 的 transaction-scoped advisory lock），在同一事务按 `max(requested_attempt_number)+1` 分配编号并插入 Job；partial unique 是并发兜底。不能锁一个尚不存在的 Pack 行来分配 attempt。

Evidence dead-letter `/replay` 同样在该锁下创建新 Job、原子分配新的 `requested_attempt_number`，保存 `parent_job_id` 并令 `replay_nonce+1`；它不复用旧 attempt 编号。编号允许因 cancelled/dead-letter Job 产生空洞，审计按 Job lineage 解释，`UNIQUE(project_id, brief_version_id, requested_attempt_number)` 保持有效。

技术 Job 的 `running/retry_wait/finalizing/failed` 不得写进 Pack build result。Finalization 在一个事务中插入 Pack、Items、诊断和 hash；sealed Pack/Items 的 UPDATE/DELETE 必须由数据库 trigger 拒绝，service guard 和行为测试只是附加保护，不能替代数据库不可变性。

若 finalization 产生新的 `ready` Attempt，同事务将旧 current ready 标为 superseded，并更新 Brief Version 的 `selected_evidence_pack_id`；失败 Attempt 不覆盖已有 selected ready Pack。普通 FK 无法验证 Pack 的 `build_result/stale_at/superseded_at`，因此 MUST 使用 `DEFERRABLE INITIALLY DEFERRED` constraint trigger 在提交时保证 selected Pack 属于同 project/Brief Version，且 `build_result='ready' AND stale_at IS NULL AND superseded_at IS NULL`。

`content_evidence_pack_items`：

```text
project_id NOT NULL
evidence_pack_id NOT NULL
item_type CHECK (...)
approved_fact_id/chunk_id/citation_id/report_export_id/action_recommendation_id/retest_comparison_id/source_asset_id typed nullable columns
CHECK num_nonnulls(typed source columns) = 1
source_revision_kind NOT NULL
source_revision_value NOT NULL CHECK (btrim(source_revision_value) <> '')
locator jsonb NOT NULL
locator_hash NOT NULL
CHECK num_nonnulls(snapshot_text, snapshot_object_uri) = 1
CHECK snapshot_text IS NULL OR btrim(snapshot_text) <> ''
CHECK snapshot_object_uri IS NULL OR btrim(snapshot_object_uri) <> ''
preview_text NULL  -- 派生预览，不参与 item_fingerprint/snapshot 身份
snapshot_hash NOT NULL
subject_role NOT NULL
typed subject entity columns + CHECK
public_disclosure_allowed/public_source_url/public_source_title/citation_label
quotation_allowed/attribution_required
item_fingerprint NOT NULL
UNIQUE(project_id, evidence_pack_id, item_fingerprint)
UNIQUE(project_id, evidence_pack_id, id)
composite FK to Pack and each typed source
```

`item_fingerprint = hash(item_type + typed_source_id + source_revision + canonical_locator + snapshot_hash)`。它允许同一报告版本保存多个不同 locator 的合法节选，同时阻止 NULL unique 语义造成重复。旧 citation 表若缺 `project_id`，必须先从所属 AnswerRun 回填并建立 `(project_id,id)` 唯一约束。

`content_prompt_bundles`：

```text
project_id/brief_version_id/evidence_pack_id/generation_template_release_id NOT NULL
model_policy_version/compiler_version/output_schema_version NOT NULL
full_snapshot_uri/full_snapshot_hash/size/content_type NOT NULL
UNIQUE(project_id, id, brief_version_id, evidence_pack_id)
composite FK to matching Brief Version, selected ready Pack and Template Release
immutable after insert
```

Prompt Compiler 必须锁定 Brief Version 与其 selected Pack，在插入 Bundle 时用 deferred constraint trigger 校验 Pack 正是该 Brief 当前 `selected_evidence_pack_id`，且仍为 ready/non-stale/non-superseded；普通 FK 只证明“属于同一 Brief”，不足以表达该条件。Bundle 插入后保留历史身份，即使 Pack 日后 stale 也不修改 Bundle。

`content_generation_jobs` 对 `(project_id, prompt_bundle_id, brief_version_id, evidence_pack_id)` 建复合 FK 指向 Bundle 声明的完整编译链。API 创建 Job 和 worker freeze input 前都必须重新检查 Pack 仍是 selected ready、Bundle hash 未变；不满足时在任何模型调用前 fail closed。运行期间失效则通过 cancel/stale propagation 阻止结果成为可审核 Version。

`content_claims/content_claim_evidence`：

```text
claim: project_id, content_draft_version_id, target_content_hash, evidence_pack_id, text, offsets, claim_type, risk_level
claim: subject_role + typed subject entity columns
claim: extractor_key/version, inventory_hash
mapping: project_id NOT NULL
claim_id NOT NULL
evidence_pack_id NOT NULL
evidence_pack_item_id NOT NULL
support_type IN (supports, partially_supports, conflicts, context_only)
UNIQUE(project_id, claim_id, evidence_pack_item_id)
UNIQUE(project_id, claim_id, evidence_pack_id) on claims
composite FK claim(project_id, version_id, hash, evidence_pack_id) -> exact Draft Version/hash/Pack
composite FK mapping(project_id, claim_id, evidence_pack_id) -> Claim
composite FK mapping(project_id, evidence_pack_id, evidence_pack_item_id) -> Evidence Item
```

这两组 mapping FK 保证 Item 不仅属于同 project，而且属于该 Draft Version 冻结的同一个 Evidence Pack，不能用同项目另一个 Pack 的证据支持 Claim。Action/Report/Retest 默认只可作为 `context_only`；只有其内容能继续追到合格 Fact/Chunk/公开来源时，才可成为 `supports`。Claim 还必须保存 subject role/typed entity，使 Claim 与 Evidence 主体一致性可以确定性检查。

`content_drafts` aggregate head：

```text
project_id NOT NULL
current_version_id uuid NULL during migration
current_status compatibility projection
UNIQUE(project_id, id)
deferred FK(project_id, id, current_version_id) -> content_draft_versions(project_id, content_draft_id, id)
```

`content_draft_versions`：

```text
project_id NOT NULL
content_draft_id NOT NULL
version integer NOT NULL
base_version_id uuid NULL
content_hash NOT NULL
brief_version_id/evidence_pack_id/prompt_bundle_id NOT NULL
edited_by/edited_at/edit_reason
submitted_for_review_by/submitted_for_review_at
workflow_status CHECK (generated, qa_running, pending_human_review, needs_revision, blocked, approved, rejected, archived, superseded)
UNIQUE(project_id, content_draft_id, version)
UNIQUE(project_id, content_draft_id, id)
UNIQUE(project_id, id, content_hash)
UNIQUE(project_id, id, content_hash, evidence_pack_id)
composite FK to Asset head, base Version and exact Brief/Pack/Prompt compilation chain
immutable content/content_hash after insert; guarded workflow_status transitions only
```

`content_evaluation_jobs/content_evaluations`：

```text
job: project_id/content_draft_version_id/target_content_hash/evaluation_policy_version NOT NULL
job: status/lease/retry/DLQ/finalizing/idempotency/budget/progress/error fields
evaluation: project_id/content_draft_version_id/target_content_hash/job_id/evaluator_key/version/result_hash
composite FK job/evaluation -> exact Draft Version/hash
partial UNIQUE(project_id, content_draft_version_id, target_content_hash, evaluation_policy_version)
  WHERE status IN ('queued','running','retry_wait','finalizing')
UNIQUE(project_id, job_id, evaluator_key, evaluator_version)
```

Evaluation Job `succeeded` 表示 Claim extraction/QA 结果已完整持久化，不表示 Asset 通过 Gate；硬门禁失败由 exact Asset Version 转为 `needs_revision/blocked` 表达。正文编辑事务通过 outbox 创建 Evaluation Job，worker 不能把评测写到非 current hash。

`human_review_records` 增量字段：

```text
content_draft_version_id uuid NULL
target_content_hash text NULL
review_kind = claim_inventory | subject_matter | compliance | internal_approval | customer_acceptance
policy_version text
required_role text
claim_inventory_complete boolean NULL
claim_inventory_hash text NULL
claim_inventory_reviewed_at timestamptz NULL
invalidated_at timestamptz NULL
invalidation_reason text NULL
supersedes_review_id uuid NULL
```

对 Content review：

- Phase 0 先强制 `target_content_hash`，以 `content_draft_id + target_content_hash` 锁定审核目标；
- Phase 1 回填 legacy draft 为 `version=1` 后，`content_draft_version_id` 和 `target_content_hash` 对所有新审核必填；
- `claim_inventory` review 必须同时保存 completeness、inventory hash、extractor key/version 和 reviewer；
- 新 Asset Version 不继承旧版本批准；
- customer delivery/publication eligibility 只读取 exact current version/hash 的有效 review；
- reviewer 修改决定时，在同一事务中 invalidate 旧记录并写新记录；
- Phase 0 对 `(project_id, target_id, target_content_hash, review_kind, reviewer_id)` 建立仅覆盖 `invalidated_at IS NULL` 的 partial unique index；
- 对 `(project_id, content_draft_version_id, review_kind, reviewer_id)` 建立仅覆盖 `invalidated_at IS NULL` 的 partial unique index。

`manual_distribution_records` 增量字段：

```text
content_draft_version_id uuid NULL  -- 仅 Phase 1 backfill 窗口允许 NULL
delivery_package_id uuid NULL
publication_request_id uuid NULL  -- Phase 4 引入 aggregate 后回填
publication_snapshot_hash text NOT NULL
publication_channel text NOT NULL
destination_account_id text NULL
destination_key text NOT NULL
publication_attempt integer NOT NULL CHECK (publication_attempt > 0)
request_idempotency_scope_hash text
request_idempotency_key_hash text
request_payload_hash text
requested_by/requested_at/request_reason
target_url text NULL
status CHECK (awaiting_url_backfill, url_backfilled, published, verified, blocked)
```

唯一创建时点是用户对已批准精确版本执行显式 `publication request` 且 `publication_eligible=true` 的事务。Export、Delivery、Approve 都不得隐式创建。Phase 0 以 `content_draft_id + publication_snapshot_hash` 锁定内容；Phase 1 回填 `version=1` 后改为精确 Version/hash 复合 FK。

迁移先把 legacy 空字符串 URL 规范为 NULL，再增加约束：`awaiting_url_backfill` 必须 `target_url IS NULL`，`url_backfilled/published/verified` 必须有非空 URL。业务唯一键允许多账号、多地区和多次发布：

```text
UNIQUE(project_id, content_draft_version_id, publication_channel, destination_key, publication_attempt)
```

Phase 0 在 version FK 回填前使用 `(project_id, content_draft_id, publication_snapshot_hash, publication_channel, destination_key, publication_attempt)`。重复点击使用带 actor/route scope 的 idempotency key hash partial unique 防重，而不是通过 `(version, platform)` 禁止合法多次发布。`publication_attempt` 必须在锁定现存 Draft Version 行或获取 `(project, version, channel, destination)` transaction-scoped advisory lock 后，按 `max(attempt)+1` 原子分配；锁“不存在的下一条 distribution row”不能防止并发重复编号。

`content_delivery_jobs/content_delivery_packages`：

```text
project_id/content_draft_version_id/target_content_hash NOT NULL
package_kind = internal | customer
job status/lease/retry/DLQ/finalizing/scoped-idempotency fields
package artifact_uri/hash/size/content_type/manifest_hash
composite FK(project_id, version_id, target_content_hash) -> exact Draft Version/hash
UNIQUE(project_id, request_idempotency_scope_hash, request_idempotency_key_hash)
  WHERE request_idempotency_key_hash IS NOT NULL
```

Customer package 必须由独立 allowlist builder 产生，不能对 internal zip 做删除字段式转换。

`content_skill_compile_jobs`：

```text
scope_type/scope_key/skill_version_id/source_hash/compiler_version NOT NULL
scope_id/project_id uuid NULL; CHECK system scope => scope_id/project_id NULL;
CHECK tenant scope => scope_id NOT NULL/project_id NULL; project scope => project_id=scope_id
status/lease/retry/DLQ/finalizing/scoped-idempotency/progress/error fields
result_template_release_id/result_release_hash NULL until succeeded
composite FK to exact Skill Version/source hash and resulting Template Release/release hash
partial UNIQUE(scope_key, skill_version_id, source_hash, compiler_version)
  WHERE status IN ('queued','running','retry_wait','finalizing')
```

Compile Job `succeeded` 只表示不可变 Template Release 已持久化；`release` 是另一个需要 capability/reason 的显式命令。dead-letter replay 创建带 parent/replay nonce 的新 Job，不能覆盖旧 Release。

`scope_key` 是非空规范键（`system`、`tenant:{id}`、`project:{id}`），同时保留 typed scope 列/FK；它用于解决 NULL unique 语义，不能替代 scope 完整性和相应 RLS/管理策略。

所有列表路径必须有 `project_id + status + updated_at` 索引；queue 使用与 claim predicate 匹配的 partial index（例如 queued/retry_wait 的 `next_run_at, priority, created_at`）并配合 `FOR UPDATE SKIP LOCKED`。

### 17.4 Trace 类型

扩展 `knowledge_trace_refs`：

```text
action_plan/report/retest
  -> content_brief
content_brief
  -> evidence_pack
approved_fact/chunk/source_asset
  -> evidence_pack
evidence_pack
  -> prompt_bundle
prompt_bundle
  -> content_generation_job
content_generation_job
  -> content_draft_version
content_draft
  -> content_draft_version
content_draft_version
  -> content_evaluation
content_draft_version
  -> export_event/content_delivery_package/publication_request
publication_request
  -> manual_distribution/content_publication
publication
  -> retest
```

Claim 级 evidence 使用专表，对象级 lineage 继续使用 trace refs。所有 Evaluation、Review、Variant、Delivery、Publication、Feedback 和 Retest link 必须引用不可变 `content_draft_version_id + content_hash`，不能只引用会移动的 `content_draft` aggregate。

### 17.5 MinIO 对象路径

```text
content-prompts/{project_id}/{brief_version_id}/{prompt_bundle_id}/
  prompt-bundle-{full_snapshot_hash}.json

content-evidence/{project_id}/{brief_version_id}/{evidence_pack_id}/
  item-{item_id}-{snapshot_hash}.{ext}

content-artifacts/{project_id}/{content_draft_id}/{version}/
  canonical-{hash}.json
  article-{hash}.md
  article-{hash}.html
  scorecard-{hash}.json
  manifest-{hash}.json

content-deliveries/{project_id}/{delivery_package_id}/
  internal-{hash}.zip
  customer-{hash}.zip
```

Prompt Bundle 在 Draft 之前创建，必须使用 Brief Version/Bundle ID 路径。生成后的 Draft manifest 引用 Bundle ID、URI 和 hash；禁止为了获得对象路径预创建空 Draft aggregate。对象必须 content-addressed、不可覆盖、上传时校验 hash。下载不得直接暴露永久 S3 URI。

### 17.6 Qdrant

MVP 继续使用现有 knowledge chunk collection 和强制 payload filter：

```text
project_id
status=active
embedding_status=embedded
embedding_model/version
```

Approved facts 保持 PostgreSQL 真源。只有经过基准证明索引参数或数据生命周期明显不同，才拆 collection。

未审核 Draft、QA failed 内容和模型推断永远不得进入 Evidence 检索空间。

---

## 18. Repository 与代码结构

### 18.1 原则

现有主 repository 和 FastAPI main 已过大。新内容能力不得继续直接堆入：

```text
packages/geo_core/geo_core/repository.py
apps/api/geo_api/main.py
workers/knowledge_worker/run_knowledge_pipeline.py
```

### 18.2 建议结构

```text
packages/geo_core/geo_core/content_generation/
  domain/
    opportunity.py
    brief.py
    evidence_pack.py
    asset.py
    claim.py
    evaluation.py
  application/
    opportunity_service.py
    brief_service.py
    evidence_service.py
    generation_service.py
    review_service.py
    delivery_service.py
  compiler/
    skill_resolver.py
    prompt_compiler.py
    model_policy.py
  evaluation/
    deterministic.py
    claims.py
    factuality.py
    scorecard.py
  ports/
    repositories.py
    model_gateway.py
    object_store.py
  events.py

packages/geo_core/geo_core/repositories/
  content_repository.py
  content_postgres_repository.py

apps/api/geo_api/routes/
  content_opportunities.py
  content_briefs.py
  content_evidence.py
  content_assets.py
  content_reviews.py
  content_delivery.py
  content_publication.py

workers/content_worker/
  handlers.py
  run_content_jobs.py
```

### 18.3 同步边界

当前 repository、FastAPI handlers 和 worker 主要使用同步 DB-API。首期 repository Protocol 和 Unit of Work 应保持同步上下文：

```python
class ContentUnitOfWork(Protocol):
    opportunities: ContentOpportunityRepository
    briefs: ContentBriefRepository
    evidence: EvidencePackRepository
    assets: ContentAssetRepository

    def __enter__(self) -> "ContentUnitOfWork": ...
    def __exit__(self, exc_type, exc, tb) -> None: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
```

不要只为了新模块引入局部 async repository，造成两套事务模型。

### 18.4 兼容 façade

现有 `PostgresEvidenceRepository` 和 legacy endpoints 在兼容期调用新的 Content service/repository。新领域代码不能反向依赖巨型 repository。

---

## 19. API 合同

### 19.1 路由原则

- 使用现有 `/v1` 前缀；
- 新 router 不继续写进 `main.py`；
- actor、project access 和 allowed roles 使用现有统一依赖；
- mutation 必须有 reason；
- 异步操作返回 `202 Accepted`；
- 支持 `Idempotency-Key`；
- 版本编辑支持 `If-Match`；
- 所有 Review/Variant/Delivery/Publication mutation 必须携带 immutable `content_draft_version_id + content_hash`；
- 错误返回稳定 code 和 detail；
- 单资源/列表 item 返回 capabilities、available_actions 和 blocked_reasons，前端不重算状态机；
- 列表统一 limit/offset/filter/sort；
- 下载使用授权代理或短期 signed URL。

### 19.2 Canonical routes

```http
GET  /v1/content/bootstrap/runtime
GET  /v1/content/data-readiness/runtime/summary
GET  /v1/content/data-readiness/runtime/items
PATCH /v1/content/data-readiness/runtime/items/{item_ref}

GET  /v1/content/opportunities/runtime
GET  /v1/content/opportunities/runtime/{opportunity_ref}
POST /v1/content/opportunities/runtime/{opportunity_ref}/accept
POST /v1/content/opportunities/runtime/{opportunity_ref}/dismiss
POST /v1/content/opportunities/runtime/{opportunity_ref}/block
POST /v1/content/opportunities/runtime/{opportunity_ref}/reopen
POST /v1/content/opportunities/runtime/{opportunity_ref}/terminate
POST /v1/content/opportunities/runtime/{opportunity_ref}/convert

GET  /v1/content/briefs/runtime
POST /v1/content/briefs/runtime
GET  /v1/content/briefs/runtime/{id}
GET  /v1/content/briefs/runtime/{id}/versions
GET  /v1/content/briefs/runtime/{id}/versions/{version_id}
PATCH /v1/content/briefs/runtime/{id}
POST /v1/content/briefs/runtime/{id}/versions/{version_id}/validate
POST /v1/content/briefs/runtime/{id}/versions/{version_id}/evidence-packs
GET  /v1/content/evidence-packs/runtime/{id}
GET  /v1/content/evidence-packs/runtime/{id}/items
GET  /v1/content/evidence-pack-jobs/runtime
GET  /v1/content/evidence-pack-jobs/runtime/{id}
POST /v1/content/evidence-pack-jobs/runtime/{id}/cancel
POST /v1/content/evidence-pack-jobs/runtime/{id}/retry
POST /v1/content/evidence-pack-jobs/runtime/{id}/replay

POST /v1/content/generation-jobs/runtime
GET  /v1/content/generation-jobs/runtime
GET  /v1/content/generation-jobs/runtime/{id}
POST /v1/content/generation-jobs/runtime/{id}/cancel
POST /v1/content/generation-jobs/runtime/{id}/retry
POST /v1/content/generation-jobs/runtime/{id}/regenerate
POST /v1/content/generation-jobs/runtime/{id}/replay

GET  /v1/content/assets/runtime
GET  /v1/content/assets/runtime/{id}
GET  /v1/content/assets/runtime/{id}/versions
GET  /v1/content/assets/runtime/{id}/versions/{version_id}
POST /v1/content/assets/runtime/{id}/versions
POST /v1/content/assets/runtime/{id}/versions/{version_id}/variants
POST /v1/content/assets/runtime/{id}/versions/{version_id}/submit-review

GET  /v1/content/reviews/runtime/queue
GET  /v1/content/assets/runtime/{id}/versions/{version_id}/claims
GET  /v1/content/assets/runtime/{id}/versions/{version_id}/reviews
POST /v1/content/assets/runtime/{id}/versions/{version_id}/reviews

GET  /v1/content/assets/runtime/{id}/versions/{version_id}/evaluations
GET  /v1/content/evaluation-jobs/runtime
GET  /v1/content/evaluation-jobs/runtime/{id}
POST /v1/content/evaluation-jobs/runtime/{id}/cancel
POST /v1/content/evaluation-jobs/runtime/{id}/retry
POST /v1/content/evaluation-jobs/runtime/{id}/replay
GET  /v1/content/assets/runtime/{id}/versions/{version_id}/exports
POST /v1/content/assets/runtime/{id}/versions/{version_id}/exports
GET  /v1/content/export-events/runtime/{id}/artifact
GET  /v1/content/assets/runtime/{id}/versions/{version_id}/delivery-packages
POST /v1/content/assets/runtime/{id}/versions/{version_id}/delivery-packages
GET  /v1/content/delivery-jobs/runtime
GET  /v1/content/delivery-jobs/runtime/{id}
POST /v1/content/delivery-jobs/runtime/{id}/cancel
POST /v1/content/delivery-jobs/runtime/{id}/retry
POST /v1/content/delivery-jobs/runtime/{id}/replay
GET  /v1/content/delivery-packages/runtime
GET  /v1/content/delivery-packages/runtime/{id}/artifact

GET  /v1/content/assets/runtime/{id}/versions/{version_id}/publication-requests
POST /v1/content/assets/runtime/{id}/versions/{version_id}/publication-requests
GET  /v1/content/manual-distributions/runtime
GET  /v1/content/manual-distributions/runtime/{id}
POST /v1/content/manual-distributions/runtime/{id}/url
POST /v1/content/manual-distributions/runtime/{id}/confirm-published
POST /v1/content/manual-distributions/runtime/{id}/verify
POST /v1/content/manual-distributions/runtime/{id}/block

GET  /v1/content/skills/runtime
POST /v1/content/skills/runtime
GET  /v1/content/skills/runtime/{id}
GET  /v1/content/skills/runtime/{id}/versions
GET  /v1/content/skills/runtime/{id}/versions/{version_id}
POST /v1/content/skills/runtime/{id}/versions
POST /v1/content/skills/runtime/{id}/versions/{version_id}/compile
POST /v1/content/skills/runtime/{id}/versions/{version_id}/release
POST /v1/content/skills/runtime/{id}/versions/{version_id}/rollback
GET  /v1/content/template-releases/runtime/{id}
GET  /v1/content/skill-compile-jobs/runtime
GET  /v1/content/skill-compile-jobs/runtime/{id}
POST /v1/content/skill-compile-jobs/runtime/{id}/cancel
POST /v1/content/skill-compile-jobs/runtime/{id}/retry
POST /v1/content/skill-compile-jobs/runtime/{id}/replay

GET  /v1/customer/content-deliverables/runtime
GET  /v1/customer/content-deliverables/runtime/{id}
GET  /v1/customer/content-deliverables/runtime/{id}/artifact
POST /v1/customer/content-deliverables/runtime/{id}/comments
POST /v1/customer/content-deliverables/runtime/{id}/request-changes
POST /v1/customer/content-deliverables/runtime/{id}/accept
```

`opportunity_ref` 是 `type:uuid` 不透明引用；服务端按 allowlist 解析并校验项目。当前没有独立 Source Gap 表时，不能返回虚构 `source_gap:{uuid}`，必须引用真实持久对象（例如 citation graph/source-gap projection ID）或使用 ActionRecommendation ref。

Phase 0/0.5、Phase 1/2、Phase 3 route 必须分别受 bootstrap flag 和后端 capability 保护；未启用能力返回稳定 `404 feature_not_enabled` 或从 bootstrap 中省略 action，不能只隐藏前端按钮。Data Readiness item 使用 `item_ref=source_asset:{uuid}|approved_fact:{uuid}`，PATCH 必须携带 governance payload、reason 和 `If-Match`。

Asset Version 创建同步插入新版本和 Evaluation Job outbox，返回 `201 Created + head_etag + version_etag + content_hash + evaluation_job_id/status_url`。Evidence、Generation、Evaluation、Delivery 和异步 Skill compile 返回 `202 + Location + Retry-After`。轻量内部 Export 同步生成或复用 content-addressed artifact，返回 `200/201 ContentExportResponse`；大体积 zip/客户包统一走 Delivery Job，不再发明无查询合同的 Export Job。

ETag 必须区分两个锁对象：

- `head_etag/head_revision`：保护 aggregate 当前指针；`PATCH Brief`、创建 Brief/Asset 新 Version 必须使用它；
- `version_etag`：保护 exact Version 的 workflow/review 投影；validate、submit-review 等 exact-version transition 使用它；
- `payload_hash/content_hash`：不可变业务内容身份，不等同于 ETag。

单资源 GET 返回相应 ETag header，并在 DTO 中显式返回上述字段。创建新版本同时校验 `If-Match: head_etag`、`base_version_id` 和 base hash；精确版本 mutation 校验 `If-Match: version_etag` 与 body hash。错误语义：跨项目或不可见 `404`，非法状态/非 current base `409`，ETag/hash 冲突 `412`，关系/payload `422`，预算或速率耗尽 `429`。

统一错误 envelope：

```json
{
  "code": "base_version_not_current",
  "detail": "The asset has a newer version.",
  "field_errors": {},
  "blocked_reasons": [],
  "correlation_id": "uuid",
  "retry_after_seconds": null,
  "current_version": {
    "id": "uuid",
    "content_hash": "sha256...",
    "head_etag": "...",
    "version_etag": "..."
  }
}
```

`POST .../publication-requests` 必须携带 exact version/hash、`publication_channel/destination_account_id/destination_key/reason` 和 Idempotency-Key。Phase 0 由兼容 service 显式创建 `awaiting_url_backfill` manual distribution；Phase 4 改为创建 Publication aggregate。Export、Delivery、Approve handler 不得调用该 service。

Manual Distribution 命令严格对应状态转换：`/url` 回填 URL 并进入 `url_backfilled`；`/confirm-published` 确认人工发布完成并进入 `published`；`/verify` 只验证已经 published 的 URL/proof 并进入 `verified`；`/block` 保存 reason/owner 并进入 `blocked`。所有命令携带 reason、exact target hash 和 `If-Match`，不得由 `/verify` 隐式跳过 published。

`submit-review` 只负责将 QA 已完成的 exact Version/hash 提交到 `pending_human_review` 并记录 `submitted_for_review_by`；`reviews` endpoint 只写 reviewer decision，二者不得合并。内部 approver 必须与 submitter 不同。

### 19.3 异步 Job 响应

```json
{
  "job_id": "uuid",
  "job_type": "generation",
  "status": "queued",
  "terminal": false,
  "progress": {
    "stage": "queued",
    "current": 0,
    "total": 5
  },
  "attempt_count": 0,
  "max_attempts": 3,
  "lease_expires_at": null,
  "next_run_at": null,
  "request_idempotency_key_hash": "sha256...",
  "parent_job_id": null,
  "regeneration_nonce": 0,
  "replay_nonce": 0,
  "error": null,
  "result_refs": {},
  "available_actions": ["cancel"],
  "status_url": "/v1/content/generation-jobs/runtime/uuid",
  "dispatch": {
    "status": "queued",
    "message_id": "..."
  }
}
```

响应头：

```text
HTTP 202
Location: /v1/content/generation-jobs/runtime/{id}
Retry-After: 2
```

`ContentJobResponse` 是 Evidence/Generation/Evaluation/Delivery/Skill Compile 共用的可判别 envelope。稳定枚举为：

```text
ContentJobStatus = queued | running | retry_wait | finalizing |
                   succeeded | failed | dead_letter | cancelled
ContentJobType = evidence_pack_build | generation | evaluation |
                 delivery_package_build | skill_compile
```

`terminal=true` 仅适用于 `succeeded/failed/dead_letter/cancelled`。`error` 至少包含稳定 `code/detail/retryable/correlation_id`；`result_refs` 按 job type 返回 `evidence_pack_id/asset_version_id/evaluation_ids/delivery_package_id/template_release_id`，未产生结果时为空。`available_actions` 由服务端计算：active Job 可 cancel，`retry_wait` 可 retry，`dead_letter` 可 replay；terminal `failed` 不能原地 retry，Generation 可 regenerate，其他 Job 通过原始创建命令建立新 attempt。前端不得通过 HTTP 请求超时、progress 停顿或 Asset gate 失败推断 Job failed。

Evidence 构建在 Pack 尚不存在时返回 pending union，而不是伪造 `evidence_pack_id`：

```text
PendingEvidenceAttempt = job_id + brief_version_id + requested_attempt_number
FinalizedEvidenceAttempt = evidence_pack_id + attempt_number + build_result + snapshot_hash
```

进入 `finalizing` 后进度 stage 必须明确为 artifact finalization；恢复器只恢复制品，不重做外部模型调用。

### 19.4 OpenAPI Schema 与 Bootstrap 合同

FastAPI/Pydantic schema 名称必须稳定，OpenAPI snapshot 和生成的 TypeScript 类型是 Admin/Customer 联调真源。至少定义以下枚举，禁止在页面层退化成裸 `string`：

```text
ContentJobStatus / ContentJobType / ResourceAction / ContentCapability / ContentErrorCode
LegacyContentDraftStatus
BriefWorkflowStatus / EvidencePackBuildResult / AssetWorkflowStatus
DeliveryPackageStatus / ManualDistributionStatus / PublicationChannel
SubjectRole / EvidenceItemType / ReviewKind / ReviewDecision
InvitationSurface / InvitationSurfaceCompatibility / InvitationRedeemRecoveryStatus
RuntimeSessionScopeVersion
```

至少定义并在 OpenAPI 暴露以下 DTO：

```text
ContentBootstrapResponse / ContentPageMeta / ContentJobResponse
LegacyContentV0JobResponse / LegacyContentV0DraftResponse
LegacyInlineClaimInventoryReviewRequest / LegacyPublicationRequestCreateRequest
DataReadinessSummaryResponse / DataReadinessItemResponse / DataReadinessPatchRequest
OpportunityListItem / OpportunityDetailResponse / OpportunityCommandRequest
BriefCreateRequest / BriefPatchRequest / BriefDetailResponse / BriefVersionResponse
BriefValidateRequest / BriefValidationResponse
EvidencePackBuildRequest / EvidencePackJobResponse / EvidencePackResponse
EvidencePackItemResponse（discriminator=item_type）
GenerationJobCreateRequest / AssetVersionCreateRequest / AssetVersionResponse
ClaimResponse / EvaluationResponse / ReviewSubmitRequest / ReviewDecisionRequest
ContentExportRequest / ContentExportResponse
DeliveryPackageCreateRequest / DeliveryJobResponse / DeliveryPackageResponse
PublicationRequestCreateRequest / PublicationRequestResponse
ManualDistributionResponse / ManualDistributionCommandRequest
CustomerDeliverableListItem / CustomerDeliverableDetailResponse
CustomerCommentRequest / CustomerDecisionRequest
SkillResponse / SkillVersionCreateRequest / SkillCompileRequest / TemplateReleaseResponse
AuthInvitationPreflightRequest / AuthInvitationPreflightResponse
AuthInvitationRedeemRequest / AuthInvitationRedeemResponse
RuntimeSessionScopeV2 / RuntimeProjectSessionScope
ContentErrorResponse
```

所有列表返回 `items + page`，所有可操作资源返回 typed `available_actions/blocked_actions/capabilities`。`EvidencePackItemResponse`、Evidence pending/finalized response 和 job `result_refs` 使用 OpenAPI discriminator/`oneOf`，不使用 `dict[str, object]` 或 `Record<string, unknown>` 逃逸。

`GET /v1/content/bootstrap/runtime` 的最低响应合同：

```json
{
  "schema_version": "content-v1.0-r4",
  "legacy_mode": true,
  "flags": {
    "content_studio_v1": true,
    "content_data_readiness_v1": true,
    "content_claim_qa_v1": false,
    "content_variants_v1": false,
    "content_delivery_v1": false,
    "content_customer_deliverables_v1": false,
    "content_skills_v1": false,
    "content_publication_request_v1": true,
    "content_auto_publication": false
  },
  "flag_blocked_reasons": {},
  "capabilities": ["content.read"],
  "available_actions": ["view_work_queue"],
  "poll_defaults": {
    "initial_seconds": 2,
    "max_seconds": 15,
    "jitter_ratio": 0.2
  }
}
```

bootstrap 结果按 actor/project 计算，必须设置私有缓存或 `no-store`，不能跨用户 CDN 缓存。后端 flag 是能力上限，capability 是当前 actor 权限，资源 `available_actions` 是最终可执行集合；三者都允许才显示命令。

### 19.5 兼容计划

以下接口保留至少两个发布周期：

```text
/v1/knowledge/content-generation-jobs/runtime
/v1/knowledge/content-drafts/runtime
/v1/knowledge/content-drafts/runtime/{id}/export.md
/v1/knowledge/content-drafts/runtime/{id}/review
POST /v1/knowledge/content-drafts/runtime/{id}/publication-request
```

兼容 adapter 行为：

1. 没有 Brief 时，从旧 payload 生成 `implicit_legacy_brief_v1`；
2. 构建并冻结 Evidence Pack；
3. 创建新 generation job；
4. 返回旧响应结构；
5. 写 deprecation header 和 audit event；
6. review/export 前锁定当前 draft，解析精确 version，并校验请求期间 current version/content hash 未变化；
7. 对账 old/new read model 数量和 hash；
8. 迁移完成前不删除旧数据。

Legacy `GET .../export.md` 必须保持只读和无 Publication/Distribution 副作用；最多记录独立 download audit。旧 `target_platform/platform` 在 adapter 中映射为 `publication_channel`，不得继续进入新领域模型。

Phase 0 使用兼容 `publication-request` 命令，body 必须包含 `content_hash/publication_channel/destination_key/reason` 和 Idempotency-Key，并锁定当前 Draft/hash。Phase 1 回填 Version 后，该命令解析 current version、校验 hash，再委托 canonical `.../versions/{version_id}/publication-requests`；两个发布周期后移除。

旧 `/v1/knowledge-applications/runtime` 只读兼容，不再扩展。

### 19.6 共享认证前置接口

Content Studio 与 Customer Deliverables 依赖同一 Runtime Session，因此 Phase 0 同步收口：

```http
POST /v1/auth/invitations/preflight
POST /v1/auth/invitations/redeem
GET  /v1/auth/me
POST /v1/auth/logout
GET  /v1/projects/runtime
```

`preflight` 是可选 UX 优化：请求包含 `invitation_id/invite_token/requested_surface`，只校验 token hash、pending、expiry 和服务端 surface capability policy，绝不修改 Invitation/Member/Session，也不设置 Cookie。响应只返回 `compatible/recommended_surface/invitation_role/policy_version` 等安全字段，不回显 raw token、member existence 或跨项目信息。

`redeem` 必须包含 `requested_surface=admin|customer` 和 `Idempotency-Key`，且请求模型不允许客户端 `accepted_by`；actor 来自规范化 Invitation email/已验证 principal。API 在持锁事务中重复全部校验，preflight 成功不能替代该检查。surface 权限由服务端 capability policy/version 决定，Admin/Customer BFF 不维护本地角色 allowlist。响应丢失后的同 key 重试按 §22.7 的 redemption attempt 合同重放同一 Session delivery，不旋转已签发 Session，也不把已消费 Invitation 变成永久登录失败。

错误入口返回稳定错误：

```json
{
  "code": "invitation_surface_mismatch",
  "detail": "This invitation cannot open the requested surface.",
  "recommended_surface": "customer",
  "invitation_consumed": false,
  "correlation_id": "uuid"
}
```

该响应 MUST 无 `Set-Cookie`，Invitation 仍为 pending，Member/Session/Audit accepted event 均不存在。Admin Web 可以展示到推荐入口的普通链接或重新提交入口，但不得把 raw token 拼进日志、错误、analytics 或 API 响应；原始邀请仍可在正确入口完成兑换。

---

## 20. Admin Web 与 Customer Web

### 20.1 前端演进约束

Admin Web 继续使用现有项目页 `operations/content` 作为唯一 Content Studio 入口，不建立平行产品壳。Phase 0 在原入口替换薄工作台，保留现有项目、知识、行动、审核和权限上下文。

最小 `GET /v1/content/bootstrap/runtime`、`ContentBootstrapResponse`、legacy adapter DTO、稳定错误 envelope 和 generated TypeScript types 必须在 Phase 0 与 v0 工作台同时上线，不能等到 Phase 1。此时 `legacy_mode=true`，仅开放 v0 已实现的 action。legacy inline Claim review 请求固定为：

```json
{
  "content_hash": "sha256...",
  "inline_claim_inventory_complete": true,
  "reason": "Reviewed every factual sentence"
}
```

服务端锁定 Draft current hash 后写 Review；hash 已变化返回 `412`，前端保留审核输入并刷新 Draft，不允许把布尔值写到另一个内容版本。

前端不是状态、权限或资格真源。API 返回 exact version/hash、ETag、capabilities、available actions、blocked reasons 和三种资格；前端只展示并提交命令，不按本地角色字符串重算门禁。

界面必须将以下三个操作和时间线彻底分开：

```text
Export package/download       -- 不改变 Asset、不创建发布任务
Create/Deliver Package        -- 独立 Delivery Job/Package
Mark as ready to publish      -- 显式 Publication Request
```

### 20.2 分阶段页面范围

| 阶段 | Admin 能力 | Customer 能力 |
| --- | --- | --- |
| Phase 0 | Generation queue、v0 Draft detail、inline claim completeness 审核、独立 Export、显式标记待发布、URL 回填/确认发布/验证/阻断 | 无 Content 页面 |
| Phase 0.5 | Data Readiness 概览、unknown rights/authority 治理队列 | 无 |
| Phase 1 | Opportunity projection、Brief Editor、Evidence Attempt、Website Asset Editor、Claim completeness、精确版本审核 | 无 |
| Phase 2 | Canonical/Variant、完整 Claim QA、Delivery Job、内部/客户包预览 | 可选只读预览，不开放客户动作 |
| Phase 3 | 产品化 Opportunity、Skill/Template lineage、客户可见性和审批管理 | Deliverables 列表/详情、评论、接受、请求修改、安全下载 |

入口保持：

```text
/projects/{project_id}?tab=operations&operation_tab=content
```

在该入口内使用可复制、可后退的 query state：

```text
content_view=queue|readiness|opportunities|briefs|assets|reviews|delivery|skills
brief_id / brief_version_id / asset_id / asset_version_id
```

### 20.3 Admin 信息架构与布局

顶层视图：

| View | 主要内容 |
| --- | --- |
| Work Queue | Evidence/Generation/Evaluation/Delivery Jobs、待审核、stale、blocked、dead letter |
| Data Readiness | eligible counts、unknown rights/authority 队列、owner/SLA、治理修改 |
| Opportunities | 投影 ref、评分、缺失输入、接受/阻断恢复/终止 |
| Briefs | head、不可变版本、主体实体、验证问题、证据策略 |
| Assets | Canonical/Variant、版本 diff、working copy、预览 |
| Reviews | Claim completeness、逐 Claim support、内部/合规审批 |
| Delivery & Publication | Export history、Package、Publication Request、Manual Distribution |
| Skills | Phase 3 Skill source、Template Release、diff、灰度、回滚 |

页面与后端合同：

| View | 首屏读取 | 主要命令 |
| --- | --- | --- |
| Work Queue | bootstrap + 四类 Job list + review queue | cancel、retry、regenerate、replay，严格按 available actions |
| Data Readiness | readiness summary/items | PATCH exact item governance + reason + If-Match |
| Opportunities | opportunity list/detail | accept、dismiss、block、reopen、terminate、convert |
| Briefs | Brief list/detail/versions + Evidence attempts | PATCH head、validate exact Version、build new Pack Attempt |
| Assets | Asset list/detail/versions | create Version、create Variant、synchronous internal Export |
| Reviews | Claims/Reviews/Evaluations | submit-review、typed review decision |
| Delivery & Publication | exports/packages/requests/distributions lists | create package/request、URL、confirm published、verify、block |
| Skills | Skill/detail/versions/releases | create version、compile、release、rollback |
| Customer Deliverables | customer-safe list/detail | comment、request changes、accept、authorised artifact download |

桌面布局：

```text
顶栏：项目 / 对象 / 精确版本 / Workflow Gate / Job / 主操作
左栏：机会、Brief、版本和对象导航
中栏：Brief 或 Canonical/Variant 编辑器与预览
右栏：Evidence、Claim、QA、Review、模型和 lineage
底部独立区：Export / Delivery / Publication 时间线
```

Asset 标题只显示 workflow status。Export、Delivery、Publication 以事件、计数和独立 badge 展示，不能合成 `exported/delivered/published` Asset badge。

视觉上保持现有后台的安静、信息密集风格：页面 section 使用无框分区，卡片只用于重复 Job/Opportunity/Deliverable item，不嵌套卡片；编辑/预览使用 segmented control，Evidence/Claims/Reviews 使用 tabs，状态 badge 同时显示图标和文字，颜色不是唯一信号。保存、导出、下载、重试、回滚等命令优先使用现有图标库并带 tooltip；危险或不可逆命令必须二次确认，普通状态切换不使用营销式大按钮。

“标记为待发布”确认框必须显示 exact Version/hash、publication channel、destination、reason、资格检查和“只创建跟踪记录，不会自动向平台发送”的明确结果；重复点击返回已有幂等结果。

### 20.4 Evidence、Claim 与版本交互

Evidence Inspector 显示 Attempt 时间线和对应 Job：

```text
Attempt 1  needs_evidence  -- 缺失主题与 owner
Attempt 2  blocked         -- 权限/授权/冲突 reason
Attempt 3  ready           -- selected for generation
```

- 旧 Attempt 永不重新显示为 building；
- `needs_evidence` 只能在补证后创建新 Attempt；
- `blocked` 修复策略前不显示普通 retry；
- Item 按判别联合显示 locator、snapshot/hash、subject、rights 和公开披露资格；
- internal Evidence 与 public Citation 使用不同筛选、图标和计数。

Claim/QA Panel 分开显示：

```text
Claim inventory completeness
Claim evidence support
Public citation availability
```

内部批准前 reviewer 必须确认 inventory complete 和逐 Claim support。任何正文编辑、新 Asset Version 或 extractor version 变化都会清除 completeness；coverage 在 completeness 未确认时显示 unknown，不得显示 100%。

已保存 Asset Version 只读；点击编辑创建 working copy，保存时调用“创建新 Version”，不覆盖原行。长文编辑不按每次按键建版本，不把机密正文写入 localStorage；离开未保存 working copy 时提示。`412` 后保留本地内容，允许比较 current head、基于新版本重放或放弃。

### 20.5 ViewModel、Actions 与错误合同

禁止新增 Content 页面继续直接消费数据库行或 `Record<string, unknown>`。FastAPI OpenAPI DTO 是传输真源，页面使用显式 ViewModel mapper。共同字段：

```ts
type ResourceActions = {
  available_actions: ResourceAction[];
  blocked_actions: Array<{ action: ResourceAction; reasons: BlockedReason[] }>;
  capabilities: ContentCapability[];
};

type LegacyContentV0DraftVM = {
  draft_id: string;
  content_hash: string;
  status: LegacyContentDraftStatus;
  rendered_text: string;
  inline_claim_inventory_complete: boolean;
  exportable_internal: boolean;
  publication_eligible: boolean;
  manual_distributions: ManualDistributionSummary[];
  actions: ResourceActions;
};

type BriefEditorVM = {
  brief_id: string;
  version_id: string;
  head_revision: number;
  head_etag: string;
  version_etag: string;
  payload_hash: string;
  workflow_status: BriefWorkflowStatus;
  primary_brand_entity_id: string;
  compared_entity_ids: string[];
  allowed_subject_entity_ids: string[];
  validation_issues: Array<{ path: string; code: string; message: string }>;
  selected_evidence_pack_id: string | null;
  actions: ResourceActions;
};

type EvidenceAttemptVM =
  | {
      state: "pending";
      job: ContentJobVM;
      brief_version_id: string;
      requested_attempt_number: number;
      evidence_pack_id: null;
    }
  | {
      state: "finalized";
      evidence_pack_id: string;
      brief_version_id: string;
      attempt_number: number;
      build_result: EvidencePackBuildResult;
      snapshot_hash: string;
      job: ContentJobVM;
      missing_subtopics: string[];
      blocked_reasons: BlockedReason[];
      public_citation_count: number;
      items: EvidenceItemVM[];
      actions: ResourceActions;
    };

type ContentJobVM = {
  job_id: string;
  job_type: ContentJobType;
  status: ContentJobStatus;
  terminal: boolean;
  progress: JobProgress;
  attempt_count: number;
  max_attempts: number;
  parent_job_id: string | null;
  regeneration_nonce: number;
  replay_nonce: number;
  error: ContentJobError | null;
  result_refs: JobResultRefs;
  actions: ResourceActions;
};

type AssetVersionEditorVM = {
  asset_id: string;
  version_id: string;
  version: number;
  head_revision: number;
  head_etag: string;
  version_etag: string;
  content_hash: string;
  workflow_status: AssetWorkflowStatus;
  rendered_text: string;
  content_json: ContentDocument;
  claim_inventory_complete: boolean;
  gate_summary: GateSummaryItem[];
  last_exported_at: string | null;
  delivery_package_count: number;
  latest_delivery_status: DeliveryPackageStatus | null;
  publication_request_count: number;
  actions: ResourceActions;
};
```

`EvidenceItemVM` 必须与后端 `item_type` 一一对应，是 `ApprovedFact | Chunk | Citation | ReportExtract | ActionExtract | RetestExtract | SourceAsset` 判别联合；新增后端 item type 时 OpenAPI discriminator diff 必须阻断漏实现的前端 exhaustive switch。Opportunity VM 使用 `opportunity_ref`，前端不解析底层表 UUID。

HTTP 处理：

| HTTP | UI 行为 |
| --- | --- |
| 401 | 清除失效会话，携带安全 return URL 登录 |
| 403 | 显示无 capability，不重复 mutation |
| 404 | 区分不存在、已撤回或当前用户不可见 |
| 409 | 刷新 actions/status，显示非法转换或幂等冲突 |
| 412 | 保留本地编辑，显示版本 diff/rebase/discard |
| 422 | 定位 field error；Gate 错误进入 Gate Summary |
| 429 | 遵循 Retry-After，只禁用受限命令 |
| 5xx/network | 保留输入，展示 correlation ID，允许安全重试 |

Admin/Customer 必须共享错误 envelope；Customer runtime 不得把所有非 2xx 折叠为 `null`。

### 20.6 状态与操作矩阵

| 对象/状态 | 允许的主要操作 | 禁止 |
| --- | --- | --- |
| Brief draft | 编辑、validate、取消 | Build Evidence、Generate |
| Brief validated | Build Evidence | 修改当前 payload、Generate |
| Brief evidence_building | 查看/取消 Job | 修改当前版本、Generate |
| Brief needs_evidence | 查看缺口、补证后新 Attempt | 原 Pack 回 building、Generate |
| Brief blocked | 查看 remediation，修复后新 Attempt | 普通 retry、Generate |
| Brief ready | Generate、创建新 Brief Version | 修改 current payload |
| Evidence blocked | 查看 remediation | 普通 retry、Generate |
| Evidence ready | Generate | 修改 Pack/Items |
| Job queued/running/finalizing | 进度、cancel（finalizing 可按服务端 action 禁用） | retry/regenerate/replay |
| Job retry_wait | 自动到期或授权用户 retry 同 Job | regenerate/replay |
| Job failed | 查看不可重试原因；Generation 可 regenerate 新 Job，其他类型重发原创建命令 | retry 同 Job、把 QA blocked 显示为 partial success |
| Job dead_letter | operator replay 为新 Job | 清除旧审计 |
| Asset qa_running | 查看 QA | Review、customer delivery、publication request |
| Asset pending_human_review | completeness/support Review、受控 internal Export | customer delivery、publication request |
| Asset approved | internal Export、Delivery、显式 Publication Request | 修改原版本 |
| Asset needs_revision/rejected | 基于 current 创建新 Version | customer delivery、publication request |
| Asset superseded/archived | 历史 lineage/制品 | 新审批、交付、发布请求 |
| Delivery Job queued/running | 查看、cancel | 下载未完成包 |
| Package ready | 下载、授权后 customer visible | 修改冻结包 |
| Distribution awaiting_url_backfill | URL 回填、block | 无 URL 时 verify |
| Distribution url_backfilled | confirm published、block | verify、改绑 Asset Version |
| Distribution published | verify、block | 改绑 Asset Version |
| Distribution verified/blocked | 查看历史；需要时新建 attempt | 修改终态记录 |

### 20.7 异步任务与并发

Evidence、Generation、Evaluation、Delivery 和异步 Skill Compile Job 统一：

1. `202` 后读取 `Location/Retry-After/status_url`；
2. 按 `2s -> 3s -> 5s -> 8s -> 15s` 加 jitter 轮询，服务端 Retry-After 优先；
3. 页面后台时降频，恢复可见立即刷新；
4. 前端超时只显示“仍在后台运行”，不得把服务端 Job 改成 failed；
5. terminal 后刷新 Job、Asset、Review Queue 和 available actions；
6. 离开页面不取消 Job；
7. retry/regenerate/operator replay 只按 `available_actions` 展示，并将 nonce/parent lineage 分开显示；
8. 网络结果不确定时复用同一 Idempotency-Key，显式 regenerate 使用新 key/nonce。

### 20.8 权限与 Customer Web

UI 只消费 API capabilities，按钮隐藏不能代替后端授权。核心 capability：

```text
content.brief.write
content.generate
content.job.retry / content.job.regenerate / content.job.replay
content.review.submit
content.review.claim_inventory
content.review.internal
content.review.compliance
content.export.internal
content.delivery.create
content.publication.request
content.publication.manage
content.skill.write / content.skill.release
content.accept_customer
portal.admin.access / portal.customer.access
```

`content.job.replay` 只授予受审计 operator/admin；普通 editor 只能 retry/regenerate 自己有权访问的 Job。

内部批准必须满足 `submitted_for_review_by != approver`。System Worker 永远不能显示为人工 approver。

Admin/Customer 登录 BFF 必须共享 generated Auth DTO 和服务端 surface capability：

- 可以先调用只读 preflight，也可以直接 redeem，但 redeem body 必须分别携带 `requested_surface=admin|customer`；
- 不再维护 `ADMIN_ROLES` 或从 top-level flat roles 推导入口权限；Admin bootstrap 必须检查 API 返回的 `portal.admin.access`；
- `invitation_surface_mismatch` 只显示正确入口的安全提示/链接，不转发 Cookie、不消费 token、不把 token 放入 query/localStorage/日志；
- 登录页 GET/只读 preflight 的响应必须在发起 redeem mutation **之前**生成随机、单 surface、绑定 token fingerprint 和 request hash 的稳定 Idempotency-Key，并放入 `Secure + HttpOnly + SameSite` 的短时 recovery Cookie；redeem POST 没有该 Cookie 时只返回带 recovery Cookie 的稳定 `428 redeem_prepare_required`，不得调 API 消费 Invitation，客户端用当前内存中的原表单 body 重提，不通过 URL/localStorage 搬运 token；从浏览器到 BFF 再到 API 的整次重试都复用该 key，不在每次 upstream retry 时重新生成；
- redeem 成功后完整转发所有 `Set-Cookie`，再 303 到固定 allowlist landing，禁止使用未经验证的 return URL；
- landing 后立即用新 Session 调用 `/v1/auth/me` 确认 delivery，成功后清理 recovery Cookie；响应丢失、断网重提和浏览器重定向丢失不得换 key，超过恢复 TTL 则显式进入重新邀请/人工恢复；
- Admin/Customer 多项目选择器只读取 API 按 `surface=admin|customer` 投影后的项目列表，不直接拿完整 Session scopes 自行过滤；切换 project 后所有 BFF request 仍由 API 做逐项目授权。

Phase 3 Customer Content Deliverables：

```text
/portal/content?project_id={id}
/portal/content?project_id={id}&delivery_package_id={id}
```

- 只读取 customer-safe DTO 和已内部批准的精确版本；
- 不显示 Prompt、内部 review notes、机密 Evidence、PII/security findings；
- 展示目标、公开证据摘要、public citations、版本、渠道和 Package；
- comment/request changes/acceptance 绑定 exact version/hash 并写独立 review；
- superseded/revoked Package 不能下载；
- 客户不能修改 Evidence、绕过内部审批、激活 Skill 或创建 Publication Request。

### 20.9 Responsive 与可访问性

```text
>=1280px   三栏：左 280-320，中 minmax(560,1fr)，右 340-400
901-1279   左导航 + 编辑器；Evidence/QA 使用右侧 Sheet
<=900      单列；Brief/Editor/Evidence/QA 使用 Tabs
<=620      全屏编辑/预览切换，底部稳定主操作栏，diff 顺序展示
```

字体不随 viewport 缩放；长 ID/错误/状态必须换行；工具栏和按钮尺寸稳定；状态不能只靠颜色；Job 更新使用 `aria-live=polite`；Dialog/Sheet 正确管理焦点；Error Summary 可跳字段；移动端必须支持阅读、评论、审核和长文编辑，sticky UI 不遮正文或系统键盘。

### 20.10 代码边界与联调

不得继续把 Content v1 堆进巨型 `ProjectActions.tsx`：

```text
apps/admin-web/app/projects/[project_id]/_content/
  ContentStudio.tsx
  ContentWorkspaceLoader.ts
  ContentWorkspaceViewModel.ts
  actions.ts
  components/
    OpportunityBoard.tsx
    BriefEditor.tsx
    DataReadinessBanner.tsx
    EvidenceInspector.tsx
    EvidenceAttemptTimeline.tsx
    AssetEditor.tsx
    VersionSwitcher.tsx
    ClaimQaPanel.tsx
    ReviewDecisionPanel.tsx
    DeliveryPanel.tsx
    PublicationPanel.tsx

apps/customer-web/app/_content/
  ContentDeliverables.tsx
  CustomerContentDetail.tsx
  CustomerReviewActions.tsx
```

Server Component 负责初始加载/权限；Client Component 只承担编辑、轮询、diff 和 dialog；浏览器不直连内部 API，使用同源 BFF/server action。沿用 `decisions/0010-frontend-component-stack.md` 的 TypeScript、Zod/RHF、Radix/shadcn 和 TanStack Table，不为 Content 单独引入另一套组件系统。

首次加载必须有确定的前后端握手顺序：

```text
ContentWorkspaceLoader
  -> GET bootstrap（schema/flags/capabilities/poll defaults）
  -> 按 flag/capability 并行加载当前 view 的 list endpoint
  -> 选中对象后并行加载 exact Version + Claims + Reviews + 时间线
  -> Client poller 只接管 bootstrap 允许的 active Job
  -> mutation 成功后按 result_refs 精确失效 query，不做整页 reload
```

bootstrap/schema major version 不受前端支持时，页面显示兼容性错误和 correlation ID，不尝试猜字段；某个次级 list 失败时保留已加载主对象并显示局部 retry。Work Queue 使用各 Job list API，Evidence Inspector 使用 pending/finalized union，Delivery & Publication 时间线分别使用 exports、delivery-packages、publication-requests 和 manual-distributions read API。

FastAPI OpenAPI snapshot 是 DTO 真源，CI 生成 Admin/Customer TypeScript 类型并运行 OpenAPI diff、typecheck 和 Python contract；generated 文件不得手改，新增 Content 页面禁止以 `Record<string, unknown>` 绕过类型。ViewModel mapper 必须测试 unknown enum、缺字段和向后兼容。

Fixture 至少覆盖：approved/exportable、publication request、needs evidence、blocked evidence、Evidence pending、Job finalizing/retry_wait/dead_letter、version conflict、claim incomplete、evaluation blocked、delivery ready、customer visible、revoked。Fixture mode 在 production build fail closed。API bootstrap 返回 flags、capabilities 和 schema version；前端 env 只能作为 kill switch，不能开启后端未启用能力。

---

## 21. Delivery、Publication 与反馈

### 21.1 Delivery Package

内部交付包：

```text
internal-delivery-package/
  canonical/
    article.md
    article.html
    content.json
  variants/
    linkedin.md
    youtube-script.md
  evidence/
    evidence-map.json
    source-list.csv
  geo/
    faq.json
    schema-markup.json
    internal-linking.csv
  qa/
    claims.json
    scorecard.json
    review-records.json
  manifest.json
```

客户安全包必须单独构建，不能直接复用内部 zip：

```text
customer-delivery-package/
  canonical/
  approved-variants/
  public-evidence-summary/
  public-citations.json
  customer-scorecard.json
  manifest.json
```

客户包禁止包含完整 Prompt Bundle、内部 review notes、机密 Evidence、PII/security findings 和未批准 Variant。

manifest 至少保存：

- project；
- asset/version；
- Brief version；
- Evidence Pack；
- Prompt Bundle；
- Skill versions；
- Model Policy 和 exact model；
- LLM call IDs；
- evaluator versions；
- review IDs；
- Claim inventory hash/completeness review；
- internal evidence ref hash 和 public citation refs（客户包只含后者）；
- internal export/customer delivery/publication eligibility results；
- artifact hash/size/content type；
- market/locale/channel；
- generated/approved timestamps 和独立 export/delivery event refs；
- validity/stale policy。

`content_delivery_jobs` 是 package 构建的 durable ledger。它必须复用 report worker 已有的 lease、retry、dead letter、object hash 和恢复模式，但不能伪装成 `report_export`；`content_delivery_packages` 只保存已冻结结果。

### 21.2 Publication

Phase 0-2 只支持：

- 内部 Export（无发布副作用）；
- Delivery Package（Phase 2，独立状态）；
- 显式 Publication Request；
- manual publication execution；
- URL/proof 回填；
- published/verified/blocked 状态。

正确顺序：

```text
approved Asset Version
  -> zero or more internal exports
  -> optional Delivery Package / delivery
  -> explicit publication_requested by authorised user
  -> manual_distribution_record awaiting_url_backfill
  -> url_backfilled -> published -> verified
  -> blocked（上述任一未验证状态均可阻断）
```

Export、Delivery 和 Approval 都不能隐式创建待发布记录。Phase 0 的显式 publication request 以 `content_draft_id + immutable publication_snapshot_hash` 绑定内容；Phase 1-2 改为精确 `content_draft_version_id + content_hash`，并记录 channel、destination、attempt、requester 和 reason。一个版本允许在同渠道发布到多个 destination 或多次更新；重复点击由 Idempotency-Key 防重。

Phase 0-2 中 `manual_distribution_records` 是显式手工发布执行真源。Phase 4 引入 `content_publications` 后，Publication aggregate 成为权威状态，manual distribution row 迁移为 publication attempt/compatibility projection，只能单向投影，禁止两边独立修改 status。

自动连接器进入 Phase 5，并要求 OAuth 最小 scope、secret rotation、dry run、撤回和失败补偿。

### 21.3 Feedback

反馈记录必须关联：

```text
content_draft_version_id
content_hash
publication_id
monitoring_query_id
observation_provider
market/city/device
observed_at
baseline_run_id
retest_run_id
```

支持：

- AI citation；
- brand mention/recommendation；
- source URL；
- search impression/click；
- conversion；
- social engagement；
- customer business signal。

效果展示必须写为“观察到的关联变化”。只有受控实验或充分因果设计才可使用因果措辞。

---

## 22. 安全、隐私、版权与治理

### 22.1 Prompt Injection

`CG-SEC-001`：Evidence 必须视为不可信数据。

要求：

- 预检常见 injection 指令；
- Evidence 不进入 system prompt；
- 生成任务默认无 tool 权限；
- 输出只能引用 Pack 中的 Evidence ID；
- 输出后运行 Schema、Claim、HTML 和 URL 检查；
- injection finding 属于不可 accepted risk 的 hard gate。

### 22.2 PII 与机密信息

当前预检对 email/phone 主要产生 warning，不足以支撑外部模型治理。目标流程：

```text
PII detection
  -> data classification
  -> redact/tokenise
  -> Model Policy check
  -> allow or block
```

记录检测类型和计数，不在普通日志记录原始敏感值。

不可 accepted risk 的是 `unauthorised_pii`、`classification_policy_violation` 和 `unredacted_restricted_data`，不是任何 PII。公开业务电话、公司地址、公开负责人姓名和获授权客户证言可在 usage rights、consent 与 Model Policy 全部允许时使用；外部模型输入许可与最终公开输出许可必须分别判定。

### 22.3 版权与使用许可

Evidence Pack 必须记录：

- source owner；
- licence/permission；
- quotation limit；
- allowed channel；
- customer case consent；
- expiry/revocation。

禁止把未知许可的第三方长文本直接改写为公开内容。

公开 Citation gate 还必须验证：

- `public_disclosure_allowed=true`；
- public URL 通过 scheme/host/SSRF 安全检查；
- quotation/attribution 规则满足；
- citation label/title 不泄露内部命名；
- Customer Package/公开输出只包含 `public_citation_refs`，内部 `internal_evidence_refs` 不透出。

### 22.4 高风险内容

金融、医疗、法律、就业、信用等高风险内容默认不在 MVP。启用前必须有：

- 专门 policy；
- 合格 reviewer；
- mandatory disclosure；
- 100% human review；
- jurisdiction/version；
- audit retention。

### 22.5 数据删除与保留

删除合同必须覆盖：

- PostgreSQL；
- Qdrant；
- MinIO；
- backup；
- cache；
- prompt/evaluation snapshot；
- provider retention request。

支持 legal hold；在 legal hold 下禁止物理删除但必须限制访问。

### 22.6 生产部署安全

Production Gate 必须验证：

- production compose/部署清单确实被使用；
- API 和所有 worker 使用同一 production environment；
- secret 来自 secret manager/managed secret，不挂载仓库根文本；
- 非默认 PostgreSQL/MinIO/Valkey 凭据；
- Qdrant API key/TLS 或私有网络；
- PostgreSQL/Qdrant/MinIO 不直接暴露公网数据端口；
- MinIO bucket policy/versioning/lifecycle + Phase 0 加密数据卷/key lifecycle/restore；
- worker egress allowlist；
- backup 加密和恢复演练；
- merged production config 的自动安全检查。

Phase 0 production baseline 明确只支持一个模式：

```text
OBJECT_STORE_MODE=embedded_minio
  -- 启动 encrypted data volume + MinIO + minio-bootstrap
```

Managed S3 后置到独立 ADR/overlay；在 provider provisioning、workload identity、encryption、policy、backup/restore 和等价 live Gate 定义完成前，不得把 `managed_s3` 配置标为 production supported。这样 Phase 0 Gate 不保留一个永远无法 Green 的伪分支。

`embedded_minio` 使用三类常驻/治理身份和两类短期任务身份：

| 身份 | 可见服务 | 权限 |
| --- | --- | --- |
| MinIO root | `minio`、一次性 `minio-bootstrap` | 只用于创建 bucket/principal/policy 和治理配置，不进入业务容器 |
| Application principal | 所有实际对象存储 runtime consumer | 仅对 `geo-reports`/配置 bucket 执行 put/get/head/list，禁止 admin/CreateBucket/常规 delete |
| Backup principal | backup job 与 `backup-object-smoke` | source bucket 只读；正式 backup prefix 可写不可删，当次隔离 smoke prefix 可写/读/清理；不复用 root/application 身份 |
| Ephemeral restore principal | 仅受控 restore job | 读取指定 backup manifest，只能写 `geo-reports/restore-smoke/{run_id}` 或批准恢复 prefix，完成后撤销 |
| Ephemeral retention principal | 仅受控 retention/delete job | 只删除批准 manifest 中的精确业务 prefix，完成后撤销 |

production 必须要求非默认 `MINIO_ROOT_USER/MINIO_ROOT_PASSWORD`、`OBJECT_STORE_ACCESS_KEY/OBJECT_STORE_SECRET_KEY`、`OBJECT_STORE_BACKUP_ACCESS_KEY/OBJECT_STORE_BACKUP_SECRET_KEY`；restore 演练另注入短期 `OBJECT_STORE_RESTORE_ACCESS_KEY/OBJECT_STORE_RESTORE_SECRET_KEY`，retention job 同理使用短期 `OBJECT_STORE_RETENTION_ACCESS_KEY/OBJECT_STORE_RETENTION_SECRET_KEY`。缺失或仍为 `minio/minio123` 时 merged config/build preflight 直接失败。base compose 可以保留本地开发默认值，但 base + production overlay 的任何 profile 都不得继承这些默认值。

`minio-bootstrap` 使用 root 身份幂等完成 `geo-reports/geo-backups` bucket、application/backup principal、最小权限 policy、versioning 和 lifecycle，写入不含 secret 的 policy/version receipt 后退出。bucket 只能由 bootstrap/IaC 创建；production runtime 必须设置 `OBJECT_STORE_AUTO_CREATE_BUCKET=0`，客户端只做 bucket `HEAD`/readiness，任何 application/backup principal 的 `CreateBucket` 都必须被 policy negative test 拒绝。现有 `put_object()` 和 `backup-object-smoke` 的 `mc mb` 行为必须在 production 路径禁用/移除，不能通过授予建桶权限绕过。

Phase 0 的 at-rest encryption 选定为 **MinIO data volume/backup volume 的基础设施加密**，不是尚未配置的对象级 SSE-KMS。加密卷必须在 MinIO 启动前由部署平台创建，key 由 Security/Platform 控制的 KMS/secret manager 管理，不进入 Compose 或应用容器。receipt 至少记录 `volume_id/provider/encryption_enabled/key_alias/policy_version/verified_at`，不记录 key；必须有 rotation owner、恢复所需 key escrow/权限和从加密 snapshot 在新节点 restore 的演练。若未来改为 SSE-KMS/KES，必须单独 ADR、双读/迁移和 restore Gate，不能只检查配置字符串。

API/worker 在加密卷 preflight、bootstrap 成功且 application principal 完成真实 `put -> head -> get -> hash` readiness 前不得 ready 或领取任务；root secret 不得出现在 API、worker、Web、日志或测试 artifact。

Application 对象存储配置必须来自同一个 production config/secret source，并作为完整原子集合传播：

```text
OBJECT_STORE_ENDPOINT
OBJECT_STORE_BUCKET
OBJECT_STORE_REGION
OBJECT_STORE_ACCESS_KEY
OBJECT_STORE_SECRET_KEY
```

runtime consumer inventory 当前至少包括：`api`、`collector-worker`、`collector-worker-litellm`、`browser-fidelity-scheduler`、`report-export-worker`、`knowledge-worker`、`task-worker-runtime`、`task-worker-knowledge`。`runtime-e2e` 是验证消费者；`backup-object-smoke` 使用独立 backup principal。Admin/Customer/Dashboard Web、PDF renderer、Embedding API 和 recovery dispatcher 不消费对象存储，不得收到这些 secret。新增调用 `build_object_store_from_env` 的服务必须自动进入 inventory 和 Gate，不能靠人工维护遗漏。

Bucket/prefix/action 合同：

| Principal | Source | Destination | Delete |
| --- | --- | --- | --- |
| application | `geo-reports` 业务 prefix read/write | 无跨 bucket | none（retention 另用短期身份） |
| backup | `geo-reports` read/list | 正式 `geo-backups/production/{environment}/` put/list/get；测试 `geo-backups/smoke/{run_id}/` put/list/get | 仅当次 `geo-backups/smoke/{run_id}/` |
| ephemeral restore | 指定 backup manifest/get | `geo-reports/restore-smoke/{run_id}` 或批准恢复 prefix put | 仅本次 restore-smoke prefix |
| ephemeral retention | 批准 deletion manifest 中的精确业务 prefix | 无跨 bucket | 仅 manifest 列出的 object keys |

上表 application 的 Delete 列实际为 none；业务对象删除只能由 ephemeral retention principal 执行，backup principal 的唯一 delete 例外是当次隔离 smoke prefix。backup/restore 复用 application 的 `OBJECT_STORE_ENDPOINT/OBJECT_STORE_REGION`；source bucket 使用 `OBJECT_STORE_BUCKET=geo-reports`，destination 使用 `OBJECT_STORE_BACKUP_BUCKET=geo-backups`，正式备份前缀使用 `OBJECT_STORE_BACKUP_PREFIX=production/{environment}/`，`backup-object-smoke` 必须使用 `OBJECT_STORE_BACKUP_SMOKE_PREFIX=smoke/{run_id}/`，并分别使用上述 backup/restore credential env。smoke 先对当次 prefix 执行 put/list/get/hash，再只删除当次 prefix；不创建 bucket，不得写入或清理正式 backup prefix。常驻 backup principal 不得写/delete 业务 source bucket，正式 backup prefix 不得 delete；restore/retention 权限不得常驻。

merged-compose contract 必须覆盖所有 production profiles，并验证：

- endpoint/bucket/region 在所有 runtime consumer 中一致；
- application key 只比较不可逆 fingerprint，所有 consumer fingerprint 一致；
- MinIO 只接收 root 身份，业务容器不接收 root；非 consumer 不接收任何对象存储 secret；
- 不存在开发字面量、空 required secret 或 backup smoke 硬编码凭据；
- application principal 无 admin/越 bucket 权限；backup principal 不得写/delete source 业务 bucket，正式 backup prefix 只能 put/list/get，smoke prefix 只能对当次 `run_id` put/list/get/delete；跨 run 和正式 prefix delete 必须被拒绝；
- application/backup `CreateBucket` 均被拒绝；restore principal 过期/撤销后访问被拒绝；
- 加密卷 receipt、key alias/rotation owner 和 encrypted snapshot restore 行为通过，不以 source-string 代替；
- secret 原值不进入 `docker compose config` artifact、日志、浏览器 payload 或诊断输出。

### 22.7 邀请兑换与多项目 Session

邀请 token 是一次性 capability。角色/surface 不匹配、Session 创建失败或并发失败都不能消耗它。安全真源是 API 的 versioned capability policy，不是 Admin/Customer Web 中的角色字符串集合。

Invitation 增加 `tenant_id/audience/allowed_surfaces/policy_version`，Project Member 也增加 `tenant_id`；两者的 `(project_id, tenant_id)` 都以复合 FK 指向 Project，使兑换和完整 membership scope 查询不必 JOIN 一个在 FORCE RLS 下尚不可见的 Project。该 FK 的物理前置是 Project 父表先有 `UNIQUE (id, tenant_id)`，Member/Invitation 回填并验证后 `tenant_id` 必须 `NOT NULL`；可空或未验证的 tenant 不能成为权威兑换输入。创建邀请时按服务端 role -> capability policy 固定受众；旧 pending invitation 按同一 policy 回填，无法无歧义分类的记录撤销并重发，不能由前端猜测。

Phase 0 冻结 `auth_surface_policy_v1` 最小矩阵：

| Canonical role | Surface capability | 说明 |
| --- | --- | --- |
| `super_admin/tenant_admin` | `portal.admin.access` | 按 tenant policy 为该 tenant 的项目生成 tenant-derived project scope |
| `project_owner`（`owner/admin` alias） | `portal.admin.access` | 仅所属 project 的管理能力 |
| `analyst/reviewer/knowledge_architect/content_operator` | `portal.admin.access` | 可进入工作台，但具体命令仍由逐项目 permission 限制 |
| `client_viewer`（`viewer` alias） | `portal.customer.access` | 只进入 Customer surface 和 customer-safe DTO |

因此 `analyst` 是合法 Admin 工作台角色，不应被前端 `ADMIN_ROLES` 拒绝；`viewer` 从 Admin 入口提交则必须 mismatch 且不消费。若未来允许 owner 客户预览或新增双 surface role，必须发布新 policy version。Invitation 的有效 surfaces 取“签发快照与当前 policy 的交集”，policy 变化不得扩大旧 Invitation；交集为空返回 `invitation_policy_stale` 并重发。Session 保存 `authz_policy_version`，policy 收紧时撤销/刷新受影响 Session。

权威 redeem 必须是单一数据库 Unit of Work：

```text
BEGIN
  -> SET LOCAL invitation token hash；清空 actor/project/tenant context
  -> SELECT invitation FOR UPDATE（只读 invitation.tenant_id，不 JOIN projects）
  -> INSERT ... ON CONFLICT / SELECT redemption attempt FOR UPDATE
  -> 已成功的同 key attempt：校验 request binding/TTL/confirmation 后返回同一 Session delivery
  -> 新 attempt：validate id/hash/pending/expiry/audience/requested_surface/policy_version
  -> mismatch: rollback and return 409, zero side effects
  -> upsert project_member using invitation-accept RLS policy
  -> SET LOCAL actor = normalized invitation email；tenant = invitation.tenant_id；project = NULL
  -> query actor's complete active membership scope in that tenant
     (actor_id + tenant_id, MUST NOT filter by invitation project_id)
  -> create scope-v2 runtime_session
  -> envelope-encrypt Session delivery material into short-lived attempt
  -> mark invitation accepted_by_attempt + write audit
COMMIT once
  -> only after commit emit Session/CSRF cookies
```

所有 auth context 必须通过 `SET LOCAL` 或 `set_config(..., true)` 设置，commit/rollback 后自动清除；连接归还 pool 前验证没有 invitation hash、actor、project 或 tenant context 泄漏。Heartbeat/普通 API 不得复用 Invitation context。repository accept、membership scope、Session insert 和 Invitation accepted 不能各自 commit。任一步失败必须回滚 Member/Session/accepted/audit；两个并发 redeem 由 invitation row lock 保证最多一个成功。preflight 只是只读体验优化，redeem 必须在同一锁内重新校验，防止 TOCTOU。public redeem 的 actor 固定为规范化 Invitation email 或已验证 principal，移除/拒绝客户端 `accepted_by`。

为关闭 “COMMIT 成功但 Set-Cookie 响应丢失” 窗口，redeem 强制 `Idempotency-Key`，并新增 redemption attempt ledger：

```text
UNIQUE(invitation_id, requested_surface, idempotency_key_hash)
request_hash/token_fingerprint/session_id/status/replay_count
delivery_ciphertext/delivery_key_id/delivery_nonce/delivery_expires_at
delivery_confirmed_at/secret_erased_at/created_at/updated_at
```

首次 UoW 必须在任何 Member/Session/Invitation 副作用之前 insert/lock attempt，并在同一事务中写入 Session 与可重放 delivery；delivery 冻结首次签发的完整 serialized `Set-Cookie` 值、attributes 和绝对 expiry，重放不重新计时。同 token fingerprint + surface + key + request hash 的并发/网络重试必须锁同一 attempt，在恢复窗口内返回字节等价的同一 Session/CSRF Cookie，**不得 revoke/rotate Session**；因此两个响应即使乱序到达，Cookie 也不会被旧 generation 覆盖。不同 payload 复用 key 返回 `409 idempotency_key_reused`，Invitation 已由其他 key 消费则 fail closed，不得用新 key 把一次性 token 变为长期 Session 签发凭据。

delivery material 不得明文落库；使用专用 Auth Delivery KMS key 做 envelope encryption，密文不进入日志/备份分析导出。Phase 0 默认 `recovery TTL=10 min`、`max replay=5`；`/v1/auth/me` 首次成功使用该 Session 后原子设置 `delivery_confirmed_at` 并擦除密文。已确认、超 TTL 或超重放上限的 attempt 不得撤销正在使用的 Session，而是返回稳定恢复错误并要求重新邀请/人工核验。过期 job 先擦除密文再按 Auth audit retention 保留 hash-only ledger；密钥轮换必须覆盖 TTL 内密文解密。BFF 按 §20.8 使用短时 HttpOnly recovery Cookie 保证浏览器到 API 的 key 稳定，审计只写 key/token fingerprint、replay count 和结果。

Session v2 的持久化和 `/v1/auth/me` 响应至少包含：

```yaml
scope_version: runtime_session_scope_v2
authz_policy_version: auth_surface_policy_v1
actor_id: user@example.com
tenant_id: uuid
tenant_roles: []
project_scopes:
  - project_id: project-a
    roles: [project_owner]
    permissions: [project.read, project.update, report.read]
    portal_capabilities: [portal.admin.access]
  - project_id: project-b
    roles: [client_viewer]
    permissions: [report.read, report.download]
    portal_capabilities: [portal.customer.access]
project_ids: [project-a, project-b] # compatibility projection only
```

`project_ids` 必须等于当前 tenant 内完整 `project_scopes` key set，不能只含邀请项目。`super_admin/tenant_admin` 按 policy 对 tenant 内所有 active Project 生成 `scope_source=tenant_role` 的 project scope；其他角色只使用直接 active membership。顶层 flat `roles/permissions` 只能作为兼容展示字段，所有授权必须按请求 `project_id` 读取对应 `project_scope`，再按明确规则叠加 tenant role；禁止把 `owner(project-a) + viewer(project-b)` 合并成 project-b 的 owner 权限。

tenant-derived scope 不能只存在 Session JSON 中；否则当前只认 `project_members` 的 FORCE RLS 仍会拒绝同 tenant 访问。Phase 0 新增可审计 `runtime_project_access_grants`（或等价规范表），至少包含：

```text
tenant_id/project_id/actor_id
source_type=tenant_role/source_id/canonical_role
permission_set_version/status/granted_at/revoked_at
UNIQUE(tenant_id, project_id, actor_id, source_type, source_id)
FOREIGN KEY(project_id, tenant_id) REFERENCES projects(id, tenant_id)
```

tenant role 变更、Project 创建/激活/归档必须在同一数据库事务内物化或撤销 grants；同步失败时 fail closed，不允许先授权再异步补表。`geo_runtime_can_access_project` 及所有 project-owned RLS policy 收口为“直接 active `project_members` **OR** 当前 actor/tenant 的 active grant + 所需 permission”。Phase 0 冻结为独立 `NOLOGIN BYPASSRLS` 的 `geo_rls_authz_owner` 持有窄 SECURITY DEFINER helper：固定安全 `search_path`、全部表名 schema-qualified、禁止 dynamic SQL、撤销 PUBLIC execute，仅向 app role 授予执行；function 只读 Member/Grant 表和 transaction-local actor/tenant GUC，不读 `projects`，避免 RLS 递归。owner 不得登录、持有业务表或被应用 `SET ROLE`，function body/owner/ACL/search_path 纳入 migration drift Gate。Session scope 签发从直接 Member + active Grant 合并，`/projects?surface=...`、detail 和 mutation 均经同一 RLS anchor，不得仅在 repository 中特判 tenant admin。

Session 的完整 scope 不等于某个门户的可见项目。`GET /v1/projects/runtime?surface=admin|customer` 必须由 API 做 server-side projection：Admin 只返回含 `portal.admin.access` 的 scope，Customer 只返回含 `portal.customer.access` 的 scope；UI 不接收后再自行过滤。owner(A)+viewer(B) 的 Customer selector 只能看到 B，Admin selector 只能看到 A，两个 surface 的 detail/mutation 也重复逐项目校验。当前 Session 固定一个 tenant；跨 tenant membership 不静默合并，必须显式切换/新建 Session。

Phase 0 additive migration：

- 先 inventory 大小写重复：同 project/规范化 user 且同 role 的 Member 合并到确定 canonical row；role 冲突必须进入 owner 人工队列，禁止自动提升权限；
- 同 project/规范化 email 的 pending Invitation 若 role/audience 相同，只保留最新未过期项并 revoke 其余；冲突则全部 revoke 并要求重发；所有 merge/revoke 记录 before/after audit 和 count/hash 对账；
- 先为 `projects(id, tenant_id)` 建 concurrent unique index 并 attach 为父级 UNIQUE constraint；再为 Member、Invitation 和 Grant additive 增加可空 `tenant_id`，用 maintenance scope 按 `project_id -> projects.tenant_id` 回填、隔离无父项或伪造 mismatch，并完成 count/hash 对账；
- 回填清理后添加 `(project_id, tenant_id) REFERENCES projects(id, tenant_id) NOT VALID` 和 `tenant_id IS NOT NULL NOT VALID` check，依次 `VALIDATE CONSTRAINT`，再 `ALTER COLUMN tenant_id SET NOT NULL` 并移除过渡 check；只有全部验证成功才切换 redeem/RLS，升级窗口由 dual-write trigger/service 保证新行不丢 tenant；
- 清理完成后删除 `idx_project_members_viewer_user_global_unique` 和 `idx_project_member_invitations_viewer_email_global_unique`，建立 project 内 case-insensitive unique index：Member `(project_id, lower(user_id))`，pending Invitation `(project_id, lower(email)) WHERE status='pending'`；
- 回填 tenant-role grants，在真实 app role 下核对 tenant admin 的 Project 数量/权限，再原子切换所有 project RLS anchor；无稳定 actor 或 tenant 的 role 记录不自动授权，进入 owner 队列；
- `runtime_sessions` 增加 `scope_version/authz_policy_version/tenant_roles/project_scopes`（或等价规范化 child table），并保证 `project_ids` 是事务内生成的兼容投影；新增短时加密 delivery 的 redemption attempt ledger 与清理 job；
- active v1 Session 按 actor + tenant 的当前 membership 回填；无法可靠回填的 Session fail closed/revoke，并进入 `reauth_required` 队列，由 Admin 发出新 Invitation/登录挑战；accepted 旧 Invitation 不可直接复活；
- Membership role/status 改变后，撤销或原子刷新该 tenant 的 active Session，不能让旧权限持续到 7 天 TTL 结束。

本方案冻结 **fail-closed rollback**，不依赖旧 binary 补写 `tenant_id`：回滚前先在 edge/gateway 禁用所有 Auth、Member 和 Invitation mutation（包括 redeem、Session 签发、Member create/update/delete、Invitation create/revoke/accept），统一返回 `503 auth_writes_temporarily_disabled + Retry-After`；同时撤销 scope-v2 Session，并从 rollback app DB role 撤销 `project_members/project_member_invitations/runtime_sessions/runtime_project_access_grants/redemption_attempts` 的 mutation privilege，作为不可绕过的第二层保护。旧 redeem/auth route 不得恢复流量，只有 forward-fix 代码通过新 schema Gate 后才重开写入。父 UNIQUE、复合 FK/NOT NULL、Grant 和 ledger 保持 additive，不因应用回滚删除或放宽。fresh install、含大小写/角色冲突的 dirty upgrade，以及“旧 binary + 新 schema + 全 Auth mutation 双层禁用”回滚都必须是独立验收路径。

Preflight/redeem 必须 `Cache-Control: no-store`、限速并统一无效 token 的外部错误，防止枚举。raw token 不得进入 URL 重定向、response、Cookie 之外的客户端存储、日志、analytics 或 artifact；审计只保存 token hash/fingerprint。

---

## 23. 可观测性、成本与 SLO

### 23.1 Correlation

以下对象共享 `correlation_id`：

```text
opportunity
brief
evidence_pack
prompt_bundle
generation_job
asset_version
evaluation
review
delivery
publication
retest
```

### 23.2 指标

API：

- request count/error/latency；
- 401/403/409/422/429/5xx；
- idempotency hit/conflict。

Job/Worker：

- queue depth；
- oldest queued age；
- claim latency；
- stage duration；
- attempts/retries；
- expired lease active/reclaimed/dead-letter by queue + job type；
- per-table oldest expired age/recovery pass cursor/slots used/starvation；
- lease lost/stale-token completion rejected；
- heartbeat success/failure；
- dead letter；
- cancellation；
- worker heartbeat age。

Model：

- provider/model requests；
- timeout/rate limit/schema failure；
- fallback/circuit open；
- provider calls used / remaining Job budget；
- prompt/completion tokens；
- cost；
- latency；
- response size。

Evidence/QA：

- eligible source assets/approved facts by project/channel；
- unknown usage rights count/age/owner；
- Evidence Pack Job status、Attempt count、ready/needs evidence/blocked；
- coverage；
- claim inventory completeness/recall；
- public citation availability；
- conflict/expired/permission blocked；
- Claim supported/partial/unsupported/conflict；
- hard gate failure；
- stale asset。

Review/Delivery：

- review queue age；
- first pass approval；
- changes requested；
- customer acceptance age；
- package build failure；
- artifact restore failure；
- export count；
- publication request/destination/attempt；
- explicit request -> published conversion。

Platform/Identity：

- object-store readiness/auth failure by service class，credential 只使用 fingerprint 一致性指标；
- invitation preflight/redeem/surface mismatch/rollback/concurrent conflict；
- redemption response-loss replay/delivery confirmation/replay limit/secret erasure；
- Session scope/authz policy version、direct/grant project scope count、membership/policy-change revocation；
- tenant-role grant create/revoke/drift 和 RLS helper denied by source；
- per-project authorization denied 和 cross-project role-bleed attempt。

### 23.3 初始 SLO 候选

正式值必须在基线测量后批准。候选：

| SLO | 候选目标 |
| --- | --- |
| Mutation API accepted | p95 < 500 ms，不包含异步模型时间 |
| Durable Job acceptance | 99.9% 请求要么成功落账要么明确失败 |
| Queue start | 正常负载 p95 < 60 s |
| Standard Website draft | p95 < 5 min |
| Expired lease recovery | 2 个 recovery interval 内 |
| Active expired lease beyond recovery window | 0 |
| Stale lease result accepted | 0 |
| Production object-store credential mismatch accepted | 0 |
| Wrong-surface invitation consumed | 0 |
| Same-key invitation replay changed Session token | 0 |
| Confirmed Session revoked by invitation replay | 0 |
| Cross-project role bleed | 0 |
| Cross-tenant tenant-role grant accepted | 0 |
| Cross-project leakage | 0 |
| Cross-project FK violation accepted | 0 |
| Unsupported high-risk Claim published | 0 |
| Claim inventory incomplete publication | 0 |
| Export-created publication request | 0 |
| Delivery artifact hash mismatch | 0 |

RPO/RTO 应沿用项目总体备份合同，并增加 Content 新表和 MinIO package 的恢复检查。

### 23.4 告警

至少配置：

- queue age 超阈值；
- active expired lease 持续超过 2 个 recovery interval；
- 任一 Knowledge/Collection 表 recovery pass 连续缺席，或 fresh backlog 占用了保留 recovery slots；
- heartbeat failure/lease lost 激增；
- dead letter > 0；
- provider 429/5xx 激增；
- cost budget 80%/100%；
- hard gate 异常下降或绕过；
- stale approved Asset 或 published destination；
- claim inventory incomplete approval attempt；
- publication request without explicit actor/reason；
- customer download 403/5xx；
- Qdrant/MinIO/PostgreSQL health；
- object-store consumer credential fingerprint/readiness 不一致；
- wrong-surface redeem 出现 accepted/session/cookie 副作用；
- redemption delivery 密文超 TTL 未擦除、replay limit 激增或同 key 出现多个 Session ID；
- tenant-role grant 与 active tenant member/project 数量漂移，或 RLS helper owner/ACL/search_path 发生变化；
- backup artifact hash mismatch。

---

## 24. 测试与验收

### 24.1 现有可复用测试

- Python unit/contract；
- ASGI API contract；
- knowledge pipeline live E2E；
- Qdrant smoke；
- heavy component smoke；
- frontend knowledge lifecycle Playwright；
- content review/export smoke；
- RLS、backup、ops 和 production gate 框架。

注意：部分 Production verifier 只是检查源码字符串存在，不等于运行行为通过。

### 24.2 新增测试层

单元：

- Opportunity score/version/missing component normalisation；
- Brief validation/version concurrency；
- Evidence conflict/dedup/validity/rights；
- Evidence item fingerprint/discriminated union；
- Evidence snapshot text/URI exactly-one 与非空约束；
- Skill merge strategy；
- Skill -> Template Release compiler lineage；
- Prompt compiler source map；
- canonical Content JSON/render/hash determinism 与 client preview mismatch；
- idempotency key；
- state transition guard；
- Claim matching；
- Claim inventory completeness、subject entity match 和 public citation eligibility；
- internal export/customer delivery/publication eligibility；
- qualification composition and fail-closed behavior。

Repository/DB：

- fresh install；
- `0028 -> 0029+` upgrade；
- rollback；
- backfill counts/hash；
- unique constraint；
- same-project composite FK 和 typed polymorphic FK negative；
- deferred Brief head/current-version cycle；
- Evidence active builder partial unique、原子 attempt 编号和并发创建；
- selected ready Pack deferred constraint trigger；
- sealed Evidence Pack/Item immutable trigger behavior；
- Claim/Evidence mapping 必须属于 Draft 冻结的同一 Pack；
- explicit publication request 与 Export 无副作用；
- multi-destination/multi-attempt distribution、原子 attempt 编号、scoped idempotency 和完整 URL/published/verified 转换；
- Asset edit creates version、invalidates review、preserves history；
- optimistic locking；
- project RLS SELECT/INSERT/UPDATE/DELETE negative；
- system/tenant/project Skill policy；
- Knowledge/Collection lease schema、per-table status/active-lease CHECK、claim/reclaim partial index 的 fresh/0028 upgrade/rollback；upgrade seed 覆盖 `draft/ready/fallback_succeeded/partial_succeeded`，证明追加 lease 状态不删除既有合法状态；
- 删除 viewer global unique，建立 project-scoped case-insensitive Member/pending Invitation 唯一；
- 大小写重复/role 冲突脏数据清理、audit/count/hash 对账后再建 unique；
- `projects(id, tenant_id)` 父 UNIQUE，Member/Invitation/Grant `tenant_id` 回填 -> NOT VALID FK/CHECK -> VALIDATE -> NOT NULL 的 fresh/dirty-upgrade/rollback；伪造 project/tenant mismatch 必须被复合 FK 拒绝；
- “旧 binary + 新 schema”回滚演练中，edge 对全 Auth/Member/Invitation mutation 返回稳定 503，rollback DB role 对 Member/Invitation/Session/Grant/Ledger 写入被拒绝，无 NOT NULL 500、无 v1 Session 签发和部分副作用；
- Session scope-v2/加密 redemption attempt backfill、无法回填 Session revoke/reauth queue、delivery secret TTL 擦除和 membership/policy change invalidation；
- tenant-role grant 在 role/Project create、activate、archive 时与业务变更同事务，grant 回填对账、revoke 立即生效，RLS helper body/owner/ACL/fixed-search-path drift 均 fail Gate；
- 真实 app role + FORCE RLS 下 invitation accept/scope/session 正向路径，commit/rollback 后复用连接无 context 泄漏；
- tenant_admin/super_admin 在无显式 project_member 时可签发同 tenant scope、列表/detail/mutate，但跨 tenant 和未授 permission 均被真实 RLS 拒绝。

Worker：

- duplicate dispatch；
- concurrent claim；
- queued/retry_wait claim，fresh running 不可领取，expired running 原子 reclaim；
- 两连接并发 reclaim 只有一个 owner，token 旋转且 attempt+1；
- 前序 Knowledge 表持续填充 queued backlog 且 `max_jobs` 受限时，后序表和 Collection 的 expired running/finalizing 仍按 expired-first + round-robin 在 2 个 interval 内转移 token；各表最旧 lease 的处理顺序可验证；
- heartbeat 延长租约，旧/过期 token 的 heartbeat/complete/fail/finalize 全部 0-row；
- finalizing 持续超过一个初始 lease 时 heartbeat 有效且第二 worker 不可领取；
- queued/retry_wait cancel 直接 terminal，active cancel 与 complete/fail 的线性化竞态只产生一个合法终态；
- attempt 上限进入 DLQ，cancel-requested 不接管；
- 在 claim commit 后、complete/fail 前 kill -9 Knowledge worker 和持有 Collection lease 的 Dramatiq actor/container，确认数据库保留 running 后仍在 lease expiry + 2 recovery interval 内旋转 token 接管；child subprocess kill 另测正常 fail/retry；
- crash after model/before commit；
- crash/reclaim during `finalizing`，验证只重做 artifact finalize 且不重复模型调用；
- retry；
- dead letter/replay；
- retry/regenerate/replay lineage；
- Evidence Pack Job/new Attempt；
- Evidence dead-letter replay 分配新 attempt 并保留 parent lineage；
- Evaluation Job/exact Version-hash binding；
- Job/provider total call budget；
- cancel；
- deterministic result binding；
- Prompt Bundle selected-ready preflight 和 stale-before-model fail closed；
- Skill Compile Job/result lineage/retry/replay。

Model/Gateway：

- timeout；
- rate limit；
- schema invalid；
- compatible fallback；
- cost budget；
- call log；
- sensitive log redaction；
- Provider Capability Registry fail closed。

Security：

- prompt injection；
- PII classification/redaction；
- secret；
- malicious HTML；
- SSRF URL；
- cross-project Evidence；
- revoked consent；
- unsupported high-risk Claim；
- unauthorised PII vs authorised public contact；
- internal Evidence/public Citation separation；
- Invitation preflight zero-write、surface mismatch zero-write/no-cookie、Session insert failure 全事务 rollback；
- concurrent redeem 只成功一次，raw token 不进入 response/log/URL/artifact；
- redeem commit 后响应丢失，同 Idempotency-Key 在 TTL 内返回同一 Session/CSRF Cookie，不 revoke/rotate；同 key 并发、响应乱序和浏览器丢失 303 后重提均可登录；
- payload 改变复用 key、超 TTL/重放上限、已 confirmed Session 后重放均 fail closed，且不撤销已确认 Session；delivery 密文到期/确认后可验证擦除；
- `auth_surface_policy_v1` 矩阵：analyst Admin 可登录但权限受限、viewer Admin mismatch、stale policy Invitation fail closed；
- owner(project A)+viewer(project B) 对 B 的管理 mutation 为 403，跨 tenant membership 不并入 Session；
- Admin/Customer project list 做 server-side surface projection，mixed-role A/B 双向不可见且 detail/mutation 均拒绝。

Infrastructure/live：

- 带 sentinel 的 base + production merged compose 覆盖所有 profiles，所有 object-store consumer 配置/fingerprint 一致且无开发默认；
- 缺任一 required root/application/backup secret 时 compose/preflight 失败；
- non-default embedded MinIO 启动后 API、Collector、Report、Knowledge、Dramatiq 路径分别完成 put/get/head/hash；
- application/backup principal 的 CreateBucket/admin/越 bucket 负测；正式 backup prefix 无 delete，当次 smoke prefix 可 put/get/hash/delete 但跨 run 删除被拒绝；ephemeral restore prefix 权限和真实 restore SHA-256；
- 加密卷 receipt、key alias/rotation/recovery owner 和 encrypted snapshot 新节点 restore；
- non-consumer 未收到对象存储 secret，artifact/日志不包含 secret 原值。

Frontend/E2E 主链：

```text
GEO Action
  -> Brief
  -> Evidence Pack
  -> Generate Canonical
  -> Claim QA
  -> Internal approval
  -> LinkedIn variant
  -> Customer request changes/accept
  -> Delivery Package
  -> explicit Publication Request
  -> manual publication URL/confirm published/verify
  -> GEO retest
```

覆盖 desktop/mobile、console error、HTTP 5xx、下载内容和截图。

分层行为：

| Profile | 必测前端行为 |
| --- | --- |
| P0 | 最小 bootstrap/legacy typed DTO；邀请错入口不消费、丢失响应同 key 稳定恢复、Admin/Customer surface-projected 多项目选择和逐项目权限；exact-hash inline review；Export 不创建 distribution；显式标记待发布才创建；URL/confirm published/verify/block；租约恢复语义 |
| P0.5 | governance migration；Data Readiness counts、unknown rights owner、eligibility dry-run 和 eligible Evidence drill-down |
| P1 | bootstrap/list/detail 联调；Evidence 失败后新 Attempt；Claim completeness；Evaluation Job；人工编辑新 Version；旧审批失效；head/version ETag 与 412 冲突 |
| P2 | Variant invariant；Delivery Job；内部/客户包隔离；hash/restore；Asset/Delivery 状态分离 |
| P3 | 客户只见批准精确版本；comment/request changes/accept；maker-checker；revoked/superseded 下载阻断 |

每个 profile 覆盖 `401/403/409/412/422/429/5xx`、1440px desktop、约 900px tablet、390px mobile、keyboard/focus、刷新/后退/多标签页和重复提交。source-string/page-click smoke 可保留，但不能作为 lifecycle gate 的唯一证据。

### 24.3 Golden Set

数量在样本分析后确定，不预先拍脑袋。数据集必须：

- 有 owner 和版本；
- 按 content type/channel/risk/market 分层；
- 区分 train/dev/test；
- 固定 Evidence Pack；
- 有 Claim 支持人工标注；
- 分别标注 Claim extraction recall、Evidence matching precision 和 support classification accuracy；
- inventory incomplete 样本必须阻断 coverage=100%；
- 高风险样本双人标注；
- 记录标注一致性；
- 有允许退化阈值；
- 模型/Skill/evaluator 升级必须重跑。

### 24.4 需求追踪矩阵

| Requirement | Test | Artifact | Gate |
| --- | --- | --- | --- |
| `CG-PROD-002` Claim 可追踪 | claim repository + live E2E | `content-claim-trace/latest.json` | claim gate |
| `CG-PROD-003` 证据不足阻断 | unit + API + E2E | `content-needs-evidence/latest.json` | evidence gate |
| `CG-PROD-006` Claim inventory completeness | recall set + reviewer E2E | `content-claim-inventory/latest.json` | claim gate |
| `CG-MODEL-001` 统一 Gateway | adapter + live model smoke | `content-model-gateway/latest.json` | model gate |
| `CG-SEC-001` untrusted evidence | adversarial suite | `content-security/latest.json` | security gate |
| `CG-PROD-009` Durable Job 租约恢复 | Knowledge/Collection PG concurrency + kill/reclaim | `durable-job-lease-recovery/latest.json` | worker gate |
| `CG-PROD-008` Production object-store identity coherence | merged-compose + non-default MinIO live/policy/restore | `production-object-store-credentials/latest.json` | security gate |
| `CG-PROD-010/AUTH-INV-001` 邀请 surface 原子校验/稳定重放 | repository/API/browser mismatch + concurrent/reordered/lost-response redeem | `auth-invitation-surface/latest.json` | identity gate |
| `CG-PROD-010/AUTH-SES-001` 多项目逐项目 Session | dirty migration + API + Member/Grant RBAC/RLS + selector E2E | `auth-session-project-scope/latest.json` | RBAC/RLS gate |
| Project isolation | CRUD RLS negative | `content-rls/latest.json` | RLS gate |
| Same-project relationship integrity | composite FK DB negative | `content-relationship-integrity/latest.json` | DB gate |
| `CG-PROD-007` Export 无发布副作用 | API + frontend E2E | `content-publication-intent/latest.json` | publication gate |
| Delivery hash/restore | MinIO package restore | `content-delivery-restore/latest.json` | backup gate |
| Internal/customer approval | frontend/API E2E | `content-approval-lifecycle/latest.json` | review gate |

每个 artifact 必须包含：

```text
run_id
started_at
finished_at
git_commit
worktree_dirty
environment
input_hash
status
checks
output_hash
```

---

## 25. Production Final Gate

门禁按交付阶段分层启用，不能把未来阶段能力提前变成 Phase 0 的阻塞项，也不能因为未来能力尚未启用而跳过当前阶段的基础安全门禁。

| Profile | 适用阶段 | 阻塞范围 |
| --- | --- | --- |
| Base / Content v0 | Phase 0 及以后始终启用 | 当前 Production Final Gate、Gateway、Job 恢复、来源关联、硬门禁、部署安全、可观测性 |
| P0.5 / Data Readiness | Phase 0.5 及以后 | Source/Fact 治理、公开使用许可、eligible Evidence 基线 |
| P1 / Website MVP | Phase 1 及以后 | Brief/Evidence/Website、基础 Claim 映射、迁移/RLS、制品完整性 |
| P2 / Variant & Delivery | Phase 2 及以后 | 完整 Claim entailment、Golden/Adversarial、Variant invariant、Delivery restore |
| P3 / Approval & Skill | Phase 3 及以后 | Skill 发布/回滚、客户审批、maker-checker、授权可见性 |
| P4 / Publication & Learning | Phase 4 及以后 | Publication aggregate、反馈归因、实验隔离、闭环重测 |
| P5 / Connectors | Phase 5 | OAuth、draft-only、dry run、撤回和失败补偿 |

每次发布只要求“Base + 当前已启用阶段及此前阶段”的 profile 全部通过。门禁清单如下：

```text
[Base] 当前基础 Production Final Gate 在最新代码上通过
[Base] 所有已提供的 action/report/retest/source gap 存在、类型正确且属于同一 project；Manual Brief 的审计来源完整
[Base] Qdrant project/status/version 过滤通过
[Base] 统一 Gateway call log/token/cost 通过
[Base] Provider Capability Registry 和 Job 总调用/成本预算通过
[Base] Job request idempotency/execution fingerprint/retry/regenerate/replay 通过
[Base] Knowledge 8 类 Job + Collection 的 active-lease CHECK、expired-first 逐表公平 reclaim、heartbeat、stale-token fencing、cancel 线性化、max-attempt DLQ 和 actor kill/recovery live test 通过；持续前序表 backlog + 受限 `max_jobs` 不能饿死后序表 expired row
[Base] Fact lifecycle status 与 review_status 映射在真实数据库上通过
[Base] Prompt Injection/secret 和未授权 PII 泄露 hard block；PII 分类、脱敏及 Model Policy enforcement 通过
[Base] internal export/customer delivery/publication eligibility 三种资格守卫通过
[Base] Phase 0 publication guard 的 inline claim completeness 绑定 exact hash，且不伪造 coverage
[Base] Legacy GET export 无 publication 副作用；只有显式 publication request 创建 distribution
[Base] 最小 Content bootstrap、legacy typed DTO/generated types、稳定错误和 exact-hash inline review 通过
[Base] Phase 0 Admin 的 Export/标记待发布/URL 管理在 desktop/mobile 可区分且可操作
[Base] Invitation preflight/redeem 在真实 FORCE RLS 下通过；surface mismatch 零副作用、并发单次消费、Session 创建失败 rollback、连接 context 不泄漏
[Base] redeem commit 后响应丢失、同 key 并发和乱序响应都字节等价重放同一 Session delivery；不 rotate/revoke，TTL/replay limit/confirmation/secret erasure 通过
[Base] auth_surface_policy_v1 与 stale-policy invalidation 通过；analyst Admin 可登录但不越权，viewer Admin mismatch 后仍可 Customer redeem
[Base] Project 父 UNIQUE、Member/Invitation/Grant tenant 复合 FK/NOT NULL 的 fresh/dirty-upgrade/rollback 通过，伪造 project/tenant mismatch 被数据库拒绝
[Base] Auth 应用回滚在旧 binary + 新 schema 下双层禁用全 Auth/Member/Invitation mutation，不签发 v1 Session、不触发 tenant NOT NULL 500，只能 forward-fix 后重开
[Base] tenant-role Grant 与 Project/role 变更同事务；RLS helper owner/body/ACL/search_path 通过，tenant admin 无显式 Member 仍只可访问同 tenant 授权项目
[Base] Session v2 包含同 tenant 完整 direct/grant project scopes，Admin/Customer server-side surface projection 和逐项目 RBAC/RLS 无 role bleed，多项目 E2E 通过
[Base] queue/model/QA/review/cost Prometheus 指标可抓取
[Base] 所有 production profiles 的 merged config 无开发对象存储凭据，root/application/backup 身份分离且 consumer fingerprint 一致
[Base] non-default embedded MinIO bootstrap 后 API/Collector/Report/Knowledge/Dramatiq put/get/head/hash、CreateBucket/policy negative 通过；backup smoke 只在当次 run prefix 可写读删，正式 backup/跨 run delete 被拒绝，ephemeral restore 通过
[Base] MinIO/backup 加密卷 receipt、key lifecycle 和 encrypted snapshot 新节点恢复通过
[Base] 所有适用 artifact 新鲜且绑定当前 commit
[Base] git diff --check 通过

[P0.5] rollout project/channel 的 source/fact 治理盘点完成
[P0.5] governance additive migration 的 fresh upgrade/rollback/RLS/审计行为通过
[P0.5] eligible_source_asset_count > 0
[P0.5] eligible_approved_fact_count 满足 Website Golden Set 输入要求
[P0.5] unknown_usage_rights 均有 owner、期限和处置计划
[P0.5] readiness summary/items/PATCH API 与 Admin queue E2E 通过
[P0.5] Website Evidence eligibility dry-run hard block=0，且 artifact 绑定输入/规则/output hash

[P1] 空库安装和从 0028 升级迁移均通过
[P1] legacy/new read model 数量与 hash 对账
[P1] 所有 project_id 新表自动纳入 RLS inventory
[P1] Content CRUD RLS negative + composite FK/typed FK 数据库行为测试通过
[P1] Evidence Job active unique/Attempt 分配/selected Pack constraint trigger、判别 Item、validity/conflict/rights gate 通过
[P1] Claim inventory recall/completeness + support/public citation gate 通过
[P1] Claim mapping 只能引用 Draft 冻结的同一 Evidence Pack
[P1] Evaluation Job 可查询/恢复并绑定 exact Version/hash；QA gate 不冒充 Job partial success
[P1] Asset 人工编辑新版本、旧审批失效和历史 lineage 通过
[P1] canonical JSON/renderer/content hash 可复现，客户端 rendered preview 不一致返回 422
[P1] Prompt Bundle 独立路径和 manifest URI/hash 通过
[P1] Prompt Bundle 仅从 selected ready Pack 编译，Generation 在模型调用前拒绝 stale/非 selected Pack
[P1] OpenAPI generated types、bootstrap/read lists、head/version ETag、412、统一 Job 轮询和稳定错误 UI 通过
[P1] Website 基础 Golden Set 通过（结构、引用映射和基础质量）
[P1] Markdown/HTML/manifest package hash 通过
[P1] Website desktop/mobile Playwright 通过

[P2] Claim-level Golden/Adversarial 通过
[P2] Variant 不引入新事实检查通过
[P2] Asset workflow 与 Delivery 状态完全分离
[P2] Internal/Customer package 隔离、hash 和 MinIO backup/restore 通过
[P2] 三渠道 desktop/mobile Playwright 通过

[P3] Skill release/diff/rollback 可复现
[P3] Skill Compile Job list/detail/retry/replay 与 Template Release result lineage 通过，compile/release 分离
[P3] Internal + Customer approval 策略通过
[P3] maker-checker、授权可见性和审批 SLA E2E 通过
[P3] Customer generated DTO 不含 Prompt、内部 notes、机密 Evidence、PII/security findings，泄漏负测通过
[P3] comment/request changes/accept 绑定 exact Version/hash，hash 冲突 fail closed
[P3] revoked/superseded Package 的授权下载失败，Customer desktop/mobile E2E 通过

[P4] 发布 URL/平台 ID 回填绑定精确版本
[P4] 反馈、实验和 GEO retest 归因通过

[P5] OAuth 最小权限、secret rotation 和租户隔离通过
[P5] draft-only 默认、双审批和 dry run 通过
[P5] connector 幂等、重试补偿、撤回和审计 E2E 通过
```

禁止：

- 用旧 artifact；
- 用静态 source contains 代替 live behavior；
- 删除失败门禁；
- 放宽 freshness；
- 使用 `--skip-live/--skip-qdrant/--skip-heavy-components` 宣称 production pass；
- accepted risk 绕过安全、隐私、追踪、Claim 或审批。

---

## 26. 分阶段实施

### Phase 0：稳定现有 Content v0

目标：修复当前薄闭环，不新增大规模产品功能。

工作：

1. 内容生成迁移到统一 LLM Gateway；
2. 正确传递 primary brand/category/tone，并在 input snapshot 固定 allowed subject entity/role，禁止第一条 Fact subject 充当品牌；
3. API 支持明确 fact/chunk filter，并完整持久化到 pipeline metadata、Content Job 字段和冻结 input snapshot；
4. 对所有已提供的 `source_action_id/source_report_id/source_retest_id/source_gap_id` 校验对象存在、类型正确且属于同一 project；Manual Brief 则强制校验 `source_type/reason/manual_source_refs` 审计来源；
5. active fact 增加 `valid_from/valid_until` 检查；
6. 修复 Fact Review 双状态：生成只读取 `status=active AND review_status=approved`；`approved -> active`、`pending_review/rejected -> archived`（明确禁止时为 `forbidden`）、`archived -> archived`，并以真实 PostgreSQL 测试覆盖 CHECK；
7. 生成响应增加过渡期内联结构：`claim_text + 当前 approved fact/active chunk ID`；Phase 0 不新增 Claim 表、不把“有 ID”误判成 entailment，但 publication request 前 reviewer 必须对 exact hash 确认 `inline_claim_inventory_complete`；
8. 补齐 Prompt Injection、未经授权 PII、secret、traceability 和三种资格检查，集中进入统一 guard；
9. Legacy `GET export.md` 保持无业务副作用；内部 Export 只写 download/export audit，不改变 Asset 或 Distribution；
10. 新增显式“标记为待发布”API/UI；只有授权用户点击且 publication eligible 时，才以 `draft_id + immutable content_hash + channel + destination` 幂等创建 `awaiting_url_backfill`；
11. Job 增加 request idempotency、execution fingerprint、input snapshot 和总模型调用/成本预算；
12. 为 Knowledge 8 类 Job 和 Collection Job 实现统一 expired-running/finalizing 原子接管、expired-first 逐表公平 recovery pass、LeaseGuard heartbeat、token fencing、cancel、DLQ 和 attempt-scoped 幂等；Content retry/regenerate/operator replay 保持独立语义；
13. 新旧生成路径兼容和 deprecation；
14. content queue/worker/model/QA 指标；
15. 收口 production 对象存储：Phase 0 只支持 `embedded_minio`、root/application/backup + ephemeral restore 身份、加密卷、MinIO bootstrap、关闭 runtime auto-create、完整 consumer 配置传播、merged-config contract 和 non-default live/policy/restore smoke；
16. Admin v0 工作台拆分 Export、Publication Request 和 URL 管理，并补轮询、错误码和 desktop/mobile E2E；
17. Phase 0 同步交付最小 Content bootstrap、legacy typed DTO/generated types、稳定错误 envelope 和 exact-hash inline Claim review；
18. 原子化 Invitation preflight/redeem + 短时加密的同 key Session delivery replay + Session scope v2；移除 viewer 全局唯一，增加 Member/Invitation tenant 复合 FK 和 tenant-role Grant/RLS anchor，Admin/Customer BFF 改为稳定 recovery key、typed surface capability 和逐项目 scope；
19. 重跑 Base / Content v0 Production Final Gate。

退出条件：

- 当前已有内容路径全链 live pass；
- 内部 Export、客户交付和 Publication Eligibility 不再共用一个布尔状态；
- Export/Approve/Delivery 不会产生 manual distribution，显式 publication request 才会；
- crash/retry 不产生重复 draft；
- kill -9 Knowledge/Collection worker 后无永久 running Job，旧 lease token 不能写 terminal/result；前序表持续 backlog 时后序表 expired Job 仍在 2 个 recovery interval 内被接管；
- 所有结构化来源关联均通过存在性、类型和同 project 校验，Manual Brief 审计来源完整；
- Fact Review 的所有允许决策在最新数据库约束下可执行，生成链不会读取未批准事实；
- Gateway 有可核验 Token/成本；
- Phase 0 Content UI 可显示 Job、hard-gate blocked reason、correlation ID 和显式发布意图；
- Phase 0 Content UI 通过 bootstrap/legacy typed DTO 加载，inline Claim review 对 hash 冲突 fail closed；
- production 使用非默认 MinIO root/application/backup principal，所有 runtime consumer 完成跨服务 artifact roundtrip 且无越权；application/backup `CreateBucket` 被拒绝，加密 volume receipt 和 encrypted snapshot restore 通过；
- viewer 从 Admin 入口提交不会消费 Invitation，正确 Customer 入口仍可兑换；兑换响应丢失可用稳定 key 重放同一 Cookie；analyst 可进入 Admin 但只能执行其逐项目 permissions；tenant admin 无显式 Project Member 时可访问同 tenant Grant，但不能跨 tenant；surface-projected 多项目 selector 完整且角色不串权；
- Base / Content v0 Production Final Gate Green。

### Phase 0.5：Evidence Data Readiness Slice

目标：在 Phase 1 开发完成前证明至少有一组真实、可授权、可公开使用的 Evidence，不用 unknown 默认放行。

工作：

1. 先发布 Source Asset/Fact governance additive migration：可空列、枚举/check、索引、RLS 和审计字段；
2. 按 rollout project、publication channel、source type 统计 Source Asset/Fact/Chunk；
3. 批量回填 authority、confidentiality、usage rights、allowed channels、consent 和主体实体；
4. 把 `unknown/冲突/过期/无授权` 进入带 owner、SLA、reason 的人工治理队列；
5. 输出 eligibility 报告和 Website Golden Set 所需证据覆盖；
6. Admin Content Studio 通过 summary/items/PATCH API 展示 Data Readiness banner、缺口和治理入口；
7. 旧 implicit Evidence Pack 只补历史 lineage，不得绕过 `usage_rights=unknown` fail closed；
8. 清理异常后收紧公开生成所需 CHECK/NOT NULL，并运行 upgrade/rollback/RLS 行为测试。

退出条件：

- `eligible_source_asset_count > 0`；
- `eligible_approved_fact_count` 满足 Website Golden Set 的主题/主体要求；
- 所有 `unknown_usage_rights` 有 owner 和处置日期；
- 对 Website Golden Set 执行不写入 Phase 1 对象的 Evidence eligibility dry-run：主题/主体覆盖满足阈值、所有引用可解析、hard block 为 0，并输出可复现 input/output hash；
- P0.5 Gate Green。

### Phase 1：Evidence-constrained Website MVP

范围：

- ActionRecommendation/Source Gap 投影 Opportunity；
- 版本化 Brief；
- primary/compared/allowed subject entity 关系表与 Claim/Evidence 主体校验；
- Durable Evidence Pack Job + 不可变 Attempt + 判别 Item；
- Prompt Bundle；
- Website Canonical Article/Answer Page；
- `content_draft_versions`；
- Asset 人工编辑创建新 Version；
- 基础 Claim extraction/mapping + inventory completeness；
- Durable Evaluation Job + exact Version/hash QA 结果；
- 复合 FK、typed FK、RLS 和独立 Prompt Bundle path；
- Admin bootstrap、Work Queue、Evidence Inspector 和 typed read APIs；
- Markdown + HTML + manifest。

内容类型：

```text
answer_page
comparison_guide
faq
local_au_guide
```

Case Study 在客户授权合同完成前不进入 MVP。

退出条件：

- Claim inventory 由 reviewer 确认完整，每个公开事实 Claim 有 Evidence Item 并确认为 supported；inference 只允许非事实性文本；
- Brief/Evidence/Prompt/Asset/Review 链路由同项目复合 FK 约束；
- Claim/Evidence mapping 只能引用该 Asset Version 冻结的同一 Pack；
- Evidence retry 创建新 Attempt，Asset 编辑创建新 Version，旧审批自动失效；
- Admin 使用生成 OpenAPI 类型，不再消费未类型化 Content record；
- Evidence stale 能传播到 Asset；
- Website Golden Set 通过；
- migration/RLS/backup/live E2E 通过。

### Phase 2：Canonical、Variant、QA 与 Delivery

范围：

- LinkedIn Post；
- YouTube Script；
- Canonical/Variant invariant；
- 完整 Claim-Evidence entailment；
- 多维 scorecard；
- Delivery Package；
- 可选独立 content actor。

退出条件：

- Variant 不引入新事实；
- 三渠道 Golden Set 和对抗集通过；
- Delivery package hash/restore 通过；
- Asset workflow 不包含 exported/delivered，Delivery 使用独立 Job/Package 状态；
- 若启用独立 content actor，必须证明其可独立扩缩容且不影响 knowledge SLA；未启用时，必须验证共享队列的隔离指标、并发上限和预算不会挤占 knowledge workload。

### Phase 3：产品化 Opportunity、Skill 和客户审批

范围：

- 一等 Opportunity 生命周期和排序；
- Content Opportunity Board；
- Skill Registry/Resolver/Release Assignment；
- Skill Version -> Compiler -> immutable Template Release 迁移；
- Skill diff、灰度、回滚；
- Durable Skill Compile Job、Template Release result lineage 和恢复；
- Customer Deliverables；
- comment/request changes/acceptance；
- maker-checker。

退出条件：

- 客户只能看到授权且内部批准的精确版本；
- Customer Web 只消费 customer-safe typed DTO，comment/request changes/acceptance 绑定 exact version/hash；
- Skill rollback 可复现；
- Skill Compile Job 可查询/retry/replay，compile succeeded 与 release action 分离；
- Skill source、Template Release 和 Prompt Bundle lineage 可见；
- customer acceptance 不覆盖 internal approval；
- 审核 SLA 和权限 E2E 通过。

### Phase 4：Publication 与反馈实验

范围：

- publication record；
- content-level GEO retest；
- Search Console/analytics signals；
- Skill A/B；
- cost/quality/outcome dashboard。

退出条件：

- 反馈关联同 query/provider/market/city/device 口径；
- UI 明确“相关性观察”；
- experiment 有最小样本和停止规则；
- 删除/撤销传播通过。

### Phase 5：发布连接器

最后考虑：

- WordPress；
- Webflow；
- Shopify；
- LinkedIn；
- YouTube；
- Google Business Profile。

必须先完成 OAuth 最小权限、draft-only 默认、双审批、dry run、撤回和失败补偿。

---

## 27. Feature Flag、迁移与回滚

建议：

```text
GEO_CONTENT_V1_ENABLED
GEO_CONTENT_DATA_READINESS_ENABLED
GEO_CONTENT_CLAIM_QA_ENABLED
GEO_CONTENT_VARIANTS_ENABLED
GEO_CONTENT_DELIVERY_ENABLED
GEO_CONTENT_CUSTOMER_APPROVAL_ENABLED
GEO_CONTENT_SKILLS_ENABLED
GEO_CONTENT_PUBLICATION_REQUEST_ENABLED
GEO_CONTENT_AUTO_PUBLICATION_ENABLED=false
```

API bootstrap 一一投影为：

```text
GEO_CONTENT_V1_ENABLED                  -> content_studio_v1
GEO_CONTENT_DATA_READINESS_ENABLED      -> content_data_readiness_v1
GEO_CONTENT_CLAIM_QA_ENABLED            -> content_claim_qa_v1
GEO_CONTENT_VARIANTS_ENABLED            -> content_variants_v1
GEO_CONTENT_DELIVERY_ENABLED            -> content_delivery_v1
GEO_CONTENT_CUSTOMER_APPROVAL_ENABLED    -> content_customer_deliverables_v1
GEO_CONTENT_SKILLS_ENABLED               -> content_skills_v1
GEO_CONTENT_PUBLICATION_REQUEST_ENABLED  -> content_publication_request_v1
GEO_CONTENT_AUTO_PUBLICATION_ENABLED     -> content_auto_publication
```

`content_auto_publication` 默认且持续为 false，直到 Phase 5 connector gate 单独批准。bootstrap 同时返回 actor/project capabilities、available actions 和 schema version。前端 env 只能作为全局 kill switch，不能单独开启后端未启用能力。每个 flag 必须有 owner、默认值、上线/回滚条件和删除日期；隐藏 UI 不改变 API 授权或 Gate。

合法依赖与降级合同：

| Bootstrap flag | 首次阶段 | 前置依赖 | 阶段默认 | 依赖不满足时 |
| --- | --- | --- | --- | --- |
| `content_studio_v1` | Phase 1 | Base + P0.5 Gate | false，按项目灰度 | `legacy_mode=true`，只显示 v0 actions |
| `content_data_readiness_v1` | Phase 0.5 | 最小 bootstrap + governance migration | false，rollout project 开启 | 隐藏治理 mutation，显示 readiness unavailable |
| `content_claim_qa_v1` | Phase 1 | studio + readiness Gate | false | 所有 Claim QA action fail closed |
| `content_variants_v1` | Phase 2 | studio + claim QA | false | 只显示 Canonical |
| `content_delivery_v1` | Phase 2 | studio + Claim/Review Gate | false | 禁止创建 Package/客户下载 |
| `content_customer_deliverables_v1` | Phase 3 | delivery + internal approval + customer-safe DTO | false | Customer Content 路由 404，不泄露存在性 |
| `content_skills_v1` | Phase 3 | studio + compiler/template lineage | false | 继续使用 system Template Release，只读 lineage |
| `content_publication_request_v1` | Phase 0 | 最小 bootstrap + publication eligibility guard | Base Gate 后对 rollout project 为 true | 只允许 Export，不创建 distribution |
| `content_auto_publication` | Phase 5 | publication request + connector/P5 Gate | 始终 false，逐 connector 审批 | 保持人工发布 |

配置加载时先校验依赖；非法组合不得原样下发。bootstrap 将无效 flag 计算为 false，并在 `flag_blocked_reasons` 返回稳定 reason code，同时记录告警/audit；前端只消费 effective flags，不实现第二套依赖求值器。

对象存储身份一致性、Knowledge/Collection lease recovery 和 Invitation/Session scope v2 属于 Base 安全/可靠性合同，不受任何 Content feature flag 控制；关闭 Content UI 不能掩盖这些基础缺陷。

迁移顺序：

1. Phase 0 先修 production object-store overlay/bootstrap/consumer inventory，在非默认凭据 live smoke Green 前不启动内容 rollout；
2. 停领/drain 旧 Knowledge/Collection consumer，添加 lease token/heartbeat/status/index，处理遗留 active row，再以新 LeaseGuard consumer 恢复领取；
3. 按 §22.7 完成 Auth additive migration：父表 `(id, tenant_id)` UNIQUE -> Member/Invitation/Grant tenant 回填 -> NOT VALID 复合 FK/CHECK -> VALIDATE -> NOT NULL -> tenant-role Grant/RLS anchor -> scope-v2/加密 redemption ledger；回填或 revoke v1 Session，删除 viewer global unique、建立 project-scoped unique，完成 dirty-upgrade 对账后才切换原子 redeem/BFF 并开放登录；
4. Phase 0.5 为 Source Asset/Fact 增加 governance 可空列、枚举/check、索引和 RLS policy；
5. 批量分类/回填、分配 owner、清理冲突并通过 Data Readiness Gate，再收紧公开生成所需约束；
6. Phase 1 添加新内容表/可空列、父侧 UNIQUE、引用侧索引、RLS；
7. 新代码兼容旧数据；
8. 从旧 content_drafts 回填 version 1；
9. 回填 typed source/subject relation 和 project_id，清理 cross-project/unknown row；
10. 以 `NOT VALID` 添加历史复合 FK，验证后 `VALIDATE CONSTRAINT`；
11. 回填 Brief current-version deferred FK 和 selected ready Pack，并启用 deferred constraint trigger；
12. 旧请求生成 implicit Brief/Evidence Pack，但不绕过 rights fail closed；
13. 生成 OpenAPI TypeScript 类型和 UI fixture；
14. shadow read 和数量/hash 对账；
15. 开启内部项目、少量客户并观察指标后默认开启；两个发布周期后再移除 legacy write，物理删表必须单独 ADR。

回滚：

- 关闭 feature flag；
- 保持 additive schema；
- legacy API 仍可读；
- 新 worker 停止领取新类型 Job；
- lease migration 回滚前必须 drain 新 token owner，旧 worker 不得与新 worker 并行；
- Auth code 回滚按 §22.7 fail closed：edge/gateway 禁用全 Auth/Member/Invitation mutation，rollback DB role 撤销 Member/Invitation/Session/Grant/Ledger 写权，revoke 不兼容 Session，保持 tenant 复合 FK/NOT NULL、Grant 和 ledger additive schema；旧 auth route 不得重开，也不得恢复 viewer global unique index；
- object-store credential rollback 使用受控 secret rotation，不回退开发默认；
- 已生成 artifact 不删除；
- 记录 rollback audit；
- 回滚后运行旧路径回归和数据对账。

---

## 28. 主要风险

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 双真源 | 状态和内容不一致 | 复用现表、兼容投影、禁止长期双写 |
| Export 被误计为发布意图 | 虚假任务和 publication rate | 显式 Publication Request；Legacy GET export 无副作用 |
| 事实选择错误 | 竞品/市场事实被当品牌 | 显式 brand/entity/filter + Evidence Pack |
| Claim 漏抽取 | coverage 虚高并绕过 gate | inventory completeness review + extraction recall Golden Set |
| 过期事实 | 对外错误 Claim | validity guard + stale propagation |
| Gate 被绕过 | 不安全内容导出 | 单一 publishability service |
| Provider 直连 | 无成本/审计/熔断 | 统一 Gateway |
| Job 重复 | 重复内容和费用 | idempotency + lease reclaim + transactional result |
| expired-running 永久卡住、跨表饿死或旧 worker 覆盖 | Pipeline/Collection 停滞或重复结果 | expired-first 逐表公平 reclaim + heartbeat + fencing token + CAS terminal + DLQ |
| production 对象存储身份不一致 | API/worker 无法读写或暴露弱 root 凭据 | root/app/backup 分离 + 全 consumer 传播 + merged/live Gate |
| Invitation 错入口被消费 | 用户无法登录正确门户 | redeem 持锁校验 requested surface，mismatch 零副作用 |
| Invitation 兑换响应丢失/乱序 | 旧 Cookie 覆盖新 generation 或一次性 token 无法恢复 | 同 key 字节等价重放同一加密 Session delivery + TTL/replay/confirmation/erasure |
| 多项目 Session 角色串权 | A 项目管理员越权管理 B 项目 | scope-v2 逐项目 roles/permissions；flat roles 禁止授权 |
| tenant admin 仅有 Session scope 无 RLS grant | 同 tenant 项目误拒绝，或 repository 特判导致越权 | 事务化 Project Grant + 统一 FORCE RLS helper + 跨 tenant negative |
| Prompt Injection | 指令劫持/泄密 | untrusted evidence zone + no tools + post-check |
| 跨项目泄漏/脏引用 | 严重安全事件或不可见脏数据 | project RLS + composite FK + typed FK + Qdrant filter + DB negative |
| 版权/授权缺失 | 法律和客户风险 | usage rights + consent gate |
| 旧数据全部 fail closed | Phase 1 无可用 Evidence | Phase 0.5 Data Readiness、owner/SLA、eligible 基线 |
| Skill 漂移 | 风格/质量退化 | immutable version + Golden Set + rollback |
| 过早自动发布 | 品牌事故 | manual export 默认，auto publication flag 永久默认 false |
| 指标伪因果 | 错误产品结论 | 同口径复测，只展示关联 |
| 代码热点与知识集中 | API 主入口和 contract tests 同时是高频变更/修复热点，Git 历史仅 1 位提交者 | 新功能拆独立模块、ADR/状态表/迁移说明入库、关键路径由 DB behavior + contract + E2E 多层门禁固化 |

---

## 29. 待决问题与建议默认值

| 问题 | 建议默认 |
| --- | --- |
| Phase 1 是否支持多个渠道 | 只支持 Website Canonical |
| LinkedIn/YouTube 何时进入 | Phase 2，Claim QA 稳定后 |
| Customer 是否可最终批准发布 | 只能 acceptance；内部 approval 仍必须存在 |
| 高风险行业是否进入 MVP | 否 |
| Opportunity 是否立即独立建表 | 否，先投影 ActionRecommendation |
| Projection ID 如何表达 | 使用服务端解析的 `type:uuid` opportunity_ref，不暴露表假设 |
| 是否立即拆 content worker | 否，先抽 handler 和修可靠性；达到隔离触发条件再拆 |
| 是否新建多个 Qdrant collection | 否 |
| 是否自动发布 | 否 |
| Export 是否创建待发布任务 | 否；只有显式 Publication Request |
| Prompt 全文存哪里 | MinIO 受控快照，DB 存 URI/hash/metadata |
| Content Asset 是否新建平行主表 | 否，先演进 content_drafts + immutable versions |
| Skill 是否支持跨项目共享 | Phase 3；system/tenant/project scope |
| Template 与 Skill 谁是真源 | Skill 是规则源，Template Release 是不可变编译产物 |
| 内容是否可回灌知识库 | 只有重新经过独立 fact extraction + human review，绝不自动 |

这些默认值需由产品、工程、安全和交付负责人共同确认后进入 Approved 状态。

---

## 30. Definition of Done

一个 Content v1 功能只有同时满足以下条件才能标记 Done：

1. 需求、schema、状态、权限和失败语义已文档化；
2. 现有数据兼容和回滚路径存在；
3. 单元、repository、API、worker、security 和 E2E 测试通过；
4. fresh install 与 upgrade migration 通过；
5. project RLS CRUD negative 通过；
6. same-project composite FK/typed FK 数据库 negative 通过；
7. Qdrant/MinIO/Valkey/PostgreSQL/真实模型联合运行通过；
8. artifact 绑定当前 commit 且未过期；
9. Claim inventory completeness 和 hard gate 不可绕过；
10. Export 无发布副作用，Publication Request 必须显式；
11. metrics、alerts、backup/restore 可验证；
12. OpenAPI generated types、稳定错误和 Admin desktop/mobile 通过；
13. Customer 权限路径通过（若本阶段包含）；
14. Phase 1 前 Data Readiness Gate 通过；
15. Production Final Gate 通过；
16. production object-store identity coherence、Durable Job lease recovery、Invitation stable replay 和 Member/Grant-backed Session scope-v2 Base Gate 通过；
17. 没有把 “代码存在” 误写成 “客户可投产”。

---

## 31. 最终目标架构

```text
Admin Web / Customer Web
          |
       FastAPI
          |
  +-------+-------------------------------+
  |                                       |
GEO Analysis Domain             Content Generation Domain
  |                                       |
Collection / Analysis            Opportunity / Brief
Score / Citation / Gap           Evidence Pack / Skill
Action / Report / Retest         Prompt Bundle / Model Policy
  |                              Canonical / Variant / Claim Inventory / QA
  +---------------+-----------------------+
                  |
            Knowledge Domain
                  |
 Source Asset / Parser / Chunk / Approved Fact
                  |
 PostgreSQL / Qdrant / MinIO / Valkey-Dramatiq
                  |
 Audit / Trace / Review / Metrics / Backup
```

Content 输出侧边界：

```text
Asset Version -> Export Event
Asset Version -> Delivery Job/Package
Asset Version -> explicit Publication Request -> Manual Distribution/Publication
```

本方案最重要的五个不变量：

1. **文案系统消费经过治理的事实，不创造事实。**
2. **每个公开 Claim 都能回到冻结证据和精确版本。**
3. **任何新能力都必须沿用项目现有的 Job、RLS、Audit、Trace 和 Production Gate，而不是另建一套表面完整、实际脱节的系统。**
4. **项目拥有对象之间的引用必须由包含 project_id 的数据库约束保证同项目；RLS 不能代替关系完整性。**
5. **Export 和 Delivery 永远不隐含发布意图；只有授权用户的显式 Publication Request 才能创建待发布记录。**

---

## 32. 现有实现证据索引

本索引用于支持第 2 节的现状判断。行号以 2026-07-12 当前工作区为基线，后续代码调整时应同步刷新。

### 32.1 项目状态与门禁

| 结论 | 证据 |
| --- | --- |
| 仓库已经从文档规划进入工程实现 | `README.md:1-15` |
| 知识流水线、GEO 文案生成、审核和导出已经落地 | `docs/GEO-当前项目进度汇报-2026-07-10.md:9-23` |
| 当前不能宣称 Production Final Gate 通过 | `docs/GEO-当前项目进度汇报-2026-07-10.md:25-27` |
| 最新代码仍需 DB/RLS/MinIO/Qdrant/worker/Playwright/backup 联合验收 | `docs/GEO-当前项目进度汇报-2026-07-10.md:102-116` |
| 总门禁入口 | `Makefile:363-364` |

### 32.2 GEO、知识与内容数据

| 能力 | 证据 |
| --- | --- |
| Source Gap 与 Action Recommendation 领域模型 | `packages/geo_core/geo_core/models.py:522-568` |
| active fact、有效期和 ContentDraft 领域模型 | `packages/geo_core/geo_core/models.py:597-610,816-833` |
| project-scoped `brand_entities` | `infra/db/migrations/up/0001_init.sql:673-681` |
| 初始 `content_drafts` 和 `manual_distribution_records` | `infra/db/migrations/up/0001_init.sql:285-325` |
| Legacy knowledge application jobs/candidates | `infra/db/migrations/up/0021_knowledge_application.sql:60-129` |
| durable `content_generation_jobs` | `infra/db/migrations/up/0023_knowledge_pipeline_orchestration.sql:453-483` |
| content draft 的 pipeline、chunk、citation 和 status 扩展 | `infra/db/migrations/up/0023_knowledge_pipeline_orchestration.sql:485-496` |
| `knowledge_trace_refs` | `infra/db/migrations/up/0023_knowledge_pipeline_orchestration.sql:498-515` |
| generation/security/traceability/publish gate 定义 | `infra/db/migrations/up/0023_knowledge_pipeline_orchestration.sql:613-624` |
| knowledge/content 表的 project RLS | `infra/db/migrations/up/0023_knowledge_pipeline_orchestration.sql:626-699` |
| content summary/risk、target audience/action 和 template 扩展 | `infra/db/migrations/up/0028_knowledge_pipeline_production_contract.sql:120-184` |
| Fact lifecycle CHECK 只允许 active/superseded/archived/forbidden | `infra/db/migrations/up/0027_knowledge_pipeline_consolidation.sql:8-12` |

### 32.3 API 与权限

| 能力 | 证据 |
| --- | --- |
| 当前可持久化 ProjectRole 只有 owner/admin/analyst/viewer | `packages/geo_core/geo_core/models.py:10,80-86` |
| 更细 RBAC role/permission vocabulary 已定义但未完全贯通成员模型 | `packages/geo_core/geo_core/rbac.py:17-211` |
| Content generation request 字段 | `apps/api/geo_api/main.py:2647-2661` |
| 内容生成 Job API 与项目管理权限 | `apps/api/geo_api/main.py:10762-10820` |
| Content Draft review API | `apps/api/geo_api/main.py:9493-9529` |
| Draft list 和 Markdown export API | `apps/api/geo_api/main.py:10854-10895` |
| Human review list/queue/save API | `apps/api/geo_api/main.py:7436-7572` |
| Action/Report/Retest ID 与 Source Gap 类型标签写入 Job metadata | `apps/api/geo_api/main.py:10787-10801` |
| Runtime Fact Review 仍可能把 rejected/pending_review 写入 lifecycle status | `packages/geo_core/geo_core/repository.py:16225-16250` |
| 邀请兑换当前按 invitation project 缩窄 membership scope | `apps/api/geo_api/main.py:5260-5264` |
| Session 当前只有 project_ids + flat roles/permissions | `infra/db/migrations/up/0016_runtime_sessions.sql:1-20` |
| viewer Member/Invitation 当前被全局唯一索引限制 | `infra/db/migrations/up/0015_customer_portal_launch_access_logs.sql:33-39` |

### 32.4 Worker、生成和质量门禁

| 能力或缺口 | 证据 |
| --- | --- |
| active fact + active embedded chunk 筛选 | `workers/knowledge_worker/run_knowledge_pipeline.py:2039-2089` |
| 当前 Content Job handler | `workers/knowledge_worker/run_knowledge_pipeline.py:2324-2583` |
| 当前固定 brand/category、top facts 和 direct DeepSeek 调用 | `workers/knowledge_worker/run_knowledge_pipeline.py:2324-2351` |
| forbidden substring、citation count 和 risk flags | `workers/knowledge_worker/run_knowledge_pipeline.py:2376-2387` |
| 草稿 fact/chunk/citation_refs 写入 | `workers/knowledge_worker/run_knowledge_pipeline.py:2392-2433` |
| Action/Report/Retest trace；Source Gap 只有类型 metadata | `workers/knowledge_worker/run_knowledge_pipeline.py:2456-2490` |
| generation/security/traceability gate 执行 | `workers/knowledge_worker/run_knowledge_pipeline.py:2535-2576` |
| content job enqueue 和 target action 映射 | `packages/geo_core/geo_core/knowledge_pipeline.py:3002-3114` |
| 已批准草稿导出守卫 | `packages/geo_core/geo_core/knowledge_pipeline.py:2716-2757` |
| 内容审批时重新检查 active facts/chunks/risk flags | `packages/geo_core/geo_core/repository.py:14579-14666` |
| manual distribution 回填与审计 | `packages/geo_core/geo_core/repository.py:14669-14744` |
| Knowledge child Job claim 当前只领取 queued，complete/fail 无 lease CAS | `packages/geo_core/geo_core/knowledge_pipeline.py:3364-3455` |
| Collection Job claim 当前只领取 queued，complete/fail 无 lease CAS | `packages/geo_core/geo_core/collection_jobs.py:153-228` |
| recovery dispatcher 当前只重发 actor | `workers/task_queue/run_recovery_dispatcher.py:17-25` |

### 32.5 模型与任务基础设施

| 能力或缺口 | 证据 |
| --- | --- |
| 通用 `LLMGateway` Protocol | `packages/geo_core/geo_core/contracts.py:41-51` |
| LiteLLM retry、Token、成本、延迟和 call log | `packages/geo_core/geo_core/llm_gateway.py:142-345` |
| 当前 DeepSeek 内容生成直连与 JSON retry | `packages/geo_core/geo_core/knowledge_application.py:438-599` |
| Task actor 只有 collection/knowledge/report | `packages/geo_core/geo_core/task_queue.py:8-13` |
| knowledge Dramatiq actor | `workers/task_queue/tasks.py:123-152` |
| PostgreSQL/MinIO/Qdrant/Valkey 基础设施 | `infra/docker-compose.yml:1-95` |
| knowledge worker 与 embedding API | `infra/docker-compose.yml:436-510` |
| production overlay 当前只向 API 覆盖对象存储凭据 | `infra/docker-compose.production.yml:2-14` |
| base MinIO 与多个 consumer 当前使用开发默认凭据 | `infra/docker-compose.yml:68-73,139-153,254-337,407-571` |

### 32.6 前端与测试

| 能力或缺口 | 证据 |
| --- | --- |
| Admin Content Workbench | `apps/admin-web/app/projects/[project_id]/ProjectActions.tsx:2489-2640` |
| Admin 内容审核 action | `apps/admin-web/app/projects/[project_id]/actions.ts:1685-1721` |
| Admin Content 唯一入口为 operations/content tab | `apps/admin-web/app/projects/[project_id]/page.tsx:1465-1477` |
| Customer Web 当前只加载 score/evidence/report/action/trace | `apps/customer-web/app/runtime.ts:165-176` |
| 前端组件栈 ADR | `decisions/0010-frontend-component-stack.md:15-31` |
| 前端生成、审核、Markdown 下载生命周期 | `scripts/run_frontend_knowledge_lifecycle_smoke.py:291-328` |
| 当前本地 knowledge eval 只有三类核心检查 | `scripts/run_promptfoo_knowledge_eval.py:15-108` |
| Knowledge Pipeline contract 基线 | `tests/test_knowledge_pipeline_contracts.py` |
| API content review/list/export contract | `tests/test_api_contracts.py` |
| 内容生成已进入 production gate 的静态检查 | `scripts/verify_production_v1_gate.py:922-960` |
| Admin 登录当前先 redeem 再本地检查管理角色 | `apps/admin-web/app/api/auth/login/route.ts:52-67` |

### 32.7 证据索引维护规则

- 代码结构调整后必须更新本索引；
- 只有路径和符号存在不能证明行为通过；
- 每个 “live verified” 结论必须同时引用运行 artifact；
- artifact 必须包含 commit、时间、环境和 hash；
- 当前文档不把 2026-07-10 的历史通过记录视为 2026-07-12 工作区的最新生产证明。
