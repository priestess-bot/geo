import type {
  DifyWorkflowRuntimeCard,
  DifyWorkflowRuntimePage,
  PromptLoadProblem
} from "./promptProgramTypes";
import {
  nativeReviewPromptProgramKinds,
  reservedPromptProgramKinds
} from "./promptProgramKinds";
import { DifyConsoleLink } from "./DifyConsoleLink";
import styles from "./PromptPrograms.module.css";

type WorkflowLabel = Readonly<{
  name: string;
  description: string;
  input: string;
  output: string;
}>;

const labels: Record<DifyWorkflowRuntimeCard["purpose"], WorkflowLabel> = {
  "knowledge.question_generation": {
    name: "测试问题生成",
    description: "依据业务上下文和批准事实生成 GEO 测试问题。",
    input: "问题维度、批准 Fact、主体实体",
    output: "待审核的问题草稿"
  },
  "knowledge.rag_grounding": {
    name: "知识依据生成",
    description: "为单个问题匹配可验证的事实和证据依据。",
    input: "来源正文、任务类型、输出边界",
    output: "结构化 Fact 或问题证据"
  },
  "placements.generation": {
    name: "投放内容生成",
    description: "根据 Brief、证据和目标规则生成待发布草稿。",
    input: "Brief、证据包、目标页面",
    output: "待审核的投放内容草稿"
  },
  "placements.simulation": {
    name: "投放内容仿真",
    description: "在发布前生成有边界的离线回答预览。",
    input: "内容版本、问题、证据边界",
    output: "不会发布的离线回答"
  },
  "synthetic_lab.generation": {
    name: "合成候选生成",
    description: "按冻结场景、事实和风格画像生成四条澳洲英文候选。",
    input: "测评场景、风格画像、批准 Fact",
    output: "四条待检查的澳洲英文候选"
  },
  "synthetic_lab.claim_extraction": {
    name: "Claim 提取",
    description: "从每条候选中提取可独立校验的原子 Claim。",
    input: "一条合成候选和可引用证据",
    output: "可逐项校验的原子 Claim"
  },
  "synthetic_lab.conflict_check": {
    name: "知识冲突检查",
    description: "对照批准 Fact 检查明确冲突和主体串用。",
    input: "原子 Claim、批准 Fact、主体信息",
    output: "冲突、未知推演和主体串用清单"
  },
  "synthetic_lab.revision": {
    name: "候选修订",
    description: "依据冻结问题修订候选并报告每项问题的处理结果。",
    input: "待修订候选、问题清单、批准证据",
    output: "修订候选和逐项处理结果"
  },
  "synthetic_lab.style_profile": {
    name: "风格画像生成",
    description: "从已批准、去重且匿名的渠道样本生成可冻结的澳洲英文风格画像。",
    input: "目标渠道、匿名短例、冻结样本清单",
    output: "待审核并冻结的风格画像"
  },
  "recommendations.recommendation": {
    name: "证据建议生成",
    description: "只依据冻结的真实证据形成建议和待人工处理的下游草稿意图。",
    input: "真实观测、统计、归因、Fact 和规则",
    output: "带证据的建议和下游草稿意图"
  }
};

const migrationPurposes = new Set<DifyWorkflowRuntimeCard["purpose"]>([
  "synthetic_lab.style_profile",
  "recommendations.recommendation"
]);

const nativeLabels: Record<typeof nativeReviewPromptProgramKinds[number], {
  name: string;
  description: string;
}> = {
  style_judge: {
    name: "风格评审",
    description: "根据冻结 Style Profile 和评分门槛判断候选风格。"
  },
  arbiter: {
    name: "候选仲裁",
    description: "汇总候选的冲突与风格评审结果并执行确定性仲裁。"
  },
  metric_judge: {
    name: "指标评审",
    description: "按冻结指标定义判断答案，并保留证据定位。"
  },
  offline_answer: {
    name: "离线回答",
    description: "为配对离线实验生成受语料版本约束的回答。"
  }
};

const reservedLabels: Record<typeof reservedPromptProgramKinds[number], {
  name: string;
  description: string;
}> = {
  reference_translation: {
    name: "参考内容翻译",
    description: "仅保留类型契约；当前不创建、不执行，也不在 Dify 迁移范围。"
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
          <span>Prompt、模型和流程变量只在 Dify 中修改；此处只读展示已验证的冻结版本。</span>
        </div>
        <a className={styles.refreshLink} href={`/projects/${encodeURIComponent(projectId)}?tab=prompts`}>
          刷新同步
        </a>
      </header>

      {problem ? <div className={styles.loadError} role="alert">{problem.detail}</div> : null}
      <div className={styles.difyFlowList} aria-label="Dify 工作流列表">
        {page.items.map((item) => (
          <WorkflowSection
            item={item}
            key={item.purpose}
            runtimeBackend={page.runtime_backend}
          />
        ))}
      </div>
      {page.items.length === 0 && !problem ? (
        <div className={styles.emptyState}>尚未配置 Dify 工作流。</div>
      ) : null}

      <StaticWorkflowCatalog
        catalogId="native"
        eyebrow="由 GEO 原生执行"
        heading="GEO 内置评审"
        description="这些流程依赖 GEO 状态机和确定性校验，设计上长期保留原生执行。"
        items={nativeReviewPromptProgramKinds.map((kind) => ({
          id: kind,
          ...nativeLabels[kind],
          status: "GEO 原生执行",
          note: "由 GEO Worker 执行，不读取 Dify 工作流，也不需要迁移。"
        }))}
      />
      <StaticWorkflowCatalog
        catalogId="reserved"
        eyebrow="保留类型契约"
        heading="预留能力"
        description="预留项不会进入运行队列，也不会显示为待接入工作流。"
        items={reservedPromptProgramKinds.map((kind) => ({
          id: kind,
          ...reservedLabels[kind],
          status: "预留，暂不可用",
          note: "不会进入运行队列；当前没有可配置或可执行入口。"
        }))}
        reserved
      />
    </div>
  );
}

function StaticWorkflowCatalog({
  catalogId,
  description,
  eyebrow,
  heading,
  items,
  reserved = false
}: {
  catalogId: "native" | "reserved";
  description: string;
  eyebrow: string;
  heading: string;
  items: ReadonlyArray<Readonly<{
    id: string;
    name: string;
    description: string;
    status: string;
    note: string;
  }>>;
  reserved?: boolean;
}) {
  const headingId = `workflow-catalog-${catalogId}`;
  return (
    <section aria-labelledby={headingId}>
      <header className={styles.difyHeader}>
        <div>
          <p>{eyebrow}</p>
          <h2 id={headingId}>{heading}</h2>
          <span>{description}</span>
        </div>
      </header>
      <div className={styles.difyFlowList}>
        {items.map((item) => (
          <article className={styles.difyFlow} key={item.id}>
            <header className={styles.difyFlowHeader}>
              <div>
                <div className={styles.difyTitleLine}>
                  <h3>{item.name}</h3>
                  <span className={`${styles.syncBadge} ${styles[reserved ? "sync_not_observed" : "sync_current"]}`}>
                    {item.status}
                  </span>
                </div>
                <p>{item.description}</p>
                <small className={styles.staticWorkflowNote}>{item.note}</small>
              </div>
            </header>
          </article>
        ))}
      </div>
    </section>
  );
}

function WorkflowSection({
  item,
  runtimeBackend
}: {
  item: DifyWorkflowRuntimeCard;
  runtimeBackend: DifyWorkflowRuntimePage["runtime_backend"];
}) {
  const label = labels[item.purpose];
  const available = item.published_prompt_nodes.length > 0;
  const guidance = runtimeGuidance(item, runtimeBackend);
  return (
    <section className={styles.difyFlow} aria-labelledby={`workflow-${item.purpose}`}>
      <header className={styles.difyFlowHeader}>
        <div>
          <div className={styles.difyTitleLine}>
            <h3 id={`workflow-${item.purpose}`}>{label.name}</h3>
            <div className={styles.workflowBadges}>
              <span className={`${styles.runtimeBadge} ${styles[`runtimeGuidance_${guidance.tone}`]}`}>
                {guidance.label}
              </span>
              <SyncStatus item={item} />
            </div>
          </div>
          <p>{label.description}</p>
        </div>
        {item.console_url ? (
          <DifyConsoleLink
            className={styles.difyOpenLink}
            consoleUrl={item.console_url}
          />
        ) : <span className={styles.unboundDify}>尚未绑定 Dify 应用</span>}
      </header>

      <dl className={styles.workflowContract}>
        <div><dt>输入</dt><dd>{label.input}</dd></div>
        <div><dt>产出</dt><dd>{label.output}</dd></div>
      </dl>

      <div
        className={`${styles.runtimeGuidance} ${styles[`runtimeGuidance_${guidance.tone}`]}`}
        role={guidance.tone === "blocked" ? "alert" : "status"}
      >
        <div><strong>当前状态</strong><span>{guidance.detail}</span></div>
        <p><strong>下一步</strong><span>{guidance.action}</span></p>
        {item.sync_error ? <small>系统信息：{item.sync_error}</small> : null}
      </div>

      {!available ? (
        <div className={styles.emptyPrompt}>没有可验证的已发布 Prompt 快照。完成 Dify 发布与 GEO 验证后才会在这里显示。</div>
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
          <div><dt>最近运行</dt><dd>{attemptStatusLabel(item.last_attempt_status)}</dd></div>
        </dl>
      </details>
    </section>
  );
}

function SyncStatus({ item }: { item: DifyWorkflowRuntimeCard }) {
  const value = item.sync_status === "current"
    ? "发布图一致"
    : item.sync_status === "drifted"
      ? "发布图已漂移"
    : item.sync_status === "unreachable"
      ? "Dify 暂不可达"
      : item.sync_status === "cached"
        ? "上次确认快照"
        : "未验证发布图";
  return <span className={`${styles.syncBadge} ${styles[`sync_${item.sync_status}`]}`}>{value}</span>;
}

type RuntimeGuidance = Readonly<{
  label: string;
  detail: string;
  action: string;
  tone: "ready" | "warning" | "blocked" | "migration" | "idle";
}>;

function runtimeGuidance(
  item: DifyWorkflowRuntimeCard,
  runtimeBackend: DifyWorkflowRuntimePage["runtime_backend"]
): RuntimeGuidance {
  if (isMigrationPending(item)) {
    return {
      label: "尚未完成迁移",
      detail: "没有已验证的 Dify Release 或发布快照；已有旧版业务结果（如有）不计作 Dify 验证。",
      action: "在 Dify 发布工作流，再由 GEO 注册 Release、完成真实 Canary 并激活。",
      tone: "migration"
    };
  }
  if (item.sync_status === "drifted") {
    return {
      label: "运行已阻断",
      detail: "Dify 当前发布图与已验证的冻结快照不同；新图不会用于业务任务。",
      action: "在 Dify 核对改动，然后注册、验证并激活新的 Workflow Release。",
      tone: "blocked"
    };
  }
  if (item.activation_status === "blocked_secret") {
    return {
      label: "运行已阻断",
      detail: "冻结的 Dify API 凭据不可用，业务任务会明确失败。",
      action: "修复或轮换凭据，重新执行真实 Canary 后再恢复运行。",
      tone: "blocked"
    };
  }
  if (item.activation_status === "blocked_prompt_retired") {
    return {
      label: "运行已阻断",
      detail: "此工作流关联的 Prompt Release 已停用，不能继续执行。",
      action: "在 Dify 发布新版本，并注册、验证和激活新的 Workflow Release。",
      tone: "blocked"
    };
  }
  if (item.activation_status === "stale_prompt") {
    return {
      label: "运行已阻断",
      detail: "GEO 已发布新 Prompt，但 Dify 仍绑定旧版本。",
      action: "同步 Dify 工作流并完成新 Release 的真实验证与激活。",
      tone: "blocked"
    };
  }
  if (item.activation_status === "not_configured") {
    return {
      label: "尚未启用",
      detail: "没有已激活的 Dify Release，当前不会调用 Dify。",
      action: "先在 Dify 发布，再由 GEO 注册 Release、执行真实 Canary 并激活。",
      tone: "idle"
    };
  }
  if (runtimeBackend !== "dify") {
    return {
      label: "已验证，当前原生执行",
      detail: "Dify Release 已保留，但全局运行后端当前显式使用 GEO 原生流程。",
      action: "确认切换窗口后启用 Dify 运行后端；不要把已验证等同于正在调用。",
      tone: "warning"
    };
  }
  if (item.sync_status === "current") {
    return {
      label: "业务运行中",
      detail: "业务任务调用此已验证冻结版本，输出通过 GEO 校验后才会保存。",
      action: "无需处理；修改 Prompt 时先在 Dify 发布新版本，再完成验证和激活。",
      tone: "ready"
    };
  }
  return {
    label: "业务已启用，状态待确认",
    detail: "业务仍绑定已验证的冻结 Release，但看板暂时无法确认 Dify 当前发布图。",
    action: "恢复 Dify Console 连接并刷新同步；不要覆盖当前冻结 Release。",
    tone: "warning"
  };
}

function isMigrationPending(item: DifyWorkflowRuntimeCard): boolean {
  return migrationPurposes.has(item.purpose)
    && item.backend === "native"
    && item.activation_status === "not_configured"
    && item.release_id === null
    && item.published_snapshot_hash === null;
}

function attemptStatusLabel(status: string | null): string {
  if (!status) return "暂无";
  return {
    succeeded: "成功",
    failed: "失败",
    running: "运行中",
    queued: "排队中",
    cancelled: "已取消",
    dead_lettered: "已终止"
  }[status] || status;
}

function shortHash(value: string | null): string {
  return value ? `${value.slice(0, 12)}...` : "暂无";
}

function formatDate(value: string | null): string {
  if (!value) return "暂无";
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" })
    .format(new Date(value));
}
