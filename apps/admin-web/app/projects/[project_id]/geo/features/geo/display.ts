import type { CatalogEntity, MarketProfile } from "../../../catalogTypes";
import type { DestinationView, OpportunityView } from "@geo/types/geo";

const CHANNEL_LABELS: Record<string, string> = {
  owned_site: "品牌官网", productreview: "ProductReview", youtube: "YouTube",
  reddit: "Reddit", amazon: "Amazon Australia", ozbargain: "OzBargain",
  tiktok: "TikTok", instagram: "Instagram", quora: "Quora", other: "其他渠道"
};

const STATUS_LABELS: Record<string, string> = {
  active: "进行中", draft: "草稿", frozen: "已冻结", paused: "已暂停", archived: "已归档",
  identified: "待准备", qualified: "已就绪", briefing: "准备内容", in_progress: "进行中",
  blocked: "受阻", completed: "已完成", cancelled: "已取消", approved: "已批准",
  restricted: "受限", prohibited: "禁止", pending: "等待中", pending_review: "待审核",
  ready: "可使用", succeeded: "成功", failed: "失败", verified: "已验证",
  awaiting_url: "等待网址", needs_revision: "需要修改", rejected: "已拒绝",
  policy_approved: "政策已批准", missing: "未配置", open: "待处理",
  finalized: "已完成", queued: "排队中", running: "处理中", retry_wait: "等待重试",
  complete: "完整", confounded: "存在混杂", insufficient_evidence: "证据不足"
};

export function channelLabel(channel: string): string {
  return CHANNEL_LABELS[channel] || channel.replaceAll("_", " ");
}

export function statusLabel(status: string): string {
  return STATUS_LABELS[status.replaceAll(" ", "_")] || status.replaceAll("_", " ");
}

export function entityName(entities: CatalogEntity[], id?: string | null): string {
  return entities.find((item) => item.id === id)?.canonical_name || "未选择产品";
}

export function marketName(markets: MarketProfile[], id?: string | null): string {
  const market = markets.find((item) => item.id === id);
  return market ? `${market.market_code} · ${market.locale}` : "未选择市场";
}

export function destinationName(destinations: DestinationView[], id?: string | null): string {
  const item = destinations.find((candidate) => candidate.id === id);
  return item ? `${channelLabel(item.publication_channel)} · ${item.destination_key}` : "未选择渠道";
}

export function opportunityName(
  opportunities: OpportunityView[], destinations: DestinationView[], id?: string | null
): string {
  const opportunity = opportunities.find((item) => item.id === id);
  return opportunity ? destinationName(destinations, opportunity.destination_id) : "请选择渠道任务";
}

export function commandLabel(command: string): string {
  return ({ qualify: "标记就绪", block: "标记受阻", reopen: "重新打开", cancel: "取消任务" } as Record<string, string>)[command] || command;
}

export function opportunityRationale(value: string): string {
  if (value.startsWith("Prepare an evidence-backed, policy-gated placement task")) {
    return "为当前商品准备有证据支持、符合渠道政策的投放内容；受限渠道保留任务并显示阻断原因。";
  }
  return value;
}
