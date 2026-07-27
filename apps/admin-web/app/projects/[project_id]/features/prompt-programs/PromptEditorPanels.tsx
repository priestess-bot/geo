import { useEffect, useState } from "react";

import {
  workflowPromptProgramKinds,
  type DifyWorkflowRuntimeCard,
  type PromptFlow,
  type PromptProgramReleaseDetail,
  type PromptRenderPreview,
  type PromptTestRun,
  type PromptWorkspaceData,
  type PromptWorkingDraft
} from "./promptProgramTypes";
import styles from "./PromptPrograms.module.css";

export type SaveState = "saved" | "saving" | "dirty" | "error";

export function DifyConsoleLink({
  className = "button secondary",
  consoleUrl,
  label = "打开 Dify 工作流"
}: {
  className?: string;
  consoleUrl: string | null | undefined;
  label?: string;
}) {
  const [href, setHref] = useState<string | null>(null);

  useEffect(() => {
    setHref(resolveDifyConsoleUrl(consoleUrl));
  }, [consoleUrl]);

  if (!href) return null;
  return <a className={className} href={href} rel="noreferrer" target="_blank">{label}</a>;
}

function resolveDifyConsoleUrl(consoleUrl: string | null | undefined): string | null {
  if (!consoleUrl) return null;
  try {
    const target = new URL(consoleUrl);
    const isLocalConsole = target.hostname === "127.0.0.1"
      || target.hostname === "localhost"
      || target.hostname === "::1";
    if (isLocalConsole && typeof window !== "undefined") {
      target.hostname = window.location.hostname;
    }
    return target.toString();
  } catch {
    return null;
  }
}

const DIFY_CONTEXT_ROWS: Readonly<Record<string, ReadonlyArray<Readonly<{
  key: string;
  label: string;
  description: string;
  source: string;
}>>>> = {
  "knowledge.question_generation": [
    { key: "dimensions", label: "问题维度", description: "问题意图、轮次和父级关系。", source: "Question Job" },
    { key: "facts", label: "批准事实", description: "本批问题允许使用的 Fact ID 与原文。", source: "知识库快照" },
    { key: "entities", label: "主体实体", description: "允许引用的品牌、产品及实体 ID。", source: "实体图快照" },
    { key: "parent_candidates", label: "父问题", description: "多轮问题可引用的已生成父问题。", source: "当前生成批次" }
  ],
  "knowledge.rag_grounding": [
    { key: "adapter_purpose", label: "适配器任务", description: "区分事实抽取或问题证据约束。", source: "RAG Adapter" },
    { key: "messages", label: "业务消息", description: "包含来源正文、允许类型和精确输出要求。", source: "知识处理 Job" },
    { key: "max_output_tokens", label: "输出上限", description: "当前调用冻结的最大输出 Token。", source: "RAG Release" }
  ],
  "placements.generation": [
    { key: "prompt_bundle_id", label: "Prompt 包", description: "当前内容任务冻结的 Prompt 包身份。", source: "Placement Job" },
    { key: "campaign_id", label: "Campaign", description: "内容所属 Campaign；没有时为空。", source: "内容任务快照" },
    { key: "destination_id", label: "目标页面", description: "内容准备投放的目标页面身份。", source: "内容任务快照" },
    { key: "evidence_item_ids", label: "内部证据", description: "允许支撑事实声明的证据 ID。", source: "证据包" },
    { key: "public_citation_item_ids", label: "公开引用", description: "允许出现在成品中的公开引用 ID。", source: "证据包" }
  ],
  "placements.simulation": [
    { key: "simulation_id", label: "仿真任务", description: "本次离线仿真的稳定身份。", source: "Simulation Job" },
    { key: "authenticity_mode", label: "真实性模式", description: "决定证据披露与生成边界。", source: "仿真快照" },
    { key: "destination_id", label: "目标页面", description: "被仿真的目标页面身份。", source: "仿真快照" },
    { key: "evidence_item_ids", label: "内部证据", description: "仿真允许使用的内部证据 ID。", source: "证据包" },
    { key: "public_citation_item_ids", label: "公开引用", description: "仿真允许输出的引用 ID。", source: "证据包" }
  ]
};

export function DifyWorkflowCanvas({
  draft,
  flow,
  release,
  runtime,
  runtimeBackend
}: {
  draft: PromptWorkingDraft;
  flow: PromptFlow;
  release: PromptProgramReleaseDetail | null;
  runtime: DifyWorkflowRuntimeCard | null;
  runtimeBackend: "native" | "dify";
}) {
  const systemPrompt = runtime?.prompt_system_template
    || release?.system_template
    || draft.system_template;
  const userPrompt = runtime?.prompt_user_template
    || release?.user_template
    || draft.user_template;
  const rows = DIFY_CONTEXT_ROWS[flow.purpose] || [];
  return (
    <div className={styles.difyCanvas}>
      <div className={styles.difyTitleRow}>
        <div>
          <span>Dify Workflow</span>
          <h3>{flow.display_name}</h3>
          <p>{flow.description}</p>
        </div>
        <span className={`${styles.runtimeState} ${styles[`runtime_${runtimeTone(runtime, runtimeBackend)}`]}`}>
          {runtimeStatusLabel(runtime, runtimeBackend)}
        </span>
      </div>

      <div className={styles.workflowPath} aria-label="工作流执行路径">
        <div><span>1</span><strong>GEO 冻结上下文</strong><small>按 Job 生成</small></div>
        <i aria-hidden="true" />
        <div><span>2</span><strong>Dify Workflow</strong><small>{runtime?.configured_model || "等待配置模型"}</small></div>
        <i aria-hidden="true" />
        <div><span>3</span><strong>GEO 业务校验</strong><small>通过后才落库</small></div>
      </div>

      <section className={styles.difyPromptSection}>
        <header>
          <div><h4>实际发送的规则 Prompt</h4><p>每次调用会在这层规则后附加当前 Job 的具体任务。</p></div>
          <span>{runtime?.prompt_release_id ? `Dify Release v${runtime.release_version}` : "当前 Program 版本"}</span>
        </header>
        <div className={styles.readonlyPrompts}>
          <article><h5>System Prompt</h5><pre>{systemPrompt}</pre></article>
          <article><h5>User Prompt</h5><pre>{userPrompt}</pre></article>
        </div>
      </section>

      <section className={styles.difyContextSection}>
        <header><div><h4>运行时上下文</h4><p>字段由业务 Job 按用途组装，不支持在 Prompt 中任意插槽。</p></div><span>只读</span></header>
        <div className={styles.contextTable} role="table" aria-label={`${flow.display_name}运行时上下文`}>
          <div className={styles.contextTableHead} role="row"><span>字段</span><span>含义</span><span>来源</span></div>
          {rows.map((row) => (
            <div key={row.key} role="row">
              <span><strong>{row.label}</strong><code>{row.key}</code></span><span>{row.description}</span><small>{row.source}</small>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

export function DifyRuntimeRail({
  flow,
  runtime,
  runtimeBackend
}: {
  flow: PromptFlow | null;
  runtime: DifyWorkflowRuntimeCard | null;
  runtimeBackend: "native" | "dify";
}) {
  return (
    <>
      <section className={styles.runtimePanel}>
        <header><h3>当前运行</h3><span className={`${styles.runtimeState} ${styles[`runtime_${runtimeTone(runtime, runtimeBackend)}`]}`}>{runtimeStatusLabel(runtime, runtimeBackend)}</span></header>
        <p>{runtimeStatusDetail(runtime, runtimeBackend)}</p>
        <DifyConsoleLink consoleUrl={runtime?.console_url} label="打开当前工作流" />
      </section>
      <section className={styles.runtimePanel}>
        <header><h3>运行版本</h3></header>
        <dl>
          <div><dt>用途</dt><dd>{flow?.purpose || "-"}</dd></div>
          <div><dt>模型</dt><dd>{runtime?.configured_model || "-"}</dd></div>
          <div><dt>Dify Release</dt><dd>{runtime?.release_version ? `v${runtime.release_version}` : "-"}</dd></div>
          <div><dt>Prompt Release</dt><dd>{shortId(runtime?.prompt_release_id)}</dd></div>
          <div><dt>DSL Hash</dt><dd><code>{shortHash(runtime?.dsl_hash)}</code></dd></div>
        </dl>
      </section>
      <section className={styles.runtimePanel}>
        <header><h3>最近执行</h3></header>
        {runtime?.last_attempt_status ? (
          <dl>
            <div><dt>类型</dt><dd>{runtime.last_attempt_kind === "canary" ? "真实 Canary" : "业务任务"}</dd></div>
            <div><dt>结果</dt><dd>{runtime.last_attempt_status === "succeeded" ? "成功" : "失败"}</dd></div>
            <div><dt>时间</dt><dd>{runtime.last_attempt_at ? formatTime(runtime.last_attempt_at) : "-"}</dd></div>
          </dl>
        ) : <p>尚无 Dify 执行记录。</p>}
        {runtime?.last_error_message ? <div className={styles.runtimeError}><strong>{runtime.last_error_code || "执行失败"}</strong><span>{runtime.last_error_message}</span></div> : null}
      </section>
    </>
  );
}

export function PreviewPanel({ preview }: { preview: PromptRenderPreview | null }) {
  if (!preview) return <div className={styles.previewLoading}>正在按固定测试 Case 拼接 Prompt...</div>;
  return (
    <div className={styles.previewPanel}>
      <header><div><strong>{preview.fixture_label}</strong><span>{preview.fixture_id}</span></div></header>
      <div className={styles.previewColumns}>
        <PromptPreviewColumn label="工作草稿" prompt={preview.draft} />
        {preview.current ? <PromptPreviewColumn label={`当前版本 v${preview.current_release_version}`} prompt={preview.current} /> : null}
      </div>
    </div>
  );
}

function PromptPreviewColumn({ label, prompt }: { label: string; prompt: PromptRenderPreview["draft"] }) {
  return (
    <section>
      <h3>{label}</h3>
      <h4>System Prompt</h4><pre>{prompt.system_prompt}</pre>
      <h4>User Prompt</h4><pre>{prompt.user_prompt}</pre>
    </section>
  );
}

export function HistoryPanel({
  flowKey,
  onRestore,
  projectId,
  releases,
  selected
}: {
  flowKey: string;
  onRestore: (release: PromptProgramReleaseDetail) => void;
  projectId: string;
  releases: PromptWorkspaceData["releases"]["items"];
  selected: PromptProgramReleaseDetail | null;
}) {
  return (
    <div className={styles.historyPanel}>
      <nav aria-label="Prompt 版本">
        {releases.map((release) => (
          <a className={release.id === selected?.id ? styles.historyActive : undefined} href={historyHref(projectId, flowKey, release.id)} key={release.id}>
            <strong>v{release.version}</strong><span>{releaseStatus(release.state.status)}</span>
          </a>
        ))}
      </nav>
      {selected ? (
        <section>
          <header><div><h3>v{selected.version}</h3><span>{formatTime(selected.state.acted_at)}</span></div><button onClick={() => onRestore(selected)} type="button">载入为草稿</button></header>
          <h4>System Prompt</h4><pre>{selected.system_template}</pre>
          <h4>User Prompt</h4><pre>{selected.user_template}</pre>
        </section>
      ) : <div className={styles.promptEmpty}>选择版本查看完整 Prompt。</div>}
    </div>
  );
}

export function TestRunList({ items }: { items: PromptTestRun[] }) {
  if (!items.length) return <p className={styles.noTests}>尚未运行固定测试。</p>;
  return (
    <div className={styles.testRuns}>
      {items.slice(0, 5).map((run) => (
        <div key={run.job_id}>
          <span className={styles[`test_${testTone(run)}`]}>{testLabel(run)}</span>
          <strong>候选 v{run.release_version}</strong>
          <small>{formatTime(run.requested_at)}</small>
          {run.error_code ? <code>{run.error_code}</code> : null}
        </div>
      ))}
    </div>
  );
}

export function flowHref(projectId: string, flowKey: string): string {
  return `/projects/${encodeURIComponent(projectId)}?tab=prompts&prompt_flow=${encodeURIComponent(flowKey)}`;
}

export function matchesFlow(flow: PromptFlow, search: string): boolean {
  const query = search.trim().toLocaleLowerCase("zh-CN");
  if (!query) return true;
  return [flow.display_name, flow.description, flow.purpose]
    .some((value) => value.toLocaleLowerCase("zh-CN").includes(query));
}

function historyHref(projectId: string, flowKey: string, releaseId: string): string {
  return `${flowHref(projectId, flowKey)}&prompt_release_id=${encodeURIComponent(releaseId)}`;
}

export function flowStatus(
  flow: PromptFlow,
  runtime?: DifyWorkflowRuntimeCard,
  runtimeBackend: "native" | "dify" = "native"
): string {
  if (isDifyManagedFlow(flow)) return runtimeStatusLabel(runtime || null, runtimeBackend);
  if (flow.latest_test_status && isActiveTest(flow.latest_test_status)) return "测试中";
  if (flow.candidate_status === "tested") return "可发布";
  if (flow.draft && flow.current_release_id !== flow.draft.base_release_id) return "有草稿";
  return flow.current_release_version ? `当前 v${flow.current_release_version}` : "未发布";
}

export function isDifyManagedFlow(flow: PromptFlow | null): boolean {
  return Boolean(flow && workflowPromptProgramKinds.includes(
    flow.program_kind as typeof workflowPromptProgramKinds[number]
  ));
}

export function runtimeTone(
  runtime: DifyWorkflowRuntimeCard | null,
  backend: "native" | "dify"
): "active" | "idle" | "warning" | "blocked" {
  if (!runtime || runtime.activation_status === "not_configured") return "idle";
  if (runtime.activation_status !== "active") return "blocked";
  return backend === "dify" ? "active" : "warning";
}

export function runtimeStatusLabel(
  runtime: DifyWorkflowRuntimeCard | null,
  backend: "native" | "dify"
): string {
  if (!runtime || runtime.activation_status === "not_configured") return "尚未接入 Dify";
  if (runtime.activation_status === "blocked_secret") return "凭据不可用";
  if (runtime.activation_status === "blocked_prompt_retired") return "Prompt 已停用";
  if (runtime.activation_status === "stale_prompt") return "等待同步新 Prompt";
  return backend === "dify" ? "Dify 运行中" : "已配置，当前原生";
}

function runtimeStatusDetail(
  runtime: DifyWorkflowRuntimeCard | null,
  backend: "native" | "dify"
): string {
  if (!runtime || runtime.activation_status === "not_configured") {
    return "这个流程尚未绑定已通过真实 Canary 的 Dify Release，当前继续使用 GEO 原生执行。";
  }
  if (runtime.activation_status === "blocked_secret") {
    return "冻结的 Dify API 凭据已不可用。业务任务会明确失败，不会静默切换模型。";
  }
  if (runtime.activation_status === "blocked_prompt_retired") {
    return "该 Release 关联的 Prompt 已停用，需要重新发布并注册新的运行版本。";
  }
  if (runtime.activation_status === "stale_prompt") {
    return "当前 Program 已发布新版本，Dify 仍绑定旧 Prompt，因此暂停使用。";
  }
  return backend === "dify"
    ? "Worker 正在调用已激活的 Dify Workflow；输出通过 GEO 业务校验后才会保存。"
    : "Release 已验证并保留，但 Worker 当前显式回滚到 GEO 原生执行。";
}

function shortId(value: string | null | undefined): string {
  return value ? `${value.slice(0, 8)}...${value.slice(-4)}` : "-";
}

function shortHash(value: string | null | undefined): string {
  return value ? `${value.slice(0, 10)}...${value.slice(-6)}` : "-";
}

export function saveLabel(state: SaveState): string {
  return { saved: "已保存", saving: "保存中", dirty: "未保存", error: "保存失败" }[state];
}

export function draftContent(draft: PromptWorkingDraft | null): string {
  return draft ? contentKey(draft.display_name, draft.system_template, draft.user_template) : "";
}

export function contentKey(name: string, system: string, user: string): string {
  return `${name}\u0000${system}\u0000${user}`;
}

export function isActiveTest(status: string): boolean {
  return ["queued", "running", "finalizing", "retry_wait"].includes(status);
}

function testTone(run: PromptTestRun): "running" | "passed" | "failed" {
  if (isActiveTest(run.status)) return "running";
  return run.passed === true ? "passed" : "failed";
}

function testLabel(run: PromptTestRun): string {
  if (isActiveTest(run.status)) return "运行中";
  if (run.passed === true) return `通过${run.score === null ? "" : ` · ${run.score} 分`}`;
  if (run.status === "succeeded") return `未通过${run.score === null ? "" : ` · ${run.score} 分`}`;
  return "执行失败";
}

function releaseStatus(status: string): string {
  return { draft: "候选", tested: "测试通过", approved: "已批准", frozen: "已发布", retired: "已停用" }[status] || status;
}

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23"
  }).formatToParts(date);
  const part = (type: Intl.DateTimeFormatPartTypes): string => (
    parts.find((item) => item.type === type)?.value || "00"
  );
  return `${part("year")}-${part("month")}-${part("day")} ${part("hour")}:${part("minute")}:${part("second")} 北京时间`;
}
