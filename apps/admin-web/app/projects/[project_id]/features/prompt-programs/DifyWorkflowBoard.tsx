import type {
  DifyWorkflowRuntimeCard,
  DifyWorkflowRuntimePage,
  PromptLoadProblem
} from "./promptProgramTypes";
import styles from "./PromptPrograms.module.css";

const labels: Record<DifyWorkflowRuntimeCard["purpose"], { name: string; description: string }> = {
  "knowledge.question_generation": {
    name: "测试问题生成",
    description: "依据业务上下文和批准事实生成 GEO 测试问题。"
  },
  "knowledge.rag_grounding": {
    name: "知识依据生成",
    description: "为单个问题匹配可验证的事实和证据依据。"
  },
  "placements.generation": {
    name: "投放内容生成",
    description: "根据 Brief、证据和目标规则生成待发布草稿。"
  },
  "placements.simulation": {
    name: "投放内容仿真",
    description: "在发布前生成有边界的离线回答预览。"
  }
};

export function DifyWorkflowBoard({
  page,
  problem,
  projectId
}: {
  page: DifyWorkflowRuntimePage;
  problem?: PromptLoadProblem;
  projectId: string;
}) {
  return (
    <div className={styles.difyBoard}>
      <header className={styles.difyHeader}>
        <div>
          <p>由 Dify 托管</p>
          <h2>Dify 工作流</h2>
          <span>Prompt、模型和流程变量只在 Dify 中修改；此处展示当前已发布版本。</span>
        </div>
        <a className={styles.refreshLink} href={`/projects/${encodeURIComponent(projectId)}?tab=prompts`}>
          刷新同步
        </a>
      </header>

      {problem ? <div className={styles.loadError} role="alert">{problem.detail}</div> : null}
      <div className={styles.difyFlowList} aria-label="Dify 工作流列表">
        {page.items.map((item) => <WorkflowSection item={item} key={item.purpose} />)}
      </div>
      {page.items.length === 0 && !problem ? (
        <div className={styles.emptyState}>尚未配置 Dify 工作流。</div>
      ) : null}
    </div>
  );
}

function WorkflowSection({ item }: { item: DifyWorkflowRuntimeCard }) {
  const label = labels[item.purpose];
  const available = item.published_prompt_nodes.length > 0;
  return (
    <section className={styles.difyFlow} aria-labelledby={`workflow-${item.purpose}`}>
      <header className={styles.difyFlowHeader}>
        <div>
          <div className={styles.difyTitleLine}>
            <h3 id={`workflow-${item.purpose}`}>{label.name}</h3>
            <SyncStatus item={item} />
          </div>
          <p>{label.description}</p>
        </div>
        {item.console_url ? (
          <a href={item.console_url} rel="noreferrer" target="_blank">在 Dify 中编辑</a>
        ) : null}
      </header>

      {item.sync_status === "unreachable" ? (
        <div className={styles.syncWarning} role="status">
          Dify 当前无法连接。下面显示最后一次成功同步的快照；业务任务不会回退到本地 Prompt。
          {item.sync_error ? <small>{item.sync_error}</small> : null}
        </div>
      ) : null}
      {!available ? (
        <div className={styles.emptyPrompt}>还没有可展示的已发布 Prompt，请先在 Dify 发布工作流。</div>
      ) : (
        item.published_prompt_nodes.map((node) => (
          <div className={styles.difyPromptNode} key={node.node_id}>
            <div className={styles.nodeMeta}>
              <strong>{node.title}</strong>
              <span>{node.model_name || "未识别模型"}</span>
              <code>{node.model_provider || "未识别 Provider"}</code>
            </div>
            <div className={styles.promptMessages}>
              {node.messages.map((message, index) => (
                <article key={`${message.role}-${index}`}>
                  <h4>{message.role === "system" ? "System Prompt" : "User Prompt"}</h4>
                  <pre>{message.text}</pre>
                </article>
              ))}
            </div>
          </div>
        ))
      )}

      <details className={styles.difyDetails}>
        <summary>输入变量与版本信息</summary>
        <div className={styles.variableGrid}>
          {item.published_input_variables.map((variable) => (
            <div key={variable.name}>
              <code>{variable.name}</code>
              <span>{variable.label}{variable.required ? " · 必填" : ""}</span>
              {variable.description ? <small>{variable.description}</small> : null}
            </div>
          ))}
        </div>
        <dl className={styles.snapshotMeta}>
          <div><dt>发布版本</dt><dd><code>{shortHash(item.published_workflow_hash)}</code></dd></div>
          <div><dt>快照</dt><dd><code>{shortHash(item.published_snapshot_hash)}</code></dd></div>
          <div><dt>最后同步</dt><dd>{formatDate(item.observed_at)}</dd></div>
          <div><dt>最近运行</dt><dd>{item.last_attempt_status || "暂无"}</dd></div>
        </dl>
      </details>
    </section>
  );
}

function SyncStatus({ item }: { item: DifyWorkflowRuntimeCard }) {
  const value = item.sync_status === "current"
    ? "已同步"
    : item.sync_status === "unreachable"
      ? "使用缓存"
      : item.sync_status === "cached"
        ? "上次快照"
        : "未同步";
  return <span className={`${styles.syncBadge} ${styles[`sync_${item.sync_status}`]}`}>{value}</span>;
}

function shortHash(value: string | null): string {
  return value ? `${value.slice(0, 12)}...` : "暂无";
}

function formatDate(value: string | null): string {
  if (!value) return "暂无";
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" })
    .format(new Date(value));
}
