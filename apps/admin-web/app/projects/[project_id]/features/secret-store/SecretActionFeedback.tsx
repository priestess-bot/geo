import type { SecretActionState } from "./secretStoreTypes";
import styles from "./SecretStore.module.css";

export function SecretActionFeedback({ state }: { state: SecretActionState }) {
  if (state.kind === "idle") return null;
  return (
    <div
      className={state.kind === "error" ? styles.errorFeedback : styles.successFeedback}
      role={state.kind === "error" ? "alert" : "status"}
    >
      <strong>{state.status ? `${state.status} · ` : ""}{state.message}</strong>
      {state.correlationId ? <small>关联 ID：{state.correlationId}</small> : null}
      {state.version ? (
        <dl className={styles.feedbackMetadata}>
          <div><dt>密钥版本</dt><dd>v{state.version.version} · {state.version.status}</dd></div>
          <div><dt>聚合版本</dt><dd>{state.version.aggregate_version}</dd></div>
          <div><dt>主密钥版本</dt><dd>{state.version.master_key_version}</dd></div>
          <div><dt>指纹</dt><dd><code>{state.version.fingerprint}</code></dd></div>
          <div><dt>已验证</dt><dd>{formatTime(state.version.verified_at)}</dd></div>
          <div><dt>已激活 / 已撤销</dt><dd>{formatTime(state.version.activated_at || state.version.revoked_at)}</dd></div>
        </dl>
      ) : null}
      {state.nextHref ? <a className={styles.resultLink} href={state.nextHref}>打开 Reference</a> : null}
    </div>
  );
}

function formatTime(value: string | null): string {
  if (!value) return "-";
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleString("zh-CN");
}
