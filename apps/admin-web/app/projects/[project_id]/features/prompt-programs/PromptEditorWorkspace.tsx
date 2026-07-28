"use client";

import { useCallback, useEffect, useMemo, useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import {
  initializePromptWorkspaceAction,
  loadPromptTestRunsAction,
  publishPromptDraftAction,
  renderPromptDraftAction,
  runPromptSuiteAction,
  savePromptDraftAction
} from "./promptWorkspaceActions";
import {
  DifyWorkflowRuntimeCard,
  PromptFlow,
  PromptProgramReleaseDetail,
  PromptRenderPreview,
  PromptWorkspaceData,
  PromptWorkingDraft
} from "./promptProgramTypes";
import {
  contentKey,
  DifyConsoleLink,
  DifyRuntimeRail,
  DifyWorkflowCanvas,
  draftContent,
  flowHref,
  flowStatus,
  HistoryPanel,
  isActiveTest,
  isDifyManagedFlow,
  matchesFlow,
  PreviewPanel,
  runtimeStatusLabel,
  runtimeTone,
  saveLabel,
  TestRunList,
  type SaveState
} from "./PromptEditorPanels";
import styles from "./PromptPrograms.module.css";

type EditorTab = "edit" | "preview" | "history" | "workflow";
type MobileRegion = "flows" | "editor" | "test";

const GROUPS: ReadonlyArray<Readonly<{
  id: PromptFlow["group"];
  label: string;
}>> = [
  { id: "synthetic_lab", label: "内部合成测评" },
  { id: "question_and_content", label: "问题与内容生成" },
  { id: "measurement_and_recommendation", label: "测量与建议" }
];

const REQUEST_JSON_BLOCK = "<request_json>\n{{request_json}}\n</request_json>";

export function PromptEditorWorkspace({
  canEdit,
  canPublish,
  data,
  projectId
}: {
  canEdit: boolean;
  canPublish: boolean;
  data: PromptWorkspaceData;
  projectId: string;
}) {
  const router = useRouter();
  const flow = data.selectedFlow;
  const difyManaged = isDifyManagedFlow(flow);
  const workflowRuntimesByPurpose = useMemo(
    () => new Map<string, DifyWorkflowRuntimeCard>(
      data.workflowRuntimes.items.map((item) => [item.purpose, item])
    ),
    [data.workflowRuntimes.items]
  );
  const workflowRuntime = flow
    ? workflowRuntimesByPurpose.get(flow.purpose) || null
    : null;
  const difyConsoleUrl = workflowRuntime?.console_url
    || data.workflowRuntimes.items.find((item) => item.console_url)?.console_url
    || null;
  const initialDraft = flow?.draft || null;
  const [draft, setDraft] = useState(initialDraft);
  const [displayName, setDisplayName] = useState(initialDraft?.display_name || flow?.display_name || "");
  const [systemTemplate, setSystemTemplate] = useState(initialDraft?.system_template || "");
  const [userTemplate, setUserTemplate] = useState(initialDraft?.user_template || "");
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [message, setMessage] = useState<string | null>(null);
  const [editorTab, setEditorTab] = useState<EditorTab>("edit");
  const [mobileRegion, setMobileRegion] = useState<MobileRegion>("editor");
  const [activeEditor, setActiveEditor] = useState<"system" | "user">("user");
  const [preview, setPreview] = useState<PromptRenderPreview | null>(null);
  const [runtimeId, setRuntimeId] = useState(data.testRuntimes[0]?.runtime_selection_id || "");
  const [testRuns, setTestRuns] = useState(data.testRuns.items);
  const [candidateReady, setCandidateReady] = useState(flow?.candidate_status === "tested");
  const [search, setSearch] = useState("");
  const [isPending, startTransition] = useTransition();
  const systemRef = useRef<HTMLTextAreaElement>(null);
  const userRef = useRef<HTMLTextAreaElement>(null);
  const lastSavedContent = useRef(draftContent(initialDraft));
  const saveSequence = useRef(0);

  useEffect(() => {
    setDraft(initialDraft);
    setDisplayName(initialDraft?.display_name || flow?.display_name || "");
    setSystemTemplate(initialDraft?.system_template || "");
    setUserTemplate(initialDraft?.user_template || "");
    setSaveState("saved");
    setMessage(null);
    setPreview(null);
    setTestRuns(data.testRuns.items);
    setCandidateReady(flow?.candidate_status === "tested");
    lastSavedContent.current = draftContent(initialDraft);
  }, [flow?.flow_key, initialDraft?.program_id]);

  const currentContent = useMemo(
    () => contentKey(displayName, systemTemplate, userTemplate),
    [displayName, systemTemplate, userTemplate]
  );

  const save = useCallback(async (): Promise<PromptWorkingDraft | null> => {
    if (!flow?.program || !draft || !canEdit) return draft;
    if (!displayName.trim() || !systemTemplate.trim() || !userTemplate.trim()) {
      setSaveState("error");
      setMessage("名称、System Prompt 和 User Prompt 不能为空。");
      return null;
    }
    const content = contentKey(displayName, systemTemplate, userTemplate);
    if (content === lastSavedContent.current) {
      setSaveState("saved");
      return draft;
    }
    const sequence = ++saveSequence.current;
    setSaveState("saving");
    const result = await savePromptDraftAction({
      projectId,
      programId: flow.program.id,
      displayName,
      systemTemplate,
      userTemplate,
      expectedRevision: draft.revision
    });
    if (sequence !== saveSequence.current) return null;
    if (!result.ok) {
      setSaveState("error");
      setMessage(result.status === 409
        ? "草稿已在其他请求中更新，请刷新后继续编辑。"
        : result.message);
      return null;
    }
    setDraft(result.data);
    lastSavedContent.current = content;
    setSaveState("saved");
    setMessage(null);
    setCandidateReady(false);
    return result.data;
  }, [canEdit, displayName, draft, flow?.program, projectId, systemTemplate, userTemplate]);

  useEffect(() => {
    if (!draft || currentContent === lastSavedContent.current) return;
    setSaveState("dirty");
    const timer = window.setTimeout(() => void save(), 1000);
    return () => window.clearTimeout(timer);
  }, [currentContent, draft, save]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        void save();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [save]);

  const running = testRuns.some((run) => isActiveTest(run.status));
  useEffect(() => {
    if (!running || !flow?.program) return;
    const timer = window.setInterval(() => {
      void refreshTests(flow.program!.id);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [running, flow?.program, draft?.candidate_release_id]);

  async function refreshTests(programId: string): Promise<void> {
    const result = await loadPromptTestRunsAction({ projectId, programId });
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    setTestRuns(result.data.items);
    setCandidateReady(Boolean(
      draft?.candidate_release_id
      && result.data.items.some((run) => (
        run.release_id === draft.candidate_release_id && run.passed === true
      ))
    ));
  }

  function insertSlot(insertion: string): void {
    const target = activeEditor === "system" ? systemRef.current : userRef.current;
    const value = activeEditor === "system" ? systemTemplate : userTemplate;
    if (!target) return;
    const start = target.selectionStart;
    const end = target.selectionEnd;
    const prefix = start > 0 && value[start - 1] !== "\n" ? "\n" : "";
    const suffix = end < value.length && value[end] !== "\n" ? "\n" : "";
    const next = `${value.slice(0, start)}${prefix}${insertion}${suffix}${value.slice(end)}`;
    if (activeEditor === "system") setSystemTemplate(next);
    else setUserTemplate(next);
    window.requestAnimationFrame(() => {
      const cursor = start + prefix.length + insertion.length;
      target.focus();
      target.setSelectionRange(cursor, cursor);
    });
  }

  const activeTemplate = activeEditor === "system" ? systemTemplate : userTemplate;
  const requestBlockPresent = activeTemplate.includes("<request_json>");

  async function openPreview(): Promise<void> {
    if (!flow?.program) return;
    const saved = await save();
    if (!saved) return;
    setEditorTab("preview");
    setMessage(null);
    const result = await renderPromptDraftAction({
      projectId,
      programId: flow.program.id
    });
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    setPreview(result.data);
  }

  function runSuite(): void {
    if (!flow?.program || !runtimeId || !draft) return;
    startTransition(async () => {
      const saved = await save();
      if (!saved) return;
      setMessage(null);
      const result = await runPromptSuiteAction({
        projectId,
        programId: flow.program!.id,
        runtimeSelectionId: runtimeId,
        expectedRevision: saved.revision,
        idempotencyKey: crypto.randomUUID()
      });
      if (!result.ok) {
        setMessage(result.message);
        return;
      }
      setDraft(result.data.draft);
      setTestRuns((items) => [
        {
          job_id: result.data.job.job_id,
          project_id: result.data.job.project_id,
          program_id: flow.program!.id,
          release_id: result.data.job.release_id,
          release_version: result.data.candidate_release.version,
          status: result.data.job.status,
          requested_at: new Date().toISOString(),
          finished_at: null,
          passed: null,
          score: null,
          result_ref: null,
          error_code: null
        },
        ...items.filter((item) => item.job_id !== result.data.job.job_id)
      ]);
      setCandidateReady(false);
      setMessage("固定测试已启动，结果会自动刷新。");
    });
  }

  function publish(): void {
    if (!flow?.program || !draft || !candidateReady || !canPublish) return;
    startTransition(async () => {
      const saved = await save();
      if (!saved) return;
      const result = await publishPromptDraftAction({
        projectId,
        programId: flow.program!.id,
        expectedRevision: saved.revision,
        idempotencyKey: crypto.randomUUID()
      });
      if (!result.ok) {
        setMessage(result.message);
        return;
      }
      setDraft(result.data.draft);
      setCandidateReady(false);
      setMessage(`v${result.data.release.version} 已发布并生效。`);
      router.refresh();
    });
  }

  function initializeWorkspace(): void {
    startTransition(async () => {
      setMessage(null);
      const result = await initializePromptWorkspaceAction({ projectId });
      if (!result.ok) {
        setMessage(result.message);
        return;
      }
      if (result.data.failed_count > 0) {
        setMessage(`已创建 ${result.data.created_count} 个 Prompt，${result.data.failed_count} 个失败。`);
        return;
      }
      router.refresh();
    });
  }

  function restoreRelease(release: PromptProgramReleaseDetail): void {
    setSystemTemplate(release.system_template);
    setUserTemplate(release.user_template);
    setEditorTab("edit");
    setMessage(`已将 v${release.version} 载入工作草稿，保存后不会修改历史版本。`);
  }

  return (
    <div className={styles.editorWorkspace}>
      <header className={styles.editorHeader}>
        <div>
          <h2>Prompt 程序</h2>
        </div>
        <div className={styles.headerActions}>
          <DifyConsoleLink consoleUrl={difyConsoleUrl} />
          {difyManaged ? (
            <>
            <span className={`${styles.runtimeState} ${styles[`runtime_${runtimeTone(workflowRuntime, data.workflowRuntimes.runtime_backend)}`]}`}>
              {runtimeStatusLabel(workflowRuntime, data.workflowRuntimes.runtime_backend)}
            </span>
            </>
          ) : null}
          <span className={`${styles.saveStatus} ${styles[`save_${saveState}`]}`}>
            {saveLabel(saveState)}
          </span>
          <button className="button secondary" disabled={!canEdit || saveState === "saving"} onClick={() => void save()} type="button">
            保存
          </button>
          <button className="button" disabled={!canPublish || !candidateReady || isPending} onClick={publish} type="button">
            {isPending ? "处理中" : "发布并生效"}
          </button>
        </div>
      </header>

      <nav className={styles.mobileRegions} aria-label="Prompt 工作区">
        {(["flows", "editor", "test"] as const).map((region) => (
          <button
            className={mobileRegion === region ? styles.mobileRegionActive : undefined}
            key={region}
            onClick={() => setMobileRegion(region)}
            type="button"
          >
            {{ flows: "Prompt", editor: "编辑", test: "测试" }[region]}
          </button>
        ))}
      </nav>

      {message ? <div className={styles.workspaceMessage} role="status">{message}</div> : null}
      {data.flowsProblem ? <div className={styles.workspaceError} role="alert">{data.flowsProblem.detail}</div> : null}
      {data.workflowRuntimesProblem && difyManaged ? <div className={styles.workspaceError} role="alert">{data.workflowRuntimesProblem.detail}</div> : null}

      <div className={styles.editorGrid}>
        <aside className={`${styles.flowRail} ${mobileRegion !== "flows" ? styles.mobileHidden : ""}`}>
          <label className={styles.searchField}>
            <span>流程 Prompt</span>
            <input
              aria-label="搜索 Prompt"
              onChange={(event) => setSearch(event.target.value)}
              placeholder="按名称查找"
              type="search"
              value={search}
            />
          </label>
          <div className={styles.flowGroups}>
            {GROUPS.map((group) => (
              <section key={group.id}>
                <h3>{group.label}</h3>
                <div className={styles.flowList}>
                  {data.flows.items.filter((item) => (
                    item.group === group.id && matchesFlow(item, search)
                  )).map((item) => (
                    item.program ? (
                      <a
                        aria-current={item.flow_key === flow?.flow_key ? "page" : undefined}
                        className={item.flow_key === flow?.flow_key ? styles.flowActive : undefined}
                        href={flowHref(projectId, item.flow_key)}
                        key={item.flow_key}
                      >
                        <strong>{item.display_name}</strong>
                        <span>{flowStatus(
                          item,
                          workflowRuntimesByPurpose.get(item.purpose),
                          data.workflowRuntimes.runtime_backend
                        )}</span>
                      </a>
                    ) : (
                      <div className={styles.flowUnavailable} key={item.flow_key}>
                        <strong>{item.display_name}</strong>
                        <span>{flowStatus(
                          item,
                          workflowRuntimesByPurpose.get(item.purpose),
                          data.workflowRuntimes.runtime_backend
                        )}</span>
                      </div>
                    )
                  ))}
                </div>
              </section>
            ))}
          </div>
        </aside>

        <main className={`${styles.promptCanvas} ${mobileRegion !== "editor" ? styles.mobileHidden : ""}`}>
          {flow && draft ? (
            <>
              <div className={styles.promptTitleRow}>
                <div className={styles.promptNameField}>
                  <label htmlFor="prompt-display-name">Prompt 名称</label>
                  <input
                    disabled={!canEdit}
                    id="prompt-display-name"
                    onChange={(event) => setDisplayName(event.target.value)}
                    value={displayName}
                  />
                </div>
                <div className={styles.versionSummary}>
                  <span>当前 v{flow.current_release_version || "-"}</span>
                  <span>草稿 r{draft.revision}</span>
                </div>
              </div>
              <p className={styles.flowDescription}>{flow.description}</p>
              <div className={styles.editorTabs} role="tablist" aria-label="Prompt 编辑视图">
                <button aria-selected={editorTab === "edit"} onClick={() => setEditorTab("edit")} role="tab" type="button">编辑</button>
                <button aria-selected={editorTab === "preview"} onClick={() => void openPreview()} role="tab" type="button">拼接预览</button>
                <button aria-selected={editorTab === "history"} onClick={() => setEditorTab("history")} role="tab" type="button">版本历史</button>
                {difyManaged ? <button aria-selected={editorTab === "workflow"} onClick={() => setEditorTab("workflow")} role="tab" type="button">Dify 工作流</button> : null}
              </div>

              {editorTab === "edit" ? (
                <div className={styles.promptEditors}>
                  <label>
                    <span><strong>System Prompt</strong><small>{systemTemplate.length.toLocaleString()} 字符</small></span>
                    <textarea
                      disabled={!canEdit}
                      onChange={(event) => setSystemTemplate(event.target.value)}
                      onFocus={() => setActiveEditor("system")}
                      ref={systemRef}
                      spellCheck={false}
                      value={systemTemplate}
                    />
                  </label>
                  <label>
                    <span><strong>User Prompt</strong><small>{userTemplate.length.toLocaleString()} 字符</small></span>
                    <textarea
                      disabled={!canEdit}
                      onChange={(event) => setUserTemplate(event.target.value)}
                      onFocus={() => setActiveEditor("user")}
                      ref={userRef}
                      spellCheck={false}
                      value={userTemplate}
                    />
                  </label>
                </div>
              ) : null}
              {editorTab === "preview" ? <PreviewPanel preview={preview} /> : null}
              {editorTab === "history" ? (
                <HistoryPanel
                  projectId={projectId}
                  releases={data.releases.items}
                  selected={data.selectedReleaseDetail}
                  flowKey={flow.flow_key}
                  onRestore={restoreRelease}
                />
              ) : null}
              {editorTab === "workflow" && difyManaged ? (
                <DifyWorkflowCanvas
                  draft={draft}
                  flow={flow}
                  release={data.selectedReleaseDetail}
                  runtime={workflowRuntime}
                  runtimeBackend={data.workflowRuntimes.runtime_backend}
                />
              ) : null}
            </>
          ) : (
            <div className={styles.promptEmpty}>
              <strong>{data.programs.total === 0 ? "尚未初始化 Prompt" : "选择一个可编辑的 Prompt"}</strong>
              {data.programs.total === 0 && canPublish ? (
                <button className="button" disabled={isPending} onClick={initializeWorkspace} type="button">
                  {isPending ? "初始化中" : "初始化默认 Prompt"}
                </button>
              ) : null}
            </div>
          )}
        </main>

        <aside className={`${styles.testRail} ${mobileRegion !== "test" ? styles.mobileHidden : ""}`}>
          {difyManaged ? (
            <DifyRuntimeRail
              flow={flow}
              runtime={workflowRuntime}
              runtimeBackend={data.workflowRuntimes.runtime_backend}
            />
          ) : null}
          <section className={styles.contextPanel}>
            <header><h3>上下文槽位</h3><span>插入到 {activeEditor === "system" ? "System" : "User"}</span></header>
            <div className={styles.slotList}>
              {flow?.context_slots.map((slot) => (
                <button disabled={!draft || !canEdit} key={slot.key} onClick={() => insertSlot(slot.insertion)} title={slot.description} type="button">
                  <strong>{slot.label}</strong>
                  <code>{`{{${slot.key}}}`}</code>
                </button>
              ))}
              {flow?.context_slots.some((slot) => slot.key === "request_json") ? (
                <button
                  disabled={!draft || !canEdit || requestBlockPresent}
                  onClick={() => insertSlot(REQUEST_JSON_BLOCK)}
                  title={requestBlockPresent ? "当前编辑器已包含完整请求块" : "插入带明确数据边界的完整请求块"}
                  type="button"
                >
                  <strong>完整请求块</strong>
                  <code>{"<request_json>..."}</code>
                </button>
              ) : null}
            </div>
          </section>
          <section className={styles.testPanel}>
            <header><h3>测试</h3><button disabled={!flow?.program} onClick={() => flow?.program && void refreshTests(flow.program.id)} type="button">刷新</button></header>
            <label>
              <span>模型</span>
              <select disabled={!data.testRuntimes.length || isPending} onChange={(event) => setRuntimeId(event.target.value)} value={runtimeId}>
                {!data.testRuntimes.length ? <option value="">暂无可用模型</option> : null}
                {data.testRuntimes.map((runtime) => (
                  <option key={runtime.runtime_selection_id} value={runtime.runtime_selection_id}>
                    {runtime.provider} / {runtime.configured_model}
                  </option>
                ))}
              </select>
            </label>
            <button className="button secondary" disabled={!flow?.program || !draft || !runtimeId || running || isPending} onClick={runSuite} type="button">
              {running ? "测试运行中" : "运行固定测试集"}
            </button>
            <TestRunList items={testRuns} />
          </section>
          <details className={styles.technicalInfo}>
            <summary>技术信息</summary>
            <dl>
              <div><dt>用途</dt><dd>{flow?.purpose || "-"}</dd></div>
              <div><dt>草稿 Hash</dt><dd>{draft?.draft_hash || "-"}</dd></div>
              <div><dt>Program ID</dt><dd>{flow?.program?.id || "-"}</dd></div>
            </dl>
          </details>
        </aside>
      </div>
    </div>
  );
}
