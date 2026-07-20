# F-019 RAG 核心集成合同

## 状态与边界

- F-019 选型 Gate 已完成。`project-native-rag-v1` 与
  `llamaindex-property-graph-v1` 均以真实 provider 调用获得 `0.99`，全部硬门槛通过；按
  质量接近后比较成本、耗时的冻结规则，正式选择 `project-native-rag-v1`。
- PostgreSQL 是候选、审批状态和正式 Knowledge Graph 的唯一业务真源。MinIO 只保存可复核
  的 canonical candidate artifact；框架对象和私有索引不进入 Domain、API 或业务表。
- 本合同只覆盖批次 3 的 Fact/Entity/Relation 核心。QuestionSet、Protocol 绑定、pgvector
  检索和 synthetic Simulation 属于批次 4，不在本迁移中伪造 embedding 或测试观测。
- 不扩展 Catalog 的 `product_entities.entity_type`。10 类广义实体属于 Knowledge Graph；仅
  brand/product/competitor/market 可经独立人工动作映射已有 Catalog Entity。

## Worker 合同

1. `knowledge.process` 在 Source/Run/Document/Chunk 原子落库后创建子 Job
   `knowledge.rag.extract`，并写同一 `broker_outbox`。
2. Job 固定 adapter release、selection manifest SHA-256、模型和调用预算。运行时 selection
   文件及所选 benchmark report 必须通过 hash 校验，且 enqueue hash 必须一致。
3. 每个 Chunk 是一个 adapter 输入 fragment，所有 fragment 使用同一 Document group。只有
   整份 Document 没有可追踪 Fact 时失败；候选来源仍精确定位到 Chunk 和 `line:<n>`。
4. 每次 provider I/O 前写 `model_call_logs.reserved`，随后追加 succeeded/failed 终态；沿用
   Durable Job lease、heartbeat、重试和取消，不增加第二套模型日志或任务系统。
5. canonical artifact 使用 `knowledge-rag-candidate-artifact-v1`，内容哈希键写入现有 MinIO：
   `knowledge-rag-artifacts/{project}/{logical_source}/{run}/{sha256}.json`。
6. Candidate revision、候选行和 Durable Job completion 在一个 fenced PostgreSQL transaction
   中提交。MinIO 上传先发生，失败重试覆盖同一内容地址；事务失败最多留下不可达的同哈希对象。

## 迁移顺序

迁移由单一 owner 在当前线性 Alembic head 之后实施；F-019 代码不得自行创建第二个 head。
以下名称和列是生产 repository 已采用的冻结合同。

### 1. Immutable Source revision

`knowledge_sources` 增加：

- `logical_source_id uuid`：回填为现有 `id`，再设 `NOT NULL`。
- `supersedes_source_id uuid NULL`。
- `UNIQUE (id, project_id, logical_source_id)`。
- `(logical_source_id, project_id) -> knowledge_sources(id, project_id)`。
- `(supersedes_source_id, project_id, logical_source_id) ->
  knowledge_sources(id, project_id, logical_source_id)`。
- `UNIQUE (supersedes_source_id, project_id)`：NULL root 不冲突，每个 revision 最多一个直接后继，
  禁止并发分支按完成顺序覆盖新内容。
- 根 revision 必须 `id = logical_source_id AND supersedes_source_id IS NULL`；后续 revision 必须
  `id <> logical_source_id AND supersedes_source_id IS NOT NULL`。

新内容必须创建新 Source 行；旧 Source、Document、Chunk、Fact 和 Evidence lineage 不改写。
Source 首次从 queued/processing 进入 ready 时允许写抓取结果和 content hash；已有 content hash
之后，title/source kind/URL/filename/media type/raw content/content hash/logical identity 均不可变。
同内容 reprocess 可新建 Run；远端内容已变化时旧 Source 回到 ready 并要求显式创建 revision。
新 revision 只有在 RAG 成功后才使同 logical source 的旧 ready Source archived，避免切换中断。
切换时旧 revision 的 active Chunk 必须 disabled，旧 active candidate 必须 superseded。显式归档
必须同时取消该 Source 尚未终态的 `knowledge.process` 与 `knowledge.rag.extract` Job，并将 legacy/RAG
candidate 统一 withdrawn，禁止运行中的父任务把已归档 Source 恢复为 ready。

### 2. RAG Job spec

`knowledge_rag_job_specs`：

- `job_id uuid PRIMARY KEY`
- `project_id uuid NOT NULL`
- `pipeline_run_id uuid NOT NULL`
- `source_id uuid NOT NULL`
- `document_id uuid NOT NULL`
- `configured_model text NOT NULL`
- `model_call_budget integer NOT NULL CHECK (> 0)`
- `adapter_release text NOT NULL CHECK IN
  ('project-native-rag-v1','llamaindex-property-graph-v1')`
- `selection_manifest_hash text NOT NULL`，小写 SHA-256
- `requested_by uuid NOT NULL REFERENCES identities(id)`
- `created_at timestamptz NOT NULL DEFAULT clock_timestamp()`
- `UNIQUE (job_id, project_id, pipeline_run_id, source_id, document_id)`

复合 FK 必须分别指向 Durable Job、Run exact source key 和 Document exact context key；触发器
限定 Job kind 为 `knowledge.rag.extract`。同一 Run/Document 只允许一个 spec。

### 3. RAG revision

`knowledge_rag_revisions`：

- identity/context：`id`、`project_id`、`job_id`、`pipeline_run_id`、`source_id`、
  `logical_source_id`、`document_id`
- frozen execution：`adapter_release`、`selection_manifest_hash`、`input_hash`
- evidence：`output_hash`、`artifact_uri`、`artifact_hash`
- lifecycle：`lifecycle_status IN ('active','superseded','withdrawn')`
- actor/time：`created_by`、`created_at`、`completed_at`、`superseded_at`、`withdrawn_at`

哈希均为小写 SHA-256；artifact URI 必须为 `s3://`；当前 v1 要求
`output_hash = artifact_hash`。复合 FK 指向 Job spec、Run、Source exact logical key、Document。
`UNIQUE(job_id, project_id)`、`UNIQUE(pipeline_run_id, document_id, adapter_release, input_hash)`，
且每 `(project_id, logical_source_id)` 最多一个 active revision。身份、输入、输出和工件不可改；
唯一允许状态转换是 `active -> superseded|withdrawn`，并要求对应时间戳，其后不可再改。

### 4. Fact candidate 扩展

`knowledge_fact_candidates` 增加：

- `rag_revision_id uuid NULL`
- `extractor_release text NOT NULL DEFAULT 'legacy-sentence-v1'`
- `source_locator text NULL`
- `lifecycle_status text NOT NULL DEFAULT 'active'
  CHECK IN ('active','superseded','withdrawn')`

Legacy 行保持 `rag_revision_id IS NULL`、`extractor_release='legacy-sentence-v1'`，不得补造 revision。
RAG 行必须有 revision、选型 adapter release 和 `line:<positive integer>` locator。Review status
继续独立使用 pending_review/approved/rejected；只有 lifecycle=active 可审批或转 Evidence。
增加 `(id, project_id, pipeline_run_id, source_id, document_id)` exact key及 revision 复合 FK。删除旧的
全局 `UNIQUE(pipeline_run_id, statement_hash)`，改为两个互不混淆的身份约束：legacy 使用
`UNIQUE INDEX (pipeline_run_id, statement_hash) WHERE rag_revision_id IS NULL`，RAG 使用
`UNIQUE(rag_revision_id, statement_hash)`。同一句话从 legacy 流程进入 RAG 时必须新建独立 RAG Fact
行，旧行只转为 superseded；禁止通过 upsert 把旧行的 `rag_revision_id` 从 NULL 改成 revision。

`knowledge_fact_candidate_sources`：project、fact candidate、revision、Run、Source、Document、
Chunk、source locator；复合 FK 必须证明 Fact/Revision/Chunk 处于同一完整上下文。主键至少覆盖
`(project_id, fact_candidate_id, rag_revision_id, chunk_id, source_locator)`，支持同一事实多 Chunk
来源，禁止跨 Project/Run 拼接。

### 5. Entity/Relation candidates

允许 entity type：`brand, product, competitor, feature, specification, use_case, persona,
pain_point, market, channel`。

`knowledge_entity_candidates`：完整 revision/Run/Source/Document 上下文、
`adapter_candidate_id`、entity type、`name`、`name_hash`、`workflow_status`、
`lifecycle_status`、review actor/notes/time、`graph_entity_id`、`generated_by_job_id` 和时间戳。
唯一键为 revision/type/name hash 及 revision/adapter candidate ID。pending/rejected 不得有
graph entity；approved 必须有 reviewed metadata 和 graph entity。

`knowledge_entity_candidate_sources`：candidate、revision、Run、Source、Document、Chunk、
`line:<n>`，所有边使用精确复合 FK。

允许 predicate：`belongs_to, has_feature, has_specification, competes_with,
belongs_to_market, uses_channel, compatible_with, has_pain_point, supports_use_case`。

`knowledge_relation_candidates`：完整上下文、Chunk、adapter candidate ID、subject entity
candidate、predicate、object entity candidate、source locator、workflow/lifecycle、review metadata、
`graph_relation_id`、generated Job 和时间戳。两端 candidate 必须属于同一 revision/context；
subject 不得等于 object；唯一键为 revision/两端/predicate/Chunk。approved 必须两端已 approved
且有 approved graph entity。

### 6. Validation findings

`knowledge_rag_validation_findings` 保存 project、revision、Run、Source、Document、Chunk、
candidate kind、reason code、candidate SHA-256 和 created_at。只保存哈希，不保存被拒绝的原始
provider 内容。唯一键覆盖 revision/Chunk/kind/reason/hash；所有上下文使用复合 FK。

### 7. Approved Knowledge Graph

`knowledge_graph_entities`：10 类实体、canonical name/name hash、`status current|archived`、
approved actor/time、可空 `catalog_entity_id`、时间戳；唯一 `(project,type,name_hash)`。Catalog FK
必须包含 project。数据库触发器或应用共同保证只有四个可映射类型能设置 Catalog ID；应用还
强制相同 type 和 canonical name，且映射只能经独立人工动作完成。

`knowledge_graph_entity_sources`：approved graph entity、origin entity candidate、revision、
Run、Source、Document、Chunk、locator、approved actor、`lifecycle_status
active|superseded|withdrawn`，全部为精确复合 FK。

`knowledge_graph_relations`：subject approved graph entity、predicate、object approved graph
entity、`status current|archived`、approved actor/time 和时间戳；唯一
`(project,subject,predicate,object)`。两端必须是同 Project 的 approved graph entity。

`knowledge_graph_relation_sources`：approved relation、origin relation candidate、revision 和
完整 Source lineage、locator、actor、lifecycle。Source revision supersede/withdraw 时先停用
这些来源；没有 active 来源的 approved graph row 变为 archived。

### 8. RLS、索引与回滚

- 所有新表 `ENABLE/FORCE ROW LEVEL SECURITY`，复用 `geo_current_project_ids()`；geo_app 和
  geo_worker 按最小读写授权，geo_readonly 只读。
- 至少建立 project + lifecycle/workflow、revision、source/logical source、Job、review queue
  索引；所有 FK 有对应 leading-column 索引。
- down migration 只允许在 RAG Job/spec/revision/candidate/graph/source-revision 新数据为空时
  执行；否则显式失败，禁止为可回滚而删除业务数据或把新事实伪装成 legacy。

## 已实现代码边界

- `geo_core.rag`：框架中立 DTO、selected adapter factory、hash-addressed runtime selection。
- `geo_core.knowledge.rag_domain`：claim、10 类实体/9 类关系、lineage/工件验证。
- `geo_core.knowledge.rag_worker`：Durable lease、审计模型调用、MinIO 工件、fail-closed 执行。
- `geo_core.knowledge.rag_postgres`：候选 finalization、revision supersede、model log 复用。
- `geo_core.knowledge.rag_application`：Source revision/archive、候选人工审批、approved graph 和
  显式 Catalog mapping。
- `geo_worker.tasks`：`knowledge.process -> knowledge.rag.extract` 生产 composition。

迁移可用后仍需执行 F019-INT-01/02：真实 PostgreSQL + MinIO 的导入、同 key 重放、同内容
reimport、内容 update、archive/delete、lease retry，以及两个 Project 相似内容的交叉读写负测。
