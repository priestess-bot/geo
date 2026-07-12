import { readFile, stat } from "node:fs/promises";
import path from "node:path";

export const dynamic = "force-dynamic";

const checklistFileName = "GEO-Production-v1执行进度-checklist-2026-07-05.md";
const planFileName = "GEO-Production-v1完整规划-2026-07-05.md";
const reviewFileName = "GEO-Production-v1正式可用性复查报告-2026-07-05.md";
const knowledgePlanFileName = "GEO-知识库解析与生成工作流规划-2026-07-08.md";
const progressFileName = "GEO-当前项目进度汇报-2026-07-10.md";
const testingFileName = "GEO-可复用测试流程-2026-07-06.md";
const docsCandidateDirs = [
  path.join(process.cwd(), "docs"),
  path.join(process.cwd(), "..", "..", "docs")
];
const projectCandidateDirs = [
  process.cwd(),
  path.join(process.cwd(), "..", "..")
];

const currentDocuments = [
  {
    fileName: planFileName,
    title: "Production v1 完整规划",
    role: "唯一规划口径",
    summary: "冻结技术选型、P0/P1/P2 边界、工作流、门禁和最终验收命令。"
  },
  {
    fileName: checklistFileName,
    title: "执行进度 Checklist",
    role: "本页数据源",
    summary: "每个执行项必须同时具备完成状态、验收命令和证据路径；commit 作为独立交付记录。"
  },
  {
    fileName: reviewFileName,
    title: "正式可用性复查报告",
    role: "复查与整改基线",
    summary: "记录正式入口、用户动作、客户体验、测试覆盖和状态误报风险。"
  },
  {
    fileName: knowledgePlanFileName,
    title: "知识库生产工作流规划",
    role: "知识库实施蓝图",
    summary: "定义解析、OCR、表格、Chunk、事实、Prompt、文案、追踪、质量门禁和 36 项总验收。"
  },
  {
    fileName: progressFileName,
    title: "当前项目进度汇报",
    role: "最新事实状态",
    summary: "区分已实现、已实跑和仍被运行环境阻塞的门禁，不沿用旧 artifact 冒充完成。"
  },
  {
    fileName: testingFileName,
    title: "可复用测试流程",
    role: "变更验收规范",
    summary: "规定前后端、真实项目、知识库、模型、负向权限和最终门禁的复用流程。"
  }
];

const gateCommands = [
  {
    name: "最终门禁",
    command: "make production-v1-final-gate",
    detail: "串起 lint、typecheck、单测、DB/RLS、运行时 E2E、安全、真实 connector、前端点击、全生命周期、运维和备份。"
  },
  {
    name: "前端逐页点击",
    command: "make frontend-page-click-smoke",
    detail: "覆盖 Admin Web 和 Customer Web 的正式页面，检查渲染、控制台、框架 overlay 和基础交互。"
  },
  {
    name: "知识库前端生命周期",
    command: "make frontend-knowledge-click-smoke",
    detail: "从前端完成导入、事实审核、Prompt 生成/审核/导入、文案生成/审核/下载和检索。"
  },
  {
    name: "知识库完整流水线",
    command: "make geo-production-full-pipeline-smoke",
    detail: "强制执行重型组件、Qdrant、36 项 live E2E、重跑版本链和额外运行契约。"
  },
  {
    name: "完整项目生命周期",
    command: "make full-project-lifecycle-smoke",
    detail: "从创建项目开始跑配置、成员、邀请、Prompt、知识库、补录、报告、行动、审计和负向权限。"
  },
  {
    name: "真实模型调用",
    command: "make connector-real-smoke",
    detail: "使用 DeepSeek v4 flash 真实端点做 smoke，并验证测试产物不泄露 API key。"
  },
  {
    name: "看板真实性",
    command: "make development-board-truth-smoke",
    detail: "保证本页不再只按 Done 计数，而是按 Production Ready 条件计算。"
  }
];

const boardPrinciples = [
  {
    title: "唯一进度入口",
    detail: "独立 18006 Dashboard Web 不再作为默认入口；文档、门禁、审计摘要和下一步统一并入本页。"
  },
  {
    title: "只认正式证据",
    detail: "只有完成状态、验收命令和证据路径都可复核的执行项，才进入 Production Ready。"
  },
  {
    title: "旧口径降级",
    detail: "旧项目口径和历史工程叙述只保留在归档文件中，不再作为当前产品页面或验收依据。"
  },
  {
    title: "页面必须可操作",
    detail: "后续功能不能只在 API、脚本或旧 /ops 存在；必须能从 Admin Web 或 Customer Web 的正式路径完成关键动作。"
  }
];

type ChecklistItem = {
  id: string;
  section: string;
  title: string;
  status: string;
  command: string;
  evidence: string;
  commit: string;
  note: string;
  productionReady: boolean;
  productionBlockers: string[];
};

type UpgradeItem = {
  id: string;
  title: string;
  status: string;
  requirement: string;
};

type SectionGroup = {
  title: string;
  items: ChecklistItem[];
};

type DocumentItem = {
  fileName: string;
  title: string;
  role: string;
  summary: string;
  updatedAt: string;
  available: boolean;
};

type ArtifactItem = {
  id: string;
  title: string;
  command: string;
  path: string;
  status: string;
  detail: string;
  updatedAt: string;
  available: boolean;
};

type ChecklistData = {
  generatedAt: string;
  sourceUpdatedAt: string;
  groups: SectionGroup[];
  upgrades: UpgradeItem[];
  totals: {
    all: number;
    done: number;
    blocked: number;
    verifying: number;
    inProgress: number;
    notStarted: number;
    deferred: number;
    productionReady: number;
    productionPending: number;
  };
};

const workflowSectionPattern = /^##\s+\d+\.\s+(.+)$/;
const tableSeparatorPattern = /^\|\s*-+/;

function stripMarkdown(value: string): string {
  return value
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .trim();
}

function splitMarkdownRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => stripMarkdown(cell));
}

function normalizeStatus(status: string): string {
  const normalized = status.trim();
  if (normalized === "Done") {
    return "已完成";
  }
  if (normalized === "In progress") {
    return "进行中";
  }
  if (normalized === "Verifying") {
    return "验收中";
  }
  if (normalized === "Blocked") {
    return "阻塞";
  }
  if (normalized === "Not started") {
    return "未开始";
  }
  if (normalized === "Deferred upgrade") {
    return "后续升级";
  }
  return normalized || "未知";
}

function statusClassName(status: string): string {
  if (status === "Production Ready") {
    return "production";
  }
  if (status === "Needs Production Evidence") {
    return "blocked";
  }
  if (status === "Done") {
    return "done";
  }
  if (status === "Blocked") {
    return "blocked";
  }
  if (status === "Verifying") {
    return "verifying";
  }
  if (status === "In progress") {
    return "progress";
  }
  if (status === "Deferred upgrade") {
    return "deferred";
  }
  return "neutral";
}

function countStatus(items: ChecklistItem[], status: string): number {
  return items.filter((item) => item.status === status).length;
}

function hasUsableCell(value: string): boolean {
  const normalized = value.trim();
  return Boolean(normalized && normalized !== "待填" && normalized !== "未填写" && normalized !== "-");
}

function productionBlockersFor(cells: {
  status: string;
  command: string;
  evidence: string;
}): string[] {
  const blockers: string[] = [];
  if (cells.status !== "Done") {
    blockers.push(`状态仍为 ${cells.status || "未知"}`);
  }
  if (!hasUsableCell(cells.command)) {
    blockers.push("验收命令未填写");
  }
  if (!hasUsableCell(cells.evidence)) {
    blockers.push("证据路径未填写");
  }
  return blockers;
}

function parseChecklist(markdown: string, sourceUpdatedAt: string): ChecklistData {
  const lines = markdown.split(/\r?\n/);
  const generatedAt = stripMarkdown(lines.find((line) => line.startsWith("生成日期："))?.replace("生成日期：", "") || "未知");
  const groups: SectionGroup[] = [];
  const upgrades: UpgradeItem[] = [];
  let activeGroup: SectionGroup | null = null;
  let parsingUpgradeTable = false;

  for (const line of lines) {
    const sectionMatch = line.match(workflowSectionPattern);
    if (sectionMatch) {
      const sectionTitle = sectionMatch[1].trim();
      parsingUpgradeTable = sectionTitle.includes("升级项");
      activeGroup = parsingUpgradeTable ? null : { title: sectionTitle, items: [] };
      if (activeGroup) {
        groups.push(activeGroup);
      }
      continue;
    }

    if (!line.startsWith("|") || tableSeparatorPattern.test(line) || line.includes("编号 |")) {
      continue;
    }

    const cells = splitMarkdownRow(line);
    if (parsingUpgradeTable && cells.length >= 5 && cells[0].startsWith("U")) {
      upgrades.push({
        id: cells[0],
        title: cells[2],
        status: cells[3],
        requirement: cells[4]
      });
      continue;
    }

    if (!activeGroup || cells.length < 9) {
      continue;
    }

    const id = cells[0];
    if (!id || id === "编号" || id === "状态" || id.includes("---")) {
      continue;
    }

    const status = cells[4];
    const command = cells[5];
    const evidence = cells[6];
    const commit = cells[7];
    const note = cells[8];
    const productionBlockers = productionBlockersFor({ status, command, evidence });
    activeGroup.items.push({
      id,
      section: cells[1],
      title: cells[2],
      status,
      command,
      evidence,
      commit,
      note,
      productionReady: productionBlockers.length === 0,
      productionBlockers
    });
  }

  const allItems = groups.flatMap((group) => group.items);
  const productionReady = allItems.filter((item) => item.productionReady).length;
  return {
    generatedAt,
    sourceUpdatedAt,
    groups,
    upgrades,
    totals: {
      all: allItems.length,
      done: countStatus(allItems, "Done"),
      blocked: countStatus(allItems, "Blocked"),
      verifying: countStatus(allItems, "Verifying"),
      inProgress: countStatus(allItems, "In progress"),
      notStarted: countStatus(allItems, "Not started"),
      deferred: upgrades.filter((item) => item.status === "Deferred upgrade").length,
      productionReady,
      productionPending: allItems.length - productionReady
    }
  };
}

async function resolveDocsPath(fileName: string): Promise<string> {
  for (const docsDir of docsCandidateDirs) {
    const candidate = path.join(docsDir, fileName);
    try {
      await stat(candidate);
      return candidate;
    } catch {
      continue;
    }
  }
  return path.join(docsCandidateDirs[0], fileName);
}

async function loadChecklist(): Promise<ChecklistData> {
  const checklistPath = await resolveDocsPath(checklistFileName);
  const [markdown, metadata] = await Promise.all([readFile(checklistPath, "utf-8"), stat(checklistPath)]);
  return parseChecklist(markdown, metadata.mtime.toLocaleString("zh-CN", { hour12: false }));
}

async function resolveProjectPath(relativePath: string): Promise<string> {
  for (const rootDir of projectCandidateDirs) {
    const candidate = path.join(rootDir, relativePath);
    try {
      await stat(candidate);
      return candidate;
    } catch {
      continue;
    }
  }
  return path.join(projectCandidateDirs[0], relativePath);
}

async function loadDocumentItems(): Promise<DocumentItem[]> {
  return Promise.all(
    currentDocuments.map(async (document) => {
      try {
        const documentPath = await resolveDocsPath(document.fileName);
        const metadata = await stat(documentPath);
        return {
          ...document,
          updatedAt: metadata.mtime.toLocaleString("zh-CN", { hour12: false }),
          available: true
        };
      } catch {
        return {
          ...document,
          updatedAt: "未找到",
          available: false
        };
      }
    })
  );
}

function summarizeArtifact(payload: unknown): string {
  if (!payload || typeof payload !== "object") {
    return "测试产物不是对象结构。";
  }
  const record = payload as Record<string, unknown>;
  const summary = record.summary && typeof record.summary === "object" ? (record.summary as Record<string, unknown>) : {};
  const pass = summary.pass;
  const fail = summary.fail;
  const viewports = Array.isArray(summary.viewports) ? `；视口 ${summary.viewports.join(" / ")}` : "";
  const projectId = typeof record.project_id === "string" ? `；项目 ${record.project_id}` : "";
  if (pass !== undefined || fail !== undefined) {
    return `通过 ${pass ?? 0}，失败 ${fail ?? 0}${viewports}${projectId}`;
  }
  const live = record.live_pipeline && typeof record.live_pipeline === "object"
    ? record.live_pipeline as Record<string, unknown>
    : {};
  const acceptance = Array.isArray(live.acceptance_checks) ? live.acceptance_checks : [];
  const operational = Array.isArray(live.operational_checks) ? live.operational_checks : [];
  if (acceptance.length || operational.length) {
    return `知识库验收 ${acceptance.length}/36；运行契约 ${operational.length}/12${projectId}`;
  }
  return JSON.stringify(summary || {}).slice(0, 160) || "已生成，但没有 summary 字段。";
}

async function loadArtifactItems(): Promise<ArtifactItem[]> {
  const artifacts = [
    {
      id: "frontend-page-click-smoke",
      title: "前端逐页点击测试",
      command: "make frontend-page-click-smoke",
      path: "tmp/frontend-page-click-smoke/latest.json"
    },
    {
      id: "frontend-knowledge-lifecycle-smoke",
      title: "知识库前端生命周期测试",
      command: "make frontend-knowledge-click-smoke",
      path: "tmp/frontend-knowledge-lifecycle-smoke/latest.json"
    },
    {
      id: "geo-production-full-pipeline-smoke",
      title: "知识库完整生产流水线",
      command: "make geo-production-full-pipeline-smoke",
      path: "tmp/geo-production-full-pipeline-smoke/latest.json"
    },
    {
      id: "full-project-lifecycle-smoke",
      title: "完整项目生命周期测试",
      command: "make full-project-lifecycle-smoke",
      path: "tmp/full-project-lifecycle-smoke/latest.json"
    },
    {
      id: "connector-real-smoke",
      title: "真实模型调用 smoke",
      command: "make connector-real-smoke",
      path: "tmp/connector-real-smoke/latest.json"
    },
    {
      id: "promptfoo-knowledge-eval",
      title: "Prompt 与知识生成评估",
      command: "make promptfoo-knowledge-eval",
      path: "tmp/promptfoo-knowledge-eval/latest.json"
    }
  ];

  return Promise.all(
    artifacts.map(async (artifact) => {
      try {
        const artifactPath = await resolveProjectPath(artifact.path);
        const [raw, metadata] = await Promise.all([readFile(artifactPath, "utf-8"), stat(artifactPath)]);
        const payload = JSON.parse(raw) as Record<string, unknown>;
        const status = typeof payload.status === "string" ? payload.status : "unknown";
        return {
          ...artifact,
          status,
          detail: summarizeArtifact(payload),
          updatedAt: metadata.mtime.toLocaleString("zh-CN", { hour12: false }),
          available: true
        };
      } catch {
        return {
          ...artifact,
          status: "missing",
          detail: "尚未找到 latest.json；运行对应命令后会在这里显示最近结果。",
          updatedAt: "未生成",
          available: false
        };
      }
    })
  );
}

function buildFocusItems(groups: SectionGroup[]): Array<{ title: string; detail: string; command: string }> {
  return groups
    .map((group) => {
      const pending = group.items.filter((item) => !item.productionReady);
      const firstPending = pending[0];
      return {
        title: group.title,
        pending: pending.length,
        total: group.items.length,
        detail: firstPending
          ? `${firstPending.id}：${firstPending.productionBlockers.join("；") || "待补正式证据"}`
          : "本组 checklist 项已满足 Production Ready 口径。",
        command: firstPending?.command || "make production-v1-final-gate"
      };
    })
    .filter((item) => item.pending > 0)
    .sort((left, right) => right.pending - left.pending)
    .slice(0, 6)
    .map((item) => ({
      title: `${item.title}：${item.pending} / ${item.total} 待补`,
      detail: item.detail,
      command: item.command
    }));
}

function ProgressBar({ done, total }: { done: number; total: number }) {
  const percentage = total > 0 ? Math.round((done / total) * 100) : 0;

  return (
    <div className="developmentProgress" aria-label={`完成进度 ${percentage}%`}>
      <span style={{ width: `${percentage}%` }} />
    </div>
  );
}

export default async function DevelopmentBoardPage() {
  const [checklist, documents, artifacts] = await Promise.all([loadChecklist(), loadDocumentItems(), loadArtifactItems()]);
  const completion = checklist.totals.all > 0 ? Math.round((checklist.totals.productionReady / checklist.totals.all) * 100) : 0;
  const focusItems = buildFocusItems(checklist.groups);

  return (
    <main className="shell developmentBoardShell">
      <section className="topbar developmentTopbar">
        <div>
          <p className="eyebrow">开发板</p>
          <h1>GEO Production v1 执行看板</h1>
          <p className="muted" style={{ marginTop: 8 }}>
            这是当前唯一的工程进度看板。它从最新 checklist、正式规划、复查报告和 smoke 产物读取事实；状态、验收命令和证据路径均完整，才计入正式完成，commit 作为独立交付记录展示。
          </p>
        </div>
        <nav className="nav">
          <a className="button secondary" href="/">
            返回首页
          </a>
          <a className="button secondary" href="/projects">
            项目列表
          </a>
          <a className="button secondary" href="#gate-evidence">
            验收证据
          </a>
        </nav>
      </section>

      <section className="developmentSourcePanel" aria-label="数据来源">
        <div>
          <span>数据来源</span>
          <strong>{checklistFileName}</strong>
        </div>
        <div>
          <span>对照规划</span>
          <strong>{planFileName}</strong>
        </div>
        <div>
          <span>Checklist 生成日期</span>
          <strong>{checklist.generatedAt}</strong>
        </div>
        <div>
          <span>文件最后更新时间</span>
          <strong>{checklist.sourceUpdatedAt}</strong>
        </div>
      </section>

      <section className="developmentNotice" aria-label="看板合并说明">
        <div>
          <span className="statusPill statusPill-production">已合并</span>
          <h2>18006 独立 Dashboard 不再作为默认入口</h2>
          <p>
            原 Dashboard Web 的“文档、审计、下一步、门禁”信息已经并入本页。默认启动只保留 Admin Web 的
            <strong> /development-board</strong> 作为正式进度入口，避免两个看板使用不同日期、不同项目名和不同完成口径。
          </p>
        </div>
      </section>

      <section className="developmentHeroGrid" aria-label="总体进度">
        <div className="developmentHeroCard">
          <span>总体完成率</span>
          <strong>{completion}%</strong>
          <ProgressBar done={checklist.totals.productionReady} total={checklist.totals.all} />
          <p className="muted">
            Production Ready {checklist.totals.productionReady} / {checklist.totals.all} 个执行项；普通 Done 但缺证据不计入。
          </p>
        </div>
        <div className="developmentMetric warningMetric">
          <span>待补正式证据</span>
          <strong>{checklist.totals.productionPending}</strong>
        </div>
        <div className="developmentMetric">
          <span>阻塞</span>
          <strong>{checklist.totals.blocked}</strong>
        </div>
        <div className="developmentMetric">
          <span>验收中</span>
          <strong>{checklist.totals.verifying}</strong>
        </div>
        <div className="developmentMetric">
          <span>进行中</span>
          <strong>{checklist.totals.inProgress}</strong>
        </div>
        <div className="developmentMetric">
          <span>未开始</span>
          <strong>{checklist.totals.notStarted}</strong>
        </div>
        <div className="developmentMetric">
          <span>后续升级</span>
          <strong>{checklist.totals.deferred}</strong>
        </div>
      </section>

      <section className="developmentDocPanel" aria-label="当前文档索引">
        <div className="sectionTitle">
          <div>
            <p className="eyebrow">当前口径</p>
            <h2>文档索引</h2>
          </div>
        </div>
        <div className="developmentDocGrid">
          {documents.map((document) => (
            <article className="developmentDocCard" key={document.fileName}>
              <span className={`statusPill statusPill-${document.available ? "production" : "blocked"}`}>
                {document.available ? "可读取" : "缺失"}
              </span>
              <h3>{document.title}</h3>
              <p>{document.summary}</p>
              <dl className="developmentItemMeta">
                <div>
                  <dt>文件</dt>
                  <dd>{document.fileName}</dd>
                </div>
                <div>
                  <dt>角色</dt>
                  <dd>{document.role}</dd>
                </div>
                <div>
                  <dt>更新时间</dt>
                  <dd>{document.updatedAt}</dd>
                </div>
              </dl>
            </article>
          ))}
        </div>
      </section>

      <section id="gate-evidence" className="developmentDocPanel" aria-label="验收门禁与近期证据">
        <div className="sectionTitle">
          <div>
            <p className="eyebrow">验收证据</p>
            <h2>门禁命令与最近测试产物</h2>
          </div>
        </div>
        <div className="developmentGateGrid">
          {gateCommands.map((gate) => (
            <article className="developmentGateCard" key={gate.command}>
              <h3>{gate.name}</h3>
              <code>{gate.command}</code>
              <p>{gate.detail}</p>
            </article>
          ))}
        </div>
        <div className="developmentArtifactGrid">
          {artifacts.map((artifact) => (
            <article className="developmentArtifactCard" key={artifact.id}>
              <span className={`statusPill statusPill-${artifact.status === "passed" ? "production" : artifact.available ? "verifying" : "blocked"}`}>
                {artifact.status === "passed" ? "最近通过" : artifact.available ? artifact.status : "未生成"}
              </span>
              <h3>{artifact.title}</h3>
              <p>{artifact.detail}</p>
              <dl className="developmentItemMeta">
                <div>
                  <dt>命令</dt>
                  <dd>{artifact.command}</dd>
                </div>
                <div>
                  <dt>产物</dt>
                  <dd>{artifact.path}</dd>
                </div>
                <div>
                  <dt>更新时间</dt>
                  <dd>{artifact.updatedAt}</dd>
                </div>
              </dl>
            </article>
          ))}
        </div>
      </section>

      <section className="developmentDocPanel" aria-label="审计口径与下一步焦点">
        <div className="sectionTitle">
          <div>
            <p className="eyebrow">审计与焦点</p>
            <h2>当前看板规则</h2>
          </div>
        </div>
        <div className="developmentPrincipleGrid">
          {boardPrinciples.map((principle) => (
            <article className="developmentPrinciple" key={principle.title}>
              <h3>{principle.title}</h3>
              <p>{principle.detail}</p>
            </article>
          ))}
        </div>
        <div className="developmentFocusList">
          {focusItems.length ? (
            focusItems.map((item) => (
              <article className="developmentFocusItem" key={item.title}>
                <div>
                  <h3>{item.title}</h3>
                  <p>{item.detail}</p>
                </div>
                <code>{item.command}</code>
              </article>
            ))
          ) : (
            <article className="developmentFocusItem">
              <div>
                <h3>没有待补 Production Ready 条目</h3>
                <p>继续运行最终门禁并保持文档和证据对齐，commit 作为独立交付记录维护。</p>
              </div>
              <code>make production-v1-final-gate</code>
            </article>
          )}
        </div>
      </section>

      <section className="developmentGroups" aria-label="工作流状态">
        {checklist.groups.map((group) => {
          const done = group.items.filter((item) => item.productionReady).length;
          return (
            <details className="developmentGroup" key={group.title} open>
              <summary>
                <span>
                  <strong>{group.title}</strong>
                  <small>
                    {done} / {group.items.length} Production Ready
                  </small>
                </span>
                <ProgressBar done={done} total={group.items.length} />
              </summary>
              <div className="developmentItemList">
                {group.items.map((item) => (
                  <article className="developmentItem" key={item.id}>
                    <div className="developmentItemMain">
                      <span className={`statusPill statusPill-${statusClassName(item.productionReady ? "Production Ready" : item.status === "Done" ? "Needs Production Evidence" : item.status)}`}>
                        {item.productionReady ? "正式完成" : item.status === "Done" ? "待补正式证据" : normalizeStatus(item.status)}
                      </span>
                      <h2>
                        {item.id} · {item.title}
                      </h2>
                      <p>{item.note || "无额外备注"}</p>
                      {!item.productionReady ? (
                        <p className="developmentBlockers">
                          {item.productionBlockers.join("；")}
                        </p>
                      ) : null}
                    </div>
                    <dl className="developmentItemMeta">
                      <div>
                        <dt>规划章节</dt>
                        <dd>{item.section}</dd>
                      </div>
                      <div>
                        <dt>验收命令</dt>
                        <dd>{item.command || "未填写"}</dd>
                      </div>
                      <div>
                        <dt>证据路径</dt>
                        <dd>{item.evidence || "未填写"}</dd>
                      </div>
                      <div>
                        <dt>Commit</dt>
                        <dd>{item.commit || "未填写"}</dd>
                      </div>
                    </dl>
                  </article>
                ))}
              </div>
            </details>
          );
        })}
      </section>

      <section className="developmentUpgradePanel" aria-label="后续升级项">
        <div className="sectionTitle">
          <div>
            <p className="eyebrow">不纳入本次完成门槛</p>
            <h2>后续升级边界</h2>
          </div>
        </div>
        <div className="developmentUpgradeGrid">
          {checklist.upgrades.map((item) => (
            <article className="developmentUpgrade" key={item.id}>
              <span className={`statusPill statusPill-${statusClassName(item.status)}`}>
                {normalizeStatus(item.status)}
              </span>
              <h3>
                {item.id} · {item.title}
              </h3>
              <p>{item.requirement}</p>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}
