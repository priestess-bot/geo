import { InternalApiClient } from "@geo/api-client/internal";
import type {
  EngineeringAxis,
  EngineeringAxisState,
  EngineeringWorkItem,
  EngineeringWorkItemsResponse
} from "@geo/types/internal";
import {
  ENGINEERING_AXIS_LABELS,
  ENGINEERING_STATUS_LABELS,
  FRESHNESS_LABELS
} from "@geo/ui";

import { actorHeaders, apiBase } from "../runtime";

const AXES: EngineeringAxis[] = ["planned", "implemented", "verified", "deployed"];

type BoardLoad =
  | { status: "available"; items: EngineeringWorkItem[]; observedAt?: string }
  | { status: "unavailable"; detail: string; correlationId?: string };

function isAxisState(value: unknown): value is EngineeringAxisState {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const state = value as Partial<EngineeringAxisState>;
  return (
    ["satisfied", "pending", "blocked", "unavailable"].includes(String(state.status))
    && Array.isArray(state.evidence)
    && state.evidence.every((entry) => (
      Boolean(entry)
      && typeof entry === "object"
      && typeof entry.label === "string"
      && (entry.url === undefined || typeof entry.url === "string")
    ))
    && (state.observed_at === undefined || typeof state.observed_at === "string")
  );
}

function isWorkItem(value: unknown): value is EngineeringWorkItem {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const item = value as Partial<EngineeringWorkItem>;
  const axes = item.axes as Partial<Record<EngineeringAxis, unknown>> | undefined;
  return (
    typeof item.id === "string"
    && typeof item.title === "string"
    && (item.summary === undefined || typeof item.summary === "string")
    && Boolean(axes)
    && AXES.every((axis) => isAxisState(axes?.[axis]))
    && Array.isArray(item.blockers)
    && item.blockers.every((blocker) => typeof blocker === "string")
    && typeof item.observed_at === "string"
    && ["fresh", "stale", "unknown"].includes(String(item.freshness))
  );
}

function isWorkItemsResponse(value: unknown): value is EngineeringWorkItemsResponse {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const response = value as Partial<EngineeringWorkItemsResponse>;
  return (
    Array.isArray(response.items)
    && response.items.every(isWorkItem)
    && (response.observed_at === undefined || typeof response.observed_at === "string")
  );
}

async function loadBoard(): Promise<BoardLoad> {
  const client = new InternalApiClient(apiBase(), {
    headers: await actorHeaders(),
    cache: "no-store"
  });
  const result = await client.listEngineeringWorkItems();
  if (!result.ok) {
    return {
      status: "unavailable",
      detail: result.error.detail || "工程事实接口当前不可用。",
      correlationId: result.error.correlation_id || result.response.correlationId
    };
  }
  if (!isWorkItemsResponse(result.data)) {
    return {
      status: "unavailable",
      detail: "工程事实接口返回了无法识别的契约；看板不会据此推断完成状态。",
      correlationId: result.response.correlationId
    };
  }
  return {
    status: "available",
    items: result.data.items,
    observedAt: result.data.observed_at
  };
}

function axisSummary(items: EngineeringWorkItem[], axis: EngineeringAxis) {
  const satisfied = items.filter((item) => item.axes[axis].status === "satisfied").length;
  return {
    satisfied,
    total: items.length,
    percentage: items.length ? Math.round((satisfied / items.length) * 100) : 0
  };
}

function itemIsDone(item: EngineeringWorkItem): boolean {
  return AXES.every((axis) => item.axes[axis].status === "satisfied");
}

function formatObservedAt(value?: string): string {
  if (!value) {
    return "未提供";
  }
  const timestamp = new Date(value);
  return Number.isNaN(timestamp.valueOf())
    ? value
    : timestamp.toLocaleString("zh-CN", { hour12: false });
}

function safeEvidenceHref(url?: string): string | undefined {
  if (!url) {
    return undefined;
  }
  return url.startsWith("/") || url.startsWith("https://") || url.startsWith("http://")
    ? url
    : undefined;
}

function AxisEvidence({ state }: { state: EngineeringAxisState }) {
  return (
    <div className={`engineeringAxis engineeringAxis-${state.status}`}>
      <span className="statusPill">{ENGINEERING_STATUS_LABELS[state.status]}</span>
      {state.evidence.length ? (
        <ul>
          {state.evidence.map((evidence, index) => {
            const href = safeEvidenceHref(evidence.url);
            return (
              <li key={`${evidence.label}-${index}`}>
                {href ? <a href={href}>{evidence.label}</a> : evidence.label}
              </li>
            );
          })}
        </ul>
      ) : (
        <small>无证据</small>
      )}
      <small>观测：{formatObservedAt(state.observed_at)}</small>
    </div>
  );
}

function UnavailableBoard({ detail, correlationId }: { detail: string; correlationId?: string }) {
  return (
    <section className="developmentUnavailable" aria-live="polite" role="status">
      <span className="statusPill statusPill-blocked">Unavailable</span>
      <h2>工程事实暂不可用</h2>
      <p>{detail}</p>
      <p className="muted">
        看板不会回退到文档、提交数量或静态百分比来伪造完成状态。
        {correlationId ? ` 关联 ID：${correlationId}` : ""}
      </p>
    </section>
  );
}

export default async function DevelopmentBoardPage() {
  const board = await loadBoard();

  return (
    <main className="shell developmentBoardShell">
      <section className="topbar developmentTopbar">
        <div>
          <p className="eyebrow">Engineering governance</p>
          <h1>Development Board</h1>
          <p className="muted" style={{ marginTop: 8 }}>
            进度来自工程事实接口。工作项只有在 Planned、Implemented、Verified、Deployed
            四个必需轴全部满足时才标记完成。
          </p>
        </div>
        <nav className="nav" aria-label="Development Board 导航">
          <a className="button secondary" href="/">返回首页</a>
          <a className="button secondary" href="/projects">项目列表</a>
        </nav>
      </section>

      {board.status === "unavailable" ? (
        <UnavailableBoard detail={board.detail} correlationId={board.correlationId} />
      ) : (
        <>
          <section className="developmentSourcePanel" aria-label="工程事实来源">
            <div><span>接口</span><strong>/v1/engineering/work-items</strong></div>
            <div><span>工作项</span><strong>{board.items.length}</strong></div>
            <div><span>整体观测时间</span><strong>{formatObservedAt(board.observedAt)}</strong></div>
            <div><span>完成口径</span><strong>四轴全部满足</strong></div>
          </section>

          <section className="engineeringAxisSummary" aria-label="四轴进度">
            {AXES.map((axis) => {
              const summary = axisSummary(board.items, axis);
              return (
                <article key={axis}>
                  <span>{ENGINEERING_AXIS_LABELS[axis]}</span>
                  <strong>{summary.percentage}%</strong>
                  <p>{summary.satisfied} / {summary.total} 已满足</p>
                </article>
              );
            })}
          </section>

          {board.items.length ? (
            <section className="engineeringWorkItems" aria-label="工程工作项">
              {board.items.map((item) => (
                <article className="engineeringWorkItem" key={item.id}>
                  <header>
                    <div>
                      <span className={`statusPill statusPill-${itemIsDone(item) ? "production" : "progress"}`}>
                        {itemIsDone(item) ? "Done" : "Not done"}
                      </span>
                      <h2>{item.title}</h2>
                      {item.summary ? <p>{item.summary}</p> : null}
                    </div>
                    <dl>
                      <div><dt>Observed at</dt><dd>{formatObservedAt(item.observed_at)}</dd></div>
                      <div><dt>Freshness</dt><dd>{FRESHNESS_LABELS[item.freshness]}</dd></div>
                    </dl>
                  </header>

                  {item.blockers.length ? (
                    <div className="developmentBlockers">
                      <strong>Blockers</strong>
                      <ul>{item.blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}</ul>
                    </div>
                  ) : null}

                  <div className="engineeringAxisGrid">
                    {AXES.map((axis) => (
                      <section key={axis} aria-label={ENGINEERING_AXIS_LABELS[axis]}>
                        <h3>{ENGINEERING_AXIS_LABELS[axis]}</h3>
                        <AxisEvidence state={item.axes[axis]} />
                      </section>
                    ))}
                  </div>
                </article>
              ))}
            </section>
          ) : (
            <section className="developmentUnavailable">
              <h2>尚无工作项</h2>
              <p>接口已响应，但没有返回工程工作项；因此所有四轴均保持 0 / 0。</p>
            </section>
          )}
        </>
      )}
    </main>
  );
}
