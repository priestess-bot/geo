"use client";

import { useEffect, useState } from "react";

import { parseAuthError, type AuthErrorEnvelope } from "./contracts";

export function SessionDeliveryConfirm({ active }: { active: boolean }) {
  const [error, setError] = useState<AuthErrorEnvelope | null>(null);
  const [confirmed, setConfirmed] = useState(false);

  useEffect(() => {
    if (!active) {
      return;
    }
    const controller = new AbortController();
    void fetch("/api/auth/session-confirm", {
      method: "POST",
      cache: "no-store",
      signal: controller.signal
    }).then(async (response) => {
      const payload = await response.json().catch(() => undefined) as unknown;
      if (response.status === 202) {
        return;
      }
      if (!response.ok) {
        setError(parseAuthError(payload, "auth_request_failed", "会话确认失败，请刷新页面重试。"));
        return;
      }
      setConfirmed(true);
    }).catch((reason: unknown) => {
      if (!(reason instanceof DOMException && reason.name === "AbortError")) {
        setError({
          code: "auth_upstream_unavailable",
          detail: "会话确认暂时不可用，请刷新页面重试。",
          correlation_id: ""
        });
      }
    });
    return () => controller.abort();
  }, [active]);

  return (
    <div aria-live="polite">
      {error ? (
        <div
          className="notice error"
          role="alert"
          style={{ border: "1px solid #f1c1b8", borderRadius: 8, marginBottom: 16, padding: 14 }}
        >
          <p>{error.detail}</p>
          <p className="muted">错误代码：{error.code}</p>
          {error.correlation_id ? <p className="muted">关联 ID：{error.correlation_id}</p> : null}
        </div>
      ) : null}
      {confirmed ? (
        <span style={{ height: 1, left: -10000, overflow: "hidden", position: "absolute", width: 1 }}>
          会话已确认
        </span>
      ) : null}
    </div>
  );
}
