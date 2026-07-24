import { randomUUID } from "node:crypto";

import type { ManagedMemberRole } from "../../memberTypes";
import { EvidenceGraphPanel } from "./EvidenceGraphPanel";
import { RecommendationGenerationPanel } from "./RecommendationGenerationPanel";
import type { RecommendationGenerationCatalog } from "./recommendationGenerationTypes";
import {
  RecommendationCommands,
  type RecommendationCommandKeys
} from "./RecommendationCommands";
import { recommendationHref } from "./recommendationData";
import {
  recommendationStatuses,
  recommendationTypes,
  type LinkedDraft,
  type Recommendation,
  type RecommendationLoadProblem,
  type RecommendationWorkflow,
  type RecommendationWorkspaceData
} from "./recommendationTypes";
import styles from "./Recommendations.module.css";

export function RecommendationWorkspace({
  actorIdentityId,
  currentRole,
  data,
  projectId
}: {
  actorIdentityId: string;
  currentRole: ManagedMemberRole | null;
  data: RecommendationWorkspaceData;
  projectId: string;
}) {
  const canContribute = currentRole === "owner" || currentRole === "admin" || currentRole === "analyst";
  const canApprove = currentRole === "owner" || currentRole === "admin";
  return (
    <div className={styles.workspace}>
      <header className={styles.workspaceHeader}>
        <div><p>Evidence to controlled draft</p><h2>Recommendations</h2></div>
        <div className={styles.summary}>
          <span><strong>{data.sourceTotal}</strong> 总记录</span>
          <span><strong>{data.page.items.length}</strong> 当前筛选</span>
          <span><strong>{currentRole ? roleLabel(currentRole) : "未授权"}</strong> 当前角色</span>
        </div>
      </header>

      <FilterBar data={data} projectId={projectId} />
      {data.listProblem ? <LoadProblem label="Recommendation 列表" problem={data.listProblem} /> : null}
      {!data.listProblem && data.page.items.length === 0 ? (
        <div className={styles.emptyState}>
          <strong>{data.sourceTotal ? "当前筛选没有结果" : "暂无 Recommendation"}</strong>
          <span>{data.sourceTotal ? "调整状态或类型筛选后重试。" : "真实证据形成建议后会显示在这里。"}</span>
        </div>
      ) : null}

      {data.page.items.length ? (
        <RecommendationTable
          data={data}
          projectId={projectId}
          selectedId={data.selected?.recommendation.id}
        />
      ) : null}

      {data.selectedProblem ? <LoadProblem label="所选 Recommendation" problem={data.selectedProblem} /> : null}
      {data.selected ? (
        <RecommendationDetail
          actorIdentityId={actorIdentityId}
          canApprove={canApprove}
          canContribute={canContribute}
          generationCatalog={data.generationCatalog}
          projectId={projectId}
          workflow={data.selected}
        />
      ) : null}
    </div>
  );
}

function FilterBar({ data, projectId }: { data: RecommendationWorkspaceData; projectId: string }) {
  return (
    <form action={`/projects/${encodeURIComponent(projectId)}`} className={styles.filters} method="get">
      <input name="tab" type="hidden" value="recommendations" />
      <label><span>状态</span><select defaultValue={data.filters.status} name="recommendation_status">
        <option value="all">全部状态</option>
        {recommendationStatuses.map((status) => <option key={status} value={status}>{statusLabel(status)}</option>)}
      </select></label>
      <label><span>类型</span><select defaultValue={data.filters.type} name="recommendation_type">
        <option value="all">全部类型</option>
        {recommendationTypes.map((type) => <option key={type} value={type}>{typeLabel(type)}</option>)}
      </select></label>
      <button type="submit">应用筛选</button>
      <a className={styles.resetLink} href={recommendationHref(projectId)}>清除</a>
    </form>
  );
}

function RecommendationTable({
  data,
  projectId,
  selectedId
}: {
  data: RecommendationWorkspaceData;
  projectId: string;
  selectedId?: string;
}) {
  return (
    <section className={styles.listSection} aria-labelledby="recommendation-list-heading">
      <div className={styles.sectionHeading}>
        <h3 id="recommendation-list-heading">建议清单</h3>
        <span>{data.page.items.length} / {data.sourceTotal}</span>
      </div>
      <div className={styles.tableWrap}>
        <table className={styles.listTable}>
          <thead><tr><th>类型 / ID</th><th>状态</th><th>决策摘要</th><th>有效期</th><th>草稿</th><th>操作</th></tr></thead>
          <tbody>{data.page.items.map((workflow) => {
            const recommendation = workflow.recommendation;
            return (
              <tr className={recommendation.id === selectedId ? styles.activeRow : undefined} key={recommendation.id}>
                <td><strong>{typeLabel(recommendation.recommendation_type)}</strong><code>{recommendation.id}</code></td>
                <td><StatusPill value={recommendation.status} /><small>v{recommendation.version}</small></td>
                <td><span>{recommendation.evidence.decision.business_value}</span><small>置信度：{recommendation.evidence.decision.confidence}</small></td>
                <td><time dateTime={recommendation.valid_until}>{formatTime(recommendation.valid_until)}</time><small>{validityLabel(recommendation.valid_until)}</small></td>
                <td>{workflow.drafts.length}<small>{draftStatusSummary(workflow.drafts)}</small></td>
                <td><a className={styles.openLink} href={recommendationHref(projectId, recommendation.id, data.filters)}>检查</a></td>
              </tr>
            );
          })}</tbody>
        </table>
      </div>
    </section>
  );
}

function RecommendationDetail({
  actorIdentityId,
  canApprove,
  canContribute,
  generationCatalog,
  projectId,
  workflow
}: {
  actorIdentityId: string;
  canApprove: boolean;
  canContribute: boolean;
  generationCatalog: RecommendationGenerationCatalog;
  projectId: string;
  workflow: RecommendationWorkflow;
}) {
  const recommendation = workflow.recommendation;
  return (
    <div className={styles.detailArea}>
      <section className={styles.detailSection} aria-labelledby="recommendation-detail-heading">
        <div className={styles.detailHeading}>
          <div>
            <p>{typeLabel(recommendation.recommendation_type)}</p>
            <h3 id="recommendation-detail-heading">Recommendation v{recommendation.version}</h3>
            <code>{recommendation.id}</code>
          </div>
          <StatusPill value={recommendation.status} />
        </div>
        {recommendation.status === "stale" || recommendation.status === "expired" ? (
          <div className={styles.blockedNotice} role="status">
            <strong>{recommendation.status === "stale" ? "证据输入已变化" : "批准有效期已结束"}</strong>
            <span>此 Recommendation 不能继续授权关联草稿；未启动草稿必须保持 blocked 状态。</span>
          </div>
        ) : null}
        <RecommendationFacts recommendation={recommendation} />
        <ApprovalView recommendation={recommendation} />
        <DraftTable drafts={workflow.drafts} />
      </section>

      <EvidenceGraphPanel recommendation={recommendation} />
      <RecommendationGenerationPanel
        canContribute={canContribute}
        catalog={generationCatalog}
        idempotencyKey={`admin-recommendation-generate-${randomUUID()}`}
        projectId={projectId}
        recommendation={recommendation}
      />
      <RecommendationCommands
        actorIdentityId={actorIdentityId}
        canApprove={canApprove}
        canContribute={canContribute}
        commandKeys={commandKeys(workflow)}
        drafts={workflow.drafts}
        projectId={projectId}
        recommendation={recommendation}
      />
    </div>
  );
}

function RecommendationFacts({ recommendation }: { recommendation: Recommendation }) {
  return (
    <dl className={styles.factGrid}>
      <Fact label="Created by" value={recommendation.created_by} />
      <Fact label="Created" value={formatTime(recommendation.created_at)} />
      <Fact label="Updated" value={formatTime(recommendation.updated_at)} />
      <Fact label="Valid until" value={formatTime(recommendation.valid_until)} />
      <Fact label="Proposed draft" value={recommendation.proposed_draft_kind ? typeLabel(recommendation.proposed_draft_kind) : "无下游草稿"} />
      <Fact label="Scope version" value={recommendation.evidence.scope.applicable_version} />
    </dl>
  );
}

function ApprovalView({ recommendation }: { recommendation: Recommendation }) {
  const approval = recommendation.approval;
  return (
    <details className={styles.detailDisclosure} open={Boolean(approval)}>
      <summary>人工批准记录</summary>
      {approval ? (
        <dl className={styles.factGrid}>
          <Fact label="Approval ID" value={approval.id} />
          <Fact label="Approved by" value={approval.approved_by} />
          <Fact label="Approved at" value={formatTime(approval.approved_at)} />
          <Fact label="Recommendation version" value={`v${approval.recommendation_version}`} />
          <Fact label="Frozen input fingerprint" value={approval.frozen_input_fingerprint} />
          <Fact label="Frozen graph SHA-256" value={approval.frozen_evidence_graph_hash} />
        </dl>
      ) : <p className={styles.inlineEmpty}>尚未批准。只有独立审核通过后才会生成批准记录。</p>}
    </details>
  );
}

function DraftTable({ drafts }: { drafts: readonly LinkedDraft[] }) {
  return (
    <section className={styles.draftSection} aria-labelledby="recommendation-drafts-heading">
      <div className={styles.subheading}><h4 id="recommendation-drafts-heading">关联草稿</h4><span>{drafts.length}</span></div>
      {drafts.length ? (
        <div className={styles.tableWrap}>
          <table className={styles.draftTable}>
            <thead><tr><th>类型 / ID</th><th>状态</th><th>冻结版本</th><th>自动动作</th><th>阻断原因</th></tr></thead>
            <tbody>{drafts.map((draft) => (
              <tr key={draft.id}>
                <td><strong>{typeLabel(draft.kind)}</strong><code>{draft.id}</code></td>
                <td><StatusPill value={draft.status} /></td>
                <td><span>Recommendation v{draft.recommendation_version}</span><code>{draft.frozen_input_fingerprint}</code></td>
                <td><span>仅草稿</span><small>queued: {String(draft.enqueued)} · executed: {String(draft.executed)} · published: {String(draft.published)}</small></td>
                <td>{draft.blocked_reason || "未阻断"}{draft.blocked_at ? <small>{formatTime(draft.blocked_at)}</small> : null}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      ) : <p className={styles.inlineEmpty}>没有关联草稿。No Change 类型在批准后也不会创建草稿。</p>}
    </section>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd><code>{value}</code></dd></div>;
}

function LoadProblem({ label, problem }: { label: string; problem: RecommendationLoadProblem }) {
  return (
    <div className={styles.loadError} role="alert">
      <strong>{problem.status ? `${problem.status} · ` : ""}{label}加载失败</strong>
      <span>{problem.detail}</span>
      {problem.correlationId ? <small>关联 ID：{problem.correlationId}</small> : null}
    </div>
  );
}

function StatusPill({ value }: { value: string }) {
  return <span className={`${styles.statusPill} ${styles[`status_${value}`] || ""}`}>{value}</span>;
}

function commandKeys(workflow: RecommendationWorkflow): RecommendationCommandKeys {
  return {
    submit: `admin-recommendation-submit-${randomUUID()}`,
    review: `admin-recommendation-review-${randomUUID()}`,
    approve: `admin-recommendation-approve-${randomUUID()}`,
    reject: `admin-recommendation-reject-${randomUUID()}`,
    expire: `admin-recommendation-expire-${randomUUID()}`,
    reconcile: `admin-recommendation-reconcile-${randomUUID()}`,
    drafts: Object.fromEntries(workflow.drafts.map((draft) => [
      draft.id,
      `admin-recommendation-prepare-${draft.id}-${randomUUID()}`
    ]))
  };
}

function draftStatusSummary(drafts: readonly LinkedDraft[]): string {
  if (!drafts.length) return "无";
  const blocked = drafts.filter((draft) => draft.status.startsWith("blocked_")).length;
  return blocked ? `${blocked} blocked` : drafts.map((draft) => draft.status).join(", ");
}

function validityLabel(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "时间格式未知";
  return date.valueOf() <= Date.now() ? "已到期" : "有效期内";
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString("zh-CN");
}

function statusLabel(value: string): string {
  return value.replaceAll("_", " ");
}

function typeLabel(value: string): string {
  return value.replaceAll("_", " ");
}

function roleLabel(value: ManagedMemberRole): string {
  if (value === "owner") return "负责人";
  if (value === "admin") return "管理员";
  return "分析师";
}
