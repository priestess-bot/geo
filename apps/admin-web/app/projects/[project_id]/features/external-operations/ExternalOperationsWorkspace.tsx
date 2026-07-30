import { ActionForm } from "../../geo/features/geo/ActionForm";
import { externalOperation } from "./externalOperationsActions";
import type { ExternalOperationsData, LoadProblem } from "./externalOperationsTypes";
import styles from "./ExternalOperations.module.css";

export function ExternalOperationsWorkspace({
  data, projectId
}: { data: ExternalOperationsData; projectId: string }) {
  return <div className={styles.workspace}>
    <header className={styles.header}>
      <div><p className="eyebrow">真实外部数据</p><h2>外部数据与归因</h2></div>
      <div className={styles.summary}>
        <span><strong>{data.connectors.connections.length}</strong> 个连接</span>
        <span><strong>{data.browser.sessions.length}</strong> 次界面采集</span>
        <span><strong>{data.operationalAlertInputs.length}</strong> 个运行信号</span>
        <span><strong>{data.reports.filter((item) => item.status === "approved").length}</strong> 份已批准报告</span>
      </div>
    </header>
    <p className={styles.intro}>管理 GSC、GA4、官方报告、澳洲消费者界面采集和本地业务归因。Provider API 与消费者 UI 始终保持不同来源身份。</p>
    {Object.entries(data.problems).map(([key, item]) => item
      ? <Problem key={key} label={problemLabel(key)} problem={item} /> : null)}
    <OperationalAlertsSection data={data} />
    <ConnectorSection data={data} projectId={projectId} />
    <BrowserSection data={data} projectId={projectId} />
    <AttributionSection data={data} projectId={projectId} />
    <ReportSection data={data} projectId={projectId} />
  </div>;
}

function OperationalAlertsSection({ data }: { data: ExternalOperationsData }) {
  return <section className={styles.section}>
    <div className={styles.sectionTitle}><div><p className="eyebrow">告警输入</p><h3>外部运行异常</h3></div><strong>{data.operationalAlertInputs.length} 条</strong></div>
    <Rows empty="当前没有 Connector freshness/error 或消费者界面漂移信号。" items={data.operationalAlertInputs.slice(0, 50).map((item) => <div className={styles.row} key={item.id}>
      <span><strong>{signalLabel(item.signal_kind)}</strong><small>{item.reason_code} · {formatTime(item.observed_at)} · {item.input_hash.slice(0, 8)}</small></span>
      <Status value={item.severity} />
      <a href={item.action_path}>处理</a>
    </div>)} />
  </section>;
}

function ConnectorSection({ data, projectId }: { data: ExternalOperationsData; projectId: string }) {
  const approved = data.connectors.definitions.filter((item) => item.status === "approved");
  return <section className={styles.section}>
    <div className={styles.sectionTitle}><div><p className="eyebrow">GSC / GA4</p><h3>连接器</h3></div><strong>{data.connectors.runs.length} 次同步</strong></div>
    <div className={styles.columns}>
      <div><h4>定义与连接</h4>
        <ActionForm action={externalOperation} submitLabel="安装定义"><Hidden projectId={projectId} command="install_definition" />
          <label>数据源<select name="kind" defaultValue="google_search_console"><option value="google_search_console">Google Search Console</option><option value="google_analytics_4">Google Analytics 4</option></select></label>
        </ActionForm>
        <Rows empty="尚未安装连接器定义。" items={data.connectors.definitions.map((item) => <div className={styles.row} key={item.id}><span><strong>{connectorLabel(item.kind)}</strong><small>{item.adapter_release}</small></span><Status value={item.status} />{item.status === "draft" ? <ActionForm action={externalOperation} submitLabel="批准"><Hidden projectId={projectId} command="approve_definition" /><input name="definition_id" type="hidden" value={item.id} /></ActionForm> : null}</div>)} />
        <ActionForm action={externalOperation} submitLabel="创建连接" disabled={!approved.length}><Hidden projectId={projectId} command="create_connection" />
          <label>已批准定义<select name="definition_id" required>{approved.map((item) => <option key={item.id} value={item.id}>{connectorLabel(item.kind)}</option>)}</select></label>
          <label>连接名称<input name="name" required /></label><label>密钥引用 ID<input name="secret_reference_id" required /></label><label>密钥用途<input name="secret_purpose" defaultValue="connector.google" required /></label><label>密钥版本<input name="secret_version" type="number" min="1" defaultValue="1" required /></label>
        </ActionForm>
        <Rows empty="尚未创建数据连接。" items={data.connectors.connections.map((item) => <div className={styles.row} key={item.id}>
          <span><strong>{item.name}</strong><small>{item.secret_purpose} · 密钥 v{item.secret_version}</small></span><Status value={item.status} />
          {item.status !== "revoked" ? <ActionForm action={externalOperation} submitLabel={item.status === "active" ? "停用" : "启用"}><Hidden projectId={projectId} command="set_connection_status" /><input name="connection_id" type="hidden" value={item.id} /><input name="expected_version" type="hidden" value={item.version} /><input name="status" type="hidden" value={item.status === "active" ? "disabled" : "active"} /></ActionForm> : null}
          {item.status !== "revoked" ? <ActionForm action={externalOperation} submitLabel="切换密钥"><Hidden projectId={projectId} command="rotate_connection_secret" /><input name="connection_id" type="hidden" value={item.id} /><input name="expected_version" type="hidden" value={item.version} /><label>已激活密钥版本<input name="secret_version" type="number" min="1" defaultValue={item.secret_version} required /></label></ActionForm> : null}
          {item.status === "active" ? <ActionForm action={externalOperation} submitLabel="测试连接"><Hidden projectId={projectId} command="test_connection" /><input name="connection_id" type="hidden" value={item.id} /><input name="expected_version" type="hidden" value={item.version} /></ActionForm> : null}
        </div>)} />
        <Rows empty="尚无连接测试。" items={data.connectors.connection_tests.slice(0, 20).map((item) => <div className={styles.row} key={item.id}><span><strong>连接测试 · Secret v{item.secret_version}</strong><small>{formatTime(item.requested_at)}{item.error_class ? ` · ${item.error_class}` : ""}</small></span><Status value={item.status} /></div>)} />
      </div>
      <div><h4>采集范围与执行</h4>
        <ActionForm action={externalOperation} submitLabel="创建采集范围" disabled={!data.connectors.connections.length}><Hidden projectId={projectId} command="create_scope" />
          <label>连接<select name="connection_id" required>{data.connectors.connections.filter((item) => item.status === "active").map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          <label>资源标识<input name="source_locator" placeholder="sc-domain:example.com 或 GA4 property ID" required /></label><label>数据流（每行一项）<textarea name="streams" defaultValue="search_analytics_by_date&#10;search_analytics_by_page" required /></label><label>报告配置 JSON<textarea name="report_spec" defaultValue="{}" /></label><label>日期策略 JSON<textarea name="date_policy" defaultValue="{}" /></label>
        </ActionForm>
        {data.connectors.scopes.map((scope) => <div className={styles.row} key={scope.id}><span><strong>{scope.source_locator}</strong><small>{scope.streams.join("、")}</small></span><Status value={scope.status} /><ActionForm action={externalOperation} submitLabel="开始同步"><Hidden projectId={projectId} command="start_sync" /><input name="scope_id" type="hidden" value={scope.id} /><label>模式<select name="mode" defaultValue="initial"><option value="initial">首次</option><option value="incremental">增量</option><option value="backfill">回刷</option></select></label><label>开始时间（含时区）<input name="window_start" placeholder="2026-07-01T00:00:00+10:00" /></label><label>结束时间（含时区）<input name="window_end" placeholder="2026-07-28T23:59:59+10:00" /></label></ActionForm></div>)}
        <Rows empty="尚无同步记录。" items={data.connectors.runs.map((run) => <div className={styles.row} key={run.id}><span><strong>{syncLabel(run.mode)}</strong><small>{formatTime(run.requested_at)}{run.projected_row_count !== undefined ? ` · ${run.projected_row_count} 行` : ""}{run.checkpoint_id ? ` · 检查点 ${shortId(run.checkpoint_id)}` : ""}{run.freshness_status ? ` · ${freshnessLabel(run.freshness_status)}` : ""}{run.freshness_reason ? `：${run.freshness_reason}` : ""}{run.cancel_requested_at ? " · 正在安全取消" : ""}{run.error_class ? ` · ${run.error_class}` : ""}</small></span><Status value={run.cancel_requested_at && run.status === "running" ? "cancel_requested" : run.status} />{["planned", "queued", "running"].includes(run.status) && !run.cancel_requested_at ? <ActionForm action={externalOperation} submitLabel="取消"><Hidden projectId={projectId} command="cancel_sync" /><input name="run_id" type="hidden" value={run.id} /><input name="expected_version" type="hidden" value={run.version} /></ActionForm> : null}</div>)} />
      </div>
    </div>
  </section>;
}

function BrowserSection({ data, projectId }: { data: ExternalOperationsData; projectId: string }) {
  const releases = data.browser.surface_releases.filter((item) => item.status === "approved" && item.authorization_status === "approved");
  const endpoints = data.browser.egress_endpoints.filter((item) => item.status === "approved");
  const profiles = data.browser.profiles.filter((item) => item.status === "approved");
  const policies = data.browserAdmissionPolicies.filter((item) => item.status === "approved" && item.effective_authorization_state === "approved" && item.capture_method === "automated_ui");
  const configurationReady = Boolean(releases.length && endpoints.length && profiles.length);
  const inputReady = Boolean(configurationReady && policies.length);
  return <section className={styles.section}>
    <div className={styles.sectionTitle}><div><p className="eyebrow">澳洲真实界面</p><h3>消费者界面采集</h3></div><strong>{data.browser.surface_releases.length} 个 Surface Release</strong></div>
    <div className={styles.columns}>
      <div><h4>界面版本</h4>
        <ActionForm action={externalOperation} submitLabel="创建界面版本"><Hidden projectId={projectId} command="create_surface" />
          <label>平台<select name="platform"><option value="google">Google</option><option value="microsoft">Microsoft Bing</option></select></label>
          <label>界面<select name="surface"><option value="google_ai_overviews">Google AI Overviews</option><option value="google_ai_mode">Google AI Mode</option><option value="bing_copilot">Bing Copilot</option></select></label>
          <label>版本<input name="release_version" placeholder="2026-07-au-v1" required /></label>
          <label>入口 URL<input name="entry_url_template" placeholder="https://www.google.com/" required /></label>
          <label>允许域名（每行一项）<textarea name="allowed_hosts" placeholder="www.google.com" required /></label>
          <label>已实测选择器 JSON<textarea name="selectors" placeholder={SURFACE_SELECTORS_PLACEHOLDER} required /></label>
          <label>已实测阻断检测器 JSON<textarea name="block_detectors" placeholder={BLOCK_DETECTORS_PLACEHOLDER} required /></label>
          <label>解析器版本<input name="parser_release" placeholder="google-aio-parser-v1" required /></label>
          <label>浏览器版本<input name="browser_release" defaultValue="playwright:1.60.0/chromium" required /></label>
          <label>授权轨道<select name="authorization_track" defaultValue="B"><option value="B">B：只允许人工对照</option><option value="A">A：允许自动采集</option></select></label>
          <label>授权状态<select name="authorization_status" defaultValue="not_assessed"><option value="not_assessed">未评估</option><option value="approved">已批准</option><option value="restricted">受限</option><option value="prohibited">禁止</option></select></label>
          <label>授权依据<input name="authorization_reference" placeholder="法律/条款评估记录" /></label>
          <label>授权有效期（含时区）<input name="authorization_valid_until" placeholder="2026-10-31T23:59:59+11:00" /></label>
          <label>条款版本<input name="terms_version" required /></label>
        </ActionForm>
        <Rows empty="尚未配置 Google AI Overviews、AI Mode 或 Bing Copilot。" items={data.browser.surface_releases.map((item) => <div className={styles.row} key={item.id}><span><strong>{surfaceLabel(item.surface)}</strong><small>{item.release_version} · 授权 {item.authorization_status}{item.suspension_reason ? ` · ${item.suspension_reason}` : ""}</small></span><Status value={item.status} />{item.status === "draft" && item.authorization_status === "approved" ? <ActionForm action={externalOperation} submitLabel="批准版本"><Hidden projectId={projectId} command="approve_surface" /><input name="release_id" type="hidden" value={item.id} /></ActionForm> : null}{["approved", "suspended"].includes(item.status) ? <ActionForm action={externalOperation} submitLabel="停用版本"><Hidden projectId={projectId} command="retire_surface" /><input name="release_id" type="hidden" value={item.id} /></ActionForm> : null}</div>)} />
        <Rows empty="尚无 Surface 漂移事件。" items={data.browser.drift_events.slice(0, 10).map((item) => <div className={styles.row} key={item.id}><span><strong>{item.drift_kind === "browser_build" ? "浏览器构建漂移" : "选择器/解析漂移"}</strong><small>{item.expected_value} → {item.observed_value} · {formatTime(item.detected_at)}</small></span><Status value={item.release_suspended ? "suspended" : "detected"} /></div>)} />
      </div>
      <div><h4>澳洲代理出口</h4>
        <ActionForm action={externalOperation} submitLabel="创建出口"><Hidden projectId={projectId} command="create_egress" /><label>名称<input name="name" required /></label><label>协议<select name="protocol"><option value="https">HTTPS</option><option value="http">HTTP CONNECT</option><option value="socks5">SOCKS5</option></select></label><label>代理主机<input name="endpoint_host" required /></label><label>端口<input name="endpoint_port" type="number" min="1" max="65535" required /></label><label>密钥引用 ID<input name="secret_reference_id" required /></label><label>密钥用途<input name="secret_purpose" defaultValue="browser_egress.au" required /></label><label>密钥版本<input name="secret_version" type="number" min="1" defaultValue="1" /></label><label>网络类型<select name="network_type"><option value="residential">住宅</option><option value="mobile">移动网络</option></select></label><label>粘性方式<select name="sticky_mode"><option value="credential_session">凭据会话</option><option value="provider_lease">供应商租约</option><option value="trusted_connection_log">可信连接日志</option></select></label><label>州/地区<input name="expected_region" placeholder="New South Wales" /></label><label>出口策略版本<input name="egress_policy_version" defaultValue="au-consumer-v1" /></label><label>稳定分层键<input name="egress_cohort_key" defaultValue="au-residential" /></label></ActionForm>
        <Rows empty="尚未配置澳洲出口。" items={data.browser.egress_endpoints.map((item) => <div className={styles.row} key={item.id}><span><strong>{item.name}</strong><small>{item.endpoint_host}:{item.endpoint_port} · {item.network_type} · {item.sticky_mode}</small></span><Status value={item.status} />{item.status === "draft" ? <ActionForm action={externalOperation} submitLabel="批准出口"><Hidden projectId={projectId} command="approve_egress" /><input name="endpoint_id" type="hidden" value={item.id} /></ActionForm> : null}{item.status === "approved" ? <ActionForm action={externalOperation} submitLabel="测试出口"><Hidden projectId={projectId} command="test_egress" /><input name="endpoint_id" type="hidden" value={item.id} /></ActionForm> : null}{["approved", "disabled"].includes(item.status) ? <ActionForm action={externalOperation} submitLabel={item.status === "approved" ? "停用出口" : "重新启用"}><Hidden projectId={projectId} command="set_egress_status" /><input name="endpoint_id" type="hidden" value={item.id} /><input name="status" type="hidden" value={item.status === "approved" ? "disabled" : "approved"} /></ActionForm> : null}</div>)} />
        <Rows empty="尚无出口测试记录。" items={data.browser.egress_tests.slice(0, 10).map((item) => <div className={styles.row} key={item.id}><span><strong>{item.outcome ? egressOutcomeLabel(item.outcome) : "出口测试"}</strong><small>{formatTime(item.finished_at || item.requested_at)}{item.verification_hash ? ` · ${item.verification_hash.slice(0, 8)}` : ""}{item.error_class ? ` · ${item.error_class}` : ""}</small></span><Status value={item.status} /></div>)} />
      </div>
      <div><h4>浏览器画像</h4><ActionForm action={externalOperation} submitLabel="创建画像"><Hidden projectId={projectId} command="create_profile" /><label>版本<input name="version" defaultValue="au-desktop-v1" required /></label><label>浏览器版本<input name="browser_release" defaultValue="playwright:1.60.0/chromium" required /></label><label>设备<select name="device_class"><option value="desktop">桌面</option><option value="mobile">移动</option></select></label><label>视口 JSON<textarea name="viewport" defaultValue={'{"width":1440,"height":1000}'} /></label></ActionForm><Rows empty="尚未配置浏览器画像。" items={data.browser.profiles.map((item) => <div className={styles.row} key={item.id}><span><strong>{item.version}</strong><small>{item.device_class} · {item.locale} · {item.account_cohort}</small></span><Status value={item.status} />{item.status === "draft" ? <ActionForm action={externalOperation} submitLabel="批准画像"><Hidden projectId={projectId} command="approve_profile" /><input name="profile_id" type="hidden" value={item.id} /></ActionForm> : null}</div>)} /></div>
    </div>
    <div><h4>接入 Sampling Core</h4><p className={styles.empty}>这里只冻结消费者界面运行输入。问题、重复次数、Run 和统计仍在“观测与统计”中统一管理，消费者 UI 不会与 Provider API 混分母。</p>
      <ActionForm action={externalOperation} submitLabel="1. 注册运行选项" disabled={!configurationReady}><Hidden projectId={projectId} command="register_browser_runtime_option" />
        <label>Surface Release<select name="surface_release_id" required>{releases.map((item) => <option key={item.id} value={item.id}>{surfaceLabel(item.surface)} · {item.release_version}</option>)}</select></label>
        <label>澳洲出口<select name="egress_endpoint_id" required>{endpoints.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.network_type}</option>)}</select></label>
        <label>浏览器画像<select name="profile_version_id" required>{profiles.map((item) => <option key={item.id} value={item.id}>{item.version} · {item.device_class}</option>)}</select></label>
      </ActionForm>
      <p className={styles.empty}>运行选项注册后，到“观测与统计 → 准入”创建并批准 automated_ui 策略，再回来完成第 2 步。</p>
      <ActionForm action={externalOperation} submitLabel="2. 注册采样输入" disabled={!inputReady}><Hidden projectId={projectId} command="register_browser_sampling_input" />
        <label>Surface Release<select name="surface_release_id" required>{releases.map((item) => <option key={item.id} value={item.id}>{surfaceLabel(item.surface)} · {item.release_version}</option>)}</select></label>
        <label>澳洲出口<select name="egress_endpoint_id" required>{endpoints.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.network_type}</option>)}</select></label>
        <label>浏览器画像<select name="profile_version_id" required>{profiles.map((item) => <option key={item.id} value={item.id}>{item.version} · {item.device_class}</option>)}</select></label>
        <label>自动 UI 准入策略<select name="admission_policy_id" required>{policies.map((item) => <option key={item.id} value={item.id}>{item.platform} · 有效至 {formatTime(item.valid_until)}</option>)}</select></label>
        <label>冻结 QuestionSet ID<input name="question_set_id" placeholder="从知识库问题集选择已冻结版本" required /></label>
        <label>选项键<input name="option_key" placeholder="google-aio-au-desktop-v1" required /></label>
        <label>显示名称<input name="display_name" placeholder="Google AIO · 澳洲桌面匿名" required /></label>
      </ActionForm>
      {!configurationReady ? <p className={styles.empty}>需先具备已批准且授权有效的 Surface、澳洲出口和浏览器画像。</p> : null}
      {configurationReady && !policies.length ? <p className={styles.empty}>尚无已批准且授权有效的 automated_ui 准入策略。</p> : null}
    </div>
    <div><h4>运行消费者界面任务</h4>
      <p className={styles.empty}>任务来自“观测与统计”中已冻结的 automated_ui 采样运行；Surface、澳洲出口和画像由套件锁定，无需再次选择。</p>
      <Rows empty="尚无消费者界面采样任务。请先在“观测与统计”创建套件并启动运行。" items={data.browser.tasks.slice(0, 100).map((item) => <div className={styles.row} key={item.id}>
        <span><strong>问题 {shortId(item.question_id)} · 第 {item.repetition} 次</strong><small>任务 {shortId(item.id)} · Run {shortId(item.run_id)}</small></span>
        <Status value={item.attempt_status || item.status} />
        {item.status === "planned" && ["planned", "running"].includes(item.run_status) ? <ActionForm action={externalOperation} submitLabel="开始采集"><Hidden projectId={projectId} command="enqueue_browser_capture" /><input name="run_id" type="hidden" value={item.run_id} /><input name="task_id" type="hidden" value={item.id} /><input name="expected_task_version" type="hidden" value={item.version} /><input name="surface_release_id" type="hidden" value={item.surface_release_id} /><input name="egress_endpoint_id" type="hidden" value={item.egress_endpoint_id} /><input name="profile_version_id" type="hidden" value={item.profile_version_id} /></ActionForm> : null}
      </div>)} />
    </div>
    <details><summary>最近采集会话（{data.browser.sessions.length}）</summary><pre className={styles.code}>{JSON.stringify(data.browser.sessions.slice(0, 20), null, 2)}</pre></details>
  </section>;
}

function AttributionSection({ data, projectId }: { data: ExternalOperationsData; projectId: string }) {
  return <section className={styles.section}><div className={styles.sectionTitle}><div><p className="eyebrow">Session → Revenue</p><h3>本地业务归因</h3></div><strong>{data.attribution.counts.revenues || 0} 条收入</strong></div><div className={styles.metrics}>{Object.entries(data.attribution.counts).map(([key, value]) => <div key={key}><span>{countLabel(key)}</span><strong>{value}</strong></div>)}</div><div className={styles.columns}><ActionForm action={externalOperation} submitLabel="启用归因策略"><Hidden projectId={projectId} command="create_policy" /><label>末次点击窗口（天）<input name="last_click_days" type="number" min="1" defaultValue="30" /></label><label>助攻窗口（天）<input name="assisted_days" type="number" min="1" defaultValue="90" /></label></ActionForm><ActionForm action={externalOperation} submitLabel="创建一方采集端"><Hidden projectId={projectId} command="create_collector" /><label>名称<input name="name" required /></label><label>允许来源（每行一项 HTTPS Origin）<textarea name="allowed_origins" placeholder="https://www.example.com" required /></label></ActionForm><ActionForm action={externalOperation} submitLabel="生成归因快照" disabled={!data.attribution.policies.length}><Hidden projectId={projectId} command="create_snapshot" /><label>策略<select name="policy_id">{data.attribution.policies.map((item) => <option key={item.id} value={item.id}>v{item.version} · {item.last_click_days}/{item.assisted_days} 天</option>)}</select></label><label>截止时间（含时区）<input name="cutoff_at" placeholder="2026-07-28T23:59:59+10:00" required /></label></ActionForm></div></section>;
}

function ReportSection({ data, projectId }: { data: ExternalOperationsData; projectId: string }) {
  const projections = data.connectors.runs.filter((item) => item.projection_batch_id);
  return <section className={styles.section}><div className={styles.sectionTitle}><div><p className="eyebrow">Customer 可见性</p><h3>外部数据报告审核</h3></div><strong>{data.reports.length} 份报告</strong></div>
    <div className={styles.columns}>
      <ActionForm action={externalOperation} submitLabel="创建 Connector 报告草稿" disabled={!projections.length}><Hidden projectId={projectId} command="create_connector_report" /><label>活动 ID<input name="campaign_id" required /></label><label>成功同步<select name="projection_batch_id" required>{projections.map((item) => <option key={item.id} value={item.projection_batch_id}>{syncLabel(item.mode)} · {item.projected_row_count ?? 0} 行 · {formatTime(item.finished_at)}</option>)}</select></label><label>标题<input name="title" required /></label><label>摘要<textarea name="summary" /></label></ActionForm>
      <ActionForm action={externalOperation} submitLabel="创建官方报告草稿"><Hidden projectId={projectId} command="create_official_report" /><label>活动 ID<input name="campaign_id" required /></label><label>官方报告导入 ID<input name="import_id" required /></label><label>Customer 字段（每行一项）<textarea name="customer_fields" required /></label><label>标题<input name="title" required /></label><label>摘要<textarea name="summary" /></label></ActionForm>
      <ActionForm action={externalOperation} submitLabel="创建归因报告草稿" disabled={!data.attribution.snapshots.length}><Hidden projectId={projectId} command="create_attribution_report" /><label>活动 ID<input name="campaign_id" required /></label><label>归因快照<select name="attribution_snapshot_id" required>{data.attribution.snapshots.map((item) => <option key={item.id} value={item.id}>{formatTime(item.cutoff_at)} · {item.result_hash.slice(0, 8)}</option>)}</select></label><label>标题<input name="title" defaultValue="GEO 内容业务归因" required /></label><label>摘要<textarea name="summary" /></label></ActionForm>
    </div>
    <Rows empty="同步或官方报告导入后，在这里创建并审核 Customer 投影。" items={data.reports.map((item) => <div className={styles.row} key={item.id}><span><strong>{item.title}</strong><small>{item.source_kind || "来源待投影"} · {item.row_count ?? 0} 行 · {formatTime(item.created_at)}</small></span><Status value={item.status} />{item.status === "draft" ? <ActionForm action={externalOperation} submitLabel="提交审核"><Hidden projectId={projectId} command="submit_report" /><input name="report_id" type="hidden" value={item.id} /></ActionForm> : null}{item.status === "in_review" ? <ActionForm action={externalOperation} submitLabel="记录审核"><Hidden projectId={projectId} command="decide_report" /><input name="report_id" type="hidden" value={item.id} /><input name="snapshot_hash" type="hidden" value={item.snapshot_hash} /><label>决定<select name="decision"><option value="approved">批准</option><option value="rejected">拒绝</option></select></label><label>理由<textarea name="reason" required /></label></ActionForm> : null}</div>)} />
  </section>;
}

function Hidden({ projectId, command }: { projectId: string; command: string }) { return <><input name="project_id" type="hidden" value={projectId} /><input name="command" type="hidden" value={command} /></>; }
function Rows({ empty, items }: { empty: string; items: React.ReactNode[] }) { return items.length ? <div className={styles.rows}>{items}</div> : <p className={styles.empty}>{empty}</p>; }
function Status({ value }: { value: string }) { return <span className={styles.status}>{statusLabel(value)}</span>; }
function Problem({ label, problem }: { label: string; problem: LoadProblem }) { return <div className={styles.problem} role="alert"><strong>{label}加载失败</strong><span>{problem.detail}</span>{problem.correlationId ? <code>{problem.correlationId}</code> : null}</div>; }
function formatTime(value?: string) { return value ? new Date(value).toLocaleString("zh-CN") : "-"; }
function shortId(value: string) { return value.length > 13 ? `${value.slice(0, 8)}...${value.slice(-4)}` : value; }
function connectorLabel(value: string) { return ({ google_search_console: "Google Search Console", google_analytics_4: "Google Analytics 4" } as Record<string, string>)[value] || value; }
function surfaceLabel(value: string) { return ({ google_ai_overviews: "Google AI Overviews", google_ai_mode: "Google AI Mode", bing_copilot: "Bing Copilot" } as Record<string, string>)[value] || value; }
function statusLabel(value: string) { return ({ draft: "草稿", approved: "已批准", active: "运行中", disabled: "已停用", suspended: "已暂停", detected: "已检测", queued: "排队中", running: "执行中", cancel_requested: "正在取消", succeeded: "成功", failed: "失败", cancelled: "已取消", in_review: "审核中", rejected: "已拒绝", stale: "已过期", revoked: "已撤销", info: "提示", warning: "警告", critical: "严重" } as Record<string, string>)[value] || value; }
function syncLabel(value: string) { return ({ initial: "首次同步", incremental: "增量同步", backfill: "历史回刷" } as Record<string, string>)[value] || value; }
function freshnessLabel(value: string) { return ({ fresh: "数据新鲜", stale: "数据已过期", unknown: "新鲜度未知" } as Record<string, string>)[value] || value; }
function egressOutcomeLabel(value: string) { return ({ au_consumer_representative: "澳洲消费者出口已验证", au_geo_verified: "仅验证为澳洲地域", geo_mismatch: "地域不匹配", geo_unverified: "地域无法验证", egress_changed: "粘性会话出口发生变化" } as Record<string, string>)[value] || value; }
function countLabel(value: string) { return ({ traces: "追踪链接", sessions: "会话", touches: "触点", leads: "线索", conversions: "转化", deals: "交易", revenues: "收入" } as Record<string, string>)[value] || value; }
function signalLabel(value: string) { return ({ connector_auth: "连接授权异常", connector_schema: "连接器 Schema 漂移", connector_quota: "连接器配额耗尽", connector_rate: "连接器触发限流", connector_failure: "连接器执行失败", connector_freshness: "连接器数据过期", surface_parser: "消费者界面解析漂移", browser_build: "浏览器构建漂移" } as Record<string, string>)[value] || value; }
function problemLabel(value: string) { return ({ connectors: "连接器", browser: "消费者界面采集", browserPolicies: "消费者界面准入策略", reports: "外部报告", alerts: "外部运行告警", attribution: "归因" } as Record<string, string>)[value] || value; }

const SURFACE_SELECTORS_PLACEHOLDER = JSON.stringify({
  query_input: "<实测 CSS 选择器>",
  page_complete: "<实测 CSS 选择器>",
  surface_marker: "<实测 CSS 选择器>",
  answer: "<实测 CSS 选择器>",
  citations: "<实测 CSS 选择器>",
  page_location: "<实测 CSS 选择器>",
  ready_timeout_ms: 45000
}, null, 2);
const BLOCK_DETECTORS_PLACEHOLDER = JSON.stringify({
  consent: "<实测 CSS 选择器>",
  login: "<实测 CSS 选择器>",
  captcha: "<实测 CSS 选择器>",
  rate_limit: "<实测 CSS 选择器>"
}, null, 2);
