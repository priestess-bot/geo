"use client";

import { useRef, useState, type FormEvent } from "react";

import {
  parseAuthError,
  type AuthErrorEnvelope,
  type InvitationSurface,
  type RedeemPrepareResponse
} from "@geo/types/auth";

type InvitationFormBody = {
  invitation_id: string;
  invite_token: string;
};

function recommendedPortalHref(base: string, invitationId: string): string {
  const absolute = /^https?:\/\//i.test(base);
  const url = new URL(base, "http://geo.local");
  url.searchParams.delete("invite_token");
  url.searchParams.set("invitation_id", invitationId.trim());
  return absolute ? url.toString() : `${url.pathname}${url.search}${url.hash}`;
}

export function InvitationLoginForm({
  initialInvitationId = "",
  landingPath,
  recommendedSurfaceUrls,
  surface
}: {
  initialInvitationId?: string;
  landingPath: "/" | "/projects";
  recommendedSurfaceUrls: Record<InvitationSurface, string>;
  surface: InvitationSurface;
}) {
  const [invitationId, setInvitationId] = useState(initialInvitationId);
  const [inviteToken, setInviteToken] = useState("");
  const [error, setError] = useState<AuthErrorEnvelope | null>(null);
  const [busy, setBusy] = useState(false);
  const preparedBody = useRef<InvitationFormBody | null>(null);

  async function prepare(body: InvitationFormBody): Promise<boolean> {
    let response: Response;
    try {
      response = await fetch("/api/auth/redeem-prepare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        cache: "no-store"
      });
    } catch {
      setError({
        code: "auth_upstream_unavailable",
        detail: "登录服务暂时不可用，请稍后重试。",
        correlation_id: ""
      });
      return false;
    }
    const payload = await response.json().catch(() => undefined) as unknown;
    if (!response.ok) {
      setError(parseAuthError(payload, "auth_request_failed", "邀请校验失败。"));
      return false;
    }
    const prepared = payload as Partial<RedeemPrepareResponse>;
    if (!prepared.prepared || prepared.requested_surface !== surface) {
      setError({
        code: "auth_request_failed",
        detail: "登录服务返回了无效的准备结果。",
        correlation_id: ""
      });
      return false;
    }
    preparedBody.current = body;
    return true;
  }

  async function redeem(body: InvitationFormBody, allowPrepareRetry: boolean): Promise<void> {
    let response: Response;
    try {
      response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        cache: "no-store",
        redirect: "manual"
      });
    } catch {
      setError({
        code: "auth_upstream_unavailable",
        detail: "登录结果尚未确认。请重试，系统会恢复同一个会话。",
        correlation_id: ""
      });
      return;
    }
    if (response.type === "opaqueredirect" || response.status === 303 || response.redirected) {
      window.location.assign(landingPath);
      return;
    }
    const payload = await response.json().catch(() => undefined) as unknown;
    if (response.status === 428 && allowPrepareRetry) {
      preparedBody.current = null;
      if (await prepare(body)) {
        await redeem(body, false);
      }
      return;
    }
    if (!response.ok) {
      setError(parseAuthError(payload, "auth_request_failed", "邀请兑换失败。"));
      return;
    }
    window.location.assign(landingPath);
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) {
      return;
    }
    const body = { invitation_id: invitationId.trim(), invite_token: inviteToken.trim() };
    if (!body.invitation_id || !body.invite_token) {
      setError({
        code: "auth_invalid_request",
        detail: "请同时填写邀请 ID 和一次性邀请 token。",
        correlation_id: ""
      });
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const alreadyPrepared = preparedBody.current?.invitation_id === body.invitation_id
        && preparedBody.current?.invite_token === body.invite_token;
      if ((alreadyPrepared || await prepare(body))) {
        await redeem(body, true);
      }
    } finally {
      setBusy(false);
    }
  }

  function resetPrepared() {
    preparedBody.current = null;
    setError(null);
  }

  const recommendedSurface = error?.recommended_surface;
  return (
    <form className={surface === "admin" ? "configForm singleColumn" : "tokenForm"} onSubmit={onSubmit}>
      <label>
        <span>邀请 ID</span>
        <input
          name="invitation_id"
          value={invitationId}
          onChange={(event) => { resetPrepared(); setInvitationId(event.target.value); }}
          autoComplete="off"
          required
        />
      </label>
      <label>
        <span>一次性邀请 token</span>
        <input
          name="invite_token"
          value={inviteToken}
          onChange={(event) => { resetPrepared(); setInviteToken(event.target.value); }}
          type="password"
          autoComplete="one-time-code"
          required
        />
      </label>
      <div className={surface === "admin" ? "formActions" : undefined}>
        <button type="submit" disabled={busy} aria-busy={busy} style={{ minWidth: 156 }}>
          {busy ? "正在登录..." : "兑换邀请并登录"}
        </button>
      </div>
      <div
        aria-live="polite"
        className={error ? "notice error" : undefined}
        role={error ? "alert" : undefined}
        style={error ? {
          border: "1px solid #f1c1b8",
          borderRadius: 8,
          gridColumn: "1 / -1",
          marginTop: 4,
          padding: 14
        } : undefined}
      >
        {error ? (
          <>
            <p>{error.detail}</p>
            <p className="muted">错误代码：{error.code}</p>
            {error.correlation_id ? <p className="muted">关联 ID：{error.correlation_id}</p> : null}
            {recommendedSurface ? (
              <a
                className="button secondary"
                href={recommendedPortalHref(recommendedSurfaceUrls[recommendedSurface], invitationId)}
              >
                前往{recommendedSurface === "admin" ? "管理台" : "客户门户"}
              </a>
            ) : null}
          </>
        ) : null}
      </div>
    </form>
  );
}
