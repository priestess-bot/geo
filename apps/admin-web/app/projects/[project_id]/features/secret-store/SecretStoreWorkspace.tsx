import { randomUUID } from "node:crypto";

import type { ManagedMemberRole } from "../../memberTypes";
import { CreateSecretReferenceForm, SecretLifecycleForms } from "./SecretStoreForms";
import type {
  SecretAuditEvent,
  SecretLoadProblem,
  SecretReference,
  SecretWorkspaceData
} from "./secretStoreTypes";
import styles from "./SecretStore.module.css";

export function SecretStoreWorkspace({
  currentRole,
  data,
  projectId
}: {
  currentRole: ManagedMemberRole | null;
  data: SecretWorkspaceData;
  projectId: string;
}) {
  const runtimeUnavailable = data.referencesProblem?.status === 503
    || data.auditsProblem?.status === 503;
  const canManage = !runtimeUnavailable
    && (currentRole === "owner" || currentRole === "admin");
  const selectedAudits = data.selectedReference
    ? data.audits.items.filter(
      (item) => item.reference_id === data.selectedReference?.reference_id
    )
    : [];
  return (
    <div className={styles.workspace}>
      <header className={styles.workspaceHeader}>
        <div><p>加密凭据</p><h2>密钥库</h2></div>
        <div className={styles.summary}>
          <span><strong>{data.references.total}</strong> 个引用</span>
          <span><strong>{data.audits.total}</strong> 条审计事件</span>
          <span><strong>{currentRole ? roleLabel(currentRole) : "未授权"}</strong> 当前角色</span>
        </div>
      </header>

      {runtimeUnavailable ? (
        <div className={styles.unavailable} role="alert">
          <strong>密钥库暂不可用</strong>
          <span>持久化或密钥运行时未连接，所有写入保持关闭。</span>
        </div>
      ) : null}

      <details className={styles.createSection}>
        <summary>新建密钥引用</summary>
        <CreateSecretReferenceForm
          canManage={canManage}
          idempotencyKey={`admin-secret-create-${randomUUID()}`}
          projectId={projectId}
        />
      </details>

      {data.referencesProblem ? <LoadProblem label="密钥引用" problem={data.referencesProblem} /> : null}
      {data.selectionProblem ? <LoadProblem label="所选密钥引用" problem={data.selectionProblem} /> : null}
      {!data.referencesProblem && data.references.items.length === 0 ? (
        <div className={styles.emptyState}><strong>暂无密钥引用</strong></div>
      ) : null}

      {data.references.items.length ? (
        <section className={styles.referenceSection} aria-labelledby="secret-reference-list-heading">
          <div className={styles.sectionHeading}>
            <h3 id="secret-reference-list-heading">密钥引用</h3>
            <span>{pageRange(data.references.offset, data.references.items.length, data.references.total)}</span>
          </div>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead><tr><th>用途 / 引用</th><th>状态</th><th>版本</th><th>主密钥版本</th><th>指纹</th><th>操作</th></tr></thead>
              <tbody>{data.references.items.map((reference) => (
                <ReferenceRow
                  active={reference.reference_id === data.selectedReference?.reference_id}
                  key={reference.reference_id}
                  projectId={projectId}
                  reference={reference}
                />
              ))}</tbody>
            </table>
          </div>
          <Pagination
            kind="secret_page"
            limit={data.references.limit}
            offset={data.references.offset}
            projectId={projectId}
            total={data.references.total}
          />
        </section>
      ) : null}

      {data.selectedReference ? (
        <section className={styles.detailSection} aria-labelledby="secret-detail-heading">
          <div className={styles.sectionHeading}>
            <div><p>{data.selectedReference.purpose}</p><h3 id="secret-detail-heading">密钥引用</h3></div>
            <StatusPill value={data.selectedReference.status} />
          </div>
          <ReferenceMetadata reference={data.selectedReference} />
          <SecretLifecycleForms
            audits={selectedAudits}
            canManage={canManage && !data.auditsProblem}
            commandKeys={{
              activate: `admin-secret-activate-${randomUUID()}`,
              revoke: `admin-secret-revoke-${randomUUID()}`,
              rotate: `admin-secret-rotate-${randomUUID()}`,
              verify: `admin-secret-verify-${randomUUID()}`
            }}
            key={data.selectedReference.reference_id}
            projectId={projectId}
            reference={data.selectedReference}
          />
        </section>
      ) : null}

      <section className={styles.auditSection} aria-labelledby="secret-audit-heading">
        <div className={styles.sectionHeading}>
          <h3 id="secret-audit-heading">审计与版本状态</h3>
          <span>{pageRange(data.audits.offset, data.audits.items.length, data.audits.total)}</span>
        </div>
        {data.auditsProblem ? <LoadProblem label="密钥审计" problem={data.auditsProblem} /> : null}
        {!data.auditsProblem && data.audits.items.length === 0 ? (
          <div className={styles.emptyState}><strong>暂无审计事件</strong></div>
        ) : null}
        {data.audits.items.length ? <AuditTable items={data.audits.items} /> : null}
        <Pagination
          kind="secret_audit_page"
          limit={data.audits.limit}
          offset={data.audits.offset}
          projectId={projectId}
          referenceId={data.selectedReference?.reference_id}
          total={data.audits.total}
        />
      </section>
    </div>
  );
}

function ReferenceRow({
  active,
  projectId,
  reference
}: {
  active: boolean;
  projectId: string;
  reference: SecretReference;
}) {
  return (
    <tr className={active ? styles.activeRow : undefined}>
      <td><strong>{reference.purpose}</strong><code>{reference.reference_id}</code></td>
      <td><StatusPill value={reference.status} /></td>
      <td><span>聚合版本 v{reference.aggregate_version}</span><small>当前 {reference.current_version ?? "-"} · 最新 {reference.latest_version}</small></td>
      <td>v{reference.master_key_version}</td>
      <td><code>{reference.fingerprint}</code></td>
      <td><a className={styles.tableLink} href={secretHref(projectId, reference.reference_id)}>打开</a></td>
    </tr>
  );
}

function ReferenceMetadata({ reference }: { reference: SecretReference }) {
  return (
    <dl className={styles.metadataGrid}>
      <Metadata label="引用 ID" value={reference.reference_id} />
      <Metadata label="用途" value={reference.purpose} />
      <Metadata label="聚合版本" value={String(reference.aggregate_version)} />
      <Metadata label="当前 / 最新" value={`${reference.current_version ?? "-"} / ${reference.latest_version}`} />
      <Metadata label="主密钥版本" value={String(reference.master_key_version)} />
      <Metadata label="指纹" value={reference.fingerprint} />
      <Metadata label="创建时间" value={formatTime(reference.created_at)} />
      <Metadata label="更新时间" value={formatTime(reference.updated_at)} />
    </dl>
  );
}

function Metadata({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd><code>{value}</code></dd></div>;
}

function AuditTable({ items }: { items: SecretAuditEvent[] }) {
  return (
    <div className={styles.tableWrap}>
      <table className={`${styles.table} ${styles.auditTable}`}>
        <thead><tr><th>时间</th><th>引用</th><th>版本 / 操作</th><th>主密钥版本</th><th>指纹</th></tr></thead>
        <tbody>{items.map((event, index) => (
          <tr key={`${event.reference_id}:${event.version}:${event.action}:${event.occurred_at}:${index}`}>
            <td>{formatTime(event.occurred_at)}</td>
            <td><code>{event.reference_id}</code></td>
            <td><strong>v{event.version}</strong><span>{actionLabel(event.action)}</span></td>
            <td>v{event.master_key_version}</td>
            <td><code>{event.fingerprint}</code></td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function Pagination({
  kind,
  limit,
  offset,
  projectId,
  referenceId,
  total
}: {
  kind: "secret_page" | "secret_audit_page";
  limit: number;
  offset: number;
  projectId: string;
  referenceId?: string;
  total: number;
}) {
  const nextOffset = offset + limit;
  return (
    <nav className={styles.pagination} aria-label={kind === "secret_page" ? "密钥引用分页" : "密钥审计分页"}>
      {offset > 0
        ? <a href={pageHref(projectId, kind, Math.max(0, offset - limit), limit, referenceId)}>上一页</a>
        : <span aria-disabled="true">上一页</span>}
      <strong>第 {Math.floor(offset / limit) + 1} 页</strong>
      {nextOffset < total
        ? <a href={pageHref(projectId, kind, nextOffset, limit, referenceId)}>下一页</a>
        : <span aria-disabled="true">下一页</span>}
    </nav>
  );
}

function LoadProblem({ label, problem }: { label: string; problem: SecretLoadProblem }) {
  return (
    <div className={styles.loadError} role="alert">
      <strong>{problem.status ? `${problem.status} · ` : ""}{label}加载失败</strong>
      <span>{problem.status === 503 ? "密钥库暂不可用。" : problem.detail}</span>
      {problem.correlationId ? <small>关联 ID：{problem.correlationId}</small> : null}
    </div>
  );
}

function StatusPill({ value }: { value: string }) {
  return <span className={`${styles.statusPill} ${styles[`status_${value}`] || ""}`}>{secretStatusLabel(value)}</span>;
}

function secretStatusLabel(value: string): string {
  return { active: "已启用", pending: "待处理", revoked: "已撤销", staged: "已暂存" }[value] || value;
}

function secretHref(projectId: string, referenceId: string): string {
  return `/projects/${encodeURIComponent(projectId)}?tab=secrets&secret_reference_id=${encodeURIComponent(referenceId)}`;
}

function pageHref(
  projectId: string,
  kind: "secret_page" | "secret_audit_page",
  offset: number,
  limit: number,
  referenceId?: string
): string {
  const query = new URLSearchParams({ tab: "secrets" });
  query.set(kind, String(Math.floor(offset / limit) + 1));
  if (referenceId) query.set("secret_reference_id", referenceId);
  return `/projects/${encodeURIComponent(projectId)}?${query.toString()}`;
}

function actionLabel(value: string): string {
  return {
    version_created: "已创建版本",
    version_verified: "已验证版本",
    version_activated: "已激活版本",
    version_revoked: "已撤销版本"
  }[value] || value.replaceAll("_", " ");
}

function pageRange(offset: number, count: number, total: number): string {
  return total ? `${offset + 1}-${Math.min(offset + count, total)} / ${total}` : "0 / 0";
}

function roleLabel(value: ManagedMemberRole): string {
  if (value === "owner") return "负责人";
  if (value === "admin") return "管理员";
  return "分析师";
}

function formatTime(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleString("zh-CN");
}
