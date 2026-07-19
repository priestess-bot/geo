"use client";

import { useState } from "react";

import styles from "./GeoWorkspace.module.css";

type ExportState = "idle" | "requesting" | "waiting" | "failed";

export function ProjectExportButtons({
  campaignId,
  projectId
}: Readonly<{ campaignId?: string; projectId: string }>) {
  const [state, setState] = useState<ExportState>("idle");
  const [detail, setDetail] = useState("");

  async function start(scopeCampaignId: string | null) {
    setState("requesting");
    setDetail("");
    const response = await fetch(`/projects/${encodeURIComponent(projectId)}/project-export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ campaign_id: scopeCampaignId })
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || typeof payload.job_id !== "string") {
      setState("failed");
      setDetail(typeof payload.detail === "string" ? payload.detail : "导出任务创建失败");
      return;
    }
    setState("waiting");
    await downloadWhenReady(payload.job_id);
  }

  async function downloadWhenReady(jobId: string) {
    for (let attempt = 0; attempt < 120; attempt += 1) {
      const response = await fetch(
        `/projects/${encodeURIComponent(projectId)}/project-export?job_id=${encodeURIComponent(jobId)}`,
        { cache: "no-store" }
      );
      if (response.ok) {
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = `geo-project-export-${jobId}.zip`;
        anchor.click();
        URL.revokeObjectURL(url);
        setState("idle");
        return;
      }
      if (response.status !== 409) {
        const payload = await response.json().catch(() => ({}));
        setState("failed");
        setDetail(typeof payload.detail === "string" ? payload.detail : "导出下载失败");
        return;
      }
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
    }
    setState("failed");
    setDetail("导出任务仍在处理中，请稍后重试");
  }

  const pending = state === "requesting" || state === "waiting";
  return (
    <div className={styles.exportToolbar} aria-live="polite">
      <button disabled={pending} onClick={() => start(null)} type="button">
        {pending ? "正在准备导出..." : "导出整个项目"}
      </button>
      {campaignId ? (
        <button disabled={pending} onClick={() => start(campaignId)} type="button">
          导出当前 Campaign
        </button>
      ) : null}
      {state === "failed" ? <span role="alert">{detail}</span> : null}
    </div>
  );
}
