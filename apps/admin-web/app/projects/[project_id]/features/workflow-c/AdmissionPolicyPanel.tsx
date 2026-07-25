import { AdmissionPolicyCommands, type AdmissionPolicyCommandKeys } from "./AdmissionPolicyCommands";
import {
  EmptyState,
  Fact,
  LoadProblem,
  SectionHeading,
  captureLabel
} from "./WorkflowCWorkspace";
import { workflowCHref } from "./workflowCData";
import type {
  AdmissionPolicy,
  AdmissionPolicyPage,
  Resource,
  WorkflowCWorkspaceData
} from "./workflowCTypes";
import styles from "./WorkflowC.module.css";

export function AdmissionPolicyPanel({
  actorId,
  canManage,
  commandKeys,
  policies,
  projectId,
  runtimeOptions,
  selectedPolicyId,
  selection,
  validUntilDefault
}: {
  actorId: string;
  canManage: boolean;
  commandKeys: AdmissionPolicyCommandKeys;
  policies: Resource<AdmissionPolicyPage>;
  projectId: string;
  runtimeOptions: WorkflowCWorkspaceData["admissionRuntimeOptions"];
  selectedPolicyId?: string;
  selection: WorkflowCWorkspaceData["selection"];
  validUntilDefault: string;
}) {
  if (policies.problem) {
    return <LoadProblem label="采样准入策略" problem={policies.problem} />;
  }
  const selected = policies.data?.items.find((item) => item.id === selectedPolicyId)
    || policies.data?.items[0]
    || null;
  return (
    <div className={styles.sectionStack}>
      <section>
        <SectionHeading
          eyebrow="授权清单"
          title={`${policies.data?.total || 0} 条策略`}
        />
        {policies.data?.items.length ? (
          <div className={styles.tableWrap}>
            <table className={styles.dataTable}>
              <thead>
                <tr><th>目标</th><th>状态</th><th>生效情况</th><th>有效期</th><th>修订版本</th><th>定义</th></tr>
              </thead>
              <tbody>
                {policies.data.items.map((policy) => (
                  <tr key={policy.id}>
                    <td>
                      <a href={workflowCHref(projectId, { ...selection, policyId: policy.id }, "admission")}>
                        <strong>{policy.platform}</strong>
                      </a>
                      <small>{captureLabel(policy.capture_method)} · {policy.adapter_release}</small>
                    </td>
                    <td><Status value={policy.status} /></td>
                    <td><Status value={policy.effective_authorization_state} /></td>
                    <td>{formatTime(policy.valid_until)}</td>
                    <td>r{policy.revision} · v{policy.aggregate_version}</td>
                    <td><code>{policy.definition_hash}</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <EmptyState title="准入策略尚未创建" />}
      </section>

      {selected ? <PolicyDetail policy={selected} /> : null}
      <AdmissionPolicyCommands
        actorId={actorId}
        canManage={canManage}
        commandKeys={commandKeys}
        policies={policies.data?.items || []}
        policy={selected}
        projectId={projectId}
        runtimeOptions={runtimeOptions.data?.items || []}
        validUntilDefault={validUntilDefault}
      />
      {runtimeOptions.problem ? (
        <LoadProblem label="采样运行时授权选项" problem={runtimeOptions.problem} />
      ) : null}
    </div>
  );
}

function PolicyDetail({ policy }: { policy: AdmissionPolicy }) {
  return (
    <section>
      <SectionHeading eyebrow="不可变策略" title={policy.id} />
      <dl className={styles.factGrid}>
        <Fact label="状态" value={`${policy.status} / ${policy.effective_authorization_state}`} />
        <Fact label="平台" value={`${policy.platform} / ${captureLabel(policy.capture_method)}`} />
        <Fact label="适配器发布版本" value={policy.adapter_release} />
        <Fact label="授权用途" value={policy.authorized_purposes.join(", ")} />
        <Fact label="授权证据" value={policy.authorization_reference} />
        <Fact label="有效至" value={formatTime(policy.valid_until)} />
        <Fact label="配额" value={`总计 ${policy.quota_remaining} / 每日 ${policy.daily_task_limit}`} />
        <Fact label="速率" value={`${policy.minimum_request_interval_seconds} 秒 / 并发 ${policy.max_concurrency}`} />
        <Fact label="下次允许时间" value={formatTime(policy.next_allowed_at)} />
        <Fact label="策略版本" value={policy.policy_version} />
        <Fact label="定义 SHA-256" value={policy.definition_hash} />
        <Fact label="替代策略" value={policy.supersedes_policy_id || "-"} />
      </dl>
      <div className={styles.tableWrap}>
        <table className={styles.dataTable}>
          <thead><tr><th>阶段</th><th>执行人</th><th>时间</th><th>原因</th></tr></thead>
          <tbody>
            <AuditRow actor={policy.created_by} label="已创建" time={policy.created_at} />
            <AuditRow actor={policy.submitted_by} label="已提交" time={policy.submitted_at} />
            <AuditRow actor={policy.decided_by} label="已决策" reason={policy.decision_reason} time={policy.decided_at} />
            <AuditRow actor={policy.revoked_by} label="已撤销" reason={policy.revocation_reason} time={policy.revoked_at} />
          </tbody>
        </table>
      </div>
    </section>
  );
}

function AuditRow({
  actor,
  label,
  reason,
  time
}: {
  actor: string | null;
  label: string;
  reason?: string | null;
  time: string | null;
}) {
  return <tr><td>{label}</td><td>{actor || "-"}</td><td>{formatTime(time)}</td><td>{reason || "-"}</td></tr>;
}

function Status({ value }: { value: string }) {
  return <span className={styles.status} data-status={value}>{statusLabel(value)}</span>;
}

function statusLabel(value: string): string {
  return ({ draft: "草稿", pending_review: "待复核", approved: "已批准", revoked: "已撤销", active: "生效中", not_assessed: "未评估", no_basis: "无依据", expired: "已过期" } as Record<string, string>)[value] || value.replaceAll("_", " ");
}

function formatTime(value: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString("zh-CN");
}
