# F-019 QuestionSet、Protocol 与内部仿真集成合同

状态：`FROZEN_FOR_0019`
迁移：`0019_knowledge_question_sets`，线性接在 `0018_metric_membership` 之后。
范围：F019 批次 4；0017 Fact/Entity/Relation 核心是前置条件。

## 1. 不可变边界

- PostgreSQL 继续是唯一业务真源。问题生成框架对象、缓存和索引不得进入 Domain/API/表。
- 根上下文固定为 `(project_id, campaign_id)`；所有 Job、候选、QuestionSet、Protocol 和仿真
  复合外键必须同时证明这两个 ID。
- 问题只可引用生成 Job 冻结时仍为 `active + approved` 的 Fact，以及 `current` 的批准图实体。
  候选至少一个 Fact 来源；仅实体来源不能构成事实支持。
- 候选先人工批准，QuestionSet 再执行 `draft -> approved -> frozen`。QuestionSet item 从创建起
  不可修改；选错候选时创建新版本，不原地替换。
- Protocol 只能在 `draft` 状态一次性绑定一个 `frozen` QuestionSet；绑定后不可解绑或换版本。
  绑定必须把 QuestionSet 全部 item 一一投影成现有 suggestion/query，禁止缺项、加项和快照漂移。
- 内部 GEO 仿真复用现有 `prompt_simulation.generate`、Opportunity 当前 approved Prompt Release、
  model call log、MinIO artifact 和 F009 边界。不得建立第二套生成/密钥/发布体系。
- 仿真仍由数据库强制 `test_only=true`、`publication_eligible=false`。本批次不把仿真自动写成
  Monitoring Observation；因此它不会进入 Observation、Metric、Report、Publication 或 Submission。

## 2. 生成 Job 与冻结输入

### `knowledge_question_generation_specs`

- `job_id uuid PRIMARY KEY`
- `project_id uuid NOT NULL`
- `campaign_id uuid NOT NULL`
- `configured_model text NOT NULL CHECK (btrim(...) <> '')`
- `model_call_budget integer NOT NULL CHECK (BETWEEN 1 AND 1000)`
- `adapter_release text NOT NULL CHECK IN ('project-native-rag-v1',
  'llamaindex-property-graph-v1')`
- `selection_manifest_hash text NOT NULL`，小写 SHA-256
- `dimension_schema_version text NOT NULL CHECK = 'geo-question-dimensions-v1'`
- `embedding_model_key text NOT NULL CHECK = 'geo-question-semantic-hash-v1'`
- `semantic_duplicate_threshold numeric(5,4) NOT NULL CHECK (>= 0.80 AND <= 1.00)`，默认
  `0.9200`
- `requested_by uuid NOT NULL REFERENCES identities(id)`
- `created_at timestamptz NOT NULL DEFAULT clock_timestamp()`

复合 FK：

- `(job_id, project_id, campaign_id) -> durable_jobs(id, project_id, campaign_id)`，Job kind 必须是
  `knowledge.question.generate`。
- `(campaign_id, project_id) -> geo_campaigns(id, project_id)`。
- `UNIQUE(job_id, project_id, campaign_id)`。

Spec INSERT 后不可 UPDATE；只能随同 Durable Job 删除，且删除保护沿用现有 exact-job 规则。

### `knowledge_question_dimensions`

一行是一个实际 fan-out 单元，而不是未展开的 JSON：

- 上下文：`job_id`、`project_id`、`campaign_id`
- identity：`dimension_key text`、`ordinal integer > 0`
- multi-turn：`turn_index integer BETWEEN 1 AND 3`、`parent_dimension_key text NULL`
- 维度快照：`persona`、`scenario`、`intent`、`funnel`、`region`、`language`、
  `brand_scope`、`platform`、`query_kind`、`subject`
- `competitor_entity_id uuid NULL`
- `created_at`

枚举：

- `funnel IN ('awareness','consideration','decision','retention')`
- `brand_scope IN ('brand','non_brand','competitor')`
- `platform` 与 Monitoring Protocol 现有平台枚举一致
- `query_kind IN ('recommendation','comparison','research','support')`

约束：PK `(job_id, dimension_key)`；唯一 `(job_id, ordinal)`；parent 使用同 Job/Project/Campaign
自 FK。`turn_index=1` 当且仅当 parent 为 NULL；后续 turn 必须引用更小 turn。competitor scope
必须有同 Project 的 active Catalog competitor，其他 scope 必须为 NULL。每 Job 最多 200 个维度。

### `knowledge_question_generation_fact_inputs`

- Job exact context
- `fact_candidate_id`
- Fact exact context：`pipeline_run_id`、`source_id`、`document_id`、`chunk_id`、
  `rag_revision_id uuid NULL`
- 冻结证据：`statement_snapshot`、`statement_hash`、`source_locator NULL`、
  `extractor_release`
- `created_at`

PK `(job_id, fact_candidate_id)`；FK 到 generation spec、Fact exact context 和 Chunk exact context。
INSERT trigger 必须逐字段比对 Fact，且要求 `status='approved' AND lifecycle_status='active'`。
Snapshot/input membership 完全不可变。Job 至少一个 Fact input，最多 500 个。

### `knowledge_question_generation_entity_inputs`

- Job exact context
- `graph_entity_id`
- `entity_type_snapshot`、`canonical_name_snapshot`、`name_hash`
- `created_at`

PK `(job_id, graph_entity_id)`；exact FK 到 approved graph entity。INSERT 时要求
`status='current'` 且至少一个 active graph source。最多 500 个。

## 3. 生成结果与候选

### `knowledge_question_generation_results`

- `job_id PRIMARY KEY`、`project_id`、`campaign_id`
- `output_hash`、`artifact_uri`、`artifact_hash`；URI 必须为 `s3://`，三个 hash 合同与 0017
  RAG artifact 相同，`output_hash=artifact_hash`
- `dimension_count`、`candidate_count`、`supported_dimension_count`、
  `possible_duplicate_count`，均非负且不超过相应总数
- `generated_at timestamptz NOT NULL`

Exact FK 到 generation spec，整行 immutable。Candidate artifact 使用
`knowledge-question-candidate-artifact-v1`，只存项目 DTO 和 source IDs。

### `knowledge_question_candidates`

- identity/context：`id`、`project_id`、`campaign_id`、`generated_by_job_id`、
  `adapter_candidate_id`
- plan：`dimension_key`、`variant_index integer BETWEEN 1 AND 3`、
  `turn_index integer BETWEEN 1 AND 3`、`parent_candidate_id uuid NULL`
- text：`query_text`、`query_text_hash`、`normalized_text_hash`（均小写 SHA-256）
- semantic dedup：`semantic_fingerprint`、`embedding vector(1024)`、
  `embedding_model_key='geo-question-semantic-hash-v1'`、
  `nearest_candidate_id uuid NULL`、`nearest_similarity numeric(5,4) NULL`、
  `dedup_status IN ('unique','possible_duplicate','exact_duplicate')`
- review：`workflow_status IN ('pending_review','approved','rejected')`、`reviewed_by`、
  `review_notes`、`reviewed_at`
- `created_at`、`updated_at`

Exact FK 到 spec + dimension；parent/nearest 自 FK 必须仍在同 Job/Project/Campaign。唯一键：
`(generated_by_job_id, adapter_candidate_id)` 和
`(generated_by_job_id, dimension_key, variant_index)`。Review 只能
`pending_review -> approved|rejected` 一次；`exact_duplicate` 不能批准；批准
`possible_duplicate` 必须有非空 review notes。候选 identity、text、embedding、来源和 dedup 结果
不可修改。

`query_text_hash` 对原问题 UTF-8 求 SHA-256；`normalized_text_hash` 对 Unicode NFKC、casefold、
折叠空白和统一终止标点后的文本求 SHA-256。`semantic_fingerprint` 是模型在受控维度和来源内
生成的规范化意图短语，必须非空，不得包含来源外事实。

`geo-question-semantic-hash-v1` 固定算法：对规范化问题、semantic fingerprint 和九个维度快照
生成 Unicode 字符 unigram/bigram、词 token/bigram；使用 SHA-256 signed feature hashing 投影到
1024 维并 L2 normalize。先按 normalized hash/semantic fingerprint 标记重复，再在同
Project/Campaign/Job 内用 pgvector cosine 距离比较；相似度达到 spec threshold 标为
`possible_duplicate`。模型语义 fingerprint + pgvector 只是辅助，最终批准仍由人完成。

### 候选来源表

`knowledge_question_candidate_fact_sources`：candidate exact context +
`fact_candidate_id`，复合 FK 必须指向该 Job 的 frozen Fact input。
`knowledge_question_candidate_entity_sources`：candidate exact context +
`graph_entity_id`，复合 FK 必须指向该 Job 的 frozen Entity input。

二者 immutable。Deferred constraint 要求每个 candidate 至少一个 Fact source；candidate artifact、
数据库 source rows 和模型返回 source IDs 必须一致。

## 4. QuestionSet 版本

### `knowledge_question_sets`

- `id uuid PRIMARY KEY`
- `project_id`、`campaign_id`
- `series_id uuid NOT NULL`、`previous_version_id uuid NULL`、`version_number integer > 0`
- `generated_by_job_id uuid NOT NULL`
- `name text NOT NULL`
- `status IN ('draft','approved','frozen')`
- freeze measurements：`dimension_count`、`covered_dimension_count`、
  `possible_duplicate_count`、`coverage_ratio numeric(5,4)`、
  `duplicate_ratio numeric(5,4)`、`content_hash text NULL`
- actors/times：created、approved、frozen

根版本要求 `id=series_id, previous_version_id IS NULL, version_number=1`；后续版本要求相同
series、精确 previous、`version_number=previous+1`。每 previous 只有一个 successor。
Exact FK 到 generation spec；唯一 `(series_id, version_number)`、`(id,campaign_id,project_id)`、
`(id,campaign_id,project_id,content_hash)`。

状态：

- draft：无批准/冻结 metadata，`content_hash IS NULL`
- approved：批准 metadata 完整、无冻结 metadata/hash
- frozen：批准/冻结 metadata 完整、content hash 完整

只允许 `draft -> approved -> frozen`。Identity/measurements 不可改；冻结后全行不可改/删。
Approve/freeze 时重新验证所有 source Fact active-approved、graph entity current。
Freeze 要求：item 非空、`covered_dimension_count / dimension_count >= 0.90`、
`possible_duplicate_count / item_count <= 0.10`、无 exact duplicate、每个 item candidate 已批准。

### `knowledge_question_set_items`

- `id uuid PRIMARY KEY`
- Set exact context + `generated_by_job_id` + `question_candidate_id`
- `ordinal > 0`
- immutable snapshots：`dimension_key`、`query_text_snapshot`、`query_text_hash`、
  `normalized_text_hash`、`query_kind_snapshot`、`query_cluster_key`、`source_lineage_hash`
- `created_at`

唯一 `(question_set_id, ordinal)`、`(question_set_id, question_candidate_id)`、
`(question_set_id, normalized_text_hash)`；exact FK 保证 candidate 属于同一 generation job。
INSERT 只接受 approved candidate 且 snapshot/hash 完全一致。Item 从 INSERT 起 immutable，不允许删。

QuestionSet content hash 由稳定排序的 Set identity、generation job/input hashes 和全部 item snapshot/
source lineage 计算；0019 提供 SQL recompute function，freeze trigger 必须核对 Application 提交值。

## 5. Monitoring Protocol 显式绑定

`monitoring_protocols` 增加：

- `question_set_id uuid NULL`
- `question_set_hash text NULL`
- `question_set_bound_by uuid NULL REFERENCES identities(id)`
- `question_set_bound_at timestamptz NULL`

四列必须全 NULL 或全非 NULL。Exact FK
`(question_set_id,campaign_id,project_id,question_set_hash)` 指向 frozen QuestionSet exact key。
只允许 draft Protocol 从 NULL 一次变为绑定值；之后不可解绑/换版本。

`monitoring_query_suggestions` 和 `monitoring_protocol_queries` 各增加
`question_set_item_id uuid NULL`、`question_candidate_id uuid NULL`；两列成对。Exact FK 同时证明
item/candidate/Protocol-bound set/Project/Campaign。手工 Protocol 继续使用 NULL。

绑定 repository 在单事务中：

1. `FOR UPDATE` draft Protocol 和 frozen QuestionSet；校验 Campaign/Project。
2. 一次性写 Protocol binding 四列。
3. 对全部 Set item 按 ordinal 插入 approved suggestion（suggested/decided actor 都是 binder）。
4. 创建现有 `monitoring_queries`。
5. 创建现有 `monitoring_protocol_queries`，快照必须来自 Set item，cluster key 使用 item snapshot。

DB deferred gate 要求绑定后的 query inventory 与 Set item 双向相等且数量一致；绑定 Protocol 禁止再
插入无 item lineage 的 suggestion/query。现有 approve/freeze gate 增加该完整性校验。
`protocol_hash()` 必须加入 `question_set_id`、`question_set_hash` 和每个 item ID；历史无绑定
Protocol 仍按原合同工作。

## 6. Prompt Simulation 的 GEO 问题绑定

`prompt_simulations` 增加：

- `simulation_purpose text NOT NULL DEFAULT 'content_preview'
  CHECK IN ('content_preview','geo_question_test')`
- `question_set_id`、`question_set_hash`、`question_set_item_id`、
  `question_candidate_id`，均 nullable

Shape：content preview 四列全 NULL；geo question test 四列全非 NULL。Exact FK 要求 frozen Set、
item、candidate 与 simulation 的 Project/Campaign 一致。INSERT trigger 额外要求：

- QuestionSet 已 frozen；item candidate 仍是 approved；
- item 的每个 Fact source 已有 `knowledge_fact_evidence_lineages`，且对应 Evidence 出现在
  `prompt_simulation_evidence`；
- Opportunity、Destination、binding 和 approved Prompt Release 继续由现有
  `opportunity-binding-v2` trigger/repository 校验。

GEO simulation 的 canonical `input_snapshot` 增加
`question_binding={question_set_id,question_set_hash,item_id,candidate_id,question_text,
dimension_key,source_fact_ids,source_entity_ids}`，input hash 必须覆盖它。Worker result artifact 同样
保存该 binding。现有表的 `CHECK(test_only)` 与 `CHECK(NOT publication_eligible)` 不得放宽。

0019 不向 Publication、Submission、Observation、Metric 或 Report 增加 Simulation FK，也不创建
这些对象。回归测试必须在仿真前后检查上述真实业务表记录数不变。

## 7. Repository/Worker SQL 顺序

1. Enqueue：锁定 Campaign、active-approved Facts/current entities；展开且限制维度；插入 Durable
   Job/spec/dimensions/frozen inputs/outbox。Job input hash覆盖完整有序维度与 source snapshots。
2. Worker load：再次验证 frozen inputs 当前有效；任何 supersede/withdraw/archive 都 fail closed。
3. 生成：按维度批次调用现有 audited gateway；每次调用走 `model_call_logs` 预留/终态事件和 Job
   总预算。模型只返回 question text、dimension/variant、parent、semantic fingerprint、source IDs。
4. Validate：精确 schema、Project/Campaign、source membership、turn/parent、文本边界；无 Fact source
   的候选丢弃并记 validation finding，不得进入候选表。
5. Dedup：规范化 hash -> semantic fingerprint -> pgvector cosine；保存最近候选及 similarity。
6. Persist：先 MinIO canonical artifact，再在 fenced transaction 写 result/candidates/source rows并完成 Job。
7. Review：App role only；一次 decision。跨 Project/Campaign 返回 not found。
8. Set：从同 Job 的 approved candidates 创建 immutable draft/items；approve；freeze 时重算 gate/hash。
9. Bind：按第 5 节执行单事务完整投影。
10. Simulation：扩展现有 create API/repository，不能绕开 Opportunity Release binding 或 Evidence。

## 8. RLS、权限、降级

所有新表 `ENABLE/FORCE RLS`，project policy 使用 `geo_current_project_ids()`。App：SELECT、candidate
review、QuestionSet state/binding；Worker：spec/input SELECT、result/candidate INSERT；Readonly：SELECT。
所有动态候选/Set/来源 identity 使用 immutable trigger。

0019 downgrade 必须先检查：

- 任一 generation spec/result/dimension/input/candidate/source/QuestionSet/item 存在；或
- 任一 Protocol/Simulation 的 QuestionSet binding 非 NULL。

任一条件成立即 `55000` fail closed，提示先保留 0019；禁止 DELETE 业务数据、清空绑定或把新记录
伪装成 legacy。只有零业务数据/零绑定时才允许 drop 新表、trigger/function/index 和新增列。

## 9. 必须通过的测试

- `F019-INT-03`：真实 PG，生成来源、semantic dedup、人工批准、90% coverage、冻结不可变、完整
  Protocol binding；缺项/加项/跨 Campaign/跨 Project 全失败。
- `F019-INT-04`：两个 Project 使用相同文本/semantic fingerprint/embedding，候选、nearest search、
  QuestionSet、Protocol 全隔离。
- `F019-REG-01`：GEO simulation 真实 Worker/model log/MinIO artifact；始终 test-only，且
  Publication/Submission/Monitoring Observation/Metric/Report 均零新增。
- `F019-WEB-01`：Admin Chromium 完成 generation -> candidate review -> frozen QuestionSet ->
  Protocol binding -> GEO simulation，并显示 Job、来源、覆盖率、重复标记和不可发布状态。
