import { AlertCommands, type AlertCommandKeys } from "./AlertCommands";
import {
  EmptyState,
  Fact,
  LoadProblem,
  SectionHeading
} from "./WorkflowCWorkspace";
import { workflowCHref } from "./workflowCData";
import type {
  AlertPage,
  AlertRecord,
  NotificationProjection,
  Resource,
  WorkflowCWorkspaceData
} from "./workflowCTypes";
import alertStyles from "./WorkflowCAlerts.module.css";
import styles from "./WorkflowC.module.css";

type Selection = WorkflowCWorkspaceData["selection"];

export function AlertInbox({
  alerts,
  canAct,
  commandKeys,
  notifications,
  projectId,
  selected,
  selection,
  suppressionDefault
}: {
  alerts: Resource<AlertPage>;
  canAct: boolean;
  commandKeys: AlertCommandKeys;
  notifications: Resource<NotificationProjection[]>;
  projectId: string;
  selected: AlertRecord | null;
  selection: Selection;
  suppressionDefault: string;
}) {
  if (alerts.problem) return <LoadProblem label="Alert inbox" problem={alerts.problem} />;
  if (!alerts.data?.items.length) return <EmptyState title="Alert inbox 为空" />;

  return (
    <div className={alertStyles.alertWorkspace}>
      <section className={alertStyles.alertList} aria-label="Alert inbox">
        <SectionHeading eyebrow="Alert inbox" title={`${alerts.data.total} alerts`} />
        <div className={alertStyles.alertRows}>
          {alerts.data.items.map((alert) => (
            <a
              aria-current={selected?.id === alert.id ? "true" : undefined}
              data-severity={alert.severity}
              href={workflowCHref(projectId, { ...selection, alertId: alert.id }, "alerts")}
              key={alert.id}
            >
              <span className={alertStyles.alertRowTopline}>
                <strong>{alert.rule.rule_key}</strong>
                <Status value={alert.status} />
              </span>
              <span>{alert.scope.resource_kind} / {alert.scope.resource_key}</span>
              <small>{formatTime(alert.updated_at)} · v{alert.version}</small>
            </a>
          ))}
        </div>
      </section>

      <div className={alertStyles.alertDetail}>
        {selected ? (
          <>
            <AlertSummary alert={selected} />
            <AlertEvidence alert={selected} />
            <DispositionHistory alert={selected} />
            <NotificationHistory notifications={notifications} />
            <AlertCommands
              alert={selected}
              canAct={canAct}
              commandKeys={commandKeys}
              projectId={projectId}
              suppressionDefault={suppressionDefault}
            />
          </>
        ) : <EmptyState title="请选择 Alert" />}
      </div>
    </div>
  );
}

function AlertSummary({ alert }: { alert: AlertRecord }) {
  return (
    <section>
      <SectionHeading eyebrow={`${alert.severity} severity`} title={alert.rule.rule_key} />
      <div className={alertStyles.alertHeadline}>
        <Status value={alert.status} />
        <span>{alert.rule.kind}</span>
        {alert.replayed ? <span>idempotent replay</span> : null}
      </div>
      <dl className={styles.factGrid}>
        <Fact label="Alert ID" value={alert.id} />
        <Fact label="Scope" value={`${alert.scope.resource_kind} / ${alert.scope.resource_key}`} />
        <Fact label="Rule" value={`${alert.rule.id} · v${alert.rule.version}`} />
        <Fact label="Rule SHA-256" value={alert.rule_hash} />
        <Fact label="Trigger SHA-256" value={alert.trigger_snapshot_hash} />
        <Fact label="Dedupe key" value={alert.dedupe_key} />
        <Fact label="Opened" value={formatTime(alert.opened_at)} />
        <Fact label="Updated" value={formatTime(alert.updated_at)} />
        <Fact label="Suppressed until" value={formatTime(alert.suppressed_until)} />
        <Fact label="Suppression reason" value={alert.suppression_reason || "-"} />
      </dl>
      <KeyValueBlock label="Frozen rule parameters" values={alert.rule.parameters} />
      <KeyValueBlock label="Trigger values" values={alert.trigger_values} />
      <KeyValueBlock label="Scope dimensions" values={alert.scope.dimensions} />
    </section>
  );
}

function AlertEvidence({ alert }: { alert: AlertRecord }) {
  return (
    <section>
      <SectionHeading eyebrow="Immutable lineage" title={`${alert.evidence.length} evidence locators`} />
      <div className={styles.tableWrap}>
        <table className={styles.dataTable}>
          <thead><tr><th>Kind</th><th>Resource</th><th>Version</th><th>SHA-256</th><th>Locator</th></tr></thead>
          <tbody>{alert.evidence.map((item, index) => (
            <tr key={`${item.sha256}-${index}`}>
              <td>{item.kind}</td>
              <td><code>{item.resource_id}</code></td>
              <td>{item.version}</td>
              <td><code>{item.sha256}</code></td>
              <td><code>{item.locator || "-"}</code></td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </section>
  );
}

function DispositionHistory({ alert }: { alert: AlertRecord }) {
  return (
    <section>
      <SectionHeading eyebrow="Audit trail" title="处置历史" />
      {alert.dispositions.length ? (
        <div className={styles.tableWrap}>
          <table className={styles.dataTable}>
            <thead><tr><th>Disposition</th><th>Transition</th><th>Actor / time</th><th>Reason</th><th>Command lineage</th></tr></thead>
            <tbody>{alert.dispositions.map((item) => (
              <tr key={item.command_hash}>
                <td><strong>{item.disposition}</strong><small>result v{item.resulting_version}</small></td>
                <td>{item.from_status} → {item.to_status}<small>{formatTime(item.suppressed_until)}</small></td>
                <td><code>{item.actor_id}</code><small>{formatTime(item.occurred_at)}</small></td>
                <td>{item.reason}</td>
                <td><code>{item.command_key}</code><small>{item.command_hash}</small></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      ) : <EmptyState title="尚无人工处置" />}
    </section>
  );
}

function NotificationHistory({ notifications }: { notifications: Resource<NotificationProjection[]> }) {
  return (
    <section>
      <SectionHeading eyebrow="Outbox projection" title="通知记录" />
      {notifications.problem ? <LoadProblem label="Notification projection" problem={notifications.problem} /> : null}
      {notifications.data?.length ? (
        <div className={alertStyles.notificationList}>
          {notifications.data.map((item) => (
            <article key={item.id}>
              <header><strong>{channelLabel(item.channel)}</strong><small>alert v{item.alert_version}</small></header>
              <span>{item.topic}</span>
              <KeyValueBlock label="Safe summary" values={item.summary} />
              <footer><code>{item.payload_hash}</code><time>{formatTime(item.created_at)}</time></footer>
            </article>
          ))}
        </div>
      ) : <EmptyState title="尚无通知投影" />}
    </section>
  );
}

function KeyValueBlock({ label, values }: { label: string; values: Record<string, unknown> }) {
  const entries = Object.entries(values);
  if (!entries.length) return null;
  return (
    <details className={alertStyles.keyValues}>
      <summary>{label}</summary>
      <dl>{entries.map(([key, value]) => <Fact key={key} label={key} value={displayValue(value)} />)}</dl>
    </details>
  );
}

function Status({ value }: { value: string }) {
  return <span className={styles.status} data-status={value}>{value.replaceAll("_", " ")}</span>;
}

function channelLabel(value: NotificationProjection["channel"]): string {
  if (value === "admin_inbox") return "Admin inbox";
  if (value === "local_smtp") return "Local SMTP";
  return "Internal Webhook";
}

function displayValue(value: unknown): string {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  if (value === null) return "null";
  return JSON.stringify(value);
}

function formatTime(value: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString("zh-CN");
}
