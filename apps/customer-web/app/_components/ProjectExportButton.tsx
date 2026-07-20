"use client";

import { useState } from "react";

export function ProjectExportButton({
  campaignId,
  projectId
}: Readonly<{ campaignId: string; projectId: string }>) {
  const [state, setState] = useState<"idle" | "pending" | "failed">("idle");
  const [detail, setDetail] = useState("");

  async function start() {
    setState("pending");
    setDetail("");
    const query = new URLSearchParams({ project_id: projectId, campaign_id: campaignId });
    const response = await fetch(`/api/project-export?${query}`, { cache: "no-store" });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      setState("failed");
      setDetail(typeof payload.detail === "string" ? payload.detail : "导出下载失败");
      return;
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `geo-project-export-${campaignId}.zip`;
    anchor.click();
    URL.revokeObjectURL(url);
    setState("idle");
  }

  return (
    <div className="projectExportControl" aria-live="polite">
      <button className="secondary" disabled={state === "pending"} onClick={start} type="button">
        {state === "pending" ? "正在准备导出..." : "下载当前 Campaign 数据"}
      </button>
      {state === "failed" ? <span role="alert">{detail}</span> : null}
    </div>
  );
}
