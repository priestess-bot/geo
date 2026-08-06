"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import type { JobState } from "@geo/types/geo";

const TERMINAL_STATES = new Set<JobState>([
  "succeeded",
  "failed",
  "dead_lettered",
  "cancelled"
]);
const REFRESH_INTERVAL_MS = 4_000;
const AUTO_REFRESH_LIMIT_MS = 5 * 60 * 1_000;

export function QuestionJobWatcher({ status }: { status: JobState }) {
  const router = useRouter();
  const startedAt = useRef(Date.now());
  const [timedOut, setTimedOut] = useState(false);
  const terminal = TERMINAL_STATES.has(status);

  useEffect(() => {
    if (terminal || timedOut) return;
    const timer = window.setInterval(() => {
      if (Date.now() - startedAt.current >= AUTO_REFRESH_LIMIT_MS) {
        setTimedOut(true);
        return;
      }
      if (document.visibilityState === "visible") router.refresh();
    }, REFRESH_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [router, status, terminal, timedOut]);

  if (terminal) return null;
  return <div role="status">
    <span>{timedOut ? "自动刷新已暂停" : "任务运行中，页面会自动更新"}</span>
    <button type="button" onClick={() => router.refresh()}>刷新状态</button>
  </div>;
}
