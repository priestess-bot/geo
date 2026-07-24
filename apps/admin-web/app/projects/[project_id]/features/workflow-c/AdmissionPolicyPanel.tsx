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
    return <LoadProblem label="Sampling Admission Policy" problem={policies.problem} />;
  }
  const selected = policies.data?.items.find((item) => item.id === selectedPolicyId)
    || policies.data?.items[0]
    || null;
  return (
    <div className={styles.sectionStack}>
      <section>
        <SectionHeading
          eyebrow="Authorization inventory"
          title={`${policies.data?.total || 0} policies`}
        />
        {policies.data?.items.length ? (
          <div className={styles.tableWrap}>
            <table className={styles.dataTable}>
              <thead>
                <tr><th>Target</th><th>Status</th><th>Effective</th><th>Expiry</th><th>Revision</th><th>Definition</th></tr>
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
        ) : <EmptyState title="Admission Policy 尚未创建" />}
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
        <LoadProblem label="Sampling runtime authorization options" problem={runtimeOptions.problem} />
      ) : null}
    </div>
  );
}

function PolicyDetail({ policy }: { policy: AdmissionPolicy }) {
  return (
    <section>
      <SectionHeading eyebrow="Immutable policy" title={policy.id} />
      <dl className={styles.factGrid}>
        <Fact label="Status" value={`${policy.status} / ${policy.effective_authorization_state}`} />
        <Fact label="Platform" value={`${policy.platform} / ${captureLabel(policy.capture_method)}`} />
        <Fact label="Adapter Release" value={policy.adapter_release} />
        <Fact label="Authorized purposes" value={policy.authorized_purposes.join(", ")} />
        <Fact label="Authorization evidence" value={policy.authorization_reference} />
        <Fact label="Valid until" value={formatTime(policy.valid_until)} />
        <Fact label="Quota" value={`${policy.quota_remaining} total / ${policy.daily_task_limit} daily`} />
        <Fact label="Rate" value={`${policy.minimum_request_interval_seconds}s / concurrency ${policy.max_concurrency}`} />
        <Fact label="Next allowed" value={formatTime(policy.next_allowed_at)} />
        <Fact label="Policy version" value={policy.policy_version} />
        <Fact label="Definition SHA-256" value={policy.definition_hash} />
        <Fact label="Supersedes" value={policy.supersedes_policy_id || "-"} />
      </dl>
      <div className={styles.tableWrap}>
        <table className={styles.dataTable}>
          <thead><tr><th>Stage</th><th>Actor</th><th>Time</th><th>Reason</th></tr></thead>
          <tbody>
            <AuditRow actor={policy.created_by} label="Created" time={policy.created_at} />
            <AuditRow actor={policy.submitted_by} label="Submitted" time={policy.submitted_at} />
            <AuditRow actor={policy.decided_by} label="Decided" reason={policy.decision_reason} time={policy.decided_at} />
            <AuditRow actor={policy.revoked_by} label="Revoked" reason={policy.revocation_reason} time={policy.revoked_at} />
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
  return <span className={styles.status} data-status={value}>{value.replaceAll("_", " ")}</span>;
}

function formatTime(value: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString("zh-CN");
}
