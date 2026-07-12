export function statusLabel(status?: string): string {
  const normalized = String(status || "").trim().toLowerCase();
  const labels: Record<string, string> = {
    active: "运行中",
    paused: "暂停中",
    archived: "已归档",
    configured: "已配置",
    draft: "草稿",
    ready: "就绪",
    fixture: "开发测试",
    fixture_only: "仅开发测试",
    manual: "手工补录",
    manual_ready: "手工补录就绪",
    not_configured: "未配置",
    pending: "待处理",
    pending_review: "待审核",
    pending_human_review: "等待人工审核",
    waiting_human_review: "等待人工审核",
    waiting_review: "等待审核",
    not_started: "未开始",
    retrying: "重试中",
    blocked: "已阻断",
    skipped: "已跳过",
    running: "运行中",
    queued: "排队中",
    crawling: "抓取中",
    crawled: "已抓取",
    extracting: "抽取中",
    extracted: "已抽取",
    failed: "失败",
    succeeded: "成功",
    partial_succeeded: "部分成功",
    fallback_succeeded: "降级后成功",
    approved: "已批准",
    edited_approved: "编辑后批准",
    rejected: "已拒绝",
    needs_reextract: "需要重新抽取",
    needs_revision: "需要修改",
    superseded: "已替代",
    merged: "已合并",
    forbidden: "禁止使用",
    disabled: "已禁用",
    embedded: "已向量化",
    stale: "已过期",
    warning: "警告",
    passed: "已通过",
    accepted_risk: "已接受风险",
    published: "已发布",
    exported: "已导出",
    imported: "已导入",
    accepted: "已接受",
    revoked: "已撤销",
    expired: "已过期",
    client_ready: "客户可见",
    internal_review: "内部审核",
    owner: "负责人",
    admin: "管理员",
    analyst: "分析师",
    viewer: "客户查看者"
  };
  return labels[normalized] || status || "未知";
}

export function projectStatusLabel(status?: string): string {
  return statusLabel(status);
}

export function roleLabel(role?: string): string {
  return statusLabel(role);
}
