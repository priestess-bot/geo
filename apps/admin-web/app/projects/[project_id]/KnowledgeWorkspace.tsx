import type { CatalogEntity } from "./catalogTypes";
import { FactEvidencePromotionForm } from "./FactEvidencePromotionForm";
import { KnowledgeActionForm } from "./KnowledgeActionForm";
import {
  disableKnowledgeChunk,
  importKnowledgeSource,
  reprocessKnowledgeSource,
  reviewKnowledgeFact,
  reviewKnowledgeFinding
} from "./knowledgeActions";
import type {
  KnowledgeChunk, KnowledgeFact, KnowledgeProblem, KnowledgeRun, KnowledgeWorkspaceData
} from "./knowledgeTypes";
import styles from "./KnowledgeWorkspace.module.css";

const views = [
  ["import", "导入"],
  ["processing", "处理任务"],
  ["chunks", "Chunk 可视化"],
  ["search", "检索"],
  ["dashboard", "知识库看板"],
  ["quality", "质检"],
  ["trace", "证据追踪"]
] as const;

export function KnowledgeWorkspace({
  canPromote,
  data,
  entities,
  projectId
}: {
  canPromote: boolean;
  data: KnowledgeWorkspaceData;
  entities: CatalogEntity[];
  projectId: string;
}) {
  return (
    <div className={styles.workspace}>
      <header className={styles.header}>
        <div><p className="eyebrow">Enterprise knowledge</p><h2>导入、清洗与事实治理</h2></div>
        <p>企业来源经过解析、清洗、分块、事实提取和质量检查后，才能进入 Evidence Pack。</p>
      </header>
      <nav className={styles.subnav} aria-label="知识库处理阶段">
        {views.map(([id, label]) => <a className={data.activeView === id ? styles.active : ""} href={href(projectId, id)} key={id}>{label}</a>)}
      </nav>
      <Summary data={data} />
      {data.activeView === "import" ? <ImportView data={data} projectId={projectId} /> : null}
      {data.activeView === "processing" ? <ProcessingView data={data} projectId={projectId} /> : null}
      {data.activeView === "chunks" ? <ChunksView chunks={data.chunks.data} projectId={projectId} /> : null}
      {data.activeView === "search" ? <SearchView data={data} projectId={projectId} /> : null}
      {data.activeView === "dashboard" ? <DashboardView data={data} /> : null}
      {data.activeView === "quality" ? <QualityView data={data} projectId={projectId} /> : null}
      {data.activeView === "trace" ? <TraceView canPromote={canPromote} data={data} entities={entities} projectId={projectId} /> : null}
      <Problems data={data} />
    </div>
  );
}

function Summary({ data }: { data: KnowledgeWorkspaceData }) {
  const dashboard = data.dashboard.data;
  const metrics = [
    ["来源", dashboard.sources], ["成功任务", dashboard.succeeded_runs],
    ["活动 Chunk", dashboard.active_chunks], ["待审事实", dashboard.pending_facts],
    ["开放问题", dashboard.open_findings]
  ];
  return <section className={styles.metrics} aria-label="知识库摘要">{metrics.map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}</section>;
}

function ImportView({ data, projectId }: { data: KnowledgeWorkspaceData; projectId: string }) {
  return <div className={styles.stack}>
    <section className={styles.section}>
      <div className={styles.sectionHeading}><div><p>Source intake</p><h3>导入企业知识</h3></div><span>单个来源上限 5 MB</span></div>
      <div className={styles.importGrid}>
        <KnowledgeActionForm action={importKnowledgeSource} submitLabel="导入 URL">
          <input name="project_id" type="hidden" value={projectId} /><input name="source_kind" type="hidden" value="url" />
          <label>来源标题<input name="title" required placeholder="ADVINSYS 官方网站" /></label>
          <label>公开 URL<input name="source_url" required type="url" placeholder="https://www.example.com/page" /></label>
          <input name="media_type" type="hidden" value="text/html" />
        </KnowledgeActionForm>
        <KnowledgeActionForm action={importKnowledgeSource} submitLabel="上传文件">
          <input name="project_id" type="hidden" value={projectId} /><input name="source_kind" type="hidden" value="file" />
          <label>来源标题<input name="title" required placeholder="产品资料或授权说明" /></label>
          <label>文件<input accept=".txt,.md,.csv,.json,.html,.htm,.pdf,.docx" name="file" required type="file" /></label>
        </KnowledgeActionForm>
        <KnowledgeActionForm action={importKnowledgeSource} submitLabel="导入文本">
          <input name="project_id" type="hidden" value={projectId} /><input name="source_kind" type="hidden" value="text" />
          <label>来源标题<input name="title" required placeholder="客服记录或授权消费者描述" /></label>
          <label>文本内容<textarea name="content_text" required rows={5} /></label>
          <input name="media_type" type="hidden" value="text/plain" />
        </KnowledgeActionForm>
      </div>
    </section>
    <section className={styles.section}>
      <div className={styles.sectionHeading}><div><p>Source assets</p><h3>已导入来源</h3></div><span>{data.sources.data.length} 条</span></div>
      <div className={styles.tableWrap}><table><thead><tr><th>来源</th><th>类型</th><th>大小</th><th>状态</th><th>操作</th></tr></thead><tbody>
        {data.sources.data.map((source) => <tr key={source.id}><td><strong>{source.title}</strong><small>{source.source_url || source.filename || source.id}</small></td><td>{source.media_type}</td><td>{formatBytes(source.content_bytes)}</td><td><Status value={source.status} />{source.error_detail ? <small className={styles.error}>{source.error_detail}</small> : null}</td><td><div className={styles.actions}><a href={`/api/knowledge/source-asset?project_id=${projectId}&source_id=${source.id}`}>下载</a><KnowledgeActionForm action={reprocessKnowledgeSource} className={styles.inlineForm} submitLabel="重处理"><input name="project_id" type="hidden" value={projectId} /><input name="source_id" type="hidden" value={source.id} /></KnowledgeActionForm></div></td></tr>)}
        {!data.sources.data.length ? <tr><td colSpan={5}>尚未导入企业知识来源。</td></tr> : null}
      </tbody></table></div>
    </section>
  </div>;
}

function ProcessingView({ data, projectId }: { data: KnowledgeWorkspaceData; projectId: string }) {
  const selectedId = data.stages.data[0]?.pipeline_run_id || data.runs.data[0]?.id;
  return <div className={styles.processingGrid}>
    <section className={styles.section}><div className={styles.sectionHeading}><div><p>Durable jobs</p><h3>处理任务</h3></div><span>{data.runs.data.length} 次</span></div><div className={styles.runList}>{data.runs.data.map((run) => <a className={run.id === selectedId ? styles.selectedRun : ""} href={`${href(projectId, "processing")}&pipeline_run_id=${run.id}`} key={run.id}><span><strong>{run.source_title}</strong><small>{formatDate(run.created_at)}</small></span><Status value={run.status} /></a>)}</div></section>
    <section className={styles.section}><div className={styles.sectionHeading}><div><p>Pipeline stages</p><h3>解析与清洗进度</h3></div><span>{data.stages.data.length}/6</span></div><ol className={styles.stageList}>{data.stages.data.map((stage) => <li key={stage.id}><span className={styles.stageIndex}>{stage.ordinal}</span><div><strong>{stageLabel(stage.stage_key)}</strong><small>{Object.entries(stage.metrics || {}).map(([key, value]) => `${key}: ${String(value)}`).join(" · ") || stage.error_detail || "等待处理"}</small></div><Status value={stage.status} /></li>)}</ol>{!data.stages.data.length ? <p>选择处理任务后查看六阶段状态。</p> : null}</section>
  </div>;
}

function ChunksView({ chunks, projectId }: { chunks: KnowledgeChunk[]; projectId: string }) {
  return <section className={styles.section}><div className={styles.sectionHeading}><div><p>Cleaned corpus</p><h3>Chunk 可视化</h3></div><span>{chunks.length} 条</span></div><div className={styles.chunkList}>{chunks.map((chunk) => <article key={chunk.id}><header><span><strong>{chunk.source_title}</strong><small>Chunk {chunk.chunk_index} · {chunk.char_count} 字符 · {chunk.text_hash.slice(0, 10)}</small></span><Status value={chunk.status} /></header><p>{chunk.text}</p><footer><span>{chunk.quality_flags.join(" · ") || "无质量标记"}</span>{chunk.status === "active" ? <KnowledgeActionForm action={disableKnowledgeChunk} className={styles.inlineForm} submitLabel="禁用"><input name="project_id" type="hidden" value={projectId} /><input name="chunk_id" type="hidden" value={chunk.id} /></KnowledgeActionForm> : null}</footer></article>)}</div>{!chunks.length ? <p>成功处理来源后将在这里显示可追踪 Chunk。</p> : null}</section>;
}

function SearchView({ data, projectId }: { data: KnowledgeWorkspaceData; projectId: string }) {
  return <section className={styles.section}><div className={styles.sectionHeading}><div><p>Corpus search</p><h3>知识检索</h3></div><span>{data.chunks.data.length} 条结果</span></div><form action={`/projects/${projectId}`} className={styles.searchForm} method="get"><input name="tab" type="hidden" value="knowledge" /><input name="knowledge_tab" type="hidden" value="search" /><label>检索词<input defaultValue={data.query} name="knowledge_query" placeholder="产品、能力、保修或使用场景" /></label><button type="submit">检索</button></form><div className={styles.searchResults}>{data.chunks.data.map((chunk) => <article key={chunk.id}><strong>{chunk.source_title} · Chunk {chunk.chunk_index}</strong><p>{chunk.text}</p></article>)}</div></section>;
}

function DashboardView({ data }: { data: KnowledgeWorkspaceData }) {
  const latest = data.runs.data[0];
  return <div className={styles.stack}><section className={styles.section}><div className={styles.sectionHeading}><div><p>Readiness</p><h3>知识库看板</h3></div><Status value={latest?.status || "empty"} /></div><div className={styles.dashboardGrid}><DashboardItem label="来源治理" value={`${data.dashboard.data.sources} 个来源`} note="URL、文件和授权文本" /><DashboardItem label="处理成功率" value={`${data.dashboard.data.succeeded_runs}/${data.runs.data.length}`} note={`失败 ${data.dashboard.data.failed_runs}`} /><DashboardItem label="可用语料" value={`${data.dashboard.data.active_chunks} Chunks`} note="仅 active 可进入后续治理" /><DashboardItem label="事实审核" value={`${data.dashboard.data.pending_facts} 待处理`} note="批准后才可转为正式 Evidence" /></div></section></div>;
}

function QualityView({ data, projectId }: { data: KnowledgeWorkspaceData; projectId: string }) {
  return <section className={styles.section}><div className={styles.sectionHeading}><div><p>Quality gates</p><h3>质检发现</h3></div><span>{data.findings.data.length} 条</span></div><div className={styles.findingList}>{data.findings.data.map((item) => <article key={item.id}><header><strong>{item.finding_code}</strong><span className={styles[item.severity] || ""}>{item.severity}</span></header><p>{item.message}</p><small>{item.source_title} · {item.status}</small>{item.status === "open" ? <KnowledgeActionForm action={reviewKnowledgeFinding} className={styles.inlineForm} submitLabel="确认处置"><input name="project_id" type="hidden" value={projectId} /><input name="finding_id" type="hidden" value={item.id} /><label>处置<select name="decision"><option value="resolved">问题已解决</option><option value="accepted">接受风险</option></select></label></KnowledgeActionForm> : null}</article>)}</div>{!data.findings.data.length ? <p>当前没有开放的质量问题。</p> : null}</section>;
}

function TraceView({
  canPromote,
  data,
  entities,
  projectId
}: {
  canPromote: boolean;
  data: KnowledgeWorkspaceData;
  entities: CatalogEntity[];
  projectId: string;
}) {
  const facts = data.facts.data;
  const proposal = data.evidenceProposal.data;
  return <div className={styles.stack}>
    <section className={styles.section}><div className={styles.sectionHeading}><div><p>Evidence lineage</p><h3>事实候选与证据追踪</h3></div><span>{facts.length} 条</span></div><div className={styles.factList}>{facts.map((fact) => <article className={fact.id === data.selectedFactId ? styles.selectedFact : ""} key={fact.id}><header><span><strong>{fact.source_title}</strong><small>Chunk {fact.chunk_id.slice(0, 8)} · {fact.statement_hash.slice(0, 10)}</small></span><Status value={fact.status} /></header><p>{fact.statement}</p>{fact.status === "pending_review" ? <KnowledgeActionForm action={reviewKnowledgeFact} submitLabel="保存审核"><input name="project_id" type="hidden" value={projectId} /><input name="fact_id" type="hidden" value={fact.id} /><div className={styles.reviewFields}><label>结论<select name="decision"><option value="approved">批准</option><option value="rejected">拒绝</option></select></label><label>审核说明<input name="notes" placeholder="说明事实主体、时效或使用限制" /></label></div></KnowledgeActionForm> : <div className={styles.factFooter}><small>{fact.review_notes || "已完成审核"}</small>{fact.status === "approved" ? <a href={factHref(projectId, fact.id)}>Evidence 与追溯链</a> : null}</div>}</article>)}</div>{!facts.length ? <p>Pipeline 生成事实候选后将在此人工审核。</p> : null}</section>
    {proposal ? <FactEvidenceDetail canPromote={canPromote} entities={entities} projectId={projectId} proposal={proposal} /> : null}
  </div>;
}

function FactEvidenceDetail({
  canPromote,
  entities,
  projectId,
  proposal
}: {
  canPromote: boolean;
  entities: CatalogEntity[];
  projectId: string;
  proposal: NonNullable<KnowledgeWorkspaceData["evidenceProposal"]["data"]>;
}) {
  const existing = proposal.existing;
  return <section className={styles.section}>
    <div className={styles.sectionHeading}><div><p>Governed Evidence</p><h3>{existing ? existing.evidence.title : "正式 Evidence 提升"}</h3></div><Status value={existing ? "ready" : proposal.promotable ? "approved" : "blocked"} /></div>
    <div className={styles.traceGrid}>
      <div><span>Source</span><strong>{proposal.source.title}</strong><small>{proposal.source.id}</small><code>{shortHash(proposal.source.content_hash)}</code></div>
      <div><span>Document</span><strong>{proposal.document.parser_version}</strong><small>{proposal.document.id}</small><code>{shortHash(proposal.document.cleaned_text_hash)}</code></div>
      <div><span>Chunk {proposal.chunk.chunk_index}</span><strong>{proposal.chunk.status}</strong><small>{proposal.chunk.id}</small><code>{shortHash(proposal.chunk.text_hash)}</code></div>
      <div><span>Approved Fact</span><strong>{proposal.fact.status}</strong><small>{proposal.fact.id}</small><code>{shortHash(proposal.fact.statement_hash)}</code></div>
    </div>
    {existing ? <div className={styles.lineage}>
      <dl><div><dt>Evidence ID</dt><dd>{existing.evidence.id}</dd></div><div><dt>契约</dt><dd>{existing.lineage.lineage_contract_version}</dd></div><div><dt>Idempotency-Key</dt><dd>{existing.lineage.idempotency_key}</dd></div><div><dt>Request SHA-256</dt><dd>{existing.lineage.promotion_request_hash}</dd></div><div><dt>Evidence SHA-256</dt><dd>{existing.lineage.evidence_snapshot_hash}</dd></div><div><dt>提升时间</dt><dd>{formatDate(existing.lineage.promoted_at)}</dd></div></dl>
      <div className={styles.detailActions}><a href={`/projects/${encodeURIComponent(projectId)}?tab=geo&geo_section=placement&placement_stage=brief`}>进入 Evidence Pack</a></div>
    </div> : <>
      {proposal.blockers.length ? <p className={styles.error}>{proposal.blockers.map(blockerLabel).join(" · ")}</p> : null}
      {proposal.promotable && canPromote ? <FactEvidencePromotionForm entities={entities} projectId={projectId} proposal={proposal} /> : null}
      {proposal.promotable && !canPromote ? <p>当前角色仅可查看追溯链。</p> : null}
    </>}
  </section>;
}

function DashboardItem({ label, note, value }: { label: string; note: string; value: string }) { return <div><span>{label}</span><strong>{value}</strong><small>{note}</small></div>; }
function Status({ value }: { value: string }) { return <span className={`${styles.status} ${styles[value] || ""}`}>{statusLabel(value)}</span>; }
function Problems({ data }: { data: KnowledgeWorkspaceData }) { const problems = [data.sources.problem, data.runs.problem, data.stages.problem, data.chunks.problem, data.facts.problem, data.findings.problem, data.dashboard.problem, data.evidenceProposal.problem].filter(Boolean) as KnowledgeProblem[]; return problems.length ? <section className={styles.problems}>{problems.map((item, index) => <p key={`${item.detail}-${index}`}>{item.status || "错误"} · {item.detail}{item.correlationId ? ` · ${item.correlationId}` : ""}</p>)}</section> : null; }
function href(projectId: string, view: string) { return `/projects/${encodeURIComponent(projectId)}?tab=knowledge&knowledge_tab=${view}`; }
function factHref(projectId: string, factId: string) { return `${href(projectId, "trace")}&knowledge_fact_id=${encodeURIComponent(factId)}`; }
function shortHash(value: string | null) { return value ? value.slice(0, 16) : "missing"; }
function blockerLabel(value: string) { return ({ fact_not_approved: "Fact 尚未批准", fact_review_metadata_missing: "缺少审核记录", source_not_ready: "来源尚未就绪", source_content_hash_missing: "来源缺少内容哈希", pipeline_run_not_succeeded: "处理任务尚未成功", source_content_hash_mismatch: "来源内容哈希不匹配", document_cleaned_text_hash_mismatch: "Document 哈希不匹配", chunk_disabled: "Chunk 已禁用", chunk_integrity_mismatch: "Chunk 完整性校验失败", fact_statement_hash_mismatch: "Fact 哈希不匹配" } as Record<string, string>)[value] || value; }
function formatBytes(value: number | null) { if (!value) return "—"; return value > 1024 * 1024 ? `${(value / 1024 / 1024).toFixed(1)} MB` : `${Math.ceil(value / 1024)} KB`; }
function formatDate(value: string) { return value ? value.slice(0, 16).replace("T", " ") : "—"; }
function stageLabel(value: string) { return ({ ingest: "接收来源", parse: "解析正文", clean: "清洗去重", chunk: "语义分块", fact_extract: "事实候选", quality: "质量检查" } as Record<string, string>)[value] || value; }
function statusLabel(value: string) { return ({ queued: "排队中", processing: "处理中", running: "运行中", ready: "可用", succeeded: "成功", failed: "失败", pending: "等待", pending_review: "待审核", approved: "已批准", rejected: "已拒绝", active: "活动", disabled: "已禁用", empty: "暂无数据" } as Record<string, string>)[value] || value; }
