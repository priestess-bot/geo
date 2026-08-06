"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";

type CampaignOption = Readonly<{
  id: string;
  name: string;
  status: string;
}>;

export function QuestionCampaignSwitcher({
  campaigns,
  embedded,
  projectId,
  selectedCampaignId
}: {
  campaigns: readonly CampaignOption[];
  embedded: boolean;
  projectId: string;
  selectedCampaignId?: string;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  return <label>
    <span>测量活动</span>
    <select
      aria-label="测量活动"
      defaultValue={selectedCampaignId || ""}
      disabled={pending}
      onChange={(event) => {
        const params = new URLSearchParams({
          workflow_view: "questions",
          campaign_id: event.currentTarget.value
        });
        const pathname = embedded
          ? `/projects/${encodeURIComponent(projectId)}`
          : `/projects/${encodeURIComponent(projectId)}/workflow-c`;
        if (embedded) params.set("tab", "measurement");
        startTransition(() => router.push(`${pathname}?${params.toString()}`));
      }}
    >
      <option disabled value="">选择活动</option>
      {campaigns.map((campaign) => <option key={campaign.id} value={campaign.id}>
        {campaign.name} · {campaign.status === "active" ? "运行中" : campaign.status}
      </option>)}
    </select>
  </label>;
}
