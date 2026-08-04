import type { ReactNode } from "react";

import type {
  SyntheticChannel,
  SyntheticLabView,
  SyntheticLoadProblem
} from "./syntheticLabTypes";
import styles from "./SyntheticLab.module.css";

export const syntheticViewItems: ReadonlyArray<Readonly<{
  id: SyntheticLabView;
  label: string;
  description: string;
}>> = [
  { id: "generate", label: "生成工作台", description: "填写目标并查看结果" },
  { id: "style", label: "渠道风格", description: "维护九渠道风格提示词" }
];

export function SyntheticLabNavigation({
  currentView,
  projectId
}: {
  currentView: SyntheticLabView;
  projectId: string;
}) {
  return (
    <nav aria-label="合成测评实验室功能" className={styles.labNavigation}>
      {syntheticViewItems.map((item) => (
        <a
          aria-current={item.id === currentView ? "page" : undefined}
          className={`${styles.labNavItem}${item.id === currentView ? ` ${styles.labNavItemActive}` : ""}`}
          href={syntheticHref(projectId, item.id)}
          key={item.id}
        >
          <strong>{item.label}</strong>
          <span>{item.description}</span>
        </a>
      ))}
    </nav>
  );
}

export function SyntheticBoundaryBand({ compact = false }: { compact?: boolean }) {
  return (
    <section
      className={`${styles.boundaryBand}${compact ? ` ${styles.boundaryBandCompact}` : ""}`}
      aria-label="合成测评实验室使用边界"
    >
      <strong>仅限内部合成测评</strong>
      <span>不会进入客户门户，也不能直接发布。</span>
      <details>
        <summary>查看技术边界</summary>
        <code>synthetic = true</code>
        <code>test_only = true</code>
        <code>publication_eligible = false</code>
      </details>
    </section>
  );
}

export function ViewHeader({
  eyebrow,
  title,
  description,
  action
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <header className={styles.viewHeader}>
      <div>
        <p>{eyebrow}</p>
        <h3>{title}</h3>
        <span>{description}</span>
      </div>
      {action ? <div className={styles.viewHeaderAction}>{action}</div> : null}
    </header>
  );
}

export function SectionHeading({
  eyebrow,
  title,
  aside
}: {
  eyebrow?: string;
  title: string;
  aside?: ReactNode;
}) {
  return (
    <div className={styles.sectionHeading}>
      <div>{eyebrow ? <p>{eyebrow}</p> : null}<h4>{title}</h4></div>
      {aside ? <div className={styles.sectionAside}>{aside}</div> : null}
    </div>
  );
}

export function StatusBadge({ value }: { value: string }) {
  return (
    <span className={`${styles.statusPill} ${styles[`status_${value}`] || ""}`}>
      {statusLabel(value)}
    </span>
  );
}

export function EmptyState({
  title,
  description,
  action
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className={styles.emptyState}>
      <strong>{title}</strong>
      {description ? <span>{description}</span> : null}
      {action ? <div>{action}</div> : null}
    </div>
  );
}

export function LoadProblem({
  problem,
  title = "内容加载失败"
}: {
  problem: SyntheticLoadProblem;
  title?: string;
}) {
  return (
    <div className={styles.loadError} role="alert">
      <strong>{problem.status ? `${problem.status} · ` : ""}{title}</strong>
      <span>{problem.detail}</span>
      <small>可以刷新重试；其他未依赖此数据的功能仍可继续使用。</small>
      {problem.correlationId ? <code>关联 ID：{problem.correlationId}</code> : null}
    </div>
  );
}

export function TechnicalMetadata({
  items
}: {
  items: ReadonlyArray<Readonly<{ label: string; value: string }>>;
}) {
  return (
    <dl className={styles.metadataGrid}>
      {items.map((item) => (
        <div key={item.label}><dt>{item.label}</dt><dd><code>{item.value}</code></dd></div>
      ))}
    </dl>
  );
}

export function syntheticHref(
  projectId: string,
  view: SyntheticLabView,
  values: Record<string, string> = {}
): string {
  const query = new URLSearchParams({ tab: "synthetic-lab", synthetic_view: view, ...values });
  return `/projects/${encodeURIComponent(projectId)}?${query.toString()}`;
}

export function statusLabel(value: string): string {
  return {
    active: "启用",
    draft: "草稿",
    pending: "待处理",
    pending_review: "待审核",
    in_review: "审核中",
    approved: "已批准",
    frozen: "已冻结",
    queued: "排队中",
    running: "运行中",
    finalizing: "正在收尾",
    retry_wait: "等待重试",
    succeeded: "已完成",
    passed: "通过",
    completed_with_warning: "带提醒完成",
    failed: "失败",
    dead_lettered: "需人工处理",
    cancelled: "已取消",
    revoked: "已撤销",
    expired: "已过期",
    assessed_no_basis: "无采集依据",
    not_assessed: "待评估",
    retired: "已停用",
    suspended: "已暂停",
    superseded: "已替代",
    rejected: "已拒绝"
  }[value] || value;
}

export function channelLabel(value: SyntheticChannel | string): string {
  return {
    owned_site: "自有网站",
    amazon: "Amazon",
    youtube: "YouTube",
    tiktok: "TikTok",
    instagram: "Instagram",
    productreview: "ProductReview",
    reddit: "Reddit",
    ozbargain: "OzBargain",
    quora: "Quora"
  }[value] || value;
}

export function jobKindLabel(value: string): string {
  return {
    style_collection: "风格样本采集",
    style_profile_build: "风格画像构建",
    candidate_generation: "目标仿真文案生成",
    candidate_revision: "文案修订",
    corpus_finalize: "语料冻结",
    offline_experiment: "离线三臂实验"
  }[value] || value;
}

export function caseModeLabel(value: string): string {
  return {
    autonomous_scenario: "自主场景",
    guided_scenario: "引导场景"
  }[value] || value;
}

export function accessModeLabel(value: string): string {
  return { public: "公开页面", authenticated: "登录页面", manual_import: "人工导入" }[value] || value;
}
