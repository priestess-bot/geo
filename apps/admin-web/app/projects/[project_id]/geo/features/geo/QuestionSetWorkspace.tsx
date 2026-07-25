import type {
  KnowledgeQuestionCandidateView,
  KnowledgeQuestionFactView,
  KnowledgeQuestionSetView
} from "@geo/types/geo";
import { ActionForm } from "./ActionForm";
import {
  bindQuestionSetToProtocol,
  createQuestionGeneration,
  createQuestionSet,
  reviewQuestionCandidate,
  transitionQuestionSet
} from "./question-set-actions";
import {
  CommandPanel,
  Empty,
  HiddenProject,
  ResourceBlock,
  SectionHeader,
  ShortId,
  Status,
  TechnicalInfo,
  geoHref
} from "./common";
import type { GeoWorkspaceData } from "./model";
import styles from "./GeoWorkspace.module.css";

export function QuestionSetWorkspace({ projectId, data }: {
  projectId: string;
  data: GeoWorkspaceData;
}) {
  const campaignId = data.selection.campaignId || "";
  const facts = data.questionFacts.data.filter(
    (fact) => fact.status === "approved" && fact.lifecycle_status === "active"
  );
  const candidates = data.questionCandidates.data;
  const approvedCandidates = candidates.filter((item) => item.workflow_status === "approved");
  const factLabels = new Map(facts.map((fact) => [fact.id, fact.source_title]));
  return <section className={styles.workspace} aria-labelledby="question-set-title">
    <div className={styles.pageHeading}>
      <div>
        <h2 id="question-set-title">GEO 测试问题</h2>
        <p>知识来源、候选复核、问题集版本与监测方案绑定</p>
      </div>
      <CommandPanel label="生成测试问题">
        <ResourceBlock resource={data.questionFacts}>{() => <QuestionGenerationForm
          campaignId={campaignId} facts={facts} projectId={projectId}
        />}</ResourceBlock>
      </CommandPanel>
    </div>

    <div className={styles.testBanner} role="status">
      <strong>仅限内部测试</strong>
      <span>仿真固定为仅测试且不可发布</span>
    </div>

    <div className={styles.columns}>
      <section className={styles.panel}>
        <SectionHeader eyebrow="不可变输入" title="生成任务">
          <span className={styles.meta}>{data.questionGenerations.data.length} 次</span>
        </SectionHeader>
        <ResourceBlock resource={data.questionGenerations}>{(jobs) => jobs.length
          ? <div className={styles.list}>{jobs.map((job) => <a
            className={job.job_id === data.selection.questionGenerationJobId
              ? styles.selectedRow : styles.row}
            href={geoHref(projectId, data.selection, {
              question_generation_job_id: job.job_id
            })}
            key={job.job_id}
            data-testid="question-generation-job"
          >
            <span className={styles.rowHeader}>
              <strong>任务 <ShortId value={job.job_id} /></strong><Status value={job.status} />
            </span>
            <span className={styles.meta}>
              <span>{job.dimension_count ?? 0} 个维度</span>
              <span>{job.candidate_count ?? 0} 条候选</span>
              <span>{job.supported_dimension_count ?? 0} 个有来源维度</span>
              <span>{job.possible_duplicate_count ?? 0} 条可能重复</span>
              <span>{job.configured_model}</span>
            </span>
            <TechnicalInfo><span>{job.adapter_release}</span><code>{job.input_hash}</code>
              {job.artifact_hash ? <code>{job.artifact_hash}</code> : null}</TechnicalInfo>
          </a>)}</div>
          : <Empty>尚无测试问题生成任务。</Empty>}
        </ResourceBlock>
      </section>

      <section className={styles.panel}>
        <SectionHeader eyebrow="人工门禁" title="候选问题">
          <span className={styles.meta}>{candidates.length} 条</span>
        </SectionHeader>
        <ResourceBlock resource={data.questionCandidates}>{(items) => items.length
          ? <div className={styles.list}>{items.map((candidate) => <CandidateRow
            campaignId={campaignId}
            candidate={candidate}
            factLabels={factLabels}
            key={candidate.id}
            projectId={projectId}
          />)}</div>
          : <Empty>选择已完成的生成任务后显示候选问题。</Empty>}
        </ResourceBlock>
      </section>
    </div>

    <section className={styles.panel}>
      <SectionHeader eyebrow="版本化清单" title="问题集">
        <CommandPanel label="创建问题集草稿">
          <ActionForm
            action={createQuestionSet}
            disabled={!approvedCandidates.length || !data.selection.questionGenerationJobId}
            submitLabel="创建不可变问题清单"
          >
            <HiddenProject projectId={projectId} />
            <input name="campaign_id" type="hidden" value={campaignId} />
            <input name="generation_job_id" type="hidden"
              value={data.selection.questionGenerationJobId || ""} />
            <label>问题集名称<input name="name" required /></label>
            <label>已批准候选
              <select className={styles.multiSelect} name="candidate_ids" required multiple
                size={Math.min(Math.max(approvedCandidates.length, 3), 10)}>
                {approvedCandidates.map((item) => <option key={item.id} value={item.id}>
                  {item.dimension_key} · {item.query_text}
                </option>)}
              </select>
            </label>
          </ActionForm>
        </CommandPanel>
      </SectionHeader>
      <ResourceBlock resource={data.questionSets}>{(sets) => sets.length
        ? <div className={styles.metricList}>{sets.map((set) => <QuestionSetRow
          data={data}
          key={set.id}
          projectId={projectId}
          set={set}
        />)}</div>
        : <Empty>批准候选后创建问题集草稿。</Empty>}
      </ResourceBlock>
    </section>
  </section>;
}

function QuestionGenerationForm({ campaignId, facts, projectId }: {
  campaignId: string;
  facts: KnowledgeQuestionFactView[];
  projectId: string;
}) {
  return <ActionForm action={createQuestionGeneration} disabled={!campaignId || !facts.length}
    submitLabel="生成候选问题">
    <HiddenProject projectId={projectId} />
    <input name="campaign_id" type="hidden" value={campaignId} />
    <label>已批准事实
      <select className={styles.multiSelect} name="fact_candidate_ids" required multiple
        size={Math.min(Math.max(facts.length, 3), 10)}>
        {facts.map((fact) => <option key={fact.id} value={fact.id}>
          {fact.source_title} · {preview(fact.statement, 120)}
        </option>)}
      </select>
    </label>
    <div className={styles.inline}>
      <label>人群<input name="persona" required placeholder="澳洲住宅业主" /></label>
      <label>主题<input name="subject" required placeholder="机器人割草机" /></label>
    </div>
    <label>场景<textarea name="scenario" required
      placeholder="为中等面积草坪寻找可靠的割草机" /></label>
    <label>意图<input name="intent" required placeholder="比较合适的产品" /></label>
    <div className={styles.inline}>
      <label>漏斗阶段<select name="funnel" defaultValue="consideration">
        <option value="awareness">认知</option><option value="consideration">考虑</option>
        <option value="decision">决策</option><option value="retention">留存</option>
      </select></label>
      <label>问题类型<select name="query_kind" defaultValue="recommendation">
        <option value="recommendation">推荐</option><option value="comparison">比较</option>
        <option value="research">调研</option><option value="support">支持</option>
      </select></label>
    </div>
    <div className={styles.inline}>
      <label>平台<select name="platform" defaultValue="chatgpt_search">
        <option value="chatgpt_search">ChatGPT Search</option>
        <option value="google_ai_overviews">Google AI Overviews</option>
        <option value="google_search">Google Search</option>
        <option value="perplexity">Perplexity</option><option value="gemini">Gemini</option>
        <option value="other">其他</option>
      </select></label>
      <label>品牌范围<select name="brand_scope" defaultValue="non_brand">
        <option value="non_brand">非品牌</option><option value="brand">品牌</option>
        <option value="competitor">竞品</option>
      </select></label>
    </div>
    <div className={styles.inline}>
      <label>区域<input name="region" required defaultValue="AU" /></label>
      <label>语言<input name="language" required defaultValue="en-AU" /></label>
    </div>
    <details><summary>图谱与模型设置</summary><div className={styles.formInset}>
      <label>批准图谱实体 ID<textarea name="graph_entity_ids" /></label>
      <label>竞品实体 ID<input name="competitor_entity_id" /></label>
      <label>语义重复阈值<input name="semantic_duplicate_threshold" type="number"
        min="0.8" max="1" step="0.0001" defaultValue="0.92" /></label>
      <label>模型调用预算<input name="model_call_budget" type="number"
        min="1" max="1000" defaultValue="60" /></label>
    </div></details>
    {!facts.length ? <Empty>知识库中没有已批准且启用的事实。</Empty> : null}
  </ActionForm>;
}

function CandidateRow({ campaignId, candidate, factLabels, projectId }: {
  campaignId: string;
  candidate: KnowledgeQuestionCandidateView;
  factLabels: ReadonlyMap<string, string>;
  projectId: string;
}) {
  return <article className={styles.row} data-testid="question-candidate">
    <span className={styles.rowHeader}>
      <strong>{candidate.query_text}</strong><Status value={candidate.workflow_status} />
    </span>
    <span className={styles.meta}>
      <span>{candidate.dimension_key}</span><span>第 {candidate.turn_index} 轮</span>
      <span>变体 {candidate.variant_index}</span><span>{dedupLabel(candidate.dedup_status)}</span>
      {candidate.nearest_similarity === null ? null
        : <span>最近相似度 {(candidate.nearest_similarity * 100).toFixed(1)}%</span>}
    </span>
    <div className={styles.meta}>
      {candidate.fact_source_ids.map((id) => <span className={styles.sourceBadge} key={id}>
        事实 · {factLabels.get(id) || id.slice(0, 8)}
      </span>)}
      {candidate.entity_source_ids.map((id) => <span className={styles.sourceBadge} key={id}>
        实体 · {id.slice(0, 8)}
      </span>)}
    </div>
    <TechnicalInfo label="语义与来源哈希">
      <span>{candidate.semantic_fingerprint}</span><code>{candidate.query_text_hash}</code>
    </TechnicalInfo>
    {candidate.workflow_status === "pending_review" ? <ActionForm
      action={reviewQuestionCandidate}
      submitLabel="保存人工审核"
    >
      <HiddenProject projectId={projectId} />
      <input name="campaign_id" type="hidden" value={campaignId} />
      <input name="candidate_id" type="hidden" value={candidate.id} />
      <div className={styles.inline}>
        <label>结论<select name="decision" defaultValue={candidate.dedup_status === "exact_duplicate"
          ? "rejected" : "approved"}>
          {candidate.dedup_status !== "exact_duplicate"
            ? <option value="approved">批准</option> : null}
          <option value="rejected">拒绝</option>
        </select></label>
        <label>审核说明<input name="notes" required /></label>
      </div>
    </ActionForm> : candidate.review_notes ? <span className={styles.meta}>{candidate.review_notes}</span> : null}
  </article>;
}

function QuestionSetRow({ data, projectId, set }: {
  data: GeoWorkspaceData;
  projectId: string;
  set: KnowledgeQuestionSetView;
}) {
  const campaignId = data.selection.campaignId || "";
  const draftProtocols = data.protocols.data.filter(
    (protocol) => protocol.status === "draft" && !protocol.question_set_id
  );
  const boundProtocols = data.protocols.data.filter((protocol) => protocol.question_set_id === set.id);
  return <article className={styles.metricSnapshot} data-testid="question-set">
    <span className={styles.rowHeader}>
      <strong>{set.name} · v{set.version_number}</strong><Status value={set.status} />
    </span>
    <div className={styles.metricEvidence}>
      <div><span>维度覆盖</span><strong>{set.covered_dimension_count}/{set.dimension_count}
        · {percent(set.coverage_ratio)}</strong></div>
      <div><span>可能重复</span><strong>{set.possible_duplicate_count}
        · {percent(set.duplicate_ratio)}</strong></div>
      <div><span>问题数量</span><strong>{set.items.length}</strong></div>
    </div>
    <details className={styles.metricDetails}><summary>问题清单与来源溯源</summary>
      <table className={styles.table}><thead><tr><th>#</th><th>问题</th><th>维度 / 簇</th><th>来源</th></tr></thead>
        <tbody>{set.items.map((item) => <tr key={item.id}><td>{item.ordinal}</td>
          <td>{item.query_text_snapshot}</td><td>{item.dimension_key}<br />{item.query_cluster_key}</td>
          <td><ShortId value={item.source_lineage_hash} /></td></tr>)}</tbody></table>
    </details>
    <div className={styles.toolbar}>
      {set.status === "draft" ? <ActionForm action={transitionQuestionSet} submitLabel="批准问题集">
        <HiddenProject projectId={projectId} /><input name="campaign_id" type="hidden" value={campaignId} />
        <input name="question_set_id" type="hidden" value={set.id} />
        <input name="command" type="hidden" value="approve" />
      </ActionForm> : null}
      {set.status === "approved" ? <ActionForm action={transitionQuestionSet} submitLabel="冻结问题集">
        <HiddenProject projectId={projectId} /><input name="campaign_id" type="hidden" value={campaignId} />
        <input name="question_set_id" type="hidden" value={set.id} />
        <input name="command" type="hidden" value="freeze" />
      </ActionForm> : null}
    </div>
    {set.status === "frozen" && set.content_hash ? <>
      {draftProtocols.length ? <ActionForm action={bindQuestionSetToProtocol}
        submitLabel="绑定到 draft 监测方案">
        <HiddenProject projectId={projectId} />
        <input name="campaign_id" type="hidden" value={campaignId} />
        <input name="question_set_id" type="hidden" value={set.id} />
        <input name="confirmed_content_hash" type="hidden" value={set.content_hash} />
        <label>draft 监测方案<select name="protocol_id" required defaultValue="">
          <option value="" disabled>选择监测方案</option>
          {draftProtocols.map((protocol) => <option key={protocol.id} value={protocol.id}>
            {protocol.name}
          </option>)}
        </select></label>
      </ActionForm> : null}
      {boundProtocols.map((protocol) => <div className={styles.notice} key={protocol.id}>
        <span>已绑定监测方案：<strong>{protocol.name}</strong></span><Status value={protocol.status} />
      </div>)}
      <a className="button secondary" href={geoHref(projectId, data.selection, {
        section: "placement", placement_stage: "simulation", question_set_id: set.id
      })}>进入内部 GEO 仿真</a>
      <TechnicalInfo label="冻结身份"><code>{set.id}</code><code>{set.content_hash}</code></TechnicalInfo>
    </> : null}
  </article>;
}

function dedupLabel(value: KnowledgeQuestionCandidateView["dedup_status"]): string {
  if (value === "possible_duplicate") return "可能重复";
  if (value === "exact_duplicate") return "完全重复";
  return "语义独立";
}

function percent(value: number): string {
  return `${(value * 100).toFixed(value === 0 || value === 1 ? 0 : 1)}%`;
}

function preview(value: string, max: number): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  return normalized.length > max ? `${normalized.slice(0, max - 1)}…` : normalized;
}
