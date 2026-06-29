import data from "../data/dashboard-data.json";

type Status = "done" | "in_progress" | "todo" | "risk" | "blocked";
type Category = "plan" | "code" | "test" | "docs" | "next";
type TabId = "overview" | "plan" | "code" | "test" | "docs" | "next";

type SearchValue = string | string[] | undefined;
type DashboardSearchParams = Promise<Record<string, SearchValue>>;

type EvidenceItem = {
  evidencePaths?: string[];
  commands?: string[];
  result?: string;
};

type Task = EvidenceItem & {
  id: string;
  title: string;
  status: Status;
  statusLabel: string;
  source: string;
  milestone: string;
  category: Category;
  categoryLabel: string;
  summary: string;
};

type AuditEntry = EvidenceItem & {
  id: string;
  date: string;
  title: string;
  month: string;
  category: Category;
  categoryLabel: string;
  status: Status;
  statusLabel: string;
  summary: string;
};

type FilterState = {
  q: string;
  status: string;
  category: string;
  milestone: string;
};

const tabs: Array<{ id: TabId; label: string; anchors: Array<[string, string]> }> = [
  {
    id: "overview",
    label: "总览",
    anchors: [
      ["summary", "进度摘要"],
      ["milestones", "里程碑"],
      ["priority", "下一步"],
      ["risk", "风险缺口"],
      ["recent-audit", "最近审计"]
    ]
  },
  {
    id: "plan",
    label: "计划",
    anchors: [
      ["milestone-table", "里程碑表"],
      ["task-list", "任务清单"],
      ["decision-log", "设计决策"]
    ]
  },
  {
    id: "code",
    label: "代码",
    anchors: [
      ["code-health", "代码健康"],
      ["module-map", "模块拆分"],
      ["task-list", "代码任务"]
    ]
  },
  {
    id: "test",
    label: "测试",
    anchors: [
      ["quality-gates", "质量门禁"],
      ["validation", "验证命令"],
      ["test-gaps", "测试缺口"]
    ]
  },
  {
    id: "docs",
    label: "文档",
    anchors: [
      ["document-index", "文档索引"],
      ["audit-timeline", "审计时间线"],
      ["handoff", "交接摘要"]
    ]
  },
  {
    id: "next",
    label: "下一步",
    anchors: [
      ["next-actions", "优先级清单"],
      ["acceptance", "验收标准"],
      ["decision-log", "设计决策"]
    ]
  }
];

const statusOptions: Array<[string, string]> = [
  ["", "全部状态"],
  ["done", "完成"],
  ["in_progress", "进行中"],
  ["todo", "待办"],
  ["blocked", "阻塞"],
  ["risk", "风险"]
];

const categoryOptions: Array<[string, string]> = [
  ["", "全部分类"],
  ["plan", "计划"],
  ["code", "代码"],
  ["test", "测试"],
  ["docs", "文档"],
  ["next", "下一步"]
];
const dashboardTitle = "GENO 工程进展 Dashboard";

function one(value: SearchValue): string {
  if (Array.isArray(value)) {
    return value[0] || "";
  }
  return value || "";
}

function cleanTab(value: string): TabId {
  return tabs.some((tab) => tab.id === value) ? (value as TabId) : "overview";
}

function tabHref(tab: TabId, filters: FilterState): string {
  const params = new URLSearchParams();
  params.set("tab", tab);
  if (filters.q) params.set("q", filters.q);
  if (filters.status) params.set("status", filters.status);
  if (filters.category) params.set("category", filters.category);
  if (filters.milestone) params.set("milestone", filters.milestone);
  return `/?${params.toString()}`;
}

function matchesFilters(item: Task | AuditEntry, filters: FilterState): boolean {
  const haystack = [
    item.title,
    item.summary,
    item.statusLabel,
    item.categoryLabel,
    "source" in item ? item.source : "docs/工程实施审计日志.md",
    "milestone" in item ? item.milestone : "",
    ...(item.evidencePaths || []),
    ...(item.commands || [])
  ]
    .join(" ")
    .toLowerCase();

  if (filters.q && !haystack.includes(filters.q.toLowerCase())) return false;
  if (filters.status && item.status !== filters.status) return false;
  if (filters.category && item.category !== filters.category) return false;
  if ("milestone" in item && filters.milestone && item.milestone !== filters.milestone) return false;
  return true;
}

function StatusBadge({ status, label }: { status: Status; label?: string }) {
  return <span className={`statusBadge ${status}`}>{label || status}</span>;
}

function ProgressBar({ value }: { value: number }) {
  return (
    <div className="progressTrack" aria-label={`完成度 ${value}%`}>
      <span className="progressFill" style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  );
}

function EvidenceBlock({ item }: { item: EvidenceItem }) {
  const paths = item.evidencePaths || [];
  const commands = item.commands || [];
  return (
    <div className="evidenceBlock">
      <div>
        <strong>路径</strong>
        {paths.length ? (
          <ul className="monoList">{paths.map((path) => <li key={path}>{path}</li>)}</ul>
        ) : (
          <p className="muted">未记录具体路径。</p>
        )}
      </div>
      <div>
        <strong>命令</strong>
        {commands.length ? (
          <ul className="monoList">{commands.map((command) => <li key={command}>{command}</li>)}</ul>
        ) : (
          <p className="muted">未记录验证命令。</p>
        )}
      </div>
      <div>
        <strong>结果</strong>
        <p className="muted">{item.result || "待补充结果。"}</p>
      </div>
    </div>
  );
}

function AnchorNav({ activeTab }: { activeTab: TabId }) {
  const tab = tabs.find((item) => item.id === activeTab) || tabs[0];
  return (
    <nav className="anchorNav" aria-label="页面内导航">
      {tab.anchors.map(([id, label]) => (
        <a key={id} href={`#${id}`}>{label}</a>
      ))}
    </nav>
  );
}

function FilterBar({ filters, milestones }: { filters: FilterState; milestones: string[] }) {
  return (
    <form className="filterBar" action="/" method="get">
      <input type="hidden" name="tab" value="plan" />
      <label>
        <span>关键词</span>
        <input name="q" defaultValue={filters.q} placeholder="路径、命令、任务标题" />
      </label>
      <label>
        <span>状态</span>
        <select name="status" defaultValue={filters.status}>
          {statusOptions.map(([value, label]) => <option key={value || "all"} value={value}>{label}</option>)}
        </select>
      </label>
      <label>
        <span>分类</span>
        <select name="category" defaultValue={filters.category}>
          {categoryOptions.map(([value, label]) => <option key={value || "all"} value={value}>{label}</option>)}
        </select>
      </label>
      <label>
        <span>里程碑</span>
        <select name="milestone" defaultValue={filters.milestone}>
          <option value="">全部里程碑</option>
          {milestones.map((milestone) => <option key={milestone} value={milestone}>{milestone}</option>)}
        </select>
      </label>
      <button type="submit">筛选</button>
      <a className="ghostButton" href="/?tab=plan">重置</a>
    </form>
  );
}

function MetricGrid() {
  return (
    <section id="summary" className="metricGrid">
      {data.summaryMetrics.map((metric) => (
        <article className="metricCard" key={metric.id}>
          <div className="metricTop"><span>{metric.label}</span><StatusBadge status={metric.status as Status} /></div>
          <strong>{metric.value}</strong>
          <p>{metric.detail}</p>
        </article>
      ))}
    </section>
  );
}

function MilestoneStrip() {
  return (
    <section id="milestones" className="panel">
      <div className="sectionHeader">
        <div><p className="eyebrow">Milestones</p><h2>M0-M7 里程碑进度</h2></div>
        <span className="countPill">{data.milestones.length} 个阶段</span>
      </div>
      <div className="milestoneStrip">
        {data.milestones.map((milestone) => (
          <article className="milestoneNode" key={milestone.id}>
            <div className="nodeTop"><strong>{milestone.id}</strong><StatusBadge status={milestone.status as Status} label={milestone.statusLabel} /></div>
            <h3>{milestone.phase}</h3>
            <p>{milestone.priority} · {milestone.epics}</p>
            <ProgressBar value={milestone.progress} />
          </article>
        ))}
      </div>
    </section>
  );
}

function NextActions({ compact = false }: { compact?: boolean }) {
  return (
    <section id={compact ? "priority" : "next-actions"} className="panel">
      <div className="sectionHeader">
        <div><p className="eyebrow">Next actions</p><h2>优先级下一步</h2></div>
        <span className="countPill">{data.nextActions.length} 项</span>
      </div>
      <div className="actionList">
        {data.nextActions.map((action) => (
          <details className="actionItem" key={action.id} open={!compact && action.priority === "P0"}>
            <summary>
              <span className="priorityPill">{action.priority}</span>
              <strong>{action.title}</strong>
              <StatusBadge status={action.status as Status} label={action.statusLabel} />
            </summary>
            <p>{action.summary}</p>
            <EvidenceBlock item={action} />
          </details>
        ))}
      </div>
    </section>
  );
}

function RiskPanel() {
  const risks = [
    "正式客户报告交付 readiness 仍为 10.0%，不能对真实客户标记 ready。",
    "OPENAI_API_KEY / PERPLEXITY_API_KEY 与 Google selector/session/manual assets 仍是外部依赖阻塞。",
    "Admin Web /projects/new 仍需接真实创建 API，Customer Web 还需接报告、评分、行动和图谱详情。",
    "repository.py、旧 /ops、main.py、models.py 仍是后续拆分重点。"
  ];
  return (
    <section id="risk" className="panel riskPanel">
      <div className="sectionHeader"><div><p className="eyebrow">Risks</p><h2>风险与缺口</h2></div></div>
      <ul className="riskList">{risks.map((risk) => <li key={risk}>{risk}</li>)}</ul>
    </section>
  );
}

function RecentAudit() {
  const recent = (data.auditTimeline as AuditEntry[]).slice(-8).reverse();
  return (
    <section id="recent-audit" className="panel">
      <div className="sectionHeader"><div><p className="eyebrow">Audit</p><h2>最近审计切片</h2></div><a className="ghostButton" href="/?tab=docs#audit-timeline">查看全部</a></div>
      <div className="compactTimeline">
        {recent.map((entry) => (
          <article key={entry.id}>
            <time>{entry.date}</time>
            <strong>{entry.title}</strong>
            <p>{entry.summary}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

function MilestoneTable() {
  return (
    <section id="milestone-table" className="panel">
      <div className="sectionHeader"><div><p className="eyebrow">Plan</p><h2>里程碑表</h2></div></div>
      <div className="tableWrap">
        <table>
          <thead><tr><th>里程碑</th><th>阶段</th><th>状态</th><th>完成度</th><th>出口标准</th><th>P 级</th></tr></thead>
          <tbody>
            {data.milestones.map((milestone) => (
              <tr key={milestone.id}>
                <td><strong>{milestone.id}</strong></td>
                <td>{milestone.phase}</td>
                <td><StatusBadge status={milestone.status as Status} label={milestone.statusLabel} /></td>
                <td><ProgressBar value={milestone.progress} /></td>
                <td>{milestone.exitCriteria}</td>
                <td>{milestone.priority}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function TaskTable({ tasks, title = "任务级完整清单" }: { tasks: Task[]; title?: string }) {
  return (
    <section id="task-list" className="panel">
      <div className="sectionHeader"><div><p className="eyebrow">Tasks</p><h2>{title}</h2></div><span className="countPill">{tasks.length} 条</span></div>
      <div className="tableWrap">
        <table className="taskTable">
          <thead><tr><th>状态</th><th>任务</th><th>里程碑</th><th>分类</th><th>来源</th><th>证据</th></tr></thead>
          <tbody>
            {tasks.map((task) => (
              <tr key={task.id}>
                <td><StatusBadge status={task.status} label={task.statusLabel} /></td>
                <td>
                  <details className="rowDetails">
                    <summary>{task.title}</summary>
                    <p>{task.summary}</p>
                    <EvidenceBlock item={task} />
                  </details>
                </td>
                <td>{task.milestone}</td>
                <td>{task.categoryLabel}</td>
                <td className="monoCell">{task.source}</td>
                <td>{(task.evidencePaths || []).length + (task.commands || []).length}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function CodeTab({ tasks }: { tasks: Task[] }) {
  return (
    <>
      <section id="code-health" className="panel">
        <div className="sectionHeader"><div><p className="eyebrow">Code health</p><h2>热点文件与结构性技术债</h2></div></div>
        <div className="tableWrap">
          <table>
            <thead><tr><th>文件</th><th>规模</th><th>状态</th><th>说明</th></tr></thead>
            <tbody>{data.codeHealth.map((item) => <tr key={item.file}><td className="monoCell">{item.file}</td><td>{item.scale}</td><td><StatusBadge status={item.status as Status} /></td><td>{item.summary}</td></tr>)}</tbody>
          </table>
        </div>
      </section>
      <section id="module-map" className="panel">
        <div className="sectionHeader"><div><p className="eyebrow">Module split</p><h2>已拆模块与继续拆分方向</h2></div></div>
        <div className="moduleGrid">
          {[
            ["runtime_access_routes.py", "客户门户与启动配置 router 已拆出"],
            ["access_logging.py", "HTTP 访问日志归档与入库已拆出"],
            ["runtime_metrics.py", "Prometheus 指标渲染已拆出"],
            ["runtime_project_access_repository.py", "客户门户 / 启动配置 / 访问日志 repository mixin 已拆出"],
            ["main.py", "项目/成员/邀请/实体消歧/报告/通知路由继续拆"],
            ["apps/web/app/ops/page.tsx", "旧 Runtime Console 按域迁移到独立入口"]
          ].map(([name, summary]) => <article key={name}><strong>{name}</strong><p>{summary}</p></article>)}
        </div>
      </section>
      <TaskTable tasks={tasks} title="代码相关任务" />
    </>
  );
}

function TestTab() {
  return (
    <>
      <section id="quality-gates" className="panel">
        <div className="sectionHeader"><div><p className="eyebrow">Quality gates</p><h2>质量门禁</h2></div></div>
        <div className="qualityGrid">
          {data.qualityGates.map((gate) => (
            <article className="qualityCard" key={gate.id}>
              <div><StatusBadge status={gate.status as Status} /><strong>{gate.name}</strong></div>
              <code>{gate.command}</code>
              <p>{gate.result}</p>
            </article>
          ))}
        </div>
      </section>
      <section id="validation" className="panel">
        <div className="sectionHeader"><div><p className="eyebrow">Commands</p><h2>推荐验证命令</h2></div></div>
        <div className="commandGrid">
          {["make quality", "make test", "make web-typecheck", "make web-build", "make docker-config", "make docker-up-auto-ports"].map((command) => <code key={command}>{command}</code>)}
        </div>
      </section>
      <section id="test-gaps" className="panel">
        <div className="sectionHeader"><div><p className="eyebrow">Gaps</p><h2>测试缺口</h2></div></div>
        <ul className="riskList">
          <li>Dashboard Web 新增后需要补 typecheck、build 和静态数据契约测试。</li>
          <li>客户门户 token、project launch config、runtime_http_access_logs 仍需要更完整 contract tests。</li>
          <li>真实 Docker smoke、P0a provider key、P0b Google browser/manual/full spike 仍未完成。</li>
        </ul>
      </section>
    </>
  );
}

function DocumentTab({ audits, filters }: { audits: AuditEntry[]; filters: FilterState }) {
  const grouped = audits.reduce<Record<string, AuditEntry[]>>((acc, entry) => {
    acc[entry.month] = acc[entry.month] || [];
    acc[entry.month].push(entry);
    return acc;
  }, {});
  const months = Object.keys(grouped).sort().reverse();
  return (
    <>
      <section id="document-index" className="panel">
        <div className="sectionHeader"><div><p className="eyebrow">Documents</p><h2>文档索引</h2></div></div>
        <div className="docGrid">
          {data.documents.map((doc) => <article key={doc.path}><strong>{doc.path}</strong><span>{doc.role}</span><p>{doc.summary}</p></article>)}
        </div>
      </section>
      <section id="audit-timeline" className="panel">
        <div className="sectionHeader">
          <div><p className="eyebrow">Audit timeline</p><h2>审计时间线</h2></div>
          <span className="countPill">{audits.length} / {data.auditStats.total} 条</span>
        </div>
        <form className="filterBar" action="/" method="get">
          <input type="hidden" name="tab" value="docs" />
          <label><span>关键词</span><input name="q" defaultValue={filters.q} placeholder="审计标题、路径、命令" /></label>
          <label><span>分类</span><select name="category" defaultValue={filters.category}>{categoryOptions.map(([value, label]) => <option key={value || "all"} value={value}>{label}</option>)}</select></label>
          <button type="submit">筛选</button><a className="ghostButton" href="/?tab=docs#audit-timeline">重置</a>
        </form>
        <div className="auditGroups">
          {months.map((month, index) => (
            <details className="auditGroup" key={month} open={index === 0}>
              <summary><strong>{month}</strong><span>{grouped[month].length} 条审计切片</span></summary>
              <div className="auditEntries">
                {grouped[month].map((entry) => (
                  <details className="auditEntry" key={entry.id}>
                    <summary><time>{entry.date}</time><strong>{entry.title}</strong><StatusBadge status={entry.status} label={entry.statusLabel} /></summary>
                    <p>{entry.summary}</p>
                    <EvidenceBlock item={entry} />
                  </details>
                ))}
              </div>
            </details>
          ))}
        </div>
      </section>
      <section id="handoff" className="panel">
        <div className="sectionHeader"><div><p className="eyebrow">Handoff</p><h2>当前交接摘要</h2></div></div>
        <p className="leadText">当前交接文件确认：客户门户和内部项目中心已拆出，旧 /ops 保留为迁移源；正式客户报告未 ready，下一步应优先接 Admin 项目创建、门户 token 管理和 Customer Web 真实报告详情。</p>
      </section>
    </>
  );
}

function DecisionLog() {
  return (
    <section id="decision-log" className="panel">
      <div className="sectionHeader"><div><p className="eyebrow">Decisions</p><h2>Dashboard 设计决策</h2></div></div>
      <div className="decisionGrid">{data.decisions.map((decision) => <span key={decision}>{decision}</span>)}</div>
    </section>
  );
}

function AcceptancePanel() {
  return (
    <section id="acceptance" className="panel">
      <div className="sectionHeader"><div><p className="eyebrow">Acceptance</p><h2>验收标准</h2></div></div>
      <ul className="riskList">
        <li>页面不依赖 API、数据库或 MinIO，静态 JSON 即可渲染。</li>
        <li>顶部 Tabs、Tab 内锚点、本地筛选、任务展开、审计分组折叠都可用。</li>
        <li>342 条审计日志切片在文档 Tab 中可检索、可展开。</li>
        <li>Docker 自动端口会打印 Dashboard Web URL，并能启动新服务。</li>
      </ul>
    </section>
  );
}

export default async function DashboardHome({ searchParams }: { searchParams?: DashboardSearchParams }) {
  const params = (await searchParams) || {};
  const filters: FilterState = {
    q: one(params.q).trim(),
    status: one(params.status).trim(),
    category: one(params.category).trim(),
    milestone: one(params.milestone).trim()
  };
  const activeTab = cleanTab(one(params.tab));
  const tasks = (data.tasks as Task[]).filter((task) => matchesFilters(task, filters));
  const audits = (data.auditTimeline as AuditEntry[]).filter((entry) => matchesFilters(entry, filters));
  const milestones = Array.from(new Set((data.tasks as Task[]).map((task) => task.milestone))).sort();
  const codeTasks = tasks.filter((task) => task.category === "code");

  return (
    <main className="dashboardShell">
      <header className="topHeader">
        <div>
          <p className="eyebrow">GENO AU Engineering</p>
          <h1>{data.meta.title || dashboardTitle}</h1>
          <p className="leadText">{data.meta.projectPhase}。{data.meta.dataPolicy}</p>
        </div>
        <div className="headerFacts">
          <span><strong>状态</strong>{data.meta.headlineStatus}</span>
          <span><strong>更新</strong>{data.meta.generatedAt}</span>
          <span><strong>最新提交</strong>{data.meta.latestCommit}</span>
        </div>
      </header>

      <nav className="tabNav" aria-label="Dashboard tabs">
        {tabs.map((tab) => <a key={tab.id} className={tab.id === activeTab ? "active" : ""} href={tabHref(tab.id, filters)}>{tab.label}</a>)}
      </nav>
      <AnchorNav activeTab={activeTab} />

      {activeTab === "overview" && <><MetricGrid /><MilestoneStrip /><NextActions compact /><RiskPanel /><RecentAudit /></>}
      {activeTab === "plan" && <><MilestoneTable /><FilterBar filters={filters} milestones={milestones} /><TaskTable tasks={tasks} /><DecisionLog /></>}
      {activeTab === "code" && <CodeTab tasks={codeTasks.length ? codeTasks : tasks.filter((task) => task.category === "code")} />}
      {activeTab === "test" && <TestTab />}
      {activeTab === "docs" && <DocumentTab audits={audits} filters={filters} />}
      {activeTab === "next" && <><NextActions /><AcceptancePanel /><DecisionLog /></>}
    </main>
  );
}
