# GEO 文案生成系统最终设计方案 v2.0

> **历史设计输入：** 本文不再是当前实现、API、部署或验收真源。“最终”只表示当时阶段结论。当前合同请使用 [GEO v3 运行与验收合同](GEO-v3-%E5%85%A8%E6%B5%81%E7%A8%8B%E8%BF%90%E8%A1%8C%E6%89%8B%E5%86%8C.md)、[系统架构](architecture/system-overview.md) 和 [全流程操作手册](operations/geo-full-flow-runbook.md)。

> - 文档状态：Final Design Baseline，待阶段审批记录签署
> - 设计日期：2026-07-13
> - 实施起始基线：`8220422`
> - 数据策略：现有数据均为可删除测试数据，不做历史数据迁移或回填
> - 实施方式：一个长期项目完成全部范围，使用小批次、阶段 Gate 和最多三个并行 worktree
> - 首个真实试点：单一 AU 项目，Website，`en-AU + zh-CN`

本文曾替换 `GEO-文案生成系统设计方案v1_0.md`，现与 v1 一并保留为审查历史，不再作为实现合同。

---

## 1. 最终设计结论

1. 使用独立 `geo_v2` 数据库并行建设 Schema v2；不在旧 `0001-0030` 迁移链上继续叠加 Content v2。
2. 保留 Auth、多项目、Collection、Knowledge、Scoring、Reports、Notifications、Portal 和 Audit 的有效能力，但不保留旧测试数据。
3. Content v0 在 Schema v2 切换时直接移除，不建设 Legacy Adapter、隐式 Brief 或旧 Draft 回填。
4. `content_assets/content_asset_versions` 是内容真源，不继续使用 `content_drafts` 过渡命名。
5. Export、Delivery、Publication Request 和 Publication Execution 是四种独立事件；Export 不产生发布任务。
6. 每份可交付内容必须包含 `en-AU` 和 `zh-CN`；英文是语义真源，中文绑定精确英文版本。
7. Prompt 与业务流程完全解耦；Prompt 可单独编辑、测试、发布、灰度和回滚，无需重新部署。
8. DeepSeek 是首选模型，但生成、翻译和评测全部通过统一 Model Gateway。
9. Evidence、Claim、Review、Delivery 和 Publication 都绑定精确版本与 hash，并由数据库复合外键保证同项目。
10. 发布需要内部批准、客户接受和独立 Publication Review；两种 locale 独立申请和执行发布。
11. 上传即按项目政策授权外部模型处理和公开改写，但真实性、主体归属、事实有效期和公开 Citation 仍独立校验。
12. 高风险金融、医疗、法律、就业和信贷内容不进入本系统。

---

## 2. 产品目标与边界

目标流程：

```text
GEO Opportunity
  -> Content Brief
  -> Evidence Pack
  -> Prompt Bundle
  -> en-AU Canonical Asset
  -> Claim QA + Internal Review
  -> zh-CN Translation + Parity QA
  -> Bilingual Delivery Package
  -> Customer Acceptance
  -> Publication Review
  -> Manual/Connector Publication
  -> GEO Retest and Feedback
```

最终渠道：

```text
Website
WordPress
Webflow
Shopify
LinkedIn
YouTube
Google Business Profile
```

明确非目标：

- 不让模型自行创造事实；
- 不把生成内容自动回灌为 Approved Fact；
- 不以 Export 或 Delivery 推断发布意图；
- 不用提示词代替权限、状态机、Evidence 和发布硬门禁；
- 不生成虚构消费者身份或描述中不存在的使用经历；
- 不在首个试点支持高风险行业内容。

---

## 3. 总体架构

```text
Admin Web / Customer Web
              |
        FastAPI Modular Monolith
              |
  +-----------+------------+-------------+
  |                        |             |
GEO Domain          Content Domain   Knowledge Domain
  |                        |             |
Opportunity / Retest  Brief / Evidence  Source / Chunk / Fact
  |                   Prompt / Asset          |
  +------------------------+------------------+
                           |
             PostgreSQL Durable Ledgers
                           |
          Valkey / Dramatiq wake-up and dispatch
                           |
 Evidence | Generation | Evaluation | Delivery | Skill workers
                           |
         Model Gateway / Qdrant / MinIO / Connectors
```

FastAPI 保持一个部署单元，但新增代码必须按模块组织：

```text
apps/api/geo_api/routers/content/
packages/geo_core/geo_core/content/
  contracts.py
  models.py
  repository.py
  services/
  jobs/
  rendering/
  prompts/
  qa/
```

不得继续把 Content v2 写入巨型 `apps/api/geo_api/main.py`、主 `repository.py` 或 `ProjectActions.tsx`。

---

## 4. Schema v2 基线

使用独立数据库 `geo_v2`，不使用同库双 schema 或 `search_path` 切换。

```text
infra/db/schema-v2/
  manifest.json
  baseline/
    0000_extensions_roles.sql
    0010_tenancy_project_rls.sql
    0011_auth_session_context.sql
    0012_auth_state_guards.sql
    0013_auth_commands.sql
    0014_auth_login_provision.sql
    0020_collection_geo_scoring.sql
    0030_knowledge_pipeline.sql
    0040_reports_notifications_integrations.sql
    0050_content_domain.sql
    0060_content_jobs_reviews_publication.sql
    0070_indexes_triggers_grants.sql
    0080_system_seeds.sql
  migrations/
```

元数据表：

```text
app_schema_metadata(
  schema_generation,
  baseline_version,
  baseline_hash,
  minimum_app_version,
  installed_at
)

schema_migration_ledger(
  migration_id,
  checksum,
  applied_at,
  app_commit
)
```

规则：

- Baseline 文件 checksum 写入 `manifest.json`，已应用文件发生 hash 漂移时 runner 必须拒绝启动；
- runner 使用 PostgreSQL advisory lock，防止并发安装；
- API、Dispatcher 和所有 Worker 启动时校验 `schema_generation=2`、baseline hash 和应用兼容范围；
- 生产 seed 只包含系统策略、系统 Skill、Prompt Definition 和枚举配置，不包含示例客户内容；
- 测试 fixture 与生产 seed 完全分离。

数据库授权上下文必须满足：

```text
HTTP request
  -> hash raw session token in process
  -> SET LOCAL app.session_token_hash
  -> SECURITY DEFINER resolver
  -> active runtime_sessions snapshot
  -> actor / tenant / project capabilities
```

- `0010` 只安装 Tenancy、Project、Membership、derived Grant 和 Audit 边界，并对全部表启用 `FORCE RLS`；在 `0011` 安装前，runtime role 没有 schema/table/function 权限，也没有 runtime policy；
- Schema v2 授权只接受事务级 `app.session_token_hash`，不得使用 `app.actor_id`、`app.tenant_id`、`app.project_id`、`app.project_ids` 或请求角色 GUC 作为身份真源；
- raw Session Token 永不进入 PostgreSQL、日志、错误、审计或 Job payload；数据库只接收其 SHA-256，且 runtime role 不能直接读取或枚举 `runtime_sessions.session_token_hash`；
- 无 hash、格式错误、未知、过期或撤销 Session 一律解析为匿名零权限，不向调用方暴露具体原因；
- 每个事务重新设置 `SET LOCAL app.session_token_hash`，连接池归还前必须 rollback/reset，清理失败时销毁连接；
- Worker 不继承用户 Session Token/hash，使用独立 worker 数据库角色和窄 Job 函数；Job 只保存请求 Session/Actor 的审计 lineage；
- API/Worker 登录角色、runtime group role、authz owner 和 schema owner 必须分离；runtime/worker 不能继承或 `SET ROLE` 到 `BYPASSRLS` authz owner。

---

## 5. 角色、Capability 与职责分离

Schema v2 使用六种 canonical project role，由服务端映射 capability：

| 持久角色 | 主要边界 |
| --- | --- |
| `project_owner` | 项目、成员、Connector、报告可见性和 Publication 管理 |
| `analyst` | Collection、Analysis、Scoring、Action 和 Report 生成 |
| `reviewer` | Analysis/Report/Content 审核，不运行 Connector |
| `knowledge_architect` | Knowledge 导入、内部读取、Fact 审核和已批准知识读取 |
| `content_operator` | 只消费已批准 Knowledge，执行 Content 生成、编辑和 Delivery |
| `client_viewer` | 只读取 customer-visible 投影，执行 Customer comment、request changes 和 accept |

旧输入别名只用于切换期兼容：

```text
owner | admin -> project_owner
viewer        -> client_viewer
analyst       -> analyst
```

新写入、Session scope 和审计必须使用 canonical role。`project_owner`、`analyst` 和 `reviewer` 不因角色名称自动获得 Knowledge 内部权限；Knowledge 治理只由 `knowledge_architect` 执行，`content_operator` 只读已批准投影，`client_viewer` 还必须满足 `customer-visible` 条件。

Content 流程中的“内部操作者、内部批准者、Publication Owner、Customer”是 capability 职责，不是另一套持久化角色。一个命令所需的 capability 必须由 API 按当前 `project_id` 返回，不能使用跨项目的扁平权限集。

必须满足：

```text
submitted_for_review_by != internal_approver
```

默认任一 active `client_viewer` 的首次有效 acceptance 满足客户接受。所有按钮和命令以 API 返回的 `capabilities/available_actions/blocked_reasons` 为准，前端不得根据角色字符串自行计算权限。

两个不同且具备对应 approval capability 的内部审批者可以共同接受软质量 warning，但不能 override：

- Evidence 不合格；
- Claim inventory 不完整；
- Claim unsupported/conflict；
- exact version/hash 不匹配；
- 跨项目引用；
- customer acceptance；
- publication approval；
- 虚构或无来源的消费者体验。

---

## 6. 核心领域对象

| 聚合 | 表/对象 |
| --- | --- |
| Opportunity | `content_opportunities`、typed origin、opaque `opportunity_ref` |
| Brief | `content_briefs`、`content_brief_versions`、`content_brief_subject_entities` |
| Evidence | `content_evidence_pack_jobs`、packs、items、diagnostics |
| Prompt | definitions、definition versions、template releases、assignments、bundles |
| Skill | skills、versions、compile jobs、assignments |
| Generation | requests、jobs、budget reservations、locale pairs |
| Asset | `content_assets`、`content_asset_versions`、version relations |
| QA | claims、claim evidence、evaluation jobs/results/findings |
| Review | `human_review_records` + `content_review_targets` |
| Export | immutable export events |
| Delivery | delivery jobs、bilingual packages、customer visibility |
| Publication | requests、publications、attempts、proofs |
| Feedback | signals、retests、experiments |

新增 project-scoped `product_entities`。品牌、竞品、产品和市场主体必须显式建模，禁止把第一条 Fact 的 subject 推断为品牌。

---

## 7. 数据库全局不变量

1. 所有 project-owned 父对象必须有 `UNIQUE(project_id, id)`。
2. 所有项目内 FK 必须携带 `project_id`，RLS 不能代替关系完整性。
3. Brief、Asset head 与 Version 使用预生成 UUID 和 `DEFERRABLE INITIALLY DEFERRED` 循环 FK。
4. 多态来源使用 typed nullable FK；`item_type` 必须与唯一非空 typed FK 匹配。
5. Prompt Bundle 必须复合引用同一个 Brief Version、Evidence Pack 和 Template Release。
6. Asset Version 必须复合引用同一条 Brief/Evidence/Prompt 编译链。
7. Claim Evidence 只能引用该 Asset Version 冻结 Evidence Pack 中的 Item。
8. Review、Delivery 和 Publication 必须绑定 exact Asset Version + content hash。
9. sealed Evidence、Prompt、Asset content、Evaluation result 和 Package 由触发器禁止 UPDATE/DELETE。
10. 状态转换除 Service 守卫外，必须有真实 PostgreSQL 行为测试；关键不可逆状态使用触发器保护。

---

## 8. Opportunity 与 Brief

Opportunity 从 Action Recommendation、Source Gap、Report、Retest 或手工输入创建。API 使用不透明引用：

```text
action_recommendation:{uuid}
source_gap:{uuid}
report_export:{uuid}
retest_comparison:{uuid}
manual:{uuid}
```

Brief Version 是正式生成输入，至少包含：

```yaml
content_type: answer_page | comparison_guide | faq | local_au_guide
market: AU
source_locale: en-AU
required_locales: [en-AU, zh-CN]
publication_channels: [website]
primary_brand_entity_id: uuid
compared_entity_ids: []
allowed_subject_entity_ids: []
authorship_mode: brand_authored | editorial | verified_experience
audience: "..."
goal: "..."
tone: "..."
required_topics: []
prohibited_topics: []
```

Brief 状态：

```text
draft -> validating -> validated -> evidence_building
-> ready | needs_evidence | blocked
-> locked | superseded | cancelled
```

修改 Brief 必须创建新 Version；已用于 Prompt Bundle 的 Version 不可修改。

---

## 9. Evidence Pack

Evidence Pack 是不可变 Attempt，而不是可原地重跑的工作区：

```text
Brief Version
  -> Attempt 1: needs_evidence
  -> Attempt 2: blocked
  -> Attempt 3: ready
```

技术错误通过 Job retry 恢复；补充资料或修改治理后创建新 Job 和新 Attempt。Job 技术失败不产生 Pack。

Evidence Item 判别联合：

```text
approved_fact
chunk
citation
report_extract
action_extract
retest_extract
source_asset
verified_experience
```

每个 Item 保存：

- typed source ID；
- source revision；
- locator 和 locator hash；
- snapshot text 或 MinIO URI，二者恰好一个；
- snapshot hash；
- subject entity/role；
- authority、validity 和 lifecycle；
- public disclosure、URL、title、label 和 attribution 配置。

Qdrant 只返回候选，Builder 必须回 PostgreSQL 校验 project、active、approved、validity、subject 和 source hash。

上传行为自动记录：

```text
external_model_use_allowed=true
public_adaptation_allowed=true
authorization_basis=project_upload_policy_version
authorised_by=current_actor
authorised_at=current_timestamp
```

无公网 URL 的资料可支持内部 Claim QA，但不能显示为公开 Citation。渠道策略要求公开引用时，必须补充官方可访问 URL，否则 Publication 被阻断。

---

## 10. 真实消费者使用描述

`verified_experience` 不要求用户手工填写提供者、产品、时间、场景、原始陈述等一组结构化字段。

用户只提供：

```yaml
experience_description: |
  一段真实消费者使用描述
attestation_confirmed: true
```

确认文案固定表达为：

> 我确认这段描述来自真实使用经历，并且我有权将其用于本项目的文案生成和公开发布。

系统自动记录：

```text
submitted_by
submitted_at
description_hash
attestation_policy_version
project_id
```

实现规则：

1. `experience_description` 是唯一体验事实边界；模型可以重写和组织表达，但不能补造描述中不存在的产品使用、效果、时间、身份或推荐理由。
2. 系统可从描述中自动提取产品、时间和使用场景用于 Claim QA，但提取结果不是新增事实，也不要求用户补填。
3. 描述没有出现的细节必须省略，不得用常识、品牌材料或其他消费者描述补全第一人称经历。
4. 生成结果中的第一人称体验 Claim 必须能映射回该描述的文本片段。
5. `attestation_confirmed=false` 时不能进入生成流程。
6. 品牌和 editorial 模式不得伪装成消费者第一人称体验。

以下仍为不可 override 硬阻断：

```text
synthetic_testimonial
fake_persona
unsupported_first_person_experience
hidden_commercial_relationship
```

---

## 11. Prompt 与流程完全解耦

业务代码只调用稳定 Task Key：

```text
canonical.generate
translation.zh_cn
claims.extract
claims.evaluate
quality.evaluate
variant.generate.website
variant.generate.linkedin
variant.generate.youtube
```

正式编译关系：

```text
Prompt Definition Version
  + resolved Skill Versions
  + Output Schema Version
  + Compiler Version
  -> immutable Template Release
  -> per-run immutable Prompt Bundle
```

数据表：

```text
content_prompt_definitions
content_prompt_definition_versions
content_prompt_template_releases
content_prompt_release_assignments
content_prompt_test_runs
content_prompt_bundles
```

Prompt Definition Version 保存：

- task key；
- system/user message template；
- typed variable schema；
- output schema reference；
- model-policy compatibility；
- source hash、author、reason 和版本。

Admin Prompt Studio 支持：

```text
create version -> lint -> preview rendered prompt -> diff
-> Golden Set test -> cost/quality comparison
-> release -> project/channel assignment -> canary -> rollback
```

约束：

- 修改提示词文本、结构、语气、示例和写作规则不需要代码部署；
- 提示词不能修改状态机、权限、Evidence 边界、预算或发布门禁；
- 必需变量或输出结构变化必须创建新的 contract/output-schema/compiler version；
- `retry` 使用原 Prompt Bundle；
- `regenerate` 创建新 Job，可显式选择原 Release 或最新 Release；
- Release 回滚只切换 Assignment，不修改历史 Bundle；
- Prompt Bundle 保存完整受控快照 URI/hash，保证可复现。

---

## 12. Skill 与 Template Release

Skill 是可编辑规则模块，Prompt Definition 是基础提示词源，两者不是竞争真源。

Resolver 顺序：

```text
system -> tenant -> project -> market -> content type -> channel
```

Skill Compile Job 生成不可变的编译片段；Prompt Compiler 再将 Prompt Definition、resolved Skills 和 Output Schema 编译成 Template Release。

Compile succeeded 只表示产物已保存，不代表已 release。Release、canary、assignment 和 rollback 都是独立命令并记录审计。

---

## 13. Model Gateway 与预算

DeepSeek 作为 `content-primary` 首选模型。所有 Content、Translation、Claim 和 Evaluation 调用必须通过统一 Gateway，不允许 Worker 直连 Provider。

```python
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
```

默认策略：

```yaml
preferred_alias: content-primary
default_model: deepseek-v4-flash
max_model_calls_per_job: 3
max_cost_usd_per_job: 2.00
structured_output_required: true
external_training_allowed: false
```

首次调用、Schema repair、fallback 和 retry 共用一个 Job 预算，retry 不重置。调用前原子预留预算，外部调用期间不得持数据库锁。

Evaluation 使用独立 evaluator alias、Prompt、call log 和结果；即使使用相同 Provider，也不能复用生成模型的自评结论。

Provider Capability Registry 保存 Provider/Model、训练和保留政策证据、合同版本、复核时间和有效期。路由必须满足项目 Model Policy。

---

## 14. Durable Job 合同

独立 Worker：

```text
evidence-worker
generation-worker
evaluation-worker
delivery-worker
skill-worker
```

共享 Job 字段和行为：

```text
queued / running / retry_wait / finalizing
succeeded / failed / dead_letter / cancelled
lease_token / lease_expires_at / heartbeat_at
attempt_count / max_attempts / next_attempt_at
idempotency scope/key/payload hash
parent_job_id / regeneration_nonce / replay_nonce
budget and progress
```

业务 Job 与 `durable_job_dispatch_outbox` 在同一 PostgreSQL 事务创建。Valkey/Dramatiq 只负责唤醒，Worker 必须从 PostgreSQL 原子 claim。

必须支持 expired-running/finalizing reclaim、heartbeat、fencing、CAS terminal write、cancel、DLQ 和 operator replay。旧 lease token 不能提交结果。

Job succeeded 表示结果已完整持久化，不表示 Asset 通过 QA。单产物 Job 不使用 `partial_succeeded`。

PostgreSQL 结果与 Job terminal 状态必须同事务提交。MinIO 使用 attempt-scoped pending key，进入 finalizing 后恢复器只 finalize，不重新调用模型。

---

## 15. Asset、双语和编辑

Asset Version 状态：

```text
generated -> qa_running
-> pending_human_review
-> approved | needs_revision | rejected | blocked
-> superseded | archived
```

Export、Delivery 和 Publication 不属于 Asset 状态。

双语规则：

1. `en-AU` 是唯一语义真源。
2. `zh-CN` Version 必须保存 `source_version_id + source_content_hash`。
3. 中文不得改变实体、数字、价格、日期、否定、限定词、Claim、Citation 或披露。
4. 中文无需独立人工双语审核，使用 `approval_basis=automated_translation_policy`。
5. 中文人工编辑创建新 Version 并重跑 Translation Parity QA。
6. 中文可以调整文本和必要排版，但不能新增事实或删除披露、Citation 和 Claim-bearing block。
7. English 编辑创建新 English Version，并触发新的中文翻译和 Locale Pair。
8. 新编辑 Version 创建时，旧批准 Version 仍有效；只有新 Version 批准后才 supersede 旧批准 Version。

Delivery Package 必须绑定 immutable Locale Pair：

```text
en_asset_version_id + en_content_hash
zh_asset_version_id + zh_content_hash
bundle_hash
```

修改任一语言都会使旧 Package、Customer acceptance 和未执行 Publication approval 失效。

---

## 16. ContentDocument V1

正文使用 TipTap/ProseMirror 兼容结构，但传输和 hash 使用服务端定义的 `ContentDocumentV1`。

允许节点：

```text
doc / heading / paragraph / text
bulletList / orderedList / listItem
blockquote
table / tableRow / tableCell
faqGroup / faqItem
comparisonTable
cta / disclosure / imageRef
```

允许 marks：

```text
bold / italic / link / claimRef / citationRef
```

每个 block 必须有稳定 `block_id`；中文 block 保存 `source_block_id`。禁止 arbitrary HTML、inline style、script 和任意 embed。

客户端只提交 `content_json`。服务端固定 renderer 生成 HTML、Markdown、Text 和 canonical hash。Claim 使用 `block_id + offsets + extractor_version` 定位，版本 diff 按 block ID 比较。

人工编辑 API：

```http
POST /v1/content/assets/runtime/{id}/versions
```

请求必须包含 base version/hash、ContentDocument、reason，并使用 `If-Match`。新版本重新执行 Claim extraction、QA 和 Review；旧审批不复制。

---

## 17. Claim、Evaluation 与硬门禁

QA 分三层：

1. 确定性检查：Schema、长度、locale、数字、链接、禁止内容、敏感输出、品牌/竞品主体。
2. Claim 检查：inventory completeness、subject consistency、Evidence support、conflict 和 public Citation availability。
3. 独立软质量评测：清晰度、结构、语气、渠道适配、GEO 可引用性和翻译自然度。

必须分别评估：

```text
Claim extraction recall
Claim evidence precision
Support classification accuracy
Translation claim parity
```

`evidence_coverage_ratio=100%` 只有在 Claim inventory completeness 已确认时才有效。

英文内部批准前必须有：

```text
claim_inventory_complete=true
all factual claims=supported
no unresolved conflict
deterministic gates=passed
```

中文使用严格自动 parity gate，不要求独立人工双语审核。

---

## 18. Review、Delivery 与 Publication

Review kinds：

```text
claim_inventory
subject_matter
internal_approval
customer_acceptance
publication_approval
```

Publication 完整资格：

```text
valid Evidence Pack
+ Claim inventory complete
+ all factual Claims supported
+ internal approval
+ bilingual bundle ready
+ customer acceptance
+ locale-specific publication approval
+ channel/destination policy passed
```

Export：

- 只产生 artifact 和 audit event；
- 不修改 Asset；
- 不创建 Delivery 或 Publication；
- 未批准内部导出必须带 `NOT APPROVED` manifest。

Delivery：

- 由独立 durable Job 构建；
- 客户 Package 采用 allowlist builder，不能从内部 zip 删除字段得到；
- 客户包只含批准内容、公开 Evidence 摘要、公开 Citations、客户 scorecard 和 manifest。

Publication Request：

```http
POST /v1/content/assets/runtime/{id}/versions/{version_id}/publication-requests
```

绑定 exact version/hash、locale、channel、destination、reason 和 Idempotency-Key。

Publication 状态：

```text
requested -> pending_review -> approved
-> scheduled -> publishing -> published -> verifying -> verified
failed -> retrying | cancelled
scheduled -> cancelled
```

手工发布和 Connector 发布都是 `content_publication_attempts`，使用 `execution_mode=manual|connector`。Export、Delivery 和 Approval 都不能隐式创建 Attempt。

---

## 19. API 合同

统一前缀 `/v1/content`。核心资源：

```http
GET  /bootstrap/runtime

GET  /opportunities/runtime
POST /opportunities/runtime/{ref}/accept
POST /opportunities/runtime/{ref}/dismiss

POST /briefs/runtime
GET  /briefs/runtime/{id}/versions
POST /briefs/runtime/{id}/versions
POST /briefs/runtime/{id}/versions/{version_id}/validate
POST /briefs/runtime/{id}/versions/{version_id}/evidence-pack-jobs

GET  /evidence-pack-jobs/runtime/{id}
GET  /evidence-packs/runtime/{id}
GET  /evidence-packs/runtime/{id}/items

POST /generation-requests/runtime
GET  /generation-jobs/runtime/{id}

GET  /assets/runtime/{id}
GET  /assets/runtime/{id}/versions
POST /assets/runtime/{id}/versions
GET  /assets/runtime/{id}/versions/{version_id}/locale-bundle
POST /assets/runtime/{id}/versions/{version_id}/submit-review

GET  /assets/runtime/{id}/versions/{version_id}/claims
GET  /assets/runtime/{id}/versions/{version_id}/evaluations

POST /assets/runtime/{id}/versions/{version_id}/exports
POST /assets/runtime/{id}/versions/{version_id}/delivery-jobs
POST /assets/runtime/{id}/versions/{version_id}/publication-requests

GET  /delivery-jobs/runtime/{id}
GET  /delivery-packages/runtime/{id}
GET  /publication-requests/runtime/{id}
POST /publication-requests/runtime/{id}/approve
POST /publication-requests/runtime/{id}/cancel
POST /publication-attempts/runtime/{id}/url
POST /publication-attempts/runtime/{id}/confirm-published
POST /publication-attempts/runtime/{id}/verify
POST /publication-attempts/runtime/{id}/block

GET  /prompt-definitions/runtime
POST /prompt-definitions/runtime/{id}/versions
POST /prompt-definitions/runtime/{id}/versions/{version_id}/test-runs
POST /prompt-template-releases/runtime/{id}/release
POST /prompt-template-releases/runtime/{id}/rollback
```

所有编辑命令使用 `ETag/If-Match`，所有创建命令使用作用域化 `Idempotency-Key`。异步命令返回：

```text
202 Accepted
Location
Retry-After
status_url
```

稳定错误 envelope 覆盖 `401/403/404/409/412/422/429/5xx`，包含 machine-readable code、field/gate details 和 correlation ID。

FastAPI OpenAPI 是 DTO 唯一真源。Admin 和 Customer 从同一 snapshot 生成 TypeScript 类型并校验 contract hash，禁止手写重复 Content DTO 或使用 `Record<string, unknown>` 绕过。

---

## 20. Admin Web 与 Customer Web

Admin 保持项目内唯一 Content Studio 入口：

```text
/projects/{project_id}?tab=operations&operation_tab=content
```

Views：

```text
Work Queue
Readiness
Opportunities
Briefs
Assets
Reviews
Prompt Studio
Skills
Delivery
Publication
Feedback
```

桌面 Asset 页面：左侧对象/版本导航，中间编辑和预览，右侧 Evidence/Claim/QA/Review/Lineage；Export、Delivery、Publication 使用独立底部时间线。移动端降级为 Tabs 和全屏编辑/预览。

核心组件：

```text
OpportunityBoard
BriefEditor
EvidenceInspector
EvidenceAttemptTimeline
PromptStudio
PromptVersionDiff
PromptTestRunPanel
StructuredAssetEditor
LocalePairBar
TranslationParityPanel
ClaimQaPanel
ReviewDecisionPanel
CustomerPackageBuilder
PublicationRequestDialog
PublicationReviewPanel
ConnectorExecutionTimeline
```

Customer Web：

```text
/portal/content?project_id={id}
/portal/content?project_id={id}&delivery_package_id={id}
```

提供双语 Package 查看、English/Chinese 切换或并排对照、按 `locale + block_id` 评论、请求修改和接受。不得展示 Prompt Bundle、内部 Evidence、内部 Review note、模型日志或安全 finding。

前端只消费 API 的 `available_actions/blocked_reasons`。`412` 必须保留本地 working copy并提供 diff/rebase/discard；异步轮询遵循 `Retry-After`，页面离开不取消后台 Job。

---

## 21. Connector 与反馈

第一波：

```text
WordPress / Webflow / Shopify
```

第二波：

```text
LinkedIn / YouTube / Google Business Profile
```

每个 Connector 必须完成：

```text
capability registry
-> least-privilege OAuth
-> encrypted secret reference
-> sandbox
-> draft-only
-> dry run
-> idempotent outbox
-> publish
-> verify
-> retry
-> revoke/compensate
```

默认 draft-only。只有项目和渠道政策明确启用时才允许自动发布，并且仍需要显式 Publication Request 和全部审批。

Feedback 必须绑定 exact Asset Version/hash、Publication、Monitoring Query、Observation Provider、market/city/device、baseline 和 retest。UI 只能表述为相关性观察，不自动宣称因果。

默认 Retest：发布前 baseline、发布后 7/30/90 天；项目可配置，但必须保持同 query/provider/market/city/device 口径。

---

## 22. 对象存储、安全与保留

对象路径：

```text
content-prompts/{project_id}/{brief_version_id}/{prompt_bundle_id}/
content-evidence/{project_id}/{brief_version_id}/{evidence_pack_id}/
content-artifacts/{project_id}/{asset_id}/{version}/
content-deliveries/{project_id}/{delivery_package_id}/
```

Prompt Bundle 在 Draft/Asset 生成前创建，因此路径不得依赖 Asset ID。

保留策略：

- 被引用的 Evidence、Prompt、Asset、Evaluation、Review、Delivery 和 Publication 版本无限期保留；
- legal hold 阻止删除；
- 只允许授权人工删除，并记录 audit 和引用影响；
- 仅未引用 pending/temp artifact 可以自动 GC。

基础设施必须保持：

- MinIO root/application/backup/restore 身份分离；
- 所有对象存储 consumer 传播一致的 application credentials；
- application/backup principal 无 `CreateBucket`；
- 真实加密 volume receipt 和新节点 encrypted snapshot restore receipt；
- PostgreSQL 非默认密码；
- Valkey 认证；
- Qdrant API key/TLS 或严格内部网络隔离；
- 非必要数据库、MinIO、Qdrant 端口不暴露到公网。

上传资料允许原样发送至项目配置的 DeepSeek，但 Provider Capability、合同和 Security 审批必须可核验。公开输出仍需扫描 active credential、secret token 和意外泄漏；上传授权不等于要求把凭据写进公开内容。

---

## 23. 可观测性与 SLO

统一 correlation：

```text
request_id
project_id
workflow_id
job_id
brief_version_id
evidence_pack_id
prompt_bundle_id
asset_version_id
delivery_package_id
publication_id
llm_call_id
```

核心指标：

- 各队列 depth、oldest age、running、retry、DLQ、lease reclaim；
- Evidence ready/needs_evidence/blocked 比率；
- Model calls、Token、成本、超时、fallback、预算阻断；
- Claim extraction recall、support 和 conflict；
- Translation parity failure；
- Review 和 Customer acceptance SLA；
- Delivery build/restore；
- Publication publish/verify/failure；
- Connector rate limit/auth failure；
- Prompt Release 的质量、成本和回滚率。

单节点 Compose 明确不提供 HA。初始服务目标：API 月可用性 99.5%，expired Job 在两个 recovery interval 内接管，RPO 24 小时，RTO 4 小时。真实指标稳定后再调整。

---

## 24. 测试与 Golden Set

开工前必须先修复当前全量测试的 `10 failures + 1 error`，建立 Green 基线。

测试层：

```text
unit
repository
real PostgreSQL behavior
RLS/composite-FK negative
API contract/OpenAPI diff
worker crash/reclaim/fencing
Model Gateway stub/live smoke
MinIO finalize/backup/restore
Admin/Customer component and Playwright
Connector sandbox/live smoke
full production gate
```

Golden Set 必须分别衡量：

- Claim extraction recall；
- Claim evidence precision；
- support classification accuracy；
- 品牌/竞品/产品/市场主体归属；
- `en-AU` 拼写、AUD/GST 和内容质量；
- `zh-CN` Claim、数字、限定词和 Citation parity；
- Prompt Injection 对抗；
- 真实体验描述边界，不补造体验；
- 公开 Citation 可解析性；
- Prompt Release 前后质量和成本回归。

关键 E2E：

1. English 生成后自动创建 Chinese translation Job；
2. 中文 QA 未完成时 Delivery 被阻断；
3. English/Chinese 编辑分别创建新 Version；
4. 任一语言修改使旧 Customer acceptance 失效；
5. 双语 Package 一次接受；
6. 两种 locale 独立 Publication Request；
7. Export 无 Publication 副作用；
8. `412` 保留 working copy；
9. `reviewer`/`project_owner`/`client_viewer` 以及按项目 capability 权限隔离；
10. 真实体验描述之外的第一人称细节被阻断；
11. Prompt 修改无需部署，新 Job 使用新 Release，retry 使用旧 Bundle；
12. 1440/1024/390 px 无重叠且关键流程可操作。

---

## 25. 实施批次

```text
B0  修复测试基线，冻结最终合同和审批模板
B1  Schema v2 runner、manifest、geo_v2 Compose profile
B2  Auth/Project/Collection/Knowledge/Scoring/Report/Portal parity
B3  Content Schema、RLS、composite FK、trigger
B4  模块化 API、OpenAPI、Bootstrap、typed clients
B5  Opportunity、Brief、Evidence Job/Pack/Items
B6  Prompt Studio、Skill、Compiler、Gateway、Generation
B7  Asset、ContentDocument、Claim、Evaluation、Review
B8  zh-CN Translation、Locale Pair、Delivery、Customer Web
B9  Publication、Feedback、Experiment
B10 WordPress/Webflow/Shopify Connectors
B11 LinkedIn/YouTube/Google Business Profile Connectors
B12 全量演练、原子切换、旧系统删除
```

这是一个完整项目范围，不将 B9-B11 重新定义为不确定的未来版本。批次只用于降低合并和验证风险。

每个批次只完成一个明确 transform，运行定向测试；阶段 Gate 运行全量 suite、fresh install、RLS negative、OpenAPI diff、worker crash、backup/restore 和 live smoke。

---

## 26. Worktree 并行与合并

最多三个实施 worktree，加当前集成 session：

```bash
git worktree add ../geo-schema-v2 -b codex/content-v2-schema main
git worktree add ../geo-content-core -b codex/content-v2-core main
git worktree add ../geo-content-web -b codex/content-v2-web main
```

职责：

| Worktree | 所有权 |
| --- | --- |
| `geo-schema-v2` | Schema、runner、RLS、trigger、DB behavior tests |
| `geo-content-core` | Domain、Service、Gateway、Jobs、API、Worker |
| `geo-content-web` | generated client、Admin、Customer、Playwright |
| 当前 session | 契约冻结、共享 OpenAPI、Compose、CI、审批和合并 |

避免长期分支：每轮依赖合并后，从最新 `main` 重建下一批分支。共享热点文件只由当前集成 session 修改。

---

## 27. 原子切换与回滚

```text
冻结 release
-> maintenance mode，停止旧 API mutation
-> drain dispatcher/workers/active leases
-> 从 manifest 创建并验证 geo_v2
-> 部署同一 release manifest 的 image/schema/OpenAPI
-> 启动 v2 workers/dispatcher/API
-> 全能力 smoke、RLS、backup/restore
-> 反向代理一次性切流
-> Content v0 routes 返回 404
```

Release manifest 必须绑定：

```text
git commit
worktree dirty=false
schema baseline hash
OpenAPI snapshot hash
container image digests
Prompt system release IDs
test/gate artifact hashes
```

首个真实 v2 数据写入前，可以整对回滚旧应用和旧数据库。真实数据写入后进入 forward-fix，不再回滚至 v1。

观察期结束后删除：

- 旧数据库 volume；
- Content v0 routes、DTO、UI 和 tests；
- `content_drafts` 和 `manual_distribution_records` 旧实现；
- `infra/db/migrations/up/0001-0030` 及对应硬编码迁移列表。

Git 历史继续保留旧迁移作为审计记录。

---

## 28. 阶段审批

审批记录保存到：

```text
docs/approvals/content-v2/
  gate-0-baseline.yaml
  gate-1-schema-parity.yaml
  gate-2-content-core.yaml
  gate-3-delivery-customer.yaml
  gate-4-publication-connectors.yaml
  gate-5-production-pilot.yaml
```

每份记录包含 Owner、Product、Engineering、Security、Delivery 结论，commit、schema/OpenAPI/artifact hash、测试结果、偏差、批准人和时间。

---

## 29. Definition of Done

最终完成必须同时满足：

1. 当前全量测试 Green；
2. Schema v2 fresh install 和 manifest 校验 Green；
3. 现有产品能力 parity Green；
4. 所有 project-owned 关系通过 composite FK 和 RLS negative；
5. Prompt 可独立编辑、测试、发布、灰度和回滚；
6. DeepSeek 和独立 Evaluation 通过统一 Gateway，预算可核验；
7. Evidence/Claim/Review exact lineage 不可绕过；
8. 真实体验输入只需一段描述和一次确认，生成结果不补造描述外经历；
9. `en-AU + zh-CN` Website Golden Set Green；
10. Customer bilingual Delivery 和三层审批 Green；
11. Export 无 Publication 副作用；
12. 六个 Connector 全部通过 sandbox、dry-run、publish、verify 和补偿 Gate；
13. 真实 PostgreSQL/Qdrant/Valkey/MinIO/DeepSeek 联合运行 Green；
14. 加密 volume、backup 和新节点 restore Green；
15. 单一 AU Website pilot Green；
16. Product、Engineering、Security、Delivery 审批齐全；
17. Content v0、旧数据库和旧迁移链已移除。

本设计不再保留旧数据回填、Legacy Content 兼容、提示词硬编码或未定义的后续架构迁移。
