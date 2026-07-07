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
    running: "运行中",
    queued: "排队中",
    crawling: "抓取中",
    crawled: "已抓取",
    extracting: "抽取中",
    extracted: "已抽取",
    failed: "失败",
    succeeded: "成功",
    approved: "已批准",
    rejected: "已拒绝",
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
