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
  if (alerts.problem) return <LoadProblem label="告警收件箱" problem={alerts.problem} />;
  if (!alerts.data?.items.length) return <EmptyState title="告警收件箱为空" />;

  return (
    <div className={alertStyles.alertWorkspace}>
      <section className={alertStyles.alertList} aria-label="告警收件箱">
        <SectionHeading eyebrow="告警收件箱" title={`${alerts.data.total} 条告警`} />
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
        ) : <EmptyState title="请选择告警" />}
      </div>
    </div>
  );
}

function AlertSummary({ alert }: { alert: AlertRecord }) {
  return (
    <section>
      <SectionHeading eyebrow={`${alert.severity} 级别`} title={alert.rule.rule_key} />
      <div className={alertStyles.alertHeadline}>
        <Status value={alert.status} />
        <span>{alert.rule.kind}</span>
        {alert.replayed ? <span>幂等重放</span> : null}
      </div>
      <dl className={styles.factGrid}>
        <Fact label="告警 ID" value={alert.id} />
        <Fact label="范围" value={`${alert.scope.resource_kind} / ${alert.scope.resource_key}`} />
        <Fact label="规则" value={`${alert.rule.id} · v${alert.rule.version}`} />
        <Fact label="规则 SHA-256" value={alert.rule_hash} />
        <Fact label="触发快照 SHA-256" value={alert.trigger_snapshot_hash} />
        <Fact label="去重键" value={alert.dedupe_key} />
        <Fact label="打开时间" value={formatTime(alert.opened_at)} />
        <Fact label="更新时间" value={formatTime(alert.updated_at)} />
        <Fact label="抑制至" value={formatTime(alert.suppressed_until)} />
        <Fact label="抑制原因" value={alert.suppression_reason || "-"} />
      </dl>
      <KeyValueBlock label="冻结规则参数" values={alert.rule.parameters} />
      <KeyValueBlock label="触发值" values={alert.trigger_values} />
      <KeyValueBlock label="范围维度" values={alert.scope.dimensions} />
    </section>
  );
}

function AlertEvidence({ alert }: { alert: AlertRecord }) {
  return (
    <section>
      <SectionHeading eyebrow="不可变溯源" title={`${alert.evidence.length} 条证据定位`} />
      <div className={styles.tableWrap}>
        <table className={styles.dataTable}>
          <thead><tr><th>类型</th><th>资源</th><th>版本</th><th>SHA-256</th><th>定位信息</th></tr></thead>
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
      <SectionHeading eyebrow="审计轨迹" title="处置历史" />
      {alert.dispositions.length ? (
        <div className={styles.tableWrap}>
          <table className={styles.dataTable}>
            <thead><tr><th>处置</th><th>状态转换</th><th>操作人 / 时间</th><th>原因</th><th>命令溯源</th></tr></thead>
            <tbody>{alert.dispositions.map((item) => (
              <tr key={item.command_hash}>
                <td><strong>{item.disposition}</strong><small>结果 v{item.resulting_version}</small></td>
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
      <SectionHeading eyebrow="Outbox 投影" title="通知记录" />
      {notifications.problem ? <LoadProblem label="通知投影" problem={notifications.problem} /> : null}
      {notifications.data?.length ? (
        <div className={alertStyles.notificationList}>
          {notifications.data.map((item) => (
            <article key={item.id}>
              <header><strong>{channelLabel(item.channel)}</strong><small>告警 v{item.alert_version}</small></header>
              <span>{item.topic}</span>
              <KeyValueBlock label="安全摘要" values={item.summary} />
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
  return <span className={styles.status} data-status={value}>{statusLabel(value)}</span>;
}

function statusLabel(value: string): string {
  return { open: "打开", acknowledged: "已确认", suppressed: "已抑制", resolved: "已解决" }[value] || value.replaceAll("_", " ");
}

function channelLabel(value: NotificationProjection["channel"]): string {
  if (value === "admin_inbox") return "管理端收件箱";
  if (value === "local_smtp") return "本地 SMTP";
  return "内部 Webhook";
}

function displayValue(value: unknown): string {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  if (value === null) return "空";
  return JSON.stringify(value);
}

function formatTime(value: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString("zh-CN");
}
