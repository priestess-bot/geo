"use client";

import type { KnowledgeQuestionSetView } from "@geo/types/geo";
import { useActionState } from "react";

import {
  bootstrapBrowserCaptureAction,
  configureBrowserSessionAction,
  configureAustralianEgressAction,
  registerBrowserRuntimeOptionAction,
  registerBrowserSamplingInputAction,
  testAustralianEgressAction
} from "./browserCaptureActions";
import { WorkflowCActionFeedback } from "./WorkflowCActionFeedback";
import type {
  AdmissionPolicy,
  AdmissionRuntimeOption,
  BrowserCaptureInventory,
  BrowserCaptureReadiness,
  BrowserCaptureReadinessItem,
  Resource,
  SamplingSuiteInputOption,
  WorkflowCActionState
} from "./workflowCTypes";
import { initialWorkflowCActionState } from "./workflowCTypes";
import styles from "./ConsumerSurfaceCaptureSetup.module.css";

const SURFACES = [
  "google_ai_overviews",
  "google_ai_mode",
  "bing_copilot"
] as const;

export function ConsumerSurfaceCaptureSetup({
  admissionPolicies,
  admissionRuntimeOptions,
  canOperate,
  inventory,
  projectId,
  questionSets,
  readiness,
  suiteInputOptions
}: {
  admissionPolicies: AdmissionPolicy[];
  admissionRuntimeOptions: AdmissionRuntimeOption[];
  canOperate: boolean;
  inventory: Resource<BrowserCaptureInventory>;
  projectId: string;
  questionSets: KnowledgeQuestionSetView[];
  readiness: Resource<BrowserCaptureReadiness>;
  suiteInputOptions: SamplingSuiteInputOption[];
}) {
  const [bootstrapState, bootstrapAction, bootstrapPending] = useActionState(
    bootstrapBrowserCaptureAction,
    initialWorkflowCActionState
  );
  const [proxyState, proxyAction, proxyPending] = useActionState(
    configureAustralianEgressAction,
    initialWorkflowCActionState
  );
  const [testState, testAction, testPending] = useActionState(
    testAustralianEgressAction,
    initialWorkflowCActionState
  );
  const [sessionState, sessionAction, sessionPending] = useActionState(
    configureBrowserSessionAction,
    initialWorkflowCActionState
  );
  const [optionState, optionAction, optionPending] = useActionState(
    registerBrowserRuntimeOptionAction,
    initialWorkflowCActionState
  );
  const [inputState, inputAction, inputPending] = useActionState(
    registerBrowserSamplingInputAction,
    initialWorkflowCActionState
  );
  const items = readiness.data?.items || [];
  const bySurface = new Map(items.map((item) => [item.surface, item]));
  const missingAdapter = items.length !== 3 || items.some((item) =>
    item.blocking_reasons.includes("needs_adapter")
  );
  const activeEndpointId = items.find((item) => item.egress_endpoint_id)?.egress_endpoint_id;
  const endpoint = inventory.data?.egress_endpoints.find((item) => item.id === activeEndpointId);
  const latestTest = endpoint
    ? inventory.data?.egress_tests.find((item) => item.endpoint_id === endpoint.id)
    : undefined;
  const egressVerified = latestTest?.status === "succeeded" && latestTest.eligible === true;
  const frozenQuestionSets = questionSets.filter((item) => item.status === "frozen");
  const approvedPolicies = admissionPolicies.filter((item) =>
    item.capture_method === "automated_ui"
    && item.status === "approved"
    && item.effective_authorization_state === "approved"
  );
  const activeProfileId = items.find((item) => item.profile_version_id)?.profile_version_id;
  const activeProfile = inventory.data?.profiles.find((item) => item.id === activeProfileId);
  const feedback = [bootstrapState, proxyState, testState, sessionState, optionState, inputState]
    .find((state) => state.kind !== "idle") || initialWorkflowCActionState;

  return (
    <section className={styles.setup} aria-labelledby="consumer-capture-heading">
      <header className={styles.heading}>
        <div>
          <p>消费者 AI 界面</p>
          <h3 id="consumer-capture-heading">澳洲真实搜索采样</h3>
          <span>通过同一粘性代理会话访问、前后验证出口，并保存答案与引用。</span>
        </div>
        <strong>{items.filter((item) => item.state !== "blocked").length}/3 可运行</strong>
      </header>

      {readiness.problem ? <Problem text={readiness.problem.detail} /> : null}
      {inventory.problem ? <Problem text={inventory.problem.detail} /> : null}

      <div className={styles.surfaces}>
        {SURFACES.map((surface) => (
          <SurfaceStatus item={bySurface.get(surface)} key={surface} surface={surface} />
        ))}
      </div>

      {missingAdapter ? (
        <form action={bootstrapAction} className={styles.primaryAction}>
          <CommandFields keyValue={`browser-bootstrap-${projectId}`} projectId={projectId} />
          <div><strong>安装内置采集器</strong><span>同时创建默认匿名桌面浏览器配置。</span></div>
          <button disabled={!canOperate || bootstrapPending} type="submit">
            {bootstrapPending ? "正在安装..." : "启用三个采集器"}
          </button>
        </form>
      ) : null}

      <div className={styles.steps}>
        <section data-complete={Boolean(endpoint)}>
          <header><span>1</span><div><strong>澳洲粘性代理</strong><small>{endpoint ? `${endpoint.endpoint_host}:${endpoint.endpoint_port}` : "尚未配置"}</small></div></header>
          {endpoint ? (
            <div className={styles.inlineStatus}>
              <span>{endpoint.network_type === "residential" ? "住宅网络" : endpoint.network_type}</span>
              <Status value={egressVerified ? "verified" : latestTest?.status || "untested"} />
              {!egressVerified ? (
                <form action={testAction}>
                  <CommandFields keyValue={`browser-egress-test-${endpoint.id}`} projectId={projectId} />
                  <input name="endpoint_id" type="hidden" value={endpoint.id} />
                  <button disabled={!canOperate || testPending} type="submit">
                    {testPending ? "测试中..." : "测试澳洲出口"}
                  </button>
                </form>
              ) : null}
            </div>
          ) : (
            <details className={styles.proxyForm} open>
              <summary>填写代理连接信息</summary>
              <form action={proxyAction}>
                <CommandFields keyValue={`browser-proxy-${projectId}`} projectId={projectId} />
                <label><span>协议</span><select name="protocol"><option value="https">HTTPS</option><option value="http">HTTP</option><option value="socks5">SOCKS5</option></select></label>
                <label><span>代理主机</span><input name="endpoint_host" placeholder="au.proxy.example.com" required /></label>
                <label><span>端口</span><input max="65535" min="1" name="endpoint_port" placeholder="443" required type="number" /></label>
                <label className={styles.wide}><span>粘性用户名模板</span><input name="username_template" placeholder="customer-zone-au-session-{session_id}" required /><small>保留 <code>{"{session_id}"}</code>，每次采集会自动替换为独立会话 ID。</small></label>
                <label><span>代理密码</span><input autoComplete="new-password" name="password" required type="password" /></label>
                <label><span>网络类型</span><select name="network_type"><option value="residential">住宅</option><option value="mobile">移动</option></select></label>
                <label><span>州/地区（可选）</span><input name="expected_region" placeholder="New South Wales" /></label>
                <button disabled={!canOperate || proxyPending} type="submit">{proxyPending ? "正在保存..." : "保存并启用代理"}</button>
              </form>
            </details>
          )}
        </section>

        <section data-complete={Boolean(activeProfile)}>
          <header><span>2</span><div><strong>浏览器身份</strong><small>匿名默认；登录会话仅在界面要求登录时使用</small></div></header>
          <div className={styles.profileStatus}>
            <strong>{activeProfile?.account_cohort === "managed_test_account" ? "受管测试账号" : "干净匿名会话"}</strong>
            <span>{activeProfile?.version || "安装采集器后自动创建"}</span>
          </div>
          <details className={styles.sessionForm}>
            <summary>导入可选登录会话</summary>
            <p>粘贴 Playwright 导出的 <code>storage_state</code> JSON。仅接受 Google、Bing 和 Microsoft 域名，内容加密保存且不会回显。</p>
            <form action={sessionAction}>
              <CommandFields keyValue={`browser-session-${activeProfile?.id || projectId}`} projectId={projectId} />
              <label><span>storage_state JSON</span><textarea name="storage_state_json" placeholder={'{"cookies": [], "origins": []}'} required rows={7} /></label>
              <button disabled={!canOperate || sessionPending} type="submit">{sessionPending ? "正在加密导入..." : "导入并启用"}</button>
            </form>
          </details>
        </section>

        <section className={styles.bindingStep} data-complete={items.length === 3 && items.every((item) => item.state !== "blocked")}>
          <header><span>3</span><div><strong>逐界面绑定问题集与运行策略</strong><small>三个界面分别形成独立采样输入和统计分母</small></div></header>
          {!egressVerified ? <p className={styles.hint}>先通过澳洲出口测试，才能创建真实采样任务。</p> : (
            <SamplingInputSetup
              admissionRuntimeOptions={admissionRuntimeOptions}
              canOperate={canOperate}
              frozenQuestionSets={frozenQuestionSets}
              inputAction={inputAction}
              inputPending={inputPending}
              items={items}
              optionAction={optionAction}
              optionPending={optionPending}
              policies={approvedPolicies}
              projectId={projectId}
              suiteInputOptions={suiteInputOptions}
            />
          )}
        </section>
      </div>
      <WorkflowCActionFeedback state={feedback} />
    </section>
  );
}

function SamplingInputSetup({
  admissionRuntimeOptions,
  canOperate,
  frozenQuestionSets,
  inputAction,
  inputPending,
  items,
  optionAction,
  optionPending,
  policies,
  projectId,
  suiteInputOptions
}: {
  admissionRuntimeOptions: AdmissionRuntimeOption[];
  canOperate: boolean;
  frozenQuestionSets: KnowledgeQuestionSetView[];
  inputAction: (payload: FormData) => void;
  inputPending: boolean;
  items: BrowserCaptureReadinessItem[];
  optionAction: (payload: FormData) => void;
  optionPending: boolean;
  policies: AdmissionPolicy[];
  projectId: string;
  suiteInputOptions: SamplingSuiteInputOption[];
}) {
  const alreadyBound = suiteInputOptions.filter((item) =>
    item.source_stratum.capture_method === "automated_ui"
  );
  return (
    <div className={styles.surfaceBindings}>
      {SURFACES.map((surface) => {
        const item = items.find((candidate) => candidate.surface === surface);
        if (!item?.surface_release_id || !item.egress_endpoint_id || !item.profile_version_id) {
          return <article key={surface}><strong>{surfaceLabel(surface)}</strong><p className={styles.hint}>浏览器运行配置尚未就绪。</p></article>;
        }
        const runtimeKey = `browser:${item.surface_release_id}:${item.profile_version_id}:${item.egress_endpoint_id}`;
        const runtimeOption = admissionRuntimeOptions.find((option) => option.option_key === runtimeKey);
        const matchingPolicies = runtimeOption ? policies.filter((policy) =>
          policy.adapter_release === runtimeOption.adapter_release
          && policy.location_evidence_hash === runtimeOption.location_evidence_hash
          && policy.platform === runtimeOption.platform
        ) : [];
        const bound = alreadyBound.filter((option) => option.source_stratum.surface === surface);
        return (
          <article key={surface}>
            <header><strong>{surfaceLabel(surface)}</strong><small>{bound.length ? `已绑定 ${bound.length} 个输入` : "尚未绑定"}</small></header>
            {!runtimeOption ? (
              <div className={styles.authorizationPrompt}>
                <p>先注册当前采集器、代理和浏览器身份的运行选项。</p>
                <form action={optionAction}>
                  <CommandFields keyValue={`browser-option-${item.surface_release_id}-${item.profile_version_id}`} projectId={projectId} />
                  <RuntimeFields item={item} />
                  <button disabled={!canOperate || optionPending} type="submit">{optionPending ? "正在注册..." : "注册运行选项"}</button>
                </form>
              </div>
            ) : !matchingPolicies.length ? (
              <div className={styles.authorizationPrompt}>
                <p>运行选项已注册，还需要为此界面批准一条匹配的自动采样策略。</p>
                <a href={`/projects/${encodeURIComponent(projectId)}?tab=measurement&workflow_view=admission&runtime_option=${encodeURIComponent(runtimeOption.option_key)}`}>前往准入设置</a>
              </div>
            ) : (
              <form action={inputAction} className={styles.bindingForm}>
                <CommandFields keyValue={`browser-input-${item.surface_release_id}`} projectId={projectId} />
                <RuntimeFields item={item} />
                <input name="surface" type="hidden" value={surface} />
                <label><span>冻结问题集</span><select name="question_set_id" required><option value="">请选择</option>{frozenQuestionSets.map((set) => <option key={set.id} value={set.id}>{set.name} · {set.items.length} 个问题</option>)}</select></label>
                <label><span>自动采样策略</span><select name="admission_policy_id" required><option value="">请选择</option>{matchingPolicies.map((policy) => <option key={policy.id} value={policy.id}>有效至 {formatDate(policy.valid_until)}</option>)}</select></label>
                <button disabled={!canOperate || inputPending || !frozenQuestionSets.length} type="submit">{inputPending ? "正在绑定..." : "绑定采样输入"}</button>
              </form>
            )}
          </article>
        );
      })}
      {!frozenQuestionSets.length ? <small>当前活动下还没有已冻结问题集。</small> : null}
    </div>
  );
}

function SurfaceStatus({ item, surface }: { item?: BrowserCaptureReadinessItem; surface: string }) {
  const state = item?.state || "blocked";
  return <article data-state={state}><div><strong>{surfaceLabel(surface)}</strong><small>{item?.release_version ? `采集器 ${item.release_version}` : "采集器未安装"}</small></div><Status value={state} /><p>{item ? readinessText(item) : "等待加载"}</p></article>;
}

function RuntimeFields({ item }: { item: BrowserCaptureReadinessItem }) {
  return <><input name="surface_release_id" type="hidden" value={item.surface_release_id || ""} /><input name="egress_endpoint_id" type="hidden" value={item.egress_endpoint_id || ""} /><input name="profile_version_id" type="hidden" value={item.profile_version_id || ""} /></>;
}

function CommandFields({ keyValue, projectId }: { keyValue: string; projectId: string }) {
  return <><input name="project_id" type="hidden" value={projectId} /><input name="idempotency_key" type="hidden" value={keyValue} /></>;
}

function Status({ value }: { value: string }) {
  return <span className={styles.status} data-state={value}>{statusLabel(value)}</span>;
}

function Problem({ text }: { text: string }) {
  return <div className={styles.problem} role="alert">{text}</div>;
}

function readinessText(item: BrowserCaptureReadinessItem): string {
  if (item.state === "fidelity_accepted") return `${item.captured_count} 条真实采样，保真度门槛已满足`;
  if (item.state === "live_verified") return `${item.captured_count} 条真实采样，已完成基础验证`;
  if (item.state === "ready") return "配置就绪，等待首批真实采样";
  return item.blocking_reasons.map((reason) => ({
    needs_adapter: "需要安装采集器",
    adapter_drifted: "页面结构变化，采集器已暂停",
    adapter_not_enabled: "采集器尚未启用",
    needs_au_egress: "需要澳洲粘性代理",
    needs_egress_test: "需要通过澳洲出口测试",
    needs_browser_profile: "需要浏览器配置"
  } as Record<string, string>)[reason] || reason).join("；");
}

function statusLabel(value: string): string {
  return ({
    blocked: "未就绪",
    ready: "可运行",
    live_verified: "真实验证",
    fidelity_accepted: "保真验收",
    verified: "澳洲已验证",
    untested: "未测试",
    queued: "排队中",
    running: "测试中",
    succeeded: "已完成",
    failed: "失败"
  } as Record<string, string>)[value] || value;
}

function surfaceLabel(value: string): string {
  return ({ google_ai_overviews: "Google AI Overviews", google_ai_mode: "Google AI Mode", bing_copilot: "Bing Copilot" } as Record<string, string>)[value] || value;
}

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString("zh-CN");
}
